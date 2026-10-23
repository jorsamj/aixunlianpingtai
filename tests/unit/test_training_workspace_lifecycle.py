import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus
from platform_core.training_workspace_lifecycle import TrainingWorkspaceLifecycle, mark_training_workspace


def workspace(tmp_path, status=TaskStatus.FAILED):
    data = tmp_path / "data"
    project = data / "projects" / "p"
    project.mkdir(parents=True)
    artifacts = ArtifactStore(data / "task_runtime" / "artifacts")
    repository = TaskRepository(data / "task_runtime" / "tasks.sqlite3")
    task = replace(TaskRecord.new("t", "p", TaskKind.TRAINING, "payload.json", "training:cpu"),
                   status=status, attempt=1, finished_at="2026-10-23T00:00:00+00:00")
    repository.create(task)
    snapshot = {"snapshot_id": "a" * 64, "dataset_revision_id": "b" * 64}
    artifacts.atomic_write_json("t", "snapshot.json", snapshot)
    artifacts.atomic_write_json("t", "payload.json", {"target": "local", "input_freeze_id": "f"})
    mark_training_workspace(artifacts, task, snapshot, "f")
    image = artifacts.artifact_path("t", "work/bundle/dataset/images/train/x.jpg")
    image.parent.mkdir(parents=True)
    image.write_bytes(b"task-owned-copy")
    original = project / "original.jpg"
    original.write_bytes(b"original")
    artifacts.atomic_write_json("t", "work/bundle/manifest.json", {**snapshot, "splits": {}})
    artifacts.atomic_write_json("t", "failure.json", {"task_id": "t", "project_id": "p", "recoverable": False})
    return TrainingWorkspaceLifecycle(data, repository, artifacts), repository, artifacts, original


def test_failed_cleanup_is_scoped_idempotent_and_preserves_formal_evidence(tmp_path):
    service, repo, artifacts, original = workspace(tmp_path)
    artifacts.atomic_write_json("t", "checkpoints/worker.json", {"stage": "snapshot_ready"})
    artifacts.atomic_write_json("t", "outputs/model.json", {"retain": True})
    assert service.inspect("p", "t")["eligible"] is True
    first = service.cleanup("p", "t", actor="test-user")
    assert first["status"] == "deleted"
    assert first["deleted_logical_bytes"] > 0
    assert not artifacts.artifact_path("t", "work/bundle").exists()
    assert original.read_bytes() == b"original"
    for ref in ("snapshot.json", "failure.json", "checkpoints/worker.json", "outputs/model.json"):
        assert artifacts.artifact_path("t", ref).is_file()
    assert artifacts.artifact_path("t", "evidence/bundle/manifest.json").is_file()
    assert service.cleanup("p", "t", actor="test-user")["status"] == "already_clean"
    assert repo.get("t").status is TaskStatus.FAILED


@pytest.mark.parametrize("condition,reason", [
    ("running", "TASK_ACTIVE"), ("recovery", "RECOVERY_DEPENDENCY"),
    ("checkpoint", "RECOVERY_DEPENDENCY"), ("legacy", "OWNERSHIP_UNVERIFIED"),
    ("consumer", "ACTIVE_CONSUMER"), ("identity", "OWNERSHIP_UNVERIFIED"),
    ("model_missing", "MODEL_EVIDENCE_UNVERIFIED"),
])
def test_cleanup_refuses_unsafe_dependencies(tmp_path, condition, reason):
    service, repo, artifacts, original = workspace(tmp_path,
        TaskStatus.RUNNING if condition == "running" else
        TaskStatus.SUCCEEDED if condition == "model_missing" else TaskStatus.FAILED)
    if condition == "recovery":
        artifacts.atomic_write_json("t", "failure.json", {"task_id": "t", "project_id": "p", "recoverable": True})
    elif condition == "checkpoint":
        checkpoint = service.data_dir / "projects/p/runs/train_t/weights/last.pt"
        checkpoint.parent.mkdir(parents=True)
        checkpoint.write_bytes(b"checkpoint")
    elif condition == "legacy":
        artifacts.artifact_path("t", "workspace-lifecycle.json").unlink()
    elif condition == "identity":
        artifacts.atomic_write_json("t", "snapshot.json", {"snapshot_id": "changed"})
    elif condition == "consumer":
        repo.create(replace(TaskRecord.new("eval", "p", TaskKind.DEPLOYMENT_TEST,
            "payload.json", "eval:cpu"), status=TaskStatus.RUNNING))
    before = artifacts.artifact_path("t", "work/bundle/dataset/images/train/x.jpg").read_bytes()
    assert reason in service.inspect("p", "t")["blockers"]
    with pytest.raises(RuntimeError, match=reason):
        service.cleanup("p", "t", actor="test-user")
    assert artifacts.artifact_path("t", "work/bundle/dataset/images/train/x.jpg").read_bytes() == before
    assert original.read_bytes() == b"original"


