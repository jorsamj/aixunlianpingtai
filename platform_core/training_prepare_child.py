"""Single durable TRAINING_PREPARE child constructor for Web and Worker repair."""
from __future__ import annotations

from .task_runtime import TaskKind, TaskRecord


def ensure_training_prepare_child(repository, artifacts, project_id: str,
                                  task_id: str, prepare_task_id: str, priority: int) -> TaskRecord:
    if prepare_task_id != f"trainprep_{task_id}":
        raise ValueError("训练准备任务身份不匹配")
    expected = {"schema_version": 2, "training_task_id": task_id, "project_id": project_id}
    existing = repository.get(prepare_task_id)
    if existing is not None:
        if (existing.project_id != project_id
                or existing.kind is not TaskKind.TRAINING_PREPARE
                or artifacts.read_json(prepare_task_id, existing.payload_ref, default={}) != expected):
            raise ValueError("训练准备任务已由其他请求占用")
        return existing
    orphan = artifacts.read_json(prepare_task_id, "payload.json", default=None)
    if orphan is not None and orphan != expected:
        raise ValueError("训练准备任务残留载荷与当前父任务冲突")
    if orphan is None:
        artifacts.atomic_write_json(prepare_task_id, "payload.json", expected)
    return repository.create(TaskRecord.new(
        prepare_task_id, project_id, TaskKind.TRAINING_PREPARE,
        "payload.json", f"training-prepare:{project_id}",
        priority=int(priority), required_capabilities=("training.prepare",),
    ))
