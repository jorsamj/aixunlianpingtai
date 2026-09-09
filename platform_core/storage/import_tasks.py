from __future__ import annotations

import hashlib
import json
import os
import time
from contextlib import closing
from dataclasses import asdict
from pathlib import Path
from typing import Any, Iterable, Iterator

from PIL import Image, UnidentifiedImageError

from platform_core.material_repository import MaterialRepository
from platform_core.annotation_repository import AnnotationRepository
from platform_core.annotations import annotation_summary
from platform_core.secrets import KeyringSecretStore, SecretCredentialStore
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskStatus

from .errors import redact_storage_error
from .factory import StorageProviderFactory
from .import_candidates import ImportCandidateStore
from .import_confirmation import mapping_suggestions
from .models import StorageType
from .source_repository import StorageSourceRepository
from .yolo_import import YoloImportError, YoloImportScanner, YoloScanCancelled
from .zip_import import (
    ExtractionCancelled,
    ServerZipImportError,
    UnsafeArchive,
    extract_server_zip,
    finalize_server_zip_publication,
    resolve_server_zip,
)


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MANIFEST_REF = "scan/candidates.sqlite3"
SCAN_RESULT_REF = "scan/result.json"
FINAL_RESULT_REF = "scan/final.json"
ERROR_RESULT_REF = "scan/error.json"
BATCH_SIZE = 500


def _sha256_stream(stream) -> str:
    digest = hashlib.sha256()
    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
        digest.update(chunk)
    return digest.hexdigest()


def _provider(data_dir: Path, project_id: str, source):
    credentials = {}
    if source.secret_ref:
        try:
            credentials = SecretCredentialStore(KeyringSecretStore()).get(source.secret_ref) or {}
        except Exception as error:
            raise EnvironmentError(
                f"storage credential is unavailable: {redact_storage_error(error)}"
            ) from error
    return StorageProviderFactory(
        data_dir=data_dir,
        project_dir=data_dir / "projects" / project_id,
        credentials={source.id: credentials},
    ).create(source)


def iter_provider_objects(provider, prefix: str, recursive: bool) -> Iterator[Any]:
    """Use provider streaming capability when available, otherwise bounded pages."""
    streaming = getattr(provider, "iter_objects", None)
    if callable(streaming):
        yield from streaming(prefix, recursive=recursive)
        return
    cursor = None
    while True:
        page = provider.list_objects(
            prefix, recursive=recursive, cursor=cursor, limit=BATCH_SIZE,
        )
        yield from page.items
        if not page.next_cursor:
            return
        cursor = page.next_cursor


def _stored_name(image_id: str, object_key: str) -> str:
    suffix = Path(object_key).suffix.lower()
    return f"{image_id}{suffix}" if suffix in IMAGE_EXTENSIONS else f"{image_id}.img"


def server_import_dir(data_dir: Path) -> Path:
    configured = os.environ.get("MC_SERVER_IMPORT_DIR", "").strip()
    return (
        Path(configured).expanduser() if configured else data_dir / "imports"
    ).resolve()


