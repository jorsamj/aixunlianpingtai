import json

from platform_core.secrets import MemorySecretStore


def test_model_api_key_is_kept_out_of_json_and_responses(client, monkeypatch):
    import app as app_module

    secret = "sk-sensitive-1234567890"
    store = MemorySecretStore()
    monkeypatch.setattr(app_module, "MODEL_SECRET_STORE", store)
    response = client.post("/api/v35/model-configs", json={
        "name": "火山方舟视觉",
        "provider_type": "volcengine_ark",
        "model_kind": "vlm",
        "detect_url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "model_name": "vision-endpoint",
        "api_key": secret,
    })

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["has_api_key"] is True
    assert body["api_key_masked"] == "sk-****7890"
    assert secret not in response.text
    assert "api_key" not in body

    persisted = app_module.MODEL_CONFIGS_FILE.read_text(encoding="utf-8")
    assert secret not in persisted
    config = json.loads(persisted)[0]
    assert "api_key" not in config
    assert config["secret_ref"].startswith("xjalgo:model-config:")
    assert store.get(config["secret_ref"]) == secret

    listed = client.get("/api/v35/model-configs")
    assert secret not in listed.text


def test_bootstrap_snapshot_contains_sanitized_model_configs(client, seeded_project, monkeypatch):
    import app as app_module

    project_id, _ = seeded_project
    store = MemorySecretStore()
    monkeypatch.setattr(app_module, "MODEL_SECRET_STORE", store)
    created = client.post("/api/v35/model-configs", json={
        "name": "默认自动标注模型",
        "provider_type": "volcengine_ark",
        "model_kind": "vlm",
        "detect_url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
        "model_name": "vision-endpoint",
        "api_key": "sk-bootstrap-secret",
        "default_for_annotation": True,
    })
    assert created.status_code == 200, created.text

    snapshot = app_module._v53_build_snapshot(project_id)

    assert snapshot["model_configs"][0]["name"] == "默认自动标注模型"
    assert snapshot["model_configs"][0]["default_for_annotation"] is True
    assert snapshot["model_configs"][0]["has_api_key"] is True
    assert "api_key" not in snapshot["model_configs"][0]
    assert "secret_ref" not in snapshot["model_configs"][0]
    assert "sk-bootstrap-secret" not in json.dumps(snapshot, ensure_ascii=False)
