from datetime import datetime, timezone
from pathlib import Path

import pytest

from platform_core.external_algorithm_platform import (
    ChangLianClient,
    ChangLianEndpoints,
    ExternalAlgorithmPlatformService,
    ExternalPlatformConfigPayload,
    EndpointPayload,
    PROVIDER_CHANGLIAN,
    SOURCE_EXTERNAL,
    _analysis_is_enabled,
    _analysis_is_visual,
    _analysis_summary,
    algorithm_is_external_readonly,
    assert_external_algorithm_master_data_current,
    mirror_products_to_algorithms,
    resolve_external_training_analysis,
)
from platform_core.algorithms import list_algorithms, save_algorithms
from platform_core.errors import PlatformError
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
            assert kwargs.get("params") == {"access_key": "ak", "access_secret": "secret"}
            assert "json" not in kwargs
            return FakeResponse({"code": 200, "data": {"timestamp": "100", "nonce": "abc", "signature": "sig"}})
        if url.endswith("/internal/auth/token"):
            assert kwargs["headers"]["Access-Key"] == "ak"
            assert kwargs["headers"]["Timestamp"] == "100"
            return FakeResponse({"code": 200, "data": {"accessToken": "token-1", "tokenType": "Bearer", "expiresIn": 3600}})
        if url.endswith("/internal/base/category/tree"):
            assert kwargs["headers"]["Authorization"] == "Bearer token-1"
            assert "Access-Token" not in kwargs["headers"]
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
        "/internal/base/category/tree",
    ]


def test_changlian_default_endpoints_match_documented_core_contract():
    endpoints = ChangLianEndpoints()
    assert endpoints.test_sign == "/internal/auth/test-sign"
    assert endpoints.token == "/internal/auth/token"
    assert endpoints.category_tree == "/internal/base/category/tree"
    assert endpoints.product_list == "/internal/algorithm/product-ai/listAll"
    assert endpoints.analysis_by_product == "/internal/algorithm/algorithm-analysis/listByProduct/{productId}"
    assert endpoints.compute_platform_list == "/internal/base/compute-platform/listAll"
    assert endpoints.version_create == "/internal/algorithm/algorithm-version/add"
    assert endpoints.weight_create == "/internal/algorithm/algorithm-weight/add"
    assert endpoints.logout == "/internal/auth/logout"
    assert endpoints.category_list == "/internal/base/category/list"
    assert endpoints.category_list_all == "/internal/base/category/listAll"
    assert endpoints.product_list_page == "/internal/algorithm/product-ai/list"
    assert endpoints.product_detail == "/internal/algorithm/product-ai/getInfo/{productId}"
    assert endpoints.analysis_list_page == "/internal/algorithm/algorithm-analysis/list"
    assert endpoints.analysis_list_all == "/internal/algorithm/algorithm-analysis/listAll"
    assert endpoints.analysis_detail == "/internal/algorithm/algorithm-analysis/getInfo/{analysisId}"
    assert endpoints.compute_platform_list_page == "/internal/base/compute-platform/list"
    assert endpoints.version_edit == "/internal/algorithm/algorithm-version/edit"
    assert endpoints.version_remove == "/internal/algorithm/algorithm-version/remove/{algoVersionIds}"
    assert endpoints.version_list_page == "/internal/algorithm/algorithm-version/list"
    assert endpoints.version_list_by_product == "/internal/algorithm/algorithm-version/listByProduct/{productId}"
    assert endpoints.version_list_by_analysis == "/internal/algorithm/algorithm-version/listByAnalysis/{analysisId}"
    assert endpoints.version_list_all == "/internal/algorithm/algorithm-version/listAll"
    assert endpoints.version_detail == "/internal/algorithm/algorithm-version/getInfo/{algoVersionId}"
    assert endpoints.weight_edit == "/internal/algorithm/algorithm-weight/edit"
    assert endpoints.weight_remove == "/internal/algorithm/algorithm-weight/remove/{weightIds}"
    assert endpoints.weight_list_page == "/internal/algorithm/algorithm-weight/list"
    assert endpoints.weight_list_by_version == "/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}"
    assert endpoints.weight_list_by_product == "/internal/algorithm/algorithm-weight/listByProduct/{productId}"
    assert endpoints.weight_detail == "/internal/algorithm/algorithm-weight/getInfo/{weightId}"


def test_changlian_legacy_endpoint_paths_migrate_to_internal_namespaces():
    endpoints = ChangLianEndpoints.from_mapping({
        "category_tree": "/algorithm-category/tree",
        "product_list": "/algorithm-product/listAll",
        "analysis_by_product": "/algorithm-product-analysis/listByProduct/{productId}",
        "compute_platform_list": "/compute-platform/listAll",
        "version_create": "/algorithm-version/add",
        "weight_create": "/algorithm-weight/add",
    })

    assert endpoints.category_tree == "/internal/base/category/tree"
    assert endpoints.product_list == "/internal/algorithm/product-ai/listAll"
    assert endpoints.analysis_by_product == "/internal/algorithm/algorithm-analysis/listByProduct/{productId}"
    assert endpoints.compute_platform_list == "/internal/base/compute-platform/listAll"
    assert endpoints.version_create == "/internal/algorithm/algorithm-version/add"
    assert endpoints.weight_create == "/internal/algorithm/algorithm-weight/add"


class NeverCalledSession:
    def __init__(self):
        self.calls = []

    def request(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        raise AssertionError("invalid mutation payload must fail before any HTTP request")


@pytest.mark.parametrize(
    "payload",
    [
        {"versionName": "正式版本 V1"},
        {"analysisId": 101, "productId": 201, "versionName": "正式版本 V1"},
    ],
)
def test_version_create_requires_exactly_one_analysis_or_product(payload):
    session = NeverCalledSession()
    client = ChangLianClient(
        base_url="https://changlian.example",
        access_key="ak",
        access_secret="secret",
        endpoints=ChangLianEndpoints(),
        session=session,
    )

    with pytest.raises(ValueError, match="二选一"):
        client.version_create(payload)

    assert session.calls == []


class MutationSession:
    def __init__(self):
        self.calls = []

    def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        if url.endswith("/internal/algorithm/algorithm-version/add"):
            return FakeResponse({"code": 200, "data": 501})
        if url.endswith("/internal/algorithm/algorithm-weight/add"):
            return FakeResponse({"code": 200, "data": 701})
        raise AssertionError(url)


def _authenticated_mutation_client(session):
    client = ChangLianClient(
        base_url="https://changlian.example",
        access_key="ak",
        access_secret="secret",
        endpoints=ChangLianEndpoints(),
        session=session,
    )
    client._token = "token-1"
    client._token_expires_at = 10**18
    return client


def test_version_create_allows_optional_version_name_and_version_no():
    session = MutationSession()
    client = _authenticated_mutation_client(session)

    body = client.version_create({"analysisId": 101})

    assert body == {"code": 200, "data": 501}
    _, url, kwargs = session.calls[-1]
    assert url.endswith("/internal/algorithm/algorithm-version/add")
    assert kwargs["json"] == {"analysisId": 101}
    assert kwargs["headers"]["Authorization"] == "Bearer token-1"


def test_weight_create_requires_only_algo_version_id_at_official_client_layer():
    missing = NeverCalledSession()
    client = ChangLianClient(
        base_url="https://changlian.example",
        access_key="ak",
        access_secret="secret",
        endpoints=ChangLianEndpoints(),
        session=missing,
    )
    with pytest.raises(ValueError, match="algoVersionId"):
        client.weight_create({"fileName": "best.pt"})
    assert missing.calls == []

    session = MutationSession()
    client = _authenticated_mutation_client(session)
    body = client.weight_create({
        "algoVersionId": 501,
        "computePlatformId": 91,
        "fileName": "best.pt",
        "filePath": "https://models.example/best.pt",
    })

    assert body == {"code": 200, "data": 701}
    _, url, kwargs = session.calls[-1]
    assert url.endswith("/internal/algorithm/algorithm-weight/add")
    assert kwargs["json"] == {
        "algoVersionId": 501,
        "computePlatformId": 91,
        "fileName": "best.pt",
        "filePath": "https://models.example/best.pt",
    }
    assert "chipCode" not in kwargs["json"]


def test_changlian_auth_audit_redacts_credentials_before_callback():
    session = FakeSession()
    events = []
    client = ChangLianClient(
        base_url="https://changlian.example",
        access_key="ak",
        access_secret="secret",
        endpoints=ChangLianEndpoints(),
        session=session,
        audit_callback=events.append,
    )

    client.category_tree()

    signature = next(event for event in events if event.get("operation") == "auth_signature")
    assert signature["request"]["params"] == {"access_key": "***", "access_secret": "***"}
    token = next(event for event in events if event.get("operation") == "auth_token")
    assert token["request"]["headers"]["Access-Key"] == "***"
    assert token["request"]["headers"]["Signature"] == "***"
    category = next(event for event in events if event.get("operation") == "category_list")
    assert category["request"]["headers"]["Authorization"] == "***"
    assert "Access-Token" not in category["request"]["headers"]


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
        analyses_by_product={"p1": [{"analysisId": "a1", "analysisName": "视觉智能分析", "analysisType": 1, "status": 1, "computePlatformIds": ["gpu"]}]},
        synced_at="2026-09-17T00:00:00Z",
    )

    rows = list_algorithms(path)
    local = next(row for row in rows if row["id"] == "local-1")
    external = next(row for row in rows if row.get("external_product_id") == "p1")

    assert result["updated"] == 1
    assert local["name"] == "本地历史算法"
    assert external["name"] == "抽烟检测"
    assert external["external_analysis_id"] == "a1"
    assert external["external_analyses"] == [{
        "analysis_id": "a1",
        "analysis_name": "视觉智能分析",
        "analysis_type": "1",
        "status": "1",
        "compute_platform_ids": ["gpu"],
    }]
    assert external["external_category_id"] == "c1"
    assert external["versions"] == [{"id": "v1", "version_name": "V1"}]
    assert external["current_version_id"] == "v1"
    assert external["master_data_readonly"] is True
    assert algorithm_is_external_readonly(path, external["id"]) is True


