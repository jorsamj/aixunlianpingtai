from pathlib import Path

from platform_core.external_algorithm_platform import (
    ChangLianClient,
    ChangLianEndpoints,
    ExternalAlgorithmPlatformService,
    ExternalPlatformConfigPayload,
    EndpointPayload,
    PROVIDER_CHANGLIAN,
    SOURCE_EXTERNAL,
    algorithm_is_external_readonly,
    mirror_products_to_algorithms,
)
from platform_core.algorithms import list_algorithms, save_algorithms
from platform_core.secrets import MemorySecretStore


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        return self._body


class FakeSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/internal/auth/test-sign"):
            return FakeResponse({"code": 200, "data": {"timestamp": "100", "nonce": "abc", "signature": "sig"}})
        if url.endswith("/internal/auth/token"):
            assert kwargs["headers"]["Access-Key"] == "ak"
            assert kwargs["headers"]["Timestamp"] == "100"
            return FakeResponse({"code": 200, "data": {"accessToken": "token-1", "tokenType": "Bearer", "expiresIn": 3600}})
        if url.endswith("/algorithm-category/tree"):
            assert kwargs["headers"]["Authorization"] == "Bearer token-1"
            return FakeResponse({"code": 200, "data": [{"categoryId": "c1", "categoryName": "园区安全"}]})
        raise AssertionError(url)


def test_changlian_auth_chain_uses_test_sign_then_token_then_bearer():
    session = FakeSession()
    client = ChangLianClient(
        base_url="https://changlian.example",
        access_key="ak",
        access_secret="secret",
        endpoints=ChangLianEndpoints(),
        session=session,
    )

    body = client.category_tree()

    assert body["data"][0]["categoryId"] == "c1"
    assert [call[1].split("changlian.example")[-1] for call in session.calls] == [
        "/internal/auth/test-sign",
        "/internal/auth/token",
        "/algorithm-category/tree",
    ]


def test_external_mirror_preserves_local_and_existing_versions(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    save_algorithms(path, [
        {
            "id": "local-1",
            "name": "本地历史算法",
            "versions": [],
            "current_version_id": None,
        },
        {
            "id": "external-old",
            "name": "旧名称",
            "source_type": SOURCE_EXTERNAL,
            "provider_type": PROVIDER_CHANGLIAN,
            "external_product_id": "p1",
            "versions": [{"id": "v1", "version_name": "V1"}],
            "current_version_id": "v1",
            "version_operations": [],
        },
    ])

    result = mirror_products_to_algorithms(
        algorithms_path=path,
        products=[{"productId": "p1", "productName": "抽烟检测", "categoryId": "c1"}],
        categories=[{"categoryId": "c1", "categoryName": "行为分析"}],
        analyses_by_product={"p1": [{"analysisId": "a1", "analysisName": "视觉智能分析", "computePlatformIds": ["gpu"]}]},
        synced_at="2026-09-17T00:00:00Z",
    )

    rows = list_algorithms(path)
    local = next(row for row in rows if row["id"] == "local-1")
    external = next(row for row in rows if row.get("external_product_id") == "p1")

    assert result["updated"] == 1
    assert local["name"] == "本地历史算法"
    assert external["name"] == "抽烟检测"
    assert external["external_analysis_id"] == "a1"
    assert external["external_category_id"] == "c1"
    assert external["versions"] == [{"id": "v1", "version_name": "V1"}]
    assert external["current_version_id"] == "v1"
    assert external["master_data_readonly"] is True
    assert algorithm_is_external_readonly(path, external["id"]) is True


def test_missing_external_product_is_inactivated_not_deleted(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    save_algorithms(path, [
        {
            "id": "external-p1",
            "name": "抽烟检测",
            "source_type": SOURCE_EXTERNAL,
            "provider_type": PROVIDER_CHANGLIAN,
            "external_product_id": "p1",
            "external_active": True,
            "versions": [{"id": "v1"}],
            "current_version_id": "v1",
        },
    ])

    result = mirror_products_to_algorithms(
        algorithms_path=path,
        products=[],
        categories=[],
        analyses_by_product={},
        synced_at="2026-09-17T00:00:00Z",
    )

    rows = list_algorithms(path)
    assert result["inactivated"] == 1
    assert len(rows) == 1
    assert rows[0]["external_active"] is False
    assert rows[0]["versions"] == [{"id": "v1"}]


class FakeChangLianClient:
    def __init__(self, **_kwargs):
        pass

    def probe(self):
        return {"ok": True, "provider": "changlian", "auth": "ok"}

    def category_tree(self):
        return {"data": [{"categoryId": "c1", "categoryName": "园区", "children": []}]}

    def products(self):
        return {"data": [{"productId": "p1", "productName": "抽烟检测", "categoryId": "c1"}]}

    def analyses(self, product_id):
        assert product_id == "p1"
        return {"data": [{"analysisId": "a1", "analysisName": "视觉智能分析"}]}

    def compute_platforms(self):
        return {"data": [{"computePlatformId": "cp1", "computePlatformName": "ONNX"}]}


def test_service_sync_saves_redacted_config_cache_history_and_mirror(tmp_path: Path):
    memory = MemorySecretStore()
    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=FakeChangLianClient,
    )
    config = service.save(ExternalPlatformConfigPayload(
        mode="external",
        provider="changlian",
        base_url="https://changlian.example/",
        access_key="ak-123",
        access_secret="secret-456",
        endpoints=EndpointPayload(),
    ))
    assert config["base_url"] == "https://changlian.example"
    assert config["credentials"]["configured"] is True
    assert "secret-456" not in str(config)

    algorithms_path = tmp_path / "project" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    result = service.sync(project_id="p-local", algorithms_path=algorithms_path)

    assert result["ok"] is True
    assert result["mirror"]["added"] == 1
    assert service.repository.cache()["products"][0]["productId"] == "p1"
    assert service.repository.history()[0]["status"] == "success"
    row = list_algorithms(algorithms_path)[0]
    assert row["external_product_id"] == "p1"
    assert row["source_type"] == SOURCE_EXTERNAL


def test_auto_sync_due_respects_switch_and_interval(tmp_path: Path):
    memory = MemorySecretStore()
    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=FakeChangLianClient,
    )
    service.save(ExternalPlatformConfigPayload(
        mode="external",
        provider="changlian",
        base_url="https://changlian.example",
        auto_sync_enabled=True,
        auto_sync_interval_seconds=600,
        access_key="ak",
        access_secret="secret",
        endpoints=EndpointPayload(),
    ))
    assert service.auto_sync_due() is True
    service.repository.append_history({
        "id": "recent",
        "sync_type": "manual",
        "status": "success",
        "finished_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat().replace("+00:00", "Z"),
    })
    assert service.auto_sync_due() is False


def test_public_config_marks_test_sign_as_integration_bridge(tmp_path: Path):
    memory = MemorySecretStore()
    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=FakeChangLianClient,
    )
    public = service.public_config()
    assert public["auth_mode"] == "test_sign_bridge"
    assert public["auto_sync_interval_seconds"] == 600
