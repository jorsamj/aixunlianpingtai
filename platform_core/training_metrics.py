"""Worker-side bounded resource resolution and low-frequency training telemetry.

The estimate is deliberately conservative, not a hardware benchmark. Unknown
telemetry is retained as null and never treated as evidence for GPU sharing.
"""
from __future__ import annotations

import json
import math
import os
import shutil
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

from .annotations import atomic_write_json
from .gpu_resources import sample_gpus
from .training_precision import normalize_training_precision

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


def effective_loader_resources(train_image_count, batch, workers):
    """Apply the small, stable DataLoader constraints that affect resource truth.

    Ultralytics caps the loader batch by dataset length and caps worker
    processes by the final number of loader batches, using zero workers for a
    single-batch loader. Platform CPU/profile limits are applied before this
    helper; keeping only these final constraints here avoids copying framework
    internals while ensuring the resource decision is executable.
    """
    try:
        train_images = int(train_image_count)
        candidate_batch = int(batch)
        candidate_workers = int(workers)
    except (TypeError, ValueError) as error:
        raise ValueError("RESOURCE_DATASET_INVALID: loader resources must be integers") from error
    if train_images < 1:
        raise ValueError("RESOURCE_DATASET_INVALID: train_image_count must be >= 1")
    if candidate_batch < 1:
        raise ValueError("RESOURCE_REQUEST_INVALID: effective batch must be >= 1")
    if candidate_workers < 0:
        raise ValueError("RESOURCE_REQUEST_INVALID: workers must be >= 0")

    effective_batch = min(candidate_batch, train_images)
    loader_batches = int(math.ceil(train_images / effective_batch))
    worker_batch_cap = 0 if loader_batches <= 1 else loader_batches
    effective_workers = min(candidate_workers, worker_batch_cap)
    return {
        "train_image_count": train_images,
        "candidate_batch": candidate_batch,
        "effective_batch": effective_batch,
        "candidate_workers": candidate_workers,
        "effective_workers": effective_workers,
        "loader_batches": loader_batches,
        "worker_batch_cap": worker_batch_cap,
    }


def runtime_loader_resources(trainer):
    """Read the effective runtime values from the constructed training loader."""
    loader = getattr(trainer, "train_loader", None)
    if loader is None:
        raise RuntimeError("RESOURCE_RUNTIME_MISMATCH: trainer has no train_loader")
    batch = getattr(loader, "batch_size", None)
    workers = getattr(loader, "num_workers", None)
    if batch is None or workers is None:
        raise RuntimeError("RESOURCE_RUNTIME_MISMATCH: train_loader resource truth is incomplete")
    args = getattr(trainer, "args", None)
    cache = normalize_cache(getattr(args, "cache", False))
    return {
        "runtime_batch": int(batch),
        "runtime_workers": int(workers),
        "runtime_cache": cache,
    }


