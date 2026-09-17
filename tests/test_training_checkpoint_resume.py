from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from platform_core import training_checkpoint_resume_tasks as resume


class FakeArtifacts:
    def __init__(self, root: Path):
        self.root = root

    def artifact_path(self, task_id: str, ref: str) -> Path:
        return self.root / task_id / ref

    def read_json(self, task_id: str, ref: str, default=None):
        path = self.artifact_path(task_id, ref)
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return default

    def atomic_write_json(self, task_id: str, ref: str, value):
        path = self.artifact_path(task_id, ref)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def build_context(tmp_path: Path, *, snapshot_id="snap-1", attempt=2):
    data_dir = tmp_path / "data"
    project = data_dir / "projects" / "project-1"
    task_id = "train-task-1"
    artifacts = FakeArtifacts(data_dir / "task_runtime" / "artifacts")
    task = SimpleNamespace(
        task_id=task_id,
        project_id="project-1",
        payload_ref="payload.json",
        retry_of=None,
        attempt=attempt,
    )
    lease = SimpleNamespace(lease_token="lease-2", worker_id="worker-2")
    context = SimpleNamespace(task=task, lease=lease, artifacts=artifacts)

    write_json(
        project / "jobs" / task_id / "job.json",
        {
            "id": task_id,
            "task_id": task_id,
            "status": "running",
            "snapshot_id": snapshot_id,
            "epochs": 100,
            "current_epoch": 36,
            "progress_percent": 44,
            "imgsz": 640,
            "requested_device": "auto",
        },
    )
    write_json(
        artifacts.artifact_path(task_id, "payload.json"),
        {"epochs": 100, "imgsz": 640, "requested_device": "auto", "val_max_samples": 0},
    )
    write_json(artifacts.artifact_path(task_id, "snapshot.json"), {"snapshot_id": snapshot_id})
    write_json(
        artifacts.artifact_path(task_id, "assignment.json"),
        {
            "lease_token": "lease-2",
            "worker_id": "worker-2",
            "assigned_device": "cuda:0",
            "gpu_uuid": "GPU-test",
            "reserved_bytes": 123,
        },
    )
    write_json(
        artifacts.artifact_path(task_id, "resource-context.json"),
        {"dataset_bytes": 456, "train_image_count": 10},
    )
    runtime_yaml = artifacts.artifact_path(task_id, "work/runtime-data.yaml")
    runtime_yaml.parent.mkdir(parents=True, exist_ok=True)
    runtime_yaml.write_text("path: .\ntrain: images/train\nval: images/validation\n", encoding="utf-8")
    manifest = artifacts.artifact_path(task_id, "work/bundle/manifest.json")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    manifest.write_text("{}", encoding="utf-8")

    run_dir = project / "runs" / f"train_{task_id}"
    checkpoint = run_dir / "weights" / "last.pt"
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_bytes(b"trusted-checkpoint")
    (run_dir / "results.csv").write_text("epoch,metric\n1,0.1\n2,0.2\n", encoding="utf-8")
    return data_dir, project, context, checkpoint


def test_same_task_reclaim_admits_trusted_last_checkpoint(tmp_path, monkeypatch):
    data_dir, _project, context, checkpoint = build_context(tmp_path)
    monkeypatch.setattr(resume.base, "_training_python", lambda _data_dir: sys.executable)
    monkeypatch.setattr(
        resume.base,
        "_verify_materialized_dataset_evidence",
        lambda _manifest: {"snapshot_id": "snap-1", "verified_files": 10, "verification_mode": "materialization_evidence"},
    )

    candidate = resume.inspect_training_resume_candidate(context, data_dir)

    assert candidate["eligible"] is True
    assert candidate["resume_from_epoch"] == 36
    assert candidate["requested_epochs"] == 100
    assert Path(candidate["checkpoint_path"]) == checkpoint.resolve()
    assert candidate["argv"][1].endswith("train_checkpoint_resume_worker.py")
    assert "--resume-checkpoint" in candidate["argv"]
    assert "--snapshot-id" in candidate["argv"]
    assert context.artifacts.read_json(context.task.task_id, "resume-resource-context.json", {})["gpu_uuid"] == "GPU-test"


def test_first_attempt_never_uses_resume_path(tmp_path, monkeypatch):
    data_dir, _project, context, _checkpoint = build_context(tmp_path, attempt=1)
    monkeypatch.setattr(resume.base, "_training_python", lambda _data_dir: sys.executable)
    candidate = resume.inspect_training_resume_candidate(context, data_dir)
    assert candidate == {"eligible": False, "reason": "task_has_not_been_reclaimed"}


def test_snapshot_mismatch_fails_closed(tmp_path, monkeypatch):
    data_dir, _project, context, _checkpoint = build_context(tmp_path)
    write_json(context.artifacts.artifact_path(context.task.task_id, "snapshot.json"), {"snapshot_id": "different"})
    monkeypatch.setattr(resume.base, "_training_python", lambda _data_dir: sys.executable)
    candidate = resume.inspect_training_resume_candidate(context, data_dir)
    assert candidate["eligible"] is False
    assert candidate["reason"] == "snapshot_identity_mismatch"


def test_stale_scheduler_assignment_fails_closed(tmp_path, monkeypatch):
    data_dir, _project, context, _checkpoint = build_context(tmp_path)
    write_json(
        context.artifacts.artifact_path(context.task.task_id, "assignment.json"),
        {"lease_token": "old-lease", "worker_id": "old-worker", "assigned_device": "cuda:0"},
    )
    monkeypatch.setattr(resume.base, "_training_python", lambda _data_dir: sys.executable)
    monkeypatch.setattr(
        resume.base,
        "_verify_materialized_dataset_evidence",
        lambda _manifest: {"snapshot_id": "snap-1", "verified_files": 10, "verification_mode": "materialization_evidence"},
    )
    candidate = resume.inspect_training_resume_candidate(context, data_dir)
    assert candidate["eligible"] is False
    assert candidate["reason"] == "scheduler_assignment_stale"


def test_completed_epoch_checkpoint_is_not_resumed(tmp_path, monkeypatch):
    data_dir, project, context, _checkpoint = build_context(tmp_path)
    job_file = project / "jobs" / context.task.task_id / "job.json"
    job = json.loads(job_file.read_text(encoding="utf-8"))
    job["current_epoch"] = 100
    write_json(job_file, job)
    monkeypatch.setattr(resume.base, "_training_python", lambda _data_dir: sys.executable)
    monkeypatch.setattr(
        resume.base,
        "_verify_materialized_dataset_evidence",
        lambda _manifest: {"snapshot_id": "snap-1", "verified_files": 10, "verification_mode": "materialization_evidence"},
    )
    candidate = resume.inspect_training_resume_candidate(context, data_dir)
    assert candidate["eligible"] is False
    assert candidate["reason"] == "checkpoint_is_not_incomplete_training"


def test_worker_registry_points_at_checkpoint_resume_handler():
    from platform_core import worker_registry

    assert worker_registry.ROLE_MODULES["training"] == "platform_core.training_checkpoint_resume_tasks"
