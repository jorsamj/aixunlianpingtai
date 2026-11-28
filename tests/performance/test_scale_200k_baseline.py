"""W14 isolated scale baseline: real 200k-material SQLite read/write paths.

Opt-in only: ``RUN_SCALE_PERF=1``. The fixture builds an isolated temporary data
directory with the *real* schema owners (MaterialRepository, AnnotationRepository,
AlgorithmSqlStore, TaskRepository, TrainingMaterialUsage, CandidateStore,
training_selection_reference) and then measures the existing read paths. No
production data, network, GPU or model binary is touched.

RUN:  $env:RUN_SCALE_PERF='1'; python -m pytest -q tests/performance/test_scale_200k_baseline.py -rs
Optional: $env:SCALE_PERF_REPORT='<path>.json' writes the raw measured report.
Optional: $env:SCALE_MATERIALS='50000' runs the reproducible smaller fixture.

These are isolated measurements, never production SLAs. Every ``SCALE_PERF``
JSON line is evidence for docs/performance/2026-11-24-scale-200k-baseline.md.
"""
from __future__ import annotations

import builtins
import hashlib
import io
import json
import math
import os
import platform
import socket
import sqlite3
import statistics
import threading
import time
from contextlib import closing, contextmanager
from dataclasses import replace
from pathlib import Path
from unittest import mock

import pytest

pytestmark = [
    pytest.mark.scale,
    pytest.mark.skipif(
        os.environ.get("RUN_SCALE_PERF") != "1",
        reason="set RUN_SCALE_PERF=1 for the isolated 200k scale baseline",
    ),
]

PROJECT = "scale200k"
FOCUS_SOURCE = "src-focus"
FOCUS_IDS = 20_000
USED_FOCUS_IDS = 500
TOTAL_MATERIALS = int(os.environ.get("SCALE_MATERIALS", "200000"))
TOTAL_GT = min(TOTAL_MATERIALS, int(os.environ.get("SCALE_GT", "40000")))
TOTAL_ALGORITHMS = 110
VERSIONS_PER_ALGORITHM = 10
TOTAL_HISTORY_TASKS = 1_100
TOTAL_USAGE_TASKS = 200
CLAIM_TASKS = 60
TOTAL_CONVERSIONS = 1_000
TOTAL_CANDIDATES = 20_000
REAL_IMAGES = 8
ALGO_ACTIVE = "algo-000"

RESULTS: dict = {"environment": {}, "build": {}, "cases": [], "matches": [], "notes": []}
FROZEN: dict[str, str] = {}
MODEL_SUFFIXES = {".pt", ".pth", ".onnx", ".bin", ".engine", ".rknn", ".bmodel"}


# ---------------------------------------------------------------------------
# Bounded instrumentation: SQL statements, JSON parses, SHA256, file opens.
# ---------------------------------------------------------------------------
_ACTIVE_PROBE: dict = {"probe": None}


class Probe:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.sql_statements = 0
        self.sql_ms = 0.0
        self.max_sql_ms = 0.0
        self.json_loads = 0
        self.sha256_calls = 0
        self.file_opens = 0
        self.file_paths: list[str] = []
        self.network_calls = 0
        self.transactions: list[tuple[float, str]] = []
        self._open_tx: dict[int, tuple[float, str]] = {}

    def _sql(self, connection, sql: str, elapsed_ms: float) -> None:
        head = " ".join(str(sql).strip().split())[:60].upper()
        with self.lock:
            self.sql_statements += 1
            self.sql_ms += elapsed_ms
            self.max_sql_ms = max(self.max_sql_ms, elapsed_ms)
            key = id(connection)
            if head.startswith("BEGIN"):
                self._open_tx[key] = (time.perf_counter(), head)
            elif head.startswith(("COMMIT", "ROLLBACK", "END")) and key in self._open_tx:
                began, statement = self._open_tx.pop(key)
                self.transactions.append(((time.perf_counter() - began) * 1000, statement))

    def _file(self, path) -> None:
        name = str(path)
        with self.lock:
            self.file_opens += 1
            if len(self.file_paths) < 300:
                self.file_paths.append(name)

    def snapshot(self, calls: int = 1) -> dict:
        calls = max(1, int(calls))
        with self.lock:
            durations = sorted(duration for duration, _ in self.transactions)
            return {
                "sql_statements": self.sql_statements,
                "sql_statements_per_call": round(self.sql_statements / calls, 2),
                "sql_sum_ms": round(self.sql_ms, 3),
                "sql_max_ms": round(self.max_sql_ms, 3),
                "json_loads": self.json_loads,
                "json_loads_per_call": round(self.json_loads / calls, 2),
                "sha256_calls": self.sha256_calls,
                "sha256_calls_per_call": round(self.sha256_calls / calls, 2),
                "file_opens": self.file_opens,
                "file_opens_per_call": round(self.file_opens / calls, 2),
                "network_calls": self.network_calls,
                "transactions": len(durations),
                "max_transaction_ms": round(durations[-1], 3) if durations else 0.0,
                "slow_transactions_100ms": sum(1 for value in durations if value >= 100),
                "model_binary_opens": sum(1 for name in self.file_paths
                                          if Path(name).suffix.lower() in MODEL_SUFFIXES),
            }


class _ProbeConnection(sqlite3.Connection):
    def execute(self, sql, *args, **kwargs):
        probe = _ACTIVE_PROBE["probe"]
        if probe is None:
            return super().execute(sql, *args, **kwargs)
        began = time.perf_counter()
        try:
            return super().execute(sql, *args, **kwargs)
        finally:
            probe._sql(self, sql, (time.perf_counter() - began) * 1000)


_REAL_CONNECT = sqlite3.connect
_REAL_JSON_LOADS = json.loads
_REAL_SHA256 = hashlib.sha256
_REAL_IO_OPEN = io.open
_REAL_BUILTINS_OPEN = builtins.open
_REAL_GETADDRINFO = socket.getaddrinfo
_REAL_CREATE_CONNECTION = socket.create_connection


def _probe_connect(*args, **kwargs):
    if _ACTIVE_PROBE["probe"] is None:
        return _REAL_CONNECT(*args, **kwargs)
    if "factory" not in kwargs:
        kwargs["factory"] = _ProbeConnection
    elif not issubclass(kwargs["factory"], _ProbeConnection):
        kwargs["factory"] = type("_ProbeConnectionCombined", (kwargs["factory"], _ProbeConnection), {})
    return _REAL_CONNECT(*args, **kwargs)


