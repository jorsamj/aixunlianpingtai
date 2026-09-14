import json
from pathlib import Path

from platform_core.deployment.conversion_tasks import ConversionHandler
from platform_core.deployment.inference_tasks import DeploymentTestHandler
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus
from platform_core.task_runtime.worker import WorkerContext


def _reclaim(repository: TaskRepository, task_id: str, kind: TaskKind, capability: str):
    first = repository.claim_next("worker-before-crash", [kind], {capability})
    assert first is not None
    with repository._connect() as database:
        database.execute(
            "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
            ("2000-01-01T00:00:00+00:00", task_id),
        )
    assert repository.release_expired() == 1
    second = repository.claim_next("worker-after-restart", [kind], {capability})
    assert second is not None and second.task.attempt >= 2
    return second


def test_completed_conversion_job_recovers_without_rerunning_converter(tmp_path: Path):
    task_id = "convert-recover"
    project_id = "project-one"
    data_dir = tmp_path / "data"
    runtime = data_dir / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")

    job_dir = data_dir / "deployment" / task_id
    converted = job_dir / "artifacts" / "model.onnx"
    converted.parent.mkdir(parents=True)
    converted.write_bytes(b"already-converted-model")
    manifest = job_dir / "artifacts" / "manifest.json"
    manifest.write_text(json.dumps({"target": "onnx"}), encoding="utf-8")
    job = {
        "id": task_id,
        "task_id": task_id,
        "status": "done",
        "target": "onnx",
        "progress": 100,
        "stage": "转换完成",
        "source_name": "source.pt",
        "outputs": [{"name": converted.name, "path": str(converted), "size_mb": 0.001}],
        "manifest_path": str(manifest),
        "runtime_verified": True,
        "validation_status": "runtime_verified",
        "finished_at": "2026-09-14 09:00:00",
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    artifacts.atomic_write_json(task_id, "request.json", {
        "job_dir": str(job_dir),
        "worker_path": str(tmp_path / "converter-that-no-longer-exists.py"),
        "python_path": str(tmp_path / "python-that-no-longer-exists"),
    })
    repository.create(TaskRecord.new(
        task_id,
        project_id,
        TaskKind.MODEL_CONVERSION,
        "request.json",
        "conversion:cpu",
        required_capabilities=("conversion.runtime",),
    ))
    lease = _reclaim(repository, task_id, TaskKind.MODEL_CONVERSION, "conversion.runtime")
    context = WorkerContext(lease.task, lease, repository, artifacts)

    status, result_ref = ConversionHandler().recover(context)
    context.finish(status, result_ref)

    task = repository.get(task_id)
    assert task is not None and task.status is TaskStatus.SUCCEEDED
    assert task.result_ref == "conversion/result.json"
    result = artifacts.read_json(task_id, task.result_ref)
    assert result["job_id"] == task_id
    assert result["outputs"][0]["path"] == str(converted)
    assert result["recovered_from_completed_work"] is True


def test_completed_deployment_test_recovers_from_output_and_log_without_rerunning(tmp_path: Path):
    task_id = "deploy-test-recover"
    project_id = "project-one"
    data_dir = tmp_path / "data"
    runtime = data_dir / "task_runtime"
    repository = TaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")

    output = data_dir / "deployment_tests" / task_id / "result.jpg"
    output.parent.mkdir(parents=True)
    output.write_bytes(b"already-rendered-result-image")
    log_path = artifacts.artifact_path(task_id, "logs/runtime.log")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(
        "runtime initialized\n" + json.dumps({"detections": 2, "elapsed_ms": 88.2}) + "\n",
        encoding="utf-8",
    )

    artifacts.atomic_write_json(task_id, "request.json", {
        "model_path": str(tmp_path / "model-that-no-longer-exists.onnx"),
        "model_reference": "model.onnx",
        "model_reference_type": "project",
        "input_path": str(tmp_path / "input-that-no-longer-exists.jpg"),
        "output_path": str(output),
        "runner_path": str(tmp_path / "runner-that-no-longer-exists.py"),
        "python_path": str(tmp_path / "python-that-no-longer-exists"),
        "framework": "ultralytics",
        "image_url": "/api/example/result.jpg",
        "conf": 0.25,
    })
    repository.create(TaskRecord.new(
        task_id,
        project_id,
        TaskKind.DEPLOYMENT_TEST,
        "request.json",
        "deployment:test",
        required_capabilities=("deployment.runtime",),
    ))
    lease = _reclaim(repository, task_id, TaskKind.DEPLOYMENT_TEST, "deployment.runtime")
    context = WorkerContext(lease.task, lease, repository, artifacts)

    status, result_ref = DeploymentTestHandler().recover(context)
    context.finish(status, result_ref)

    task = repository.get(task_id)
    assert task is not None and task.status is TaskStatus.SUCCEEDED
    assert task.result_ref == "result.json"
    result = artifacts.read_json(task_id, task.result_ref)
    assert result["detections"] == 2
    assert result["output_path"] == str(output)
    assert result["output_size_bytes"] == output.stat().st_size
    assert result["recovered_from_completed_work"] is True
