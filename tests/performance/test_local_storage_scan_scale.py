from __future__ import annotations

import time
import tracemalloc

from platform_core.storage import LocalStorageProvider


def test_local_storage_iter_objects_scans_10001_files_with_bounded_memory(tmp_path):
    provider = LocalStorageProvider("local-scale", tmp_path / "root")
    for index in range(10_001):
        path = provider.root / f"batch-{index // 100:03d}" / f"image-{index:05d}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()

    tracemalloc.start()
    started = time.perf_counter()
    count = sum(1 for _ in provider.iter_objects())
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    print(f"count={count} elapsed={elapsed:.3f}s peak={peak / 1024 / 1024:.2f}MiB")
    assert count == 10_001
    assert peak < 64 * 1024 * 1024
