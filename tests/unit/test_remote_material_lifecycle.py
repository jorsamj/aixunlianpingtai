from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from platform_core.remote_material_lifecycle import (
    REMOTE_MATERIAL_CLEANUP_REF,
    RemoteExecutionStagingLifecycle,
    RemoteMaterialStagingLifecycle,
    remote_execution_staging_refs,
)
from platform_core.storage.models import ObjectMetadata
from platform_core.task_runtime import (
    ArtifactStore,
    TaskKind,
    TaskRecord,
    TaskRepository,
    TaskStatus,
)


class FakeProvider:
    def __init__(self):
        self.objects = {}
        self.deleted = []

    def put(self, key, data: bytes, sha256: str):
        self.objects[str(key)] = {
            "data": bytes(data),
            "sha256": str(sha256),
        }

    def exists(self, key):
        return str(key) in self.objects

    def stat(self, key):
        item = self.objects[str(key)]
        return ObjectMetadata(
            key=str(key),
            size_bytes=len(item["data"]),
            content_type="application/zip",
            sha256=item["sha256"],
        )

    def delete(self, key):
        self.deleted.append(str(key))
        self.objects.pop(str(key), None)


def payload(task_id="material-task", project_id="project-1"):
    prefix = f"remote-execution/{project_id}/{task_id}"
    return {
        "remote_execution": {
            "version": 1,
            "task_kind": "MATERIAL_IMPORT",
            "transport": "object-storage-v1",
            "material_import": {
                "schema_version": 1,
                "mode": "zip_scan",
                "import_format": "yolo",
                "target": {
                    "storage_source_id": "s3-main",
                    "storage_type": "s3",
                    "target_prefix": "formal/materials",
                },
                "input": {
                    "storage_source_id": "s3-main",
                    "object_key": f"{prefix}/material-input/source.zip",
                    "file_name": "source.zip",
                    "size_bytes": 5,
                    "sha256": "a" * 64,
                    "content_type": "application/zip",
                },
                "output": {
                    "storage_source_id": "s3-main",
                    "object_key": f"{prefix}/material-review/review.zip",
                    "file_name": "material-review.zip",
                    "content_type": "application/zip",
                },
            },
        }
    }


def task(status=TaskStatus.RUNNING, *, finished_at=None, attempt=1):
    return SimpleNamespace(
        task_id="material-task",
        project_id="project-1",
        kind=TaskKind.MATERIAL_IMPORT,
        status=status,
        payload_ref="request.json",
        finished_at=finished_at,
        updated_at=finished_at or datetime.now(timezone.utc).isoformat(),
        attempt=attempt,
    )


