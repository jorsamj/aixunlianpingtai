from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)
from platform_core.task_runtime.process_control import ProcessIdentity
from platform_core.task_runtime.worker import WorkerContext


class RecordingHandler:
    def __init__(self):
        self.calls = []

    def run(self, context):
        self.calls.append(("run", context.task.task_id))
        context.save_checkpoint({"committed": 4})
        context.artifacts.atomic_write_json(
            context.task.task_id,
            "result.json",
            {"committed": 4},
        )
        return TaskStatus.SUCCEEDED, "result.json"

    def recover(self, context):
        self.calls.append(("recover", context.load_checkpoint()["committed"]))
        return TaskStatus.SUCCEEDED, "result.json"


def test_scheduler_claims_without_api_request_and_finishes(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task = TaskRecord.new(
        "video-1",
        "project-1",
        TaskKind.VIDEO_FRAMES,
        "payload.json",
        "cpu:video",
        4,
        ("opencv",),
    )
    repository.create(task)
    artifacts.atomic_write_json("video-1", "payload.json", {"video": "inputs/a.mp4"})
    handler = RecordingHandler()
    scheduler = Scheduler(
        repository,
        artifacts,
        "worker-1",
        {TaskKind.VIDEO_FRAMES: handler},
        {"opencv"},
    )

    assert scheduler.run_once() is True
    assert repository.get("video-1").status is TaskStatus.SUCCEEDED
    assert handler.calls == [("run", "video-1")]


def test_expired_attempt_uses_recover(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    repository.create(
        TaskRecord.new(
            "video-2",
            "project-1",
            TaskKind.VIDEO_FRAMES,
            "payload.json",
            "cpu:video",
        )
    )
    artifacts.atomic_write_json(
        "video-2",
        "checkpoints/worker.json",
        {"committed": 9},
    )
    assert repository.claim_next("dead", [TaskKind.VIDEO_FRAMES], set(), 1) is not None
    repository.release_expired("2999-01-01T00:00:00+00:00")

    handler = RecordingHandler()
    scheduler = Scheduler(
        repository,
        artifacts,
        "worker-2",
        {TaskKind.VIDEO_FRAMES: handler},
        set(),
    )
    assert scheduler.run_once() is True
    assert handler.calls == [("recover", 9)]


def test_scheduler_turns_cancel_request_into_cancelled(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    repository.create(
        TaskRecord.new(
            "video-3",
            "project-1",
            TaskKind.VIDEO_FRAMES,
            "payload.json",
            "cpu:video",
        )
    )

    class CancellingHandler(RecordingHandler):
        def run(self, context):
            context.repository.request_cancel(context.task.task_id)
            return TaskStatus.SUCCEEDED, "must-not-be-kept.json"

    scheduler = Scheduler(
        repository,
        artifacts,
        "worker-3",
        {TaskKind.VIDEO_FRAMES: CancellingHandler()},
        set(),
    )
    scheduler.run_once()
    task = repository.get("video-3")
    assert task.status is TaskStatus.CANCELLED
    assert task.result_ref is None


def test_cancel_interrupt_does_not_become_failed(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    repository.create(
        TaskRecord.new(
            "video-4",
            "project-1",
            TaskKind.VIDEO_FRAMES,
            "payload.json",
            "cpu:video",
        )
    )

    class InterruptedHandler(RecordingHandler):
        def run(self, context):
            context.repository.request_cancel(context.task.task_id)
            raise InterruptedError("cancelled at frame boundary")

    Scheduler(
        repository,
        artifacts,
        "worker-4",
        {TaskKind.VIDEO_FRAMES: InterruptedHandler()},
        set(),
    ).run_once()
    task = repository.get("video-4")
    assert task.status is TaskStatus.CANCELLED
    assert task.error is None


def test_cancelled_training_releases_reservation_and_next_task_is_claimed(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    for task_id in ("train-a", "train-b"):
        repository.create(
            TaskRecord.new(
                task_id,
                "project-1",
                TaskKind.TRAINING,
                "payload.json",
                "training:auto",
                required_capabilities=("training.ultralytics",),
            )
        )
        artifacts.atomic_write_json(task_id, "payload.json", {})

    class ReservationGPU:
        def refresh(self):
            return None

        def admit(self, database, task, worker_id, token, expires_at, now):
            database.execute(
                """
                INSERT INTO gpu_reservations(
                    task_id,gpu_uuid,gpu_index,reserved_bytes,estimated_bytes,
                    worker_id,worker_slot,lease_token,policy,share_eligible,
                    created_at,heartbeat_at,expires_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    task["task_id"], "GPU-test", 0, 1, 1, worker_id, "slot-one",
                    token, "exclusive", 0, now, now, expires_at,
                ),
            )
            return True, None

        def assignment(self, lease):
            return {
                "requested_device": "auto",
                "assigned_device": "cuda:0",
                "gpu_uuid": "GPU-test",
                "gpu_index": 0,
                "worker_id": lease.worker_id,
                "lease_token": lease.lease_token,
            }

    calls = []

    class TrainingHandler(RecordingHandler):
        def run(self, context):
            calls.append(context.task.task_id)
            if context.task.task_id == "train-a":
                context.repository.request_cancel(context.task.task_id)
                raise RuntimeError("terminated child exited with code -15")
            return TaskStatus.SUCCEEDED, "result.json"

    scheduler = Scheduler(
        repository,
        artifacts,
        "training-worker",
        {TaskKind.TRAINING: TrainingHandler()},
        {"training.ultralytics"},
        gpu_resources=ReservationGPU(),
    )

    assert scheduler.run_once() is True
    cancelled = repository.get("train-a")
    assert cancelled.status is TaskStatus.CANCELLED
    assert cancelled.worker_id is None
    assert cancelled.lease_expires_at is None
    with repository._connect() as database:
        assert database.execute(
            "SELECT COUNT(*) FROM gpu_reservations WHERE task_id='train-a'"
        ).fetchone()[0] == 0

    assert scheduler.run_once() is True
    assert repository.get("train-b").status is TaskStatus.SUCCEEDED
    assert calls == ["train-a", "train-b"]


def test_cancel_does_not_release_gpu_when_bound_process_cleanup_is_unverified(tmp_path, monkeypatch):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    repository.create(
        TaskRecord.new(
            "train-unsafe-cleanup",
            "project-1",
            TaskKind.TRAINING,
            "payload.json",
            "training:auto",
            required_capabilities=("training.ultralytics",),
        )
    )
    artifacts.atomic_write_json("train-unsafe-cleanup", "payload.json", {})

    class ReservationGPU:
        def refresh(self):
            return None

        def admit(self, database, task, worker_id, token, expires_at, now):
            database.execute(
                """
                INSERT INTO gpu_reservations(
                    task_id,gpu_uuid,gpu_index,reserved_bytes,estimated_bytes,
                    worker_id,worker_slot,lease_token,policy,share_eligible,
                    created_at,heartbeat_at,expires_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    task["task_id"], "GPU-test", 0, 1, 1, worker_id, "slot-one",
                    token, "exclusive", 0, now, now, expires_at,
                ),
            )
            return True, None

        def assignment(self, lease):
            return {
                "requested_device": "auto",
                "assigned_device": "cuda:0",
                "gpu_uuid": "GPU-test",
                "gpu_index": 0,
                "worker_id": lease.worker_id,
                "lease_token": lease.lease_token,
            }

    class CancellingHandler(RecordingHandler):
        def run(self, context):
            context.bind_process(ProcessIdentity(12345, 1.0, "command-hash"))
            context.repository.request_cancel(context.task.task_id)
            raise RuntimeError("cleanup could not be verified")

    monkeypatch.setattr(WorkerContext, "terminate_bound_process", lambda self, timeout=5.0: False)
    scheduler = Scheduler(
        repository,
        artifacts,
        "training-worker",
        {TaskKind.TRAINING: CancellingHandler()},
        {"training.ultralytics"},
        gpu_resources=ReservationGPU(),
    )

    assert scheduler.run_once() is True
    held = repository.get("train-unsafe-cleanup")
    assert held.status is TaskStatus.CANCEL_REQUESTED
    assert held.lease_expires_at is not None
    with repository._connect() as database:
        assert database.execute(
            "SELECT COUNT(*) FROM gpu_reservations WHERE task_id='train-unsafe-cleanup'"
        ).fetchone()[0] == 1


def test_failed_task_releases_resource_before_next_scheduler_claim(tmp_path):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    for task_id in ("first", "next"):
        repository.create(
            TaskRecord.new(task_id, "project-1", TaskKind.VIDEO_FRAMES, "payload.json", "cpu:video")
        )

    calls = []

    class FailThenSucceed(RecordingHandler):
        def run(self, context):
            calls.append(context.task.task_id)
            if context.task.task_id == "first":
                raise RuntimeError("expected failure")
            return TaskStatus.SUCCEEDED, "result.json"

    scheduler = Scheduler(
        repository,
        artifacts,
        "worker",
        {TaskKind.VIDEO_FRAMES: FailThenSucceed()},
        set(),
    )

    assert scheduler.run_once() is True
    assert repository.get("first").status is TaskStatus.FAILED
    assert scheduler.run_once() is True
    assert repository.get("next").status is TaskStatus.SUCCEEDED
    assert calls == ["first", "next"]
