from types import SimpleNamespace

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
        "resource_profile": "balanced",
    }
    assert target["algorithms"]
    assert all(item["framework"] == "ultralytics" for item in target["algorithms"])