def test_server_confirmed_cleanup_deletes_only_exact_task_owned_staging(tmp_path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    provider = FakeProvider()
    input_key = "remote-execution/project-1/material-task/material-input/source.zip"
    review_key = (
        "remote-execution/project-1/material-task/material-review/"
        "generation-1/material-review.zip"
    )
    formal_key = "formal/materials/images/train/image.jpg"
    provider.put(input_key, b"input", "a" * 64)
    provider.put(review_key, b"review", "b" * 64)
    provider.put(formal_key, b"formal", "c" * 64)

    lifecycle = RemoteMaterialStagingLifecycle(
        None,
        artifacts,
        lambda _project_id, _ref: provider,
    )
    recorded = lifecycle.record_confirmed(
        task(),
        payload(),
        {
            "execution_generation": 1,
            "sha256": "b" * 64,
            "size_bytes": len(b"review"),
        },
        {
            "result": {
                "output_storage": {
                    "storage_source_id": "s3-main",
                    "object_key": review_key,
                    "file_name": "material-review.zip",
                    "content_type": "application/zip",
                },
                "output_sha256": "b" * 64,
                "output_size_bytes": len(b"review"),
            }
        },
    )

    # Commit-time recording must not delete before the outer result state is
    # durable; the existing storage-Worker sweep performs the deletion later.
    assert recorded["status"] == "RECORDED"
    assert provider.exists(input_key) is True
    assert provider.exists(review_key) is True
    outcome = lifecycle.cleanup_task(task(), force=True)
    assert outcome["status"] == "COMPLETE"
    assert provider.exists(input_key) is False
    assert provider.exists(review_key) is False
    assert provider.exists(formal_key) is True
    assert sorted(provider.deleted) == sorted([input_key, review_key])

    ledger = artifacts.read_json("material-task", REMOTE_MATERIAL_CLEANUP_REF)
    assert ledger["complete"] is True
    assert {row["role"] for row in ledger["objects"]} == {"input", "review"}
    assert all(row["status"] == "DELETED" for row in ledger["objects"])


def test_cleanup_refuses_to_delete_changed_staging_object(tmp_path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    provider = FakeProvider()
    input_key = "remote-execution/project-1/material-task/material-input/source.zip"
    provider.put(input_key, b"changed", "d" * 64)
    lifecycle = RemoteMaterialStagingLifecycle(
        None,
        artifacts,
        lambda _project_id, _ref: provider,
    )

    recorded = lifecycle.record_confirmed(
        task(),
        payload(),
        {
            "execution_generation": 1,
            "sha256": "b" * 64,
            "size_bytes": len(b"review"),
        },
        {
            "result": {
                "output_storage": {
                    "storage_source_id": "s3-main",
                    "object_key": (
                        "remote-execution/project-1/material-task/material-review/"
                        "generation-1/material-review.zip"
                    ),
                    "file_name": "material-review.zip",
                },
                "output_sha256": "b" * 64,
                "output_size_bytes": len(b"review"),
            }
        },
    )
    assert recorded["status"] == "RECORDED"
    outcome = lifecycle.cleanup_task(task(), force=True)
    assert outcome["status"] == "INCOMPLETE"
    assert provider.exists(input_key) is True
    assert input_key not in provider.deleted
    ledger = artifacts.read_json("material-task", REMOTE_MATERIAL_CLEANUP_REF)
    input_row = next(row for row in ledger["objects"] if row["role"] == "input")
    assert input_row["status"] == "CONFLICT"
    assert "size/SHA256" in input_row["last_error"]


def test_terminal_orphan_respects_retention_then_deletes_exact_generation_refs(tmp_path):
    runtime = tmp_path / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    provider = FakeProvider()
    task_id = "material-task"
    request = payload()
    artifacts.atomic_write_json(task_id, "request.json", request)
    repository.create(
        TaskRecord.new(
            task_id,
            "project-1",
            TaskKind.MATERIAL_IMPORT,
            "request.json",
            "material-import:agent:s3-main",
            required_capabilities=("agent.remote",),
        ),
        artifacts=artifacts,
    )
    lease = repository.claim_next(
        "agent",
        (TaskKind.MATERIAL_IMPORT,),
        {"agent.remote"},
    )
    assert lease is not None
    input_key = "remote-execution/project-1/material-task/material-input/source.zip"
    review_key = (
        "remote-execution/project-1/material-task/material-review/"
        "generation-1/material-review.zip"
    )
    provider.put(input_key, b"input", "a" * 64)
    provider.put(review_key, b"review", "b" * 64)
    artifacts.atomic_write_json(
        task_id,
        "remote-results/1/upload.json",
        {
            "execution_generation": 1,
            "storage_ref": {
                "storage_source_id": "s3-main",
                "object_key": review_key,
                "file_name": "material-review.zip",
            },
            "sha256": "b" * 64,
            "size_bytes": len(b"review"),
        },
    )
    failed = repository.finish(
        task_id,
        lease.lease_token,
        TaskStatus.FAILED,
        error="agent failed after upload",
    )
    assert failed.status is TaskStatus.FAILED
    finished = datetime.fromisoformat(failed.finished_at)

    lifecycle = RemoteMaterialStagingLifecycle(
        repository,
        artifacts,
        lambda _project_id, _ref: provider,
        retention_seconds=3600,
    )
    early = lifecycle.maintain(now=finished + timedelta(minutes=30))
    assert early["retained"] == 1
    assert provider.exists(input_key) is True
    assert provider.exists(review_key) is True

    late = lifecycle.maintain(now=finished + timedelta(hours=2))
    assert late["complete"] == 1
    assert provider.exists(input_key) is False
    assert provider.exists(review_key) is False


def test_cleanup_rejects_non_owned_object_key_even_if_written_into_payload(tmp_path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    provider = FakeProvider()
    unsafe = payload()
    unsafe["remote_execution"]["material_import"]["input"]["object_key"] = (
        "formal/materials/do-not-delete.zip"
    )
    lifecycle = RemoteMaterialStagingLifecycle(
        None,
        artifacts,
        lambda _project_id, _ref: provider,
    )

    try:
        lifecycle.record_confirmed(
            task(),
            unsafe,
            {"execution_generation": 1, "sha256": "b" * 64, "size_bytes": 6},
            {
                "result": {
                    "output_storage": {
                        "storage_source_id": "s3-main",
                        "object_key": (
                            "remote-execution/project-1/material-task/material-review/"
                            "generation-1/material-review.zip"
                        ),
                    },
                    "output_sha256": "b" * 64,
                    "output_size_bytes": 6,
                }
            },
        )
    except ValueError as error:
        assert "task-owned" in str(error)
    else:
        raise AssertionError("non-owned object key was accepted for staging cleanup")



def _remote_task(kind, task_id, status=TaskStatus.RUNNING, *, finished_at=None, attempt=1):
    return SimpleNamespace(
        task_id=task_id,
        project_id="project-1",
        kind=kind,
        status=status,
        payload_ref="request.json",
        finished_at=finished_at,
        updated_at=finished_at or datetime.now(timezone.utc).isoformat(),
        attempt=attempt,
    )


def _result_payload(kind, task_id):
    section_name = {
        TaskKind.MODEL_CONVERSION: "conversion",
        TaskKind.TRAINING: "training",
        TaskKind.MATERIAL_BATCH: "cleaning",
    }[kind]
    section = {
        "output": {
            "storage_source_id": "s3-main",
            "object_key": f"remote-execution/project-1/{task_id}/output/result.bin",
            "file_name": "result.bin",
        }
    }
    if kind is TaskKind.MODEL_CONVERSION:
        section["source"] = {
            "storage_source_id": "s3-main",
            "object_key": "changlian-ai/artifacts/project-1/a1/v1/original/model.pt",
            "sha256": "c" * 64,
            "size_bytes": 9,
        }
    elif kind is TaskKind.TRAINING:
        section["bundle"] = {
            "storage_source_id": "s3-main",
            "object_key": "remote-training/bundles/project-1/snapshot/bundle.zip",
            "sha256": "c" * 64,
            "size_bytes": 9,
        }
        section["model"] = {
            "type": "object",
            "storage_source_id": "s3-main",
            "object_key": "changlian-ai/artifacts/project-1/a1/v1/training/model.pt",
            "sha256": "d" * 64,
            "size_bytes": 10,
        }
    return {
        "remote_execution": {
            "version": 1,
            "task_kind": kind.value,
            "transport": "object-storage-v1",
            section_name: section,
        }
    }


def test_conversion_terminal_gc_uses_exact_upload_state_and_keeps_canonical_source(tmp_path):
    runtime = tmp_path / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    provider = FakeProvider()
    task_id = "convert-task"
    request = _result_payload(TaskKind.MODEL_CONVERSION, task_id)
    artifacts.atomic_write_json(task_id, "request.json", request)
    repository.create(
        TaskRecord.new(
            task_id,
            "project-1",
            TaskKind.MODEL_CONVERSION,
            "request.json",
            "conversion:agent",
            required_capabilities=("agent.remote",),
        ),
        artifacts=artifacts,
    )
    lease = repository.claim_next(
        "agent",
        (TaskKind.MODEL_CONVERSION,),
        {"agent.remote"},
    )
    assert lease is not None
    output_key = "remote-execution/project-1/convert-task/output/generation-1/result.bin"
    canonical_key = "changlian-ai/artifacts/project-1/a1/v1/original/model.pt"
    provider.put(output_key, b"output!", "e" * 64)
    provider.put(canonical_key, b"canonical", "c" * 64)
    artifacts.atomic_write_json(
        task_id,
        "remote-results/1/upload.json",
        {
            "execution_generation": 1,
            "storage_ref": {"storage_source_id": "s3-main", "object_key": output_key},
            "sha256": "e" * 64,
            "size_bytes": len(b"output!"),
        },
    )
    failed = repository.finish(
        task_id,
        lease.lease_token,
        TaskStatus.FAILED,
        error="agent failed after upload",
    )
    finished = datetime.fromisoformat(failed.finished_at)

    lifecycle = RemoteExecutionStagingLifecycle(
        repository,
        artifacts,
        lambda _project_id, _ref: provider,
        retention_seconds=3600,
    )
    early = lifecycle.maintain(now=finished + timedelta(minutes=30))
    assert early["retained"] == 1
    assert provider.exists(output_key) is True
    late = lifecycle.maintain(now=finished + timedelta(hours=2))
    assert late["complete"] == 1
    assert provider.exists(output_key) is False
    assert provider.exists(canonical_key) is True
    assert canonical_key not in provider.deleted


@pytest.mark.parametrize(
    "kind",
    [TaskKind.MODEL_CONVERSION, TaskKind.TRAINING, TaskKind.MATERIAL_BATCH],
)
def test_confirmed_remote_result_records_only_task_owned_result(kind, tmp_path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task_id = f"{kind.value.lower()}-task"
    task_value = _remote_task(kind, task_id)
    request = _result_payload(kind, task_id)
    result_key = f"remote-execution/project-1/{task_id}/output/generation-1/result.bin"
    lifecycle = RemoteExecutionStagingLifecycle(
        None,
        artifacts,
        lambda _project_id, _ref: FakeProvider(),
    )
    recorded = lifecycle.record_confirmed(
        task_value,
        request,
        {"execution_generation": 1, "sha256": "f" * 64, "size_bytes": 6},
        {
            "result": {
                "output_storage": {"storage_source_id": "s3-main", "object_key": result_key},
                "output_sha256": "f" * 64,
                "output_size_bytes": 6,
            }
        },
    )
    assert recorded["status"] == "RECORDED"
    ledger = artifacts.read_json(task_id, REMOTE_MATERIAL_CLEANUP_REF)
    assert [row["object_key"] for row in ledger["objects"]] == [result_key]


def test_successful_retry_ledger_includes_previous_generation_result(tmp_path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task_id = "training-retry"
    task_value = _remote_task(TaskKind.TRAINING, task_id, attempt=2)
    request = _result_payload(TaskKind.TRAINING, task_id)
    old_key = "remote-execution/project-1/training-retry/output/generation-1/result.bin"
    current_key = "remote-execution/project-1/training-retry/output/generation-2/result.bin"
    for generation, key, digest, size in (
        (1, old_key, "a" * 64, 5),
        (2, current_key, "b" * 64, 6),
    ):
        artifacts.atomic_write_json(
            task_id,
            f"remote-results/{generation}/upload.json",
            {
                "execution_generation": generation,
                "storage_ref": {"storage_source_id": "s3-main", "object_key": key},
                "sha256": digest,
                "size_bytes": size,
            },
        )
    lifecycle = RemoteExecutionStagingLifecycle(
        None,
        artifacts,
        lambda _project_id, _ref: FakeProvider(),
    )
    lifecycle.record_confirmed(
        task_value,
        request,
        {"execution_generation": 2, "sha256": "b" * 64, "size_bytes": 6},
        {
            "result": {
                "output_storage": {"storage_source_id": "s3-main", "object_key": current_key},
                "output_sha256": "b" * 64,
                "output_size_bytes": 6,
            }
        },
    )
    ledger = artifacts.read_json(task_id, REMOTE_MATERIAL_CLEANUP_REF)
    assert {row["object_key"] for row in ledger["objects"]} == {old_key, current_key}


def test_deployment_test_gc_records_only_staged_model_and_input_not_result_output(tmp_path):
    artifacts = ArtifactStore(tmp_path / "artifacts")
    task_value = _remote_task(TaskKind.DEPLOYMENT_TEST, "deploy-task")
    prefix = "remote-execution/project-1/deploy-task"
    payload_value = {
        "remote_execution": {
            "version": 1,
            "task_kind": "DEPLOYMENT_TEST",
            "transport": "object-storage-v1",
            "deployment": {
                "input": {
                    "storage_source_id": "s3-main",
                    "object_key": f"{prefix}/rknn-board-input/image.jpg",
                    "sha256": "a" * 64,
                    "size_bytes": 5,
                },
                "model": {
                    "type": "object",
                    "storage_source_id": "s3-main",
                    "object_key": f"{prefix}/rknn-board-model/model.rknn",
                    "sha256": "c" * 64,
                    "size_bytes": 7,
                },
                "output": {
                    "storage_source_id": "s3-main",
                    "object_key": f"{prefix}/rknn-board-output/result.jpg",
                },
            },
        }
    }
    output_key = f"{prefix}/rknn-board-output/generation-1/result.jpg"
    confirmed = {
        "result": {
            "output_storage": {
                "storage_source_id": "s3-main",
                "object_key": output_key,
            },
            "output_sha256": "b" * 64,
            "output_size_bytes": 6,
        }
    }
    refs = remote_execution_staging_refs(
        task_value,
        payload_value,
        confirmed=confirmed,
        evidence={"execution_generation": 1, "sha256": "b" * 64, "size_bytes": 6},
        artifacts=artifacts,
    )
    assert {row["role"] for row in refs} == {"board-model", "board-input"}
    assert {row["object_key"] for row in refs} == {
        f"{prefix}/rknn-board-model/model.rknn",
        f"{prefix}/rknn-board-input/image.jpg",
    }
    assert output_key not in {row["object_key"] for row in refs}

    lifecycle = RemoteExecutionStagingLifecycle(
        None,
        artifacts,
        lambda _project_id, _ref: FakeProvider(),
    )
    recorded = lifecycle.record_confirmed(
        task_value,
        payload_value,
        {"execution_generation": 1, "sha256": "b" * 64, "size_bytes": 6},
        confirmed,
    )
    assert recorded["status"] == "RECORDED"
    ledger = artifacts.read_json("deploy-task", REMOTE_MATERIAL_CLEANUP_REF)
    assert {row["object_key"] for row in ledger["objects"]} == {
        f"{prefix}/rknn-board-model/model.rknn",
        f"{prefix}/rknn-board-input/image.jpg",
    }
    assert output_key not in {row["object_key"] for row in ledger["objects"]}
