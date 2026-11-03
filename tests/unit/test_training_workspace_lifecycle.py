import hashlib
import errno
import json
import sqlite3
import threading
from dataclasses import replace
from pathlib import Path

import pytest

from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus
from platform_core.training_workspace_lifecycle import TrainingWorkspaceLifecycle, mark_training_workspace


@pytest.mark.parametrize("source", ["sample_outcomes", "sample_evidence"])
def test_cleanup_retains_diagnostic_samples_outside_top_errors(tmp_path, source):
    service, repo, artifacts, original = workspace(tmp_path)
    image = artifacts.artifact_path("t", "work/bundle/dataset/images/train/x.jpg")
    digest = hashlib.sha256(image.read_bytes()).hexdigest()
    snapshot = artifacts.read_json("t", "snapshot.json")
    artifacts.atomic_write_json("t", "work/bundle/manifest.json", {**snapshot, "splits": {
        "test": [{"image_id": "x", "image_ref": "dataset/images/train/x.jpg", "content_sha256": digest}]}})
    artifacts.atomic_write_json("t", "result.json", {"training_report": {"test_result": {
        source: [{"image_id": "x", "image": "x.jpg", "image_content_sha256": digest, "fn_count": 1}]}}})
    service.cleanup("p", "t", actor="test")
    assert artifacts.artifact_path("t", "evidence/bundle/dataset/images/train/x.jpg").read_bytes() == b"task-owned-copy"
    assert original.read_bytes() == b"original"


def test_archive_rejects_explicit_id_even_when_filename_matches(tmp_path):
    service, repo, artifacts, _ = workspace(tmp_path)
    image = artifacts.artifact_path("t", "work/bundle/dataset/images/train/x.jpg")
    snapshot = artifacts.read_json("t", "snapshot.json")
    artifacts.atomic_write_json("t", "work/bundle/manifest.json", {**snapshot, "splits": {"test": [
        {"image_id": "x", "image_ref": "dataset/images/train/x.jpg",
         "content_sha256": hashlib.sha256(image.read_bytes()).hexdigest()}]}})
    artifacts.atomic_write_json("t", "result.json", {"training_report": {"test_result": {
        "error_samples": [{"image_id": "foreign", "image": "x.jpg"}]}}})
    with pytest.raises(RuntimeError, match="REPORT_IMAGE_IDENTITY_UNVERIFIED"):
        service.cleanup("p", "t", actor="test")
    assert image.exists()


def test_automatic_maintenance_records_recovery_blocker(tmp_path):
    service, _, artifacts, _ = workspace(tmp_path)
    artifacts.atomic_write_json("t", "failure.json", {"recoverable": True})
    service.maintain()
    receipt = artifacts.read_json("t", "workspace-cleanup.json")
    assert receipt["status"] == "blocked"
    assert "RECOVERY_DEPENDENCY" in receipt["blockers"]


def test_automatic_archival_failure_is_visible_and_retries(tmp_path, monkeypatch):
    service, _, artifacts, _ = workspace(tmp_path)
    archive = service._archive_evidence
    monkeypatch.setattr(service, '_archive_evidence', lambda *args: (_ for _ in ()).throw(
        OSError(errno.EIO, 'simulated transient disk error')))
    assert service.maintain()['deleted'] == 0
    receipt = artifacts.read_json('t', 'workspace-cleanup.json')
    assert receipt['status'] == 'retryable'
    assert receipt['blockers'] == ['ARCHIVE_IO_FAILURE']
    assert artifacts.artifact_path('t', 'work/bundle').exists()
    monkeypatch.setattr(service, '_archive_evidence', archive)
    receipt['next_retry_epoch'] = 0  # Simulate expiry of the bounded cooldown.
    artifacts.atomic_write_json('t', 'workspace-cleanup.json', receipt)
    service.maintain()  # reset bounded cursor
    assert service.maintain()['deleted'] == 1


