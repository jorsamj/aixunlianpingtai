import pytest
import json

from platform_core.secrets import MemorySecretStore


@pytest.fixture(autouse=True)
def isolated_model_credentials(monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "MODEL_SECRET_STORE", MemorySecretStore())
    def forbidden_system_store(*args, **kwargs):
        pytest.fail("model configuration tests must not access system credentials")
    monkeypatch.setattr(app_module, "KeyringSecretStore", forbidden_system_store)


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


def test_wevisone_is_optional_and_technical_fields_are_server_owned(client):
    general = client.post("/api/v35/model-configs", json={"name": "Qwen", "provider_adapter": "local_openai", "base_url": "http://127.0.0.1:8000/v1", "model_name": "qwen35", "default_for_annotation": True}).json()
    special = client.post("/api/v35/model-configs", json={"name": "WeVisOne", "provider_adapter": "wevisone_vl", "base_url": "http://127.0.0.1:18000", "model_name": "wevisone-vl-2b", "coordinate_space": "normalized_1000", "coordinate_order": "yxyx", "structured_output": "prompt", "default_for_annotation": True}).json()
    assert special["coordinate_space"] == "pixel" and special["coordinate_order"] == "xyxy"
    assert special["capabilities"] == ["detect", "segment", "matting"]
    listed = client.get("/api/v35/model-configs").json()["items"]
    assert {"local_openai", "wevisone_vl"}.issubset({row.get("provider_adapter") for row in listed})
    assert sum(bool(row["default_for_annotation"]) for row in listed) == 1
    assert next(row for row in listed if row["id"] == general["id"])["default_for_annotation"] is False
    changed = client.patch(f"/api/v35/model-configs/{special['id']}/availability", json={"enabled": False})
    assert changed.status_code == 200
    assert changed.json()["default_for_annotation"] is False
    assert changed.json()["enabled"] is False
    assert client.post(f"/api/v35/model-configs/{special['id']}/test-annotation").status_code == 409
    assert client.post("/api/v35/model-configs", json={"name": "invalid", "provider_adapter": "wevisone_vl", "base_url": "http://localhost:18000/v1/chat/completions", "model_name": "wevisone-vl-2b"}).status_code == 400


def test_wevisone_probe_empty_does_not_claim_accuracy_and_persists_safe_receipt(client, monkeypatch):
    from types import SimpleNamespace
    import platform_core.providers.wevisone_vision as vision
    seen = []
    def get(url, **kwargs):
        seen.append(url)
        return SimpleNamespace(ok=True, json=lambda: {"data": [{"id": "wevisone-vl-2b"}]})
    def post(url, **kwargs):
        seen.append(url)
        assert set(kwargs["json"]) == {"image", "query"}
        assert kwargs["json"]["query"] == ["fire"]
        assert kwargs["json"]["image"].startswith("data:image/jpeg;base64,")
        # Exact no-target shape recorded from the deployed 4070 FastAPI on
        # 2026-11-06 (sample white 128x128 JPEG, query=["fire"]).
        return SimpleNamespace(ok=True, json=lambda: {
            "model": "wevisone-vl-2b", "width": 128, "height": 128,
            "response": "<ref>fire</ref><box>none</box>", "latency_s": 1.0,
            "coordinate_system": "xyxy_pixel", "boxes": [],
        })
    monkeypatch.setattr(vision.requests, "get", get)
    monkeypatch.setattr(vision.requests, "post", post)
    saved = client.post("/api/v35/model-configs", json={"name": "WeVisOne", "provider_adapter": "wevisone_vl", "base_url": "http://127.0.0.1:18000", "model_name": "wevisone-vl-2b"}).json()
    result = client.post(f"/api/v35/model-configs/{saved['id']}/test-annotation")
    assert result.status_code == 200, result.text
    assert result.json()["parsed_boxes"] == []
    assert result.json()["no_target"] is True
    assert result.json()["coordinate_confirmed"] is False
    assert seen == ["http://127.0.0.1:18000/v1/models", "http://127.0.0.1:18000/v1/vision/detect"]
    refreshed = client.get("/api/v35/model-configs").json()["items"][0]
    assert refreshed["last_test"]["status"] == "protocol_passed"
    assert refreshed["coordinate_validation"]["status"] == "unverified"


def test_wevisone_model_not_loaded_is_not_reported_as_connected(client, monkeypatch):
    from types import SimpleNamespace
    import platform_core.providers.wevisone_vision as vision
    monkeypatch.setattr(vision.requests, "get", lambda *a, **k: SimpleNamespace(ok=True, json=lambda: {"data": [{"id": "qwen35"}]}))
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: pytest.fail("unloaded model should not be inferred"))
    saved = client.post("/api/v35/model-configs", json={"name": "WeVisOne", "provider_adapter": "wevisone_vl", "base_url": "http://127.0.0.1:18000", "model_name": "wevisone-vl-2b"}).json()
    r = client.post(f"/api/v35/model-configs/{saved['id']}/test-annotation")
    assert r.status_code == 400 and r.json()["code"] == "MODEL_NOT_LOADED"
    assert client.get("/api/v35/model-configs").json()["items"][0]["last_test"]["code"] == "MODEL_NOT_LOADED"


