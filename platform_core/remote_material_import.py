"""Portable review-bundle contract for Agent MATERIAL_IMPORT.

The Agent may inspect and unpack bytes but never opens central SQLite or receives
storage credentials.  It publishes one immutable review ZIP.  The control plane
verifies that ZIP, imports candidate truth into the task-owned ImportCandidateStore,
and later the local indexer streams only user-confirmed members to the target
object store.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from .storage.detection_import import (
    DetectionDatasetScanner,
    DetectionImportError,
    DetectionScanCancelled,
)
from .storage.import_candidates import ImportCandidateStore
from .storage.local import LocalStorageProvider
from .storage.import_confirmation import external_label_facts
from .storage.yolo_import import YoloImportError, YoloImportScanner, YoloScanCancelled
from .storage.import_tasks import MANIFEST_REF, SCAN_RESULT_REF, IMAGE_EXTENSIONS
from .storage.zip_import import (
    ServerZipImportError,
    extract_server_zip,
    finalize_server_zip_publication,
    safe_member_path,
)


REVIEW_SCHEMA_VERSION = 1
REVIEW_META_MEMBER = "meta.json"
REVIEW_ROWS_MEMBER = "review.jsonl"
REVIEW_ANNOTATIONS_MEMBER = "yolo/annotations.jsonl"
REVIEW_DETECTION_ANNOTATIONS_MEMBER = "annotations/detection.jsonl"
REVIEW_FILES_PREFIX = PurePosixPath("files")
REMOTE_MATERIAL_STAGING_REF = "remote-material/staged.sqlite3"
_MAX_REVIEW_ROWS = 250_000


class RemoteMaterialImportError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        self.code = str(code)
        self.status_code = int(status_code)
        super().__init__(str(message))


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _target_key(prefix: str, relative: PurePosixPath) -> str:
    clean_prefix = safe_member_path(prefix)
    joined = PurePosixPath(*clean_prefix.parts, *relative.parts)
    return joined.as_posix()


def _plain_file(root: Path, relative: PurePosixPath) -> Path:
    candidate = root.joinpath(*relative.parts)
    if candidate.is_symlink():
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_LINK_FORBIDDEN",
            "material review source contains a symbolic link",
            422,
        )
    try:
        resolved = candidate.resolve()
        resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as error:
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_PATH_UNSAFE",
            "material review source escaped its work directory",
            422,
        ) from error
    if not resolved.is_file():
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_FILE_INVALID",
            "material review source is not a regular file",
            422,
        )
    return resolved


def build_material_review_archive(
    source_root: str | Path,
    destination: str | Path,
    *,
    task_id: str,
    project_id: str,
    execution_generation: int,
    storage_source_id: str,
    storage_type: str,
    target_prefix: str,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], object] | None = None,
) -> dict[str, Any]:
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_SOURCE_INVALID",
            "extracted material review root is unavailable",
            409,
        )
    safe_member_path(target_prefix)
    members = sorted(
        (
            PurePosixPath(*path.relative_to(root).parts)
            for path in root.rglob("*")
            if path.is_file() and not path.name.startswith(".mc-import-owner")
        ),
        key=lambda item: item.as_posix(),
    )
    if len(members) > _MAX_REVIEW_ROWS:
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_MEMBER_LIMIT",
            "material review contains too many files",
            413,
        )

    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    rows_descriptor, rows_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.rows.",
        suffix=".jsonl",
    )
    os.close(rows_descriptor)
    rows_file = Path(rows_name)
    counts: dict[str, int] = {}
    seen_hashes: set[str] = set()
    payloads: list[tuple[Path, str]] = []
    try:
        with rows_file.open("wb") as rows_stream:
            for index, relative in enumerate(members, start=1):
                if cancelled is not None and cancelled():
                    raise InterruptedError("material review cancelled")
                relative = safe_member_path(relative.as_posix())
                source = _plain_file(root, relative)
                suffix = source.suffix.lower()
                row: dict[str, Any] = {
                    "object_key": _target_key(target_prefix, relative),
                    "filename": source.name,
                    "storage_source_id": str(storage_source_id),
                    "storage_type": str(storage_type),
                    "content_sha256": "",
                    "size_bytes": int(source.stat().st_size),
                    "etag": "",
                    "width": 0,
                    "height": 0,
                    "status": "SKIPPED",
                    "error": "",
                    "duplicate": False,
                    "payload_member": "",
                }
                if suffix in IMAGE_EXTENSIONS:
                    try:
                        with Image.open(source) as image:
                            width, height = image.size
                            image.verify()
                        digest = _sha256_file(source)
                        duplicate = digest in seen_hashes
                        row.update({
                            "content_sha256": digest,
                            "width": int(width),
                            "height": int(height),
                            "status": "DUPLICATE" if duplicate else "IMPORTABLE",
                            "duplicate": duplicate,
                        })
                        if not duplicate:
                            payload_member = (
                                REVIEW_FILES_PREFIX
                                / PurePosixPath(*relative.parts)
                            ).as_posix()
                            row["payload_member"] = payload_member
                            payloads.append((source, payload_member))
                        seen_hashes.add(digest)
                    except (UnidentifiedImageError, OSError, ValueError):
                        row.update({
                            "status": "INVALID",
                            "error": "IMAGE_DECODE_FAILED",
                        })
                counts[row["status"]] = counts.get(row["status"], 0) + 1
                rows_stream.write(
                    json.dumps(
                        row,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("utf-8")
                    + b"\n"
                )
                if progress is not None and (
                    index == 1
                    or index == len(members)
                    or index % max(1, len(members) // 100) == 0
                ):
                    progress(index, len(members), relative.as_posix())
            rows_stream.flush()
            os.fsync(rows_stream.fileno())

        if cancelled is not None and cancelled():
            raise InterruptedError("material review cancelled")
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as archive:
            archive.write(rows_file, arcname=REVIEW_ROWS_MEMBER)
            for source, payload_member in payloads:
                if cancelled is not None and cancelled():
                    raise InterruptedError("material review cancelled")
                archive.write(source, arcname=payload_member)
            meta = {
                "schema_version": REVIEW_SCHEMA_VERSION,
                "task_id": str(task_id),
                "project_id": str(project_id),
                "execution_generation": int(execution_generation),
                "mode": "zip_scan",
                "import_format": "images",
                "storage_source_id": str(storage_source_id),
                "storage_type": str(storage_type),
                "target_prefix": safe_member_path(target_prefix).as_posix(),
                "candidate_count": len(members),
                "counts": counts,
            }
            archive.writestr(
                REVIEW_META_MEMBER,
                json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            )
        if temporary.stat().st_size <= 0:
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_REVIEW_EMPTY",
                "material review archive is empty",
                409,
            )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)
        rows_file.unlink(missing_ok=True)

    return {
        "path": target,
        "sha256": _sha256_file(target),
        "size_bytes": int(target.stat().st_size),
        "candidate_count": len(members),
        "counts": counts,
    }


def _inspect_local_image(
    provider: LocalStorageProvider,
    item,
    *,
    storage_source_id: str,
    storage_type: str,
    seen_hashes: set[str],
) -> dict[str, Any]:
    key = str(item.key)
    row = {
        "object_key": key,
        "filename": Path(key).name,
        "storage_source_id": str(storage_source_id),
        "storage_type": str(storage_type),
        "content_sha256": "",
        "size_bytes": max(0, int(item.size_bytes or 0)),
        "etag": str(item.etag or ""),
        "width": 0,
        "height": 0,
        "status": "INVALID",
        "error": "",
        "duplicate": False,
    }
    try:
        with provider.open_reader(key) as stream:
            with Image.open(stream) as image:
                width, height = image.size
                image.verify()
        digest = str(item.sha256 or "").strip().lower()
        if len(digest) != 64 or any(char not in "0123456789abcdef" for char in digest):
            digest = _sha256_file(provider._path(key))
        if row["size_bytes"] <= 0:
            raise ValueError("image is empty")
        duplicate = digest in seen_hashes
        seen_hashes.add(digest)
        row.update({
            "content_sha256": digest,
            "width": int(width),
            "height": int(height),
            "status": "DUPLICATE" if duplicate else "IMPORTABLE",
            "duplicate": duplicate,
        })
    except (UnidentifiedImageError, OSError, ValueError):
        row.update({"status": "INVALID", "error": "IMAGE_DECODE_FAILED"})
    return row



def _inspect_storage_scan_image(
    provider,
    item,
    *,
    storage_source_id: str,
    storage_type: str,
    seen_hashes: set[str],
    deduplicate: bool = True,
) -> dict[str, Any]:
    key = safe_member_path(str(item.key)).as_posix()
    row = {
        "object_key": key,
        "filename": Path(key).name,
        "storage_source_id": str(storage_source_id),
        "storage_type": str(storage_type),
        "content_sha256": "",
        "size_bytes": max(0, int(item.size_bytes or 0)),
        "etag": str(item.etag or ""),
        "width": 0,
        "height": 0,
        "status": "INVALID",
        "error": "",
        "duplicate": False,
        "payload_member": "",
    }
    if row["size_bytes"] <= 0 or not row["etag"]:
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_SOURCE_EVIDENCE_MISSING",
            "storage_scan image is missing size/ETag evidence",
            409,
        )
    try:
        with closing(provider.open_reader(key)) as stream:
            with Image.open(stream) as image:
                width, height = image.size
                image.verify()
            stream.seek(0)
            digest = hashlib.sha256()
            size = 0
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                size += len(chunk)
                digest.update(chunk)
        actual_sha = digest.hexdigest()
        if size != row["size_bytes"]:
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_SOURCE_CHANGED",
                "storage_scan image size changed while it was reviewed",
                409,
            )
        listed_sha = str(item.sha256 or "").strip().lower()
        if listed_sha and listed_sha != actual_sha:
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_SOURCE_CHANGED",
                "storage_scan image hash changed while it was reviewed",
                409,
            )
        duplicate = bool(deduplicate and actual_sha in seen_hashes)
        seen_hashes.add(actual_sha)
        row.update({
            "content_sha256": actual_sha,
            "width": int(width),
            "height": int(height),
            "status": "DUPLICATE" if duplicate else "IMPORTABLE",
            "duplicate": duplicate,
        })
    except RemoteMaterialImportError:
        raise
    except (UnidentifiedImageError, OSError, ValueError):
        row.update({"status": "INVALID", "error": "IMAGE_DECODE_FAILED"})
    return row


def build_yolo_material_review_archive(
    source_root: str | Path,
    destination: str | Path,
    *,
    task_id: str,
    project_id: str,
    execution_generation: int,
    storage_source_id: str,
    storage_type: str,
    target_prefix: str,
    dataset_yaml: str = "",
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], object] | None = None,
) -> dict[str, Any]:
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_SOURCE_INVALID",
            "extracted YOLO material root is unavailable",
            409,
        )
    target_prefix = safe_member_path(target_prefix).as_posix()
    yaml_member = (
        safe_member_path(dataset_yaml).as_posix()
        if str(dataset_yaml or "").strip()
        else ""
    )
    provider = LocalStorageProvider("agent-yolo-review", root)
    review_target = Path(destination).expanduser().resolve()
    review_target.parent.mkdir(parents=True, exist_ok=True)
    local_fd, local_name = tempfile.mkstemp(
        dir=review_target.parent,
        prefix=".yolo-review.",
        suffix=".sqlite3",
    )
    os.close(local_fd)
    local_store_path = Path(local_name)
    # sqlite creates the database itself. Remove the mkstemp placeholder so
    # ImportCandidateStore owns schema creation from an empty path.
    local_store_path.unlink(missing_ok=True)
    store = ImportCandidateStore(local_store_path)
    scanner = YoloImportScanner(
        provider,
        store,
        lambda current, prefix, recursive: current.iter_objects(
            prefix, recursive=recursive
        ),
        cancelled=(cancelled or (lambda: False)),
        progress=lambda key: (
            progress(0, 0, str(key))
            if progress is not None
            else None
        ),
    )
    try:
        try:
            selected_format = scanner.prepare(
                "yolo",
                prefix="",
                recursive=True,
                dataset_yaml=yaml_member or None,
            )
        except YoloScanCancelled as error:
            raise InterruptedError("YOLO review cancelled") from error
        except YoloImportError as error:
            raise RemoteMaterialImportError(error.code, error.message, 422) from error
        if selected_format != "yolo":
            raise RemoteMaterialImportError(
                "REMOTE_YOLO_DISCOVERY_FAILED",
                "YOLO review did not resolve a YOLO dataset",
                422,
            )

        seen_hashes: set[str] = set()
        batch: list[dict[str, Any]] = []
        inspected = 0
        for item in scanner.iter_images():
            if cancelled is not None and cancelled():
                raise InterruptedError("YOLO review cancelled")
            batch.append(_inspect_local_image(
                provider,
                item,
                storage_source_id=storage_source_id,
                storage_type=storage_type,
                seen_hashes=seen_hashes,
            ))
            inspected += 1
            if len(batch) >= 500:
                store.upsert_many(batch)
                batch.clear()
            if progress is not None and (inspected == 1 or inspected % 100 == 0):
                progress(inspected, 0, str(item.key))
        if batch:
            store.upsert_many(batch)
        try:
            quality = scanner.scan_annotations()
        except YoloScanCancelled as error:
            raise InterruptedError("YOLO annotation review cancelled") from error
        except YoloImportError as error:
            raise RemoteMaterialImportError(error.code, error.message, 422) from error

        target = Path(destination).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        archive_fd, archive_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        os.close(archive_fd)
        temporary = Path(archive_name)
        rows_fd, rows_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.rows.",
            suffix=".jsonl",
        )
        os.close(rows_fd)
        rows_file = Path(rows_name)
        ann_fd, ann_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.annotations.",
            suffix=".jsonl",
        )
        os.close(ann_fd)
        annotations_file = Path(ann_name)
        payloads: list[tuple[Path, str]] = []
        counts: dict[str, int] = {}
        total = sum(store.counts().values())
        completed = 0
        try:
            with rows_file.open("wb") as rows_stream, annotations_file.open("wb") as ann_stream:
                page: list[dict[str, Any]] = []
                for candidate in store.iter_candidates(batch_size=500):
                    page.append(candidate)
                    if len(page) < 500:
                        continue
                    _write_yolo_review_page(
                        root,
                        store,
                        page,
                        rows_stream,
                        ann_stream,
                        payloads,
                        counts,
                        target_prefix,
                    )
                    completed += len(page)
                    if progress is not None:
                        progress(completed, total, str(page[-1]["object_key"]))
                    page.clear()
                    if cancelled is not None and cancelled():
                        raise InterruptedError("YOLO review cancelled")
                if page:
                    _write_yolo_review_page(
                        root,
                        store,
                        page,
                        rows_stream,
                        ann_stream,
                        payloads,
                        counts,
                        target_prefix,
                    )
                    completed += len(page)
                    if progress is not None:
                        progress(completed, total, str(page[-1]["object_key"]))
                rows_stream.flush()
                os.fsync(rows_stream.fileno())
                ann_stream.flush()
                os.fsync(ann_stream.fileno())

            classes = store.label_mapping_rows()
            meta = {
                "schema_version": REVIEW_SCHEMA_VERSION,
                "task_id": str(task_id),
                "project_id": str(project_id),
                "execution_generation": int(execution_generation),
                "mode": "zip_scan",
                "import_format": "yolo",
                "storage_source_id": str(storage_source_id),
                "storage_type": str(storage_type),
                "target_prefix": target_prefix,
                "candidate_count": total,
                "counts": counts,
                "dataset_yaml": str(scanner.yaml_key or ""),
                "classes": [
                    {
                        "class_id": int(row["class_id"]),
                        "name": str(row["name"]),
                    }
                    for row in classes
                ],
                "quality": quality,
            }
            if cancelled is not None and cancelled():
                raise InterruptedError("YOLO review cancelled")
            with zipfile.ZipFile(
                temporary,
                "w",
                compression=zipfile.ZIP_STORED,
                allowZip64=True,
            ) as archive:
                archive.write(rows_file, arcname=REVIEW_ROWS_MEMBER)
                archive.write(annotations_file, arcname=REVIEW_ANNOTATIONS_MEMBER)
                for source, member in payloads:
                    if cancelled is not None and cancelled():
                        raise InterruptedError("YOLO review cancelled")
                    archive.write(source, arcname=member)
                archive.writestr(
                    REVIEW_META_MEMBER,
                    json.dumps(
                        meta,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            if temporary.stat().st_size <= 0:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_REVIEW_EMPTY",
                    "YOLO review archive is empty",
                    409,
                )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
            rows_file.unlink(missing_ok=True)
            annotations_file.unlink(missing_ok=True)

        return {
            "path": target,
            "sha256": _sha256_file(target),
            "size_bytes": int(target.stat().st_size),
            "candidate_count": total,
            "counts": counts,
            "dataset_yaml": str(scanner.yaml_key or ""),
            "quality": quality,
            "classes": [
                {"class_id": int(row["class_id"]), "name": str(row["name"])}
                for row in store.label_mapping_rows()
            ],
        }
    finally:
        local_store_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(local_store_path) + suffix).unlink(missing_ok=True)




def build_detection_material_review_archive(
    source_root: str | Path,
    destination: str | Path,
    *,
    task_id: str,
    project_id: str,
    execution_generation: int,
    storage_source_id: str,
    storage_type: str,
    target_prefix: str,
    import_format: str,
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], object] | None = None,
) -> dict[str, Any]:
    root = Path(source_root).expanduser().resolve()
    if not root.is_dir() or root.is_symlink():
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_SOURCE_INVALID",
            "extracted detection material root is unavailable",
            409,
        )
    selected_format = str(import_format or "").strip().lower()
    if selected_format not in {"coco", "voc"}:
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_FORMAT_UNSUPPORTED",
            "detection ZIP review supports coco or voc",
            422,
        )
    target_prefix = safe_member_path(str(target_prefix)).as_posix()
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    provider = LocalStorageProvider("agent-detection-review", root)

    local_fd, local_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=".detection-zip-review.",
        suffix=".sqlite3",
    )
    os.close(local_fd)
    local_store_path = Path(local_name)
    local_store_path.unlink(missing_ok=True)
    store = ImportCandidateStore(local_store_path)
    scanner = DetectionDatasetScanner(
        provider,
        store,
        lambda current, scan_prefix, scan_recursive: current.iter_objects(
            scan_prefix, recursive=scan_recursive
        ),
        _inspect_local_image,
        storage_source_id=storage_source_id,
        storage_type=storage_type,
        cancelled=(cancelled or (lambda: False)),
        progress=lambda key: (
            progress(0, 0, str(key)) if progress is not None else None
        ),
    )
    try:
        try:
            detected = scanner.scan(
                selected_format,
                prefix="",
                recursive=True,
            )
        except DetectionScanCancelled as error:
            raise InterruptedError("detection ZIP review cancelled") from error
        except DetectionImportError as error:
            raise RemoteMaterialImportError(
                str(getattr(error, "code", "REMOTE_DETECTION_REVIEW_INVALID")),
                str(getattr(error, "message", error)),
                422,
            ) from error

        counts = store.counts()
        total = sum(counts.values())
        if total <= 0:
            raise RemoteMaterialImportError(
                "REMOTE_DETECTION_IMAGES_MISSING",
                "detection dataset contains no reviewable images",
                422,
            )

        archive_fd, archive_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        os.close(archive_fd)
        temporary = Path(archive_name)
        rows_fd, rows_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.rows.",
            suffix=".jsonl",
        )
        os.close(rows_fd)
        rows_file = Path(rows_name)
        ann_fd, ann_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.annotations.",
            suffix=".jsonl",
        )
        os.close(ann_fd)
        annotations_file = Path(ann_name)
        payloads: list[tuple[Path, str]] = []
        written_counts: dict[str, int] = {}
        completed = 0
        try:
            with rows_file.open("wb") as rows_stream, annotations_file.open("wb") as ann_stream:
                page: list[dict[str, Any]] = []
                for candidate in store.iter_candidates(batch_size=500):
                    page.append(candidate)
                    if len(page) < 500:
                        continue
                    _write_yolo_review_page(
                        root,
                        store,
                        page,
                        rows_stream,
                        ann_stream,
                        payloads,
                        written_counts,
                        target_prefix,
                        include_payloads=True,
                        preserve_object_keys=False,
                    )
                    completed += len(page)
                    if progress is not None:
                        progress(completed, total, str(page[-1]["object_key"]))
                    page.clear()
                    if cancelled is not None and cancelled():
                        raise InterruptedError("detection ZIP review cancelled")
                if page:
                    _write_yolo_review_page(
                        root,
                        store,
                        page,
                        rows_stream,
                        ann_stream,
                        payloads,
                        written_counts,
                        target_prefix,
                        include_payloads=True,
                        preserve_object_keys=False,
                    )
                    completed += len(page)
                    if progress is not None:
                        progress(completed, total, str(page[-1]["object_key"]))
                rows_stream.flush()
                os.fsync(rows_stream.fileno())
                ann_stream.flush()
                os.fsync(ann_stream.fileno())

            meta = {
                "schema_version": REVIEW_SCHEMA_VERSION,
                "task_id": str(task_id),
                "project_id": str(project_id),
                "execution_generation": int(execution_generation),
                "mode": "zip_scan",
                "payload_mode": "embedded",
                "import_format": str(detected.import_format),
                "storage_source_id": str(storage_source_id),
                "storage_type": str(storage_type),
                "target_prefix": target_prefix,
                "candidate_count": total,
                "counts": written_counts,
                "annotation_member": REVIEW_DETECTION_ANNOTATIONS_MEMBER,
                "classes": [
                    {"class_id": int(class_id), "name": str(name)}
                    for class_id, name in detected.classes
                ],
                "quality": detected.quality,
                "annotation_files": int(detected.annotation_files),
                "missing_images": int(detected.missing_images),
            }
            if cancelled is not None and cancelled():
                raise InterruptedError("detection ZIP review cancelled")
            with zipfile.ZipFile(
                temporary,
                "w",
                compression=zipfile.ZIP_STORED,
                allowZip64=True,
            ) as archive:
                archive.write(rows_file, arcname=REVIEW_ROWS_MEMBER)
                archive.write(
                    annotations_file,
                    arcname=REVIEW_DETECTION_ANNOTATIONS_MEMBER,
                )
                for source, member in payloads:
                    if cancelled is not None and cancelled():
                        raise InterruptedError("detection ZIP review cancelled")
                    archive.write(source, arcname=member)
                archive.writestr(
                    REVIEW_META_MEMBER,
                    json.dumps(
                        meta,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            if temporary.stat().st_size <= 0:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_REVIEW_EMPTY",
                    "detection review archive is empty",
                    409,
                )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
            rows_file.unlink(missing_ok=True)
            annotations_file.unlink(missing_ok=True)

        return {
            "path": target,
            "sha256": _sha256_file(target),
            "size_bytes": int(target.stat().st_size),
            "candidate_count": total,
            "counts": written_counts,
            "quality": detected.quality,
            "classes": [
                {"class_id": int(class_id), "name": str(name)}
                for class_id, name in detected.classes
            ],
        }
    finally:
        local_store_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(local_store_path) + suffix).unlink(missing_ok=True)


def _build_detection_storage_scan_review_archive(
    provider,
    destination: str | Path,
    *,
    task_id: str,
    project_id: str,
    execution_generation: int,
    storage_source_id: str,
    storage_type: str,
    prefix: str,
    recursive: bool,
    import_format: str,
    intent: str = "",
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], object] | None = None,
) -> dict[str, Any]:
    normalized_intent = str(intent or "").strip().lower()
    if normalized_intent not in {"", "storage_rescan"}:
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_INTENT_INVALID",
            "unsupported detection review intent",
            422,
        )
    raw_prefix = str(prefix or "").strip().replace("\\", "/").strip("/")
    target_prefix = safe_member_path(raw_prefix).as_posix() if raw_prefix else ""
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    local_fd, local_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=".detection-review.",
        suffix=".sqlite3",
    )
    os.close(local_fd)
    local_store_path = Path(local_name)
    local_store_path.unlink(missing_ok=True)
    store = ImportCandidateStore(local_store_path)
    scanner = DetectionDatasetScanner(
        provider,
        store,
        lambda current, scan_prefix, scan_recursive: current.iter_objects(
            scan_prefix, recursive=scan_recursive
        ),
        (
            lambda current, item, **kwargs: _inspect_storage_scan_image(
                current,
                item,
                **kwargs,
                deduplicate=normalized_intent != "storage_rescan",
            )
        ),
        storage_source_id=storage_source_id,
        storage_type=storage_type,
        cancelled=(cancelled or (lambda: False)),
        progress=lambda key: (
            progress(0, 0, str(key)) if progress is not None else None
        ),
        deduplicate_images=normalized_intent != "storage_rescan",
    )
    try:
        try:
            detected = scanner.scan(
                import_format,
                prefix=target_prefix,
                recursive=bool(recursive),
            )
        except DetectionScanCancelled as error:
            raise InterruptedError("detection review cancelled") from error
        except DetectionImportError as error:
            raise RemoteMaterialImportError(
                str(getattr(error, "code", "REMOTE_DETECTION_REVIEW_INVALID")),
                str(getattr(error, "message", error)),
                422,
            ) from error

        if normalized_intent == "storage_rescan":
            scanner.ensure_all_image_candidates()
        counts = store.counts()
        total = sum(counts.values())
        if total <= 0:
            raise RemoteMaterialImportError(
                "REMOTE_DETECTION_IMAGES_MISSING",
                "detection dataset contains no reviewable images",
                422,
            )
        archive_fd, archive_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.",
            suffix=".tmp",
        )
        os.close(archive_fd)
        temporary = Path(archive_name)
        rows_fd, rows_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.rows.",
            suffix=".jsonl",
        )
        os.close(rows_fd)
        rows_file = Path(rows_name)
        ann_fd, ann_name = tempfile.mkstemp(
            dir=target.parent,
            prefix=f".{target.name}.annotations.",
            suffix=".jsonl",
        )
        os.close(ann_fd)
        annotations_file = Path(ann_name)
        written_counts: dict[str, int] = {}
        completed = 0
        try:
            with rows_file.open("wb") as rows_stream, annotations_file.open("wb") as ann_stream:
                page: list[dict[str, Any]] = []
                for candidate in store.iter_candidates(batch_size=500):
                    page.append(candidate)
                    if len(page) < 500:
                        continue
                    _write_yolo_review_page(
                        None,
                        store,
                        page,
                        rows_stream,
                        ann_stream,
                        [],
                        written_counts,
                        target_prefix,
                        include_payloads=False,
                        preserve_object_keys=True,
                        skip_unmanifested_annotations=normalized_intent == "storage_rescan",
                    )
                    completed += len(page)
                    if progress is not None:
                        progress(completed, total, str(page[-1]["object_key"]))
                    page.clear()
                    if cancelled is not None and cancelled():
                        raise InterruptedError("detection review cancelled")
                if page:
                    _write_yolo_review_page(
                        None,
                        store,
                        page,
                        rows_stream,
                        ann_stream,
                        [],
                        written_counts,
                        target_prefix,
                        include_payloads=False,
                        preserve_object_keys=True,
                        skip_unmanifested_annotations=normalized_intent == "storage_rescan",
                    )
                    completed += len(page)
                    if progress is not None:
                        progress(completed, total, str(page[-1]["object_key"]))
                rows_stream.flush()
                os.fsync(rows_stream.fileno())
                ann_stream.flush()
                os.fsync(ann_stream.fileno())

            meta = {
                "schema_version": REVIEW_SCHEMA_VERSION,
                "task_id": str(task_id),
                "project_id": str(project_id),
                "execution_generation": int(execution_generation),
                "mode": "storage_scan",
                "intent": normalized_intent,
                "payload_mode": "source_reference",
                "import_format": str(detected.import_format),
                "storage_source_id": str(storage_source_id),
                "storage_type": str(storage_type),
                "target_prefix": target_prefix,
                "candidate_count": total,
                "counts": written_counts,
                "annotation_member": REVIEW_DETECTION_ANNOTATIONS_MEMBER,
                "classes": [
                    {"class_id": int(class_id), "name": str(name)}
                    for class_id, name in detected.classes
                ],
                "quality": detected.quality,
                "annotation_files": int(detected.annotation_files),
                "missing_images": int(detected.missing_images),
            }
            with zipfile.ZipFile(
                temporary,
                "w",
                compression=zipfile.ZIP_STORED,
                allowZip64=True,
            ) as archive:
                archive.write(rows_file, arcname=REVIEW_ROWS_MEMBER)
                archive.write(
                    annotations_file,
                    arcname=REVIEW_DETECTION_ANNOTATIONS_MEMBER,
                )
                archive.writestr(
                    REVIEW_META_MEMBER,
                    json.dumps(
                        meta,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    ),
                )
            if temporary.stat().st_size <= 0:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_REVIEW_EMPTY",
                    "detection review archive is empty",
                    409,
                )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
            rows_file.unlink(missing_ok=True)
            annotations_file.unlink(missing_ok=True)

        return {
            "path": target,
            "sha256": _sha256_file(target),
            "size_bytes": int(target.stat().st_size),
            "candidate_count": total,
            "counts": written_counts,
            "quality": detected.quality,
            "classes": [
                {"class_id": int(class_id), "name": str(name)}
                for class_id, name in detected.classes
            ],
        }
    finally:
        local_store_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(local_store_path) + suffix).unlink(missing_ok=True)


def build_storage_scan_material_review_archive(
    provider,
    destination: str | Path,
    *,
    task_id: str,
    project_id: str,
    execution_generation: int,
    storage_source_id: str,
    storage_type: str,
    prefix: str,
    recursive: bool,
    import_format: str,
    dataset_yaml: str = "",
    intent: str = "",
    cancelled: Callable[[], bool] | None = None,
    progress: Callable[[int, int, str], object] | None = None,
) -> dict[str, Any]:
    """Build a metadata-only review from an execution-fenced storage broker."""
    selected_format = str(import_format or "").strip().lower()
    normalized_intent = str(intent or "").strip().lower()
    if normalized_intent not in {"", "storage_rescan"}:
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_INTENT_INVALID",
            "unsupported portable material scan intent",
            422,
        )
    raw_prefix = str(prefix or "").strip().replace("\\", "/").strip("/")
    if not raw_prefix and normalized_intent != "storage_rescan":
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_PREFIX_REQUIRED",
            "storage_scan review requires an explicit object prefix",
            422,
        )
    if normalized_intent == "storage_rescan" and selected_format not in {"images", "yolo", "coco", "voc"}:
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_RESCAN_FORMAT_UNSUPPORTED",
            "storage_rescan Phase 2C supports image, YOLO, COCO or Pascal VOC reconciliation",
            422,
        )
    target_prefix = safe_member_path(raw_prefix).as_posix() if raw_prefix else ""
    if selected_format not in {"images", "yolo", "coco", "voc"}:
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_FORMAT_UNSUPPORTED",
            "storage_scan review supports images, yolo, coco or voc",
            422,
        )
    if selected_format in {"coco", "voc"}:
        if str(dataset_yaml or "").strip():
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_DATASET_YAML_INVALID",
                "COCO/VOC storage_scan does not accept dataset_yaml",
                422,
            )
        return _build_detection_storage_scan_review_archive(
            provider,
            destination,
            task_id=task_id,
            project_id=project_id,
            execution_generation=execution_generation,
            storage_source_id=storage_source_id,
            storage_type=storage_type,
            prefix=target_prefix,
            recursive=recursive,
            import_format=selected_format,
            intent=normalized_intent,
            cancelled=cancelled,
            progress=progress,
        )
    yaml_key = (
        safe_member_path(str(dataset_yaml)).as_posix()
        if str(dataset_yaml or "").strip()
        else ""
    )
    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)

    if selected_format == "images":
        archive_fd, archive_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp",
        )
        os.close(archive_fd)
        temporary = Path(archive_name)
        rows_fd, rows_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.rows.", suffix=".jsonl",
        )
        os.close(rows_fd)
        rows_file = Path(rows_name)
        counts: dict[str, int] = {}
        seen_hashes: set[str] = set()
        candidate_count = 0
        prefix_path = safe_member_path(target_prefix) if target_prefix else PurePosixPath()
        try:
            with rows_file.open("wb") as rows_stream:
                for item in provider.iter_objects(target_prefix, recursive=bool(recursive)):
                    if cancelled is not None and cancelled():
                        raise InterruptedError("storage_scan review cancelled")
                    candidate_count += 1
                    if candidate_count > _MAX_REVIEW_ROWS:
                        raise RemoteMaterialImportError(
                            "REMOTE_MATERIAL_MEMBER_LIMIT",
                            "storage_scan contains too many objects",
                            413,
                        )
                    key = safe_member_path(str(item.key)).as_posix()
                    key_path = safe_member_path(key)
                    if key_path.parts[: len(prefix_path.parts)] != prefix_path.parts:
                        raise RemoteMaterialImportError(
                            "REMOTE_MATERIAL_TARGET_MISMATCH",
                            "storage_scan broker returned an object outside its prefix",
                            409,
                        )
                    if Path(key).suffix.lower() in IMAGE_EXTENSIONS:
                        row = _inspect_storage_scan_image(
                            provider,
                            item,
                            storage_source_id=storage_source_id,
                            storage_type=storage_type,
                            seen_hashes=seen_hashes,
                            deduplicate=normalized_intent != "storage_rescan",
                        )
                    else:
                        row = {
                            "object_key": key,
                            "filename": Path(key).name,
                            "storage_source_id": str(storage_source_id),
                            "storage_type": str(storage_type),
                            "content_sha256": str(item.sha256 or "").strip().lower(),
                            "size_bytes": max(0, int(item.size_bytes or 0)),
                            "etag": str(item.etag or ""),
                            "width": 0,
                            "height": 0,
                            "status": "SKIPPED",
                            "error": "",
                            "duplicate": False,
                            "payload_member": "",
                        }
                    counts[row["status"]] = counts.get(row["status"], 0) + 1
                    rows_stream.write(
                        json.dumps(
                            row,
                            ensure_ascii=False,
                            sort_keys=True,
                            separators=(",", ":"),
                        ).encode("utf-8") + b"\n"
                    )
                    if progress is not None and (
                        candidate_count == 1 or candidate_count % 100 == 0
                    ):
                        progress(candidate_count, 0, key)
                rows_stream.flush()
                os.fsync(rows_stream.fileno())

            meta = {
                "schema_version": REVIEW_SCHEMA_VERSION,
                "task_id": str(task_id),
                "project_id": str(project_id),
                "execution_generation": int(execution_generation),
                "mode": "storage_scan",
                "intent": normalized_intent,
                "payload_mode": "source_reference",
                "import_format": "images",
                "storage_source_id": str(storage_source_id),
                "storage_type": str(storage_type),
                "target_prefix": target_prefix,
                "candidate_count": candidate_count,
                "counts": counts,
            }
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True,
            ) as archive:
                archive.write(rows_file, arcname=REVIEW_ROWS_MEMBER)
                archive.writestr(
                    REVIEW_META_MEMBER,
                    json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                )
            if temporary.stat().st_size <= 0:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_REVIEW_EMPTY",
                    "storage_scan review archive is empty",
                    409,
                )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
            rows_file.unlink(missing_ok=True)
        return {
            "path": target,
            "sha256": _sha256_file(target),
            "size_bytes": int(target.stat().st_size),
            "candidate_count": candidate_count,
            "counts": counts,
        }

    local_fd, local_name = tempfile.mkstemp(
        dir=target.parent, prefix=".storage-scan-yolo.", suffix=".sqlite3",
    )
    os.close(local_fd)
    local_store_path = Path(local_name)
    local_store_path.unlink(missing_ok=True)
    store = ImportCandidateStore(local_store_path)
    scanner = YoloImportScanner(
        provider,
        store,
        lambda current, scan_prefix, scan_recursive: current.iter_objects(
            scan_prefix, recursive=scan_recursive
        ),
        cancelled=(cancelled or (lambda: False)),
        progress=lambda key: (
            progress(0, 0, str(key)) if progress is not None else None
        ),
    )
    try:
        try:
            resolved_format = scanner.prepare(
                "yolo",
                prefix=target_prefix,
                recursive=bool(recursive),
                dataset_yaml=yaml_key or None,
            )
        except YoloScanCancelled as error:
            raise InterruptedError("storage_scan YOLO review cancelled") from error
        except YoloImportError as error:
            raise RemoteMaterialImportError(error.code, error.message, 422) from error
        if resolved_format != "yolo":
            raise RemoteMaterialImportError(
                "REMOTE_YOLO_DISCOVERY_FAILED",
                "storage_scan did not resolve a YOLO dataset",
                422,
            )

        seen_hashes: set[str] = set()
        batch: list[dict[str, Any]] = []
        inspected = 0
        yolo_objects = scanner.iter_images()
        if normalized_intent == "storage_rescan":
            yolo_objects = (
                item
                for item in scanner.iter_inventory(dataset_only=False)
                if Path(str(item.key)).suffix.lower() in IMAGE_EXTENSIONS
            )
        for item in yolo_objects:
            if cancelled is not None and cancelled():
                raise InterruptedError("storage_scan YOLO review cancelled")
            batch.append(_inspect_storage_scan_image(
                provider,
                item,
                storage_source_id=storage_source_id,
                storage_type=storage_type,
                seen_hashes=seen_hashes,
                deduplicate=normalized_intent != "storage_rescan",
            ))
            inspected += 1
            if len(batch) >= 500:
                store.upsert_many(batch)
                batch.clear()
            if progress is not None and (inspected == 1 or inspected % 100 == 0):
                progress(inspected, 0, str(item.key))
        if batch:
            store.upsert_many(batch)
        try:
            quality = scanner.scan_annotations()
        except YoloScanCancelled as error:
            raise InterruptedError("storage_scan YOLO annotation review cancelled") from error
        except YoloImportError as error:
            raise RemoteMaterialImportError(error.code, error.message, 422) from error

        archive_fd, archive_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.", suffix=".tmp",
        )
        os.close(archive_fd)
        temporary = Path(archive_name)
        rows_fd, rows_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.rows.", suffix=".jsonl",
        )
        os.close(rows_fd)
        rows_file = Path(rows_name)
        ann_fd, ann_name = tempfile.mkstemp(
            dir=target.parent, prefix=f".{target.name}.annotations.", suffix=".jsonl",
        )
        os.close(ann_fd)
        annotations_file = Path(ann_name)
        counts: dict[str, int] = {}
        total = sum(store.counts().values())
        completed = 0
        try:
            with rows_file.open("wb") as rows_stream, annotations_file.open("wb") as ann_stream:
                page: list[dict[str, Any]] = []
                for candidate in store.iter_candidates(batch_size=500):
                    page.append(candidate)
                    if len(page) < 500:
                        continue
                    _write_yolo_review_page(
                        None,
                        store,
                        page,
                        rows_stream,
                        ann_stream,
                        [],
                        counts,
                        target_prefix,
                        include_payloads=False,
                        preserve_object_keys=True,
                        skip_unmanifested_annotations=normalized_intent == "storage_rescan",
                    )
                    completed += len(page)
                    if progress is not None:
                        progress(completed, total, str(page[-1]["object_key"]))
                    page.clear()
                    if cancelled is not None and cancelled():
                        raise InterruptedError("storage_scan YOLO review cancelled")
                if page:
                    _write_yolo_review_page(
                        None,
                        store,
                        page,
                        rows_stream,
                        ann_stream,
                        [],
                        counts,
                        target_prefix,
                        include_payloads=False,
                        preserve_object_keys=True,
                        skip_unmanifested_annotations=normalized_intent == "storage_rescan",
                    )
                    completed += len(page)
                    if progress is not None:
                        progress(completed, total, str(page[-1]["object_key"]))
                rows_stream.flush()
                os.fsync(rows_stream.fileno())
                ann_stream.flush()
                os.fsync(ann_stream.fileno())

            classes = store.label_mapping_rows()
            meta = {
                "schema_version": REVIEW_SCHEMA_VERSION,
                "task_id": str(task_id),
                "project_id": str(project_id),
                "execution_generation": int(execution_generation),
                "mode": "storage_scan",
                "intent": normalized_intent,
                "payload_mode": "source_reference",
                "import_format": "yolo",
                "storage_source_id": str(storage_source_id),
                "storage_type": str(storage_type),
                "target_prefix": target_prefix,
                "candidate_count": total,
                "counts": counts,
                "dataset_yaml": str(scanner.yaml_key or ""),
                "classes": [
                    {"class_id": int(row["class_id"]), "name": str(row["name"])}
                    for row in classes
                ],
                "quality": quality,
            }
            with zipfile.ZipFile(
                temporary, "w", compression=zipfile.ZIP_STORED, allowZip64=True,
            ) as archive:
                archive.write(rows_file, arcname=REVIEW_ROWS_MEMBER)
                archive.write(annotations_file, arcname=REVIEW_ANNOTATIONS_MEMBER)
                archive.writestr(
                    REVIEW_META_MEMBER,
                    json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                )
            if temporary.stat().st_size <= 0:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_REVIEW_EMPTY",
                    "storage_scan YOLO review archive is empty",
                    409,
                )
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
            rows_file.unlink(missing_ok=True)
            annotations_file.unlink(missing_ok=True)

        return {
            "path": target,
            "sha256": _sha256_file(target),
            "size_bytes": int(target.stat().st_size),
            "candidate_count": total,
            "counts": counts,
            "dataset_yaml": str(scanner.yaml_key or ""),
            "quality": quality,
            "classes": [
                {"class_id": int(row["class_id"]), "name": str(row["name"])}
                for row in store.label_mapping_rows()
            ],
        }
    finally:
        local_store_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(str(local_store_path) + suffix).unlink(missing_ok=True)


def _write_yolo_review_page(
    root: Path | None,
    store: ImportCandidateStore,
    page: list[dict[str, Any]],
    rows_stream,
    annotations_stream,
    payloads: list[tuple[Path, str]],
    counts: dict[str, int],
    target_prefix: str,
    *,
    include_payloads: bool = True,
    preserve_object_keys: bool = False,
    skip_unmanifested_annotations: bool = False,
) -> None:
    source_keys = [str(row["object_key"]) for row in page]
    annotations = store.annotations_for_keys(source_keys)
    issues = store.annotation_issues_for_keys(source_keys)
    source_ref_keys = sorted({
        str(value)
        for annotation in annotations.values()
        for value in (annotation.get("label_key"), annotation.get("yaml_key"))
        if str(value or "").strip()
    })
    source_objects = store.inventory_for_keys(source_ref_keys)
    for candidate in page:
        source_key = safe_member_path(str(candidate["object_key"])).as_posix()
        target_key = (
            source_key
            if preserve_object_keys
            else _target_key(target_prefix, PurePosixPath(source_key))
        )
        status = str(candidate.get("status") or "").upper()
        payload_member = ""
        if status == "IMPORTABLE" and include_payloads:
            if root is None:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_SOURCE_INVALID",
                    "embedded YOLO review requires a local source root",
                    500,
                )
            source = _plain_file(root, PurePosixPath(source_key))
            payload_member = (
                REVIEW_FILES_PREFIX / PurePosixPath(source_key)
            ).as_posix()
            payloads.append((source, payload_member))
        row = {
            "object_key": target_key,
            "filename": Path(str(candidate.get("filename") or source_key)).name,
            "storage_source_id": str(candidate.get("storage_source_id") or ""),
            "storage_type": str(candidate.get("storage_type") or ""),
            "content_sha256": str(candidate.get("content_sha256") or "").lower(),
            "size_bytes": int(candidate.get("size_bytes") or 0),
            "etag": str(candidate.get("etag") or ""),
            "width": int(candidate.get("width") or 0),
            "height": int(candidate.get("height") or 0),
            "status": status,
            "error": str(candidate.get("error") or ""),
            "duplicate": bool(candidate.get("duplicate")),
            "payload_member": payload_member,
        }
        rows_stream.write(
            json.dumps(
                row,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )
        counts[status] = counts.get(status, 0) + 1

        if skip_unmanifested_annotations and source_key not in annotations:
            continue
        annotation = annotations.get(source_key) or {
            "object_key": source_key,
            "split": "",
            "label_key": None,
            "annotation_status": "unannotated",
            "box_count": 0,
            "boxes": [],
        }
        issue_rows = issues.get(source_key) or []
        label_key = (
            safe_member_path(str(annotation.get("label_key"))).as_posix()
            if annotation.get("label_key")
            else None
        )
        dataset_key = (
            safe_member_path(str(annotation.get("yaml_key"))).as_posix()
            if annotation.get("yaml_key")
            else None
        )
        annotations_stream.write(
            json.dumps(
                {
                    "object_key": target_key,
                    "split": str(annotation.get("split") or ""),
                    "label_key": label_key,
                    "label_object": source_objects.get(label_key) if label_key else None,
                    "dataset_key": dataset_key,
                    "dataset_object": source_objects.get(dataset_key) if dataset_key else None,
                    "annotation_status": str(
                        annotation.get("annotation_status") or "unannotated"
                    ),
                    "box_count": int(annotation.get("box_count") or 0),
                    "boxes": [
                        {
                            "line_number": int(box.get("line_number") or 0),
                            "class_id": int(box.get("class_id") or 0),
                            "cx": float(box.get("cx") or 0),
                            "cy": float(box.get("cy") or 0),
                            "w": float(box.get("w") or 0),
                            "h": float(box.get("h") or 0),
                            "clipped": bool(box.get("clipped")),
                        }
                        for box in annotation.get("boxes") or []
                    ],
                    "issues": [
                        {
                            "line_number": int(issue.get("line_number") or 0),
                            "code": str(issue.get("code") or ""),
                            "severity": str(issue.get("severity") or ""),
                        }
                        for issue in issue_rows
                    ],
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            + b"\n"
        )


class RemoteMaterialStagingStore:
    _SCHEMA = """
    CREATE TABLE IF NOT EXISTS staged_objects (
        object_key TEXT PRIMARY KEY,
        payload_member TEXT NOT NULL,
        sha256 TEXT NOT NULL,
        size_bytes INTEGER NOT NULL
    );
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as database:
            database.execute(self._SCHEMA)
            database.commit()

    def replace_many(self, rows: Iterable[Mapping[str, Any]]) -> int:
        count = 0

        def values():
            nonlocal count
            for row in rows:
                key = str(row.get("object_key") or "")
                member = str(row.get("payload_member") or "")
                digest = str(row.get("content_sha256") or "").lower()
                size = int(row.get("size_bytes") or 0)
                if not key or not member or len(digest) != 64 or size <= 0:
                    raise RemoteMaterialImportError(
                        "REMOTE_MATERIAL_STAGING_INVALID",
                        "material staging metadata is incomplete",
                        422,
                    )
                safe_member_path(member)
                count += 1
                yield (key, member, digest, size)

        with closing(sqlite3.connect(self.path)) as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                database.execute("DELETE FROM staged_objects")
                database.executemany(
                    "INSERT INTO staged_objects VALUES (?,?,?,?)",
                    values(),
                )
                database.commit()
            except Exception:
                database.rollback()
                raise
        return count

    def get_many(self, object_keys: Iterable[str]) -> dict[str, dict[str, Any]]:
        keys = [str(value) for value in object_keys]
        if len(keys) > 500:
            raise ValueError("material staging lookup is limited to 500 keys")
        if not keys:
            return {}
        placeholders = ",".join("?" for _ in keys)
        with closing(sqlite3.connect(self.path)) as database:
            database.row_factory = sqlite3.Row
            return {
                str(row["object_key"]): dict(row)
                for row in database.execute(
                    f"SELECT * FROM staged_objects WHERE object_key IN ({placeholders})",
                    keys,
                )
            }


