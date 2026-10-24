import pytest
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


def test_protocol_and_output_capability_roundtrip_preserves_secret(client, monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "MODEL_SECRET_STORE", MemorySecretStore())
    payload = {"name":"Responses config", "provider_type":"volcengine_ark", "model_kind":"vlm", "base_url":"https://ark.cn-beijing.volces.com/api/v3", "model_name":"glm-5-3-flash-260828", "api_key":"sk-unit-test-only", "api_protocol":"responses", "structured_output":"prompt"}
    created = client.post("/api/v35/model-configs", json=payload)
    assert created.status_code == 200
    item = created.json()
    assert item["api_protocol"] == "responses" and item["structured_output"] == "prompt"
    payload.pop("api_key");payload.pop("api_protocol");payload.pop("structured_output")
    payload["name"] = "legacy client edits name"
    edited = client.put("/api/v35/model-configs/"+item["id"], json=payload).json()
    assert edited["api_protocol"] == "responses" and edited["structured_output"] == "prompt"
    assert edited["has_api_key"] and edited["api_key_masked"] == item["api_key_masked"]
    listed = client.get("/api/v35/model-configs").json()["items"]
    assert listed[0]["api_protocol"] == "responses"
    assert "sk-unit-test-only" not in json.dumps(listed)


def test_custom_auto_url_is_preserved_with_protocol_warning(client):
    url = "https://proxy.example/custom/infer?route=responses"
    saved = client.post("/api/v35/model-configs", json={"name":"custom", "provider_type":"local_openai", "model_kind":"vlm", "base_url":url, "model_name":"custom"}).json()
    assert saved["base_url"] == url
    assert saved["api_protocol"] == "auto" and "协议" in saved["protocol_warning"]


def test_invalid_api_protocol_is_rejected_before_persistence(client):
    r = client.post("/api/v35/model-configs", json={"name":"bad", "base_url":"https://example/v1", "api_protocol":"typo"})
    assert r.status_code == 422


def test_connection_error_retains_safe_upstream_evidence(client, monkeypatch):
    from types import SimpleNamespace
    import platform_core.providers.openai_vision as vision
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k:SimpleNamespace(status_code=404, ok=False, headers={"x-request-id":"req-public"}, json=lambda:{"error":{"code":"InvalidEndpoint","message":"must-not-echo"}}))
    saved = client.post("/api/v35/model-configs", json={"name":"bad path", "provider_type":"volcengine_ark", "model_kind":"vlm", "base_url":"https://ark.cn-beijing.volces.com/api/v3/responses", "model_name":"configured-model"}).json()
    response = client.post(f"/api/v35/model-configs/{saved['id']}/test-annotation")
    assert response.status_code == 400
    body = response.json()
    assert body["code"] == "MODEL_RESOURCE_NOT_FOUND"
    assert body["request_id"] == "req-public" and body["server_error_code"] == "InvalidEndpoint" and body["upstream_status"] == 404
    assert "must-not-echo" not in response.text


def test_model_config_mutations_update_existing_bootstrap_projection(client, monkeypatch):
    import app as app_module
    snapshot = {"model_configs":[]}
    monkeypatch.setattr(app_module, "_V53_BOOTSTRAP_SNAPSHOT", snapshot)
    payload = {"name":"snapshot config", "provider_type":"volcengine_ark", "model_kind":"vlm", "base_url":"https://ark.cn-beijing.volces.com/api/v3/responses", "model_name":"glm-5-3-flash-260828", "api_protocol":"responses"}
    created = client.post("/api/v35/model-configs", json=payload).json()
    assert snapshot["model_configs"][0]["id"] == created["id"]
    payload["api_protocol"] = "auto"
    updated = client.put("/api/v35/model-configs/"+created["id"], json=payload).json()
    assert snapshot["model_configs"][0]["api_protocol"] == updated["api_protocol"] == "auto"
    assert client.delete("/api/v35/model-configs/"+created["id"]).status_code == 200
    assert snapshot["model_configs"] == []


