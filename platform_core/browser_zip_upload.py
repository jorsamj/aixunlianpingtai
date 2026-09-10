from __future__ import annotations

"""Thin browser ZIP staging for the durable MATERIAL_IMPORT worker.

The HTTP request only receives the archive and publishes it atomically under
MC_SERVER_IMPORT_DIR.  It never extracts files, enumerates images, parses YOLO
labels, hashes the dataset, or writes materials.  Those operations belong to the
storage worker after the API has returned 202.
"""

import os
import shutil
import uuid
from pathlib import Path

from fastapi import File, Form, HTTPException, UploadFile

from platform_core.storage.zip_import import ServerZipImportError


CHUNK_BYTES = 4 * 1024 * 1024
DEFAULT_MAX_UPLOAD_BYTES = 128 * 1024**3
DEFAULT_DISK_HEADROOM_BYTES = 1024**3


def _positive_bytes(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return int(default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as error:
        raise RuntimeError(f"{name} must be a positive integer") from error
    if value <= 0 or value >= 2**63:
        raise RuntimeError(f"{name} must be between 1 and 2^63-1")
    return value


def _safe_dataset_yaml(value: str) -> str:
    text = str(value or "").strip().replace("\\", "/").strip("/")
    if not text:
        return ""
    parts = text.split("/")
    if any(not part or part in {".", ".."} or ":" in part for part in parts):
        raise ValueError("dataset_yaml 必须是 ZIP 内的安全相对路径")
    if not text.lower().endswith((".yaml", ".yml")):
        raise ValueError("dataset_yaml 必须指向 .yaml 或 .yml 文件")
    return text


async def stage_browser_zip(
    upload: UploadFile,
    import_root: Path,
    relative_path: str,
) -> tuple[Path, int]:
    """Stream one browser upload to a task-owned temporary file and atomically publish it."""
    max_bytes = _positive_bytes("MC_BROWSER_ZIP_MAX_BYTES", DEFAULT_MAX_UPLOAD_BYTES)
    headroom = _positive_bytes("MC_BROWSER_ZIP_DISK_HEADROOM_BYTES", DEFAULT_DISK_HEADROOM_BYTES)
    root = Path(import_root).expanduser().resolve()
    destination = (root / relative_path).resolve()
    try:
        destination.relative_to(root)
    except ValueError as error:
        raise ValueError("browser ZIP staging path escaped its root") from error
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.part")
    written = 0
    since_disk_check = 0
    try:
        with temporary.open("xb") as output:
            while True:
                chunk = await upload.read(CHUNK_BYTES)
                if not chunk:
                    break
                written += len(chunk)
                since_disk_check += len(chunk)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"ZIP 超过浏览器上传上限 {max_bytes} 字节",
                    )
                if since_disk_check >= 64 * 1024 * 1024:
                    free = shutil.disk_usage(destination.parent).free
                    if free < headroom + CHUNK_BYTES:
                        raise HTTPException(
                            status_code=507,
                            detail="服务器磁盘剩余空间不足，已停止 ZIP 上传",
                        )
                    since_disk_check = 0
                output.write(chunk)
            if written <= 0:
                raise HTTPException(status_code=400, detail="ZIP 文件为空")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, destination)
        return destination, written
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    finally:
        await upload.close()


def install_browser_zip_routes(app, legacy) -> None:
    """Attach the v62 upload bridge to the already-loaded monolithic FastAPI app."""
    if getattr(app.state, "browser_zip_v62_installed", False):
        return
    app.state.browser_zip_v62_installed = True

    @app.post("/api/v62/projects/{project_id}/browser-zip-imports", status_code=202)
    async def create_browser_zip_import(
        project_id: str,
        file: UploadFile = File(...),
        import_format: str = Form("auto"),
        dataset_yaml: str = Form(""),
    ):
        legacy.get_project(project_id)
        filename = str(file.filename or "").strip()
        if not filename.lower().endswith(".zip"):
            await file.close()
            raise HTTPException(status_code=400, detail="文件类型不支持，请选择 .zip 压缩包")
        format_value = str(import_format or "auto").strip().lower()
        if format_value not in {"auto", "images", "yolo"}:
            await file.close()
            raise HTTPException(status_code=422, detail="浏览器 ZIP 仅支持 auto、images、yolo")
        try:
            yaml_inside_zip = _safe_dataset_yaml(dataset_yaml)
        except ValueError as error:
            await file.close()
            raise HTTPException(status_code=422, detail=str(error)) from error
        if format_value == "images" and yaml_inside_zip:
            await file.close()
            raise HTTPException(status_code=422, detail="仅图片模式不能指定 dataset_yaml")

        source = legacy.storage_source_repository().get("default_local")
        if source is None or not source.enabled or str(source.type).lower() != "local":
            await file.close()
            raise HTTPException(status_code=409, detail="平台默认本地存储不可用")

        upload_id = uuid.uuid4().hex[:16]
        relative_zip = f"browser/{upload_id}.zip"
        target_prefix = f"browser_imports/{upload_id}"
        root = legacy.server_import_dir(legacy.DATA_DIR)
        archive = root / relative_zip
        try:
            _path, uploaded_bytes = await stage_browser_zip(file, root, relative_zip)
            payload = legacy.StorageImportScanReq(
                mode="server_zip",
                storage_source_id=source.id,
                recursive=True,
                zip_path=relative_zip,
                target_prefix=target_prefix,
                import_format=format_value,
                dataset_yaml=(
                    f"{target_prefix}/{yaml_inside_zip}" if yaml_inside_zip else None
                ),
            )
            task = legacy.create_storage_import_scan(project_id, payload)
        except ServerZipImportError as error:
            archive.unlink(missing_ok=True)
            raise HTTPException(status_code=422, detail=error.message) from error
        except BaseException:
            archive.unlink(missing_ok=True)
            raise

        if isinstance(task, dict):
            return {
                **task,
                "upload_id": upload_id,
                "uploaded_bytes": uploaded_bytes,
                "pipeline": "durable_material_import",
            }
        return task
