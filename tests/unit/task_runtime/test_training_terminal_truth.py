from platform_core.task_runtime import (
    ArtifactStore,
    Scheduler,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)


class TrainingGPU:
    def refresh(self):
        return None

    def admit(self, database, task, worker_id, token, expires_at, now):
        return True, None

    def assignment(self, lease):
        return {
            "requested_device": "auto",
            "assigned_device": "cuda:0",
            "gpu_uuid": "GPU-terminal-truth",
            "gpu_index": 0,
            "worker_id": lease.worker_id,
            "lease_token": lease.lease_token,
        }


def training_task(task_id: str) -> TaskRecord:
    return TaskRecord.new(
        task_id,
        "project-terminal-truth",
        TaskKind.TRAINING,
        "payload.json",
        "training:auto",
        required_capabilities=("training.ultralytics",),
    )


def scheduler_for(tmp_path, task_id, handler):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    repository.create(training_task(task_id))
    artifacts.atomic_write_json(task_id, "payload.json", {})
    scheduler = Scheduler(
        repository,
        artifacts,
        "training-worker-terminal-truth",
        {TaskKind.TRAINING: handler},
        {"training.ultralytics"},
        gpu_resources=TrainingGPU(),
    )
    return repository, artifacts, scheduler


def test_successful_training_persists_terminal_completion_text(tmp_path):
    class SuccessHandler:
        def run(self, context):
            context.heartbeat(progress=92, stage="finalizing_commit", current_item="正在归档已验证产物")
            return TaskStatus.SUCCEEDED, "result.json"

        recover = run

    repository, _, scheduler = scheduler_for(tmp_path, "train-success", SuccessHandler())

    assert scheduler.run_once() is True
    task = repository.get("train-success")
    assert task.status is TaskStatus.SUCCEEDED
    assert task.progress == 100.0
    assert task.current_item == "训练完成，结果已归档"


def test_training_failure_prefers_durable_failure_evidence_for_terminal_detail(tmp_path):
    class FailedValidationHandler:
        def run(self, context):
            context.artifacts.atomic_write_json(
                context.task.task_id,
                "failure.json",
                {
                    "failure_stage": "final_validation",
                    "completion_error": "best.pt 独立验证失败：checkpoint checksum mismatch",
                    "last_job_message": "训练已结束，正在最终验证",
                    "recoverable": True,
                    "recovery_action": "revalidate_checkpoint",
                },
            )
            raise RuntimeError("final validation worker returned non-zero")

        recover = run

    repository, _, scheduler = scheduler_for(tmp_path, "train-validation-failed", FailedValidationHandler())

    assert scheduler.run_once() is True
    task = repository.get("train-validation-failed")
    assert task.status is TaskStatus.FAILED
    assert task.current_item == "best.pt 独立验证失败：checkpoint checksum mismatch"
    assert task.error == "RuntimeError: final validation worker returned non-zero"


def test_environment_block_keeps_exact_backend_reason(tmp_path):
    class MissingEnvironmentHandler:
        def run(self, context):
            raise EnvironmentError("训练环境缺少 ultralytics")

        recover = run

    repository, _, scheduler = scheduler_for(tmp_path, "train-env-blocked", MissingEnvironmentHandler())

    assert scheduler.run_once() is True
    task = repository.get("train-env-blocked")
    assert task.status is TaskStatus.BLOCKED_BY_ENVIRONMENT
    assert task.current_item == "OSError: 训练环境缺少 ultralytics"
    assert task.error == "OSError: 训练环境缺少 ultralytics"
