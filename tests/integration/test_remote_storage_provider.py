from __future__ import annotations

import socket
import threading
import time
from io import BytesIO

import requests
import uvicorn

from platform_core.storage import RemoteStorageProvider
from remote_material_server import create_app


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_real_remote_http_server_file_lifecycle(tmp_path):
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(
        create_app(tmp_path / "remote-root", api_key="test-token"),
        host="127.0.0.1", port=port, log_level="warning",
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    for _ in range(100):
        try:
            if requests.get(f"{base_url}/api/material-storage/v1/health", headers={"X-API-Key": "test-token"}, timeout=0.2).ok:
                break
        except requests.RequestException:
            time.sleep(0.02)
    try:
        provider = RemoteStorageProvider(
            "remote-a", {"base_url": base_url, "namespace": "factory-a", "timeout_seconds": 3},
            {"token": "test-token"},
        )
        assert provider.health_check().ok is True
        content = b"real-network-image-content"
        uploaded = provider.upload("incoming/fire.jpg", BytesIO(content), content_type="image/jpeg")
        assert uploaded.size_bytes == len(content)
        assert provider.exists("incoming/fire.jpg") is True
        assert provider.stat("incoming/fire.jpg").sha256 == uploaded.sha256
        assert [item.key for item in provider.list_objects("incoming").items] == ["incoming/fire.jpg"]

        destination = tmp_path / "downloaded.jpg"
        provider.download("incoming/fire.jpg", destination)
        assert destination.read_bytes() == content

        preview = provider.generate_preview_url("incoming/fire.jpg", expires_seconds=60)
        response = requests.get(preview, timeout=3)
        assert response.status_code == 200
        assert response.content == content
        assert "test-token" not in preview

        provider.delete("incoming/fire.jpg")
        assert provider.exists("incoming/fire.jpg") is False
        assert not list((tmp_path / "remote-root").rglob("*.part-*"))
    finally:
        server.should_exit = True
        thread.join(timeout=5)


def test_remote_server_rejects_bad_credentials_over_real_http(tmp_path):
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(create_app(tmp_path / "root", api_key="right"), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    try:
        provider = RemoteStorageProvider("remote", {"base_url": f"http://127.0.0.1:{port}", "namespace": "main", "timeout_seconds": 1}, {"token": "wrong"})
        for _ in range(100):
            health = provider.health_check()
            if "connect" not in health.message.lower():
                break
            time.sleep(0.02)
        assert health.ok is False
        assert "401" in health.message
    finally:
        server.should_exit = True
        thread.join(timeout=5)