def _iter_verified_review_rows(
    spool_path: Path,
    *,
    staging_only: bool = False,
) -> Iterator[dict[str, Any]]:
    """Replay server-verified review rows without retaining the full review in memory."""
    with spool_path.open("r", encoding="utf-8") as stream:
        for line in stream:
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_REVIEW_INVALID",
                    "verified review spool is unreadable",
                    500,
                ) from error
            if not isinstance(row, dict):
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_REVIEW_INVALID",
                    "verified review spool contains an invalid row",
                    500,
                )
            if staging_only and not str(row.get("payload_member") or ""):
                continue
            yield row


def _read_review_rows(
    review_root: Path,
    *,
    expected_source_id: str,
    expected_storage_type: str,
    expected_prefix: str,
    spool_path: Path,
    require_payload: bool = True,
    allow_root: bool = False,
) -> tuple[Path, set[str], dict[str, int], int]:
    rows_path = review_root / REVIEW_ROWS_MEMBER
    if not rows_path.is_file() or rows_path.is_symlink():
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_REVIEW_INVALID",
            "review candidate stream is missing",
            422,
        )
    prefix = (
        safe_member_path(expected_prefix)
        if str(expected_prefix or "").strip()
        else PurePosixPath()
        if allow_root
        else None
    )
    if prefix is None:
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_PREFIX_REQUIRED",
            "review verification requires an explicit target prefix",
            422,
        )

    spool_path.parent.mkdir(parents=True, exist_ok=True)
    spool_path.unlink(missing_ok=True)
    counts: dict[str, int] = {}
    seen: set[str] = set()
    row_count = 0
    with (
        rows_path.open("r", encoding="utf-8") as stream,
        spool_path.open("x", encoding="utf-8", newline="\n") as verified_stream,
    ):
        for line_number, line in enumerate(stream, start=1):
            if line_number > _MAX_REVIEW_ROWS:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_MEMBER_LIMIT",
                    "review candidate stream exceeds its row limit",
                    413,
                )
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_REVIEW_INVALID",
                    "review candidate stream contains invalid JSON",
                    422,
                ) from error
            if not isinstance(row, dict):
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_REVIEW_INVALID",
                    "review candidate entry must be an object",
                    422,
                )
            key = str(row.get("object_key") or "")
            if not key or key in seen:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_REVIEW_INVALID",
                    "review candidate object keys must be unique",
                    422,
                )
            seen.add(key)
            relative_key = safe_member_path(key)
            if relative_key.parts[: len(prefix.parts)] != prefix.parts:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_TARGET_MISMATCH",
                    "review candidate escaped the requested target prefix",
                    409,
                )
            if (
                str(row.get("storage_source_id") or "") != expected_source_id
                or str(row.get("storage_type") or "") != expected_storage_type
            ):
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_TARGET_MISMATCH",
                    "review candidate target storage changed",
                    409,
                )
            status = str(row.get("status") or "")
            if status not in {"IMPORTABLE", "DUPLICATE", "INVALID", "SKIPPED", "FAILED"}:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_REVIEW_INVALID",
                    "review candidate has an invalid status",
                    422,
                )
            candidate = {
                "object_key": key,
                "filename": Path(str(row.get("filename") or "")).name,
                "storage_source_id": expected_source_id,
                "storage_type": expected_storage_type,
                "content_sha256": str(row.get("content_sha256") or "").lower(),
                "size_bytes": max(0, int(row.get("size_bytes") or 0)),
                "etag": str(row.get("etag") or ""),
                "width": max(0, int(row.get("width") or 0)),
                "height": max(0, int(row.get("height") or 0)),
                "status": status,
                "error": str(row.get("error") or "")[:1000],
                "duplicate": bool(row.get("duplicate")),
            }
            if status == "IMPORTABLE" and not require_payload:
                digest = candidate["content_sha256"]
                if (
                    len(digest) != 64
                    or any(char not in "0123456789abcdef" for char in digest)
                    or candidate["size_bytes"] <= 0
                    or candidate["width"] <= 0
                    or candidate["height"] <= 0
                    or not candidate["etag"]
                ):
                    raise RemoteMaterialImportError(
                        "REMOTE_MATERIAL_SOURCE_EVIDENCE_MISSING",
                        "storage_scan review is missing immutable source evidence",
                        409,
                    )
            if status == "IMPORTABLE" and require_payload:
                member = safe_member_path(str(row.get("payload_member") or ""))
                payload = review_root.joinpath(*member.parts)
                if not payload.is_file() or payload.is_symlink():
                    raise RemoteMaterialImportError(
                        "REMOTE_MATERIAL_PAYLOAD_MISSING",
                        "review payload member is missing",
                        409,
                    )
                actual_size = int(payload.stat().st_size)
                actual_sha = _sha256_file(payload)
                if (
                    actual_size != candidate["size_bytes"]
                    or actual_sha != candidate["content_sha256"]
                ):
                    raise RemoteMaterialImportError(
                        "REMOTE_MATERIAL_PAYLOAD_CHANGED",
                        "review payload does not match candidate evidence",
                        409,
                    )
                try:
                    with Image.open(payload) as image:
                        width, height = image.size
                        image.verify()
                except (UnidentifiedImageError, OSError, ValueError) as error:
                    raise RemoteMaterialImportError(
                        "REMOTE_MATERIAL_PAYLOAD_INVALID",
                        "review payload is not a valid image",
                        409,
                    ) from error
                if int(width) != candidate["width"] or int(height) != candidate["height"]:
                    raise RemoteMaterialImportError(
                        "REMOTE_MATERIAL_PAYLOAD_CHANGED",
                        "review payload dimensions do not match candidate evidence",
                        409,
                    )
                candidate["payload_member"] = member.as_posix()

            verified_stream.write(
                json.dumps(
                    candidate,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            counts[status] = counts.get(status, 0) + 1
            row_count += 1
    return spool_path, seen, counts, row_count


def _commit_detection_review_annotations(
    review_root: Path,
    store: ImportCandidateStore,
    *,
    candidate_keys: set[str],
    meta: Mapping[str, Any],
    expected_prefix: str,
    annotations_member: str,
    manifest_identity: str,
) -> dict[str, Any]:
    annotation_path = safe_member_path(str(annotations_member))
    annotations_path = review_root.joinpath(*annotation_path.parts)
    if not annotations_path.is_file() or annotations_path.is_symlink():
        raise RemoteMaterialImportError(
            "REMOTE_DETECTION_REVIEW_INVALID",
            "detection review annotation stream is missing",
            422,
        )
    classes = meta.get("classes")
    if not isinstance(classes, list) or not classes or len(classes) > 10000:
        raise RemoteMaterialImportError(
            "REMOTE_DETECTION_CLASSES_INVALID",
            "detection review class mapping is invalid",
            422,
        )
    names: dict[int, str] = {}
    for item in classes:
        if not isinstance(item, Mapping):
            raise RemoteMaterialImportError(
                "REMOTE_DETECTION_CLASSES_INVALID",
                "detection review class entry must be an object",
                422,
            )
        try:
            class_id = int(item.get("class_id"))
        except (TypeError, ValueError, OverflowError) as error:
            raise RemoteMaterialImportError(
                "REMOTE_DETECTION_CLASSES_INVALID",
                "detection review class ID is invalid",
                422,
            ) from error
        name = str(item.get("name") or "").strip()
        if class_id < 0 or class_id > 2**63 - 1 or not name or len(name) > 1000:
            raise RemoteMaterialImportError(
                "REMOTE_DETECTION_CLASSES_INVALID",
                "detection review class ID/name is invalid",
                422,
            )
        if class_id in names and names[class_id] != name:
            raise RemoteMaterialImportError(
                "REMOTE_DETECTION_CLASSES_INVALID",
                "detection review contains conflicting class names",
                409,
            )
        names[class_id] = name
    store.set_label_mapping(names)

    expected_prefix_path = (
        safe_member_path(expected_prefix)
        if str(expected_prefix or "").strip()
        else PurePosixPath()
    )
    seen: set[str] = set()
    states: list[dict[str, Any]] = []
    boxes: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    source_inventory: dict[str, dict[str, Any]] = {}
    total_boxes = 0
    total_issues = 0
    rescan_evidence_required = str(meta.get("intent") or "") == "storage_rescan"

    def verified_source_object(value, key: str | None):
        if not key:
            if value is not None:
                raise RemoteMaterialImportError(
                    "REMOTE_DETECTION_REVIEW_INVALID",
                    "detection review contains source metadata without an object key",
                    422,
                )
            return None
        if value is None:
            if rescan_evidence_required:
                raise RemoteMaterialImportError(
                    "REMOTE_DETECTION_SOURCE_EVIDENCE_MISSING",
                    "detection rescan review is missing annotation source identity evidence",
                    409,
                )
            return None
        if not isinstance(value, Mapping):
            raise RemoteMaterialImportError(
                "REMOTE_DETECTION_REVIEW_INVALID",
                "detection source identity evidence must be an object",
                422,
            )
        try:
            size_bytes = int(value.get("size_bytes") or 0)
        except (TypeError, ValueError, OverflowError) as error:
            raise RemoteMaterialImportError(
                "REMOTE_DETECTION_REVIEW_INVALID",
                "detection source identity size is invalid",
                422,
            ) from error
        etag = str(value.get("etag") or "")
        sha256 = str(value.get("sha256") or "").strip().lower()
        if (
            size_bytes <= 0
            or not etag
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
        ):
            raise RemoteMaterialImportError(
                "REMOTE_DETECTION_SOURCE_EVIDENCE_INVALID",
                "detection source identity evidence is incomplete",
                422,
            )
        return {
            "object_key": key,
            "size_bytes": size_bytes,
            "etag": etag,
            "sha256": sha256,
        }

    def flush() -> None:
        if states or boxes or issues:
            store.annotation_batch(states, boxes, issues)
            states.clear()
            boxes.clear()
            issues.clear()
        if source_inventory:
            store.inventory_many(source_inventory.values())
            source_inventory.clear()

    with annotations_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if line_number > _MAX_REVIEW_ROWS:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_MEMBER_LIMIT",
                    "detection review annotation stream exceeds its row limit",
                    413,
                )
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise RemoteMaterialImportError(
                    "REMOTE_DETECTION_REVIEW_INVALID",
                    "detection review annotation stream contains invalid JSON",
                    422,
                ) from error
            if not isinstance(row, dict):
                raise RemoteMaterialImportError(
                    "REMOTE_DETECTION_REVIEW_INVALID",
                    "detection review annotation entry must be an object",
                    422,
                )
            key = str(row.get("object_key") or "")
            if not key or key in seen or key not in candidate_keys:
                raise RemoteMaterialImportError(
                    "REMOTE_DETECTION_REVIEW_INVALID",
                    "detection annotation object key is unknown or duplicated",
                    409,
                )
            key_path = safe_member_path(key)
            if key_path.parts[: len(expected_prefix_path.parts)] != expected_prefix_path.parts:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_TARGET_MISMATCH",
                    "detection annotation escaped the requested target prefix",
                    409,
                )
            seen.add(key)

            split = str(row.get("split") or "")
            if not split or len(split) > 100:
                raise RemoteMaterialImportError(
                    "REMOTE_DETECTION_REVIEW_INVALID",
                    "detection annotation split is invalid",
                    422,
                )
            status = str(row.get("annotation_status") or "")
            if status not in {"annotated", "confirmed_empty", "unannotated", "invalid"}:
                raise RemoteMaterialImportError(
                    "REMOTE_DETECTION_REVIEW_INVALID",
                    "detection annotation status is invalid",
                    422,
                )
            label_key = row.get("label_key")
            if label_key is not None:
                label_key = safe_member_path(str(label_key)).as_posix()
            dataset_key = row.get("dataset_key")
            dataset_key = (
                safe_member_path(str(dataset_key)).as_posix()
                if dataset_key
                else None
            )
            if rescan_evidence_required:
                if not label_key or not dataset_key or label_key != dataset_key:
                    raise RemoteMaterialImportError(
                        "REMOTE_DETECTION_SOURCE_EVIDENCE_INVALID",
                        "detection rescan requires one exact annotation source identity",
                        409,
                    )
                label_object = verified_source_object(row.get("label_object"), label_key)
                dataset_object = verified_source_object(row.get("dataset_object"), dataset_key)
                if label_object != dataset_object:
                    raise RemoteMaterialImportError(
                        "REMOTE_DETECTION_SOURCE_EVIDENCE_INVALID",
                        "detection annotation source evidence does not reconcile",
                        409,
                    )
                previous = source_inventory.get(dataset_key)
                if previous is not None and previous != dataset_object:
                    raise RemoteMaterialImportError(
                        "REMOTE_DETECTION_SOURCE_EVIDENCE_INVALID",
                        "detection review contains conflicting source object evidence",
                        409,
                    )
                source_inventory[dataset_key] = dataset_object

            raw_boxes = row.get("boxes")
            raw_issues = row.get("issues")
            if not isinstance(raw_boxes, list) or len(raw_boxes) > 100000:
                raise RemoteMaterialImportError(
                    "REMOTE_DETECTION_REVIEW_INVALID",
                    "detection annotation boxes are invalid or unbounded",
                    422,
                )
            if not isinstance(raw_issues, list) or len(raw_issues) > 100000:
                raise RemoteMaterialImportError(
                    "REMOTE_DETECTION_REVIEW_INVALID",
                    "detection annotation issues are invalid or unbounded",
                    422,
                )
            if int(row.get("box_count") or 0) != len(raw_boxes):
                raise RemoteMaterialImportError(
                    "REMOTE_DETECTION_REVIEW_INVALID",
                    "detection annotation box count does not reconcile",
                    409,
                )

            local_line_numbers: set[int] = set()
            for box in raw_boxes:
                if not isinstance(box, Mapping):
                    raise RemoteMaterialImportError(
                        "REMOTE_DETECTION_REVIEW_INVALID",
                        "detection box entry must be an object",
                        422,
                    )
                try:
                    item_line = int(box.get("line_number") or 0)
                    class_id = int(box.get("class_id"))
                    cx = float(box.get("cx"))
                    cy = float(box.get("cy"))
                    width = float(box.get("w"))
                    height = float(box.get("h"))
                except (TypeError, ValueError, OverflowError) as error:
                    raise RemoteMaterialImportError(
                        "REMOTE_DETECTION_REVIEW_INVALID",
                        "detection box contains invalid numeric values",
                        422,
                    ) from error
                if (
                    item_line <= 0
                    or item_line in local_line_numbers
                    or class_id not in names
                    or not all(math.isfinite(value) for value in (cx, cy, width, height))
                    or not (0.0 <= cx <= 1.0)
                    or not (0.0 <= cy <= 1.0)
                    or not (0.0 < width <= 1.0)
                    or not (0.0 < height <= 1.0)
                ):
                    raise RemoteMaterialImportError(
                        "REMOTE_DETECTION_REVIEW_INVALID",
                        "detection box violates normalized detection constraints",
                        422,
                    )
                local_line_numbers.add(item_line)
                boxes.append({
                    "object_key": key,
                    "line_number": item_line,
                    "class_id": class_id,
                    "cx": cx,
                    "cy": cy,
                    "w": width,
                    "h": height,
                    "clipped": bool(box.get("clipped")),
                })
                total_boxes += 1
                if total_boxes > 5_000_000:
                    raise RemoteMaterialImportError(
                        "REMOTE_DETECTION_REVIEW_TOO_LARGE",
                        "detection review contains too many boxes",
                        413,
                    )

            for issue in raw_issues:
                if not isinstance(issue, Mapping):
                    raise RemoteMaterialImportError(
                        "REMOTE_DETECTION_REVIEW_INVALID",
                        "detection issue entry must be an object",
                        422,
                    )
                try:
                    issue_line = int(issue.get("line_number") or 0)
                except (TypeError, ValueError, OverflowError) as error:
                    raise RemoteMaterialImportError(
                        "REMOTE_DETECTION_REVIEW_INVALID",
                        "detection issue line number is invalid",
                        422,
                    ) from error
                code = str(issue.get("code") or "").strip()
                severity = str(issue.get("severity") or "").strip()
                if (
                    issue_line < 0
                    or not code
                    or len(code) > 200
                    or severity not in {"warning", "error"}
                ):
                    raise RemoteMaterialImportError(
                        "REMOTE_DETECTION_REVIEW_INVALID",
                        "detection issue entry is invalid",
                        422,
                    )
                issues.append({
                    "object_key": key,
                    "line_number": issue_line,
                    "code": code,
                    "severity": severity,
                })
                total_issues += 1
                if total_issues > 5_000_000:
                    raise RemoteMaterialImportError(
                        "REMOTE_DETECTION_REVIEW_TOO_LARGE",
                        "detection review contains too many issues",
                        413,
                    )
            states.append({
                "object_key": key,
                "label_key": label_key,
                "annotation_status": status,
                "box_count": len(raw_boxes),
            })
            store.manifest_many([{
                "object_key": key,
                "split": split,
                "yaml_key": (
                    dataset_key
                    if rescan_evidence_required
                    else safe_member_path(
                        str(manifest_identity or annotations_member)
                    ).as_posix()
                ),
            }])
            if len(states) >= 500 or len(boxes) + len(issues) >= 5000:
                flush()
    flush()
    if not rescan_evidence_required and seen != candidate_keys:
        raise RemoteMaterialImportError(
            "REMOTE_DETECTION_REVIEW_INVALID",
            "detection annotation stream does not cover every candidate image",
            409,
        )
    return store.quality_summary()