def test_missing_external_product_is_deleted_with_versions(tmp_path: Path):
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
        {
            "id": "local-keep",
            "name": "本地算法",
            "versions": [],
            "current_version_id": None,
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
    assert result["deleted"] == 1
    assert result["inactivated"] == 0
    assert [row["id"] for row in rows] == ["local-keep"]


def test_remote_status_two_is_retained_as_inactive_not_deleted(tmp_path: Path):
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
        products=[{
            "productId": "p1",
            "productName": "抽烟检测",
            "categoryId": "c1",
            "status": 2,
        }],
        categories=[{"categoryId": "c1", "categoryName": "行为分析"}],
        analyses_by_product={"p1": []},
        synced_at="2026-09-17T00:00:00Z",
    )

    rows = list_algorithms(path)
    assert result["deleted"] == 0
    assert len(rows) == 1
    assert rows[0]["external_active"] is False
    assert rows[0]["external_status"] == "2"
    assert rows[0]["versions"] == [{"id": "v1"}]


class FakeChangLianClient:
    def __init__(self, **_kwargs):
        pass

    def probe(self):
        return {"ok": True, "provider": "changlian", "auth": "ok"}

    def category_tree(self):
        return {"data": [{"categoryId": "c1", "categoryName": "园区", "children": []}]}

    def products(self, **_filters):
        return {"data": [{"productId": "p1", "productName": "抽烟检测", "categoryId": "c1", "status": 1, "productType": 3}]}

    def product_info(self, product_id):
        assert product_id == "p1"
        return {"data": {"productId": "p1", "productName": "抽烟检测", "categoryId": "c1", "status": 1, "productType": 3}}

    def analyses(self, product_id):
        assert product_id == "p1"
        return {"data": [{"analysisId": "a1", "analysisName": "视觉智能分析", "analysisType": 1, "status": 1}]}

    def analysis_info(self, analysis_id):
        assert analysis_id == "a1"
        return {"data": {
            "analysisId": "a1",
            "productId": "p1",
            "analysisName": "视觉智能分析",
            "analysisType": 1,
            "status": 1,
        }}

    def compute_platforms(self):
        return {"data": [{"computePlatformId": "cp1", "computePlatformName": "ONNX"}]}

    def version_list_by_product(self, product_id):
        assert product_id == "p1"
        return {"data": [{"algoVersionId": "av1", "productId": "p1", "weightCount": 1}]}

    def weight_list_by_version(self, algo_version_id):
        assert algo_version_id == "av1"
        return {"data": [{"weightId": "w1", "algoVersionId": "av1"}]}


class NestedCategoryChangLianClient(FakeChangLianClient):
    def category_tree(self):
        return {
            "data": [{
                "categoryId": "root",
                "categoryName": "安全",
                "children": [{
                    "categoryId": "child",
                    "categoryName": "行为安全",
                    "children": [{
                        "categoryId": "leaf",
                        "categoryName": "抽烟",
                    }],
                }],
            }],
        }


def test_connection_and_diagnostics_count_full_category_tree(tmp_path: Path):
    memory = MemorySecretStore()
    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=NestedCategoryChangLianClient,
    )
    service.save(ExternalPlatformConfigPayload(
        mode="external",
        provider="changlian",
        base_url="https://changlian.example",
        access_key="ak",
        access_secret="secret",
        endpoints=EndpointPayload(),
    ))

    tested = service.test_connection()
    diagnosed = service.diagnose()

    tested_categories = next(row for row in tested["steps"] if row["key"] == "categories")
    diagnosed_categories = next(row for row in diagnosed["steps"] if row["key"] == "categories")
    assert tested_categories["count"] == 3
    assert diagnosed_categories["count"] == 3
    assert diagnosed["category_sample_available"] is True


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


def test_sync_uses_complete_product_set_and_purges_only_truly_missing_algorithm(tmp_path: Path):
    calls = []

    class CompleteListClient(FakeChangLianClient):
        state = {"rows": []}

        def products(self, **filters):
            calls.append(dict(filters))
            return {"data": list(self.state["rows"])}

    class Purger:
        def __init__(self):
            self.items = []

        def purge(self, project_id, algorithm):
            self.items.append((project_id, algorithm["id"], algorithm["external_product_id"]))
            return {
                "tasks_deleted": 2,
                "artifacts_deleted": 3,
                "remote_objects_deleted": 3,
                "publications_deleted": 1,
            }

    memory = MemorySecretStore()
    purger = Purger()
    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=CompleteListClient,
        local_purger=purger,
    )
    service.save(ExternalPlatformConfigPayload(
        mode="external",
        provider="changlian",
        base_url="https://changlian.example",
        access_key="ak",
        access_secret="secret",
        endpoints=EndpointPayload(),
    ))
    algorithms_path = tmp_path / "project-hard-delete" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [{
        "id": "external-p1",
        "name": "已从远端删除",
        "source_type": SOURCE_EXTERNAL,
        "provider_type": PROVIDER_CHANGLIAN,
        "external_product_id": "p1",
        "external_active": True,
        "versions": [{"id": "v1"}],
        "current_version_id": "v1",
    }])

    result = service.sync(
        project_id="project-hard-delete",
        algorithms_path=algorithms_path,
    )

    assert calls[-1].get("status") == ""
    assert purger.items == [("project-hard-delete", "external-p1", "p1")]
    assert result["mirror"]["deleted"] == 1
    assert list_algorithms(algorithms_path) == []
    counts = result["sync"]["counts"]
    assert counts["algorithms_purged"] == 1
    assert counts["tasks_deleted"] == 2
    assert counts["artifacts_deleted"] == 3
    assert counts["remote_objects_deleted"] == 3
    assert counts["publications_deleted"] == 1