def test_diagnostic_retry_receipt_without_bundle_is_already_clean(tmp_path):
    service, _, artifacts, _ = workspace(tmp_path)
    service._record_maintenance_wait('t', 'retryable', ['REPORT_IMAGE_HASH_MISMATCH'])
    service._delete_detached(artifacts.artifact_path('t', 'work/bundle'))
    assert service.cleanup('p', 't', actor='test')['status'] == 'already_clean'
    assert artifacts.read_json('t', 'workspace-cleanup.json')['deleted_logical_bytes'] == 0



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


def successful_workspace(tmp_path):
    service, repo, artifacts, original = workspace(tmp_path, TaskStatus.SUCCEEDED)
    snapshot = artifacts.read_json("t", "snapshot.json")
    model = artifacts.artifact_path("t", "outputs/best.pt")
    model.parent.mkdir()
    model.write_bytes(b"verified-model")
    models = [{"ref": "outputs/best.pt", "sha256": hashlib.sha256(model.read_bytes()).hexdigest(),
               "size_bytes": model.stat().st_size}]
    artifacts.atomic_write_json("t", "result.json", {**snapshot, "verified_models": models,
        "training_report": {"test_result": {"error_samples": []}}})
    artifacts.atomic_write_json("t", "checkpoints/worker.json",
                                {"stage": "committed", "result_ref": "result.json"})
    catalog = service.data_dir / "projects/p/algorithms.json"
    catalog.write_text(json.dumps([{"id": "a", "name": "a", "versions": [{
        "id": "v", "task_id": "t", "training_status": "SUCCEEDED",
        "artifact_verified": True, "snapshot_id": snapshot["snapshot_id"],
        "verified_models": models}]}]), encoding="utf-8")
    from platform_core.algorithms import list_algorithms
    list_algorithms(catalog)
    return service, repo, artifacts, original, model


def test_unrelated_project_wal_write_during_archive_does_not_reject_cleanup(tmp_path, monkeypatch):
    service, _, artifacts, _, model = successful_workspace(tmp_path)
    archive = service._archive_evidence
    def with_unrelated_write(task, bundle):
        archive(task, bundle)
        db = service.data_dir / "projects/p/algorithms.sqlite3"
        with sqlite3.connect(db) as connection:
            connection.execute("CREATE TABLE IF NOT EXISTS unrelated_probe (id INTEGER)")
            connection.execute("INSERT INTO unrelated_probe VALUES (1)")
    monkeypatch.setattr(service, "_archive_evidence", with_unrelated_write)
    assert service.cleanup("p", "t", actor="manual-test")["status"] == "deleted"
    assert model.read_bytes() == b"verified-model"
    assert artifacts.artifact_path("t", "evidence/archive-proof.json").is_file()


def test_current_training_version_changed_during_archive_remains_protected(tmp_path, monkeypatch):
    service, _, artifacts, _, _ = successful_workspace(tmp_path)
    archive = service._archive_evidence
    def revoke_version(task, bundle):
        archive(task, bundle)
        db = service.data_dir / "projects/p/algorithms.sqlite3"
        with sqlite3.connect(db) as connection:
            connection.execute("UPDATE algorithm_versions SET artifact_verified=0 WHERE training_job_id='t'")
    monkeypatch.setattr(service, "_archive_evidence", revoke_version)
    with pytest.raises(RuntimeError, match="MODEL_VERSION_CHANGED"):
        service.cleanup("p", "t", actor="manual-test")
    assert artifacts.artifact_path("t", "work/bundle").is_dir()


def test_stale_final_gate_reuses_previously_verified_archive(tmp_path, monkeypatch):
    service, _, artifacts, _ = workspace(tmp_path)
    old_failure = artifacts.read_json("t", "failure.json")
    archive = service._archive_evidence
    def stale_once(task, bundle):
        archive(task, bundle)
        artifacts.atomic_write_json("t", "failure.json", {"recoverable": True})
    monkeypatch.setattr(service, "_archive_evidence", stale_once)
    with pytest.raises(RuntimeError, match="WORKSPACE_PREVIEW_STALE"):
        service.cleanup("p", "t", actor="manual-test")
    artifacts.atomic_write_json("t", "failure.json", old_failure)
    monkeypatch.setattr(service, "_archive_evidence", archive)
    copies = []
    from platform_core import training_workspace_lifecycle as module
    original_copy = module.shutil.copyfile
    def counted_copy(*args, **kwargs):
        copies.append(args)
        return original_copy(*args, **kwargs)
    monkeypatch.setattr(module.shutil, "copyfile", counted_copy)
    assert service.cleanup("p", "t", actor="manual-test")["status"] == "deleted"
    assert copies == []


