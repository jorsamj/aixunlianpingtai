from __future__ import annotations

import hashlib
import hmac
import os
import time
import uuid
from pathlib import Path, PureWindowsPath
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import FileResponse


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_path(root: Path, namespace: str, key: str) -> Path:
    raw_namespace = str(namespace or "").strip()
    raw_key = str(key or "")
    candidate = Path(raw_key)
    windows = PureWindowsPath(raw_key)
    if (
        not raw_namespace or not raw_key or "\x00" in raw_key or "\\" in raw_key
        or candidate.is_absolute() or windows.is_absolute() or windows.drive
        or ".." in candidate.parts or ".." in windows.parts
        or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for char in raw_namespace)
    ):
        raise HTTPException(status_code=400, detail="invalid namespace or object key")
    base = (root / raw_namespace).resolve()
    resolved = (base / candidate).resolve()
    if resolved != base and base not in resolved.parents:
        raise HTTPException(status_code=400, detail="object key escapes namespace")
    return resolved


def _metadata(root: Path, namespace: str, path: Path) -> dict:
    base = (root / namespace).resolve()
    return {
        "key": path.relative_to(base).as_posix(),
        "size_bytes": path.stat().st_size,
        "etag": f'"{path.stat().st_mtime_ns:x}-{path.stat().st_size:x}"',
        "content_type": "application/octet-stream",
        "sha256": _sha256(path),
        "last_modified": str(path.stat().st_mtime_ns),
    }


def create_app(root: str | Path, *, api_key: str) -> FastAPI:
    storage_root = Path(root).resolve()
    storage_root.mkdir(parents=True, exist_ok=True)
    secret = str(api_key)
    app = FastAPI(title="畅联云远程素材服务", version="1")

    def authorize(x_api_key: str = Header(default="")):
        if not secret or not hmac.compare_digest(str(x_api_key), secret):
            raise HTTPException(status_code=401, detail="invalid API key")

    @app.get("/api/material-storage/v1/health", dependencies=[Depends(authorize)])
    def health():
        return {"ok": True, "protocol_version": 1, "root_available": storage_root.is_dir()}

    @app.get("/api/material-storage/v1/objects/meta", dependencies=[Depends(authorize)])
    def object_meta(namespace: str, key: str):
        path = _safe_path(storage_root, namespace, key)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="object not found")
        return _metadata(storage_root, namespace, path)

    @app.get("/api/material-storage/v1/objects/list", dependencies=[Depends(authorize)])
    def list_objects(
        namespace: str, prefix: str = "", recursive: bool = True,
        cursor: str | None = None, limit: int = Query(default=1000, ge=1, le=10000),
    ):
        base = (storage_root / namespace).resolve()
        base.mkdir(parents=True, exist_ok=True)
        prefix_path = _safe_path(storage_root, namespace, prefix) if prefix else base
        if not prefix_path.exists():
            return {"items": [], "next_cursor": None}
        candidates = [prefix_path] if prefix_path.is_file() else list(prefix_path.rglob("*") if recursive else prefix_path.glob("*"))
        items = sorted(
            (_metadata(storage_root, namespace, path) for path in candidates if path.is_file()),
            key=lambda item: item["key"],
        )
        if cursor:
            items = [item for item in items if item["key"] > cursor]
        visible = items[:limit]
        return {"items": visible, "next_cursor": visible[-1]["key"] if len(items) > limit else None}

    @app.put("/api/material-storage/v1/objects", dependencies=[Depends(authorize)])
    async def upload_object(request: Request, namespace: str, key: str):
        path = _safe_path(storage_root, namespace, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.parent / f".part-{uuid.uuid4().hex}.tmp"
        try:
            with temporary.open("wb") as stream:
                async for chunk in request.stream():
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if temporary.stat().st_size <= 0:
                raise HTTPException(status_code=422, detail="empty objects are not allowed")
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)
        return _metadata(storage_root, namespace, path)

    @app.get("/api/material-storage/v1/objects/content", dependencies=[Depends(authorize)])
    def download_object(namespace: str, key: str):
        path = _safe_path(storage_root, namespace, key)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="object not found")
        return FileResponse(path)

    @app.delete("/api/material-storage/v1/objects", dependencies=[Depends(authorize)])
    def delete_object(namespace: str, key: str):
        path = _safe_path(storage_root, namespace, key)
        path.unlink(missing_ok=True)
        return {"ok": True}

    def signature(namespace: str, key: str, expires: int) -> str:
        body = f"{namespace}\n{key}\n{expires}".encode("utf-8")
        return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()

    @app.post("/api/material-storage/v1/objects/presign", dependencies=[Depends(authorize)])
    def presign(request: Request, namespace: str, key: str, expires_seconds: int = 900):
        path = _safe_path(storage_root, namespace, key)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="object not found")
        expires = int(time.time()) + max(1, min(3600, int(expires_seconds)))
        query = urlencode({"namespace": namespace, "key": key, "expires": expires, "signature": signature(namespace, key, expires)})
        return {"url": str(request.base_url).rstrip("/") + "/api/material-storage/v1/objects/signed-content?" + query}

    @app.get("/api/material-storage/v1/objects/signed-content")
    def signed_content(namespace: str, key: str, expires: int, signature: str):
        expected_signature = hmac.new(
            secret.encode("utf-8"),
            f"{namespace}\n{key}\n{expires}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if int(expires) < int(time.time()) or not hmac.compare_digest(signature, expected_signature):
            raise HTTPException(status_code=403, detail="signed URL is invalid or expired")
        path = _safe_path(storage_root, namespace, key)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="object not found")
        return FileResponse(path)

    return app


def app_from_environment() -> FastAPI:
    root = os.environ.get("MC_REMOTE_MATERIAL_ROOT", "./remote_material_data")
    token = os.environ.get("MC_REMOTE_MATERIAL_API_KEY", "")
    if not token:
        raise RuntimeError("MC_REMOTE_MATERIAL_API_KEY is required")
    return create_app(root, api_key=token)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app_from_environment(), host="0.0.0.0", port=int(os.environ.get("MC_REMOTE_MATERIAL_PORT", "9020")))