def test_sync_rejects_concurrent_project_sync_without_mutating_state(tmp_path: Path):
    service = _configured_external_service(tmp_path, FakeChangLianClient)
    algorithms_path = tmp_path / "project-sync-busy" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])
    before_cache = service.repository.cache()
    lock = service._sync_lock("p-sync-busy")

    with lock.acquire(timeout=0):
        with pytest.raises(Exception) as error:
            service.sync(project_id="p-sync-busy", algorithms_path=algorithms_path)

    assert getattr(error.value, "code", "") == "EXTERNAL_PLATFORM_SYNC_BUSY"
    assert getattr(error.value, "status_code", 409) == 409
    assert list_algorithms(algorithms_path) == []
    assert service.repository.cache() == before_cache
    assert service.repository.history() == []


def test_sync_cache_write_failure_does_not_mutate_algorithm_mirror(tmp_path: Path, monkeypatch):
    import platform_core.external_algorithm_platform as platform_module

    service = _configured_external_service(tmp_path, FakeChangLianClient)
    algorithms_path = tmp_path / "project-cache-failure" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])
    mirror_calls = []

    monkeypatch.setattr(
        platform_module,
        "mirror_products_to_algorithms",
        lambda **kwargs: mirror_calls.append(kwargs) or {"added": 1},
    )
    monkeypatch.setattr(
        service.repository,
        "save_cache",
        lambda _value: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(Exception) as error:
        service.sync(project_id="p-cache-failure", algorithms_path=algorithms_path)

    assert getattr(error.value, "code", "") == "EXTERNAL_PLATFORM_SYNC_FAILED"
    assert mirror_calls == []
    assert list_algorithms(algorithms_path) == []
    assert service.repository.history()[0]["status"] == "failed"


def test_sync_mirror_failure_restores_previous_master_data_cache(tmp_path: Path, monkeypatch):
    import platform_core.external_algorithm_platform as platform_module

    service = _configured_external_service(tmp_path, FakeChangLianClient)
    algorithms_path = tmp_path / "project-mirror-failure" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])
    previous_cache = {
        "provider": "changlian",
        "synced_at": "2026-09-18T12:00:00Z",
        "categories": [{"categoryId": "old-category"}],
        "products": [{"productId": "old-product"}],
        "analyses_by_product": {"old-product": [{"analysisId": "old-analysis"}]},
        "compute_platforms": [{"computePlatformId": "old-compute"}],
    }
    service.repository.save_cache(previous_cache)

    monkeypatch.setattr(
        platform_module,
        "mirror_products_to_algorithms",
        lambda **_kwargs: (_ for _ in ()).throw(RuntimeError("sqlite mirror failed")),
    )

    with pytest.raises(Exception) as error:
        service.sync(project_id="p-mirror-failure", algorithms_path=algorithms_path)

    assert getattr(error.value, "code", "") == "EXTERNAL_PLATFORM_SYNC_FAILED"
    restored = service.repository.cache()
    assert restored["synced_at"] == previous_cache["synced_at"]
    assert restored["products"] == previous_cache["products"]
    assert restored["analyses_by_product"] == previous_cache["analyses_by_product"]
    assert restored["compute_platforms"] == previous_cache["compute_platforms"]
    assert list_algorithms(algorithms_path) == []
    assert service.repository.history()[0]["status"] == "failed"


def test_sync_binds_algorithm_mirror_to_master_data_digest(tmp_path: Path):
    service = _configured_external_service(tmp_path, FakeChangLianClient)
    algorithms_path = tmp_path / "project-digest" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    service.sync(project_id="p-digest", algorithms_path=algorithms_path)

    cache = service.repository.cache()
    row = list_algorithms(algorithms_path)[0]
    assert len(cache["master_data_digest"]) == 64
    assert row["external_master_data_digest"] == cache["master_data_digest"]
    assert_external_algorithm_master_data_current(tmp_path, row)


def test_readiness_and_training_guard_reject_stale_project_master_data(tmp_path: Path):
    service = _configured_external_service(tmp_path, FakeChangLianClient)
    algorithms_path = tmp_path / "project-stale-digest" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])
    service.sync(project_id="p-stale-digest", algorithms_path=algorithms_path)
    row = list_algorithms(algorithms_path)[0]

    changed_cache = dict(service.repository.cache())
    changed_cache["master_data_digest"] = "f" * 64
    service.repository.save_cache(changed_cache)

    readiness = service.readiness(algorithms_path=algorithms_path)
    project = next(item for item in readiness["checks"] if item["key"] == "project_algorithms")
    assert project["status"] == "blocked"
    assert "旧主数据" in project["detail"]
    assert readiness["ready"] is False

    with pytest.raises(Exception) as error:
        assert_external_algorithm_master_data_current(tmp_path, row)
    assert getattr(error.value, "code", "") == "EXTERNAL_MASTER_DATA_STALE"
    assert getattr(error.value, "status_code", 409) == 409


def test_auto_sync_due_uses_fixed_china_time_slots_and_manual_sync_does_not_consume_them(tmp_path: Path):
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
        auto_sync_enabled=False,
        auto_sync_interval_seconds=600,
        access_key="ak",
        access_secret="secret",
        endpoints=EndpointPayload(),
    ))

    before_first = datetime(2026, 9, 24, 23, 59, tzinfo=timezone.utc)
    first_slot = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
    assert service.auto_sync_due(now=before_first) is False
    assert service.auto_sync_due(now=first_slot) is True

    service.repository.append_history({
        "id": "manual-after-eight",
        "sync_type": "manual",
        "status": "success",
        "finished_at": "2026-09-25T00:05:00Z",
    })
    assert service.auto_sync_due(now=datetime(2026, 9, 25, 0, 6, tzinfo=timezone.utc)) is True

    service.repository.append_history({
        "id": "auto-eight",
        "sync_type": "auto",
        "status": "success",
        "finished_at": "2026-09-25T00:07:00Z",
    })
    assert service.auto_sync_due(now=datetime(2026, 9, 25, 3, 59, tzinfo=timezone.utc)) is False
    assert service.auto_sync_due(now=datetime(2026, 9, 25, 4, 0, tzinfo=timezone.utc)) is True

    service.repository.append_history({
        "id": "auto-noon-failed",
        "sync_type": "auto",
        "status": "failed",
        "finished_at": "2026-09-25T04:01:00Z",
    })
    assert service.auto_sync_due(now=datetime(2026, 9, 25, 6, 59, tzinfo=timezone.utc)) is False
    assert service.auto_sync_due(now=datetime(2026, 9, 25, 7, 0, tzinfo=timezone.utc)) is True

    service.repository.append_history({
        "id": "auto-three",
        "sync_type": "auto",
        "status": "success",
        "finished_at": "2026-09-25T07:02:00Z",
    })
    assert service.auto_sync_due(now=datetime(2026, 9, 25, 23, 59, tzinfo=timezone.utc)) is False
    assert service.auto_sync_due(now=datetime(2026, 9, 26, 0, 0, tzinfo=timezone.utc)) is True


def test_public_config_marks_test_sign_as_integration_bridge(tmp_path: Path):
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
        auto_sync_enabled=False,
        auto_sync_interval_seconds=600,
        auto_publish_enabled=False,
        access_key="ak",
        access_secret="secret",
        endpoints=EndpointPayload(),
    ))
    public = service.public_config()
    assert public["auth_mode"] == "test_sign_bridge"
    assert public["mode"] == "external"
    assert public["auto_sync_enabled"] is True
    assert public["auto_publish_enabled"] is True
    assert public["auto_sync_interval_seconds"] == 600
    assert public["auto_sync_schedule_local_times"] == ["08:00", "12:00", "15:00"]
    assert public["auto_sync_timezone"] == "Asia/Shanghai"

