from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)


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
