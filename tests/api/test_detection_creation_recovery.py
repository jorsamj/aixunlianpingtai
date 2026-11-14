from pathlib import Path
import pytest
import app as app_module
from platform_core.algorithms import save_algorithms


def request_data(project_id):
    return {"model_scope": "scenario", "model_source": "algorithm_version", "algorithm_id": "algorithm",
            "version_id": "version", "creation_id": "stable-creation", "detection_batch_id": "batch-stable",
            "detection_item_index": "0", "detection_item_total": "1", "detection_side": "A"}


def seed(seeded_project):
    project, _ = seeded_project
    save_algorithms(app_module.algorithms_file(project), [{"id": "algorithm", "versions": [{"id": "version", "training_status": "SUCCEEDED", "trainable": True, "artifact_verified": True, "framework": "ultralytics"}]}])
    return project


def post(client, project, data=None, image=b"image"):
    return client.post(f"/api/v61/projects/{project}/deployment-tests", data=data or request_data(project),
                       files={"file": ("test.jpg", image, "image/jpeg")})


def test_accept_is_durable_idempotent_and_does_not_call_slow_preparation(client, seeded_project, monkeypatch):
    project = seed(seeded_project)
    def slow(*args, **kwargs):
        raise AssertionError("HTTP creation must not perform model/storage preparation")
    monkeypatch.setattr(app_module, "_remote_execution_transport_service", slow)
    first = post(client, project)
    assert first.status_code == 202, first.text
    second = post(client, project)
    assert second.status_code == 202, second.text
    assert first.json()["id"] == second.json()["id"]
    lookup = client.get(f"/api/v61/projects/{project}/deployment-test-creations/stable-creation")
    assert lookup.json()["creation_state"] == "CREATED"
    assert lookup.json()["task"]["id"] == first.json()["id"]
    assert post(client, project, image=b"changed").status_code == 409


def test_missing_creation_is_authoritative_and_project_scoped(client, seeded_project):
    project = seed(seeded_project)
    result = client.get(f"/api/v61/projects/{project}/deployment-test-creations/never-arrived")
    assert result.status_code == 200, result.text
    assert result.json()["creation_state"] == "NOT_CREATED"