def resolve_resources(request, context, model, torch):
    """Resolve bounded training resources before model.train.

    manual preserves the exact user values or fails explicitly.

    auto is platform-owned adaptive scheduling. The selected profile decides
    how aggressively the worker may use GPU memory, CPU loader workers and safe
    dataset cache. Resolution happens only before training starts; runtime
    telemetry may diagnose headroom but never changes batch size mid-run.
    """
    strategy = str(request.get("resource_strategy") or "auto").strip().lower()
    if strategy not in {"auto", "manual"}:
        raise ValueError("RESOURCE_STRATEGY_INVALID")
    profile = str(request.get("resource_profile") or "balanced").strip().lower()
    if profile not in {"balanced", "performance", "stability"}:
        raise ValueError("RESOURCE_PROFILE_INVALID")
    gpu_policy = str(request.get("gpu_policy") or "auto").strip().lower()
    if gpu_policy not in {"auto", "exclusive"}:
        raise ValueError("GPU_POLICY_UNSUPPORTED: shared GPU scheduling is not enabled")
    precision = normalize_training_precision(request.get("precision") or "auto")
    activation_precision_factor = (
        2.0
        if precision == "fp32"
        or (precision == "auto" and request.get("amp") is False)
        else 1.0
    )

    requested_batch = int(request["batch"])
    requested_workers = int(request["workers"])
    requested_cache = normalize_cache(request["cache"])
    if strategy == "manual":
        if not 1 <= requested_batch <= 4096:
            raise ValueError("RESOURCE_MANUAL_INVALID: batch must be 1..4096")
        if requested_workers < 0:
            raise ValueError("RESOURCE_REQUEST_INVALID: workers must be >= 0")
    else:
        if requested_batch != -1 and not 1 <= requested_batch <= 4096:
            raise ValueError("RESOURCE_REQUEST_INVALID: auto batch must be -1 or 1..4096")
        if requested_workers < 0:
            raise ValueError("RESOURCE_REQUEST_INVALID: workers must be >= 0")

    profile_cfg = {
        "stability": {
            "gpu_fraction": 0.58,
            "worker_cap": 4,
            "ram_fraction": 0.22,
            "batch_cap": 64,
        },
        "balanced": {
            "gpu_fraction": 0.70,
            "worker_cap": 8,
            "ram_fraction": 0.35,
            "batch_cap": 128,
        },
        "performance": {
            "gpu_fraction": 0.82,
            "worker_cap": 12,
            "ram_fraction": 0.50,
            "batch_cap": 256,
        },
    }[profile]

    cores, ram = host_resources()
    concurrency = max(1, int(context.get("concurrent_reservations") or 1))
    cpu_budget = max(1, cores // concurrency)
    dataset_bytes = max(0, int(context.get("dataset_bytes") or 0))
    try:
        train_image_count = int(context.get("train_image_count"))
    except (TypeError, ValueError) as error:
        raise ValueError("RESOURCE_DATASET_INVALID: train_image_count is required") from error
    if train_image_count < 1:
        raise ValueError("RESOURCE_DATASET_INVALID: train_image_count must be >= 1")
    decoded = context.get("decoded_dataset_bytes")
    decoded = max(0, int(decoded)) if decoded is not None else None
    disk = shutil.disk_usage(Path(request["data"]).parent).free
    ram_available = max(0, int(ram or 0))
    cache_budget = max(
        0,
        int(ram_available * float(profile_cfg["ram_fraction"]) / concurrency) - GIB,
    )
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
        cap = int(profile_cfg["worker_cap"])
        if os.name == "nt":
            cap = min(cap, 4)
        cpu_loader_budget = max(0, cpu_budget - 1)
        # Divide host CPU by tasks actually reserved on this host, not by the
        # number of installed GPUs. An idle multi-GPU server should not throttle
        # a single training job before the other GPUs have work. The final
        # DataLoader batch-count cap is applied after GPU batch resolution.
        workers = min(cap, cpu_loader_budget)
        if request.get("device") == "cpu":
            workers = 0
        reasons.append(
            f"Adaptive loader worker candidate profile={profile}; cores={cores}; "
            f"reservations={concurrency}; cap={cap}; candidate={workers}"
        )

        cache = False
        if local_ready and decoded is not None and decoded > 0 and decoded * 3 <= cache_budget:
            cache = "ram"
            reasons.append(
                f"Adaptive cache selected RAM; decoded={decoded}; safe_budget={cache_budget}"
            )
        elif local_ready and dataset_bytes > 0 and disk_need + 2 * GIB <= disk:
            cache = "disk"
            reasons.append(
                f"Adaptive cache selected disk; required={disk_need + 2 * GIB}; free={disk}; "
                f"decoded_estimate={'known' if decoded is not None else 'conservative-from-source-bytes'}"
            )
        else:
            reasons.append("Adaptive cache remains disabled because safe RAM/disk headroom is unavailable")
        if cache != requested_cache:
            adjustments.append(f"cache auto-resolved {requested_cache}->{cache}")
        batch = 1

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
            * activation_precision_factor
        )
        other = max(0, int(context.get("other_reserved_bytes") or 0))
        reserve_floor = max(GIB, int(total * 0.05))
        available_after_other = max(0, free - other - reserve_floor)
        budget = max(0, int(available_after_other * float(profile_cfg["gpu_fraction"])))
        reserved = context.get("reserved_bytes")
        if reserved:
            budget = min(budget, int(reserved))
        if strategy == "auto":
            maximum = min(
                int(profile_cfg["batch_cap"]),
                (budget - fixed) // max(1, per_image),
            )
            if maximum < 1:
                raise RuntimeError("GPU_MEMORY_INSUFFICIENT: batch=1 exceeds adaptive budget; no CPU fallback")
            batch = int(maximum)
            reasons.append(
                f"Adaptive batch capacity profile={profile}; gpu_fraction={profile_cfg['gpu_fraction']:.2f}; "
                f"candidate_batch={batch}"
            )
        else:
            if fixed + requested_batch * per_image > budget and budget > 0:
                raise ValueError(
                    f"RESOURCE_MANUAL_INVALID: requested batch={requested_batch} exceeds current GPU budget"
                )
            batch = requested_batch
    elif strategy == "auto":
        batch = 1
        reasons.append("CPU assignment uses conservative batch candidate=1")
    else:
        batch = requested_batch

    candidate_batch = int(batch)
    candidate_workers = int(workers)
    loader = effective_loader_resources(train_image_count, candidate_batch, candidate_workers)
    batch = loader["effective_batch"]
    workers = loader["effective_workers"]

    if strategy == "manual":
        if batch != requested_batch:
            raise ValueError(
                f"RESOURCE_MANUAL_INVALID: requested batch={requested_batch} exceeds "
                f"train image count={train_image_count}; runtime batch would be {batch}"
            )
        if workers != requested_workers:
            raise ValueError(
                f"RESOURCE_MANUAL_INVALID: requested workers={requested_workers} exceeds "
                f"runtime loader cap={loader['worker_batch_cap']} for "
                f"{loader['loader_batches']} loader batches"
            )
    else:
        if candidate_batch != batch:
            adjustments.append(
                f"batch capped {candidate_batch}->{batch} by train image count {train_image_count}"
            )
        if candidate_workers != workers:
            adjustments.append(
                f"workers capped {candidate_workers}->{workers} by loader batch count "
                f"{loader['loader_batches']}"
            )
        if batch != requested_batch:
            adjustments.append(f"batch auto-resolved {requested_batch}->{batch}")
        if workers != requested_workers:
            adjustments.append(f"workers auto-resolved {requested_workers}->{workers}")
        reasons.append(
            f"DataLoader constraints train_images={train_image_count}; "
            f"effective_batch={batch}; loader_batches={loader['loader_batches']}; "
            f"worker_batch_cap={loader['worker_batch_cap']}; effective_workers={workers}"
        )

    if str(request.get("device", "")).startswith("cuda:"):
        estimated = fixed + batch * per_image

    resolved = dict(
        resource_strategy=strategy,
        resource_profile=profile,
        gpu_policy=gpu_policy,
        precision=precision,
        activation_precision_factor=activation_precision_factor,
        requested_batch=requested_batch,
        requested_workers=requested_workers,
        requested_cache=requested_cache,
        resolved_batch=batch,
        resolved_workers=workers,
        resolved_cache=cache,
        resource_candidate_batch=candidate_batch,
        resource_candidate_workers=candidate_workers,
        train_image_count=train_image_count,
        loader_batches=loader["loader_batches"],
        loader_worker_batch_cap=loader["worker_batch_cap"],
        adjustments=adjustments,
        reasons=reasons,
        estimated_gpu_memory_bytes=estimated,
        gpu_free_bytes_at_resolution=free,
        gpu_total_bytes=total,
        target_gpu_memory_fraction=(float(profile_cfg["gpu_fraction"]) if strategy == "auto" else None),
        available_cpu_cores=cores,
        concurrent_reservations=concurrency,
        available_ram_bytes=ram,
        dataset_bytes=dataset_bytes,
        decoded_dataset_bytes=decoded,
        sampled_at=datetime.now(timezone.utc).isoformat(),
    )
    print(
        "[资源决议] "
        f"strategy={strategy}; profile={profile}; "
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
        with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True, timeout=1)) as db, db:
            row = db.execute("SELECT value FROM summary WHERE id=1").fetchone()
        return json.loads(row[0]) if row else {}
    except (sqlite3.Error, ValueError, OSError):
        return {}