def _counted(function_name, real, counter_attr):
    def wrapper(*args, **kwargs):
        probe = _ACTIVE_PROBE["probe"]
        if probe is not None:
            with probe.lock:
                setattr(probe, counter_attr, getattr(probe, counter_attr) + 1)
        return real(*args, **kwargs)
    wrapper.__name__ = function_name
    return wrapper


def _counted_open(function_name, real):
    def wrapper(file, *args, **kwargs):
        probe = _ACTIVE_PROBE["probe"]
        if probe is not None:
            probe._file(file)
        return real(file, *args, **kwargs)
    wrapper.__name__ = function_name
    return wrapper


@contextmanager
def _instrumented():
    probe = Probe()
    _ACTIVE_PROBE["probe"] = probe
    try:
        with mock.patch.object(sqlite3, "connect", _probe_connect), \
                mock.patch.object(json, "loads", _counted("loads", _REAL_JSON_LOADS, "json_loads")), \
                mock.patch.object(hashlib, "sha256", _counted("sha256", _REAL_SHA256, "sha256_calls")), \
                mock.patch.object(io, "open", _counted_open("io_open", _REAL_IO_OPEN)), \
                mock.patch.object(builtins, "open", _counted_open("open", _REAL_BUILTINS_OPEN)), \
                mock.patch.object(socket, "getaddrinfo",
                                  _counted("getaddrinfo", _REAL_GETADDRINFO, "network_calls")), \
                mock.patch.object(socket, "create_connection",
                                  _counted("create_connection", _REAL_CREATE_CONNECTION, "network_calls")):
            yield probe
    finally:
        _ACTIVE_PROBE["probe"] = None


class _RssSampler(threading.Thread):
    """Best-effort process RSS peak for one measurement window (psutil)."""

    def __init__(self) -> None:
        super().__init__(daemon=True)
        self.peak = 0
        self._halt = threading.Event()
        try:
            import psutil

            self._process = psutil.Process()
        except Exception:  # pragma: no cover - psutil present in this environment
            self._process = None

    def run(self) -> None:
        if self._process is None:
            return
        while not self._halt.wait(0.01):
            try:
                self.peak = max(self.peak, self._process.memory_info().rss)
            except Exception:
                return

    def stop(self) -> int:
        self._halt.set()
        self.join(timeout=2)
        return self.peak


def _pct(values: list[float], quantile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, min(len(ordered) - 1, math.ceil(len(ordered) * quantile) - 1))
    return ordered[index]


def _summary(samples: list[float]) -> dict:
    ordered = sorted(samples)
    return {"samples": len(ordered), "p50_ms": round(statistics.median(ordered), 3),
            "p95_ms": round(_pct(ordered, 0.95), 3), "min_ms": round(ordered[0], 3),
            "max_ms": round(ordered[-1], 3)}


def _json_bytes(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, default=str).encode("utf-8"))


def _record(record: dict) -> None:
    RESULTS["cases"].append(record)
    print("SCALE_PERF " + json.dumps(record, ensure_ascii=False, sort_keys=True, default=str))


def _measure(case: dict, callable_, *, area: str, name: str, warmup: int = 1, samples: int = 21,
             cold: bool = True, cold_callable=None, bytes_of=None, extra: dict | None = None,
             per_call_factor: int = 1) -> dict:
    """Measure one idempotent read: one cold call (optional) + warm p50/p95 window.

    SQL/JSON/SHA256/file counters are divided by ``per_call_factor`` (number of
    logical operations inside one sampled call).
    """
    cold_ms = None
    if cold:
        began = time.perf_counter()
        first = (cold_callable or callable_)()
        cold_ms = (time.perf_counter() - began) * 1000
    else:
        first = callable_()
    for _ in range(warmup):
        callable_()
    values: list[float] = []
    sampler = _RssSampler()
    sampler.start()
    with _instrumented() as probe:
        window_started = time.perf_counter()
        for _ in range(samples):
            t0 = time.perf_counter()
            result = callable_()
            values.append((time.perf_counter() - t0) * 1000)
        window_ms = (time.perf_counter() - window_started) * 1000
    rss_peak = sampler.stop()
    record = {
        "area": area, "case": name,
        "cold_ms": round(cold_ms, 3) if cold_ms is not None else None,
        **_summary(values), "window_total_ms": round(window_ms, 3),
        "response_bytes": int(bytes_of(result)) if bytes_of is not None else None,
        "rss_peak_mb": round(rss_peak / (1024 * 1024), 1) if rss_peak else None,
        **probe.snapshot(samples * max(1, int(per_call_factor))),
        **({"note": extra} if isinstance(extra, str) else (extra or {})),
    }
    case.setdefault("measures", []).append(record)
    _record(record)
    return {"first": first, "last": result, "record": record}


def _single_cold(case: dict, callable_, *, area: str, name: str, bytes_of=None,
                 extra: dict | None = None) -> dict:
    sampler = _RssSampler()
    sampler.start()
    began = time.perf_counter()
    with _instrumented() as probe:
        result = callable_()
    elapsed = (time.perf_counter() - began) * 1000
    rss_peak = sampler.stop()
    record = {
        "area": area, "case": name, "cold_ms": round(elapsed, 3), "samples": 1,
        "response_bytes": int(bytes_of(result)) if bytes_of is not None else None,
        "rss_peak_mb": round(rss_peak / (1024 * 1024), 1) if rss_peak else None,
        **probe.snapshot(1), **(extra or {}),
    }
    case.setdefault("measures", []).append(record)
    _record(record)
    return {"result": result, "record": record}


# ---------------------------------------------------------------------------
# Fixture: isolated 200k world built through the real owners.
# ---------------------------------------------------------------------------
def _timestamp(index: int) -> str:
    seconds = index * 7
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, seconds = divmod(rest, 60)
    return f"2026-07-{1 + days // 24:02d}T{hours:02d}:{minutes:02d}:{seconds:02d}+00:00"


