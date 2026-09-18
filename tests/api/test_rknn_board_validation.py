from __future__ import annotations

import hashlib
import json

import app as app_module
from platform_core.task_runtime import TaskKind


class ReadyBoardNodes:
    def __init__(self, _repository):
        pass

    def list_public(self):
        return [{
            "node_id": "rk3568-board",
            "display_name": "RK3568 Board",
            "connection_mode": "agent",
            "online": True,
            "effective_capabilities": ["deployment-test.rknn"],
            "build_id": "board-build",
            "runtime": {
                "rknn_board": {
                    "available": True,
                    "chip": "rk3568",
                    "rknn_lite_version": "2.3.2",
                }
            },
        }]


class NoBoardNodes:
    def __init__(self, _repository):
        pass

    def list_public(self):
        return []


class FakeBoardTransport:
    def __init__(self):
        self.calls = []

    def stage_rknn_board_validation(self, **kwargs):
        self.calls.append(dict(kwargs))
        model = kwargs["model_path"]
        digest = hashlib.sha256(model.read_bytes()).hexdigest()
        return {
            "version": 1,
            "task_kind": "DEPLOYMENT_TEST",
            "transport": "object-storage-v1",
            "deployment": {
                "framework": "rknn",
                "runtime_format": "rknn",
                "confidence": 0,
                "input": {
                    "storage_source_id": "s3-main",
                    "object_key": "board/input.jpg",
                    "file_name": "input.jpg",
                    "size_bytes": 12,
                    "sha256": "a" * 64,
                },
                "model": {
                    "type": "object",
                    "storage_source_id": "s3-main",
                    "object_key": "board/model.rknn",
                    "file_name": model.name,
                    "size_bytes": model.stat().st_size,
                    "sha256": digest,
                },
                "board": {
                    "schema_version": 1,
                    "chip": kwargs["chip"],
                    "input_size": kwargs["input_size"],
                    "conversion_job_id": kwargs["conversion_job_id"],
                    "model_sha256": digest,
                    "model_size_bytes": model.stat().st_size,
                },
                "output": {
                    "storage_source_id": "s3-main",
                    "object_key": "board/result.jpg",
                    "file_name": "result.jpg",
                },
            },
        }


def seed_rknn_job(project_id: str, job_id: str = "convert-rknn") -> tuple[str, str]:
    job_dir = app_module._deploy_job_dir(project_id, job_id)
    artifacts = job_dir / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    model = artifacts / "model_rk3568.rknn"
    model.write_bytes(b"rknn-board-model")
    digest = hashlib.sha256(model.read_bytes()).hexdigest()
    (artifacts / "manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "target": {"kind": "rockchip", "chip": "rk3568", "precision": "fp16"},
        "status": "converted_unverified",
        "runtime_verified": False,
        "hardware_verified": False,
        "parameters": {"input_size": 640},
        "output": {
            "file_name": model.name,
            "size_bytes": model.stat().st_size,
            "sha256": digest,
        },
    }), encoding="utf-8")
    (job_dir / "job.json").write_text(json.dumps({
        "id": job_id,
        "project_id": project_id,
        "target": "rockchip",
        "status": "done",
        "params": {"input_size": 640, "chip": "rk3568", "precision": "fp16"},
        "runtime_verified": False,
        "hardware_verified": False,
        "validation_status": "converted_unverified",
        "outputs": [{
            "name": model.name,
            "path": str(model),
            "rel": f"artifacts/{model.name}",
        }],
    }), encoding="utf-8")
    return job_id, digest


def test_rknn_hardware_test_creates_agent_only_deployment_task(
    client, seeded_project, monkeypatch
):
    project_id, _image = seeded_project
    job_id, _digest = seed_rknn_job(project_id)
    transport = FakeBoardTransport()
    monkeypatch.setattr(app_module, "ServiceNodeRepository", ReadyBoardNodes)
    monkeypatch.setattr(app_module, "_remote_execution_transport_service", lambda: transport)

    preflight = client.get(
        f"/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests/preflight"
    )
    assert preflight.status_code == 200, preflight.text
    readiness = preflight.json()
    assert readiness["ready"] is True
    assert readiness["already_verified"] is False
    assert readiness["chip"] == "rk3568"
    assert readiness["model"]["sha256"] == _digest
    assert readiness["board_nodes"][0]["node_id"] == "rk3568-board"
    assert readiness["board_nodes"][0]["rknn_lite_version"] == "2.3.2"

    response = client.post(
        f"/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests",
        files={"file": ("verify.jpg", b"real-board-verification-image", "image/jpeg")},
    )
    assert response.status_code == 202, response.text
    body = response.json()
    task = app_module.shared_task_repository().get(body["id"])
    assert task is not None
    assert task.kind is TaskKind.DEPLOYMENT_TEST
    assert task.required_capabilities == ("agent.remote",)
    request = app_module.shared_task_artifacts().read_json(task.task_id, "request.json")
    assert request["execution_mode"] == "agent"
    assert request["runtime_format"] == "rknn"
    assert request["source_conversion_job_id"] == job_id
    assert request["remote_execution"]["deployment"]["board"]["chip"] == "rk3568"
    assert transport.calls[0]["input_size"] == 640
    assert body["board_nodes"][0]["node_id"] == "rk3568-board"


