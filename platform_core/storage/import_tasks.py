from __future__ import annotations

import hashlib
import uuid
from contextlib import closing
from pathlib import Path
from typing import Any, Iterable

from PIL import Image

from platform_core.material_repository import MaterialRepository
from platform_core.secrets import KeyringSecretStore, SecretCredentialStore
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskStatus

from .errors import redact_storage_error
from .factory import StorageProviderFactory
from .source_repository import StorageSourceRepository


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}


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
            raise EnvironmentError(f"storage credential is unavailable: {redact_storage_error(error)}") from error
    return StorageProviderFactory(
        data_dir=data_dir,
        project_dir=data_dir / "projects" / project_id,
        credentials={source.id: credentials},
    ).create(source)


class StorageImportHandler:
    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).resolve()

    def run(self, context):
        request = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
        source_id = str((request or {}).get("storage_source_id") or "")
        if not source_id:
            raise ValueError("storage_source_id is required")
        sources = StorageSourceRepository(self.data_dir / "storage" / "storage_sources.sqlite3")
        source = sources.get(source_id)
        if source is None:
            raise FileNotFoundError(f"storage source does not exist: {source_id}")
        provider = _provider(self.data_dir, context.task.project_id, source)
        health = provider.health_check()
        if not health.ok:
            raise EnvironmentError(health.message)
        materials = MaterialRepository(self.data_dir / "projects" / context.task.project_id)
        prefix = str((request or {}).get("prefix") or "")
        recursive = bool((request or {}).get("recursive", True))
        cursor = None
        scanned = duplicates = failed = 0
        candidates: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        while True:
            if context.cancel_requested():
                return TaskStatus.CANCELLED, None
            page = provider.list_objects(prefix, recursive=recursive, cursor=cursor, limit=500)
            if not page.items:
                break
            for item in page.items:
                scanned += 1
                key = str(item.key)
                if Path(key).suffix.lower() in IMAGE_EXTENSIONS:
                    if materials.find_by_storage_reference(source_id, key):
                        duplicates += 1
                    else:
                        try:
                            with closing(provider.open_reader(key)) as stream:
                                with Image.open(stream) as image:
                                    width, height = image.size
                            content_sha256 = str(item.sha256 or "")
                            if not content_sha256:
                                with closing(provider.open_reader(key)) as stream:
                                    content_sha256 = _sha256_stream(stream)
                            if len(content_sha256) != 64 or item.size_bytes <= 0:
                                raise ValueError("object has no verifiable SHA256 or is empty")
                            candidates.append({
                                "filename": Path(key).name,
                                "storage_source_id": source.id,
                                "storage_type": source.type,
                                "object_key": key,
                                "content_sha256": content_sha256,
                                "size_bytes": int(item.size_bytes),
                                "etag": item.etag,
                                "width": int(width),
                                "height": int(height),
                            })
                        except Exception as error:
                            failed += 1
                            failures.append({"object_key": key, "error": redact_storage_error(error)})
                checkpoint = {
                    "stage": "SCANNING", "scanned_files": scanned,
                    "importable_images": len(candidates), "duplicates": duplicates,
                    "failed": failed, "cursor": cursor,
                }
                context.save_checkpoint(checkpoint)
                context.repository.heartbeat(
                    context.task.task_id,
                    context.lease.lease_token,
                    stage="SCANNING",
                    current_item=(
                        f"已扫描 {scanned} 个对象 · 可导入 {len(candidates)} 张 · "
                        f"重复 {duplicates} · 失败 {failed} · 当前 {key}"
                    ),
                )
            if not page.next_cursor:
                break
            cursor = page.next_cursor
        result = {
            "storage_source_id": source.id,
            "prefix": prefix,
            "recursive": recursive,
            "scanned_files": scanned,
            "importable_images": len(candidates),
            # 兼容 v42.22 初版前端字段，避免真实扫描成功后页面错误显示为 0。
            "scanned": scanned,
            "importable": len(candidates),
            "duplicates": duplicates,
            "failed": failed,
            "candidates": candidates,
            "failures": failures[:200],
        }
        context.repository.heartbeat(
            context.task.task_id,
            context.lease.lease_token,
            progress=99,
            stage="FINALIZING",
            current_item=f"扫描完成：{scanned} 个对象，可导入 {len(candidates)} 张",
        )
        context.artifacts.atomic_write_json(context.task.task_id, "scan/result.json", result)
        return TaskStatus.SUCCEEDED, "scan/result.json"

    def recover(self, context):
        result = context.artifacts.read_json(context.task.task_id, "scan/result.json", default=None)
        if isinstance(result, dict):
            return TaskStatus.SUCCEEDED, "scan/result.json"
        return self.run(context)


def commit_storage_import(
    data_dir: str | Path, project_id: str, artifacts: ArtifactStore,
    task_id: str, selected_keys: Iterable[str] | None = None,
) -> dict[str, Any]:
    root = Path(data_dir).resolve()
    result = artifacts.read_json(task_id, "scan/result.json", default=None)
    if not isinstance(result, dict):
        raise ValueError("storage scan result does not exist")
    selected = None if selected_keys is None else {str(value) for value in selected_keys}
    repository = MaterialRepository(root / "projects" / str(project_id))
    records = []
    skipped = 0
    for candidate in result.get("candidates") or []:
        key = str(candidate.get("object_key") or "")
        if selected is not None and key not in selected:
            continue
        source_id = str(candidate.get("storage_source_id") or "")
        if repository.find_by_storage_reference(source_id, key):
            skipped += 1
            continue
        image_id = uuid.uuid4().hex[:16]
        suffix = Path(key).suffix.lower()
        stored_name = f"{image_id}{suffix}" if suffix in IMAGE_EXTENSIONS else f"{image_id}.img"
        records.append({
            "id": image_id,
            "filename": candidate.get("filename") or Path(key).name,
            # 外部素材不会复制到 project/uploads，但保留一个稳定、安全的逻辑文件名，
            # 让仍依赖 stored_name 作为导出目标文件名的旧链路不会拿到空字符串。
            "stored_name": stored_name,
            **dict(candidate),
            "url": f"/api/v61/projects/{project_id}/materials/{image_id}/content",
            "source_type": "storage_import",
            "processing_status": "pending_decision",
            "split": "unassigned",
            "labels": [],
            "box_count": 0,
            "annotated": False,
        })
    persisted = repository.upsert_many(records)
    confirmation = {
        "task_id": task_id,
        "storage_source_id": result.get("storage_source_id"),
        "imported": len(persisted),
        "skipped_duplicates": skipped,
        "image_ids": [str(row["id"]) for row in persisted],
    }
    artifacts.atomic_write_json(task_id, "scan/confirmation.json", confirmation)
    return confirmation


def worker_registration(data_dir: Path):
    return {
        "handlers": {TaskKind.MATERIAL_IMPORT: StorageImportHandler(data_dir)},
        "capabilities": {"storage.import"},
    }
