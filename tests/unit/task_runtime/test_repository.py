from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor
import sqlite3
from dataclasses import replace
from threading import Barrier

import pytest

import platform_core.task_runtime.repository as task_repository_module
from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository, TaskStatus
from platform_core.task_runtime import ArtifactStore


def add(
    repository,
    task_id,
    project_id,
    priority,
    resource="gpu:local:0",
    capability="cuda",
):
    return repository.create(
        TaskRecord.new(
            task_id=task_id,
            project_id=project_id,
            kind=TaskKind.TRAINING,
            payload_ref="payload.json",
            resource_key=resource,
            priority=priority,
            required_capabilities=(capability,),
        )
    )


def test_annotation_search_across_durable_history_and_cursor_before_page_limit(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    for index in range(67):
        task_id = f"annotation-{index:03d}"
        artifacts.atomic_write_json(task_id, "request.json", {
            "task_name": "目标-烟雾" if index in {1, 15, 62} else "普通任务",
            "model_config_name": "远端视觉模型" if index == 64 else "默认模型",
            "model_config_id": "m-archive" if index == 66 else "m-default",
        })
        repository.create(TaskRecord.new(
            task_id, "project-a", TaskKind.AI_ANNOTATION, "request.json", "vision:local",
        ), artifacts=artifacts)
    assert repository.annotation_search_progress("project-a") == {
        "total": 67, "pending": 0, "failed": 0,
    }
    cursor = None
    matched = []
    for _ in range(3):
        page = repository.list(project_id="project-a", kinds={TaskKind.AI_ANNOTATION},
                               annotation_query="烟雾", limit=1, cursor=cursor)
        assert len(page.items) == 1
        matched.append(page.items[0].task_id)
        cursor = page.next_cursor
    assert set(matched) == {"annotation-001", "annotation-015", "annotation-062"}
    assert cursor is None
    assert [item.task_id for item in repository.list(
        project_id="project-a", kinds={TaskKind.AI_ANNOTATION},
        annotation_query="远端视觉模型",
    ).items] == ["annotation-064"]
    assert [item.task_id for item in repository.list(
        project_id="project-a", kinds={TaskKind.AI_ANNOTATION},
        annotation_query="m-archive",
    ).items] == ["annotation-066"]
    # LIKE wildcards must be literals, never unexpectedly match every task.
    assert not repository.list(project_id="project-a", kinds={TaskKind.AI_ANNOTATION},
                               annotation_query="%_\\").items


def test_annotation_search_schema_migrates_v1_in_place_without_dropping_tasks(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    migration_fields = (
        "    finished_at TEXT,\n"
        "    annotation_name TEXT,\n"
        "    annotation_model_name TEXT,\n"
        "    annotation_model_id TEXT,\n"
        "    annotation_search_ready INTEGER NOT NULL DEFAULT 0\n"
    )
    assert migration_fields in task_repository_module.SCHEMA
    with sqlite3.connect(path) as database:
        database.executescript(task_repository_module.SCHEMA.replace(
            migration_fields, "    finished_at TEXT\n",
        ))
        database.execute("ALTER TABLE tasks ADD COLUMN resource_wait_reason TEXT")
        legacy = TaskRecord.new("historic", "project-1", TaskKind.AI_ANNOTATION,
                                "request.json", "vision:legacy")
        values = task_repository_module._to_values(legacy)
        database.execute(
            f"INSERT INTO tasks ({','.join(values)}) VALUES ({','.join('?' for _ in values)})",
            tuple(values.values()),
        )
        database.execute("PRAGMA user_version=1")
    migrated = TaskRepository(path)
    assert migrated.get("historic") is not None
    assert migrated.annotation_search_progress("project-1") == {
        "total": 1, "pending": 1, "failed": 0,
    }
    with sqlite3.connect(path) as database:
        assert int(database.execute("PRAGMA user_version").fetchone()[0]) == 7
        assert database.execute("SELECT COUNT(*) FROM inference_permits").fetchone()[0] == 0


def test_annotation_statistics_migrate_from_v2_and_batch_scope_exactly(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    repository = TaskRepository(path)
    ai = TaskRecord.new("ai-real", "p1", TaskKind.AI_ANNOTATION, "request.json", "vision:m")
    repository.create(ai)
    repository.create(TaskRecord.new("training", "p1", TaskKind.TRAINING, "request.json", "gpu:m"))
    # Simulate a previously deployed schema-v2 database with existing task rows.
    with sqlite3.connect(path) as db:
        db.execute("DROP TABLE annotation_task_statistics")
        db.execute("PRAGMA user_version=2")
    migrated = TaskRepository(path)
    assert migrated.get("ai-real") is not None
    assert migrated.annotation_statistics_many("p1", ["ai-real"]) == {}
    counts = dict(total=3, success=1, empty=1, failed=1, accepted=1,
                  rejected=0, unreviewed=1, boxes=2, gt_committed=1)
    migrated.set_annotation_statistics("ai-real", counts)
    assert migrated.annotation_statistics_many("p1", ["ai-real"])["ai-real"]["counts"] == counts
    assert migrated.annotation_statistics_many("p2", ["ai-real"]) == {}
    assert migrated.annotation_statistics_many("p1", ["training"]) == {}
    with pytest.raises(ValueError):
        migrated.set_annotation_statistics("training", counts)
    with pytest.raises(ValueError):
        migrated.set_annotation_statistics("ai-real", {**counts, "gt_committed": 2})
    with sqlite3.connect(path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 7
        assert db.execute("SELECT COUNT(*) FROM inference_domain_state").fetchone()[0] == 0


def test_inference_schema_migrates_v3_preserving_tasks_and_candidate_statistics(tmp_path):
    path = tmp_path / 'tasks.sqlite3'
    repository = TaskRepository(path)
    task = TaskRecord.new('historic-inference', 'p', TaskKind.AI_ANNOTATION, 'request.json', 'vision:legacy')
    repository.create(task)
    before = repository.get(task.task_id)
    counts = dict(total=2, success=1, empty=1, failed=0, accepted=0,
                  rejected=0, unreviewed=2, boxes=1, gt_committed=0)
    repository.set_annotation_statistics(task.task_id, counts)
    with sqlite3.connect(path) as db:
        db.execute('DROP TABLE inference_permits')
        db.execute('DROP TABLE inference_domain_state')
        db.execute('PRAGMA user_version=3')
    migrated = TaskRepository(path)
    assert migrated.get(task.task_id) == before
    assert migrated.annotation_statistics_many('p', [task.task_id])[task.task_id]['counts'] == counts
    with sqlite3.connect(path) as db:
        assert db.execute('PRAGMA user_version').fetchone()[0] == 7
        assert db.execute('SELECT COUNT(*) FROM inference_permits').fetchone()[0] == 0
        assert db.execute('SELECT COUNT(*) FROM inference_domain_state').fetchone()[0] == 0


def test_annotation_search_legacy_batch_backfill_is_bounded_and_reports_corrupt(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    for index in range(5):
        repository.create(TaskRecord.new(
            f"legacy-{index}", "project-a", TaskKind.AI_ANNOTATION,
            "request.json", "vision:local",
        ), artifacts=artifacts)
    assert repository.annotation_search_progress("project-a")["pending"] == 5
    for index in range(4):
        artifacts.atomic_write_json(f"legacy-{index}", "request.json", {
            "task_name": f"历史任务{index}", "model_config_name": "历史视觉模型",
        })
    assert repository.backfill_annotation_search_batch("project-a", artifacts, limit=2) == 2
    assert repository.annotation_search_progress("project-a")["pending"] == 3
    assert repository.backfill_annotation_search_batch("project-a", artifacts, limit=10) == 3
    assert repository.annotation_search_progress("project-a") == {
        "total": 5, "pending": 0, "failed": 1,
    }
    assert len(repository.list(project_id="project-a", kinds={TaskKind.AI_ANNOTATION},
                               annotation_query="历史视觉模型").items) == 4
    artifacts.atomic_write_json("legacy-4", "request.json", {
        "task_name": "已恢复的任务", "model_config_name": "恢复模型",
    })
    assert repository.retry_failed_annotation_search("project-a") == 1
    assert repository.backfill_annotation_search_batch("project-a", artifacts) == 1
    assert repository.annotation_search_progress("project-a")["failed"] == 0
    assert [item.task_id for item in repository.list(
        project_id="project-a", kinds={TaskKind.AI_ANNOTATION},
        annotation_query="已恢复的任务",
    ).items] == ["legacy-4"]


def test_ready_task_repository_bypasses_init_lock(tmp_path, monkeypatch):
    path = tmp_path / "tasks.sqlite3"
    TaskRepository(path)

    class ForbiddenInitLock:
        def __init__(self, *args, **kwargs):
            raise AssertionError("ready task repository must bypass init FileLock")

    monkeypatch.setattr(task_repository_module, "FileLock", ForbiddenInitLock)

    reopened = TaskRepository(path)
    assert reopened.journal_mode() == "wal"


def test_task_regular_connection_does_not_negotiate_wal(tmp_path, monkeypatch):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    real_connect = sqlite3.connect

    class GuardedConnection:
        def __init__(self, connection):
            self.connection = connection

        @property
        def row_factory(self):
            return self.connection.row_factory

        @row_factory.setter
        def row_factory(self, value):
            self.connection.row_factory = value

        def execute(self, sql, *args, **kwargs):
            if "journal_mode" in str(sql).lower():
                raise AssertionError("ordinary TaskRepository._connect() must not touch journal_mode")
            return self.connection.execute(sql, *args, **kwargs)

        def __getattr__(self, name):
            return getattr(self.connection, name)

    monkeypatch.setattr(
        task_repository_module.sqlite3,
        "connect",
        lambda *args, **kwargs: GuardedConnection(real_connect(*args, **kwargs)),
    )

    connection = repository._connect()
    try:
        assert int(connection.execute("PRAGMA busy_timeout").fetchone()[0]) == 5000
    finally:
        connection.close()


def test_wal_claim_is_global_low_number_first_and_fifo(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repository, "late", "project-1", 20)
    add(repository, "first", "project-2", 3)
    add(repository, "second", "project-3", 3)

    assert repository.journal_mode() == "wal"
    first = repository.claim_next("worker-1", [TaskKind.TRAINING], {"cuda"}, 30)
    assert first is not None
    assert first.task.task_id == "first"
    assert first.task.attempt == 1
    assert repository.claim_next("worker-2", [TaskKind.TRAINING], {"cuda"}, 30) is None

    repository.finish("first", first.lease_token, TaskStatus.SUCCEEDED, "result.json")
    second = repository.claim_next("worker-2", [TaskKind.TRAINING], {"cuda"}, 30)
    assert second is not None
    assert second.task.task_id == "second"


def test_capability_cancel_retry_cursor_and_expired_lease(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repository, "cpu-only", "project-1", 1, "cpu:local", "opencv")
    assert repository.claim_next("gpu", [TaskKind.TRAINING], {"cuda"}) is None

    page = repository.list(project_id="project-1", limit=1)
    assert page.items[0].task_id == "cpu-only"
    cancelled = repository.request_cancel("cpu-only")
    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.finished_at is not None

    retried = repository.retry("cpu-only")
    assert retried.task_id == "cpu-only"
    assert retried.status is TaskStatus.QUEUED
    assert retried.retry_of == "cpu-only"
    assert retried.error is None
    assert retried.finished_at is None

    lease = repository.claim_next("cpu", [TaskKind.TRAINING], {"opencv"}, lease_seconds=1)
    assert lease is not None
    future = datetime.now(timezone.utc) + timedelta(seconds=2)
    assert repository.release_expired(future) == 1
    recovered = repository.get(lease.task.task_id)
    assert recovered is not None
    assert recovered.status is TaskStatus.QUEUED
    assert recovered.stage == "recovered"
    assert recovered.attempt == 1


def test_delete_terminal_refuses_live_task_and_purges_finished_truth(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repository, "delete-terminal", "project-1", 5)

    with pytest.raises(ValueError, match="only terminal tasks"):
        repository.delete_terminal(
            "delete-terminal",
            project_id="project-1",
            kind=TaskKind.TRAINING,
        )

    cancelled = repository.request_cancel("delete-terminal")
    assert cancelled.status is TaskStatus.CANCELLED
    assert repository.delete_terminal(
        "delete-terminal",
        project_id="project-1",
        kind=TaskKind.TRAINING,
    ) is True
    assert repository.get("delete-terminal") is None
    assert repository.delete_terminal(
        "delete-terminal",
        project_id="project-1",
        kind=TaskKind.TRAINING,
    ) is False


def test_heartbeat_and_finish_require_the_current_lease(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repository, "task-1", "project-1", 5)
    lease = repository.claim_next("worker", [TaskKind.TRAINING], {"cuda"})
    assert lease is not None

    with pytest.raises(PermissionError, match="lease"):
        repository.heartbeat("task-1", "wrong", progress=25)

    running = repository.heartbeat(
        "task-1",
        lease.lease_token,
        progress=25,
        stage="preparing",
        current_item="image-3",
    )
    assert (running.progress, running.stage, running.current_item) == (
        25,
        "preparing",
        "image-3",
    )

    with pytest.raises(PermissionError, match="lease"):
        repository.finish("task-1", "wrong", TaskStatus.SUCCEEDED)

    finished = repository.finish(
        "task-1",
        lease.lease_token,
        TaskStatus.SUCCEEDED,
        result_ref="result.json",
    )
    assert finished.status is TaskStatus.SUCCEEDED
    assert finished.progress == 100
    assert finished.finished_at is not None


def test_list_cursor_is_bounded_and_deterministic(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    for index in range(5):
        add(repository, f"task-{index}", "project-1", index + 1, resource=f"cpu:{index}")

    first = repository.list(project_id="project-1", limit=2)
    second = repository.list(project_id="project-1", limit=2, cursor=first.next_cursor)
    third = repository.list(project_id="project-1", limit=2, cursor=second.next_cursor)
    ids = [item.task_id for page in (first, second, third) for item in page.items]
    assert len(ids) == 5
    assert len(set(ids)) == 5
    assert third.next_cursor is None


def test_complete_review_is_guarded_idempotent_and_keeps_explicit_rejection(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    record = TaskRecord.new(
        "ai-1",
        "project-1",
        TaskKind.AI_ANNOTATION,
        "request.json",
        "vision:model-1",
        required_capabilities=("vision_provider",),
    )
    repository.create(record)
    lease = repository.claim_next(
        "vision-worker",
        [TaskKind.AI_ANNOTATION],
        {"vision_provider"},
    )
    assert lease is not None
    awaiting = repository.finish(
        "ai-1",
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        "candidates/manifest.json",
    )
    assert awaiting.finished_at is None

    rejected = repository.complete_review(
        "ai-1",
        TaskStatus.SUCCEEDED,
        "review/result.json",
        accepted=False,
    )
    assert rejected.accepted is False
    assert rejected.finished_at is not None
    same = repository.complete_review(
        "ai-1",
        TaskStatus.SUCCEEDED,
        "review/result.json",
        accepted=False,
    )
    assert same == rejected

    with pytest.raises(ValueError, match="conflicting review"):
        repository.complete_review(
            "ai-1",
            TaskStatus.PARTIAL_SUCCESS,
            "review/other.json",
            accepted=True,
        )


def test_resume_after_confirmation_requeues_material_import_and_is_idempotent(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            "import-1",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "requests/import.json",
            "cpu:local",
            required_capabilities=("archive",),
        )
    )
    lease = repository.claim_next("import-worker", [TaskKind.MATERIAL_IMPORT], {"archive"})
    assert lease is not None
    repository.heartbeat(
        "import-1",
        lease.lease_token,
        progress=75,
        stage="reviewing",
        current_item="batch-7",
    )
    repository.finish(
        "import-1",
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        result_ref="candidates/manifest.json",
        error="needs confirmation",
    )

    resumed = repository.resume_after_confirmation("import-1")

    assert resumed.status is TaskStatus.QUEUED
    assert resumed.stage == "indexing_queued"
    assert resumed.progress == 75
    assert resumed.current_item is None
    assert resumed.error is None
    assert resumed.accepted is True
    assert resumed.finished_at is None
    assert resumed.result_ref == "candidates/manifest.json"
    assert repository.resume_after_confirmation("import-1") == resumed


def test_resume_after_confirmation_can_atomically_switch_remote_scan_to_local_indexer(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            "import-remote-review",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "requests/import.json",
            "material-import:agent",
            required_capabilities=("agent.remote",),
        )
    )
    lease = repository.claim_next(
        "agent-owner",
        [TaskKind.MATERIAL_IMPORT],
        {"agent.remote"},
    )
    assert lease is not None
    repository.finish(
        "import-remote-review",
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        result_ref="remote-results/1/result.json",
    )

    resumed = repository.resume_after_confirmation(
        "import-remote-review",
        required_capabilities=("storage.import",),
    )

    assert resumed.status is TaskStatus.QUEUED
    assert resumed.stage == "indexing_queued"
    assert resumed.required_capabilities == ("storage.import",)
    assert resumed.result_ref == "remote-results/1/result.json"

    # Confirmation is idempotent and must preserve/repair the local-write owner.
    same = repository.resume_after_confirmation(
        "import-remote-review",
        required_capabilities=("storage.import",),
    )
    assert same.required_capabilities == ("storage.import",)

    local = repository.claim_next(
        "storage-import-worker",
        [TaskKind.MATERIAL_IMPORT],
        {"storage.import"},
    )
    assert local is not None
    assert local.task.task_id == "import-remote-review"
    assert local.task.stage == "indexing"


def test_resume_after_confirmation_rejects_rejected_material_import(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            "import-rejected",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "requests/import.json",
            "cpu:local",
            required_capabilities=("archive",),
        )
    )
    lease = repository.claim_next("import-worker", [TaskKind.MATERIAL_IMPORT], {"archive"})
    assert lease is not None
    repository.finish(
        "import-rejected",
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
        accepted=False,
    )
    before = repository.get("import-rejected")

    with pytest.raises(ValueError, match="cannot resume"):
        repository.resume_after_confirmation("import-rejected")

    assert repository.get("import-rejected") == before


def test_resume_after_confirmation_is_atomic_for_concurrent_confirmations(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            "import-concurrent",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "requests/import.json",
            "cpu:local",
            required_capabilities=("archive",),
        )
    )
    lease = repository.claim_next("import-worker", [TaskKind.MATERIAL_IMPORT], {"archive"})
    assert lease is not None
    repository.finish(
        "import-concurrent",
        lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
    )
    barrier = Barrier(2)

    def confirm():
        barrier.wait()
        return repository.resume_after_confirmation("import-concurrent")

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(confirm) for _ in range(2)]
        results = [future.result() for future in futures]

    assert all(record.accepted is True for record in results)
    assert all(record.status is TaskStatus.QUEUED for record in results)
    assert all(record.stage == "indexing_queued" for record in results)
    assert len({record.updated_at for record in results}) == 1


def test_confirmed_material_import_keeps_indexing_stage_through_claim_and_recovery(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    repository.create(
        TaskRecord.new(
            "import-indexing",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "requests/import.json",
            "cpu:import",
            required_capabilities=("archive",),
        )
    )
    initial_lease = repository.claim_next(
        "import-worker", [TaskKind.MATERIAL_IMPORT], {"archive"}
    )
    assert initial_lease is not None
    repository.finish(
        "import-indexing",
        initial_lease.lease_token,
        TaskStatus.AWAITING_CONFIRMATION,
    )
    repository.resume_after_confirmation("import-indexing")
    repository.create(
        TaskRecord.new(
            "training-indexing",
            "project-1",
            TaskKind.TRAINING,
            "requests/training.json",
            "cpu:training",
            required_capabilities=("cuda",),
        )
    )

    import_lease = repository.claim_next(
        "import-worker", [TaskKind.MATERIAL_IMPORT], {"archive"}
    )
    training_lease = repository.claim_next("training-worker", [TaskKind.TRAINING], {"cuda"})

    assert import_lease is not None
    assert import_lease.task.stage == "indexing"
    assert repository.resume_after_confirmation("import-indexing") == import_lease.task
    assert training_lease is not None
    assert training_lease.task.stage == "running"
    assert repository.release_expired(datetime.now(timezone.utc) + timedelta(minutes=1)) == 2
    recovered_import = repository.get("import-indexing")
    recovered_training = repository.get("training-indexing")
    assert recovered_import is not None
    assert recovered_import.stage == "indexing_queued"
    assert repository.resume_after_confirmation("import-indexing") == recovered_import
    assert recovered_training is not None
    assert recovered_training.stage == "recovered"

    running = replace(
        TaskRecord.new(
            "import-running",
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "requests/import.json",
            "cpu:other",
        ),
        status=TaskStatus.RUNNING,
        stage="running",
        accepted=True,
    )
    repository.create(running)
    with pytest.raises(ValueError, match="cannot resume"):
        repository.resume_after_confirmation("import-running")
    assert repository.get("import-running") == running


def test_promote_can_move_a_task_ahead_even_when_current_priority_is_one(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repository, "first", "project-1", 1, resource="gpu:0")
    add(repository, "promoted", "project-1", 50, resource="gpu:0")

    updated = repository.promote("promoted")
    assert updated.priority == 1
    lease = repository.claim_next("worker", [TaskKind.TRAINING], {"cuda"})
    assert lease is not None
    assert lease.task.task_id == "promoted"


def test_fail_queued_precondition_never_overwrites_running_or_cancelled_task(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    queued = TaskRecord.new(
        "queued-precondition",
        "project",
        TaskKind.TRAINING,
        "payload.json",
        "training:remote",
    )
    repository.create(queued)
    failed = repository.fail_queued_precondition(
        queued.task_id,
        "REMOTE_INPUT_FAILED",
        status=TaskStatus.BLOCKED_BY_ENVIRONMENT,
        stage="remote_input_preparation_failed",
    )
    assert failed.status is TaskStatus.BLOCKED_BY_ENVIRONMENT
    assert failed.stage == "remote_input_preparation_failed"
    assert failed.error == "REMOTE_INPUT_FAILED"
    assert failed.finished_at is not None

    running = repository.create(
        TaskRecord.new(
            "running-precondition",
            "project",
            TaskKind.TRAINING,
            "payload.json",
            "training:remote",
            required_capabilities=("cuda",),
        )
    )
    lease = repository.claim_next("worker", [TaskKind.TRAINING], {"cuda"})
    assert lease is not None and lease.task.task_id == running.task_id
    unchanged = repository.fail_queued_precondition(
        running.task_id,
        "must-not-overwrite",
        status=TaskStatus.FAILED,
    )
    assert unchanged.status is TaskStatus.RUNNING
    assert unchanged.error != "must-not-overwrite"

    cancelled = repository.create(
        TaskRecord.new(
            "cancelled-precondition",
            "project",
            TaskKind.TRAINING,
            "payload.json",
            "training:remote",
        )
    )
    repository.request_cancel(cancelled.task_id)
    unchanged = repository.fail_queued_precondition(
        cancelled.task_id,
        "must-not-revive",
        status=TaskStatus.FAILED,
    )
    assert unchanged.status is TaskStatus.CANCELLED


def test_base_repository_cannot_bypass_remote_agent_recovery_hold(tmp_path):
    """A plain TaskRepository caller must not make an expired Agent runnable."""
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    for task_id in ("first-remote", "second-remote"):
        repository.create(TaskRecord.new(
            task_id, "project-1", TaskKind.MODEL_CONVERSION,
            "payload.json", "conversion:shared-remote",
        ))
    first = repository.claim_next(
        "agent:node-a", [TaskKind.MODEL_CONVERSION], set(),
    )
    assert first is not None and first.task.task_id == "first-remote"
    expired = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with repository._connect() as db:
        db.execute("UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
                   (expired, "first-remote"))

    assert repository.release_expired() == 0
    held = repository.get("first-remote")
    assert held.status is TaskStatus.RUNNING
    assert held.stage == "recovery_blocked_remote_agent_unverified"
    assert held.worker_id == "agent:node-a"

    # claim_next calls its own release_expired logic. This second independent
    # entry point must also honor the hold, despite the expired lease.
    assert repository.claim_next(
        "local-worker", [TaskKind.MODEL_CONVERSION], set(),
    ) is None
    assert repository.get("second-remote").status is TaskStatus.QUEUED
    assert repository.get("first-remote").attempt == 1


def test_delegated_training_admission_cannot_ignore_remote_owner_hold(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    for task_id in ("remote-training-owner", "local-training-contender"):
        repository.create(TaskRecord.new(
            task_id, "project-1", TaskKind.TRAINING,
            "request.json", "training:shared-delegated",
        ))
    first = repository.claim_next("agent:node-a", [TaskKind.TRAINING], set())
    assert first is not None and first.task.task_id == "remote-training-owner"
    past = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
            (past, "remote-training-owner"),
        )
    assert repository.release_expired() == 0
    calls = []

    def permissive_gpu_admission(*_args):
        calls.append(True)
        return True, None

    # This callback models a GPU planner that admits the queued candidate.
    # It must not erase the stronger resource fence for a remote execution.
    assert repository.claim_next(
        "local-worker", [TaskKind.TRAINING], set(),
        admission=permissive_gpu_admission,
    ) is None
    assert not calls
    assert repository.get("remote-training-owner").status is TaskStatus.RUNNING
    assert repository.get("local-training-contender").status is TaskStatus.QUEUED


def test_generic_heartbeat_cannot_resurrect_expired_remote_agent_lease(tmp_path):
    """Plain TaskRepository must not bypass remote execution lease fencing."""
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repository, "remote-heartbeat", "project-1", 5,
        resource="training:remote-heartbeat", capability="cuda")
    lease = repository.claim_next(
        "agent:node-a", [TaskKind.TRAINING], {"cuda"},
    )
    assert lease is not None
    assert lease.task.task_id == "remote-heartbeat"

    expired = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with repository._connect() as db:
        db.execute(
            "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
            (expired, "remote-heartbeat"),
        )

    # Before any recovery sweep, stale Agent must not extend an expired lease.
    with pytest.raises(PermissionError, match="lease"):
        repository.heartbeat(
            "remote-heartbeat", lease.lease_token,
            progress=90, stage="training",
        )
    assert repository.get("remote-heartbeat").lease_expires_at == expired

    # A generic recovery pass marks the remote STOP_UNVERIFIED hold.
    assert repository.release_expired() == 0
    held = repository.get("remote-heartbeat")
    assert held.stage == "recovery_blocked_remote_agent_unverified"
    with pytest.raises(PermissionError, match="lease"):
        repository.heartbeat(
            "remote-heartbeat", lease.lease_token,
            progress=99, stage="completed",
        )
    after = repository.get("remote-heartbeat")
    assert after.stage == "recovery_blocked_remote_agent_unverified"
    assert after.progress == 0
    assert after.lease_expires_at == expired
    assert after.attempt == 1
    assert after.worker_id == "agent:node-a"


def test_generic_finish_and_unversioned_finalization_cannot_publish_expired_remote_agent(tmp_path):
    """Plain TaskRepository must not bypass remote execution finalization fencing."""
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    add(repository, "remote-finish", "project-1", 5,
        resource="training:remote-finish", capability="cuda")
    lease = repository.claim_next(
        "agent:node-a", [TaskKind.TRAINING], {"cuda"},
    )
    assert lease is not None

    expired = (datetime.now(timezone.utc) - timedelta(seconds=10)).isoformat()
    with repository._connect() as db:
        db.execute(
            "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
            (expired, "remote-finish"),
        )

    # Neither an unversioned begin-finalization nor generic finish may
    # declare success when a remote execution's lease has already expired.
    with pytest.raises(PermissionError, match="execution"):
        repository.begin_finalization("remote-finish", lease.lease_token)
    with pytest.raises(PermissionError, match="lease"):
        repository.finish(
            "remote-finish", lease.lease_token, TaskStatus.SUCCEEDED,
            result_ref="forged-result.json",
        )
    assert repository.release_expired() == 0

    with pytest.raises(PermissionError, match="execution"):
        repository.begin_finalization("remote-finish", lease.lease_token)
    with pytest.raises(PermissionError, match="lease"):
        repository.finish(
            "remote-finish", lease.lease_token, TaskStatus.SUCCEEDED,
            result_ref="forged-result.json",
        )

    held = repository.get("remote-finish")
    assert held.status is TaskStatus.RUNNING
    assert held.stage == "recovery_blocked_remote_agent_unverified"
    assert held.lease_expires_at == expired
    assert held.result_ref is None
    assert held.worker_id == "agent:node-a"
    assert held.attempt == 1



def test_batch_resource_queue_positions_match_scalar_and_are_bounded(tmp_path):
    repo = TaskRepository(tmp_path / 'batch.sqlite3')
    for i in range(18):
        task = TaskRecord.new(str(i), 'p' if i % 2 else 'other', TaskKind.TRAINING,
                              'request.json', 'cpu:' + str(i % 3), priority=1 + i % 4)
        repo.create(replace(task, created_at='2026-11-18T00:00:00+00:00', queue_rank=i % 5,
                            status=TaskStatus.CANCELLED if i == 3 else TaskStatus.QUEUED))
    ids = [str(i) for i in range(18)]
    expected = {key: repo.resource_queue_position(key) for key in ids}
    assert repo.resource_queue_positions(ids) == expected
    assert repo.resource_queue_positions([]) == {}
    assert repo.resource_queue_positions(['1', '1']) == {'1': expected['1']}
    with pytest.raises(KeyError): repo.resource_queue_positions(['missing'])
    with pytest.raises(ValueError): repo.resource_queue_positions(str(i) for i in range(101))
    repo.request_cancel('1')
    assert repo.resource_queue_positions(ids) == {key: repo.resource_queue_position(key) for key in ids}


def test_batch_positions_use_one_snapshot_during_concurrent_change(tmp_path, monkeypatch):
    repo = TaskRepository(tmp_path / 'snapshot.sqlite3')
    for i in range(30):
        repo.create(TaskRecord.new(str(i), 'p', TaskKind.TRAINING, 'request.json', 'cpu:test', priority=50))
    ids = [str(i) for i in range(30)]
    before = {key: repo.resource_queue_position(key) for key in ids}
    original = repo._connect
    connections = []
    statements = []
    changed = []
    def connect():
        db = original()
        connections.append(db)
        db.set_trace_callback(statements.append)
        def change_during_scan():
            if not changed:
                changed.append(True)
                with sqlite3.connect(repo.path) as writer:
                    writer.execute("UPDATE tasks SET priority=1 WHERE task_id='29'")
            return 0
        db.set_progress_handler(change_during_scan, 100)
        return db
    monkeypatch.setattr(repo, '_connect', connect)
    result = repo.resource_queue_positions(ids)
    assert changed and len(connections) == 1 and len(statements) == 1
    assert result == before
    monkeypatch.setattr(repo, '_connect', original)
    assert repo.resource_queue_position('29') == 1
    assert repo.resource_queue_positions(ids) == {key: repo.resource_queue_position(key) for key in ids}

# P2A immutable Payload reference publication; production handlers are not migrated.
def _publication_setup(tmp_path, *, deployment=False, phase=None, repository_type=TaskRepository):
    from platform_core.task_runtime.payload_publications import PayloadPublicationIdentity
    repository = repository_type(tmp_path / 'publication.sqlite3')
    store = ArtifactStore(tmp_path / 'artifacts')
    parent_kind = TaskKind.DEPLOYMENT_TEST if deployment else TaskKind.TRAINING
    child_kind = TaskKind.DEPLOYMENT_PREPARE if deployment else TaskKind.TRAINING_PREPARE
    child_id = 'parent-prepare' if deployment else 'trainprep_parent'
    parent = replace(TaskRecord.new('parent', 'project', parent_kind, 'payload.json', 'pending',
        required_capabilities=('deployment.input.pending' if deployment else 'training.input.ready',)),
        stage='PREPARING_MODEL' if deployment else 'training_input_pending')
    repository.create(parent)
    child_identity = PayloadPublicationIdentity(task_id=child_id, project_id='project', kind=child_kind.value,
        phase='create', expected_ref='', expected_parent_attempt=0, intent={'request_id':'original'})
    child_payload = {'parent_task_id':'parent'} if deployment else {'training_task_id':'parent','project_id':'project'}
    child_publication = store.prepare_payload_publication(child_identity, child_payload)
    repository.create(TaskRecord.new(child_id, 'project', child_kind, child_publication.version.payload_ref, 'prep'))
    lease = repository.claim_next('worker', [child_kind], set(), lease_seconds=120)
    assert lease is not None
    publication_identity = PayloadPublicationIdentity(task_id='parent', project_id='project', kind=parent_kind.value,
        phase=phase or ('deployment.ready' if deployment else 'training.ready'),
        expected_ref=parent.payload_ref, expected_parent_attempt=parent.attempt, intent={'request_id':'r'})
    activation = {} if publication_identity.data['phase']=='training.freeze' else {
        'resource_key':'deployment-runtime:.pt' if deployment else 'training:auto',
        'required_capabilities':['deployment.runtime' if deployment else 'training.ultralytics'], 'stage':'queued'}
    publication = store.prepare_payload_publication(publication_identity, {'prepared':True}, activation=activation)
    kwargs=dict(artifacts=store, publication=publication, child_task_id=child_id, child_lease_token=lease.lease_token,
                child_attempt=lease.task.attempt, child_worker_id=lease.worker_id,
                child_payload_ref=lease.task.payload_ref)
    method=repository.publish_deployment_payload if deployment else repository.publish_training_payload
    return repository, store, lease, kwargs, method


@pytest.mark.parametrize('deployment,phase', [(False,'training.freeze'), (False,'training.ready'), (True,'deployment.ready')])
def test_payload_publish_applied_and_idempotent(tmp_path, deployment, phase):
    repo, store, lease, kwargs, publish = _publication_setup(tmp_path, deployment=deployment, phase=phase)
    result=publish('parent', **kwargs)
    assert result.outcome=='APPLIED'
    assert result.task.payload_ref==kwargs['publication'].version.payload_ref
    assert result.task.attempt==0
    if phase=='training.freeze':
        assert result.task.required_capabilities==('training.input.ready',)
        assert result.task.stage=='training_input_pending'
    else:
        assert result.task.stage=='queued'
        assert result.task.resource_key==kwargs['publication'].metadata['activation']['resource_key']
    again=publish('parent', **kwargs)
    assert again.outcome=='ALREADY_APPLIED'
    assert again.task==result.task


@pytest.mark.parametrize('field,value,code', [
    ('child_task_id','another','PARENT_CHILD'), ('child_lease_token','wrong','LEASE_INVALID'),
    ('child_attempt',0,'LEASE_INVALID'), ('child_worker_id','foreign','LEASE_INVALID'),
    ('child_payload_ref','payload.json','CONTENT'),
    ('child_lease_token',None,'LEASE_INVALID'), ('child_worker_id','', 'LEASE_INVALID'),
])
def test_payload_publish_wrong_owner(tmp_path, field, value, code):
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, lease, kwargs, publish = _publication_setup(tmp_path)
    kwargs[field]=value
    with pytest.raises(PayloadPublicationError, match=code):
        publish('parent', **kwargs)
    assert repo.get('parent').payload_ref=='payload.json'


@pytest.mark.parametrize('target,column,value,code', [
    ('parent','status','CANCELLED','NOT_ELIGIBLE'), ('child','status','CANCEL_REQUESTED','LEASE_INVALID'),
    ('child','lease_expires_at','2000-01-01T00:00:00Z','LEASE_INVALID'),
    ('parent','project_id','foreign','IDENTITY'), ('child','project_id','foreign','PARENT_CHILD'),
    ('parent','kind','MODEL_CONVERSION','IDENTITY'), ('child','kind','VIDEO_FRAMES','PARENT_CHILD'),
    ('parent','attempt',1,'NOT_ELIGIBLE'), ('parent','stage','other','NOT_ELIGIBLE'),
    ('parent','payload_ref','successor.json','EXPECTED_REF_CONFLICT'),
])
def test_payload_publish_rechecks_database(tmp_path, target, column, value, code):
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, lease, kwargs, publish = _publication_setup(tmp_path)
    task_id='parent' if target=='parent' else lease.task.task_id
    with repo._connect() as database:
        database.execute(f'UPDATE tasks SET {column}=? WHERE task_id=?', (value, task_id))
    with pytest.raises(PayloadPublicationError, match=code):
        publish('parent', **kwargs)
    assert repo.get('parent').payload_ref != kwargs['publication'].version.payload_ref


def test_payload_publish_missing_owner_never_uses_legacy_fallback(tmp_path):
    repo, store, lease, kwargs, publish = _publication_setup(tmp_path)
    del kwargs['child_worker_id']
    with pytest.raises(TypeError):
        publish('parent', **kwargs)


def test_payload_publish_already_claimed_parent_and_old_worker(tmp_path):
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    assert publish('parent', **kwargs).outcome=='APPLIED'
    parent=repo.claim_next('training-worker', [TaskKind.TRAINING], {'training.ultralytics'})
    assert parent is not None and parent.task.attempt==1
    assert publish('parent', **kwargs).outcome=='ALREADY_APPLIED'
    assert repo.get('parent')==parent.task
    with repo._connect() as database:
        database.execute('UPDATE tasks SET lease_token=? WHERE task_id=?', ('replacement',child.task.task_id))
    assert publish('parent', **kwargs).outcome=='ALREADY_APPLIED'


def test_payload_publish_legacy_child_not_a_frozen_binding(tmp_path):
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, lease, kwargs, publish = _publication_setup(tmp_path)
    store.atomic_write_json(lease.task.task_id, 'payload.json', {'training_task_id':'parent'})
    with repo._connect() as database:
        database.execute('UPDATE tasks SET payload_ref=? WHERE task_id=?', ('payload.json',lease.task.task_id))
    kwargs['child_payload_ref']='payload.json'
    with pytest.raises(PayloadPublicationError, match='CONTENT'):
        publish('parent', **kwargs)



def test_payload_publish_parent_and_interface_binding(tmp_path):
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    with pytest.raises(PayloadPublicationError, match='IDENTITY'):
        publish('different', **kwargs)
    with pytest.raises(PayloadPublicationError, match='IDENTITY'):
        repo.publish_deployment_payload('parent', **kwargs)


def test_payload_publish_child_content_binding(tmp_path):
    from platform_core.task_runtime.payload_publications import PayloadPublicationIdentity, PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    different=store.prepare_payload_publication(PayloadPublicationIdentity(task_id=child.task.task_id,
        project_id='project', kind='TRAINING_PREPARE', phase='create', expected_ref='',
        expected_parent_attempt=0, intent={'request_id':'different'}),
        {'training_task_id':'another-parent', 'project_id':'project'})
    with repo._connect() as database:
        database.execute('UPDATE tasks SET payload_ref=? WHERE task_id=?', (different.version.payload_ref,child.task.task_id))
    kwargs['child_payload_ref']=different.version.payload_ref
    with pytest.raises(PayloadPublicationError, match='PARENT_CHILD'):
        publish('parent', **kwargs)


@pytest.mark.parametrize('failure', ['receipt_missing','content_mismatch','forged_descriptor'])
def test_payload_publish_file_precondition_failure_never_opens_writer(tmp_path, monkeypatch, failure):
    from pathlib import Path
    import os
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    publication=kwargs['publication']
    if failure=='receipt_missing':
        path=store.root/'parent'/'payload-publications'/'v1'/(publication.operation_id+'.json')
        path.unlink()
    elif failure=='content_mismatch':
        path=store.root/'parent'/publication.version.payload_ref
        if os.name=='nt': path=Path('\\\\?\\'+str(path))
        path.write_bytes(b'{}')
    else:
        kwargs['publication']=replace(publication,version=replace(publication.version,raw=b'{}'))
    monkeypatch.setattr(repo,'_connect',lambda:pytest.fail('file failure must not open Task writer'))
    with pytest.raises(PayloadPublicationError):
        publish('parent', **kwargs)


def test_payload_publish_same_operation_different_content_rejected(tmp_path):
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    with pytest.raises(PayloadPublicationError, match='OPERATION_CONFLICT'):
        store.prepare_payload_publication(kwargs['publication'].identity, {'other':True},
            activation=kwargs['publication'].metadata['activation'])
    assert repo.get('parent').payload_ref=='payload.json'


def test_payload_publish_concurrent_proposals_have_one_winner(tmp_path):
    from platform_core.task_runtime.payload_publications import PayloadPublicationIdentity, PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    second=store.prepare_payload_publication(PayloadPublicationIdentity(task_id='parent',project_id='project',
        kind='TRAINING', phase='training.ready', expected_ref='payload.json', expected_parent_attempt=0,
        intent={'request_id':'other-intent'}),{'different':True},activation=kwargs['publication'].metadata['activation'])
    barrier=Barrier(2)
    def execute(publication):
        barrier.wait(timeout=10)
        try:
            return publish('parent', **{**kwargs,'publication':publication}).outcome
        except PayloadPublicationError as error:
            return error.code
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(execute,[kwargs['publication'],second]))
    assert sorted(results)==['APPLIED','PAYLOAD_PUBLICATION_EXPECTED_REF_CONFLICT']
    assert repo.get('parent').payload_ref in {kwargs['publication'].version.payload_ref,second.version.payload_ref}


@pytest.mark.parametrize('after_commit', [False,True])
def test_payload_publish_commit_failure_or_lost_ack_is_recoverable(tmp_path, monkeypatch, after_commit):
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    connect=repo._connect
    class Connection:
        def __init__(self): self.actual=connect()
        def execute(self,*args): return self.actual.execute(*args)
        def close(self): self.actual.close()
        def commit(self):
            if after_commit: self.actual.commit()
            raise sqlite3.DatabaseError('commit response failed')
    with monkeypatch.context() as patch:
        patch.setattr(repo,'_connect',Connection)
        with pytest.raises(PayloadPublicationError, match='COMMIT_FAILED'):
            publish('parent', **kwargs)
    assert repo.get('parent').payload_ref==(kwargs['publication'].version.payload_ref if after_commit else 'payload.json')
    assert store.read_payload_publication_receipt('parent',kwargs['publication'].operation_id)==kwargs['publication']
    assert publish('parent', **kwargs).outcome==('ALREADY_APPLIED' if after_commit else 'APPLIED')


@pytest.mark.parametrize('already', [False,True])
def test_payload_publish_new_worker_can_resume_but_old_worker_cannot(tmp_path, already):
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    if already: publish('parent', **kwargs)
    with repo._connect() as database:
        database.execute('UPDATE tasks SET lease_expires_at=? WHERE task_id=?',
                         ('2000-01-01T00:00:00+00:00',child.task.task_id))
    repo.release_expired()
    successor=repo.claim_next('next-worker',[TaskKind.TRAINING_PREPARE],set(),lease_seconds=120)
    assert successor is not None and successor.task.attempt==2
    if already:
        assert publish('parent', **kwargs).outcome=='ALREADY_APPLIED'
    else:
        with pytest.raises(PayloadPublicationError, match='LEASE_INVALID'):
            publish('parent', **kwargs)
    fresh={**kwargs,'child_lease_token':successor.lease_token,'child_attempt':successor.task.attempt,
           'child_worker_id':successor.worker_id}
    assert publish('parent', **fresh).outcome==('ALREADY_APPLIED' if already else 'APPLIED')


def test_payload_publish_child_reference_change_between_read_and_commit(tmp_path, monkeypatch):
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    commit=repo._commit_payload_publication
    def change_then_commit(*args):
        with repo._connect() as database:
            database.execute('UPDATE tasks SET payload_ref=? WHERE task_id=?',('changed.json',child.task.task_id))
        return commit(*args)
    monkeypatch.setattr(repo,'_commit_payload_publication',change_then_commit)
    with pytest.raises(PayloadPublicationError, match='CONTENT'):
        publish('parent', **kwargs)


@pytest.mark.parametrize('deployment', [False,True])
def test_payload_publish_legacy_activation_cannot_mutate_new_protocol_parent(tmp_path, deployment):
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path,deployment=deployment,
        phase=None if deployment else 'training.freeze')
    publish('parent', **kwargs)
    before=repo.get('parent')
    with pytest.raises(PayloadPublicationError, match='NOT_ELIGIBLE'):
        if deployment:
            repo.settle_deployment_preparation('parent',child,prepared_ref=f'scenario/prepared-{child.task.attempt}.json')
        else:
            repo.activate_prepared_training('parent',resource_key='bypass',required_capabilities=('training.ultralytics',))
    assert repo.get('parent')==before


def test_payload_publish_fenced_repository_inherits_strict_contract(tmp_path):
    from platform_core.task_runtime import FencedTaskRepository
    repo, store, child, kwargs, publish = _publication_setup(tmp_path,repository_type=FencedTaskRepository)
    assert publish('parent', **kwargs).outcome=='APPLIED'
    assert publish('parent', **kwargs).outcome=='ALREADY_APPLIED'


def test_payload_publish_busy_keeps_retryable_sqlite_error(tmp_path, monkeypatch):
    from platform_core.task_runtime.sqlite_busy import run_with_busy_retry, is_sqlite_busy
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    connect=repo._connect
    def short_connect():
        connection=connect()
        connection.execute('PRAGMA busy_timeout=1')
        return connection
    monkeypatch.setattr(repo,'_connect',short_connect)
    blocker=connect()
    try:
        blocker.execute('BEGIN IMMEDIATE')
        with pytest.raises(sqlite3.OperationalError) as error:
            run_with_busy_retry(lambda:publish('parent', **kwargs),timeout=.05)
        assert is_sqlite_busy(error.value)
    finally:
        blocker.rollback()
        blocker.close()
    assert repo.get('parent').payload_ref=='payload.json'
    assert publish('parent', **kwargs).outcome=='APPLIED'


def test_payload_publish_verification_and_hash_outside_writer(tmp_path, monkeypatch):
    from platform_core.task_runtime import payload_publications
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    active=False
    connect=repo._connect
    def trace(statement):
        nonlocal active
        if statement.startswith('BEGIN'): active=True
        if statement.startswith(('COMMIT','ROLLBACK')): active=False
    def traced_connect():
        connection=connect()
        connection.set_trace_callback(trace)
        return connection
    read_version=store.read_payload_version
    def read(*args):
        assert not active
        return read_version(*args)
    encode=payload_publications._json_bytes
    def serialize(*args):
        assert not active
        return encode(*args)
    monkeypatch.setattr(repo,'_connect',traced_connect)
    monkeypatch.setattr(store,'read_payload_version',read)
    monkeypatch.setattr(payload_publications,'_json_bytes',serialize)
    assert publish('parent', **kwargs).outcome=='APPLIED'


@pytest.mark.parametrize('activation', [
    {'stage':'queued'},
    {'resource_key':'training:auto','stage':'other','required_capabilities':['training.ultralytics']},
    {'resource_key':'training:auto','stage':'queued','required_capabilities':[]},
    {'resource_key':'training:auto','stage':'queued','required_capabilities':['training.input.ready']},
])
def test_payload_publish_ready_requires_complete_activation(tmp_path, activation):
    from platform_core.task_runtime.payload_publications import PayloadPublicationIdentity, PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    identity=PayloadPublicationIdentity(task_id='parent',project_id='project',kind='TRAINING',phase='training.ready',
        expected_ref='payload.json',expected_parent_attempt=0,intent={'request_id':'invalid-activation'})
    kwargs['publication']=store.prepare_payload_publication(identity, {}, activation=activation)
    with pytest.raises(PayloadPublicationError,match='NOT_ELIGIBLE'):
        publish('parent', **kwargs)
    assert repo.get('parent').payload_ref=='payload.json'


def test_payload_publish_gate_cannot_be_replaced_by_queued_status(tmp_path):
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    with repo._connect() as database:
        database.execute("UPDATE tasks SET required_capabilities='[]' WHERE task_id='parent'")
    with pytest.raises(PayloadPublicationError,match='NOT_ELIGIBLE'):
        publish('parent', **kwargs)


def test_payload_publish_lease_uses_aware_utc_instants(tmp_path):
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    # +08:00 representation of an expired instant must not pass string ordering.
    with repo._connect() as database:
        expired=(datetime.now(timezone.utc)-timedelta(seconds=10)).astimezone(timezone(timedelta(hours=8))).isoformat()
        database.execute('UPDATE tasks SET lease_expires_at=? WHERE task_id=?',(expired,child.task.task_id))
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    with pytest.raises(PayloadPublicationError,match='LEASE_INVALID'):
        publish('parent', **kwargs)


def test_payload_publish_freeze_then_ready_and_superseded_freeze(tmp_path):
    from platform_core.task_runtime.payload_publications import PayloadPublicationIdentity, PayloadPublicationError
    repo, store, child, kwargs, publish = _publication_setup(tmp_path,phase='training.freeze')
    frozen=publish('parent', **kwargs)
    ready=store.prepare_payload_publication(PayloadPublicationIdentity(task_id='parent',project_id='project',
        kind='TRAINING',phase='training.ready',expected_ref=frozen.task.payload_ref,
        expected_parent_attempt=frozen.task.attempt,intent={'request_id':'ready-after-freeze'}),
        {'prepared':True,'frozen':True},activation={'resource_key':'training:auto',
        'required_capabilities':['training.ultralytics'],'stage':'queued'})
    assert publish('parent', **{**kwargs,'publication':ready}).outcome=='APPLIED'
    with pytest.raises(PayloadPublicationError,match='EXPECTED_REF_CONFLICT'):
        publish('parent', **kwargs)
    assert repo.get('parent').payload_ref==ready.version.payload_ref


def test_payload_publish_unmigrated_deployment_settlement_still_works(tmp_path):
    repo, store, child, kwargs, publish = _publication_setup(tmp_path,deployment=True)
    ref=f'scenario/prepared-{child.task.attempt}.json'
    store.atomic_write_json('parent',ref,{'legacy':True})
    repo.settle_deployment_preparation('parent',child,prepared_ref=ref)
    parent=repo.get('parent')
    assert parent.payload_ref==ref
    assert parent.required_capabilities==('deployment.runtime',)
    assert parent.stage=='queued'


@pytest.mark.parametrize('child_state', ['SUCCEEDED','expired','taken_over'])
@pytest.mark.parametrize('parent_state', ['RUNNING','SUCCEEDED'])
def test_payload_publish_confirmation_has_no_write_authority(tmp_path, monkeypatch, child_state, parent_state):
    repo, store, child, kwargs, publish = _publication_setup(tmp_path)
    publish('parent', **kwargs)
    with repo._connect() as database:
        database.execute("UPDATE tasks SET status=?,attempt=attempt+1 WHERE task_id='parent'",(parent_state,))
        if child_state=='SUCCEEDED':
            database.execute("UPDATE tasks SET status='SUCCEEDED',lease_token=NULL,worker_id=NULL WHERE task_id=?",(child.task.task_id,))
        elif child_state=='expired':
            database.execute("UPDATE tasks SET lease_expires_at='2000-01-01T00:00:00Z' WHERE task_id=?",(child.task.task_id,))
        else:
            database.execute("UPDATE tasks SET attempt=attempt+1,worker_id='successor',lease_token='next' WHERE task_id=?",(child.task.task_id,))
    before=repo.get('parent')
    statements=[]
    connect=repo._connect
    def trace_connect():
        database=connect()
        database.set_trace_callback(statements.append)
        return database
    monkeypatch.setattr(repo,'_connect',trace_connect)
    assert publish('parent', **kwargs).outcome=='ALREADY_APPLIED'
    assert repo.get('parent')==before
    assert not any(sql.startswith(('UPDATE','BEGIN IMMEDIATE')) for sql in statements)

# Bounded Claim pipeline fairness and semantic recheck contracts.
def _claim_seed(repository,count,*,missing=True,tail=True):
    from platform_core.task_runtime.repository import _to_values
    template=_to_values(TaskRecord.new('seed','p',TaskKind.VIDEO_FRAMES,'payload.json','cpu',required_capabilities=('missing',) if missing else ()))
    columns=list(template)
    values=[]
    for i in range(count):
        row={**template,'task_id':f'q-{i:06d}','resource_key':f'cpu:{i}'}
        if tail and i==count-1:row['required_capabilities']='[]'
        values.append(tuple(row[key] for key in columns))
    with repository._connect() as database:
        database.executemany(f"INSERT INTO tasks ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",values)


@pytest.mark.parametrize('budget',[64,128,256])
def test_claim_pipeline_bounded_cursor_reaches_tail(tmp_path,monkeypatch,budget):
    from platform_core.task_runtime import claim_candidates
    repository=TaskRepository(tmp_path/'bounded.sqlite3')
    _claim_seed(repository,1000)
    scans=[]
    actual=claim_candidates.page
    def counted(*args,**kwargs):
        rows=actual(*args,**kwargs)
        scans.append(len(rows))
        return rows
    monkeypatch.setattr(claim_candidates,'page',counted)
    lease=None
    for cycle in range(1000):
        scans.clear()
        lease=repository.claim_next('one-worker',[TaskKind.VIDEO_FRAMES],set(),candidate_budget=budget)
        assert sum(scans)<=budget
        if lease:break
    assert lease is not None and lease.task.task_id=='q-000999'
    assert cycle<1000//max(1,budget-min(64,budget//2))+5
    # A new high-priority task is rediscovered in the window, not after wrap.
    repository.create(TaskRecord.new('urgent','p',TaskKind.VIDEO_FRAMES,'payload.json','urgent',priority=1))
    assert repository.claim_next('one-worker',[TaskKind.VIDEO_FRAMES],set(),candidate_budget=budget).task.task_id=='urgent'


def test_claim_pipeline_prepared_limit_does_not_starve_other_resources(tmp_path):
    repository=TaskRepository(tmp_path/'resources.sqlite3')
    _claim_seed(repository,128,missing=False,tail=False)
    with repository._connect() as database:
        database.execute("UPDATE tasks SET resource_key='blocked' WHERE task_id<>'q-000127'")
    active=repository.create(TaskRecord.new('active','p',TaskKind.VIDEO_FRAMES,'payload.json','blocked',priority=1))
    owner=repository.claim_next('owner',[TaskKind.VIDEO_FRAMES],set())
    assert owner.task.task_id=='active'
    for cycle in range(12):
        result=repository.claim_next('other',[TaskKind.VIDEO_FRAMES],set())
        if result:break
    assert result is not None and result.task.task_id=='q-000127'


@pytest.mark.parametrize('field,value,allowed',[
    ('progress',50,True),('current_item','display',True),('updated_at','display-timestamp',True),
    ('priority',2,False),('queue_rank',99,False),('stage','changed-admission-stage',False),
    ('attempt',1,False),('project_id','another',False),('payload_ref','changed.json',False),
])
def test_claim_pipeline_rechecks_semantics_not_display(tmp_path,field,value,allowed):
    repository=TaskRepository(tmp_path/'semantic.sqlite3')
    repository.create(TaskRecord.new('candidate','p',TaskKind.VIDEO_FRAMES,'payload.json','cpu'))
    def admit(*args):return True,None
    def prepare(candidate):
        # This connection must obtain writer while preparation runs.
        with repository._connect() as database:
            database.execute('BEGIN IMMEDIATE')
            database.execute(f'UPDATE tasks SET {field}=? WHERE task_id=?',(value,candidate['task_id']))
            database.commit()
    admit.prepare=prepare
    result=repository.claim_next('worker',[TaskKind.VIDEO_FRAMES],set(),admission=admit)
    assert (result is not None)==allowed


def test_claim_pipeline_one_recovery_and_no_cursor_advance_on_failure(tmp_path,monkeypatch):
    repository=TaskRepository(tmp_path/'transaction.sqlite3')
    _claim_seed(repository,1000,tail=False)
    actual=repository._release_expired_in
    calls=[]
    def fail(*args):
        calls.append(1)
        raise sqlite3.OperationalError('injected non-busy transaction failure')
    with monkeypatch.context() as patch:
        patch.setattr(repository,'_release_expired_in',fail)
        with pytest.raises(sqlite3.OperationalError):
            repository.claim_next('worker',[TaskKind.VIDEO_FRAMES],set())
    assert repository._claim_cursors=={}
    def recovery(*args):
        calls.append(1)
        return actual(*args)
    monkeypatch.setattr(repository,'_release_expired_in',recovery)
    repository.claim_next('worker',[TaskKind.VIDEO_FRAMES],set())
    assert len(calls)==2  # one per call, not one per candidate


def test_claim_pipeline_aligned_incremental_index_has_no_temp_sort(tmp_path):
    repository=TaskRepository(tmp_path/'plan.sqlite3')
    with repository._connect() as database:
        plan=database.execute("EXPLAIN QUERY PLAN SELECT task_id FROM tasks candidate WHERE status='QUEUED' ORDER BY priority ASC,queue_rank DESC,created_at ASC,task_id ASC LIMIT 64").fetchall()
        text=' '.join(str(row[3]) for row in plan)
        assert 'idx_task_claim_pipeline' in text
        assert 'TEMP B-TREE' not in text
        assert database.execute("SELECT 1 FROM sqlite_master WHERE name='idx_task_claim'").fetchone()


def test_preparation_helper_does_not_hide_changed_proposals(tmp_path):
    from platform_core.task_runtime.preparation_publication import publication
    from platform_core.task_runtime.payload_publications import PayloadPublicationError
    store=ArtifactStore(tmp_path/'artifacts')
    parent=TaskRecord.new('parent','p',TaskKind.TRAINING,'payload.json','cpu')
    publication(store,parent,'training.freeze',{'source_ref':'payload.json'},{'frozen':1})
    with pytest.raises(PayloadPublicationError,match='OPERATION_CONFLICT'):
        publication(store,parent,'training.freeze',{'source_ref':'payload.json'},{'frozen':2})


def test_confirm_publication_after_child_finish_needs_no_live_owner_values(tmp_path):
    repo,store,child,kwargs,publish=_publication_setup(tmp_path)
    publish('parent',**kwargs)
    repo.finish(child.task.task_id,child.lease_token,TaskStatus.SUCCEEDED)
    readonly={**kwargs,'child_lease_token':None,'child_attempt':None,'child_worker_id':None}
    assert publish('parent',**readonly).outcome=='ALREADY_APPLIED'
    repo.delete_terminal(child.task.task_id)
    assert publish('parent',**readonly).outcome=='ALREADY_APPLIED'


def test_claim_priority_window_is_scoped_to_worker_kinds(tmp_path):
    repository=TaskRepository(tmp_path/'kind-window.sqlite3')
    _claim_seed(repository,1000,missing=False,tail=False)
    with repository._connect() as database:
        database.execute("UPDATE tasks SET kind='MATERIAL_IMPORT',priority=1")
    repository.create(TaskRecord.new('video','p',TaskKind.VIDEO_FRAMES,'payload.json','cpu:video',priority=2))
    lease=repository.claim_next('video-worker',[TaskKind.VIDEO_FRAMES],set(),candidate_budget=64)
    assert lease is not None and lease.task.task_id=='video'


def test_claim_pipeline_stable_task_id_tie_and_descending_rank(tmp_path):
    repository=TaskRepository(tmp_path/'ties.sqlite3')
    _claim_seed(repository,4,missing=False,tail=False)
    with repository._connect() as database:
        database.execute("UPDATE tasks SET queue_rank=7 WHERE task_id IN ('q-000001','q-000003')")
    actual=[]
    for i in range(4):
        lease=repository.claim_next('worker',[TaskKind.VIDEO_FRAMES],set())
        actual.append(lease.task.task_id)
    assert actual==['q-000001','q-000003','q-000000','q-000002']


def test_claim_pipeline_wrap_rediscovers_changed_capability(tmp_path):
    repository=TaskRepository(tmp_path/'wrap.sqlite3')
    _claim_seed(repository,128,tail=False)
    for i in range(10):
        assert repository.claim_next('worker',[TaskKind.VIDEO_FRAMES],set(),candidate_budget=64) is None
    with repository._connect() as database:
        database.execute("UPDATE tasks SET required_capabilities='[]' WHERE task_id='q-000080'")
    for i in range(8):
        lease=repository.claim_next('worker',[TaskKind.VIDEO_FRAMES],set(),candidate_budget=64)
        if lease is not None:
            break
    assert lease is not None and lease.task.task_id=='q-000080'


def test_claim_pipeline_denied_candidates_use_one_bounded_transaction(tmp_path,monkeypatch):
    repository=TaskRepository(tmp_path/'denied.sqlite3')
    _claim_seed(repository,1000,missing=False,tail=False)
    statements=[]
    connect=repository._connect
    def traced():
        database=connect()
        database.set_trace_callback(statements.append)
        return database
    monkeypatch.setattr(repository,'_connect',traced)
    prepared=[]
    def prepare(candidate):
        with sqlite3.connect(repository.path,timeout=0.1) as database:
            database.execute('BEGIN IMMEDIATE')
            database.rollback()
        prepared.append(candidate['task_id'])
    def admission(*args):
        return False,'injected capacity denial'
    admission.prepare=prepare
    assert repository.claim_next('worker',[TaskKind.VIDEO_FRAMES],set(),admission=admission) is None
    assert len(prepared)==32
    assert sum(sql.startswith('BEGIN IMMEDIATE') for sql in statements)==1


def test_schema_6_database_migrates_execution_holds_without_data_loss(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    repository = TaskRepository(path)
    add(repository, "keep-1", "project-1", 5)
    before = repository.get("keep-1")
    with sqlite3.connect(path) as database:
        database.execute("DROP TABLE execution_resource_holds")
        database.execute("PRAGMA user_version=6")
        database.commit()
    reopened = TaskRepository(path)
    with sqlite3.connect(path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 7
        assert database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='execution_resource_holds'"
        ).fetchone()
        assert database.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    after = reopened.get("keep-1")
    assert after.task_id == before.task_id
    assert after.attempt == before.attempt
    assert after.status == before.status
    TaskRepository(path)  # repeated open is idempotent


def test_schema_6_partial_migration_retries_without_data_loss(tmp_path):
    path = tmp_path / "tasks.sqlite3"
    repository = TaskRepository(path)
    add(repository, "keep-2", "project-1", 4)
    with sqlite3.connect(path) as database:
        database.execute("PRAGMA user_version=6")
        database.commit()
    # Simulate a migration that created the new table but failed before the
    # version marker advanced. The retry must remain idempotent.
    reopened = TaskRepository(path)
    with sqlite3.connect(path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 7
        assert database.execute("SELECT COUNT(*) FROM tasks").fetchone()[0] == 1
    assert reopened.get("keep-2").task_id == "keep-2"

