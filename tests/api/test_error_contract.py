def test_missing_label_uses_actionable_error_contract(client):
    response = client.get("/api/v54/projects/not-found/label-schema")
    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert body["code"]
    assert body["message"]
    assert body["detail"]
    assert "solution" in body


def test_validation_error_uses_same_contract(client):
    response = client.post("/api/projects", json={})
    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["code"] == "VALIDATION_ERROR"
    assert body["message"] == "提交的数据不完整或格式不正确"
    assert body["detail"]
    assert body["solution"]