def test_wevisone_segmentation_preview_is_read_only(client, monkeypatch):
    from types import SimpleNamespace
    from io import BytesIO
    from PIL import Image
    import base64
    import platform_core.providers.wevisone_vision as vision
    bitmap = BytesIO(); Image.new("RGBA", (16, 16), (255, 0, 0, 100)).save(bitmap, "PNG")
    png64 = base64.b64encode(bitmap.getvalue()).decode()
    monkeypatch.setattr(vision.requests, "get", lambda *a, **k: SimpleNamespace(ok=True, json=lambda: {"data": [{"id": "wevisone-vl-2b"}]}))
    monkeypatch.setattr(vision.requests, "post", lambda *a, **k: SimpleNamespace(ok=True, json=lambda: {"instances": [{"label": "person", "mask_png": png64, "cutout_png": png64}, {"label": "person", "mask_png": png64, "cutout_png": png64}]}))
    saved = client.post("/api/v35/model-configs", json={"name": "WeVisOne", "provider_adapter": "wevisone_vl", "base_url": "http://127.0.0.1:18000", "model_name": "wevisone-vl-2b"}).json()
    response = client.post(f"/api/v35/model-configs/{saved['id']}/verify-coordinates", json={"image_base64": png64, "labels": ["person"], "operation": "segment"})
    assert response.status_code == 200, response.text
    assert "mask" in response.json()["images"]
    assert "foreground" in response.json()["images"]
    assert len(response.json()["instances"]) == 2
    assert response.json()["notice"].startswith("仅用于预览")
    refreshed = client.get("/api/v35/model-configs").json()["items"][0]
    assert refreshed["coordinate_validation"]["status"] == "unverified"


def test_wevisone_real_image_pixel_contract_manual_confirmation(client, monkeypatch):
    from types import SimpleNamespace
    from io import BytesIO
    from PIL import Image
    import base64
    import platform_core.providers.wevisone_vision as vision
    b = BytesIO(); Image.new("RGB", (1280, 960), "white").save(b, "JPEG")
    png64 = base64.b64encode(b.getvalue()).decode()
    seen = []
    monkeypatch.setattr(vision.requests, "get", lambda *_a, **_k: SimpleNamespace(ok=True, json=lambda: {"data": [{"id": "wevisone-vl-2b"}]}))
    def post(url, **kwargs):
        seen.append(kwargs["json"])
        assert kwargs["json"]["query"] == ["person"]
        return SimpleNamespace(ok=True, json=lambda: {"coordinate_system": "xyxy_pixel", "boxes": [{"label": "person", "bbox_xyxy": [128, 192, 640, 768], "bbox_normalized": [100, 200, 500, 800]}], "response": "<ref>person</ref><box><100><200><500><800></box>"})
    monkeypatch.setattr(vision.requests, "post", post)
    saved = client.post("/api/v35/model-configs", json={"name": "WeVisOne", "provider_adapter": "wevisone_vl", "base_url": "http://127.0.0.1:18000", "model_name": "wevisone-vl-2b"}).json()
    response = client.post(f"/api/v35/model-configs/{saved['id']}/verify-coordinates", json={"image_base64": png64, "labels": ["person"]})
    assert response.status_code == 200, response.text
    sample = response.json()
    assert sample["parsed_boxes"][0]["x1"] == 128
    assert sample["parsed_boxes"][0]["y2"] == 768
    assert sample["parsed_boxes"][0]["confidence"] is None
    assert sample["coordinate_validation"]["status"] == "unverified"
    receipt = sample["coordinate_validation"]
    confirmed = client.post(f"/api/v35/model-configs/{saved['id']}/confirm-coordinates", json={"receipt": receipt["receipt"], "config_revision": receipt["config_revision"], "sample_sha256": receipt["sample_sha256"], "positions_confirmed": True})
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["coordinate_validation"]["status"] == "verified"
    assert seen and seen[0]["image"].startswith("data:image/jpeg;base64,")


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


