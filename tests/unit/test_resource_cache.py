import threading
import time

from platform_core.resource_cache import ResourceCache


def test_cached_resources_return_without_running_detector_twice():
    calls = []
    cache = ResourceCache(ttl_seconds=30)
    detector = lambda: calls.append(1) or [{"id": "onnx", "status": "ready"}]

    assert cache.get_or_refresh(detector)["items"][0]["status"] == "ready"
    assert cache.get_or_refresh(detector)["items"][0]["status"] == "ready"
    assert len(calls) == 1


def test_stale_value_is_returned_while_one_background_refresh_runs():
    cache = ResourceCache(ttl_seconds=0)
    cache.replace([{"id": "atlas", "status": "missing"}])
    started = threading.Event()
    release = threading.Event()

    def detector():
        started.set()
        release.wait(timeout=2)
        return [{"id": "atlas", "status": "ready"}]

    assert cache.snapshot()["stale"] is True
    assert cache.refresh_in_background(detector) is True
    assert cache.refresh_in_background(detector) is False
    assert started.wait(timeout=1)
    assert cache.snapshot()["items"][0]["status"] == "missing"
    assert cache.snapshot()["refreshing"] is True
    release.set()
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline and cache.snapshot()["refreshing"]:
        time.sleep(0.01)
    assert cache.snapshot()["items"][0]["status"] == "ready"
    assert cache.snapshot()["refreshing"] is False