def test_external_training_analysis_requires_choice_for_multiple_methods():
    import pytest

    algorithm = {
        "id": "external-1",
        "name": "抽烟检测",
        "source_type": SOURCE_EXTERNAL,
        "provider_type": PROVIDER_CHANGLIAN,
        "external_active": True,
        "external_analysis_id": "a1",
        "external_analysis_ids": ["a1", "a2"],
        "external_analyses": [
            {"analysis_id": "a1", "analysis_type": "1", "status": "1"},
            {"analysis_id": "a2", "analysis_type": "1", "status": "1"},
        ],
    }
    with pytest.raises(Exception) as missing:
        resolve_external_training_analysis(algorithm, "")
    assert getattr(missing.value, "code", "") == "EXTERNAL_ANALYSIS_REQUIRED"
    assert resolve_external_training_analysis(algorithm, "a2") == "a2"




@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (1, True),
        ("1", True),
        (0, False),
        ("0", False),
        (False, False),
        (True, False),
        ("false", False),
        (2, False),
        ("enabled", False),
        (None, False),
    ],
)
def test_analysis_enabled_requires_exact_status_one(status, expected):
    row = {"status": status} if status is not None else {}
    assert _analysis_is_enabled(row) is expected


@pytest.mark.parametrize(
    ("analysis_type", "expected"),
    [
        (1, True),
        ("1", True),
        (2, False),
        ("2", False),
        (3, False),
        ("3", False),
        ("vision", False),
        ("视觉智能分析", False),
        (None, False),
    ],
)
def test_analysis_visual_requires_exact_analysis_type_one(analysis_type, expected):
    row = {"analysisType": analysis_type} if analysis_type is not None else {"analysisName": "视觉智能分析"}
    assert _analysis_is_visual(row) is expected


def test_analysis_summary_preserves_numeric_zero_status():
    row = {
        "analysisId": "vision-off",
        "analysisType": 1,
        "status": 0,
        "analysisName": "停用视觉分析",
    }

    summary = _analysis_summary(row)

    assert summary["status"] == "0"


def test_external_sync_only_exposes_enabled_visual_analyses_for_training(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    save_algorithms(path, [])
    mirror_products_to_algorithms(
        algorithms_path=path,
        products=[{"productId": "p1", "productName": "抽烟检测", "categoryId": "c1"}],
        categories=[{"categoryId": "c1", "categoryName": "行为分析"}],
        analyses_by_product={
            "p1": [
                {"analysisId": "vision-on", "analysisType": 1, "status": 1, "analysisName": "视觉智能分析"},
                {"analysisId": "reserved-on", "analysisType": 2, "status": 1, "analysisName": "预留分析"},
                {"analysisId": "llm-on", "analysisType": 3, "status": 1, "analysisName": "大模型智能分析"},
                {"analysisId": "vision-off", "analysisType": 1, "status": 0, "analysisName": "停用视觉分析"},
            ],
        },
    )

    algorithm = list_algorithms(path)[0]
    assert algorithm["external_analysis_id"] == "vision-on"
    assert algorithm["external_analysis_ids"] == ["vision-on"]
    assert {row["analysis_id"] for row in algorithm["external_analyses"]} == {
        "vision-on", "reserved-on", "llm-on", "vision-off",
    }



def test_external_sync_fails_closed_when_status_or_analysis_type_is_missing(tmp_path: Path):
    path = tmp_path / "algorithms.json"
    save_algorithms(path, [])
    mirror_products_to_algorithms(
        algorithms_path=path,
        products=[{"productId": "p1", "productName": "抽烟检测", "categoryId": "c1"}],
        categories=[{"categoryId": "c1", "categoryName": "行为分析"}],
        analyses_by_product={
            "p1": [
                {"analysisId": "missing-status", "analysisType": 1, "analysisName": "视觉智能分析"},
                {"analysisId": "missing-type", "status": 1, "analysisName": "视觉智能分析"},
                {"analysisId": "name-only", "analysisName": "视觉智能分析"},
            ],
        },
    )

    algorithm = list_algorithms(path)[0]
    assert algorithm["external_analysis_id"] == ""
    assert algorithm["external_analysis_ids"] == []

    with pytest.raises(Exception) as missing:
        resolve_external_training_analysis(algorithm, "")
    assert getattr(missing.value, "code", "") == "EXTERNAL_VISUAL_ANALYSIS_MISSING"

def test_external_training_rejects_non_visual_or_disabled_analysis():
    algorithm = {
        "id": "external-1",
        "name": "抽烟检测",
        "source_type": SOURCE_EXTERNAL,
        "provider_type": PROVIDER_CHANGLIAN,
        "external_active": True,
        "external_analysis_id": "vision-on",
        "external_analysis_ids": ["vision-on"],
        "external_analyses": [
            {"analysis_id": "vision-on", "analysis_type": "1", "status": "1"},
            {"analysis_id": "llm-on", "analysis_type": "3", "status": "1"},
            {"analysis_id": "vision-off", "analysis_type": "1", "status": "0"},
        ],
    }

    with pytest.raises(Exception) as llm:
        resolve_external_training_analysis(algorithm, "llm-on")
    assert getattr(llm.value, "code", "") == "EXTERNAL_ANALYSIS_NOT_VISUAL"

    with pytest.raises(Exception) as disabled:
        resolve_external_training_analysis(algorithm, "vision-off")
    assert getattr(disabled.value, "code", "") == "EXTERNAL_ANALYSIS_NOT_VISUAL"

    assert resolve_external_training_analysis(algorithm, "vision-on") == "vision-on"


def test_external_training_fails_closed_when_product_has_no_enabled_visual_analysis():
    algorithm = {
        "id": "external-1",
        "name": "大模型分析产品",
        "source_type": SOURCE_EXTERNAL,
        "provider_type": PROVIDER_CHANGLIAN,
        "external_active": True,
        "external_analysis_id": "",
        "external_analysis_ids": [],
        "external_analyses": [
            {"analysis_id": "llm-on", "analysis_type": "3", "status": "1"},
        ],
    }

    with pytest.raises(Exception) as missing:
        resolve_external_training_analysis(algorithm, "")
    assert getattr(missing.value, "code", "") == "EXTERNAL_VISUAL_ANALYSIS_MISSING"


def test_external_training_rejects_inactive_product():
    import pytest

    algorithm = {
        "id": "external-1",
        "name": "抽烟检测",
        "source_type": SOURCE_EXTERNAL,
        "provider_type": PROVIDER_CHANGLIAN,
        "external_active": False,
        "external_analysis_ids": ["a1"],
    }
    with pytest.raises(Exception) as inactive:
        resolve_external_training_analysis(algorithm, "a1")
    assert getattr(inactive.value, "code", "") == "EXTERNAL_ALGORITHM_INACTIVE"


def test_diagnostics_reports_read_only_master_data_checks(tmp_path: Path):
    memory = MemorySecretStore()
    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=FakeChangLianClient,
    )
    service.save(ExternalPlatformConfigPayload(
        mode="external", provider="changlian", base_url="https://changlian.example",
        access_key="ak", access_secret="secret", endpoints=EndpointPayload(),
    ))
    result = service.diagnose()
    assert result["ok"] is True
    assert [row["key"] for row in result["steps"]] == ["auth", "categories", "products", "compute_platforms", "analysis", "analysis_detail", "versions", "weights"]



