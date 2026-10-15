import hashlib
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_core.task_runtime import TaskKind, TaskStatus
from platform_core.training_recovery_api import (
    RECOVERY_ACTION_REVALIDATE,
    request_training_recovery,
    training_recovery_router,
    training_recovery_truth,
)


class FakeArtifacts:
    def __init__(self, failure):
        self.failure = dict(failure)

    def read_json(self, task_id, ref, default=None):
        if ref == "failure.json":
            return dict(self.failure)
        return default


class FakeRepository:
    def __init__(self, task):
        self.task = task
        self.retry_calls = []

    def get(self, task_id):
        return self.task if task_id == self.task.task_id else None

    def retry(self, task_id):
        self.retry_calls.append(task_id)
        return SimpleNamespace(
            task_id=self.task.task_id,
            project_id=self.task.project_id,
            kind=self.task.kind,
            status=TaskStatus.QUEUED,
            stage="queued",
            retry_of=self.task.task_id,
            attempt=int(self.task.attempt or 0),
        )


def failed_training_task(task_id="train-recovery", project_id="project-recovery"):
    return SimpleNamespace(
        task_id=task_id,
        project_id=project_id,
        kind=TaskKind.TRAINING,
        status=TaskStatus.FAILED,
        error="RuntimeError: final validation failed",
        current_item="最终模型验证失败",
        attempt=1,
        retry_of=None,
    )


def recovery_failure(task, checkpoint_path, sha256, **overrides):
    body = {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "failure_stage": "final_validation",
        "completion_error": "final validation worker returned non-zero",
        "completed_epochs": 100,
        "requested_epochs": 100,
        "training_loop_completed": True,
        "checkpoint_available": True,
        "checkpoints": [
            {
                "kind": "best",
                "path": str(checkpoint_path),
                "size_bytes": checkpoint_path.stat().st_size if checkpoint_path.exists() else 0,
                "sha256": sha256,
            }
        ],
        "recoverable": True,
        "recovery_action": RECOVERY_ACTION_REVALIDATE,
        "recovery_action_available": True,
    }
    body.update(overrides)
    return body


def test_completed_epochs_alone_never_create_recovery_truth(tmp_path):
    task = failed_training_task()
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    failure = recovery_failure(task, checkpoint, digest)
    failure.pop("task_id")
    failure.pop("project_id")

    truth = training_recovery_truth(task, FakeArtifacts(failure))

    assert truth["completed_epochs"] == 0
    assert truth["training_loop_completed"] is False
    assert truth["checkpoint_available"] is False
    assert truth["recoverable"] is False
    assert truth["available"] is False
    assert truth["recovery_action"] is None


def test_declared_recovery_requires_an_existing_best_checkpoint(tmp_path):
    task = failed_training_task()
    missing = tmp_path / "missing" / "best.pt"
    failure = recovery_failure(task, missing, "a" * 64)

    truth = training_recovery_truth(task, FakeArtifacts(failure))

    assert truth["training_loop_completed"] is True
    assert truth["checkpoint_available"] is False
    assert truth["recoverable"] is False
    assert truth["available"] is False


def test_recovery_action_rejects_checkpoint_hash_mismatch_without_retry(tmp_path):
    task = failed_training_task()
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"real-checkpoint")
    artifacts = FakeArtifacts(recovery_failure(task, checkpoint, "0" * 64))
    repository = FakeRepository(task)

    with pytest.raises(RuntimeError, match="no trusted recoverable checkpoint"):
        request_training_recovery(
            repository,
            artifacts,
            task.project_id,
            task.task_id,
            RECOVERY_ACTION_REVALIDATE,
        )

    assert repository.retry_calls == []


def test_recovery_action_requeues_same_task_after_checkpoint_hash_verification(tmp_path):
    task = failed_training_task()
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"trusted-checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    artifacts = FakeArtifacts(recovery_failure(task, checkpoint, digest))
    repository = FakeRepository(task)

    retried, before = request_training_recovery(
        repository,
        artifacts,
        task.project_id,
        task.task_id,
        RECOVERY_ACTION_REVALIDATE,
    )

    assert before["available"] is True
    assert before["recoverable"] is True
    assert before["checkpoint_available"] is True
    assert before["recovery_action"] == RECOVERY_ACTION_REVALIDATE
    assert repository.retry_calls == [task.task_id]
    assert retried.task_id == task.task_id
    assert retried.status is TaskStatus.QUEUED
    assert retried.retry_of == task.task_id