def _material(index: int) -> dict:
    if index < FOCUS_IDS:
        source, status = FOCUS_SOURCE, "processed"
        labels = ["fire"] if index % 5 == 0 else ["smoke"]
    else:
        source = "src-a" if index % 3 else "src-b"
        status = "processed" if index % 7 else "pending_decision"
        labels = (["fire"] if index % 3 == 0 else ["smoke"] if index % 2 == 0 else ["person"])
    return {"id": f"img-{index:06d}", "filename": f"camera-{index:06d}.jpg",
            "object_key": f"uploads/camera-{index:06d}.jpg",
            "content_sha256": f"{index + 1:064x}", "processing_status": status,
            "storage_source_id": source, "storage_type": "local", "labels": labels,
            "width": 800, "height": 600, "size_bytes": 512 * 1024 + index,
            "created_at": _timestamp(index)}


def _ground_truth(index: int) -> dict:
    labels = _material(index)["labels"]
    if index % 11 == 0:
        return {"image_id": f"img-{index:06d}", "annotation_state": "confirmed_empty",
                "annotation_scope": labels, "boxes": []}
    return {"image_id": f"img-{index:06d}", "annotation_state": "annotated",
            "annotation_scope": labels,
            "boxes": [{"label": label, "x1": 20, "y1": 30, "x2": 200, "y2": 300} for label in labels]}


def _build_world(root: Path) -> dict:
    from PIL import Image

    from platform_core.algorithm_sql_store import AlgorithmSqlStore
    from platform_core.annotation_candidates import CandidateStore
    from platform_core.annotation_repository import AnnotationRepository
    from platform_core.conversion_history import ConversionHistoryProjection
    from platform_core.material_repository import MaterialRepository
    from platform_core.negative_pool import NegativePool
    from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository
    from platform_core.task_runtime.artifacts import ArtifactStore
    from platform_core.task_runtime.models import TaskStatus
    from platform_core.training_material_usage import TrainingMaterialUsage

    build: list[dict] = []
    world = {"root": root, "data_dir": root / "data"}
    data_dir = world["data_dir"]
    project_path = data_dir / "projects" / PROJECT
    project_path.mkdir(parents=True)
    (project_path / "meta.json").write_text(json.dumps({
        "id": PROJECT, "name": "isolated scale fixture",
        "labels": [{"code": "fire", "display_name": "fire"},
                   {"code": "smoke", "display_name": "smoke"},
                   {"code": "person", "display_name": "person"}],
    }), encoding="utf-8")

    started = time.perf_counter()
    repository = MaterialRepository(project_path)
    for base in range(0, TOTAL_MATERIALS, 1_000):
        repository.upsert_many([_material(index) for index in range(base, min(base + 1_000, TOTAL_MATERIALS))])
    build.append({"step": "materials", "rows": TOTAL_MATERIALS, "seconds": round(time.perf_counter() - started, 2)})

    uploads = project_path / "uploads"
    uploads.mkdir()
    real_records = []
    for index in range(REAL_IMAGES):
        stream = io.BytesIO()
        Image.new("RGB", (320 + index, 240 + index), (20 * index, 40, 60)).save(stream, format="JPEG", quality=82)
        payload = stream.getvalue()
        name = f"real-{index:02d}.jpg"
        (uploads / name).write_bytes(payload)
        real_records.append({"id": f"real-{index:02d}", "filename": name, "object_key": f"uploads/{name}",
                             "storage_source_id": "default_local", "storage_type": "local",
                             "content_sha256": hashlib.sha256(payload).hexdigest(), "size_bytes": len(payload),
                             "processing_status": "processed", "labels": ["fire"], "annotated": True,
                             "width": 320 + index, "height": 240 + index,
                             "created_at": _timestamp(TOTAL_MATERIALS + index)})
    repository.upsert_many(real_records)

    started = time.perf_counter()
    annotations = AnnotationRepository(project_path)
    for base in range(0, TOTAL_GT, 500):
        annotations.upsert_many([_ground_truth(index) for index in range(base, min(base + 500, TOTAL_GT))])
    build.append({"step": "formal_gt", "rows": TOTAL_GT, "seconds": round(time.perf_counter() - started, 2)})

    started = time.perf_counter()
    algorithms = AlgorithmSqlStore(project_path / "algorithms.json")
    algorithm_items = []
    for algo_index in range(TOTAL_ALGORITHMS):
        versions = []
        for version_index in range(VERSIONS_PER_ALGORITHM):
            versions.append({
                "id": f"ver-{algo_index:03d}-{version_index:02d}",
                "version_name": f"v{version_index + 1}.0", "version_no": version_index + 1,
                "task_id": f"hist-{algo_index * VERSIONS_PER_ALGORITHM + version_index:04d}",
                "framework": "ultralytics", "training_status": "succeeded",
                "stored_path": str(project_path / "models" / f"{algo_index:03d}-{version_index:02d}.pt"),
                "model_name": f"model-{algo_index:03d}-{version_index:02d}.pt",
                "artifact_verified": True, "trainable": True,
                "created_at": _timestamp(algo_index * VERSIONS_PER_ALGORITHM + version_index),
                "finished_at": _timestamp(algo_index * VERSIONS_PER_ALGORITHM + version_index + 1),
                "map50": 0.5 + (version_index % 10) / 100.0, "map50_95": 0.3,
                "metrics": {"map50": 0.5 + (version_index % 10) / 100.0, "mAP50-95": 0.3},
            })
        algorithm_items.append({
            "id": f"algo-{algo_index:03d}", "name": f"algorithm-{algo_index:03d}",
            "remark": "isolated scale fixture", "industry": "industrial",
            "algorithm_type": "yolo_ultralytics", "versions": versions,
            "current_version_id": versions[-1]["id"],
            "created_at": _timestamp(algo_index), "updated_at": _timestamp(algo_index * 2)})
    algorithms.replace_all(algorithm_items)
    build.append({"step": "algorithms", "algorithms": TOTAL_ALGORITHMS,
                  "versions": TOTAL_ALGORITHMS * VERSIONS_PER_ALGORITHM,
                  "seconds": round(time.perf_counter() - started, 2)})

    started = time.perf_counter()
    task_path = data_dir / "task_runtime" / "tasks.sqlite3"
    task_path.parent.mkdir(parents=True)
    tasks = TaskRepository(task_path)
    records = []
    for index in range(TOTAL_HISTORY_TASKS):
        record = TaskRecord.new(f"hist-{index:04d}", PROJECT, TaskKind.TRAINING,
                                "payload.json", f"training:fixture:{index}")
        if index % 11 == 0:
            record = replace(record, status=TaskStatus.FAILED, error="isolated fixture failure",
                             finished_at=_timestamp(index))
        else:
            record = replace(record, status=TaskStatus.SUCCEEDED, finished_at=_timestamp(index))
        records.append(record)
    for index in range(CLAIM_TASKS):
        records.append(TaskRecord.new(f"claim-{index:03d}", PROJECT, TaskKind.TRAINING,
                                      "payload.json", f"training:claim:{index}"))
    for record in records:
        tasks.create(record)
    build.append({"step": "tasks", "tasks": len(records),
                  "seconds": round(time.perf_counter() - started, 2)})

    started = time.perf_counter()
    usage = TrainingMaterialUsage(task_path)
    for index in range(TOTAL_USAGE_TASKS):
        task_id = f"hist-{index:04d}"
        if index < 25:
            ids = [f"img-{index * 20 + offset:06d}" for offset in range(20)]
        else:
            ids = [f"img-{100_000 + index * 10 + offset:06d}" for offset in range(10)]
        sources = repository.get_many(ids)
        usage.record_selected(PROJECT, ALGO_ACTIVE, task_id,
                              {"snapshot_id": f"snapshot-{index:04d}",
                               "images": [{"image_id": row["id"], "role": "train",
                                           "content_sha256": row["content_sha256"]} for row in sources]},
                              source_images=sources)
        usage.record_execution(task_id, completed_epoch=True)
    build.append({"step": "training_usage", "tasks": TOTAL_USAGE_TASKS,
                  "seconds": round(time.perf_counter() - started, 2)})

    started = time.perf_counter()
    artifacts = ArtifactStore(data_dir / "task_runtime" / "artifacts")
    candidates = CandidateStore(artifacts, task_id="ai-scale-task", page_size=200)
    candidates.initialize(labels=["fire", "smoke"], total_images=TOTAL_CANDIDATES)
    for base in range(0, TOTAL_CANDIDATES, 1_000):
        items = []
        for index in range(base, base + 1_000):
            status = "success" if index % 10 else ("failed" if index % 2 else "empty")
            boxes = ([{"label": "fire", "x1": 10, "y1": 10, "x2": 90, "y2": 90,
                       "confidence": 0.9}] if status == "success" else [])
            items.append({"image_id": f"img-{index:06d}", "status": status, "boxes": boxes,
                          "confidence": 0.9 if boxes else None, "source": "isolated_fixture"})
        candidates.append_items(items)
    build.append({"step": "ai_candidates", "rows": TOTAL_CANDIDATES,
                  "seconds": round(time.perf_counter() - started, 2)})

    started = time.perf_counter()
    jobs_dir = project_path / "deploy" / "jobs"
    jobs_dir.mkdir(parents=True)
    for index in range(TOTAL_CONVERSIONS):
        directory = jobs_dir / f"conv-{index:04d}"
        directory.mkdir()
        (directory / "job.json").write_text(json.dumps({
            "id": f"conv-{index:04d}", "status": "succeeded" if index % 3 else "failed",
            "created_at": _timestamp(index), "target": "rknn",
            "params": {"chip": "rk3588", "precision": "fp16" if index % 2 else "int8"},
            "source_trace": {"algorithm_id": f"algo-{index % TOTAL_ALGORITHMS:03d}",
                             "version_id": f"ver-{index % TOTAL_ALGORITHMS:03d}-00"},
        }), encoding="utf-8")
    build.append({"step": "conversion_history", "records": TOTAL_CONVERSIONS,
                  "seconds": round(time.perf_counter() - started, 2)})

    started = time.perf_counter()
    for index in range(60):
        artifacts.atomic_write_json(f"hist-{index:04d}", "payload.json", {
            "algorithm_asset_id": ALGO_ACTIVE, "auto_version_id": "ver-000-00",
            "asset_algorithm_name": "algorithm-000", "epochs": 50, "workers": 4,
            "batch": 16, "imgsz": 640, "framework": "ultralytics", "device": "auto"})
    for index in range(20):
        artifacts.atomic_write_json(f"hist-{index:04d}", "result.json", {
            "id": f"hist-{index:04d}", "asset_algorithm_id": ALGO_ACTIVE,
            "training_report": {
                "best_metrics": {"map50": 0.62, "map50_95": 0.41},
                "requested_train_params": {"epochs": 50, "workers": 4},
                "actual_train_params": {"epochs": 40, "workers": 4},
                "history": [{"epoch": epoch, "map50": 0.4 + epoch / 100.0} for epoch in range(1, 61)],
            },
            "evaluation": {"metrics": {"map50": 0.58, "map50_95": 0.37}},
            "best_epoch": 40, "completed_epochs": 40})
    build.append({"step": "task_artifacts", "payloads": 60, "reports": 20,
                  "seconds": round(time.perf_counter() - started, 2)})

    sizes = {
        "materials.sqlite3": (project_path / "materials.sqlite3").stat().st_size,
        "annotations.sqlite3": (project_path / "annotations.sqlite3").stat().st_size,
        "algorithms.sqlite3": (project_path / "algorithms.sqlite3").stat().st_size,
        "tasks.sqlite3": task_path.stat().st_size,
        "candidates_items.sqlite3": candidates.path.stat().st_size,
    }
    world.update(project_path=project_path, repository=repository, annotations=annotations,
                 algorithms=algorithms, tasks=tasks, task_path=task_path, usage=usage,
                 artifacts=artifacts, candidates=candidates, jobs_dir=jobs_dir,
                 conversion_projection=ConversionHistoryProjection(),
                 real_records=real_records, build=build, sizes=sizes,
                 negative_pool=NegativePool(repository))
    return world


