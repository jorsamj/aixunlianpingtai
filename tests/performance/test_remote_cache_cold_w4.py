"""Opt-in W4 measurement over a real loopback remote HTTP server.

This is NOT an Alibaba OSS / MinIO latency claim; it measures the existing
RemoteStorageProvider + MaterialCache protocol and request counts.
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO

import pytest
import requests
import uvicorn

from platform_core.storage import MaterialCache, RemoteStorageProvider
from remote_material_server import create_app


def _free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _p95(values):
    return round(sorted(values)[max(0, int(len(values) * 0.95) - 1)], 2)


@pytest.mark.scale
@pytest.mark.skipif(os.environ.get("RUN_W4_REMOTE") != "1",
                    reason="set RUN_W4_REMOTE=1 for loopback remote cache measurement")
def test_remote_cache_cold_hot_and_concurrent_request_counts(tmp_path):
    port = _free_port()
    application = create_app(tmp_path / "remote-root", api_key="test-token")
    counts = {"content": 0, "meta": 0}

    @application.middleware("http")
    async def count_requests(request, call_next):
        path = request.url.path
        if path.endswith("/objects/content"):
            counts["content"] += 1
        elif path.endswith("/objects/meta"):
            counts["meta"] += 1
        return await call_next(request)

    server = uvicorn.Server(uvicorn.Config(
        application, host="127.0.0.1", port=port, log_level="warning",
    ))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{port}"
    try:
        for _ in range(100):
            try:
                if requests.get(f"{base_url}/api/material-storage/v1/health",
                                headers={"X-API-Key": "test-token"}, timeout=0.2).ok:
                    break
            except requests.RequestException:
                time.sleep(0.02)
        provider = RemoteStorageProvider(
            "remote-a", {"base_url": base_url, "namespace": "factory-a", "timeout_seconds": 10},
            {"token": "test-token"},
        )
        report = {"fixture_only": True, "transport": "loopback HTTP, not OSS/MinIO", "cases": []}
        for label, content in (("small-64k", b"x" * 64_000), ("large-8m", b"y" * 8_000_000)):
            key = f"incoming/{label}.bin"
            uploaded = provider.upload(key, BytesIO(content), content_type="application/octet-stream")
            expected = hashlib.sha256(content).hexdigest()
            assert uploaded.sha256 == expected
            counts["content"] = counts["meta"] = 0

            cold = []
            base_cache = tmp_path / ("cache-" + label)
            for index in range(12):
                cache = MaterialCache(base_cache / str(index))
                began = time.perf_counter()
                result = cache.materialize(provider, key, expected_sha256=expected, suffix=".bin")
                cold.append((time.perf_counter() - began) * 1000)
                assert result.cache_hit is False and result.path.read_bytes() == content
            cold_content, cold_meta = counts["content"], counts["meta"]

            hot_cache = MaterialCache(base_cache / "hot")
            hot_cache.materialize(provider, key, expected_sha256=expected, suffix=".bin")
            counts["content"] = counts["meta"] = 0
            hot = []
            for _ in range(30):
                began = time.perf_counter()
                result = hot_cache.materialize(provider, key, expected_sha256=expected, suffix=".bin")
                hot.append((time.perf_counter() - began) * 1000)
                assert result.cache_hit is True
            hot_content, hot_meta = counts["content"], counts["meta"]

            counts["content"] = counts["meta"] = 0
            concurrent_cache = MaterialCache(base_cache / "concurrent")
            began = time.perf_counter()
            with ThreadPoolExecutor(max_workers=10) as pool:
                results = list(pool.map(
                    lambda _index: concurrent_cache.materialize(
                        provider, key, expected_sha256=expected, suffix=".bin"),
                    range(10),
                ))
            concurrent_ms = (time.perf_counter() - began) * 1000
            assert all(result.path.read_bytes() == content for result in results)
            report["cases"].append({
                "case": label, "bytes": len(content),
                "cold_p50_ms": round(statistics.median(cold), 2),
                "cold_p95_ms": _p95(cold),
                "cold_content_requests": cold_content, "cold_meta_requests": cold_meta,
                "hot_p50_ms": round(statistics.median(hot), 2),
                "hot_p95_ms": _p95(hot),
                "hot_content_requests": hot_content, "hot_meta_requests": hot_meta,
                "concurrent_10_ms": round(concurrent_ms, 2),
                "concurrent_content_requests": counts["content"],
                "concurrent_meta_requests": counts["meta"],
            })
        print(json.dumps(report, ensure_ascii=False))
    finally:
        server.should_exit = True
        thread.join(timeout=5)