class StorageImportHandler:
    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).resolve()

    @staticmethod
    def _request(context) -> dict[str, Any]:
        request = context.artifacts.read_json(
            context.task.task_id, context.task.payload_ref, default={},
        )
        return dict(request) if isinstance(request, dict) else {}

    def _source_and_provider(self, context, request):
        source_id = str(request.get("storage_source_id") or "")
        if not source_id:
            raise ValueError("storage_source_id is required")
        sources = StorageSourceRepository(
            self.data_dir / "storage" / "storage_sources.sqlite3"
        )
        source = sources.get(source_id)
        if source is None:
            raise FileNotFoundError(f"storage source does not exist: {source_id}")
        if not source.enabled:
            raise EnvironmentError("storage source is disabled")
        provider = _provider(self.data_dir, context.task.project_id, source)
        health = provider.health_check()
        if not health.ok:
            raise EnvironmentError(redact_storage_error(health.message))
        return source, provider

    @staticmethod
    def _inspect(provider, source, item) -> dict[str, Any]:
        key = str(item.key)
        base = {
            "filename": Path(key).name,
            "storage_source_id": source.id,
            "storage_type": source.type,
            "object_key": key,
            "content_sha256": "",
            "size_bytes": max(0, int(item.size_bytes or 0)),
            "etag": str(item.etag or ""),
            "width": 0,
            "height": 0,
            "status": "SKIPPED",
            "error": "",
            "duplicate": False,
        }
        if Path(key).suffix.lower() not in IMAGE_EXTENSIONS:
            return base
        try:
            with closing(provider.open_reader(key)) as stream:
                with Image.open(stream) as image:
                    width, height = image.size
                    image.verify()
            content_sha256 = str(item.sha256 or "").strip().lower()
            if len(content_sha256) != 64 or any(
                character not in "0123456789abcdef" for character in content_sha256
            ):
                with closing(provider.open_reader(key)) as stream:
                    content_sha256 = _sha256_stream(stream)
            if int(item.size_bytes or 0) <= 0:
                raise ValueError("image object is empty")
            base.update({
                "content_sha256": content_sha256,
                "width": int(width),
                "height": int(height),
                "status": "IMPORTABLE",
            })
        except (UnidentifiedImageError, OSError, ValueError) as error:
            base.update({"status": "INVALID", "error": redact_storage_error(error)})
        except Exception as error:
            base.update({"status": "FAILED", "error": redact_storage_error(error)})
        return base

    @staticmethod
    def _flush_scan_batch(store, materials, rows: list[dict[str, Any]], supplement=False) -> None:
        if not rows:
            return
        valid = [row for row in rows if row["status"] == "IMPORTABLE"]
        hashes = [str(row["content_sha256"]) for row in valid]
        material_hashes = materials.find_existing_content_hashes(hashes)
        manifest_hashes = store.find_content_hashes(hashes)
        material_references = materials.find_existing_storage_references(
            (row["storage_source_id"], row["object_key"]) for row in valid
        )
        batch_hashes: set[str] = set()
        for row in valid:
            content_hash = str(row["content_sha256"])
            reference = (str(row["storage_source_id"]), str(row["object_key"]))
            if supplement and reference in material_references:
                # The same object is a metadata/annotation update, not a second material.
                batch_hashes.add(content_hash)
                continue
            if (
                reference in material_references
                or content_hash in material_hashes
                or content_hash in manifest_hashes
                or content_hash in batch_hashes
            ):
                row["status"] = "DUPLICATE"
                row["duplicate"] = True
            batch_hashes.add(content_hash)
        store.upsert_many(rows)
        rows.clear()

    @staticmethod
    def _checkpoint_scan(context, store, current_key: str) -> None:
        counts = store.counts()
        scanned = sum(counts.values())
        checkpoint = {
            **context.load_checkpoint(),
            "stage": "SCANNING",
            "scanned_files": scanned,
            "importable_images": counts.get("IMPORTABLE", 0),
            "duplicates": counts.get("DUPLICATE", 0),
            "invalid_images": counts.get("INVALID", 0),
            "skipped_files": counts.get("SKIPPED", 0),
            "failed": counts.get("FAILED", 0),
            "current_object": current_key,
        }
        context.save_checkpoint(checkpoint)
        context.repository.heartbeat(
            context.task.task_id,
            context.lease.lease_token,
            stage="SCANNING",
            current_item=(
                f"已扫描 {scanned} 个对象 · 可导入 {counts.get('IMPORTABLE', 0)} 张 · "
                f"重复 {counts.get('DUPLICATE', 0)} · "
                f"失败 {counts.get('FAILED', 0) + counts.get('INVALID', 0)} · 当前 {current_key}"
            ),
        )

    def _scan(self, context, request):
        try:
            return self._scan_impl(context, request)
        except YoloScanCancelled:
            return TaskStatus.CANCELLED, None
        except YoloImportError as error:
            context.artifacts.atomic_write_json(context.task.task_id, ERROR_RESULT_REF, {
                "stage": "failed", "mode": str(request.get("mode") or "storage_scan"),
                "error": error.to_public_dict(),
            })
            return TaskStatus.FAILED, ERROR_RESULT_REF

    def _scan_impl(self, context, request):
        source, provider = self._source_and_provider(context, request)
        materials = MaterialRepository(
            self.data_dir / "projects" / context.task.project_id
        )
        prefix = str(request.get("prefix") or "")
        recursive = bool(request.get("recursive", True))
        store = ImportCandidateStore(
            context.artifacts.artifact_path(context.task.task_id, MANIFEST_REF)
        )
        last_heartbeat = time.monotonic()

        def yolo_progress(key):
            nonlocal last_heartbeat
            if time.monotonic() - last_heartbeat >= 5:
                context.repository.heartbeat(
                    context.task.task_id, context.lease.lease_token,
                    stage="SCANNING", current_item=f"YOLO 数据集分析：{key}",
                )
                last_heartbeat = time.monotonic()

        scanner = YoloImportScanner(
            provider, store, iter_provider_objects, cancelled=context.cancel_requested,
            progress=yolo_progress,
        )
        # Payloads created before format selection was introduced retain image-only behavior.
        import_format = scanner.prepare(
            str(request.get("import_format", "images")), prefix=prefix, recursive=recursive,
            dataset_yaml=request.get("dataset_yaml") or request.get("yaml_key"),
        )
        if import_format == "yolo":
            objects = scanner.iter_images()
        elif request.get("import_format") == "auto":
            objects = scanner.iter_inventory()
        else:
            objects = iter_provider_objects(provider, prefix, recursive)
        batch: list[dict[str, Any]] = []
        current_key = ""
        for item in objects:
            if context.cancel_requested():
                self._flush_scan_batch(store, materials, batch, import_format == 'yolo')
                return TaskStatus.CANCELLED, None
            current_key = str(item.key)
            batch.append(self._inspect(provider, source, item))
            if len(batch) >= BATCH_SIZE:
                self._flush_scan_batch(store, materials, batch, import_format == 'yolo')
                self._checkpoint_scan(context, store, current_key)
        self._flush_scan_batch(store, materials, batch, import_format == 'yolo')
        self._checkpoint_scan(context, store, current_key)
        quality = scanner.scan_annotations() if import_format == "yolo" else None

        counts = store.counts()
        scanned = sum(counts.values())
        result = {
            "stage": "awaiting_confirmation",
            "mode": str(request.get("mode") or "storage_scan"),
            "storage_source_id": source.id,
            "prefix": prefix,
            "recursive": recursive,
            "scanned_files": scanned,
            "importable_images": counts.get("IMPORTABLE", 0),
            "duplicates": counts.get("DUPLICATE", 0),
            "invalid_images": counts.get("INVALID", 0),
            "skipped_files": counts.get("SKIPPED", 0),
            "failed": counts.get("FAILED", 0),
            # Compatibility summary fields used by the existing UI.
            "scanned": scanned,
            "importable": counts.get("IMPORTABLE", 0),
            "manifest_ref": MANIFEST_REF,
            "failure_examples": store.failure_page(limit=200),
        }
        if "import_format" in request or import_format == "yolo":
            result["import_format"] = import_format
        if quality is not None:
            result.update({"dataset_yaml": scanner.yaml_key, "quality": quality})
            meta_path = self.data_dir / 'projects' / context.task.project_id / 'meta.json'
            meta = json.loads(meta_path.read_text(encoding='utf-8'))
            labels = [{**(meta.get('label_meta', [])[i] if i < len(meta.get('label_meta', [])) else {}), 'code': code}
                      for i, code in enumerate(meta.get('labels') or [])]
            result['external_classes'] = mapping_suggestions(store.external_classes(), labels)
        context.repository.heartbeat(
            context.task.task_id,
            context.lease.lease_token,
            progress=99,
            stage="FINALIZING",
            current_item=(
                f"扫描完成：{scanned} 个对象，可导入 {counts.get('IMPORTABLE', 0)} 张"
            ),
        )
        context.artifacts.atomic_write_json(
            context.task.task_id, SCAN_RESULT_REF, result,
        )
        return TaskStatus.AWAITING_CONFIRMATION, SCAN_RESULT_REF

    @staticmethod
    def _zip_error(
        context, error: ServerZipImportError, live_state: dict[str, Any] | None = None,
    ) -> str:
        checkpoint = context.load_checkpoint()
        zip_state = checkpoint.get("zip_import")
        zip_state = zip_state if isinstance(zip_state, dict) else {}
        if live_state:
            zip_state = {**zip_state, **live_state}
        result = {
            "stage": "cancelled" if isinstance(error, ExtractionCancelled) else "failed",
            "mode": "server_zip",
            "error": {
                "code": error.code,
                "message": error.message,
                "detail": error.detail,
                "solution": error.solution,
                "context": dict(error.context),
            },
            "extracted_files": max(0, int(zip_state.get("extracted_files") or 0)),
            "extracted_bytes": max(0, int(zip_state.get("extracted_bytes") or 0)),
            "declared_files": max(0, int(zip_state.get("declared_files") or 0)),
            "declared_bytes": max(0, int(zip_state.get("declared_bytes") or 0)),
            "current_file": str(zip_state.get("current_file") or ""),
        }
        context.artifacts.atomic_write_json(
            context.task.task_id, ERROR_RESULT_REF, result,
        )
        return ERROR_RESULT_REF

    def _server_zip_source(self, context, request):
        source_id = str(request.get("storage_source_id") or "")
        source = StorageSourceRepository(
            self.data_dir / "storage" / "storage_sources.sqlite3"
        ).get(source_id)
        if source is None:
            raise UnsafeArchive(
                "The storage source does not exist",
                code="ZIP_LOCAL_STORAGE_REQUIRED",
                solution="Choose an existing local storage source.",
            )
        # Reject remote providers before resolving credentials or performing a
        # health check. Server ZIP publication requires an atomic local rename.
        if StorageType.parse(source.type) is not StorageType.LOCAL:
            raise UnsafeArchive(
                "Server ZIP import requires a local storage source",
                code="ZIP_LOCAL_STORAGE_REQUIRED",
                solution="Choose a configured local storage source for server ZIP import.",
            )
        source, provider = self._source_and_provider(context, request)
        root = getattr(provider, "root", None)
        if not isinstance(root, Path):
            raise UnsafeArchive(
                "The local storage provider does not expose a physical root",
                code="ZIP_LOCAL_STORAGE_REQUIRED",
                solution="Repair or replace the configured local storage provider.",
            )
        target_prefix = str(request.get("target_prefix") or "").strip()
        if not target_prefix:
            raise UnsafeArchive(
                "target_prefix is required for server ZIP import",
                code="ZIP_TARGET_REQUIRED",
                solution="Choose a new, non-empty directory under the local storage root.",
            )
        zip_path = str(request.get("zip_path") or "")
        archive = resolve_server_zip(server_import_dir(self.data_dir), zip_path)
        return source, provider, root, target_prefix, zip_path, archive

    def _server_zip(self, context, request):
        live_state: dict[str, Any] = {}
        try:
            _source, _provider, root, target_prefix, zip_path, archive = (
                self._server_zip_source(context, request)
            )
            checkpoint = context.load_checkpoint()
            saved = checkpoint.get("zip_import")
            saved = dict(saved) if isinstance(saved, dict) else {}
            if saved.get("published") is True:
                if (
                    saved.get("target_prefix") != target_prefix
                    or saved.get("zip_path") != zip_path
                ):
                    raise UnsafeArchive(
                        "Server ZIP request no longer matches its durable checkpoint",
                        code="ZIP_CHECKPOINT_MISMATCH",
                        solution="Create a new import task instead of changing a running task.",
                    )
                finalize_server_zip_publication(
                    root, target_prefix, task_id=context.task.task_id,
                )
            else:
                completed = saved.get("completed_members")
                completed = completed if isinstance(completed, dict) else {}

                def on_extract(progress):
                    if progress.completed_member is not None:
                        completed[progress.completed_member.name] = asdict(
                            progress.completed_member
                        )
                    state = {
                        "zip_path": zip_path,
                        "target_prefix": target_prefix,
                        "published": False,
                        "completed_members": completed,
                        "extracted_files": progress.extracted_files,
                        "extracted_bytes": progress.extracted_bytes,
                        "declared_files": progress.declared_files,
                        "declared_bytes": progress.declared_bytes,
                        "current_file": progress.current_member,
                    }
                    live_state.clear()
                    live_state.update(state)
                    # Persist only completed members. Chunk heartbeats remain live
                    # without rewriting an ever-growing checkpoint every MiB.
                    if progress.completed_member is not None:
                        context.save_checkpoint({"stage": "extracting", "zip_import": state})
                    percent = (
                        min(45.0, 45.0 * progress.extracted_bytes / progress.declared_bytes)
                        if progress.declared_bytes else 0.0
                    )
                    context.repository.heartbeat(
                        context.task.task_id,
                        context.lease.lease_token,
                        progress=percent,
                        stage="extracting",
                        current_item=(
                            f"已解压 {progress.extracted_files} 个文件 · "
                            f"{progress.extracted_bytes} 字节 · 当前 {progress.current_member}"
                        ),
                    )
                    return not context.cancel_requested()

                if context.cancel_requested():
                    return TaskStatus.CANCELLED, None
                report = extract_server_zip(
                    archive,
                    root,
                    target_prefix,
                    task_id=context.task.task_id,
                    completed=completed,
                    on_progress=on_extract,
                )
                state = {
                    "zip_path": zip_path,
                    "target_prefix": target_prefix,
                    "published": True,
                    "completed_members": {
                        name: asdict(record) for name, record in report.members.items()
                    },
                    "extracted_files": report.extracted_files,
                    "extracted_bytes": report.extracted_bytes,
                    "declared_files": report.extracted_files,
                    "declared_bytes": report.extracted_bytes,
                    "current_file": "",
                }
                # This checkpoint precedes marker removal. A crash before it is
                # recovered through the task-owned marker and verified records.
                context.save_checkpoint({"stage": "published", "zip_import": state})
                finalize_server_zip_publication(
                    root, target_prefix, task_id=context.task.task_id,
                )

            scan_request = dict(request)
            scan_request["prefix"] = target_prefix
            scan_request["recursive"] = bool(request.get("recursive", True))
            return self._scan(context, scan_request)
        except ExtractionCancelled as error:
            return TaskStatus.CANCELLED, self._zip_error(context, error, live_state)
        except ServerZipImportError as error:
            return TaskStatus.FAILED, self._zip_error(context, error, live_state)

    @staticmethod
    def _material_record(row: dict[str, Any], project_id: str) -> dict[str, Any]:
        image_id = str(row["image_id"])
        key = str(row["object_key"])
        return {
            "id": image_id,
            "filename": row.get("filename") or Path(key).name,
            "stored_name": _stored_name(image_id, key),
            "storage_source_id": row["storage_source_id"],
            "storage_type": row["storage_type"],
            "object_key": key,
            "content_sha256": row["content_sha256"],
            "size_bytes": row["size_bytes"],
            "etag": row.get("etag") or "",
            "width": row["width"],
            "height": row["height"],
            "url": f"/api/v61/projects/{project_id}/materials/{image_id}/content",
            "source_type": "storage_import",
            "processing_status": "pending_decision",
            "split": "unassigned",
            "labels": [],
            "box_count": 0,
            "annotated": False,
            "annotation_state": "unannotated",
        }

    @staticmethod
    def _reconcile_selected(store, materials) -> tuple[int, int, int]:
        """Return exact selected, indexed, and material counts in bounded pages."""
        selected = indexed = imported = 0
        page: list[dict[str, Any]] = []

        def reconcile_page() -> None:
            nonlocal imported
            if not page:
                return
            persisted = {
                str(row["id"]): row
                for row in materials.get_many(str(row["image_id"]) for row in page)
            }
            for row in page:
                current = persisted.get(str(row["image_id"]))
                if current is not None and (
                    str(current.get("storage_source_id")) == str(row["storage_source_id"])
                    and str(current.get("object_key")) == str(row["object_key"])
                    and str(current.get("content_sha256")) == str(row["content_sha256"])
                ):
                    imported += 1
            page.clear()

        for row in store.iter_status("IMPORTABLE", batch_size=BATCH_SIZE):
            if not row.get("selected"):
                continue
            selected += 1
            indexed += int(bool(row.get("indexed")))
            page.append(row)
            if len(page) == BATCH_SIZE:
                reconcile_page()
        reconcile_page()
        return selected, indexed, imported

    def _index_confirmed(self, context, request):
        confirmation = context.artifacts.read_json(
            context.task.task_id, "scan/confirmation.json", default=None,
        )
        if not isinstance(confirmation, dict) or confirmation.get("accepted") is not True:
            raise ValueError("material import confirmation is missing")
        store = ImportCandidateStore(
            context.artifacts.artifact_path(context.task.task_id, MANIFEST_REF)
        )
        load_legacy_candidates(context.artifacts, context.task.task_id, store)
        selected_count = max(0, int(confirmation.get("selected_count") or 0))
        # Legacy confirmations did not persist selected flags. They always meant
        # "all candidates" unless an explicit key list was present.
        has_persisted_selection = any(
            bool(row.get("selected"))
            for row in store.iter_status("IMPORTABLE", batch_size=BATCH_SIZE)
        )
        if selected_count and not has_persisted_selection:
            legacy_keys = confirmation.get("object_keys") or confirmation.get("selected_keys")
            if legacy_keys is not None:
                store.confirm(legacy_keys)
            elif isinstance(
                context.artifacts.read_json(
                    context.task.task_id, SCAN_RESULT_REF, default=None,
                ), dict,
            ):
                store.confirm(row["object_key"] for row in store.iter_status("IMPORTABLE"))

        store.assign_image_ids(context.task.task_id, batch_size=BATCH_SIZE)
        materials = MaterialRepository(
            self.data_dir / "projects" / context.task.project_id
        )
        annotations = AnnotationRepository(self.data_dir / 'projects' / context.task.project_id)
        project_meta_path = self.data_dir / 'projects' / context.task.project_id / 'meta.json'
        project_meta = json.loads(project_meta_path.read_text(encoding='utf-8'))
        label_ids = {code: i for i, code in enumerate(project_meta.get('labels') or [])
                     if i >= len(project_meta.get('label_meta') or [])
                     or (project_meta['label_meta'][i] or {}).get('status', 'active') == 'active'}
        checkpoint = context.load_checkpoint()
        newly_imported = max(0, int(checkpoint.get("newly_imported", 0) or 0))
        index_duplicates = max(0, int(checkpoint.get("index_duplicates", 0) or 0))
        indexed_at_least = max(0, int(checkpoint.get("indexed_at_least", 0) or 0))
        progress_counts = store.indexing_counts()

        while True:
            if context.cancel_requested():
                return TaskStatus.CANCELLED, None
            batch = store.pending_index_batch(BATCH_SIZE)
            if not batch:
                break
            by_reference = materials.get_by_storage_references(
                (row["storage_source_id"], row["object_key"]) for row in batch
            )
            for row in batch:
                current = by_reference.get((row['storage_source_id'], row['object_key']))
                row['existing_material'] = current is not None
                if current is not None:
                    row['image_id'] = current['id']
            store.bind_index_batch(batch)
            by_id = {r['id']: r for r in materials.get_many(row['image_id'] for row in batch)}
            imported_annotations = store.annotations_for_keys(row['object_key'] for row in batch)
            skipped = store.skipped_boxes_for_keys(row['object_key'] for row in batch)
            records, annotation_rows = [], []
            for row in batch:
                current = by_id.get(row['image_id'])
                if current and (current['storage_source_id'], current['object_key']) != (row['storage_source_id'], row['object_key']):
                    raise ValueError('stable image_id collision')
                record = dict(current) if current else self._material_record(row, context.task.project_id)
                for field in ('content_sha256', 'size_bytes', 'etag', 'width', 'height'):
                    record[field] = row[field]
                candidate = imported_annotations.get(row['object_key'])
                row['boxes_skipped'] = skipped.get(row['object_key'], 0)
                if candidate:
                    record['imported_split'] = candidate['split']
                    boxes = []
                    for box in candidate['boxes']:
                        code = (confirmation.get('label_mapping') or {}).get(str(box['class_id']))
                        if code not in label_ids:
                            raise ValueError('confirmed platform label is no longer active; resolve the label before retrying')
                        width, height = float(row['width']), float(row['height'])
                        boxes.append({'id': f"{row['image_id']}-{box['line_number']}",
                            'label': code, 'class_id': label_ids[code],
                            'x1': max(0.0, (box['cx']-box['w']/2)*width),
                            'y1': max(0.0, (box['cy']-box['h']/2)*height),
                            'x2': min(width, (box['cx']+box['w']/2)*width),
                            'y2': min(height, (box['cy']+box['h']/2)*height)})
                    state = 'annotated' if boxes else ('confirmed_empty' if candidate['annotation_status'] == 'confirmed_empty' else 'unannotated')
                    # A missing/invalid sidecar cannot erase an existing annotation.
                    if boxes or state == 'confirmed_empty' or not current:
                        annotation_rows.append({'image_id': row['image_id'], 'boxes': boxes, 'annotation_state': state})
                        record.update(annotation_summary(boxes, state))
                        record['annotation_summary_at'] = confirmation['confirmed_at']
                        if state != 'unannotated':
                            record['processing_status'] = 'processed'
                        row.update(annotations_written=int(state != 'unannotated'),
                                   boxes_imported=len(boxes), negative_samples=int(state == 'confirmed_empty'))
                records.append(record)
            # Material identity is durable before annotation writes. Replaying the
            # same deterministic boxes preserves annotation version/content digest.
            materials.upsert_many(records)
            annotations.upsert_many(annotation_rows)
            store.record_annotation_outcomes(batch)
            store.mark_indexed(batch)
            for row in batch:
                for counter in ('annotations_written', 'boxes_imported', 'boxes_skipped', 'negative_samples'):
                    progress_counts[counter] += row.get(counter, 0)
                progress_counts['existing_materials_updated' if row['existing_material'] else 'new_materials_indexed'] += 1
            newly_imported = progress_counts['new_materials_indexed']
            # Checkpoint a true lower bound. Counting only one pending page would
            # overstate progress when more than 500 candidates remain.
            indexed_at_least = min(selected_count, indexed_at_least + len(batch))
            checkpoint = {
                "stage": "indexing",
                "selected": selected_count,
                "indexed_at_least": indexed_at_least,
                "newly_imported": newly_imported,
                "index_duplicates": index_duplicates,
                "current_object": batch[-1]["object_key"],
                **progress_counts,
            }
            context.save_checkpoint(checkpoint)
            context.repository.heartbeat(
                context.task.task_id,
                context.lease.lease_token,
                stage="indexing",
                current_item=f"正在建立素材索引：已处理 {checkpoint['indexed_at_least']} / {selected_count}",
            )

        if store.pending_index_batch(1):
            raise RuntimeError("material import candidate reconciliation failed")
        selected, indexed, imported = self._reconcile_selected(store, materials)
        if selected != selected_count or indexed != selected_count:
            raise RuntimeError(
                "material import candidate counts do not reconcile with confirmation"
            )
        scan_result = context.artifacts.read_json(
            context.task.task_id, SCAN_RESULT_REF, default={},
        )
        counts = store.counts()
        final = {
            "task_id": context.task.task_id,
            "storage_source_id": request.get("storage_source_id"),
            "manifest_ref": MANIFEST_REF,
            "selected": selected,
            "indexed": indexed,
            "imported": imported,
            "index_duplicates": selected - imported,
            "candidates": sum(counts.values()),
            "importable_images": counts.get("IMPORTABLE", 0),
            "duplicates": counts.get("DUPLICATE", 0),
            "invalid_images": counts.get("INVALID", 0),
            "skipped_files": counts.get("SKIPPED", 0),
            "failed": counts.get("FAILED", 0),
            "scan_result_ref": SCAN_RESULT_REF if isinstance(scan_result, dict) else None,
            **store.indexing_counts(),
        }
        if selected_count > counts.get("IMPORTABLE", 0):
            raise RuntimeError("confirmed candidate count exceeds importable candidate count")
        context.artifacts.atomic_write_json(
            context.task.task_id, FINAL_RESULT_REF, final,
        )
        return TaskStatus.SUCCEEDED, FINAL_RESULT_REF

    def run(self, context):
        request = self._request(context)
        confirmation = context.artifacts.read_json(
            context.task.task_id, "scan/confirmation.json", default=None,
        )
        if isinstance(confirmation, dict) and confirmation.get("accepted") is True:
            return self._index_confirmed(context, request)
        if str(request.get("mode") or "") == "server_zip":
            return self._server_zip(context, request)
        return self._scan(context, request)

    def recover(self, context):
        request = self._request(context)
        confirmation = context.artifacts.read_json(
            context.task.task_id, "scan/confirmation.json", default=None,
        )
        if isinstance(confirmation, dict) and confirmation.get("accepted") is True:
            return self._index_confirmed(context, request)
        if str(request.get("mode") or "") == "server_zip":
            return self._server_zip(context, request)
        result = context.artifacts.read_json(
            context.task.task_id, SCAN_RESULT_REF, default=None,
        )
        manifest = context.artifacts.artifact_path(
            context.task.task_id, MANIFEST_REF,
        )
        if isinstance(result, dict) and manifest.is_file():
            return TaskStatus.AWAITING_CONFIRMATION, SCAN_RESULT_REF
        return self._scan(context, request)