def _commit_yolo_review_annotations(
    review_root: Path,
    store: ImportCandidateStore,
    *,
    candidate_keys: set[str],
    meta: Mapping[str, Any],
    expected_prefix: str,
) -> dict[str, Any]:
    annotations_path = review_root / REVIEW_ANNOTATIONS_MEMBER
    if not annotations_path.is_file() or annotations_path.is_symlink():
        raise RemoteMaterialImportError(
            "REMOTE_YOLO_REVIEW_INVALID",
            "YOLO review annotation stream is missing",
            422,
        )
    classes = meta.get("classes")
    if not isinstance(classes, list) or not classes or len(classes) > 10000:
        raise RemoteMaterialImportError(
            "REMOTE_YOLO_CLASSES_INVALID",
            "YOLO review class mapping is invalid",
            422,
        )
    names: dict[int, str] = {}
    for item in classes:
        if not isinstance(item, Mapping):
            raise RemoteMaterialImportError(
                "REMOTE_YOLO_CLASSES_INVALID",
                "YOLO review class entry must be an object",
                422,
            )
        try:
            class_id = int(item.get("class_id"))
        except (TypeError, ValueError, OverflowError) as error:
            raise RemoteMaterialImportError(
                "REMOTE_YOLO_CLASSES_INVALID",
                "YOLO review class ID is invalid",
                422,
            ) from error
        name = str(item.get("name") or "").strip()
        if class_id < 0 or class_id > 2**63 - 1 or not name or len(name) > 1000:
            raise RemoteMaterialImportError(
                "REMOTE_YOLO_CLASSES_INVALID",
                "YOLO review class ID/name is invalid",
                422,
            )
        if class_id in names and names[class_id] != name:
            raise RemoteMaterialImportError(
                "REMOTE_YOLO_CLASSES_INVALID",
                "YOLO review contains conflicting class names",
                409,
            )
        names[class_id] = name
    store.set_label_mapping(names)

    expected_prefix_path = (
        safe_member_path(expected_prefix)
        if str(expected_prefix or "").strip()
        else PurePosixPath()
    )
    seen: set[str] = set()
    states: list[dict[str, Any]] = []
    boxes: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    source_inventory: dict[str, dict[str, Any]] = {}
    total_boxes = 0
    total_issues = 0
    rescan_evidence_required = str(meta.get("intent") or "") == "storage_rescan"

    def verified_source_object(value, key: str | None, *, required: bool):
        if not key:
            if value is not None:
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_REVIEW_INVALID",
                    "YOLO review contains source metadata without an object key",
                    422,
                )
            return None
        if value is None:
            if required:
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_SOURCE_EVIDENCE_MISSING",
                    "YOLO rescan review is missing source object identity evidence",
                    409,
                )
            return None
        if not isinstance(value, Mapping):
            raise RemoteMaterialImportError(
                "REMOTE_YOLO_REVIEW_INVALID",
                "YOLO source identity evidence must be an object",
                422,
            )
        try:
            size_bytes = int(value.get("size_bytes") or 0)
        except (TypeError, ValueError, OverflowError) as error:
            raise RemoteMaterialImportError(
                "REMOTE_YOLO_REVIEW_INVALID",
                "YOLO source identity size is invalid",
                422,
            ) from error
        etag = str(value.get("etag") or "")
        sha256 = str(value.get("sha256") or "").strip().lower()
        if (
            size_bytes < 0
            or len(sha256) != 64
            or any(character not in "0123456789abcdef" for character in sha256)
        ):
            raise RemoteMaterialImportError(
                "REMOTE_YOLO_SOURCE_EVIDENCE_INVALID",
                "YOLO source identity evidence is incomplete",
                422,
            )
        return {
            "object_key": key,
            "size_bytes": size_bytes,
            "etag": etag,
            "sha256": sha256,
        }

    def flush() -> None:
        if states or boxes or issues:
            store.annotation_batch(states, boxes, issues)
            states.clear()
            boxes.clear()
            issues.clear()
        if source_inventory:
            store.inventory_many(source_inventory.values())
            source_inventory.clear()

    with annotations_path.open("r", encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, start=1):
            if line_number > _MAX_REVIEW_ROWS:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_MEMBER_LIMIT",
                    "YOLO review annotation stream exceeds its row limit",
                    413,
                )
            try:
                row = json.loads(line)
            except json.JSONDecodeError as error:
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_REVIEW_INVALID",
                    "YOLO review annotation stream contains invalid JSON",
                    422,
                ) from error
            if not isinstance(row, dict):
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_REVIEW_INVALID",
                    "YOLO review annotation entry must be an object",
                    422,
                )
            key = str(row.get("object_key") or "")
            if not key or key in seen or key not in candidate_keys:
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_REVIEW_INVALID",
                    "YOLO annotation object key is unknown or duplicated",
                    409,
                )
            key_path = safe_member_path(key)
            if key_path.parts[: len(expected_prefix_path.parts)] != expected_prefix_path.parts:
                raise RemoteMaterialImportError(
                    "REMOTE_MATERIAL_TARGET_MISMATCH",
                    "YOLO annotation escaped the requested target prefix",
                    409,
                )
            seen.add(key)

            split = str(row.get("split") or "")
            if not split or len(split) > 100:
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_REVIEW_INVALID",
                    "YOLO annotation split is invalid",
                    422,
                )
            status = str(row.get("annotation_status") or "")
            if status not in {"annotated", "confirmed_empty", "unannotated", "invalid"}:
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_REVIEW_INVALID",
                    "YOLO annotation status is invalid",
                    422,
                )
            label_key = row.get("label_key")
            if label_key is not None:
                label_key = safe_member_path(str(label_key)).as_posix()
            dataset_key = row.get("dataset_key") or meta.get("dataset_yaml")
            dataset_key = (
                safe_member_path(str(dataset_key)).as_posix()
                if dataset_key
                else None
            )
            expected_dataset_key = str(meta.get("dataset_yaml") or "")
            if expected_dataset_key:
                expected_dataset_key = safe_member_path(expected_dataset_key).as_posix()
                if dataset_key != expected_dataset_key:
                    raise RemoteMaterialImportError(
                        "REMOTE_YOLO_DATASET_MISMATCH",
                        "YOLO review dataset source differs from its metadata",
                        409,
                    )
            label_object = verified_source_object(
                row.get("label_object"),
                label_key,
                required=rescan_evidence_required and label_key is not None,
            )
            dataset_object = verified_source_object(
                row.get("dataset_object"),
                dataset_key,
                required=rescan_evidence_required,
            )
            for source_object in (label_object, dataset_object):
                if source_object is None:
                    continue
                previous = source_inventory.get(source_object["object_key"])
                if previous is not None and previous != source_object:
                    raise RemoteMaterialImportError(
                        "REMOTE_YOLO_SOURCE_EVIDENCE_INVALID",
                        "YOLO review contains conflicting source object evidence",
                        409,
                    )
                source_inventory[source_object["object_key"]] = source_object

            raw_boxes = row.get("boxes")
            raw_issues = row.get("issues")
            if not isinstance(raw_boxes, list) or len(raw_boxes) > 100000:
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_REVIEW_INVALID",
                    "YOLO annotation boxes are invalid or unbounded",
                    422,
                )
            if not isinstance(raw_issues, list) or len(raw_issues) > 100000:
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_REVIEW_INVALID",
                    "YOLO annotation issues are invalid or unbounded",
                    422,
                )
            if int(row.get("box_count") or 0) != len(raw_boxes):
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_REVIEW_INVALID",
                    "YOLO annotation box count does not reconcile",
                    409,
                )

            local_line_numbers: set[int] = set()
            for box in raw_boxes:
                if not isinstance(box, Mapping):
                    raise RemoteMaterialImportError(
                        "REMOTE_YOLO_REVIEW_INVALID",
                        "YOLO box entry must be an object",
                        422,
                    )
                try:
                    item_line = int(box.get("line_number") or 0)
                    class_id = int(box.get("class_id"))
                    cx = float(box.get("cx"))
                    cy = float(box.get("cy"))
                    width = float(box.get("w"))
                    height = float(box.get("h"))
                except (TypeError, ValueError, OverflowError) as error:
                    raise RemoteMaterialImportError(
                        "REMOTE_YOLO_REVIEW_INVALID",
                        "YOLO box contains invalid numeric values",
                        422,
                    ) from error
                if (
                    item_line <= 0
                    or item_line in local_line_numbers
                    or class_id not in names
                    or not all(math.isfinite(value) for value in (cx, cy, width, height))
                    or not (0.0 <= cx <= 1.0)
                    or not (0.0 <= cy <= 1.0)
                    or not (0.0 < width <= 1.0)
                    or not (0.0 < height <= 1.0)
                ):
                    raise RemoteMaterialImportError(
                        "REMOTE_YOLO_REVIEW_INVALID",
                        "YOLO box violates normalized detection constraints",
                        422,
                    )
                local_line_numbers.add(item_line)
                boxes.append({
                    "object_key": key,
                    "line_number": item_line,
                    "class_id": class_id,
                    "cx": cx,
                    "cy": cy,
                    "w": width,
                    "h": height,
                    "clipped": bool(box.get("clipped")),
                })
                total_boxes += 1
                if total_boxes > 5_000_000:
                    raise RemoteMaterialImportError(
                        "REMOTE_YOLO_REVIEW_TOO_LARGE",
                        "YOLO review contains too many boxes",
                        413,
                    )

            for issue in raw_issues:
                if not isinstance(issue, Mapping):
                    raise RemoteMaterialImportError(
                        "REMOTE_YOLO_REVIEW_INVALID",
                        "YOLO issue entry must be an object",
                        422,
                    )
                try:
                    issue_line = int(issue.get("line_number") or 0)
                except (TypeError, ValueError, OverflowError) as error:
                    raise RemoteMaterialImportError(
                        "REMOTE_YOLO_REVIEW_INVALID",
                        "YOLO issue line number is invalid",
                        422,
                    ) from error
                code = str(issue.get("code") or "").strip()
                severity = str(issue.get("severity") or "").strip()
                if (
                    issue_line < 0
                    or not code
                    or len(code) > 200
                    or severity not in {"warning", "error"}
                ):
                    raise RemoteMaterialImportError(
                        "REMOTE_YOLO_REVIEW_INVALID",
                        "YOLO issue entry is invalid",
                        422,
                    )
                issues.append({
                    "object_key": key,
                    "line_number": issue_line,
                    "code": code,
                    "severity": severity,
                })
                total_issues += 1
                if total_issues > 5_000_000:
                    raise RemoteMaterialImportError(
                        "REMOTE_YOLO_REVIEW_TOO_LARGE",
                        "YOLO review contains too many issues",
                        413,
                    )
            states.append({
                "object_key": key,
                "label_key": label_key,
                "annotation_status": status,
                "box_count": len(raw_boxes),
            })
            store.manifest_many([{
                "object_key": key,
                "split": split,
                "yaml_key": (
                    dataset_key
                    or safe_member_path(
                        str(meta.get("dataset_yaml") or "data.yaml")
                    ).as_posix()
                ),
            }])
            if len(states) >= 500 or len(boxes) + len(issues) >= 5000:
                flush()
    flush()
    if not rescan_evidence_required and seen != candidate_keys:
        raise RemoteMaterialImportError(
            "REMOTE_YOLO_REVIEW_INVALID",
            "YOLO annotation stream does not cover every candidate image",
            409,
        )
    return store.quality_summary()


