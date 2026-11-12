from types import SimpleNamespace
from pathlib import Path

import pytest
from fastapi import HTTPException

import app as app_module


class _FakeNodes:
    def __init__(self, _repository):
        pass

    def list_public(self):
        return [
            {
                "node_id": "gpu-agent-1",
                "connection_mode": "agent",
                "online": True,
                "effective_capabilities": ["training"],
            },
            {
                "node_id": "offline-agent",
                "connection_mode": "agent",
                "online": False,
                "effective_capabilities": ["training"],
            },
        ]


class _FakeArtifactService:
    def __init__(self, **_kwargs):
        self.repository = SimpleNamespace(
            config=lambda: {"storage_source_id": "model-artifact-oss"},
        )


class _FakeSources:
    def get(self, source_id):
        assert source_id == "model-artifact-oss"
        return SimpleNamespace(enabled=True, type="oss")


def test_training_options_puts_scheduler_owned_gpu_cluster_first(monkeypatch):
    monkeypatch.setattr(app_module, "ServiceNodeRepository", _FakeNodes)
    monkeypatch.setattr(app_module, "ModelArtifactService", _FakeArtifactService)
    monkeypatch.setattr(app_module, "storage_source_repository", lambda: _FakeSources())
    monkeypatch.setattr(app_module, "get_active_ultralytics_env", lambda: {})
    monkeypatch.setattr(app_module, "get_active_paddle_env", lambda: {})
    monkeypatch.setattr(app_module, "read_json", lambda *_args, **_kwargs: [])

    body = app_module.training_options("project-1")

    assert body["ok"] is True
    assert body["targets"]
    target = body["targets"][0]
    assert target["id"] == "cluster_scheduler"
    assert target["type"] == "server"
    assert target["scheduler_owned"] is True
    assert target["online_training_nodes"] == 1
    assert target["recommendation"] == {
        "device": "auto",
        "resource_strategy": "auto",
        "resource_profile": "performance",
    }
    assert target["algorithms"]
    assert all(item["framework"] == "ultralytics" for item in target["algorithms"])


def test_training_options_never_probes_legacy_servers_or_recursively_scans_paddle(monkeypatch):
    """A read must not block on 20 remote timeouts or project job history."""
    servers = [{"id": str(i), "name": f"legacy-{i}", "base_url": f"http://host-{i}:8020"}
               for i in range(20)]
    monkeypatch.setattr(app_module, "read_json", lambda path, default: servers if path == app_module.SERVERS_FILE else default)
    monkeypatch.setattr(app_module, "get_active_ultralytics_env", lambda: {"models": [], "name": "local"})
    monkeypatch.setattr(app_module, "get_active_paddle_env", lambda: {
        "python_path": str(Path(__file__)), "paddledet_dir": str(Path(__file__).parent),
        "algorithm_scan": {"ok": True, "items": [{"key": "paddledet_test", "framework": "paddle"}],
                           "total": 1, "families": {}},
        "weight_scan": [],
    })
    monkeypatch.setattr(app_module, "list_algorithms_internal", lambda _project: [])
    monkeypatch.setattr(app_module, "list_algorithm_assets", lambda *_: [])
    monkeypatch.setattr(app_module, "list_models_internal", lambda *_: pytest.fail("training GET scanned project job history"))
    monkeypatch.setattr(app_module, "scan_paddledet_algorithms", lambda *_: pytest.fail("training GET scanned Paddle configs"))
    monkeypatch.setattr(app_module, "scan_paddle_weights", lambda *_: pytest.fail("training GET scanned Paddle weights"))
    monkeypatch.setattr(app_module.requests, "get", lambda *_args, **_kwargs: pytest.fail("training GET contacted legacy server"))

    body = app_module.training_options("project-1")

    legacy = [item for item in body["targets"] if item["id"].startswith("server:")]
    assert len(legacy) == 20
    assert all(item["status"] != "ready" for item in legacy)
    assert all("api_key" not in item for item in legacy)
    paddle = next(item for item in body["targets"] if item["id"] == "local_paddle")
    assert [row["key"] for row in paddle["algorithms"]] == ["paddledet_test"]


def test_saved_server_explicit_health_check_is_reused_without_request_time_network(monkeypatch, tmp_path):
    config = tmp_path / "train_servers.json"
    config.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(app_module, "SERVERS_FILE", config)
    monkeypatch.setattr(app_module, "get_active_ultralytics_env", lambda: {})
    monkeypatch.setattr(app_module, "get_active_paddle_env", lambda: {})
    calls = []

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"framework": "ultralytics", "algorithms": [{"key": "yolo11n_det"}], "base_models": []}

    def fetch(url, **_kwargs):
        calls.append(url)
        return Response()

    monkeypatch.setattr(app_module.requests, "get", fetch)
    app_module.save_train_server(app_module.TrainServerReq(name="legacy", base_url="http://host", api_key="secret"))
    app_module.test_train_server(app_module.TrainServerReq(name="legacy", base_url="http://host", api_key="secret"))
    assert len(calls) == 1
    first = app_module.training_options()["targets"][0]
    assert first["status"] == "ready"
    assert len(calls) == 1
    assert "secret" not in str(first)

    configured = app_module.read_json(config, [])
    configured[0]["api_key"] = "rotated"
    app_module.write_json(config, configured)
    stale = app_module.training_options()["targets"][0]
    assert stale["status"] != "ready"
    assert len(calls) == 1


