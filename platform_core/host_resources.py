"""Cross-platform host resource sampling and conservative DataLoader estimates."""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

GIB = 1024 ** 3


def sample_host_resources(path: str | Path | None = None, *, process=None) -> dict[str, Any]:
    logical = max(1, os.cpu_count() or 1)
    affinity = logical
    total = available = process_rss = cpu_percent = io_wait = None
    disk_read = disk_write = None
    try:
        import psutil
        proc = process or psutil.Process()
        try:
            affinity = max(1, len(proc.cpu_affinity()))
        except (AttributeError, OSError, psutil.Error):
            pass
        memory = psutil.virtual_memory()
        total, available = int(memory.total), int(memory.available)
        process_rss = int(proc.memory_info().rss)
        for child in proc.children(recursive=True):
            try:
                process_rss += int(child.memory_info().rss)
            except (OSError, psutil.Error):
                pass
        cpu_percent = float(psutil.cpu_percent())
        io_wait = getattr(psutil.cpu_times_percent(), "iowait", None)
        counters = psutil.disk_io_counters()
        if counters is not None:
            disk_read, disk_write = int(counters.read_bytes), int(counters.write_bytes)
    except (ImportError, OSError):
        pass
    target = Path(path or Path.cwd())
    while not target.exists() and target != target.parent:
        target = target.parent
    disk = shutil.disk_usage(target)
    shm = None
    if sys.platform.startswith("linux") and Path("/dev/shm").is_dir():
        usage = shutil.disk_usage("/dev/shm")
        shm = {"total_bytes": int(usage.total), "free_bytes": int(usage.free),
               "used_bytes": int(usage.used)}
    return {
        "cpu_logical": logical, "cpu_affinity": min(logical, affinity),
        "cpu_percent": cpu_percent, "io_wait_percent": io_wait,
        "disk_read_bytes": disk_read, "disk_write_bytes": disk_write,
        "ram_total_bytes": total, "ram_available_bytes": available,
        "process_rss_bytes": process_rss,
        "disk_total_bytes": int(disk.total), "disk_free_bytes": int(disk.free),
        "shm": shm,
    }


def estimate_training_host_memory(config: Mapping[str, Any], *, decoded_dataset_bytes: int | None = None) -> dict[str, int]:
    imgsz = max(32, int(config.get("imgsz") or 640))
    batch = max(1, int(config.get("batch") or 1))
    workers = max(0, int(config.get("workers") or 0))
    # Ultralytics builds its infinite DataLoader with prefetch_factor=4.  The
    # admission estimate must follow the actual loader rather than PyTorch's
    # lower generic default, otherwise RAM and /dev/shm are under-reserved.
    prefetch = 4 if workers else 0
    pixels = imgsz * imgsz * 3
    augmentation = 1.0 + 1.5 * float(config.get("mosaic") or 0) + float(config.get("mixup") or 0)
    augmentation += min(1.0, float(config.get("multi_scale") or 0))
    sample_bytes = max(pixels, int(pixels * augmentation))
    # Decoded image, augmented image, collated tensor and multiprocessing copy.
    loader_bytes = workers * prefetch * batch * sample_bytes * 4
    main_bytes = batch * sample_bytes * 4
    cache_bytes = int(decoded_dataset_bytes or 0) if str(config.get("cache")).lower() in {"ram", "true", "1"} else 0
    required_ram = 2 * GIB + loader_bytes + main_bytes + cache_bytes
    required_shm = loader_bytes if workers else 0
    return {"prefetch_factor": prefetch, "sample_bytes": sample_bytes, "loader_bytes": loader_bytes,
            "cache_bytes": cache_bytes, "required_ram_bytes": required_ram,
            "required_shm_bytes": required_shm}


def protect_training_host(config: Mapping[str, Any], host: Mapping[str, Any], *, strategy: str,
                          decoded_dataset_bytes: int | None = None) -> tuple[dict[str, Any], list[str], dict[str, int]]:
    """Adjust auto resources before training; manual settings fail instead of changing."""
    current = dict(config)
    reasons: list[str] = []

    def fits(estimate):
        available = host.get("ram_available_bytes")
        shm = host.get("shm") or {}
        total = host.get("ram_total_bytes")
        ceiling = None if available is None else max(0, int(available) - 2 * GIB)
        if ceiling is not None and total is not None:
            ceiling = min(ceiling, int(total) * 4 // 5)
        ram_ok = ceiling is None or estimate["required_ram_bytes"] <= ceiling
        shm_ok = not current["workers"] or not shm or estimate["required_shm_bytes"] <= int(shm.get("free_bytes") or 0) * 0.8
        return ram_ok and shm_ok

    estimate = estimate_training_host_memory(current, decoded_dataset_bytes=decoded_dataset_bytes)
    if fits(estimate):
        return current, reasons, estimate
    if strategy != "auto":
        raise RuntimeError(
            "HOST_RESOURCE_INSUFFICIENT: manual batch/workers/cache exceed available RAM or /dev/shm; "
            f"required_ram={estimate['required_ram_bytes']} required_shm={estimate['required_shm_bytes']}"
        )
    if str(current.get("cache")).lower() in {"ram", "true", "1"}:
        current["cache"] = False
        reasons.append("cache: ram -> false (host RAM safety)")
        estimate = estimate_training_host_memory(current, decoded_dataset_bytes=decoded_dataset_bytes)
    requested_workers = current["workers"]
    while current["workers"] > 0 and not fits(estimate):
        current["workers"] -= 1
        estimate = estimate_training_host_memory(current, decoded_dataset_bytes=decoded_dataset_bytes)
    if current["workers"] != requested_workers:
        reasons.append(f"workers: {requested_workers} -> {current['workers']} (RAM/SHM safety)")
    while current["batch"] > 1 and not fits(estimate):
        old = current["batch"]
        current["batch"] = max(1, old // 2)
        reasons.append(f"batch: {old} -> {current['batch']} (host RAM safety)")
        estimate = estimate_training_host_memory(current, decoded_dataset_bytes=decoded_dataset_bytes)
    if not fits(estimate):
        raise RuntimeError(
            "HOST_RESOURCE_INSUFFICIENT: batch=1/workers=0/cache=false still exceeds safe host memory"
        )
    return current, reasons, estimate