def test_wrong_project_is_rejected_before_any_cleanup(tmp_path):
    service, _, artifacts, _ = workspace(tmp_path)
    with pytest.raises(KeyError):
        service.cleanup("other", "t", actor="test-user")
    assert artifacts.artifact_path("t", "work/bundle").is_dir()


def test_workspace_history_is_readonly_bounded_and_project_scoped(tmp_path):
    service, repo, artifacts, original = workspace(tmp_path)
    repo.create(TaskRecord.new("foreign", "other", TaskKind.TRAINING, "payload.json", "training:gpu"))
    before = {str(path): path.read_bytes() for path in artifacts.root.rglob("*") if path.is_file()}
    result = service.history_page("p", limit=1)
    assert len(result["items"]) == 1
    assert result["items"][0]["task_id"] == "t"
    assert result["items"][0]["temporary_logical_bytes"] > 0
    assert result["dry_run"] is True
    assert service.history_page("p", after="t")["items"] == []
    assert before == {str(path): path.read_bytes() for path in artifacts.root.rglob("*") if path.is_file()}
    assert original.read_bytes() == b"original"


def test_delete_interruption_can_retry_without_retouching_originals(tmp_path, monkeypatch):
    service, _, artifacts, original = workspace(tmp_path)
    delete = service._delete_detached
    monkeypatch.setattr(service, "_delete_detached", lambda _path: (_ for _ in ()).throw(OSError("busy")))
    with pytest.raises(OSError, match="busy"):
        service.cleanup("p", "t", actor="test-user")
    assert artifacts.artifact_path("t", "work/.bundle-reclaim").is_dir()
    assert artifacts.read_json("t", "workspace-cleanup.json")["status"] == "retryable"
    monkeypatch.setattr(service, "_delete_detached", delete)
    assert service.cleanup("p", "t", actor="test-user")["status"] == "deleted"
    assert original.read_bytes() == b"original"


def test_link_inside_bundle_never_follows_original(tmp_path):
    service, _, artifacts, original = workspace(tmp_path)
    link = artifacts.artifact_path("t", "work/bundle/original-link")
    try:
        link.symlink_to(original)
    except OSError:
        pytest.skip("host cannot create symlinks")
    assert "UNSAFE_PATH" in service.inspect("p", "t")["blockers"]
    with pytest.raises(RuntimeError, match="UNSAFE_PATH"):
        service.cleanup("p", "t", actor="test-user")
    assert original.read_bytes() == b"original"