def test_interrupted_partial_archive_reuses_verified_files_on_retry(tmp_path, monkeypatch):
    service, _, artifacts, _ = workspace(tmp_path)
    yaml = artifacts.artifact_path("t", "work/bundle/dataset/data.yaml")
    yaml.parent.mkdir(parents=True, exist_ok=True)
    yaml.write_text("names: []\n", encoding="utf-8")
    from platform_core import training_workspace_lifecycle as module
    original_copy = module.shutil.copyfile
    count = 0
    def interrupted_copy(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 2:
            raise OSError(errno.EIO, "simulated interruption")
        return original_copy(*args, **kwargs)
    monkeypatch.setattr(module.shutil, "copyfile", interrupted_copy)
    with pytest.raises(OSError):
        service.cleanup("p", "t", actor="manual-test")
    assert artifacts.artifact_path("t", "work/bundle").exists()
    assert not artifacts.artifact_path("t", "evidence/archive-proof.json").exists()
    monkeypatch.setattr(module.shutil, "copyfile", original_copy)
    replay = []
    def count_retry(*args, **kwargs):
        replay.append(args)
        return original_copy(*args, **kwargs)
    monkeypatch.setattr(module.shutil, "copyfile", count_retry)
    assert service.cleanup("p", "t", actor="manual-test")["status"] == "deleted"
    assert len(replay) == count - 1  # The first proven target was reused.


def test_existing_complete_archive_detects_source_change(tmp_path, monkeypatch):
    service, _, artifacts, _ = workspace(tmp_path)
    archive = service._archive_evidence
    def mutate_after_archive(task, bundle):
        archive(task, bundle)
        (bundle / "manifest.json").write_text('{"tampered":true}', encoding="utf-8")
    monkeypatch.setattr(service, "_archive_evidence", mutate_after_archive)
    with pytest.raises(RuntimeError, match="WORKSPACE_PREVIEW_STALE"):
        service.cleanup("p", "t", actor="manual-test")
    assert artifacts.artifact_path("t", "work/bundle").exists()


def test_archive_disk_pressure_is_safe_and_diagnostic(tmp_path, monkeypatch):
    service, _, artifacts, _ = workspace(tmp_path)
    monkeypatch.setattr(service, "_require_archive_space", lambda *_: (_ for _ in ()).throw(
        RuntimeError("DISK_SPACE_INSUFFICIENT")))
    with pytest.raises(RuntimeError, match="DISK_SPACE_INSUFFICIENT"):
        service.cleanup("p", "t", actor="manual-test")
    assert artifacts.artifact_path("t", "work/bundle").exists()
    receipt = artifacts.read_json("t", "workspace-cleanup.json")
    assert receipt["blockers"] == ["DISK_SPACE_INSUFFICIENT"]
    assert receipt["stage"] == "archive" and receipt["diagnostic_id"]


def test_archive_space_invalid_config_fails_closed(tmp_path, monkeypatch):
    service, _, artifacts, _ = workspace(tmp_path)
    monkeypatch.setenv("CHANG_LIAN_ARCHIVE_MIN_FREE_BYTES", "bad-value")
    with pytest.raises(RuntimeError, match="DISK_SPACE_INSUFFICIENT"):
        service.cleanup("p", "t", actor="manual-test")
    assert artifacts.artifact_path("t", "work/bundle").is_dir()


def test_archive_space_uses_cross_platform_disk_usage(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from platform_core import training_workspace_lifecycle as module
    checked = []
    monkeypatch.setenv("CHANG_LIAN_ARCHIVE_MIN_FREE_BYTES", "100")
    monkeypatch.setattr(module.shutil, "disk_usage", lambda path:
                        (checked.append(Path(path)), SimpleNamespace(free=150))[1])
    module.TrainingWorkspaceLifecycle._require_archive_space(tmp_path, 50)
    with pytest.raises(RuntimeError, match="DISK_SPACE_INSUFFICIENT"):
        module.TrainingWorkspaceLifecycle._require_archive_space(tmp_path, 51)
    assert checked == [tmp_path, tmp_path]


def test_two_maintenance_workers_archive_once_and_report_reader_lock_stays_free(tmp_path, monkeypatch):
    service, repo, artifacts, _ = workspace(tmp_path)
    second = TrainingWorkspaceLifecycle(service.data_dir, repo, artifacts)
    entered, release = threading.Event(), threading.Event()
    original = service._archive_evidence
    def slow_archive(task, bundle):
        from filelock import FileLock
        # A report image reader is not blocked by the long archive phase.
        with FileLock(str(artifacts.root / "t/workspace-access.lock"), timeout=0):
            pass
        entered.set()
        assert release.wait(5)
        original(task, bundle)
    monkeypatch.setattr(service, "_archive_evidence", slow_archive)
    results = []
    thread = threading.Thread(target=lambda: results.append(service.maintain()))
    thread.start()
    assert entered.wait(5)
    assert second.maintain()["deleted"] == 0
    release.set()
    thread.join(5)
    assert not thread.is_alive()
    assert results[0]["deleted"] == 1
    assert not artifacts.artifact_path("t", "work/bundle").exists()


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


def test_workspace_api_reports_archive_oserror_stage_without_private_paths(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.training_recovery_api import training_recovery_router
    service, repo, artifacts, _ = workspace(tmp_path)
    def disk_error(*_):
        raise OSError(errno.ENOSPC, "private-path-must-not-leak")
    monkeypatch.setattr(TrainingWorkspaceLifecycle, "_archive_evidence", disk_error)
    app = FastAPI()
    app.include_router(training_recovery_router(
        lambda project_id: {"id": project_id}, lambda: repo, lambda: artifacts,
        project_path_provider=lambda project_id: service.data_dir / "projects" / project_id,
        workspace_actor_provider=lambda _request, _project: {"actor_id": "tester"},
    ))
    with TestClient(app) as client:
        url = "/api/v62/projects/p/training-tasks/t/workspace"
        preview = client.get(url).json()["workspace"]
        payload = {"confirm": "release_training_workspace", "attempt": preview["attempt"],
                   "snapshot_id": preview["snapshot_id"]}
        response = client.post(url + "/cleanup", json=payload)
        assert response.status_code == 503
        detail = response.json()["detail"]
        assert detail["code"] == "DISK_SPACE_INSUFFICIENT"
        assert detail["stage"] == "archive" and detail["diagnostic_id"]
        assert "private-path" not in response.text
        assert artifacts.artifact_path("t", "work/bundle").exists()


def test_workspace_api_distinguishes_retryable_stale_conflict_from_disk_503(tmp_path, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from platform_core.training_recovery_api import training_recovery_router
    service, repo, artifacts, _ = workspace(tmp_path)
    app = FastAPI()
    app.include_router(training_recovery_router(
        lambda project_id: {"id": project_id}, lambda: repo, lambda: artifacts,
        project_path_provider=lambda project_id: service.data_dir / "projects" / project_id,
        workspace_actor_provider=lambda _request, _project: {"actor_id": "tester"},
    ))
    with TestClient(app) as client:
        url = "/api/v62/projects/p/training-tasks/t/workspace"
        preview = client.get(url).json()["workspace"]
        payload = {"confirm": "release_training_workspace", "attempt": preview["attempt"],
                   "snapshot_id": preview["snapshot_id"]}
        stale = client.post(url + "/cleanup", json={**payload, "attempt": payload["attempt"] + 1})
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "WORKSPACE_PREVIEW_STALE"
        monkeypatch.setenv("CHANG_LIAN_ARCHIVE_MIN_FREE_BYTES", "not-an-integer")
        pressure = client.post(url + "/cleanup", json=payload)
        assert pressure.status_code == 503
        assert pressure.json()["detail"]["code"] == "DISK_SPACE_INSUFFICIENT"
        assert artifacts.artifact_path("t", "work/bundle").exists()


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