def test_draft_connection_test_does_not_persist_credentials_or_url(tmp_path: Path):
    memory = MemorySecretStore()
    captured = []

    class CapturingClient(FakeChangLianClient):
        def __init__(self, **kwargs):
            captured.append(dict(kwargs))

    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=CapturingClient,
    )
    service.save(ExternalPlatformConfigPayload(
        mode="external", provider="changlian", base_url="https://saved.example",
        access_key="saved-ak", access_secret="saved-secret", endpoints=EndpointPayload(),
    ))
    draft = ExternalPlatformConfigPayload(
        mode="external", provider="changlian", base_url="https://draft.example",
        access_key="draft-ak", access_secret="draft-secret", endpoints=EndpointPayload(),
    )

    result = service.test_connection(draft)

    assert result["ok"] is True
    assert result["base_url"] == "https://draft.example"
    assert [row["key"] for row in result["steps"]] == ["auth", "categories", "products", "compute_platforms", "analysis", "analysis_detail", "versions", "weights"]
    assert "draft-secret" not in str(result)
    assert service.repository.config()["base_url"] == "https://saved.example"
    ref = service.repository.config()["credential_ref"]
    stored = service._credential_store().get(ref)
    assert stored == {"access_key_id": "saved-ak", "access_secret": "saved-secret"}
    assert captured[-1]["access_key"] == "draft-ak"
    assert captured[-1]["access_secret"] == "draft-secret"


def test_draft_connection_blank_secret_reuses_saved_secret_without_exposing_it(tmp_path: Path):
    memory = MemorySecretStore()
    captured = []

    class CapturingClient(FakeChangLianClient):
        def __init__(self, **kwargs):
            captured.append(dict(kwargs))

    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=CapturingClient,
    )
    service.save(ExternalPlatformConfigPayload(
        mode="external", provider="changlian", base_url="https://saved.example",
        access_key="saved-ak", access_secret="saved-secret", endpoints=EndpointPayload(),
    ))
    draft = ExternalPlatformConfigPayload(
        mode="external", provider="changlian", base_url="https://saved.example",
        access_key=None, access_secret=None, endpoints=EndpointPayload(),
    )

    result = service.test_connection(draft)

    assert result["ok"] is True
    assert captured[-1]["access_key"] == "saved-ak"
    assert captured[-1]["access_secret"] == "saved-secret"
    assert "saved-secret" not in str(result)



class MissingProductIdClient(FakeChangLianClient):
    def products(self, **_filters):
        return {"data": [{"productName": "缺少 Product ID", "categoryId": "c1"}]}


class MissingAnalysisIdClient(FakeChangLianClient):
    def analyses(self, product_id):
        assert product_id == "p1"
        return {"data": [{"analysisName": "缺少 Analysis ID"}]}


class MissingComputePlatformIdClient(FakeChangLianClient):
    def compute_platforms(self):
        return {"data": [{"computePlatformName": "缺少 Compute Platform ID"}]}


def _configured_external_service(tmp_path: Path, client_factory):
    memory = MemorySecretStore()
    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=client_factory,
    )
    service.save(ExternalPlatformConfigPayload(
        mode="external",
        provider="changlian",
        base_url="https://changlian.example",
        access_key="ak",
        access_secret="secret",
        endpoints=EndpointPayload(),
    ))
    return service


def test_connection_fails_when_product_records_have_no_business_id(tmp_path: Path):
    service = _configured_external_service(tmp_path, MissingProductIdClient)

    result = service.test_connection()

    assert result["ok"] is False
    products = next(row for row in result["steps"] if row["key"] == "products")
    assert products["status"] == "failed"
    assert "正式业务 ID" in products["detail"]
    analysis = next(row for row in result["steps"] if row["key"] == "analysis")
    assert analysis["status"] == "skipped"


def test_sync_fails_closed_when_product_id_is_missing(tmp_path: Path):
    service = _configured_external_service(tmp_path, MissingProductIdClient)
    algorithms_path = tmp_path / "project-product-id" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    with pytest.raises(Exception) as error:
        service.sync(project_id="p-product-id", algorithms_path=algorithms_path)

    assert getattr(error.value, "code", "") == "EXTERNAL_PRODUCT_ID_MISSING"
    assert list_algorithms(algorithms_path) == []
    assert service.repository.cache().get("provider") is None
    assert service.repository.history()[0]["status"] == "failed"


def test_sync_fails_closed_when_analysis_id_is_missing(tmp_path: Path):
    service = _configured_external_service(tmp_path, MissingAnalysisIdClient)
    algorithms_path = tmp_path / "project-analysis-id" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    with pytest.raises(Exception) as error:
        service.sync(project_id="p-analysis-id", algorithms_path=algorithms_path)

    assert getattr(error.value, "code", "") == "EXTERNAL_ANALYSIS_ID_MISSING"
    assert list_algorithms(algorithms_path) == []
    assert service.repository.cache().get("provider") is None
    assert service.repository.history()[0]["status"] == "failed"


def test_sync_fails_closed_when_compute_platform_id_is_missing(tmp_path: Path):
    service = _configured_external_service(tmp_path, MissingComputePlatformIdClient)
    algorithms_path = tmp_path / "project-compute-id" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    with pytest.raises(Exception) as error:
        service.sync(project_id="p-compute-id", algorithms_path=algorithms_path)

    assert getattr(error.value, "code", "") == "EXTERNAL_COMPUTE_PLATFORM_ID_MISSING"
    assert list_algorithms(algorithms_path) == []
    assert service.repository.cache().get("provider") is None
    assert service.repository.history()[0]["status"] == "failed"



def test_readiness_blocks_until_saved_synced_and_project_algorithm_exists(tmp_path: Path):
    memory = MemorySecretStore()
    service = ExternalAlgorithmPlatformService(
        data_dir=tmp_path,
        secret_store_factory=lambda: memory,
        client_factory=FakeChangLianClient,
    )
    algorithms_path = tmp_path / "project-ready" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    before = service.readiness(algorithms_path=algorithms_path)
    assert before["ready"] is False
    assert before["human_login_required"] is False
    assert before["auth_type"] == "application_credentials"
    assert before["scope"] == "master_data_training"
    assert "external_mode" in before["blocking_keys"]
    assert "credentials" in before["blocking_keys"]
    assert "products" in before["blocking_keys"]
    human = next(row for row in before["checks"] if row["key"] == "human_login")
    assert human["status"] == "not_required"
    assert "AccessKey / AccessSecret" in human["detail"]

    service.save(ExternalPlatformConfigPayload(
        mode="external",
        provider="changlian",
        base_url="https://changlian.example",
        access_key="ak",
        access_secret="secret",
        endpoints=EndpointPayload(),
    ))
    service.sync(project_id="p-ready", algorithms_path=algorithms_path)

    after = service.readiness(algorithms_path=algorithms_path)
    assert after["ready"] is True
    assert after["blocking_keys"] == []
    assert next(row for row in after["checks"] if row["key"] == "categories")["count"] == 1
    assert next(row for row in after["checks"] if row["key"] == "products")["count"] == 1
    assert next(row for row in after["checks"] if row["key"] == "analyses")["count"] == 1
    assert next(row for row in after["checks"] if row["key"] == "trainable_analyses")["count"] == 1
    assert next(row for row in after["checks"] if row["key"] == "compute_platforms")["count"] == 1
    project = next(row for row in after["checks"] if row["key"] == "project_algorithms")
    assert project["status"] == "ready"
    assert project["count"] == 1


def test_readiness_does_not_treat_inactive_external_algorithm_as_trainable(tmp_path: Path):
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
        access_key="ak",
        access_secret="secret",
        endpoints=EndpointPayload(),
    ))
    algorithms_path = tmp_path / "project-inactive" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [{
        "id": "external-inactive",
        "name": "已下架算法",
        "source_type": SOURCE_EXTERNAL,
        "provider_type": PROVIDER_CHANGLIAN,
        "external_product_id": "p-old",
        "external_active": False,
        "versions": [],
    }])
    service.repository.save_cache({
        "provider": "changlian",
        "synced_at": "2026-09-19T12:00:00Z",
        "categories": [{"categoryId": "c1"}],
        "products": [{"productId": "p1"}],
        "analyses_by_product": {"p1": [{"analysisId": "a1", "analysisType": 1, "status": 1}]},
        "compute_platforms": [{"computePlatformId": "cp1"}],
    })
    service.repository.append_history({
        "id": "sync-ready",
        "sync_type": "manual",
        "status": "success",
        "finished_at": "2026-09-19T12:00:00Z",
    })

    readiness = service.readiness(algorithms_path=algorithms_path)
    project = next(row for row in readiness["checks"] if row["key"] == "project_algorithms")
    assert project["status"] == "blocked"
    assert project["count"] == 0
    assert readiness["ready"] is False


