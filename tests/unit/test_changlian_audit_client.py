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
        if url.endswith("/internal/base/category/tree"):
            assert kwargs["headers"]["Authorization"] == "Bearer token-1"
            assert "Access-Token" not in kwargs["headers"]
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
    assert category["request"]["headers"]["Authorization"] == "***"
    assert "Access-Token" not in category["request"]["headers"]
    signature = next(row for row in rows if row["operation"] == "auth_signature")
    assert signature["request"]["params"]["access_secret"] == "***"
    assert signature["request"]["params"]["access_key"] == "***"


class BusinessFailureSession(FakeSession):
    def request(self, method, url, **kwargs):
        if url.endswith("/internal/algorithm/product-ai/listAll"):
            assert kwargs["headers"]["Authorization"] == "Bearer token-1"
            assert "Access-Token" not in kwargs["headers"]
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


class ProductListSuccessSession(FakeSession):
    def request(self, method, url, **kwargs):
        if url.endswith("/internal/algorithm/product-ai/listAll"):
            assert method.upper() == "GET"
            assert kwargs["headers"]["Authorization"] == "Bearer token-1"
            assert "Access-Token" not in kwargs["headers"]
            assert kwargs.get("params") == {"productType": "3"}
            return FakeResponse({
                "code": 0,
                "msg": "操作成功",
                "data": [{
                    "productId": 101,
                    "productType": 3,
                    "productName": "抽烟检测",
                    "productCode": "smoking",
                }],
                "total": 1,
            })
        return super().request(method, url, **kwargs)


def test_changlian_product_list_uses_official_path_and_bearer_header(tmp_path: Path):
    audit = IntegrationAuditRepository(tmp_path)
    client = ChangLianClient(
        base_url="https://changlian.example",
        access_key="ak-sensitive",
        access_secret="secret-sensitive",
        endpoints=ChangLianEndpoints(),
        session=ProductListSuccessSession(),
        audit_callback=audit.record,
    )

    result = client.products()

    assert result["code"] == 0
    assert result["data"][0]["productId"] == 101
    row = next(item for item in audit.list(limit=10) if item["operation"] == "product_list")
    assert row["status"] == "SUCCESS"
    assert row["business_code"] == "0"
    assert row["endpoint"] == "/internal/algorithm/product-ai/listAll"
    assert row["request"]["headers"]["Authorization"] == "***"
    assert "Access-Token" not in row["request"]["headers"]


class FullAlgorithmContractSession(FakeSession):
    def request(self, method, url, **kwargs):
        if "/internal/algorithm/" in url or "/internal/base/" in url:
            assert kwargs["headers"]["Authorization"] == "Bearer token-1"
            assert "Access-Token" not in kwargs["headers"]
        if url.endswith("/internal/algorithm/algorithm-version/add"):
            assert method.upper() == "POST"
            assert kwargs["json"] == {"productId": 101, "versionName": "V1", "versionNo": "1.0.0"}
            return FakeResponse({"code": 0, "msg": "操作成功", "data": 501})
        if url.endswith("/internal/algorithm/algorithm-version/edit"):
            assert kwargs["json"]["algoVersionId"] == 501
            return FakeResponse({"code": 0, "msg": "操作成功", "data": 1})
        if url.endswith("/internal/algorithm/algorithm-version/listByProduct/101"):
            return FakeResponse({"code": 0, "msg": "操作成功", "data": [{"algoVersionId": 501, "productId": 101, "weightCount": 1}]})
        if url.endswith("/internal/algorithm/algorithm-version/getInfo/501"):
            return FakeResponse({"code": 0, "msg": "操作成功", "data": {"algoVersionId": 501}})
        if url.endswith("/internal/algorithm/algorithm-version/remove/501"):
            return FakeResponse({"code": 0, "msg": "操作成功", "data": 1})
        if url.endswith("/internal/algorithm/algorithm-weight/add"):
            assert kwargs["json"] == {
                "algoVersionId": 501,
                "computePlatformId": 9,
                "chipCode": "RK3568",
                "fileName": "model.rknn",
                "filePath": "https://example/model.rknn",
            }
            return FakeResponse({"code": 0, "msg": "操作成功", "data": 701})
        if url.endswith("/internal/algorithm/algorithm-weight/edit"):
            assert kwargs["json"]["weightId"] == 701
            return FakeResponse({"code": 0, "msg": "操作成功", "data": 1})
        if url.endswith("/internal/algorithm/algorithm-weight/listByVersion/501"):
            return FakeResponse({"code": 0, "msg": "操作成功", "data": [{"weightId": 701, "algoVersionId": 501}]})
        if url.endswith("/internal/algorithm/algorithm-weight/getInfo/701"):
            return FakeResponse({"code": 0, "msg": "操作成功", "data": {"weightId": 701}})
        if url.endswith("/internal/algorithm/algorithm-weight/remove/701"):
            return FakeResponse({"code": 0, "msg": "操作成功", "data": 1})
        return super().request(method, url, **kwargs)


def test_changlian_full_version_and_weight_contract_uses_bearer_and_official_paths(tmp_path: Path):
    client = ChangLianClient(
        base_url="https://changlian.example",
        access_key="ak-sensitive",
        access_secret="secret-sensitive",
        endpoints=ChangLianEndpoints(),
        session=FullAlgorithmContractSession(),
    )

    assert client.version_create({"productId": "101", "versionName": "V1", "versionNo": "1.0.0"})["data"] == 501
    assert client.version_edit({"algoVersionId": "501", "versionName": "V1-edit"})["data"] == 1
    assert client.version_list_by_product("101")["data"][0]["algoVersionId"] == 501
    assert client.version_info("501")["data"]["algoVersionId"] == 501
    assert client.version_remove(["501"])["data"] == 1

    assert client.weight_create({
        "algoVersionId": "501",
        "computePlatformId": "9",
        "chipCode": "RK3568",
        "fileName": "model.rknn",
        "filePath": "https://example/model.rknn",
    })["data"] == 701
    assert client.weight_edit({"weightId": "701", "fileName": "model-v2.rknn"})["data"] == 1
    assert client.weight_list_by_version("501")["data"][0]["weightId"] == 701
    assert client.weight_info("701")["data"]["weightId"] == 701
    assert client.weight_remove(["701"])["data"] == 1