def commit_material_review_archive(
    *,
    artifacts,
    task_id: str,
    project_id: str,
    execution_generation: int,
    archive_path: str | Path,
    archive_sha256: str,
    archive_size_bytes: int,
    expected_source_id: str,
    expected_storage_type: str,
    expected_prefix: str,
    expected_mode: str = "zip_scan",
    expected_import_format: str = "images",
    expected_dataset_yaml: str = "",
    expected_intent: str = "",
    platform_labels: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    archive = Path(archive_path).resolve()
    if (
        not archive.is_file()
        or int(archive.stat().st_size) != int(archive_size_bytes)
        or _sha256_file(archive) != str(archive_sha256).lower()
    ):
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_REVIEW_CHANGED",
            "downloaded review archive does not match server-confirmed evidence",
            409,
        )
    stage_parent = artifacts.artifact_path(
        task_id,
        f"remote-material/generation-{int(execution_generation)}",
    )
    stage_parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(
        tempfile.mkdtemp(
            dir=stage_parent,
            prefix=".verify-",
        )
    )
    review_root = temporary_root / "review"
    extract_task = f"review-{int(execution_generation)}-{uuid4().hex[:8]}"
    try:
        extract_server_zip(
            archive,
            temporary_root,
            "review",
            task_id=extract_task,
        )
        finalize_server_zip_publication(
            temporary_root,
            "review",
            task_id=extract_task,
        )
        meta_path = review_root / REVIEW_META_MEMBER
        if not meta_path.is_file() or meta_path.is_symlink():
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_REVIEW_INVALID",
                "review metadata is missing",
                422,
            )
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        normalized_intent = str(expected_intent or "").strip().lower()
        if normalized_intent not in {"", "storage_rescan"}:
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_INTENT_INVALID",
                "review verification intent is invalid",
                422,
            )
        allow_root = (
            normalized_intent == "storage_rescan"
            and str(expected_mode or "") == "storage_scan"
            and str(expected_import_format or "") in {"images", "yolo", "coco", "voc"}
            and not str(expected_prefix or "").strip()
        )
        if normalized_intent == "storage_rescan" and not allow_root:
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_RESCAN_CONTRACT_INVALID",
                "storage_rescan review must cover the complete image source",
                409,
            )
        normalized_prefix = (
            safe_member_path(expected_prefix).as_posix()
            if str(expected_prefix or "").strip()
            else ""
        )
        if (
            not isinstance(meta, dict)
            or int(meta.get("schema_version") or 0) != REVIEW_SCHEMA_VERSION
            or str(meta.get("task_id") or "") != str(task_id)
            or str(meta.get("project_id") or "") != str(project_id)
            or int(meta.get("execution_generation") or 0) != int(execution_generation)
            or str(meta.get("mode") or "") != str(expected_mode or "zip_scan")
            or str(meta.get("import_format") or "") != str(expected_import_format or "images")
            or str(meta.get("storage_source_id") or "") != expected_source_id
            or str(meta.get("storage_type") or "") != expected_storage_type
            or str(meta.get("target_prefix") or "") != normalized_prefix
            or str(meta.get("intent") or "") != normalized_intent
        ):
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_REVIEW_INVALID",
                "review metadata does not match the durable import request",
                409,
            )
        payload_mode = str(meta.get("payload_mode") or "embedded")
        if (
            str(expected_mode or "zip_scan") == "storage_scan"
            and payload_mode != "source_reference"
        ):
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_REVIEW_INVALID",
                "storage_scan review must reference existing source objects",
                409,
            )
        if str(expected_import_format or "images") == "yolo":
            dataset_yaml = str(meta.get("dataset_yaml") or "").strip()
            if not dataset_yaml:
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_REVIEW_INVALID",
                    "YOLO review dataset YAML identity is missing",
                    422,
                )
            safe_member_path(dataset_yaml)
            requested_yaml = str(expected_dataset_yaml or "").strip()
            if requested_yaml and dataset_yaml != safe_member_path(requested_yaml).as_posix():
                raise RemoteMaterialImportError(
                    "REMOTE_YOLO_DATASET_MISMATCH",
                    "YOLO review dataset YAML differs from the durable request",
                    409,
                )

        verified_rows_path, candidate_keys, counts, scanned = _read_review_rows(
            review_root,
            expected_source_id=expected_source_id,
            expected_storage_type=expected_storage_type,
            expected_prefix=expected_prefix,
            spool_path=temporary_root / "verified-review.jsonl",
            require_payload=str(expected_mode or "zip_scan") != "storage_scan",
            allow_root=allow_root,
        )
        if int(meta.get("candidate_count") or -1) != scanned:
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_REVIEW_INVALID",
                "review candidate count does not reconcile",
                409,
            )

        candidate_store = ImportCandidateStore(
            artifacts.artifact_path(task_id, MANIFEST_REF)
        )
        candidate_store.upsert_many(
            _iter_verified_review_rows(verified_rows_path)
        )
        quality = None
        external_classes = []
        normalized_format = str(expected_import_format or "images")
        if normalized_format == "yolo":
            quality = _commit_yolo_review_annotations(
                review_root,
                candidate_store,
                candidate_keys=candidate_keys,
                meta=meta,
                expected_prefix=expected_prefix,
            )
            external_classes = external_label_facts(candidate_store.external_classes())
        elif normalized_format in {"coco", "voc"}:
            annotation_member = str(meta.get("annotation_member") or "")
            if annotation_member != REVIEW_DETECTION_ANNOTATIONS_MEMBER:
                raise RemoteMaterialImportError(
                    "REMOTE_DETECTION_REVIEW_INVALID",
                    "detection review annotation member is invalid",
                    409,
                )
            quality = _commit_detection_review_annotations(
                review_root,
                candidate_store,
                candidate_keys=candidate_keys,
                meta=meta,
                expected_prefix=expected_prefix,
                annotations_member=annotation_member,
                manifest_identity=annotation_member,
            )
            external_classes = external_label_facts(candidate_store.external_classes())
        candidate_keys.clear()
        staging_store = RemoteMaterialStagingStore(
            artifacts.artifact_path(task_id, REMOTE_MATERIAL_STAGING_REF)
        )
        staging_store.replace_many(
            _iter_verified_review_rows(
                verified_rows_path,
                staging_only=True,
            )
        )

        durable_archive_ref = (
            f"remote-material/generation-{int(execution_generation)}/review.zip"
        )
        durable_archive = artifacts.artifact_path(task_id, durable_archive_ref)
        durable_archive.parent.mkdir(parents=True, exist_ok=True)
        temporary_archive = durable_archive.with_name(
            f".{durable_archive.name}.{uuid4().hex}.tmp"
        )
        with archive.open("rb") as source, temporary_archive.open("xb") as target:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        os.replace(temporary_archive, durable_archive)

        result = {
            "stage": "awaiting_confirmation",
            "mode": (
                "agent_storage_scan"
                if str(expected_mode or "zip_scan") == "storage_scan"
                else "agent_zip_scan"
            ),
            "storage_source_id": expected_source_id,
            "prefix": normalized_prefix,
            "recursive": True,
            "scanned_files": scanned,
            "importable_images": counts.get("IMPORTABLE", 0),
            "duplicates": counts.get("DUPLICATE", 0),
            "invalid_images": counts.get("INVALID", 0),
            "skipped_files": counts.get("SKIPPED", 0),
            "failed": counts.get("FAILED", 0),
            "scanned": scanned,
            "importable": counts.get("IMPORTABLE", 0),
            "manifest_ref": MANIFEST_REF,
            "failure_examples": candidate_store.failure_page(limit=200),
            "import_format": str(expected_import_format or "images"),
            **(
                {
                    **(
                        {"dataset_yaml": str(meta.get("dataset_yaml") or "")}
                        if normalized_format == "yolo"
                        else {}
                    ),
                    "quality": quality,
                    "external_classes": external_classes,
                }
                if normalized_format in {"yolo", "coco", "voc"}
                else {}
            ),
            "remote_review_archive_ref": durable_archive_ref,
            "remote_staging_ref": REMOTE_MATERIAL_STAGING_REF,
        }
        artifacts.atomic_write_json(task_id, SCAN_RESULT_REF, result)
        return {
            "material_review_committed": True,
            "material_review_archive_ref": durable_archive_ref,
            "material_staging_ref": REMOTE_MATERIAL_STAGING_REF,
            "material_scan_result_ref": SCAN_RESULT_REF,
            "material_candidates": scanned,
            "material_importable": counts.get("IMPORTABLE", 0),
        }
    except (ServerZipImportError, json.JSONDecodeError) as error:
        if isinstance(error, RemoteMaterialImportError):
            raise
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_REVIEW_INVALID",
            "review archive could not be safely verified",
            422,
        ) from error
    finally:
        import shutil
        shutil.rmtree(temporary_root, ignore_errors=True)


__all__ = [
    "REMOTE_MATERIAL_STAGING_REF",
    "REVIEW_SCHEMA_VERSION",
    "REVIEW_DETECTION_ANNOTATIONS_MEMBER",
    "RemoteMaterialImportError",
    "RemoteMaterialStagingStore",
    "build_detection_material_review_archive",
    "build_material_review_archive",
    "build_storage_scan_material_review_archive",
    "commit_material_review_archive",
]