def test_v12_training_entry_defers_external_preflight_to_durable_prepare():
    source = (Path(__file__).resolve().parents[2] / "app.py").read_text(encoding="utf-8")
    start = source.index('@app.post("/api/v12/projects/{project_id}/train/start")')
    end = source.index("def _v48_resource_key", start)
    block = source[start:end]

    split_gate = "if not payload.split_mode:"
    enqueue = "return _enqueue_explicit_training(project_id, payload)"

    for marker in (split_gate, enqueue):
        assert marker in block
    assert block.index(split_gate) < block.index(enqueue)
    assert "_refresh_external_training_algorithm(" not in block
    assert "assert_external_algorithm_master_data_current(" not in block
    assert "resolve_external_training_analysis(" not in block


def test_training_create_has_one_external_truth_owner_plus_compatibility_delegate():
    source = (Path(__file__).resolve().parents[2] / "app.py").read_text(encoding="utf-8")

    enqueue_start = source.index("def _enqueue_explicit_training(project_id: str, payload: TrainReq)")
    enqueue_end = source.index("def check_ultralytics_train_runtime", enqueue_start)
    enqueue_block = source[enqueue_start:enqueue_end]
    assert '"training_input_state": "PREPARING"' in enqueue_block
    assert "TaskKind.TRAINING_PREPARE" in enqueue_block
    assert "_refresh_external_training_algorithm(" not in enqueue_block
    assert "assert_external_algorithm_master_data_current(" not in enqueue_block
    assert "resolve_external_training_analysis(" not in enqueue_block

    v12_start = source.index('@app.post("/api/v12/projects/{project_id}/train/start")')
    v12_end = source.index("def _v48_resource_key", v12_start)
    v12_block = source[v12_start:v12_end]
    assert "return _enqueue_explicit_training(project_id, payload)" in v12_block
    assert "_refresh_external_training_algorithm(" not in v12_block
    assert "assert_external_algorithm_master_data_current(" not in v12_block
    assert "resolve_external_training_analysis(" not in v12_block

    compatibility_start = source.index('@app.post("/api/projects/{project_id}/train/start")')
    compatibility_end = source.index("def resolve_server", compatibility_start)
    compatibility_block = source[compatibility_start:compatibility_end]
    assert "return v12_start_train(project_id, payload)" in compatibility_block
    assert "_refresh_external_training_algorithm(" not in compatibility_block
    assert "assert_external_algorithm_master_data_current(" not in compatibility_block

    prepare = (
        Path(__file__).resolve().parents[2] / "platform_core" / "remote_training_tasks.py"
    ).read_text(encoding="utf-8")
    owner_start = prepare.index("class TrainingPrepareHandler:")
    owner_block = prepare[owner_start:]
    assert "service.training_preflight(" in owner_block
    assert "assert_external_algorithm_master_data_current(self.data_dir, algorithm)" in owner_block
    assert "resolve_external_training_analysis(" in owner_block
    assert "activate_prepared_training(" in owner_block


class DetailOverridesSummaryClient(FakeChangLianClient):
    def analyses(self, product_id):
        assert product_id == "p1"
        return {"data": [{"analysisId": "a1", "analysisName": "视觉智能分析", "analysisType": 1, "status": 1}]}

    def analysis_info(self, analysis_id):
        assert analysis_id == "a1"
        return {"data": {
            "analysisId": "a1", "productId": "p1",
            "analysisName": "视觉智能分析", "analysisType": 1, "status": 0,
        }}


class DetailCompletesSummaryClient(FakeChangLianClient):
    def analyses(self, product_id):
        assert product_id == "p1"
        return {"data": [{"analysisId": "a1", "analysisName": "视觉智能分析"}]}

    def analysis_info(self, analysis_id):
        assert analysis_id == "a1"
        return {"data": {
            "analysisId": "a1", "productId": "p1",
            "analysisName": "视觉智能分析", "analysisType": 1, "status": 1,
        }}


class IncompleteAnalysisDetailClient(FakeChangLianClient):
    def analysis_info(self, analysis_id):
        assert analysis_id == "a1"
        return {"data": {
            "analysisId": "a1", "productId": "p1",
            "analysisName": "视觉智能分析", "analysisType": 1,
        }}


def test_sync_uses_analysis_get_info_as_authoritative_training_truth(tmp_path: Path):
    service = _configured_external_service(tmp_path, DetailOverridesSummaryClient)
    algorithms_path = tmp_path / "detail-truth" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    result = service.sync(project_id="p-detail-off", algorithms_path=algorithms_path)

    assert result["ok"] is True
    algorithm = list_algorithms(algorithms_path)[0]
    assert algorithm["external_analysis_ids"] == []
    assert algorithm["external_analyses"][0]["status"] == "0"


def test_sync_can_train_when_get_info_proves_enabled_visual_analysis(tmp_path: Path):
    service = _configured_external_service(tmp_path, DetailCompletesSummaryClient)
    algorithms_path = tmp_path / "detail-complete" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    result = service.sync(project_id="p-detail-on", algorithms_path=algorithms_path)

    assert result["ok"] is True
    algorithm = list_algorithms(algorithms_path)[0]
    assert algorithm["external_analysis_ids"] == ["a1"]
    assert algorithm["external_analyses"][0]["analysis_type"] == "1"
    assert algorithm["external_analyses"][0]["status"] == "1"


def test_sync_fails_closed_when_analysis_get_info_omits_status(tmp_path: Path):
    service = _configured_external_service(tmp_path, IncompleteAnalysisDetailClient)
    algorithms_path = tmp_path / "detail-incomplete" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    with pytest.raises(PlatformError) as error:
        service.sync(project_id="p-detail-incomplete", algorithms_path=algorithms_path)

    assert error.value.code == "EXTERNAL_ANALYSIS_DETAIL_INCOMPLETE"


def test_connection_fails_when_analysis_detail_contract_is_incomplete(tmp_path: Path):
    service = _configured_external_service(tmp_path, IncompleteAnalysisDetailClient)

    result = service.test_connection()

    assert result["ok"] is False
    detail = next(row for row in result["steps"] if row["key"] == "analysis_detail")
    assert detail["status"] == "failed"
    assert "status" in detail["detail"]


def test_readiness_blocks_training_when_all_synced_analyses_are_non_trainable(tmp_path: Path):
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
        access_key="ak",
        access_secret="secret",
        endpoints=EndpointPayload(),
    ))
    algorithms_path = tmp_path / "project-non-trainable" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [{
        "id": "external-non-trainable",
        "name": "大模型分析算法",
        "source_type": SOURCE_EXTERNAL,
        "provider_type": PROVIDER_CHANGLIAN,
        "external_product_id": "p1",
        "external_active": True,
        "external_master_data_digest": "digest-current",
        "external_analyses": [{
            "analysis_id": "a1",
            "analysis_type": "3",
            "status": "1",
        }],
        "versions": [],
    }])
    service.repository.save_cache({
        "provider": "changlian",
        "synced_at": "2026-09-20T12:00:00Z",
        "master_data_digest": "digest-current",
        "categories": [{"categoryId": "c1"}],
        "products": [{"productId": "p1"}],
        "analyses_by_product": {
            "p1": [{"analysisId": "a1", "analysisType": 3, "status": 1}],
        },
        "compute_platforms": [{"computePlatformId": "cp1"}],
    })
    service.repository.append_history({
        "id": "sync-ready-non-trainable",
        "sync_type": "manual",
        "status": "success",
        "finished_at": "2026-09-20T12:00:00Z",
    })

    readiness = service.readiness(algorithms_path=algorithms_path)

    trainable = next(row for row in readiness["checks"] if row["key"] == "trainable_analyses")
    project = next(row for row in readiness["checks"] if row["key"] == "project_algorithms")
    assert trainable["status"] == "blocked"
    assert trainable["count"] == 0
    assert project["status"] == "blocked"
    assert project["count"] == 0
    assert "trainable_analyses" in readiness["blocking_keys"]
    assert readiness["ready"] is False