def commit_storage_import(
    data_dir: str | Path, project_id: str, artifacts: ArtifactStore,
    task_id: str, selected_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Persist a bounded confirmation; indexing belongs to the durable worker.

    Kept as a compatibility entry point until all callers use the confirmation
    route directly. This function deliberately performs no material writes.
    """
    del data_dir, project_id
    result = artifacts.read_json(task_id, SCAN_RESULT_REF, default=None)
    if not isinstance(result, dict):
        raise ValueError("storage scan result does not exist")
    if result.get('import_format') == 'yolo':
        raise ValueError('YOLO imports require the label-mapping confirmation API')
    store = ImportCandidateStore(artifacts.artifact_path(task_id, MANIFEST_REF))
    load_legacy_candidates(artifacts, task_id, store)
    keys = selected_keys
    if keys is None:
        keys = (row["object_key"] for row in store.iter_status("IMPORTABLE"))
    selection = store.confirm(keys)
    confirmation = {
        "accepted": True,
        "selection_digest": selection.digest,
        "selected_count": selection.selected_count,
        "confirmed_at": selection.confirmed_at,
    }
    artifacts.atomic_write_json(task_id, "scan/confirmation.json", confirmation)
    return confirmation


def load_legacy_candidates(
    artifacts: ArtifactStore, task_id: str, store: ImportCandidateStore,
) -> int:
    """Migrate the bounded legacy JSON candidate list into the durable manifest."""
    result = artifacts.read_json(task_id, SCAN_RESULT_REF, default=None)
    if not isinstance(result, dict) or not isinstance(result.get("candidates"), list):
        return 0
    return store.upsert_many(
        {
            **candidate,
            "status": candidate.get("status") or "IMPORTABLE",
            "error": candidate.get("error") or "",
            "duplicate": bool(candidate.get("duplicate", False)),
        }
        for candidate in result["candidates"]
        if isinstance(candidate, dict)
    )


def worker_registration(data_dir: Path):
    return {
        "handlers": {TaskKind.MATERIAL_IMPORT: StorageImportHandler(data_dir)},
        "capabilities": {"storage.import"},
    }
