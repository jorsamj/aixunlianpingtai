from __future__ import annotations

import hashlib
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable, Iterator

from PIL import Image, UnidentifiedImageError

from platform_core.material_repository import MaterialRepository
from platform_core.secrets import KeyringSecretStore, SecretCredentialStore
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskStatus

from .errors import redact_storage_error
from .factory import StorageProviderFactory
from .import_candidates import ImportCandidateStore
from .source_repository import StorageSourceRepository


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
MANIFEST_REF = "scan/candidates.sqlite3"
SCAN_RESULT_REF = "scan/result.json"
FINAL_RESULT_REF = "scan/final.json"
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
    def _flush_scan_batch(store, materials, rows: list[dict[str, Any]]) -> None:
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
        source, provider = self._source_and_provider(context, request)
        materials = MaterialRepository(
            self.data_dir / "projects" / context.task.project_id
        )
        prefix = str(request.get("prefix") or "")
        recursive = bool(request.get("recursive", True))
        store = ImportCandidateStore(
            context.artifacts.artifact_path(context.task.task_id, MANIFEST_REF)
        )
        batch: list[dict[str, Any]] = []
        current_key = ""
        for item in iter_provider_objects(provider, prefix, recursive):
            if context.cancel_requested():
                self._flush_scan_batch(store, materials, batch)
                return TaskStatus.CANCELLED, None
            current_key = str(item.key)
            batch.append(self._inspect(provider, source, item))
            if len(batch) >= BATCH_SIZE:
                self._flush_scan_batch(store, materials, batch)
                self._checkpoint_scan(context, store, current_key)
        self._flush_scan_batch(store, materials, batch)
        self._checkpoint_scan(context, store, current_key)

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
        checkpoint = context.load_checkpoint()
        newly_imported = max(0, int(checkpoint.get("newly_imported", 0) or 0))
        index_duplicates = max(0, int(checkpoint.get("index_duplicates", 0) or 0))
        indexed_at_least = max(0, int(checkpoint.get("indexed_at_least", 0) or 0))

        while True:
            if context.cancel_requested():
                return TaskStatus.CANCELLED, None
            batch = store.pending_index_batch(BATCH_SIZE)
            if not batch:
                break
            ids = [str(row["image_id"]) for row in batch]
            by_id = {row["id"]: row for row in materials.get_many(ids)}
            existing_references = materials.find_existing_storage_references(
                (row["storage_source_id"], row["object_key"]) for row in batch
            )
            existing_hashes = materials.find_existing_content_hashes(
                row["content_sha256"] for row in batch
            )
            records: list[dict[str, Any]] = []
            acknowledged: list[dict[str, Any]] = []
            accepted_hashes: set[str] = set()
            accepted_references: set[tuple[str, str]] = set()
            for row in batch:
                current = by_id.get(str(row["image_id"]))
                if current is not None:
                    if (
                        str(current.get("storage_source_id")) != str(row["storage_source_id"])
                        or str(current.get("object_key")) != str(row["object_key"])
                        or str(current.get("content_sha256")) != str(row["content_sha256"])
                    ):
                        raise ValueError(
                            f"stable image_id collision for {row['object_key']}"
                        )
                    acknowledged.append(row)
                    continue
                reference = (str(row["storage_source_id"]), str(row["object_key"]))
                content_hash = str(row["content_sha256"])
                if (
                    reference in existing_references
                    or reference in accepted_references
                    or content_hash in existing_hashes
                    or content_hash in accepted_hashes
                ):
                    index_duplicates += 1
                    acknowledged.append(row)
                    continue
                records.append(self._material_record(row, context.task.project_id))
                acknowledged.append(row)
                accepted_references.add(reference)
                accepted_hashes.add(content_hash)
            if records:
                materials.upsert_many(records)
                newly_imported += len(records)
            store.mark_indexed(acknowledged)
            # Checkpoint a true lower bound. Counting only one pending page would
            # overstate progress when more than 500 candidates remain.
            indexed_at_least = min(selected_count, indexed_at_least + len(acknowledged))
            checkpoint = {
                "stage": "indexing",
                "selected": selected_count,
                "indexed_at_least": indexed_at_least,
                "newly_imported": newly_imported,
                "index_duplicates": index_duplicates,
                "current_object": batch[-1]["object_key"],
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
        return self._scan(context, request)

    def recover(self, context):
        request = self._request(context)
        confirmation = context.artifacts.read_json(
            context.task.task_id, "scan/confirmation.json", default=None,
        )
        if isinstance(confirmation, dict) and confirmation.get("accepted") is True:
            return self._index_confirmed(context, request)
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
