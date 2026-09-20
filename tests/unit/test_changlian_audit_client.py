from pathlib import Path

from platform_core.external_algorithm_platform import ChangLianClient, ChangLianEndpoints
from platform_core.integration_audit import IntegrationAuditRepository


class FakeResponse:
    def __init__(self, body, status_code=200, headers=None):
        self._body = body
        self.status_code = status_code
        self.headers = headers or {}
        self.text = ""

    def json(self):
        return self._body


class FakeSession:
    def request(self, method, url, **kwargs):
        if url.endswith("/internal/auth/test-sign"):
            assert kwargs.get("params") == {"access_key": "ak-sensitive", "access_secret": "secret-sensitive"}
            assert "json" not in kwargs
            return FakeResponse({"code": 0, "msg": "操作成功", "data": {"timestamp": "100", "nonce": "n1", "signature": "sig"}})
        if url.endswith("/internal/auth/token"):
            return FakeResponse(
                {"code": 0, "msg": "操作成功", "data": {"accessToken": "token-1", "tokenType": "Bearer", "expiresIn": 3600}},
                headers={"X-Request-Id": "req-token"},
            )
        if url.endswith("/algorithm-category/tree"):
            assert kwargs["headers"]["Access-Token"] == "token-1"
            assert "Authorization" not in kwargs["headers"]
            return FakeResponse(
                {"code": 0, "msg": "操作成功", "data": [{"categoryId": "c1", "categoryName": "安全"}]},
                headers={"X-Request-Id": "req-category"},
            )
        raise AssertionError(url)


def test_changlian_http_client_records_every_remote_step_and_redacts_credentials(tmp_path: Path):
    audit = IntegrationAuditRepository(tmp_path)
    client = ChangLianClient(
        base_url="https://changlian.example",
        access_key="ak-sensitive",
        access_secret="secret-sensitive",
        endpoints=ChangLianEndpoints(),
        session=FakeSession(),
        audit_callback=audit.record,
    )
    client.set_audit_context(project_id="p1", algorithm_id="a1", version_id="v1")

    result = client.category_tree()

    assert result["data"][0]["categoryId"] == "c1"
    rows = audit.list(limit=10)
    assert {row["operation"] for row in rows} == {"auth_signature", "auth_token", "category_list"}
    assert all(row["status"] == "SUCCESS" for row in rows)
    category = next(row for row in rows if row["operation"] == "category_list")
    assert category["request_id"] == "req-category"
    assert category["project_id"] == "p1"
    assert category["algorithm_id"] == "a1"
    assert category["version_id"] == "v1"
    token = next(row for row in rows if row["operation"] == "auth_token")
    assert token["business_code"] == "0"
    assert token["status"] == "SUCCESS"
    assert token["error_message"] == ""
    assert token["request"]["headers"]["Access-Key"] == "***"
    assert category["request"]["headers"]["Access-Token"] == "***"
    assert "Authorization" not in category["request"]["headers"]
    signature = next(row for row in rows if row["operation"] == "auth_signature")
    assert signature["request"]["params"]["access_secret"] == "***"
    assert signature["request"]["params"]["access_key"] == "***"


class BusinessFailureSession(FakeSession):
    def request(self, method, url, **kwargs):
        if url.endswith("/internal/algorithm/algorithm-product/listAll"):
            assert kwargs["headers"]["Access-Token"] == "token-1"
            return FakeResponse({"code": 99999, "msg": "系统内部错误，请联系管理员", "data": None})
        return super().request(method, url, **kwargs)


def test_changlian_business_failure_is_not_hidden_by_http_200(tmp_path: Path):
    audit = IntegrationAuditRepository(tmp_path)
    client = ChangLianClient(
        base_url="https://changlian.example",
        access_key="ak-sensitive",
        access_secret="secret-sensitive",
        endpoints=ChangLianEndpoints(),
        session=BusinessFailureSession(),
        audit_callback=audit.record,
    )

    try:
        client.products()
        assert False, "business code 99999 must fail"
    except Exception as error:
        assert "新畅联业务码 99999" in str(error)
        assert "系统内部错误，请联系管理员" in str(error)

    row = next(item for item in audit.list(limit=10) if item["operation"] == "product_list")
    assert row["http_status"] == 200
    assert row["business_code"] == "99999"
    assert row["status"] == "FAILED"
    assert row["error_code"] == "99999"
    assert row["error_message"] == "系统内部错误，请联系管理员"