def test_sqlite_failure_does_not_publish_half_a_pair(client, seeded_project, monkeypatch):
    project = seed(seeded_project)
    repository = app_module.shared_task_repository()
    create = getattr(repository, "create_deployment_pair", None)
    assert create is not None
    import sqlite3
    monkeypatch.setattr(repository, "create_deployment_pair", lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    with pytest.raises(sqlite3.OperationalError): post(client, project)
    lookup = client.get(f"/api/v61/projects/{project}/deployment-test-creations/stable-creation")
    assert lookup.json()["creation_state"] == "NOT_CREATED"
    monkeypatch.setattr(repository, "create_deployment_pair", create)
    assert post(client, project).status_code == 202


def child_context(project, task_id):
    from platform_core.task_runtime import TaskKind
    from platform_core.task_runtime.worker import WorkerContext
    repo = app_module.shared_task_repository()
    repo.promote(task_id + "-prepare")
    lease = repo.claim_next("prepare-worker", [TaskKind.DEPLOYMENT_PREPARE], {"deployment.prepare"}, 30)
    assert lease is not None and lease.task.task_id == task_id + "-prepare"
    return WorkerContext(lease.task, lease, repo, app_module.shared_task_artifacts())


def test_prepare_is_fenced_and_publishes_original_remote_task_only_after_io(client, seeded_project, tmp_path, monkeypatch):
    from platform_core.deployment.scenario_preparation import ScenarioPreparationHandler
    from platform_core.task_node_assignments import task_node_capability
    import platform_core.scenario_models as models
    import sqlite3
    project = seed(seeded_project)
    task_id = post(client, project).json()["id"]
    ctx = child_context(project, task_id)
    parent = ctx.repository.get(task_id)
    assert task_node_capability(parent, ctx.artifacts) is None
    model = tmp_path / "verified.pt"; model.write_bytes(b"isolated-model")
    monkeypatch.setattr(models, "resolve_scenario_model", lambda *args, **kwargs: {"path": str(model), "model_sha256": "a"*64})
    class Transport:
        def stage_deployment_test(self, **kwargs):
            assert kwargs["task_id"] == task_id
            assert ctx.repository.get(task_id).status.value == "QUEUED"
            db = sqlite3.connect(ctx.repository.path, timeout=.01)
            db.execute("BEGIN IMMEDIATE"); db.rollback(); db.close()
            return {"version": 1, "task_kind": "DEPLOYMENT_TEST", "transport": "object-storage-v1"}
    handler = ScenarioPreparationHandler(app_module.DATA_DIR, transport_factory=Transport)
    handler.run(ctx)
    parent = ctx.repository.get(task_id)
    assert parent.required_capabilities == ("deployment.runtime",)
    assert parent.payload_ref == "scenario/prepared-1.json"
    assert task_node_capability(parent, ctx.artifacts) == "deployment-test"
    stored = ctx.artifacts.read_json(task_id, parent.payload_ref)
    assert stored["remote_execution"]["task_kind"] == "DEPLOYMENT_TEST"
    assert post(client, project).json()["id"] == task_id
    assert handler.recover(ctx)[0].value == "SUCCEEDED"
    from platform_core.task_runtime import TaskStatus
    ctx.finish(TaskStatus.SUCCEEDED)


def test_preparation_failure_keeps_image_and_explicit_retry_reuses_both_ids(client, seeded_project, monkeypatch):
    from platform_core.deployment.scenario_preparation import ScenarioPreparationHandler
    from platform_core.task_runtime import TaskStatus
    import platform_core.scenario_models as models
    project = seed(seeded_project)
    task_id = post(client, project).json()["id"]
    ctx = child_context(project, task_id)
    def fail(*args, **kwargs): raise PermissionError("isolated model read denied")
    monkeypatch.setattr(models, "resolve_scenario_model", fail)
    with pytest.raises(PermissionError): ScenarioPreparationHandler(app_module.DATA_DIR).run(ctx)
    parent = ctx.repository.get(task_id)
    assert parent.status is TaskStatus.FAILED
    assert "isolated model read denied" in parent.error
    stored = ctx.artifacts.read_json(task_id, parent.payload_ref)
    assert Path(stored["input_path"]).read_bytes() == b"image"
    ctx.finish(TaskStatus.FAILED, error="isolated preparation failure")
    first = client.post(f"/api/v61/projects/{project}/deployment-tests/{task_id}/retry")
    assert first.status_code == 200, first.text
    second = client.post(f"/api/v61/projects/{project}/deployment-tests/{task_id}/retry")
    assert second.json()["id"] == task_id
    assert ctx.repository.get(ctx.task.task_id).status is TaskStatus.QUEUED
    assert client.post(f"/api/v61/projects/{project}/deployment-tests/{task_id}/cancel").status_code == 200


def test_stale_prepare_cannot_activate_and_cancel_blocks_late_preparation(client, seeded_project):
    from platform_core.task_runtime import TaskStatus
    project = seed(seeded_project)
    task_id = post(client, project).json()["id"]
    ctx = child_context(project, task_id)
    with ctx.repository._connect() as db:
        db.execute("UPDATE tasks SET lease_token='changed' WHERE task_id=?", (ctx.task.task_id,))
    with pytest.raises(PermissionError):
        ctx.repository.settle_deployment_preparation(task_id, ctx.lease, prepared_ref="scenario/prepared-1.json")
    parent = client.post(f"/api/v61/projects/{project}/deployment-tests/{task_id}/cancel")
    assert parent.status_code == 200
    assert ctx.repository.get(task_id).status is TaskStatus.CANCELLED


def test_batch_expected_sides_do_not_claim_a_only_as_completed_compare(client, seeded_project):
    project = seed(seeded_project)
    data = request_data(project); data["detection_sides"] = "A,B"
    task = post(client, project, data).json()
    result = client.get(f"/api/v64/projects/{project}/detection-batches/batch-stable").json()["batch"]
    assert result["items"][0]["expected_sides"] == ["A", "B"]
    assert result["completed_items"] == 0
    assert result["items"][0]["models"]["A"]["task_id"] == task["id"]


def test_waiting_writer_cannot_activate_after_confirmed_lease_expiry(client, seeded_project):
    import sqlite3, threading, time
    from datetime import datetime, timezone, timedelta
    project = seed(seeded_project)
    task_id = post(client, project).json()["id"]
    ctx = child_context(project, task_id)
    with ctx.repository._connect() as db:
        db.execute("UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
                   ((datetime.now(timezone.utc) + timedelta(seconds=.025)).isoformat(), ctx.task.task_id))
    writer = sqlite3.connect(ctx.repository.path); writer.execute("BEGIN IMMEDIATE")
    errors = []
    def activate():
        try: ctx.repository.settle_deployment_preparation(task_id, ctx.lease, prepared_ref="scenario/prepared-1.json")
        except Exception as error: errors.append(error)
    thread = threading.Thread(target=activate); thread.start()
    time.sleep(.06); writer.rollback(); writer.close(); thread.join(3)
    ctx.repository.request_cancel(ctx.task.task_id)
    assert not thread.is_alive()
    assert errors and isinstance(errors[0], PermissionError)
    assert ctx.repository.get(task_id).required_capabilities == ("deployment.input.pending",)


def test_cancelled_parent_does_not_drop_running_child_version_reference(client, seeded_project):
    from platform_core.task_runtime import TaskStatus
    project = seed(seeded_project)
    task_id = post(client, project).json()["id"]
    ctx = child_context(project, task_id)
    ctx.repository.request_cancel(task_id)
    references = app_module._algorithm_version_active_references(project, {"id": "algorithm"}, {"id": "version"})
    assert any(row["id"] == ctx.task.task_id for row in references)
    ctx.finish(TaskStatus.CANCELLED)


def test_retry_refuses_live_process_without_erasing_its_identity(client, seeded_project):
    import os, psutil
    from platform_core.task_runtime.process_control import hash_command
    project = seed(seeded_project)
    task_id = post(client, project).json()["id"]
    repo = app_module.shared_task_repository()
    process = psutil.Process(os.getpid())
    with repo._connect() as db:
        db.execute("UPDATE tasks SET status='FAILED', process_pid=?,process_create_time=?,process_command_hash=? WHERE task_id=?",
                   (os.getpid(), process.create_time(), hash_command(process.cmdline()), task_id))
    reply = client.post(f"/api/v61/projects/{project}/deployment-tests/{task_id}/retry")
    assert reply.status_code == 409, reply.text
    assert repo.get(task_id).process_pid == os.getpid()


def test_lost_http_response_after_commit_is_found_without_another_task(client, seeded_project, monkeypatch):
    project = seed(seeded_project)
    public = app_module.public_deployment_test
    monkeypatch.setattr(app_module, "public_deployment_test", lambda task: (_ for _ in ()).throw(RuntimeError("response lost after durable commit")))
    with pytest.raises(RuntimeError): post(client, project)
    monkeypatch.setattr(app_module, "public_deployment_test", public)
    reply = client.get(f"/api/v61/projects/{project}/deployment-test-creations/stable-creation").json()
    assert reply["creation_state"] == "CREATED"
    assert post(client, project).json()["id"] == reply["task_id"]
    from platform_core.task_runtime import TaskKind
    assert len(app_module.shared_task_repository().list(project_id=project, kinds=[TaskKind.DEPLOYMENT_TEST]).items) == 1


def test_real_busy_creation_rolls_back_both_queue_rows(client, seeded_project):
    import sqlite3, uuid
    from dataclasses import replace
    from platform_core.task_runtime import TaskKind, TaskRecord
    from platform_core.task_runtime.sqlite_busy import run_with_busy_retry
    project = seed(seeded_project)
    repo = app_module.shared_task_repository()
    task_id = "busy-" + uuid.uuid4().hex
    parent = TaskRecord.new(task_id, project, TaskKind.DEPLOYMENT_TEST, "request.json", "cpu:test")
    child = TaskRecord.new(task_id + "-prepare", project, TaskKind.DEPLOYMENT_PREPARE, "request.json", "cpu:prepare")
    writer = sqlite3.connect(repo.path); writer.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(sqlite3.OperationalError):
            run_with_busy_retry(lambda: repo.create_deployment_pair(parent, child), timeout=.12)
        assert repo.get(parent.task_id) is None and repo.get(child.task_id) is None
    finally:
        writer.rollback(); writer.close()
    repo.create_deployment_pair(parent, child)
    assert repo.get(parent.task_id) and repo.get(child.task_id)


def test_fast_acceptance_still_rejects_untrained_model_metadata(client, seeded_project):
    project = seed(seeded_project)
    save_algorithms(app_module.algorithms_file(project), [{"id": "algorithm", "versions": [{"id": "version", "training_status": "FAILED"}]}])
    reply = post(client, project)
    assert reply.status_code == 409
    assert client.get(f"/api/v61/projects/{project}/deployment-test-creations/stable-creation").json()["creation_state"] == "NOT_CREATED"


def test_worker_restart_reprepares_same_parent_and_fences_late_first_generation(client, seeded_project, tmp_path, monkeypatch):
    from platform_core.deployment.scenario_preparation import ScenarioPreparationHandler
    from platform_core.task_runtime import ExecutionFencedError, TaskStatus, TaskKind
    import platform_core.scenario_models as models
    project = seed(seeded_project)
    task_id = post(client, project).json()["id"]
    first = child_context(project, task_id)
    model = tmp_path / "formal.pt"; model.write_bytes(b"isolated")
    monkeypatch.setattr(models, "resolve_scenario_model", lambda *args, **kwargs: {"path": str(model), "model_sha256": "a"*64})
    staged = []
    class Transport:
        def stage_deployment_test(self, **kwargs):
            staged.append(kwargs["task_id"])
            if len(staged) == 1:
                with first.repository._connect() as db:
                    db.execute("UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00Z' WHERE task_id=?", (first.task.task_id,))
                first.repository.release_expired()
            return None
    handler = ScenarioPreparationHandler(app_module.DATA_DIR, transport_factory=Transport)
    with pytest.raises(ExecutionFencedError): handler.run(first)
    assert first.repository.get(task_id).required_capabilities == ("deployment.input.pending",)
    recovered = child_context(project, task_id)
    assert recovered.task.attempt == 2
    assert recovered.lease.lease_token != first.lease.lease_token
    assert handler.recover(recovered)[0] is TaskStatus.SUCCEEDED
    parent = recovered.repository.get(task_id)
    assert parent.payload_ref == 'scenario/prepared-2.json'
    assert staged == [task_id, task_id]
    assert len(recovered.repository.list(project_id=project, kinds=[TaskKind.DEPLOYMENT_TEST]).items) == 1
    recovered.finish(TaskStatus.SUCCEEDED)


def test_staged_image_survives_database_failure_and_recovers_without_upload(client, seeded_project, monkeypatch):
    import sqlite3
    project = seed(seeded_project)
    repo = app_module.shared_task_repository(); create = repo.create_deployment_pair
    monkeypatch.setattr(repo, "create_deployment_pair", lambda *args: (_ for _ in ()).throw(sqlite3.OperationalError("database is locked")))
    with pytest.raises(sqlite3.OperationalError): post(client, project)
    monkeypatch.setattr(repo, "create_deployment_pair", create)
    found = client.get(f"/api/v61/projects/{project}/deployment-test-creations/stable-creation").json()
    assert found["creation_state"] == "NOT_CREATED" and found["staged_input_available"] is True
    accepted = client.post(f"/api/v61/projects/{project}/deployment-test-creations/stable-creation/recover")
    assert accepted.status_code == 202, accepted.text
    same = client.post(f"/api/v61/projects/{project}/deployment-test-creations/stable-creation/recover")
    assert same.json()["id"] == accepted.json()["id"]
    task = repo.get(accepted.json()["id"])
    request = app_module.shared_task_artifacts().read_json(task.task_id, task.payload_ref)
    assert Path(request["input_path"]).read_bytes() == b"image"
    # Recovery never accepts a changed source, even when its task row is absent.
    with repo._connect() as database:
        database.execute("DELETE FROM tasks WHERE task_id IN (?, ?)", (task.task_id, task.task_id + "-prepare"))
    Path(request["input_path"]).write_bytes(b"changed")
    rejected = client.post(f"/api/v61/projects/{project}/deployment-test-creations/stable-creation/recover")
    assert rejected.status_code == 409 and repo.get(task.task_id) is None


def test_missing_parent_with_committed_child_is_unknown_not_safe_to_recreate(client, seeded_project):
    project = seed(seeded_project)
    task_id = post(client, project).json()["id"]
    repo = app_module.shared_task_repository()
    with repo._connect() as database:
        database.execute("DELETE FROM tasks WHERE task_id=?", (task_id,))
    found = client.get(f"/api/v61/projects/{project}/deployment-test-creations/stable-creation").json()
    assert found["creation_state"] == "UNKNOWN"
    assert post(client, project).status_code == 409
    assert repo.get(task_id + "-prepare") is not None