@pytest.fixture(scope="module")
def scale(tmp_path_factory):
    root = tmp_path_factory.mktemp("scale200k_w14")
    started = time.perf_counter()
    world = _build_world(root)
    world["build_seconds"] = round(time.perf_counter() - started, 2)
    RESULTS["build"] = {"root": str(root), "build_seconds": world["build_seconds"],
                        "steps": world["build"], "db_sizes_bytes": world["sizes"]}
    RESULTS["environment"] = {
        "platform": platform.platform(), "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version, "machine": platform.machine(),
        "cpu": os.environ.get("PROCESSOR_IDENTIFIER", platform.processor()),
        "cpu_count": os.cpu_count(), "ram_bytes": _total_ram_bytes(),
        "material_rows": TOTAL_MATERIALS, "gt_rows": TOTAL_GT,
        "algorithms": TOTAL_ALGORITHMS, "versions": TOTAL_ALGORITHMS * VERSIONS_PER_ALGORITHM,
        "tasks": TOTAL_HISTORY_TASKS + CLAIM_TASKS, "usage_tasks": TOTAL_USAGE_TASKS,
        "ai_candidates": TOTAL_CANDIDATES, "conversions": TOTAL_CONVERSIONS,
        "real_image_files": REAL_IMAGES,
        "isolation": "pytest tmp_path_factory; no production data, network or GPU",
    }
    print("SCALE_PERF build " + json.dumps({"build_seconds": world["build_seconds"],
                                            "steps": world["build"], "sizes": world["sizes"]},
                                           ensure_ascii=False))
    try:
        yield world
    finally:
        RESULTS["environment"]["build_total_seconds"] = world["build_seconds"]
        output = os.environ.get("SCALE_PERF_REPORT")
        if output:
            Path(output).parent.mkdir(parents=True, exist_ok=True)
            Path(output).write_text(json.dumps(RESULTS, ensure_ascii=False, indent=2, default=str),
                                    encoding="utf-8")
            print("SCALE_PERF report written to " + output)