def test_training_preflight_rechecks_changlian_and_blocks_non_visual_change(tmp_path: Path):
    state = {"analysis_id": "a1", "analysis_type": 1, "analysis_status": 1, "product_status": 1}

    class MutableTrainingPreflightClient(FakeChangLianClient):
        def products(self, **_filters):
            return {"data": [{
                "productId": "p1", "productName": "抽烟检测", "categoryId": "c1",
                "status": state["product_status"], "productType": 3,
            }]}

        def product_info(self, product_id):
            assert product_id == "p1"
            return {"data": {
                "productId": "p1", "productName": "抽烟检测", "categoryId": "c1",
                "status": state["product_status"], "productType": 3,
            }}

        def analyses(self, product_id):
            assert product_id == "p1"
            return {"data": [{
                "analysisId": state["analysis_id"],
                "analysisName": "当前分析方式",
                "analysisType": state["analysis_type"],
                "status": state["analysis_status"],
            }]}

        def analysis_info(self, analysis_id):
            assert analysis_id == state["analysis_id"]
            return {"data": {
                "analysisId": state["analysis_id"],
                "productId": "p1",
                "analysisName": "当前分析方式",
                "analysisType": state["analysis_type"],
                "status": state["analysis_status"],
            }}

    service = _configured_external_service(tmp_path, MutableTrainingPreflightClient)
    algorithms_path = tmp_path / "preflight-nonvisual" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])
    service.sync(project_id="preflight-nonvisual", algorithms_path=algorithms_path)
    algorithm = list_algorithms(algorithms_path)[0]

    state["analysis_type"] = 2

    with pytest.raises(PlatformError) as blocked:
        service.training_preflight(
            project_id="preflight-nonvisual",
            algorithms_path=algorithms_path,
            algorithm_id=algorithm["id"],
        )

    assert blocked.value.code == "EXTERNAL_VISUAL_ANALYSIS_REQUIRED"
    assert blocked.value.status_code == 409
    assert "status=1" in blocked.value.solution
    assert "analysisType=1" in blocked.value.solution


def test_training_preflight_refreshes_drifted_visual_analysis_through_canonical_sync(tmp_path: Path):
    state = {"analysis_id": "a1"}

    class MutableVisualTrainingPreflightClient(FakeChangLianClient):
        def product_info(self, product_id):
            assert product_id == "p1"
            return {"data": {
                "productId": "p1", "productName": "抽烟检测", "categoryId": "c1",
                "status": 1, "productType": 3,
            }}

        def analyses(self, product_id):
            assert product_id == "p1"
            return {"data": [{
                "analysisId": state["analysis_id"],
                "analysisName": f"视觉方式-{state['analysis_id']}",
                "analysisType": 1,
                "status": 1,
            }]}

        def analysis_info(self, analysis_id):
            assert analysis_id == state["analysis_id"]
            return {"data": {
                "analysisId": state["analysis_id"],
                "productId": "p1",
                "analysisName": f"视觉方式-{state['analysis_id']}",
                "analysisType": 1,
                "status": 1,
            }}

    service = _configured_external_service(tmp_path, MutableVisualTrainingPreflightClient)
    algorithms_path = tmp_path / "preflight-drift" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])
    service.sync(project_id="preflight-drift", algorithms_path=algorithms_path)
    before = list_algorithms(algorithms_path)[0]
    assert before["external_analysis_ids"] == ["a1"]

    state["analysis_id"] = "a2"
    result = service.training_preflight(
        project_id="preflight-drift",
        algorithms_path=algorithms_path,
        algorithm_id=before["id"],
    )

    assert result["ready"] is True
    assert result["source"] == "changlian"
    assert result["refreshed"] is True
    assert result["trainable_analysis_ids"] == ["a2"]
    current = list_algorithms(algorithms_path)[0]
    assert current["id"] == before["id"]
    assert current["external_analysis_ids"] == ["a2"]
    assert current["external_analysis_id"] == "a2"


def test_training_preflight_blocks_remote_product_that_was_disabled_after_sync(tmp_path: Path):
    state = {"product_status": 1}

    class DisabledAfterSyncClient(FakeChangLianClient):
        def products(self, **_filters):
            return {"data": [{
                "productId": "p1", "productName": "抽烟检测", "categoryId": "c1",
                "status": state["product_status"], "productType": 3,
            }]}

        def product_info(self, product_id):
            assert product_id == "p1"
            return {"data": {
                "productId": "p1", "productName": "抽烟检测", "categoryId": "c1",
                "status": state["product_status"], "productType": 3,
            }}

    service = _configured_external_service(tmp_path, DisabledAfterSyncClient)
    algorithms_path = tmp_path / "preflight-disabled" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])
    service.sync(project_id="preflight-disabled", algorithms_path=algorithms_path)
    algorithm = list_algorithms(algorithms_path)[0]

    state["product_status"] = 0
    with pytest.raises(PlatformError) as blocked:
        service.training_preflight(
            project_id="preflight-disabled",
            algorithms_path=algorithms_path,
            algorithm_id=algorithm["id"],
        )

    assert blocked.value.code == "EXTERNAL_ALGORITHM_INACTIVE"
    assert blocked.value.status_code == 409



class _DeferredSyncThread:
    instances = []

    def __init__(self, *, target, name, daemon):
        self.target = target
        self.name = name
        self.daemon = daemon
        self.started = False
        type(self).instances.append(self)

    def start(self):
        self.started = True

    def run(self):
        assert self.started is True
        self.target()


def test_manual_sync_operation_is_durable_reused_and_finishes_through_canonical_sync(tmp_path: Path):
    _DeferredSyncThread.instances.clear()
    service = _configured_external_service(tmp_path, FakeChangLianClient)
    service.thread_factory = _DeferredSyncThread
    algorithms_path = tmp_path / "operation-project" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    first = service.start_sync(
        project_id="operation-project",
        algorithms_path=algorithms_path,
        sync_type="manual",
    )
    second = service.start_sync(
        project_id="operation-project",
        algorithms_path=algorithms_path,
        sync_type="manual",
    )

    assert first["accepted"] is True
    assert second["accepted"] is False
    assert first["operation"]["operation_id"] == second["operation"]["operation_id"]
    assert first["operation"]["status"] == "queued"
    assert first["operation"]["trigger_source"] == "manual"
    assert len(_DeferredSyncThread.instances) == 1

    _DeferredSyncThread.instances[0].run()

    operation = service.current_sync_operation("operation-project")
    assert operation["status"] == "success"
    assert operation["current_phase"] == "completed"
    assert operation["processed_products"] == 1
    assert operation["total_products"] == 1
    assert operation["success_count"] == 1
    assert operation["error_count"] == 0
    assert operation["counts"]["products"] == 1
    assert operation["counts"]["added"] == 1
    assert service.repository.history()[0]["operation_id"] == operation["operation_id"]
    assert list_algorithms(algorithms_path)[0]["external_product_id"] == "p1"