def test_real_sample_coordinate_contract_and_evidence(client, monkeypatch):
    import app as app_module
    import base64
    from io import BytesIO
    from PIL import Image
    class Provider:
        def annotate(self, **kwargs):
            assert "normalized_1000" in kwargs["prompt"]
            return {"text": '{"boxes":[{"label":"person","confidence":0.9,"x1":100,"y1":200,"x2":500,"y2":800}]}'}
    monkeypatch.setattr(app_module.auto_label_core, "provider_factory", lambda cfg: Provider())
    payload = {"name":"fixture", "base_url":"http://fixture.invalid", "model_name":"fixture", "coordinate_space":"normalized_1000", "coordinate_order":"yxyx"}
    saved = client.post("/api/v35/model-configs", json=payload).json()
    b = BytesIO(); Image.new("RGB", (1920,1080)).save(b, format="PNG")
    response = client.post(f"/api/v35/model-configs/{saved['id']}/verify-coordinates", json={"image_base64":base64.b64encode(b.getvalue()).decode(), "labels":["person"]})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["parsed_boxes"][0]["x1"] == 384
    assert result["parsed_boxes"][0]["y1"] == 108
    assert result["coordinate_validation"]["status"] == "unverified"
    assert result["coordinate_validation"]["sample_sha256"]
    evidence = result["coordinate_validation"]
    confirmation = {key:evidence[key] for key in ("receipt", "config_revision", "sample_sha256")}
    confirmation["positions_confirmed"] = True
    assert client.post(f"/api/v35/model-configs/{saved['id']}/confirm-coordinates", json={**confirmation, "receipt":"forged"}).status_code == 409
    confirmed = client.post(f"/api/v35/model-configs/{saved['id']}/confirm-coordinates", json=confirmation)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["coordinate_validation"]["status"] == "verified"
    assert client.post(f"/api/v35/model-configs/{saved['id']}/confirm-coordinates", json=confirmation).status_code == 409
    payload["annotation_prompt_template"] = "new instruction"
    edited = client.put(f"/api/v35/model-configs/{saved['id']}", json=payload).json()
    assert "sample_sha256" not in edited["coordinate_validation"]
    assert edited["coordinate_validation"]["status"] == "unverified"


def test_coordinate_contract_rejects_unknown_protocol(client):
    result = client.post("/api/v35/model-configs", json={"name":"bad", "base_url":"http://fixture.invalid", "output_protocol":"native_array"})
    assert result.status_code == 422


@pytest.mark.parametrize("fail", [False, True])
def test_coordinate_evidence_cannot_overwrite_concurrent_config_edit(client, monkeypatch, fail):
    import app as app_module
    from platform_core.providers.base import ProviderRequestError
    import base64
    from io import BytesIO
    from PIL import Image
    payload = {"name":"before", "base_url":"http://fixture.invalid", "model_name":"fixture"}
    saved = client.post("/api/v35/model-configs", json=payload).json()
    class Provider:
        def annotate(self, **kwargs):
            changed = client.put(f"/api/v35/model-configs/{saved['id']}", json={**payload, "name":"after"})
            assert changed.status_code == 200
            if fail:
                raise ProviderRequestError("fixture failed", code="MODEL_OUTPUT_PARSE_ERROR")
            return {"text": '{"boxes":[]}'}
    monkeypatch.setattr(app_module.auto_label_core, "provider_factory", lambda cfg:Provider())
    b=BytesIO();Image.new("RGB",(16,16)).save(b,format="PNG")
    response=client.post(f"/api/v35/model-configs/{saved['id']}/verify-coordinates",json={"image_base64":base64.b64encode(b.getvalue()).decode(),"labels":["person"]})
    assert response.status_code == (400 if fail else 409)
    current=next(x for x in client.get("/api/v35/model-configs").json()["items"] if x["id"]==saved["id"])
    assert current["name"]=="after"
    assert current["coordinate_config_revision"] != saved["coordinate_config_revision"]
    assert "sample_sha256" not in current["coordinate_validation"]
    assert current["coordinate_validation"]["status"] == "unverified"


def test_slow_sample_cannot_overwrite_confirmation_for_same_revision(client, monkeypatch):
    import app as app_module
    import base64
    from io import BytesIO
    from PIL import Image
    saved=client.post("/api/v35/model-configs",json={"name":"fixture","base_url":"http://fixture.invalid"}).json()
    class Provider:
        def annotate(self, **kwargs):
            # Another request has completed and been explicitly confirmed while this provider was pending.
            with app_module.FileLock(str(app_module.MODEL_CONFIGS_FILE)+".lock",timeout=10):
                items=app_module._v35_model_items()
                row=next(x for x in items if x["id"]==saved["id"])
                row["coordinate_validation"]={"status":"verified","reason":"newer human confirmation"}
                app_module._v35_save_items(app_module.MODEL_CONFIGS_FILE,items)
            return {"text":'{"boxes":[]}'}
    monkeypatch.setattr(app_module.auto_label_core,"provider_factory",lambda cfg:Provider())
    b=BytesIO();Image.new("RGB",(16,16)).save(b,format="PNG")
    response=client.post(f"/api/v35/model-configs/{saved['id']}/verify-coordinates",json={"image_base64":base64.b64encode(b.getvalue()).decode(),"labels":["person"]})
    assert response.status_code==409
    current=next(x for x in client.get("/api/v35/model-configs").json()["items"] if x["id"]==saved["id"])
    assert current["coordinate_validation"]["status"]=="verified"
    assert current["coordinate_validation"]["reason"]=="newer human confirmation"