def _total_ram_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.virtual_memory().total)
    except Exception:  # pragma: no cover
        return None


# ---------------------------------------------------------------------------
# 1) Material library read path (v61 endpoint function + owner repositories).
# ---------------------------------------------------------------------------
def test_material_library_200k(scale, monkeypatch):
    import app as api

    monkeypatch.setattr(api, "DATA_DIR", scale["data_dir"])
    repository = scale["repository"]
    area = "material_library"
    case: dict = {"area": area}
    page_args = dict(page=1, page_size=50, query="", reader_view=True,
                     storage_source_id=None, processing_status=None, label=None,
                     annotated=None, annotation_state=None, source_batch_id=None,
                     quality_status=None, created_from=None, created_to=None)

    first = _measure(case, lambda: api.list_materials_v61(PROJECT, **page_args),
                     area=area, name="first_screen_50_reader_view", samples=21, bytes_of=_json_bytes)
    assert len(first["last"]["items"]) == 50
    assert first["last"]["total"] == TOTAL_MATERIALS + REAL_IMAGES

    total_pages = (TOTAL_MATERIALS + REAL_IMAGES) // 50
    deep = _measure(case, lambda: api.list_materials_v61(PROJECT, **{**page_args, "page": total_pages - 1}),
                    area=area, name="deep_page_numbered_offset", samples=11, bytes_of=_json_bytes)
    assert len(deep["last"]["items"]) == 50

    filtered = _measure(case, lambda: api.list_materials_v61(
        PROJECT, **{**page_args, "storage_source_id": ["src-a"], "processing_status": "processed",
                    "label": ["smoke"]}),
        area=area, name="combined_filter_source_status_label", samples=11, bytes_of=_json_bytes)
    assert filtered["last"]["total"] > 0

    # Worst case: a combined filter whose intersection is empty forces the ordered
    # page scan to exhaust the filtered pool before it can conclude "no rows".
    empty_case = _measure(case, lambda: api.list_materials_v61(
        PROJECT, **{**page_args, "storage_source_id": ["src-b"], "processing_status": "processed",
                    "label": ["absent-label"]}),
        area=area, name="combined_filter_empty_intersection", samples=7, bytes_of=_json_bytes)
    assert empty_case["last"]["total"] == 0

    searched = _measure(case, lambda: api.list_materials_v61(PROJECT, **{**page_args, "query": "camera-0012"}),
                        area=area, name="filename_search", samples=11, bytes_of=_json_bytes)
    assert searched["last"]["total"] > 0

    _measure(case, repository.processing_status_counts, area=area,
             name="status_counts_cold_then_warm", warmup=0, samples=3)
    _measure(case, repository.annotation_index_counts, area=area,
             name="annotation_index_counts_cold_then_warm", warmup=0, samples=3)
    _measure(case, repository.label_reference_usage, area=area,
             name="label_reference_usage", samples=3)
    _measure(case, repository.summary, area=area, name="material_summary", samples=3)

    detail = _measure(case, lambda: api.get_annotation(PROJECT, "img-000003", reader_view=True),
                      area=area, name="material_detail_reader_view", samples=21, bytes_of=_json_bytes)
    assert detail["last"]["ok"] and detail["last"]["image"]["id"] == "img-000003"

    # Real file I/O: cold thumbnails verify source SHA256 and decode/resize/encode; warm hits the cache.
    from platform_core.storage.manager import StorageManager

    sampled = repository.get_many([record["id"] for record in scale["real_records"]])
    manager = StorageManager(data_dir=scale["data_dir"], project_id=PROJECT, materials=repository)
    cold_samples = []
    for row in sampled[:4]:
        got = _single_cold(case, lambda row=row: _thumbnail_once(manager, row),
                           area=area, name="thumbnail_cold_real_file", bytes_of=lambda value: value["bytes"],
                           extra={"image_id": row["id"]})
        cold_samples.append(got["record"]["cold_ms"])
    _record({"area": area, "case": "thumbnail_cold_summary_4_images",
             "samples": len(cold_samples), "p50_ms": round(statistics.median(cold_samples), 3),
             "p95_ms": round(max(cold_samples), 3)})
    warm = _measure(case, lambda: _thumbnail_once(manager, sampled[0]), area=area,
                    name="thumbnail_warm_file_response", warmup=1, samples=11,
                    bytes_of=lambda value: value["bytes"])
    assert warm["last"]["bytes"] > 0

    plans = {}
    with closing(repository._connect()) as database:
        for name, sql, params in (
                ("deep_offsets",
                 "SELECT id,created_at,payload_json FROM materials ORDER BY created_at,id LIMIT 51 OFFSET ?",
                 ((total_pages - 2) * 50,)),
                ("search_like",
                 "SELECT id FROM materials WHERE filename LIKE ? COLLATE NOCASE ORDER BY created_at,id LIMIT 51",
                 ("%camera-0012%",)),
                ("status_counts",
                 "SELECT COUNT(*),COALESCE(SUM(annotated),0),COALESCE(SUM(box_count),0) FROM materials", ())):
            plans[name] = [str(row[3]) for row in database.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()]
    RESULTS["query_plans"] = plans
    _record({"area": area, "case": "query_plans", **plans})
    RESULTS["notes"].append("SQL counted per connection.execute; cursor.execute paths are not double counted.")
    assert set(plans) == {"deep_offsets", "search_like", "status_counts"}


