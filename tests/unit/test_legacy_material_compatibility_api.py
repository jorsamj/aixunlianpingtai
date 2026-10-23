from fastapi import FastAPI
from fastapi.testclient import TestClient
from platform_core.legacy_material_compatibility_api import legacy_material_compatibility_router


def test_compatibility_api_requires_login_confirmation_and_hides_internal_evidence():
    calls = []
    class Service:
        def scan(self, **kwargs):
            calls.append(kwargs)
            return {"items": [{"image_id":"i", "status":"candidate", "material":{"secret":"internal"},
                              "original":{"path":"/internal/source"}, "candidate":True}]}
        def preview(self, ids):
            return {"fingerprint":"f", "_payloads":{"i":"raw-private"}, "image_ids":ids}
        def apply(self, ids, **kwargs):
            calls.append(kwargs)
            return {"status":"applied", "image_ids":ids}
    authenticated = False
    app = FastAPI()
    app.include_router(legacy_material_compatibility_router(lambda pid:Service(),
        lambda request,pid:{"actor_id":"signed-login"} if authenticated else {}))
    client = TestClient(app)
    base = "/api/v62/projects/p/legacy-material-compatibility"
    assert client.get(base + "/scan").status_code == 401
    assert calls == []
    authenticated = True
    response = client.get(base + "/scan")
    assert response.status_code == 200
    assert "internal" not in response.text
    assert "_payloads" not in client.post(base + "/preview",json={"image_ids":["i"]}).text
    assert client.post(base + "/apply",json={"image_ids":["i"]}).status_code == 422
    payload = {"image_ids":["i"], "expected_fingerprint":"f", "task_id":"batch-1", "confirm":"migrate_legacy_material_metadata"}
    assert client.post(base + "/apply",json=payload).status_code == 200
    assert calls[-1] == {"expected_fingerprint":"f", "task_id":"batch-1", "confirmed":True}
    assert client.post(base + "/preview",json={"image_ids":["i"] * 51}).status_code == 422