def _finite_float(value):
    try:
        if hasattr(value, "item"):
            value = value.item()
        number = float(value)
    except (TypeError, ValueError, RuntimeError):
        return None
    return number if math.isfinite(number) else None


def _numeric_mapping(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, raw in value.items():
        number = _finite_float(raw)
        if number is not None:
            result[str(key)] = round(number, 6)
    return result


def _loss_snapshot(trainer):
    names = [str(value) for value in (getattr(trainer, "loss_names", ()) or ())]
    raw = getattr(trainer, "tloss", None)
    if raw is None:
        return {}
    try:
        if hasattr(raw, "detach"):
            raw = raw.detach()
        if hasattr(raw, "cpu"):
            raw = raw.cpu()
        if hasattr(raw, "tolist"):
            raw = raw.tolist()
        values = list(raw) if isinstance(raw, (list, tuple)) else [raw]
    except (TypeError, RuntimeError):
        return {}
    result = {}
    for index, value in enumerate(values):
        number = _finite_float(value)
        if number is None:
            continue
        key = names[index] if index < len(names) else f"loss_{index}"
        result[key] = round(number, 6)
    return result


def _learning_rate_snapshot(trainer):
    current = _numeric_mapping(getattr(trainer, "lr", None))
    if current:
        return current
    optimizer = getattr(trainer, "optimizer", None)
    groups = getattr(optimizer, "param_groups", ()) if optimizer is not None else ()
    result = {}
    for index, group in enumerate(groups or ()):
        if not isinstance(group, dict):
            continue
        number = _finite_float(group.get("lr"))
        if number is not None:
            result[f"lr/pg{index}"] = round(number, 10)
    return result


def _trainer_total_epochs(trainer, completed):
    total = getattr(trainer, "epochs", None)
    if total is None:
        total = getattr(getattr(trainer, "args", None), "epochs", None)
    try:
        return max(int(completed), int(total))
    except (TypeError, ValueError):
        return int(completed)


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
        self.epoch_durations = []
        self.latest_epoch = None
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
        with closing(self.connect()) as db, db:
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
        with self.lock, closing(self.connect()) as db, db:
            db.execute("INSERT INTO samples(value) VALUES (?)", (json.dumps(sample),))
            db.execute("DELETE FROM samples WHERE id NOT IN (SELECT id FROM samples ORDER BY id DESC LIMIT 720)")
            rows = [json.loads(row[0]) for row in db.execute("SELECT value FROM samples ORDER BY id DESC LIMIT 6")]
            summary = dict(self.resolved, latest=sample, diagnostic=diagnose_window(rows, self.oom),
                           epoch_duration_seconds=self.epoch_duration, images_per_second=self.images_per_second,
                           latest_epoch=self.latest_epoch,
                           total_duration_seconds=round(time.monotonic() - self.started, 3),
                           sampled_at=sample["sampled_at"], interval_seconds=self.interval)
            db.execute("INSERT OR REPLACE INTO summary VALUES (1,?)", (json.dumps(summary),))

    def on_train_start(self, trainer):
        runtime = runtime_loader_resources(trainer)
        expected = {
            "runtime_batch": int(self.resolved["resolved_batch"]),
            "runtime_workers": int(self.resolved["resolved_workers"]),
            "runtime_cache": self.resolved["resolved_cache"],
        }
        if any(runtime[key] != expected[key] for key in expected):
            raise RuntimeError(
                f"RESOURCE_RUNTIME_MISMATCH: resolved={expected}; runtime={runtime}"
            )
        dataset = trainer.train_loader.dataset
        if runtime["runtime_cache"] == "ram" and hasattr(dataset, "ims") and any(image is None for image in dataset.ims):
            raise RuntimeError("RESOURCE_RUNTIME_MISMATCH: runtime declined requested RAM cache")
        with self.lock:
            self.resolved.update(runtime)
        return dict(runtime)

    def on_epoch_start(self, trainer):
        self.epoch_started = time.monotonic()
        loader = getattr(trainer, "train_loader", None)
        actual = getattr(loader, "batch_size", None)
        if actual is None or int(actual) != self.resolved["resolved_batch"]:
            raise RuntimeError("RESOURCE_RUNTIME_MISMATCH: runtime changed batch; explicit worker retry required")

    def on_epoch_end(self, trainer):
        now = time.monotonic()
        duration = max(0.001, now - self.epoch_started)
        count = len(trainer.train_loader.dataset)
        completed = int(trainer.epoch) + 1
        total = _trainer_total_epochs(trainer, completed)
        sampled_at = datetime.now(timezone.utc).isoformat()
        with self.lock, closing(self.connect()) as db, db:
            self.epoch_duration = round(duration, 3)
            self.images_per_second = round(count / duration, 3)
            self.epoch_durations.append(self.epoch_duration)
            self.epoch_durations = self.epoch_durations[-20:]
            window = self.epoch_durations[-5:]
            average_duration = round(sum(window) / len(window), 3)
            eta_seconds = round(average_duration * max(0, total - completed), 3)
            epoch = {
                "epoch": completed,
                "total_epochs": total,
                "duration_seconds": self.epoch_duration,
                "average_epoch_duration_seconds": average_duration,
                "elapsed_seconds": round(now - self.started, 3),
                "eta_seconds": eta_seconds,
                "images_per_second": self.images_per_second,
                "images": count,
                "losses": _loss_snapshot(trainer),
                "metrics": _numeric_mapping(getattr(trainer, "metrics", None)),
                "learning_rates": _learning_rate_snapshot(trainer),
                "eta_basis": "rolling_last_5_epochs",
                "sampled_at": sampled_at,
            }
            self.latest_epoch = epoch
            db.execute("INSERT INTO epochs(value) VALUES (?)", (json.dumps(epoch),))
            db.execute("DELETE FROM epochs WHERE id NOT IN (SELECT id FROM epochs ORDER BY id DESC LIMIT 1000)")
            row = db.execute("SELECT value FROM summary WHERE id=1").fetchone()
            try:
                summary = json.loads(row[0]) if row else {}
            except (TypeError, ValueError, json.JSONDecodeError):
                summary = {}
            summary.update(self.resolved)
            summary.update({
                "epoch_duration_seconds": self.epoch_duration,
                "images_per_second": self.images_per_second,
                "latest_epoch": epoch,
                "total_duration_seconds": epoch["elapsed_seconds"],
                "sampled_at": sampled_at,
                "interval_seconds": self.interval,
            })
            db.execute("INSERT OR REPLACE INTO summary VALUES (1,?)", (json.dumps(summary),))

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