def _thumbnail_once(manager, row) -> dict:
    path, lock = manager.thumbnail(row, max_edge=384, hold_verified_lock=True)
    try:
        size = path.stat().st_size
    finally:
        lock.release()
    return {"path": str(path), "bytes": int(size)}


# ---------------------------------------------------------------------------
# 2) Cross-page selection: real frozen reference, 20k ids, exclusion semantics.
# ---------------------------------------------------------------------------
def test_cross_page_selection_20k(scale):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from platform_core.training_material_picker_api import training_material_picker_router
    import platform_core.training_material_picker_api as picker_module

    app = FastAPI()
    app.include_router(training_material_picker_router(
        lambda project_id: {"id": project_id} if project_id == PROJECT else None,
        lambda: scale["data_dir"],
        algorithm_provider=lambda project_id, algorithm_id: (
            {"id": algorithm_id, "name": f"algorithm-{algorithm_id[-3:]}",
             "versions": [], "algorithm_type": "yolo_ultralytics"}
            if algorithm_id.startswith("algo-") else None)))
    client = TestClient(app)
    area = "cross_page_selection"
    base = {"algorithm_asset_id": ALGO_ACTIVE, "role": "train", "storage_source_ids": [FOCUS_SOURCE]}
    case: dict = {"area": area}

    def freeze(history_policy: str):
        return client.post(f"/api/v62/projects/{PROJECT}/training-materials/selection-reference",
                           json={**base, "history_policy": history_policy})

    excluded = _single_cold(case, lambda: freeze("new_for_algorithm"),
                            area=area, name="freeze_20k_with_history_exclusion",
                            bytes_of=lambda response: len(response.content))
    response = excluded["result"]
    assert response.status_code == 200, response.text
    frozen_excluded = response.json()
    assert frozen_excluded["count"] == FOCUS_IDS - USED_FOCUS_IDS, frozen_excluded
    assert "image_ids" not in frozen_excluded and len(response.content) < 4096
    RESULTS["matches"].append({"check": "freeze with history exclusion",
                               "expected": FOCUS_IDS - USED_FOCUS_IDS,
                               "actual": frozen_excluded["count"]})
    RESULTS["cases"][-1]["note"] = ("history_policy=new_for_algorithm excludes 500 ids that the "
                                    "same algorithm already trained on (usage token anti-join)")

    included = _single_cold(case, lambda: freeze("include_history"), area=area,
                            name="freeze_20k_include_history",
                            bytes_of=lambda response: len(response.content))
    response_all = included["result"]
    assert response_all.status_code == 200, response_all.text
    frozen_all = response_all.json()
    assert frozen_all["count"] == FOCUS_IDS, frozen_all
    assert len(response_all.content) < 4096
    ref_all = frozen_all["selection_ref"]
    FROZEN["include_history"] = ref_all
    FROZEN["excluded"] = frozen_excluded["selection_ref"]
    RESULTS["matches"].append({"check": "freeze include history", "expected": FOCUS_IDS,
                               "actual": frozen_all["count"]})

    # Exclusion proof: the 500 trained ids are absent from the excluded manifest and
    # present again after an explicit include-history re-selection.
    from platform_core.training_selection_reference import read_selection, selection_context

    excluded_context = selection_context(scale["data_dir"], PROJECT,
                                        {**base, "history_policy": "new_for_algorithm"}, "train")
    excluded_ids = read_selection(scale["data_dir"], FROZEN["excluded"], excluded_context)
    used_sample = [f"img-{index:06d}" for index in range(0, 40)]
    RESULTS["matches"].append({"check": "excluded manifest excludes 500 trained ids",
                               "expected": 0,
                               "actual": len(set(excluded_ids) & set(used_sample))})
    RESULTS["matches"].append({"check": "included manifest keeps 500 trained ids",
                               "expected": 40,
                               "actual": len(set(read_selection(
                                   scale["data_dir"], ref_all,
                                   selection_context(scale["data_dir"], PROJECT,
                                                     {**base, "history_policy": "include_history"},
                                                     "train"))) & set(used_sample))})

    context = {**base, "history_policy": "include_history"}
    summary = _measure(case, lambda: client.post(
        f"/api/v62/projects/{PROJECT}/training-materials/selection-summary",
        json={"train_selection_ref": ref_all, **context}),
        area=area, name="selection_summary_20k_reference", samples=11,
        bytes_of=lambda response: len(response.content))
    summary_body = summary["last"].json()
    assert summary["last"].status_code == 200, summary["last"].text
    assert summary_body["requested_count"] == FOCUS_IDS
    assert summary_body["selectable_count"] == FOCUS_IDS
    assert "image_ids" not in summary_body
    RESULTS["matches"].append({"check": "selection summary count", "expected": FOCUS_IDS,
                               "actual": summary_body["requested_count"]})

    membership = _measure(case, lambda: client.post(
        f"/api/v62/projects/{PROJECT}/training-materials/selection-membership",
        json={"selection_ref": ref_all, **context,
              "image_ids": [f"img-{index:06d}" for index in range(0, 200, 2)]}),
        area=area, name="selection_membership_100_of_20k", samples=11,
        bytes_of=lambda response: len(response.content))
    assert membership["last"].status_code == 200, membership["last"].text
    assert len(membership["last"].json()["items"]) == 100

    union = _measure(case, lambda: client.post(
        f"/api/v62/projects/{PROJECT}/training-materials/selection-union",
        json={"positive_ref": ref_all, **context}),
        area=area, name="selection_union_refreeze_20k", samples=5,
        bytes_of=lambda response: len(response.content))
    assert union["last"].status_code == 200, union["last"].text
    assert union["last"].json()["count"] == FOCUS_IDS
    FROZEN["union"] = union["last"].json()["selection_ref"]
    RESULTS["matches"].append({"check": "union refreeze count", "expected": FOCUS_IDS,
                               "actual": union["last"].json()["count"]})

    from platform_core.training_selection_reference import read_selection, selection_context

    context_full = selection_context(scale["data_dir"], PROJECT, context, "train")
    read = _measure(case, lambda: read_selection(scale["data_dir"], ref_all, context_full),
                    area=area, name="frozen_manifest_read_20k", samples=5,
                    bytes_of=lambda ids: len(ids) * 8)
    assert len(read["last"]) == FOCUS_IDS

    # Bulk resolve guard: a 20k+ selection must not transfer 20k ids to the browser.
    began = time.perf_counter()
    bulk = client.post(f"/api/v62/projects/{PROJECT}/training-materials/bulk-selection",
                       json={"algorithm_asset_id": ALGO_ACTIVE, "role": "train",
                             "all_available": True, "prefer_reference_over": 2000})
    _record({"area": area, "case": "bulk_selection_over_cap_guard",
             "elapsed_ms": round((time.perf_counter() - began) * 1000, 3),
             "status": bulk.status_code, "response_bytes": len(bulk.content),
             "detail": bulk.text[:160]})
    assert bulk.status_code == 422 and len(bulk.content) < 4096
    assert "items" not in bulk.json()

    def picker_page(page_number: int):
        return client.post(f"/api/v62/projects/{PROJECT}/training-materials/page",
                           json={"algorithm_asset_id": ALGO_ACTIVE, "page": page_number,
                                 "page_size": 60, "count_mode": "deferred"})

    page = _measure(case, lambda: picker_page(1), area=area, name="picker_page_1_deferred_count",
                    samples=11, bytes_of=lambda response: len(response.content))
    assert page["last"].status_code == 200, page["last"].text
    deep_page = _measure(case, lambda: picker_page(500), area=area, name="picker_page_500",
                         samples=7, bytes_of=lambda response: len(response.content))
    assert deep_page["last"].status_code == 200, deep_page["last"].text
    picker_module._cached_usage_pool.cache_clear()


