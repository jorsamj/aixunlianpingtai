import json

from platform_core.secrets import MemorySecretStore


def test_remote_deploy_api_key_is_secret_and_used_for_health_check(client, monkeypatch, tmp_path):
    import app as app_module

    secret = "deploy-secret-123456"
    resource_file = tmp_path / "deploy_resources.json"
    resource_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr(app_module, "DEPLOY_RESOURCES_FILE", resource_file)
    monkeypatch.setattr(app_module, "MODEL_SECRET_STORE", MemorySecretStore())

    created = client.post("/api/v39/deploy/resources", json={
        "name": "远程 RKNN 转换节点",
        "kind": "rockchip",
        "mode": "remote",
        "base_url": "http://converter.local",
        "api_key": secret,
    })
    assert created.status_code == 200, created.text
    resource_id = created.json()["id"]
    assert secret not in created.text
    assert "secret_ref" not in created.text
    assert created.json()["has_api_key"] is True
    assert secret not in resource_file.read_text(encoding="utf-8")
    assert json.loads(resource_file.read_text(encoding="utf-8"))[0]["secret_ref"].startswith("xjalgo:deploy-resource:")

    class Response:
        ok = True
        text = "{}"

        @staticmethod
        def json():
            return {"targets": ["rockchip"], "version": "2.3"}

    def fake_get(url, *, headers, timeout):
        assert url == "http://converter.local/api/deploy/health"
        assert headers["X-API-Key"] == secret
        return Response()

    monkeypatch.setattr(app_module.requests, "get", fake_get)
    detected = client.post(f"/api/v39/deploy/resources/{resource_id}/detect")
    assert detected.status_code == 200, detected.text
    assert detected.json()["status"] == "ready"
    assert secret not in detected.text
    assert "secret_ref" not in detected.text

    listed = client.get("/api/v39/deploy/resources")
    assert secret not in listed.text
    assert "secret_ref" not in listed.text