def test_success_cleanup_requires_verified_archived_model_and_retains_error_image(tmp_path):
    service, repo, artifacts, original = workspace(tmp_path, TaskStatus.SUCCEEDED)
    image = artifacts.artifact_path("t", "work/bundle/dataset/images/train/x.jpg")
    member = {"image_id": "x", "image_ref": "dataset/images/train/x.jpg",
              "content_sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
    snapshot = artifacts.read_json("t", "snapshot.json")
    artifacts.atomic_write_json("t", "work/bundle/manifest.json", {**snapshot, "splits": {"test": [member]}})
    model = artifacts.artifact_path("t", "outputs/best.pt")
    model.parent.mkdir()
    model.write_bytes(b"verified-model")
    artifacts.atomic_write_json("t", "result.json", {**snapshot,
        "verified_models": [{"ref": "outputs/best.pt", "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
                             "size_bytes": model.stat().st_size}],
        "training_report": {"test_result": {"error_samples": [{"image_id": "x", "image": "x.jpg"}]}}})
    artifacts.atomic_write_json("t", "checkpoints/worker.json", {"stage": "committed", "result_ref": "result.json"})
    (service.data_dir / "projects/p/algorithms.json").write_text(
        json.dumps([{"id": "a", "name": "a", "versions": [{"id": "v", "task_id": "t", "training_status": "SUCCEEDED", "artifact_verified": True,
            "snapshot_id": snapshot["snapshot_id"], "verified_models": artifacts.read_json("t", "result.json")["verified_models"]}]}]), encoding="utf-8")
    # The formal training commit, not lifecycle inspection, initializes the owner.
    from platform_core.algorithms import list_algorithms
    list_algorithms(service.data_dir / "projects/p/algorithms.json")
    assert service.inspect("p", "t")["eligible"] is True
    assert service.cleanup("p", "t", actor="test-user")["status"] == "deleted"
    assert artifacts.artifact_path("t", "evidence/bundle/dataset/images/train/x.jpg").read_bytes() == b"task-owned-copy"
    assert model.read_bytes() == b"verified-model"
    assert original.read_bytes() == b"original"


def test_live_process_blocks_even_terminal_record(tmp_path):
    import os
    service, repo, artifacts, _ = workspace(tmp_path)
    with repo._connect() as database:
        database.execute("UPDATE tasks SET process_pid=? WHERE task_id='t'", (os.getpid(),))
    assert "PROCESS_PRESENT" in service.inspect("p", "t")["blockers"]
    with pytest.raises(RuntimeError, match="PROCESS_PRESENT"):
        service.cleanup("p", "t", actor="test-user")
    assert artifacts.artifact_path("t", "work/bundle").is_dir()


def test_qualification_never_migrates_legacy_algorithm_catalog(tmp_path):
    service, _, artifacts, _ = workspace(tmp_path, TaskStatus.SUCCEEDED)
    project = service.data_dir / "projects/p"
    catalog = project / "algorithms.json"
    catalog.write_text('[{"id":"legacy","versions":[]}]', encoding="utf-8")
    # Even a plausible result cannot initialize SQL or promote old versions.
    snapshot = artifacts.read_json("t", "snapshot.json")
    model = artifacts.artifact_path("t", "outputs/best.pt")
    model.parent.mkdir()
    model.write_bytes(b"model")
    artifacts.atomic_write_json("t", "result.json", {**snapshot, "verified_models": [{
        "ref": "outputs/best.pt", "sha256": hashlib.sha256(b"model").hexdigest(), "size_bytes": 5}]})
    artifacts.atomic_write_json("t", "checkpoints/worker.json", {"stage": "committed", "result_ref": "result.json"})
    before = catalog.read_bytes()
    assert "MODEL_EVIDENCE_UNVERIFIED" in service.inspect("p", "t")["blockers"]
    assert catalog.read_bytes() == before
    assert not (project / "algorithms.sqlite3").exists()
    assert not (project / "algorithms.json.pre-sql-migration-backup").exists()


def test_report_stream_holds_workspace_lock_and_can_open_retained_bytes_after_cleanup(tmp_path):
    import asyncio
    from filelock import FileLock, Timeout
    from platform_core.training_workspace_http import TrainingEvidenceFileResponse
    service, _, artifacts, _ = workspace(tmp_path)
    bundle = artifacts.artifact_path("t", "work/bundle")
    image = bundle / "dataset/images/train/x.jpg"
    snapshot = artifacts.read_json("t", "snapshot.json")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    artifacts.atomic_write_json("t", "work/bundle/manifest.json", {**snapshot, "splits": {"test": [{
        "image_id": "x", "image_ref": "dataset/images/train/x.jpg", "content_sha256": digest}]}})
    artifacts.atomic_write_json("t", "result.json", {"training_report": {"test_result": {
        "error_samples": [{"image_id": "x", "image": "x.jpg"}]}}})
    task_root = artifacts.root / "t"
    scope = {"type": "http", "method": "GET", "headers": [], "asgi": {"spec_version": "2.4"}}
    sent = []
    async def receive():
        return {"type": "http.request"}
    async def send(message):
        if message["type"] == "http.response.body":
            with pytest.raises(Timeout):
                with FileLock(str(task_root / "workspace-access.lock"), timeout=0):
                    pass
            sent.append(message.get("body", b""))
    def response():
        return TrainingEvidenceFileResponse(image, workspace_root=task_root, expected_sha256=digest)
    asyncio.run(response()(scope, receive, send))
    assert b"".join(sent) == b"task-owned-copy"
    # A response already created before GC can still deliver the same archived bytes.
    delayed = response()
    assert service.cleanup("p", "t", actor="test-user")["status"] == "deleted"
    sent.clear()
    asyncio.run(delayed(scope, receive, send))
    assert b"".join(sent) == b"task-owned-copy"
    with FileLock(str(task_root / "workspace-access.lock"), timeout=0):
        pass


def test_workspace_api_requires_actor_explicit_confirmation_and_current_preview(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.training_recovery_api import training_recovery_router
    service, repo, artifacts, original = workspace(tmp_path)
    app = FastAPI()
    actor = {"actor_id": "logged-in-user"}
    app.include_router(training_recovery_router(
        lambda project_id: {"id": project_id}, lambda: repo, lambda: artifacts,
        project_path_provider=lambda project_id: service.data_dir / "projects" / project_id,
        workspace_actor_provider=lambda _request, _project: actor,
    ))
    with TestClient(app) as client:
        url = "/api/v62/projects/p/training-tasks/t/workspace"
        preview = client.get(url)
        assert preview.status_code == 200
        truth = preview.json()["workspace"]
        assert truth["eligible"] is True
        assert client.post(url + "/cleanup", json={}).status_code == 422
        payload = {"confirm": "release_training_workspace", "attempt": truth["attempt"],
                   "snapshot_id": truth["snapshot_id"]}
        assert client.post(url + "/cleanup", json={**payload, "attempt": 2}).status_code == 409
        actor.clear()
        assert client.post(url + "/cleanup", json=payload).status_code == 401
        actor["actor_id"] = "logged-in-user"
        assert client.post(url.replace("/projects/p/", "/projects/other/") + "/cleanup", json=payload).status_code == 404
        result = client.post(url + "/cleanup", json=payload)
        assert result.status_code == 200, result.text
        assert result.json()["workspace"]["status"] == "deleted"
        assert client.post(url + "/cleanup", json=payload).json()["workspace"]["status"] == "already_clean"
    assert original.read_bytes() == b"original"
    assert repo.get("t").status is TaskStatus.FAILED
    assert artifacts.read_json("t", "workspace-cleanup.json")["actor"] == "logged-in-user"


def test_independent_active_training_does_not_pin_task_bundle(tmp_path):
    service, repo, artifacts, original = workspace(tmp_path)
    repo.create(replace(TaskRecord.new("other", "p", TaskKind.TRAINING,
        "payload.json", "training:other"), status=TaskStatus.RUNNING))
    artifacts.atomic_write_json("other", "payload.json", {
        "target": "local", "input_freeze_id": "other-freeze", "input_freeze_ref": "input-freeze.json"})
    assert service.inspect("p", "t")["eligible"]
    assert service.cleanup("p", "t", actor="maintenance")["status"] == "deleted"
    assert original.exists()


def test_queued_explicit_bundle_consumer_blocks_cleanup(tmp_path):
    service, repo, artifacts, _ = workspace(tmp_path)
    repo.create(TaskRecord.new("other", "p", TaskKind.TRAINING_PREPARE, "payload.json", "prepare"))
    artifacts.atomic_write_json("other", "payload.json", {"training_task_id": "t"})
    assert "ACTIVE_CONSUMER" in service.inspect("p", "t")["blockers"]


def test_maintenance_rotates_bounded_batches_and_restarts_from_task_truth(tmp_path):
    service, repo, artifacts, original = workspace(tmp_path)
    # A protected old entry must not starve later eligible entries.
    repo.create(replace(TaskRecord.new("a", "p", TaskKind.TRAINING, "payload.json", "training:a"),
                       status=TaskStatus.FAILED, finished_at="2026-10-22T00:00:00+00:00"))
    first = service.maintain(limit=1)
    second = service.maintain(limit=1)
    assert first["examined"] == second["examined"] == 1
    assert not artifacts.artifact_path("t", "work/bundle").exists()
    assert original.exists()
    restarted = TrainingWorkspaceLifecycle(service.data_dir, repo, artifacts)
    assert restarted.maintain(limit=10)["deleted"] == 0


def test_evidence_archival_does_not_hold_task_database_write_lock(tmp_path, monkeypatch):
    service, repo, artifacts, _ = workspace(tmp_path)
    archive = service._archive_evidence
    def checked(task, bundle):
        with repo._connect() as connection:
            connection.execute("PRAGMA busy_timeout=1")
            connection.execute("BEGIN IMMEDIATE")
            connection.rollback()
        archive(task, bundle)
    monkeypatch.setattr(service, "_archive_evidence", checked)
    assert service.cleanup("p", "t", actor="maintenance")["status"] == "deleted"


def test_scheduler_maintenance_starts_on_restart_and_never_blocks_claim(tmp_path):
    import threading
    from platform_core.task_runtime import Scheduler
    service, repo, artifacts, _ = workspace(tmp_path)
    started, claimed, completed, stop = (threading.Event() for _ in range(4))
    def maintenance():
        started.set()
        assert claimed.wait(2), "maintenance blocked original claim loop"
        completed.set()
    scheduler = Scheduler(repo, artifacts, "worker", {}, set(), maintenance=maintenance)
    def run_once():
        assert started.wait(2)
        claimed.set()
        stop.set()
        return False
    scheduler.run_once = run_once
    scheduler.serve_forever(stop)
    assert completed.wait(2)


def test_unknown_terminal_process_identity_is_not_reclaimed(tmp_path):
    service, repo, artifacts, _ = workspace(tmp_path)
    with repo._connect() as connection:
        connection.execute("UPDATE tasks SET process_pid=2147483000 WHERE task_id='t'")
    assert "PROCESS_IDENTITY_UNVERIFIED" in service.inspect("p", "t")["blockers"]
    assert service.maintain()["deleted"] == 0
    assert artifacts.artifact_path("t", "work/bundle").exists()


def test_changed_recovery_evidence_during_archival_prevents_detach(tmp_path, monkeypatch):
    service, repo, artifacts, _ = workspace(tmp_path)
    archive = service._archive_evidence
    def changed(task, bundle):
        archive(task, bundle)
        artifacts.atomic_write_json("t", "failure.json", {"recoverable": True})
    monkeypatch.setattr(service, "_archive_evidence", changed)
    with pytest.raises(RuntimeError, match="WORKSPACE_PREVIEW_STALE"):
        service.cleanup("p", "t", actor="maintenance")
    assert artifacts.artifact_path("t", "work/bundle").exists()