# ---------------------------------------------------------------------------
# 3) Algorithm library / versions / tasks / reports / conversion history.
# ---------------------------------------------------------------------------
def test_algorithm_task_report_conversion_reads(scale):
    from platform_core.algorithm_sql_store import AlgorithmSqlStore
    from platform_core.training_reader_views import report_display, task_display

    area = "algorithm_task_report_conversion"
    case: dict = {"area": area}
    store = AlgorithmSqlStore(scale["project_path"] / "algorithms.json")
    tasks = scale["tasks"]
    artifacts = scale["artifacts"]

    _measure(case, lambda: store.bootstrap_summary(limit=500), area=area,
             name="algorithm_bootstrap_summary", samples=11, bytes_of=_json_bytes)
    _measure(case, lambda: store.asset_algorithms(page=6, page_size=20), area=area,
             name="algorithm_asset_page_6", samples=11, bytes_of=_json_bytes)
    _measure(case, lambda: store.read_all(summary_only=True), area=area,
             name="algorithm_read_all_summary", samples=7, bytes_of=_json_bytes)
    _measure(case, lambda: store.asset_versions("algo-050", page=1, page_size=20), area=area,
             name="model_versions_page_1", samples=11, bytes_of=_json_bytes)
    _measure(case, lambda: store.asset_version("algo-050", "ver-050-09"), area=area,
             name="model_version_detail", samples=11, bytes_of=_json_bytes)
    library = _measure(case, lambda: store.library_algorithms(statistics=[], page=1, page_size=10),
                       area=area, name="algorithm_library_cards_page_1", samples=11, bytes_of=_json_bytes)
    assert library["last"]["total"] == TOTAL_ALGORITHMS

    listing = _measure(case, lambda: tasks.list(project_id=PROJECT, kinds=("TRAINING",), limit=50),
                       area=area, name="training_task_list_page_1", samples=21,
                       bytes_of=lambda page: sum(_json_bytes(_task_record_json(task)) for task in page.items))
    assert len(listing["last"].items) == 50
    deep_cursor = listing["last"].next_cursor
    for _ in range(20):
        page = tasks.list(project_id=PROJECT, kinds=("TRAINING",), limit=50, cursor=deep_cursor)
        deep_cursor = page.next_cursor
        if not deep_cursor:
            break
    _measure(case, lambda: tasks.list(project_id=PROJECT, kinds=("TRAINING",), limit=50,
                                     cursor=deep_cursor or listing["last"].next_cursor),
             area=area, name="training_task_list_cursor_deep", samples=11,
             bytes_of=lambda page: sum(_json_bytes(_task_record_json(task)) for task in page.items))

    task = tasks.get("hist-0000")
    _measure(case, lambda: task_display(task, artifacts, detail=False), area=area,
             name="task_display_summary", samples=21, bytes_of=_json_bytes)
    _measure(case, lambda: task_display(task, artifacts, detail=True), area=area,
             name="task_display_detail_payload", samples=11, bytes_of=_json_bytes)
    _measure(case, lambda: report_display(
        "hist-0000", task, artifacts, scale["project_path"] / "jobs" / "hist-0000" / "job.json"),
        area=area, name="training_report_read", samples=21, bytes_of=_json_bytes)

    projection = scale["conversion_projection"]
    jobs_dir = scale["jobs_dir"]

    def read_json(path, default=None):
        try:
            return json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return default

    cold = _single_cold(case, lambda: projection.query(
        jobs_dir, read_json=read_json, page=1, page_size=20, include_facets=True, force=True),
        area=area, name="conversion_history_cold_scan_1000", bytes_of=_json_bytes)
    assert cold["result"]["total"] == TOTAL_CONVERSIONS
    RESULTS["cases"][-1]["note"] = "1,000 job.json metadata files stat'ed + parsed on a cold page"
    _measure(case, lambda: projection.query(jobs_dir, read_json=read_json, page=40,
                                            page_size=20, include_facets=True),
             area=area, name="conversion_history_warm_page_40", samples=11, bytes_of=_json_bytes)

    began = time.perf_counter()
    with _instrumented() as probe:
        store.read_all(summary_only=False)
        store.asset_algorithms(page=1, page_size=50)
        projection.query(jobs_dir, read_json=read_json, page=1, page_size=20, include_facets=True)
    facts = probe.snapshot(1)
    _record({"area": area, "case": "model_binary_and_network_open_check",
             "elapsed_ms": round((time.perf_counter() - began) * 1000, 3), **facts})
    assert facts["model_binary_opens"] == 0, facts
    assert facts["network_calls"] == 0, facts
    RESULTS["matches"].append({"check": "model binary opens during reads", "expected": 0,
                               "actual": facts["model_binary_opens"]})
    RESULTS["matches"].append({"check": "network calls during reads", "expected": 0,
                               "actual": facts["network_calls"]})

    candidates = scale["candidates"]
    _measure(case, lambda: candidates.read_page(cursor=None, limit=50), area=area,
             name="ai_candidates_page_1", samples=11, bytes_of=_json_bytes)
    _measure(case, candidates.summary, area=area, name="ai_candidates_summary",
             samples=11, bytes_of=_json_bytes)
    _measure(case, candidates.statistics, area=area, name="ai_candidates_statistics",
             samples=11, bytes_of=_json_bytes)
    _measure(case, candidates.label_summary, area=area, name="ai_candidates_label_summary",
             samples=11, bytes_of=_json_bytes)
    all_items = _measure(case, candidates.all_items, area=area, name="ai_candidates_all_items_20k",
                         warmup=0, samples=3, bytes_of=lambda items: _json_bytes(items))
    assert len(all_items["last"]) == TOTAL_CANDIDATES


