from dataclasses import replace

from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus


def test_public_status_and_kind_values_are_locked():
    assert [item.value for item in TaskStatus] == [
        "QUEUED",
        "RUNNING",
        "AWAITING_CONFIRMATION",
        "PARTIAL_SUCCESS",
        "SUCCEEDED",
        "CANCEL_REQUESTED",
        "CANCELLED",
        "FAILED",
        "BLOCKED_BY_ENVIRONMENT",
        "BLOCKED_BY_HARDWARE",
    ]
    assert [item.value for item in TaskKind] == [
        "MATERIAL_IMPORT",
        "CLEANING",
        "AI_ANNOTATION",
        "VIDEO_FRAMES",
        "TRAINING",
        "MODEL_CONVERSION",
        "DEPLOYMENT_TEST",
    ]


def test_task_record_normalizes_priority_and_keeps_review_metadata():
    record = TaskRecord.new(
        task_id="task-1",
        project_id="project-1",
        kind=TaskKind.VIDEO_FRAMES,
        payload_ref="payload.json",
        resource_key="cpu:video",
        priority=0,
        required_capabilities=("opencv", "opencv"),
    )

    assert record.priority == 1
    assert record.required_capabilities == ("opencv",)
    assert record.retry_of is None
    assert record.finished_at is None
    assert replace(record, status=TaskStatus.RUNNING).priority == 1