def test_paddle_activation_saves_config_and_weight_snapshot_for_read_only_options(monkeypatch, tmp_path):
    env_file = tmp_path / "paddle_env.json"
    configs = tmp_path / "PaddleDetection" / "configs"
    configs.mkdir(parents=True)
    scans = {"algorithms": 0, "weights": 0}

    def algorithms(_path):
        scans["algorithms"] += 1
        return {"ok": True, "items": [{"key": "paddledet_pico", "framework": "paddle"}],
                "total": 1, "families": {"PicoDet": 1}}

    def weights(_path):
        scans["weights"] += 1
        return [{"label": "actual.pdparams", "value": str(tmp_path / "actual.pdparams")}]

    monkeypatch.setattr(app_module, "PADDLE_ENV_FILE", env_file)
    monkeypatch.setattr(app_module, "scan_paddledet_algorithms", algorithms)
    monkeypatch.setattr(app_module, "scan_paddle_weights", weights)
    monkeypatch.setattr(app_module, "get_active_ultralytics_env", lambda: {})
    app_module.select_paddle_env(app_module.PaddleEnvReq(
        python_path=str(Path(__file__).resolve()), paddledet_dir=str(configs.parent)))
    assert scans == {"algorithms": 1, "weights": 1}
    target = next(row for row in app_module.training_options()["targets"] if row["id"] == "local_paddle")
    assert target["status"] == "ready"
    assert target["algorithms"][0]["key"] == "paddledet_pico"
    assert target["base_models"][1]["label"] == "actual.pdparams"
    assert scans == {"algorithms": 1, "weights": 1}


def test_legacy_check_expires_without_implicitly_rechecking(monkeypatch, tmp_path):
    config = tmp_path / "train_servers.json"
    original = {"id": "legacy-1", "base_url": "http://host", "api_key": "secret"}
    monkeypatch.setattr(app_module, "SERVERS_FILE", config)
    monkeypatch.setattr(app_module, "get_active_ultralytics_env", lambda: {})
    monkeypatch.setattr(app_module, "get_active_paddle_env", lambda: {})
    app_module.write_json(config, [original])
    app_module._record_legacy_health("legacy-1", original,
        {"ok": True, "algorithms": [{"key": "yolo", "api_key": "do-not-keep"}], "base_models": []})
    assert app_module.training_options()["targets"][0]["status"] == "ready"
    assert "do-not-keep" not in config.read_text(encoding="utf-8")
    original_snapshot = app_module.read_json(config, [])[0]["health_snapshot"]
    monkeypatch.setattr(app_module.time, "time", lambda: original_snapshot["checked_at_epoch"] + 601)
    monkeypatch.setattr(app_module.requests, "get", lambda *_args, **_kwargs: pytest.fail("expired snapshot probed remotely"))
    assert app_module.training_options()["targets"][0]["status"] == "unknown"



def test_training_request_rejects_fake_shared_gpu_policy():
    payload = app_module.TrainReq(
        gpu_policy="shared",
        split_mode="random_test_from_training_pool",
        train_image_ids=["image-a", "image-b"],
        experiment_percent=20,
        validation_percent=20,
    )
    with pytest.raises(HTTPException, match="GPU 共享") as caught:
        app_module.validate_train_request(payload)
    assert caught.value.status_code == 400


def test_training_api_defaults_to_exclusive_high_performance_and_150_epochs():
    request = app_module.TrainReq()
    assert request.epochs == 150
    assert request.resource_strategy == "auto"
    assert request.resource_profile == "performance"
    assert request.gpu_policy == "exclusive"
    assert request.early_stopping_enabled is False


def test_training_mode_is_validated_without_disabling_existing_label_contract():
    preset = app_module.TrainReq(training_mode="quick", resource_strategy="auto")
    app_module.validate_train_request(preset)
    invalid_preset = app_module.TrainReq(training_mode="complex", resource_strategy="manual")
    with pytest.raises(HTTPException, match="预设训练模式"):
        app_module.validate_train_request(invalid_preset)
    invalid_custom = app_module.TrainReq(training_mode="custom", resource_strategy="auto")
    with pytest.raises(HTTPException, match="自定义训练模式"):
        app_module.validate_train_request(invalid_custom)