def _task_record_json(task) -> dict:
    return {"task_id": task.task_id, "kind": task.kind.value, "status": task.status.value,
            "payload_ref": task.payload_ref, "progress": task.progress, "stage": task.stage}


# ---------------------------------------------------------------------------
# 4) SQLite concurrency: mixed readers/writers, lock waits, transaction bounds.
# ---------------------------------------------------------------------------
def test_sqlite_concurrency_mixed_workload(scale):
    from platform_core.algorithm_sql_store import AlgorithmSqlStore
    from platform_core.annotation_repository import AnnotationRepository
    from platform_core.material_repository import MaterialRepository
    from platform_core.task_runtime import TaskKind
    from platform_core.task_runtime.models import TaskStatus
    from platform_core.training_selection_reference import read_selection, selection_context

    area = "sqlite_concurrency"
    data_dir = scale["data_dir"]
    repository = MaterialRepository(scale["project_path"])
    annotations = AnnotationRepository(scale["project_path"])
    algorithm_store = AlgorithmSqlStore(scale["project_path"] / "algorithms.json")
    tasks = scale["tasks"]
    selection_ref = FROZEN.get("include_history")
    assert selection_ref, "the 20k frozen selection must exist before the concurrency run"
    context_full = selection_context(data_dir, PROJECT, {
        "algorithm_asset_id": ALGO_ACTIVE, "role": "train", "history_policy": "include_history",
        "storage_source_ids": [FOCUS_SOURCE]}, "train")

    errors: list[str] = []
    operations: dict[str, list[float]] = {}
    ops_lock = threading.Lock()

    def guarded(name: str, function, iterations: int):
        try:
            for _ in range(iterations):
                began = time.perf_counter()
                function()
                with ops_lock:
                    operations.setdefault(name, []).append((time.perf_counter() - began) * 1000)
        except Exception as error:  # real failures are surfaced, not swallowed
            with ops_lock:
                errors.append(f"{name}:{type(error).__name__}:{error}")

    review_counter = {"value": 0}
    review_lock = threading.Lock()

    def batch_review_writer():
        with review_lock:
            offset = review_counter["value"]
            review_counter["value"] += 50
        rows = [{"image_id": f"img-{30_000 + offset + index:06d}", "annotation_state": "annotated",
                 "annotation_scope": ["fire"],
                 "boxes": [{"label": "fire", "x1": 11, "y1": 12, "x2": 111, "y2": 112}]}
                for index in range(50)]
        annotations.upsert_many(rows)

    def claim_worker(worker_id: str):
        lease = tasks.claim_next(worker_id, (TaskKind.TRAINING,), (), lease_seconds=60)
        if lease is None:
            raise AssertionError("claim_next returned no lease")
        tasks.heartbeat(lease.task.task_id, lease.lease_token, progress=10.0)
        tasks.heartbeat(lease.task.task_id, lease.lease_token, progress=20.0)
        tasks.finish(lease.task.task_id, lease.lease_token, TaskStatus.SUCCEEDED)

    def material_reader():
        repository.list_page(page=1, limit=50)
        repository.count_filtered({"storage_source_ids": ["src-a"], "processing_status": "processed"})

    def selection_reader():
        ids = read_selection(data_dir, selection_ref, context_full)
        if len(ids) != FOCUS_IDS:
            raise AssertionError(f"frozen selection count changed: {len(ids)}")

    version_counter = {"value": 0}
    version_lock = threading.Lock()

    def model_archive_writer():
        with version_lock:
            version_counter["value"] += 1
            number = version_counter["value"]
        algorithm_store.attach_version("algo-109", {
            "id": f"ver-109-9{number:03d}", "version_name": f"archive-{number}",
            "version_no": 100 + number, "framework": "ultralytics",
            "training_status": "succeeded", "trainable": True, "created_at": _timestamp(number)})

    def algorithm_reader():
        algorithm_store.asset_algorithms(page=1, page_size=20)
        algorithm_store.bootstrap_summary(limit=200)

    plan = [
        ("claim_0", lambda: claim_worker("worker-0"), 10),
        ("claim_1", lambda: claim_worker("worker-1"), 10),
        ("claim_2", lambda: claim_worker("worker-2"), 10),
        ("material_read", material_reader, 25),
        ("material_read_2", lambda: repository.list_page(page=400, limit=50), 25),
        ("batch_review_write", batch_review_writer, 8),
        ("selection_read_20k", selection_reader, 5),
        ("model_archive_write", model_archive_writer, 20),
        ("algorithm_read", algorithm_reader, 12),
    ]
    with _instrumented() as probe:
        began = time.perf_counter()
        threads = [threading.Thread(target=guarded, args=(name, function, iterations),
                                    name=name) for name, function, iterations in plan]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        window_ms = (time.perf_counter() - began) * 1000
    facts = probe.snapshot(1)
    record = {
        "area": area, "case": "mixed_read_write_workload", "window_ms": round(window_ms, 2),
        "threads": len(plan),
        "operation_p50_p95_ms": {name: {"count": len(values),
                                       "p50_ms": round(statistics.median(values), 3),
                                       "p95_ms": round(_pct(values, 0.95), 3),
                                       "max_ms": round(max(values), 3)}
                                 for name, values in sorted(operations.items())},
        "errors": errors,
        "sqlite_busy_errors": sum(1 for value in errors if "database is locked" in value),
        **facts,
    }
    _record(record)
    RESULTS["matches"].append({"check": "concurrency errors", "expected": 0, "actual": len(errors)})
    RESULTS["matches"].append({"check": "sqlite busy errors", "expected": 0,
                               "actual": record["sqlite_busy_errors"]})
    assert not errors, errors
    assert record["sqlite_busy_errors"] == 0
    assert facts["max_transaction_ms"] < 30_000, facts

