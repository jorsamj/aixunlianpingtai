from __future__ import annotations

import json

from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository


def test_training_event_rows_emit_only_active_training_truth(tmp_path):
    import app as app_module

    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    training = repository.create(TaskRecord.new(
        "train-stream",
        "project-1",
        TaskKind.TRAINING,
        "payload.json",
        "training:cpu",
        required_capabilities=("training.ultralytics",),
    ))
    repository.create(TaskRecord.new(
        "material-stream",
        "project-1",
        TaskKind.MATERIAL_IMPORT,
        "payload.json",
        "material:cpu",
    ))

    lease = repository.claim_next(
        "training-worker",
        [TaskKind.TRAINING],
        {"training.ultralytics"},
        lease_seconds=60,
    )
    assert lease is not None
    repository.heartbeat(
        training.task_id,
        lease.lease_token,
        progress=37.5,
        stage="training",
        current_item="Epoch 11/30 · Batch 20/100",
    )

    rows = app_module._training_event_rows("project-1", repository)

    assert [row["task_id"] for row in rows] == ["train-stream"]
    assert rows[0]["status"] == "RUNNING"
    assert rows[0]["progress_percent"] == 37.5
    assert rows[0]["current_item"] == "Epoch 11/30 · Batch 20/100"


def test_training_event_signature_changes_when_live_progress_changes():
    import app as app_module

    first = {
        "task_id": "train-stream",
        "status": "RUNNING",
        "persisted_status": "RUNNING",
        "phase": "training",
        "progress_percent": 37.5,
        "current_item": "Epoch 11/30",
        "updated_at": "2026-09-22T00:00:00+00:00",
    }
    second = {**first, "progress_percent": 38.25, "updated_at": "2026-09-22T00:00:01+00:00"}

    assert app_module._training_event_signature(first) != app_module._training_event_signature(second)


def test_training_sse_message_is_named_and_json_round_trippable():
    import app as app_module

    row = {
        "task_id": "train-stream",
        "status": "RUNNING",
        "progress_percent": 42.25,
        "current_item": "Epoch 12/30",
    }
    message = app_module._training_sse_message(row)

    assert message.startswith("event: training.task\ndata: ")
    data_line = next(line for line in message.splitlines() if line.startswith("data: "))
    assert json.loads(data_line.removeprefix("data: ")) == row
