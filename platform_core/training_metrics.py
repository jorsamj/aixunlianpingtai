"""Worker-side bounded resource resolution and low-frequency training telemetry.

The estimate is deliberately conservative, not a hardware benchmark. Unknown
telemetry is retained as null and never treated as evidence for GPU sharing.
"""
from __future__ import annotations

import json
import os
import shutil
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from .annotations import atomic_write_json
from .gpu_resources import sample_gpus

GIB = 1024 ** 3


def host_resources():
    cores = os.cpu_count() or 1
    try:
        cores = len(os.sched_getaffinity(0))
    except (AttributeError, OSError):
        pass
    available = None
    try:
        import psutil
        available = int(psutil.virtual_memory().available)
        affinity = psutil.Process().cpu_affinity()
        cores = min(cores, len(affinity))
    except (ImportError, AttributeError, OSError):
        pass
    return max(1, cores), available


def normalize_cache(value):
    value = str(value).lower().strip()
    if value in {"false", "none", "0", ""}:
        return False
    if value in {"ram", "true", "1"}:
        return "ram"
    if value == "disk":
        return "disk"
    raise ValueError("RESOURCE_CACHE_INVALID: cache must be ram, disk, or false")


def resolve_resources(request, context, model, torch):
    """Resolve bounded training resources before ``model.train``.

    ``manual`` means exact user values or an explicit validation failure.

    ``auto`` is bounded by an explicit positive user request: it may reduce
    batch/workers/cache for safety, but must never silently increase them or
    enable cache when the user disabled it. ``batch=-1`` is the one explicit
    opt-in sentinel that delegates batch selection to the resource resolver.
    """
    strategy = str(request.get("resource_strategy") or "auto")
    if strategy not in {"auto", "manual"}:
        raise ValueError("RESOURCE_STRATEGY_INVALID")

    requested_batch = int(request["batch"])
    requested_workers = int(request["workers"])
    requested_cache = normalize_cache(request["cache"])
    if strategy == "manual":
        if not 1 <= requested_batch <= 4096:
            raise ValueError("RESOURCE_MANUAL_INVALID: batch must be 1..4096")
    elif requested_batch != -1 and not 1 <= requested_batch <= 4096:
        raise ValueError("RESOURCE_REQUEST_INVALID: auto batch must be -1 or 1..4096")
    if requested_workers < 0:
        raise ValueError("RESOURCE_REQUEST_INVALID: workers must be >= 0")

    cores, ram = host_resources()
    concurrency = max(1, int(context.get("concurrent_reservations") or 1))
    cpu_budget = max(1, cores // concurrency)
    dataset_bytes = max(0, int(context.get("dataset_bytes") or 0))
    decoded = context.get("decoded_dataset_bytes")
    decoded = max(0, int(decoded)) if decoded is not None else None
    disk = shutil.disk_usage(Path(request["data"]).parent).free
    cache_budget = max(0, int((ram or 0) * 0.25 / concurrency) - GIB)
    disk_need = max(dataset_bytes * 8, (decoded or 0) * 2)
    local_ready = context.get("remote_cache_ready") is True
    reasons = []
    adjustments = []

    if strategy == "manual":
        batch, workers, cache = requested_batch, requested_workers, requested_cache
        if workers > cpu_budget:
            raise ValueError(f"RESOURCE_MANUAL_INVALID: workers must be 0..{cpu_budget}")
        if os.name == "nt" and workers > 4:
            raise ValueError("RESOURCE_MANUAL_INVALID: Windows supports at most 4 loader workers")
        if request.get("device") == "cpu" and workers != 0:
            raise ValueError("RESOURCE_MANUAL_INVALID: this Ultralytics CPU runtime requires workers=0")
        if cache == "ram" and (decoded is None or decoded <= 0 or decoded * 3 > cache_budget):
            raise ValueError("RESOURCE_RAM_UNSAFE: decoded dataset size or available RAM does not support requested cache")
        if cache == "disk" and (decoded is None or disk_need + 2 * GIB > disk):
            raise ValueError("RESOURCE_DISK_UNSAFE: insufficient known disk headroom for requested cache")
        reasons.append("Validated manual values; incompatible runtime changes fail explicitly")
    else:
        batch = 1 if requested_batch == -1 else requested_batch

        # AUTO may reduce workers, but must never add workers the user did not
        # request. workers=0 is an explicit single-process DataLoader choice.
        cap = 2 if os.name == "nt" else 8
        if requested_cache != "ram":
            cap = min(cap, 4)
        cpu_loader_budget = max(0, cpu_budget - 1)
        workers = min(requested_workers, cap, cpu_loader_budget)
        if request.get("device") == "cpu":
            workers = 0
        if workers != requested_workers:
            adjustments.append(f"workers downscaled {requested_workers}->{workers} for CPU/runtime safety")
        reasons.append(
            f"Loader workers bounded by request={requested_workers}, cores={cores}, "
            f"reservations={concurrency}, platform cap={cap}"
        )

        # cache=False is authoritative. Requested RAM/Disk may only be
        # downgraded when the known host budget cannot support it.
        cache = requested_cache
        if requested_cache is False:
            cache = False
            reasons.append("Cache remains disabled because the user requested cache=false")
        elif requested_cache == "ram":
            if local_ready and decoded and decoded * 3 <= cache_budget:
                cache = "ram"
            elif local_ready and decoded and disk_need + 2 * GIB <= disk:
                cache = "disk"
                adjustments.append("cache downscaled ram->disk for memory safety")
            else:
                cache = False
                adjustments.append("cache downscaled ram->false because safe cache headroom is unavailable")
        elif requested_cache == "disk":
            if local_ready and decoded is not None and disk_need + 2 * GIB <= disk:
                cache = "disk"
            else:
                cache = False
                adjustments.append("cache downscaled disk->false because safe disk headroom is unavailable")

    estimated = None
    free = total = None
    if str(request.get("device", "")).startswith("cuda:"):
        index = int(request["device"].split(":")[1])
        torch.cuda.set_device(index)
        free, total = (int(value) for value in torch.cuda.mem_get_info(index))
        params = sum(int(value.numel()) for value in model.model.parameters())
        fixed = max(GIB, params * 24)
        per_image = int(
            256 * 1024 ** 2
            * max(1.0, (params / 3_000_000) ** 0.55)
            * (int(request["imgsz"]) / 640) ** 2
            * (1 + float(request.get("multi_scale") or 0)) ** 2
        )
        other = max(0, int(context.get("other_reserved_bytes") or 0))
        budget = max(0, int((free - other - GIB) * 0.65))
        reserved = context.get("reserved_bytes")
        if reserved:
            budget = min(budget, int(reserved))
        if strategy == "auto":
            maximum = min(64, (budget - fixed) // max(1, per_image))
            if maximum < 1:
                raise RuntimeError("GPU_MEMORY_INSUFFICIENT: batch=1 exceeds conservative budget; no CPU fallback")
            if requested_batch == -1:
                batch = int(maximum)
                reasons.append(f"Explicit batch=-1 delegated selection; safe resolved batch={batch}")
            else:
                safe_batch = min(requested_batch, int(maximum))
                if safe_batch < requested_batch:
                    adjustments.append(f"batch downscaled {requested_batch}->{safe_batch} for GPU memory safety")
                batch = safe_batch
                reasons.append(
                    f"GPU bounded estimate permits at most batch={maximum}; "
                    f"requested batch={requested_batch}; effective batch={batch}"
                )
        estimated = fixed + batch * per_image
    elif strategy == "auto":
        if requested_batch == -1:
            batch = 1
            reasons.append("Explicit batch=-1 resolved conservatively to batch=1 on CPU")
        elif batch > 1:
            adjustments.append(f"batch downscaled {batch}->1 for CPU safety")
            batch = 1
            reasons.append("Explicit CPU assignment uses conservative batch<=1")

    loader_limit = min(
        batch,
        int(context.get("train_image_count") or batch),
        max(1, cores // max(1, torch.cuda.device_count())),
    )
    if strategy == "auto":
        limited_workers = min(workers, loader_limit)
        if limited_workers != workers:
            adjustments.append(f"workers downscaled {workers}->{limited_workers} for loader capacity")
        workers = limited_workers
    elif workers > loader_limit:
        raise ValueError(f"RESOURCE_MANUAL_INVALID: runtime loader limits workers to {loader_limit}")

    resolved = dict(
        resource_strategy=strategy,
        requested_batch=requested_batch,
        requested_workers=requested_workers,
        requested_cache=requested_cache,
        resolved_batch=batch,
        resolved_workers=workers,
        resolved_cache=cache,
        adjustments=adjustments,
        reasons=reasons,
        estimated_gpu_memory_bytes=estimated,
        gpu_free_bytes_at_resolution=free,
        gpu_total_bytes=total,
        available_cpu_cores=cores,
        concurrent_reservations=concurrency,
        available_ram_bytes=ram,
        dataset_bytes=dataset_bytes,
        decoded_dataset_bytes=decoded,
        sampled_at=datetime.now(timezone.utc).isoformat(),
    )
    print(
        "[资源决议] "
        f"strategy={strategy}; "
        f"requested(batch={requested_batch}, workers={requested_workers}, cache={requested_cache}); "
        f"effective(batch={batch}, workers={workers}, cache={cache}); "
        f"adjustments={adjustments or ['none']}",
        flush=True,
    )
    return resolved


def diagnose_window(samples, oom=False):
    """Deterministic 30-second window; missing evidence never enables sharing."""
    if oom:
        return {"code": "memory_pressure_oom", "cpu_bottleneck": None, "io_bottleneck": None}
    if len(samples) < 6:
        return {"code": "insufficient_samples", "cpu_bottleneck": None, "io_bottleneck": None}
    def mean(key):
        values = [row[key] for row in samples if row.get(key) is not None]
        return sum(values) / len(values) if len(values) == len(samples) else None
    gpu, cpu, io, memory = (mean(key) for key in ("gpu_utilization", "cpu_percent", "io_wait_percent", "gpu_memory_percent"))
    cpu_busy = cpu >= 85 if cpu is not None else None
    io_busy = io >= 15 if io is not None else None
    if memory is not None and memory >= 90:
        code = "memory_pressure"
    elif gpu is None:
        code = "telemetry_unavailable"
    elif gpu < 50 and cpu_busy:
        code = "cpu_bottleneck"
    elif gpu < 50 and io_busy:
        code = "io_bottleneck"
    elif gpu >= 70:
        code = "healthy_utilization"
    elif gpu < 50 and cpu_busy is False and io_busy is False and memory is not None and memory < 65:
        code = "batch_headroom"
    else:
        code = "data_pipeline_or_unknown"
    return dict(code=code, cpu_bottleneck=cpu_busy, io_bottleneck=io_busy,
                gpu_utilization=gpu, gpu_memory_percent=memory, window_samples=len(samples))


def read_metrics(path):
    path = Path(path)
    if not path.is_file():
        return {}
    try:
        with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1) as db:
            row = db.execute("SELECT value FROM summary WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}
    except (sqlite3.Error, ValueError, OSError):
        return {}


class TrainingMetrics:
    def __init__(self, path, resolved, gpu_uuid=None, interval=5):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.resolved = dict(resolved)
        self.gpu_uuid = gpu_uuid
        self.interval = max(5, float(interval))
        self.started = time.monotonic()
        self.epoch_started = self.started
        self.epoch_duration = self.images_per_second = None
        self.oom = False
        self.stop_event = threading.Event()
        self.lock = threading.Lock()
        self.psutil = None
        try:
            import psutil
            self.psutil = psutil
            psutil.cpu_percent()
        except ImportError:
            pass
        with self.connect() as db:
            db.executescript("CREATE TABLE IF NOT EXISTS samples (id INTEGER PRIMARY KEY, value TEXT NOT NULL);"
                             "CREATE TABLE IF NOT EXISTS summary (id INTEGER PRIMARY KEY CHECK(id=1), value TEXT NOT NULL);"
                             "CREATE TABLE IF NOT EXISTS epochs (id INTEGER PRIMARY KEY, value TEXT NOT NULL);")
        self.thread = threading.Thread(target=self._run, name="training-metrics", daemon=True)

    def connect(self):
        return sqlite3.connect(self.path, timeout=2)

    def start(self):
        self.thread.start()

    def _run(self):
        while not self.stop_event.is_set():
            try:
                self.sample()
            except Exception:
                pass
            self.stop_event.wait(self.interval)

    def sample(self):
        sample = dict(sampled_at=datetime.now(timezone.utc).isoformat(), gpu_utilization=None,
                      gpu_memory_percent=None, gpu_used_bytes=None, gpu_total_bytes=None,
                      cpu_percent=None, io_wait_percent=None)
        if self.psutil:
            sample["cpu_percent"] = self.psutil.cpu_percent()
            sample["io_wait_percent"] = getattr(self.psutil.cpu_times_percent(), "iowait", None)
        if self.gpu_uuid:
            gpu = next((row for row in sample_gpus() if row["uuid"] == self.gpu_uuid), None)
            if gpu and gpu.get("total_bytes") and gpu.get("free_bytes") is not None:
                sample.update(gpu_utilization=gpu["utilization"], gpu_total_bytes=gpu["total_bytes"],
                              gpu_used_bytes=gpu["total_bytes"] - gpu["free_bytes"],
                              gpu_memory_percent=100 * (1 - gpu["free_bytes"] / gpu["total_bytes"]))
        with self.lock, self.connect() as db:
            db.execute("INSERT INTO samples(value) VALUES (?)", (json.dumps(sample),))
            db.execute("DELETE FROM samples WHERE id NOT IN (SELECT id FROM samples ORDER BY id DESC LIMIT 720)")
            rows = [json.loads(row[0]) for row in db.execute("SELECT value FROM samples ORDER BY id DESC LIMIT 6")]
            summary = dict(self.resolved, latest=sample, diagnostic=diagnose_window(rows, self.oom),
                           epoch_duration_seconds=self.epoch_duration, images_per_second=self.images_per_second,
                           total_duration_seconds=round(time.monotonic() - self.started, 3),
                           sampled_at=sample["sampled_at"], interval_seconds=self.interval)
            db.execute("INSERT OR REPLACE INTO summary VALUES (1,?)", (json.dumps(summary),))

    def on_train_start(self, trainer):
        actual = dict(resolved_batch=int(trainer.batch_size),
                      resolved_workers=int(trainer.train_loader.num_workers),
                      resolved_cache=normalize_cache(trainer.args.cache))
        if any(actual[key] != self.resolved[key] for key in actual):
            raise RuntimeError(f"RESOURCE_RUNTIME_MISMATCH: requested={self.resolved}; actual={actual}")
        dataset = trainer.train_loader.dataset
        if actual["resolved_cache"] == "ram" and hasattr(dataset, "ims") and any(image is None for image in dataset.ims):
            raise RuntimeError("RESOURCE_RUNTIME_MISMATCH: runtime declined requested RAM cache")

    def on_epoch_start(self, trainer):
        self.epoch_started = time.monotonic()
        actual = int(trainer.batch_size)
        if actual != self.resolved["resolved_batch"]:
            raise RuntimeError("RESOURCE_RUNTIME_MISMATCH: runtime changed batch; explicit worker retry required")

    def on_epoch_end(self, trainer):
        duration = max(0.001, time.monotonic() - self.epoch_started)
        count = len(trainer.train_loader.dataset)
        with self.lock, self.connect() as db:
            self.epoch_duration = round(duration, 3)
            self.images_per_second = round(count / duration, 3)
            db.execute("INSERT INTO epochs(value) VALUES (?)", (json.dumps(dict(
                epoch=int(trainer.epoch) + 1, duration_seconds=self.epoch_duration,
                images_per_second=self.images_per_second, images=count)),))
            db.execute("DELETE FROM epochs WHERE id NOT IN (SELECT id FROM epochs ORDER BY id DESC LIMIT 1000)")

    def close(self):
        self.stop_event.set()
        self.thread.join(timeout=6)
        if not self.thread.is_alive():
            try:
                self.sample()
            except Exception:
                pass


def persist_resolution(path, resolved):
    atomic_write_json(Path(path), resolved)