def test_historical_responses_config_is_inferred_without_rewriting_its_file(client, monkeypatch):
    import app as app_module
    from types import SimpleNamespace
    import platform_core.providers.openai_vision as vision
    item = {"id":"legacy-responses", "name":"historical", "provider_type":"volcengine_ark", "model_kind":"vlm", "base_url":"https://ark.cn-beijing.volces.com/api/v3/responses", "model_name":"glm-5-3-flash-260828"}
    monkeypatch.setattr(app_module, "MODEL_CONFIGS_FILE", app_module.DATA_DIR / "legacy-protocol-test.json")
    app_module.MODEL_CONFIGS_FILE.write_text(json.dumps([item]), encoding="utf-8")
    before = app_module.MODEL_CONFIGS_FILE.read_bytes()
    listed = client.get("/api/v35/model-configs").json()["items"][0]
    assert listed["api_protocol"] == "auto" and listed["resolved_api_protocol"] == "responses"
    def post(url, **kwargs):
        assert url.endswith("/api/v3/responses")
        assert "input" in kwargs["json"]
        return SimpleNamespace(status_code=200, ok=True, headers={}, json=lambda:{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":'{"boxes":[]}'}]}]})
    monkeypatch.setattr(vision.requests,"post",post)
    assert client.post("/api/v35/model-configs/legacy-responses/test-annotation").status_code == 200
    assert app_module.MODEL_CONFIGS_FILE.read_bytes() == before


def test_unsaved_vlm_connection_test_uses_the_annotation_adapter_not_health_get(client, monkeypatch):
    from types import SimpleNamespace
    import platform_core.providers.openai_vision as vision
    calls=[]
    def post(url, **kwargs):
        calls.append(url)
        assert kwargs["json"]["input"][0]["content"][1]["type"] == "input_image"
        return SimpleNamespace(status_code=200, ok=True, headers={}, json=lambda:{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":'{"boxes":[]}'}]}]})
    monkeypatch.setattr(vision.requests,"post",post)
    monkeypatch.setattr(vision.requests,"get",lambda *a,**k:(_ for _ in ()).throw(AssertionError("VLM must not use a health GET")))
    tested=client.post("/api/v35/model-configs/test",json={"name":"unsaved","provider_type":"volcengine_ark","model_kind":"vlm","base_url":"https://ark.cn-beijing.volces.com/api/v3/responses","model_name":"configured-model"})
    assert tested.status_code == 200, tested.text
    assert tested.json()["api_protocol"] == "responses" and len(calls) == 1


@pytest.mark.parametrize("version", ["v42", "v44"])
def test_legacy_saved_vision_probe_uses_original_secret_reference(client, monkeypatch, version):
    import app as app_module
    from types import SimpleNamespace
    import platform_core.providers.openai_vision as vision
    monkeypatch.setattr(app_module, "MODEL_SECRET_STORE", MemorySecretStore())
    payload={"name":"legacy probe", "provider_type":"volcengine_ark", "model_kind":"vlm", "base_url":"https://ark.cn-beijing.volces.com/api/v3/responses", "model_name":"configured-model", "api_key":"sk-probe-test-only"}
    saved=client.post("/api/v35/model-configs",json=payload).json()
    calls=[]
    def post(url, **kwargs):
        assert kwargs["headers"]["Authorization"] == "Bearer sk-probe-test-only"
        calls.append(url)
        return SimpleNamespace(status_code=200,ok=True,headers={},json=lambda:{"status":"completed","output":[{"type":"message","content":[{"type":"output_text","text":'{"boxes":[]}'}]}]})
    monkeypatch.setattr(vision.requests,"post",post)
    response=client.post(f"/api/{version}/model-configs/{saved['id']}/test")
    assert response.status_code == 200, response.text
    assert response.json()["api_protocol"] == "responses"
    assert response.json()["ok"] is True and response.json()["status_code"] == 200
    assert calls == [payload["base_url"]]
    assert payload["api_key"] not in response.text