def test_recovery_reason_prefers_worker_root_cause_over_completion_handshake(tmp_path):
    task = failed_training_task()
    checkpoint = tmp_path / "best.pt"
    checkpoint.write_bytes(b"checkpoint")
    digest = hashlib.sha256(checkpoint.read_bytes()).hexdigest()
    failure = recovery_failure(
        task,
        checkpoint,
        digest,
        last_job_message="训练失败：RESOURCE_RUNTIME_MISMATCH: resolved workers=2; runtime workers=0",
        completion_error="job status is not done",
    )

    truth = training_recovery_truth(task, FakeArtifacts(failure))

    assert truth["failure_reason"].startswith("训练失败：RESOURCE_RUNTIME_MISMATCH")
    assert truth["failure_reason"] != "job status is not done"
    assert truth["completion_handshake"] == "job status is not done"


def test_manual_resource_failure_is_the_single_primary_failure_before_worker_start():
    task = failed_training_task()
    task.error = (
        "TRAINING_PREPARATION_FAILED: RESOURCE_MANUAL_INVALID: "
        "requested batch=128 exceeds current GPU budget"
    )

    truth = training_recovery_truth(task, FakeArtifacts({}))

    assert truth["primary_error_code"] == "RESOURCE_MANUAL_INVALID"
    assert truth["primary_stage"] == "resource_validation"
    assert truth["primary_message"] == (
        "手动资源配置无法满足当前运行预算。请降低 Batch / Workers，或改用系统推荐配置。"
    )
    assert truth["process_returncode"] is None
    assert truth["checkpoint_available"] is False
    assert task.error in truth["secondary_diagnostics"]


def test_legacy_prepare_lease_loss_is_reported_as_training_input_not_trainer_failure():
    task = failed_training_task()
    task.stage = "training_input_preparation_failed"
    task.error = "TRAINING_PREPARATION_FAILED: task execution lease was lost"

    truth = training_recovery_truth(task, FakeArtifacts({}))

    assert truth["primary_error_code"] == "TRAINING_PREPARATION_FAILED"
    assert truth["primary_stage"] == "training_input"
    assert "lease was lost" in truth["primary_message"]
    assert truth["recoverable"] is False
    assert truth["diagnosis"]["code"] == "WORKER_LEASE_LOST"


def test_data_integrity_failure_outranks_process_completion_diagnostics():
    task = failed_training_task()
    task.error = "DUPLICATE_ANNOTATION_CONFLICT: duplicate annotations disagree"
    failure = {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "failure_stage": "training_process",
        "completion_error": "job status is not done",
        "process_returncode": 1,
    }

    truth = training_recovery_truth(task, FakeArtifacts(failure))

    assert truth["primary_error_code"] == "DUPLICATE_ANNOTATION_CONFLICT"
    assert truth["primary_stage"] == "data_integrity"
    assert truth["primary_message"] == "发现重复图片存在不同标注，训练已在启动 Worker 前阻止。"
    assert truth["completion_handshake"] == "job status is not done"
    assert "job status is not done" in truth["secondary_diagnostics"]


def test_task_correlated_kernel_oom_is_confirmed_host_memory_failure():
    task = failed_training_task(task_id="train-oom")
    failure = {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "failure_stage": "training_process",
        "process_returncode": -9,
        "process_signal": "SIGKILL",
        "process_pid": 501141,
        "process_create_time": 1791904700.0,
        "completion_error": "job status is not done",
        "system_evidence": [{
            "type": "linux_kernel_oom_kill",
            "source": "linux_kernel_journal",
            "process_pid": 501141,
            "process_create_time": 1791904700.0,
            "observed_at_epoch": 1791904782.5,
            "correlated": True,
        }],
    }

    truth = training_recovery_truth(task, FakeArtifacts(failure))

    assert truth["diagnosis"]["code"] == "HOST_MEMORY_OOM"
    assert truth["diagnosis"]["certainty"] == "confirmed"
    assert truth["diagnosis"]["title"] == "训练失败：服务器内存不足"
    assert any("Linux Kernel" in item for item in truth["diagnosis"]["evidence"])
    assert truth["diagnosis"]["checkpoint_message"] == (
        "当前没有可恢复的训练断点，需要重新创建训练任务。"
    )


