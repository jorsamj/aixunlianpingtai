"""The shared training ``job.json`` has one lock identity and merge-under-lock writers.

``train_worker`` (through ``platform_core.training_timing``) and
``remote_train_server`` wrote the record with a second/absent lock while ``app.py``,
``deployment_worker`` and the numeric-evidence publisher use ``<job.json>.lock``.
Progress, cancellation and report facts then raced: a progress update could write
back a snapshot that predates a persisted cancellation (or the reverse), and the
remote server's plain ``write_text`` exposed a torn document.
"""
import importlib
import json

import pytest

import train_worker
from platform_core import training_timing


def _seed(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_worker_write_uses_the_one_shared_job_record_lock(tmp_path, monkeypatch):
    job_file = tmp_path / "jobs" / "train-1" / "job.json"
    _seed(job_file, {"id": "train-1", "status": "running"})
    acquired = []
    real_lock = training_timing.FileLock

    class _RecordingLock:
        def __init__(self, path, *args, **kwargs):
            acquired.append(str(path))
            self._lock = real_lock(path, *args, **kwargs)

        def __enter__(self):
            return self._lock.__enter__()

        def __exit__(self, *exc_info):
            return self._lock.__exit__(*exc_info)

    monkeypatch.setattr(training_timing, "FileLock", _RecordingLock)
    train_worker.update_job(job_file, progress_percent=42)

    # The app/deployment/numeric identity, not a private training-only lock.
    assert acquired == [str(job_file) + ".lock"]
    assert _read(job_file)["progress_percent"] == 42
    assert not list(job_file.parent.glob(".job.json.*.tmp"))


def test_progress_update_never_clears_a_persisted_cancellation(tmp_path):
    job_file = tmp_path / "jobs" / "train-2" / "job.json"
    _seed(job_file, {
        "id": "train-2", "task_id": "train-2", "status": "stopped",
        "message": "用户手动停止", "cancel_requested": True,
        "finished_at": "2026-11-24T09:00:00+00:00",
    })

    # A late startup stage explicitly asks for status=running; the progress fact
    # must still land, but the durable cancellation must not be cleared.
    train_worker.update_job(
        job_file, status="running", message="训练中 · Epoch 3/10",
        progress_percent=42, current_epoch=3,
    )

    job = _read(job_file)
    assert job["status"] == "stopped"
    assert job["message"] == "用户手动停止"
    assert job["cancel_requested"] is True
    assert job["finished_at"] == "2026-11-24T09:00:00+00:00"
    assert job["progress_percent"] == 42
    assert job["current_epoch"] == 3


def test_older_attempt_does_not_overwrite_a_newer_attempt(tmp_path, capsys):
    job_file = tmp_path / "jobs" / "train-3" / "job.json"
    _seed(job_file, {
        "id": "train-3", "status": "running", "progress_percent": 70,
        "training_attempt_generation": 3,
    })

    train_worker.EXECUTION_ATTEMPT = 2
    try:
        train_worker.update_job(
            job_file, status="failed", error="stale worker", progress_percent=10
        )
    finally:
        train_worker.EXECUTION_ATTEMPT = None

    job = _read(job_file)
    assert job["status"] == "running"
    assert job["progress_percent"] == 70
    assert "error" not in job
    diagnostic = capsys.readouterr().err
    assert "attempt 2" in diagnostic and "generation 3" in diagnostic

    train_worker.EXECUTION_ATTEMPT = 3
    try:
        train_worker.update_job(job_file, progress_percent=80)
    finally:
        train_worker.EXECUTION_ATTEMPT = None
    assert _read(job_file)["progress_percent"] == 80

    # A legacy/remote launch carries no execution identity and is not fenced.
    train_worker.update_job(job_file, progress_percent=85)
    assert _read(job_file)["progress_percent"] == 85


def test_atomic_replace_retries_a_transient_denial_and_raises_a_real_failure(tmp_path, monkeypatch):
    job_file = tmp_path / "jobs" / "train-4" / "job.json"
    _seed(job_file, {"id": "train-4", "progress_percent": 1})
    real_replace = train_worker.os.replace
    calls = {"count": 0}

    def flaky_replace(source, target):
        calls["count"] += 1
        if calls["count"] <= 2:
            raise PermissionError(13, "另一个进程正在使用该文件", str(target), 32)
        return real_replace(source, target)

    monkeypatch.setattr(train_worker.os, "replace", flaky_replace)
    train_worker.update_job(job_file, progress_percent=5)
    assert calls["count"] == 3
    assert _read(job_file)["progress_percent"] == 5
    assert not list(job_file.parent.glob(".job.json.*.tmp"))

    def denied_replace(source, target):
        raise PermissionError(13, "另一个进程正在使用该文件", str(target), 32)

    monkeypatch.setattr(train_worker, "JOB_RECORD_REPLACE_DEADLINE_SECONDS", 0.05)
    monkeypatch.setattr(train_worker.os, "replace", denied_replace)
    with pytest.raises(PermissionError):
        train_worker.update_job(job_file, progress_percent=6)
    # The genuine failure is surfaced, and the previous accepted record is intact.
    assert _read(job_file)["progress_percent"] == 5
    assert not list(job_file.parent.glob(".job.json.*.tmp"))


def _remote_module(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_REMOTE_DATA_DIR", str(tmp_path / "remote-data"))
    module = importlib.import_module("remote_train_server")
    return importlib.reload(module)


def test_remote_record_writes_merge_under_the_shared_lock_and_never_resurrect_a_stop(tmp_path, monkeypatch):
    remote = _remote_module(tmp_path, monkeypatch)
    job_dir = remote.JOBS_DIR / "job-1"
    job_file = job_dir / "job.json"
    acquired = []
    real_lock = remote._job_record_lock

    def recording_lock(path):
        acquired.append(str(path) + ".lock")
        return real_lock(path)

    monkeypatch.setattr(remote, "_job_record_lock", recording_lock)

    remote._update_job_record(job_file, lambda record: record.update({
        "id": "job-1", "status": "queued", "epochs": 50, "progress_percent": 0,
    }))
    # The user stops the job before the launch transition reaches the record.
    remote._update_job_record(job_file, lambda record: record.update({
        "status": "stopped", "message": "用户停止", "finished_at": remote.now_iso(),
    }))
    remote._update_job_record(job_file, remote._transition_to_running)

    job = _read(job_file)
    assert job["status"] == "stopped"
    assert job["message"] == "用户停止"
    assert job["epochs"] == 50  # fields owned by an earlier writer are preserved

    inner = job_dir / "jobs" / "job-1" / "job.json"
    # A worker progress write arriving after the stop must not revive the job.
    remote._update_job_record(inner, lambda record: record.update({
        "id": "job-1", "status": "running", "progress_percent": 30,
    }))
    assert remote.sync_job("job-1")["status"] == "stopped"
    assert remote.sync_job("job-1")["message"] == "用户停止"

    # A genuine completion fact is still projected, and no field is dropped.
    remote._update_job_record(inner, lambda record: record.update({
        "id": "job-1", "status": "done", "models": ["best.pt"],
        "training_report": {"metrics": {"mAP50": 0.5}},
    }))
    merged = remote.sync_job("job-1")

    assert merged["status"] == "done"
    assert merged["models"] == ["best.pt"]
    assert merged["training_report"] == {"metrics": {"mAP50": 0.5}}
    assert merged["epochs"] == 50
    assert set(acquired) == {str(job_file) + ".lock", str(inner) + ".lock"}
    assert not list(job_dir.glob(".job.json.*.tmp"))

    # A control write must never recreate (or invent) a record that is gone.
    missing = tmp_path / "remote-data" / "jobs" / "gone" / "job.json"
    assert remote._update_job_record(
        missing, lambda record: record.update({"status": "stopped"}), create=False
    ) == {}
    assert not missing.parent.exists()