def test_rknn_hardware_test_fails_before_task_creation_without_matching_board(
    client, seeded_project, monkeypatch
):
    project_id, _image = seeded_project
    job_id, _digest = seed_rknn_job(project_id, "convert-no-board")
    monkeypatch.setattr(app_module, "ServiceNodeRepository", NoBoardNodes)

    preflight = client.get(
        f"/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests/preflight"
    )
    assert preflight.status_code == 200, preflight.text
    readiness = preflight.json()
    assert readiness["ready"] is False
    assert readiness["already_verified"] is False
    assert readiness["board_nodes"] == []
    assert "RK3568" in readiness["reason"]
    assert "deployment-test.rknn" in readiness["solution"]

    before = app_module.shared_task_repository().list(
        project_id=project_id,
        kinds=(TaskKind.DEPLOYMENT_TEST,),
        limit=200,
    )

    response = client.post(
        f"/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests",
        files={"file": ("verify.jpg", b"image", "image/jpeg")},
    )
    assert response.status_code == 409
    body = response.json()
    assert body["code"] == "RKNN_BOARD_NODE_UNAVAILABLE"

    after = app_module.shared_task_repository().list(
        project_id=project_id,
        kinds=(TaskKind.DEPLOYMENT_TEST,),
        limit=200,
    )
    assert len(after.items) == len(before.items)


def test_rknn_hardware_preflight_reports_already_verified_without_allowing_new_task(
    client, seeded_project, monkeypatch
):
    project_id, _image = seeded_project
    job_id, _digest = seed_rknn_job(project_id, "convert-already-verified")
    job_dir = app_module._deploy_job_dir(project_id, job_id)
    manifest_path = job_dir / "artifacts" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["hardware_verified"] = True
    manifest["status"] = "hardware_verified"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    monkeypatch.setattr(app_module, "ServiceNodeRepository", ReadyBoardNodes)

    preflight = client.get(
        f"/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests/preflight"
    )
    assert preflight.status_code == 200
    body = preflight.json()
    assert body["ready"] is False
    assert body["already_verified"] is True
    assert "已完成板端 Runtime 验证" in body["reason"]

    response = client.post(
        f"/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests",
        files={"file": ("verify.jpg", b"image", "image/jpeg")},
    )
    assert response.status_code == 409
    assert "已完成板端 Runtime 验证" in response.text


def test_rknn_hardware_acceptance_report_requires_complete_durable_evidence(
    client, seeded_project
):
    project_id, _image = seeded_project
    job_id, digest = seed_rknn_job(project_id, "convert-report")
    job_dir = app_module._deploy_job_dir(project_id, job_id)
    manifest_path = job_dir / "artifacts" / "manifest.json"
    job_path = job_dir / "job.json"
    verification = {
        "task_id": "board-task-report",
        "execution_generation": 4,
        "verified_at": "2026-09-19T01:02:03+00:00",
        "node_id": "rk3568-board-report",
        "chip": "rk3568",
        "engine": "rknn-lite2",
        "rknn_lite_version": "2.3.2",
        "model_sha256": digest,
        "model_size_bytes": (job_dir / "artifacts" / "model_rk3568.rknn").stat().st_size,
        "input": {
            "file_name": "verify.jpg",
            "size_bytes": 1234,
            "sha256": "b" * 64,
        },
        "inference_ms": 11.25,
        "output_count": 3,
        "output_shapes": [[1, 84, 8400]],
    }
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update({
        "status": "hardware_verified",
        "runtime_verified": True,
        "hardware_verified": True,
        "validation_status": "hardware_verified",
        "hardware_verification": verification,
    })
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job.update({
        "runtime_verified": True,
        "hardware_verified": True,
        "validation_status": "hardware_verified",
        "hardware_verification": verification,
    })
    job_path.write_text(json.dumps(job), encoding="utf-8")

    response = client.get(
        f"/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests/report"
    )
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["status"] == "passed"
    assert report["accuracy_verified"] is False
    assert report["model"]["sha256"] == digest
    assert report["board"] == {
        "node_id": "rk3568-board-report",
        "rknn_lite_version": "2.3.2",
    }
    assert report["verification"]["task_id"] == "board-task-report"
    assert report["verification"]["input"]["sha256"] == "b" * 64
    assert report["verification"]["inference_ms"] == 11.25
    assert "不代表算法准确率" in report["statement"]

    download = client.get(
        f"/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests/report?download=true"
    )
    assert download.status_code == 200
    assert "attachment;" in download.headers["content-disposition"]
    assert "rknn-hardware-acceptance-convert-report.json" in download.headers["content-disposition"]


def test_rknn_hardware_acceptance_report_refuses_unverified_job(client, seeded_project):
    project_id, _image = seeded_project
    job_id, _digest = seed_rknn_job(project_id, "convert-report-unverified")
    response = client.get(
        f"/api/v39/projects/{project_id}/deploy/jobs/{job_id}/hardware-tests/report"
    )
    assert response.status_code == 409
    assert "尚未完成真实板端 Runtime 验证" in response.text