def test_sigkill_without_correlated_oom_evidence_keeps_cause_unknown():
    task = failed_training_task(task_id="train-sigkill")
    task.error = "TRAINING_PROCESS_FAILED: training process terminated by SIGKILL"
    failure = {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "failure_stage": "training_process",
        "process_returncode": -9,
        "process_signal": "SIGKILL",
        "process_pid": 88,
        "process_create_time": 100.0,
        "system_evidence": [{
            "type": "linux_kernel_oom_kill",
            "source": "linux_kernel_journal",
            "process_pid": 99,
            "process_create_time": 100.0,
            "correlated": True,
        }],
    }

    truth = training_recovery_truth(task, FakeArtifacts(failure))

    assert truth["diagnosis"]["code"] == "SIGKILL_CAUSE_UNKNOWN"
    assert truth["diagnosis"]["certainty"] == "unknown"
    assert truth["diagnosis"]["title"] == "训练被系统强制终止"
    assert "系统内存不足" in truth["diagnosis"]["possible_causes"]
    assert "服务器内存不足" not in truth["diagnosis"]["summary"]


def test_concurrent_kernel_oom_is_reported_but_never_confirmed_for_this_task():
    task = failed_training_task(task_id="train-concurrent-oom")
    task.error = "TRAINING_PROCESS_FAILED: training process terminated by SIGKILL"
    failure = {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "failure_stage": "training_process",
        "process_returncode": -9,
        "process_signal": "SIGKILL",
        "process_pid": 88,
        "process_create_time": 100.0,
        "system_evidence": [{
            "type": "linux_kernel_oom_concurrent",
            "source": "linux_kernel_journal",
            "process_pid": 88,
            "process_create_time": 100.0,
            "observed_at_epoch": 120.0,
            "correlated": False,
        }],
    }

    diagnosis = training_recovery_truth(task, FakeArtifacts(failure))["diagnosis"]
    assert diagnosis["code"] == "HOST_OOM_CONCURRENT_UNATTRIBUTED"
    assert diagnosis["certainty"] == "suspected"
    assert "没有证据证明" in diagnosis["summary"]


def test_cgroup_oom_requires_task_lifetime_counter_delta_not_cumulative_value():
    task = failed_training_task(task_id="train-cgroup")
    base_failure = {
        "task_id": task.task_id,
        "project_id": task.project_id,
        "failure_stage": "training_process",
        "process_returncode": -9,
        "process_signal": "SIGKILL",
        "process_pid": 55,
        "process_create_time": 100.0,
    }
    cumulative_only = {
        **base_failure,
        "system_evidence": [{
            "type": "cgroup_memory_oom",
            "source": "cgroup_memory_events",
            "process_pid": 55,
            "process_create_time": 100.0,
            "observed_at_epoch": 120.0,
            "oom_kill": 7,
            "correlated": True,
        }],
    }
    correlated_delta = {
        **base_failure,
        "system_evidence": [{
            "type": "cgroup_memory_oom",
            "source": "cgroup_memory_events",
            "process_pid": 55,
            "process_create_time": 100.0,
            "observed_at_epoch": 120.0,
            "oom_kill_delta": 1,
            "scope_identity": "worker/task/train-cgroup",
            "correlated": True,
        }],
    }

    assert training_recovery_truth(task, FakeArtifacts(cumulative_only))["diagnosis"]["code"] == "SIGKILL_CAUSE_UNKNOWN"
    assert training_recovery_truth(task, FakeArtifacts(correlated_delta))["diagnosis"]["code"] == "CGROUP_MEMORY_OOM"


def test_explicit_cuda_oom_is_not_misclassified_as_host_memory_oom():
    task = failed_training_task(task_id="train-cuda-oom")
    task.error = "torch.cuda.OutOfMemoryError: CUDA out of memory while allocating tensor"

    truth = training_recovery_truth(task, FakeArtifacts({}))

    assert truth["diagnosis"]["code"] == "GPU_MEMORY_OOM"
    assert truth["diagnosis"]["certainty"] == "confirmed"
    assert truth["diagnosis"]["title"] == "训练失败：GPU 显存不足"


