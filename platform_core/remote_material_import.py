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
import os
import sqlite3
import tempfile
import zipfile
from contextlib import closing
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Iterable, Mapping
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from .storage.import_candidates import ImportCandidateStore
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
    counts: dict[str, int] = {}
    seen_hashes: set[str] = set()
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as archive:
            with archive.open(REVIEW_ROWS_MEMBER, "w") as rows_stream:
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
                            row.update({
                                "content_sha256": digest,
                                "width": int(width),
                                "height": int(height),
                                "status": "DUPLICATE" if digest in seen_hashes else "IMPORTABLE",
                                "duplicate": digest in seen_hashes,
                            })
                            if digest not in seen_hashes:
                                payload_member = (
                                    REVIEW_FILES_PREFIX
                                    / PurePosixPath(*relative.parts)
                                ).as_posix()
                                archive.write(source, arcname=payload_member)
                                row["payload_member"] = payload_member
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

    return {
        "path": target,
        "sha256": _sha256_file(target),
        "size_bytes": int(target.stat().st_size),
        "candidate_count": len(members),
        "counts": counts,
    }


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
        values = []
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
            values.append((key, member, digest, size))
        with closing(sqlite3.connect(self.path)) as database:
            database.execute("BEGIN IMMEDIATE")
            database.execute("DELETE FROM staged_objects")
            database.executemany(
                "INSERT INTO staged_objects VALUES (?,?,?,?)",
                values,
            )
            database.commit()
        return len(values)

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


def _read_review_rows(
    review_root: Path,
    *,
    expected_source_id: str,
    expected_storage_type: str,
    expected_prefix: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, int]]:
    rows_path = review_root / REVIEW_ROWS_MEMBER
    if not rows_path.is_file() or rows_path.is_symlink():
        raise RemoteMaterialImportError(
            "REMOTE_MATERIAL_REVIEW_INVALID",
            "review candidate stream is missing",
            422,
        )
    candidates: list[dict[str, Any]] = []
    staged: list[dict[str, Any]] = []
    counts: dict[str, int] = {}
    seen: set[str] = set()
    with rows_path.open("r", encoding="utf-8") as stream:
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
            prefix = safe_member_path(expected_prefix)
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
            if status == "IMPORTABLE":
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
                staged.append({
                    **candidate,
                    "payload_member": member.as_posix(),
                })
            counts[status] = counts.get(status, 0) + 1
            candidates.append(candidate)
    return candidates, staged, counts


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
        if (
            not isinstance(meta, dict)
            or int(meta.get("schema_version") or 0) != REVIEW_SCHEMA_VERSION
            or str(meta.get("task_id") or "") != str(task_id)
            or str(meta.get("project_id") or "") != str(project_id)
            or int(meta.get("execution_generation") or 0) != int(execution_generation)
            or str(meta.get("mode") or "") != "zip_scan"
            or str(meta.get("import_format") or "") != "images"
            or str(meta.get("storage_source_id") or "") != expected_source_id
            or str(meta.get("storage_type") or "") != expected_storage_type
            or str(meta.get("target_prefix") or "") != safe_member_path(expected_prefix).as_posix()
        ):
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_REVIEW_INVALID",
                "review metadata does not match the durable import request",
                409,
            )
        candidates, staged, counts = _read_review_rows(
            review_root,
            expected_source_id=expected_source_id,
            expected_storage_type=expected_storage_type,
            expected_prefix=expected_prefix,
        )
        if int(meta.get("candidate_count") or -1) != len(candidates):
            raise RemoteMaterialImportError(
                "REMOTE_MATERIAL_REVIEW_INVALID",
                "review candidate count does not reconcile",
                409,
            )

        candidate_store = ImportCandidateStore(
            artifacts.artifact_path(task_id, MANIFEST_REF)
        )
        candidate_store.upsert_many(candidates)
        staging_store = RemoteMaterialStagingStore(
            artifacts.artifact_path(task_id, REMOTE_MATERIAL_STAGING_REF)
        )
        staging_store.replace_many(staged)

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

        scanned = len(candidates)
        result = {
            "stage": "awaiting_confirmation",
            "mode": "agent_zip_scan",
            "storage_source_id": expected_source_id,
            "prefix": safe_member_path(expected_prefix).as_posix(),
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
            "import_format": "images",
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
    "RemoteMaterialImportError",
    "RemoteMaterialStagingStore",
    "build_material_review_archive",
    "commit_material_review_archive",
]