def test_sync_operation_cas_prevents_old_operation_from_overwriting_newer_one(tmp_path: Path):
    service = _configured_external_service(tmp_path, FakeChangLianClient)
    first = service._new_sync_operation("cas-project", "manual")
    claimed, _ = service.repository.claim_sync_operation("cas-project", first)
    assert claimed is True

    service.repository.update_sync_operation(
        "cas-project",
        first["operation_id"],
        {"status": "success", "current_phase": "completed"},
    )
    second = service._new_sync_operation("cas-project", "auto")
    claimed, second_current = service.repository.claim_sync_operation("cas-project", second)
    assert claimed is True

    returned = service.repository.update_sync_operation(
        "cas-project",
        first["operation_id"],
        {"status": "failed", "current_phase": "failed"},
    )

    assert returned["operation_id"] == second_current["operation_id"]
    assert service.repository.sync_operation("cas-project")["operation_id"] == second_current["operation_id"]
    assert service.repository.sync_operation("cas-project")["status"] == "queued"


def test_sync_operation_exposes_real_product_phase_counters_during_fetch(tmp_path: Path):
    observed = []
    state = {}

    class ObservedClient(FakeChangLianClient):
        def analyses(self, product_id):
            observed.append(dict(state["service"].repository.sync_operation("phase-project")))
            return super().analyses(product_id)

    service = _configured_external_service(tmp_path, ObservedClient)
    state["service"] = service
    algorithms_path = tmp_path / "phase-project" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    service.sync(project_id="phase-project", algorithms_path=algorithms_path, sync_type="auto")

    assert observed
    current = observed[0]
    assert current["status"] == "running"
    assert current["current_phase"] == "fetch_analyses"
    assert current["processed_products"] == 0
    assert current["total_products"] == 1
    final = service.current_sync_operation("phase-project")
    assert final["processed_products"] == 1
    assert final["last_request_duration_ms"] >= 0


def test_external_sync_router_uses_background_operation_owner():
    source = (Path(__file__).resolve().parents[2] / "platform_core" / "external_algorithm_platform.py").read_text(encoding="utf-8")
    route_start = source.index('@router.post("/sync")')
    route_end = source.index('@router.get("/sync-history")', route_start)
    block = source[route_start:route_end]

    assert "service.start_sync(" in block
    assert '@router.get("/sync-operation")' in block
    assert "service.current_sync_operation(project_id)" in block
    assert "service.sync(" not in block



class BulkAnalysisListClient(FakeChangLianClient):
    analyses_calls = 0
    analysis_list_all_calls = 0
    detail_calls = []

    def products(self, **_filters):
        return {"data": [
            {"productId": "p1", "productName": "抽烟检测", "categoryId": "c1", "status": 1, "productType": 3},
            {"productId": "p2", "productName": "打电话检测", "categoryId": "c1", "status": 1, "productType": 3},
        ]}

    def analysis_list_all(self, **_filters):
        type(self).analysis_list_all_calls += 1
        return {"data": [
            {"analysisId": "a1", "productId": "p1", "analysisName": "抽烟视觉分析", "analysisType": 1, "status": 1},
            {"analysisId": "a2", "productId": "p2", "analysisName": "打电话视觉分析", "analysisType": 1, "status": 1},
        ]}

    def analyses(self, product_id):
        type(self).analyses_calls += 1
        raise AssertionError(f"listAll 可完整分组时不应再调用 listByProduct: {product_id}")

    def analysis_info(self, analysis_id):
        type(self).detail_calls.append(str(analysis_id))
        mapping = {
            "a1": {"productId": "p1", "analysisName": "抽烟视觉分析"},
            "a2": {"productId": "p2", "analysisName": "打电话视觉分析"},
        }
        row = mapping[str(analysis_id)]
        return {"data": {
            "analysisId": str(analysis_id),
            "productId": row["productId"],
            "analysisName": row["analysisName"],
            "analysisType": 1,
            "status": 1,
        }}


def test_sync_uses_analysis_list_all_once_and_keeps_detail_truth_per_analysis(tmp_path: Path):
    BulkAnalysisListClient.analyses_calls = 0
    BulkAnalysisListClient.analysis_list_all_calls = 0
    BulkAnalysisListClient.detail_calls = []
    service = _configured_external_service(tmp_path, BulkAnalysisListClient)
    algorithms_path = tmp_path / "bulk-analysis-index" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    result = service.sync(
        project_id="bulk-analysis-index",
        algorithms_path=algorithms_path,
        sync_type="manual",
    )

    assert result["ok"] is True
    assert BulkAnalysisListClient.analysis_list_all_calls == 1
    assert BulkAnalysisListClient.analyses_calls == 0
    assert BulkAnalysisListClient.detail_calls == ["a1", "a2"]
    operation = service.current_sync_operation("bulk-analysis-index")
    assert operation["analysis_list_source"] == "list_all"
    assert operation["processed_products"] == 2
    assert operation["total_products"] == 2
    rows = sorted(list_algorithms(algorithms_path), key=lambda row: row["external_product_id"])
    assert [row["external_product_id"] for row in rows] == ["p1", "p2"]
    assert [row["external_analysis_ids"] for row in rows] == [["a1"], ["a2"]]


class BulkAnalysisFallbackClient(FakeChangLianClient):
    analysis_list_all_calls = 0
    analyses_calls = 0

    def analysis_list_all(self, **_filters):
        type(self).analysis_list_all_calls += 1
        return {"data": [{
            "analysisId": "a1",
            "analysisName": "视觉智能分析",
            "analysisType": 1,
            "status": 1,
        }]}

    def analyses(self, product_id):
        type(self).analyses_calls += 1
        return super().analyses(product_id)


def test_sync_falls_back_to_list_by_product_when_list_all_cannot_prove_product_ownership(tmp_path: Path):
    BulkAnalysisFallbackClient.analysis_list_all_calls = 0
    BulkAnalysisFallbackClient.analyses_calls = 0
    service = _configured_external_service(tmp_path, BulkAnalysisFallbackClient)
    algorithms_path = tmp_path / "bulk-analysis-fallback" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    result = service.sync(
        project_id="bulk-analysis-fallback",
        algorithms_path=algorithms_path,
        sync_type="manual",
    )

    assert result["ok"] is True
    assert BulkAnalysisFallbackClient.analysis_list_all_calls == 1
    assert BulkAnalysisFallbackClient.analyses_calls == 1
    operation = service.current_sync_operation("bulk-analysis-fallback")
    assert operation["analysis_list_source"] == "per_product_fallback"
    assert "productId" in operation["analysis_list_fallback_reason"]


class BulkSummaryEnabledButDetailDisabledClient(FakeChangLianClient):
    def analysis_list_all(self, **_filters):
        return {"data": [{
            "analysisId": "a1",
            "productId": "p1",
            "analysisName": "视觉智能分析",
            "analysisType": 1,
            "status": 1,
        }]}

    def analyses(self, product_id):
        raise AssertionError("优化路径不应查询 listByProduct")

    def analysis_info(self, analysis_id):
        assert analysis_id == "a1"
        return {"data": {
            "analysisId": "a1",
            "productId": "p1",
            "analysisName": "视觉智能分析",
            "analysisType": 1,
            "status": 0,
        }}


def test_bulk_analysis_index_never_overrides_authoritative_detail_training_status(tmp_path: Path):
    service = _configured_external_service(tmp_path, BulkSummaryEnabledButDetailDisabledClient)
    algorithms_path = tmp_path / "bulk-detail-truth" / "algorithms.json"
    algorithms_path.parent.mkdir(parents=True)
    save_algorithms(algorithms_path, [])

    result = service.sync(
        project_id="bulk-detail-truth",
        algorithms_path=algorithms_path,
        sync_type="manual",
    )

    assert result["ok"] is True
    algorithm = list_algorithms(algorithms_path)[0]
    assert algorithm["external_analysis_ids"] == []
    assert algorithm["external_analyses"][0]["status"] == "0"
    assert service.current_sync_operation("bulk-detail-truth")["analysis_list_source"] == "list_all"