@pytest.mark.parametrize(
    ("error", "expected_code"),
    [
        ("WORKER_LEASE_LOST: task execution lease was lost", "WORKER_LEASE_LOST"),
        ("TRAINING_CANCELLED: cancelled by user", "TRAINING_CANCELLED"),
    ],
)
def test_worker_lease_and_cancellation_never_become_oom(error, expected_code):
    task = failed_training_task()
    task.error = error

    truth = training_recovery_truth(task, FakeArtifacts({}))

    assert truth["diagnosis"]["code"] == expected_code
    assert "MEMORY_OOM" not in truth["diagnosis"]["code"]


def test_memory_symptom_without_system_correlation_is_only_suspected():
    task = failed_training_task()
    task.error = "MemoryError: Cannot allocate memory"

    truth = training_recovery_truth(task, FakeArtifacts({}))

    assert truth["diagnosis"]["code"] == "HOST_MEMORY_PRESSURE_SUSPECTED"
    assert truth["diagnosis"]["certainty"] == "suspected"
    assert "疑似" in truth["diagnosis"]["title"]


def test_public_diagnosis_and_technical_diagnostics_are_redacted():
    task = failed_training_task()
    task.error = (
        r"TRAINING_PROCESS_FAILED: C:\\srv\\private\\dataset.yaml "
        "token=super-secret Bearer abc.def.ghi"
    )

    truth = training_recovery_truth(task, FakeArtifacts({}))
    public_text = repr({
        "diagnosis": truth["diagnosis"],
        "failure_reason": truth["failure_reason"],
        "secondary_diagnostics": truth["secondary_diagnostics"],
    })

    assert "super-secret" not in public_text
    assert "abc.def.ghi" not in public_text
    assert r"C:\\srv\\private" not in public_text
    assert "[REDACTED]" in public_text


def test_training_input_issues_endpoint_reads_bounded_persisted_pages():
    task = failed_training_task()
    task_repository = FakeRepository(task)

    class InputIssueArtifacts:
        values = {
            "input-compatibility/manifest.json": {
                "schema_version": 1,
                "issue_count": 2,
                "issue_counts": {"partial_review_scope": 2},
                "required_label_codes": ["fire", "smoke"],
                "material_revision": 8,
                "annotation_revision": 5,
                "page_size": 100,
                "pages": [{
                    "page": 1,
                    "ref": "input-compatibility/pages/000001.json",
                }],
            },
            "input-compatibility/pages/000001.json": [
                {"image_id": "one", "missing_label_codes": ["smoke"]},
                {"image_id": "two", "missing_label_codes": ["smoke"]},
            ],
        }

        def read_json(self, _task_id, ref, default=None):
            return self.values.get(ref, default)

    app = FastAPI()
    app.include_router(training_recovery_router(
        lambda _project_id: {"id": task.project_id},
        lambda: task_repository,
        lambda: InputIssueArtifacts(),
    ))
    client = TestClient(app)

    response = client.get(
        f"/api/v62/projects/{task.project_id}/training-tasks/"
        f"{task.task_id}/input-issues?page=2&limit=1"
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["issue_count"] == 2
    assert body["required_label_codes"] == ["fire", "smoke"]
    assert body["items"] == [
        {
            "image_id": "two",
            "missing_label_codes": ["smoke"],
            "thumbnail_url": (
                f"/api/v62/projects/{task.project_id}/training-materials/two/thumbnail"
            ),
            "content_url": (
                f"/api/v61/projects/{task.project_id}/materials/two/content"
            ),
        }
    ]
    assert body["page"] == 2
    assert body["total_pages"] == 2


def test_training_input_issues_endpoint_returns_404_without_artifact():
    task = failed_training_task()
    app = FastAPI()
    app.include_router(training_recovery_router(
        lambda _project_id: {"id": task.project_id},
        lambda: FakeRepository(task),
        lambda: FakeArtifacts({}),
    ))
    response = TestClient(app).get(
        f"/api/v62/projects/{task.project_id}/training-tasks/"
        f"{task.task_id}/input-issues"
    )

    assert response.status_code == 404
