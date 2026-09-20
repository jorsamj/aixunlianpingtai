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
    algorithm_is_external_readonly,
    assert_external_algorithm_master_data_current,
    mirror_products_to_algorithms,
    resolve_external_training_analysis,
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
    assert external["external_analyses"] == [{
        "analysis_id": "a1",
        "analysis_name": "视觉智能分析",
        "analysis_type": "",
        "status": "",
        "compute_platform_ids": ["gpu"],
    }]
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
    }
    with pytest.raises(Exception) as missing:
        resolve_external_training_analysis(algorithm, "")
    assert getattr(missing.value, "code", "") == "EXTERNAL_ANALYSIS_REQUIRED"
    assert resolve_external_training_analysis(algorithm, "a2") == "a2"




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
                {"analysisId": "llm-on", "analysisType": 3, "status": 1, "analysisName": "大模型智能分析"},
                {"analysisId": "vision-off", "analysisType": 1, "status": 0, "analysisName": "停用视觉分析"},
            ],
        },
    )

    algorithm = list_algorithms(path)[0]
    assert algorithm["external_analysis_id"] == "vision-on"
    assert algorithm["external_analysis_ids"] == ["vision-on"]
    assert {row["analysis_id"] for row in algorithm["external_analyses"]} == {
        "vision-on", "llm-on", "vision-off",
    }


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
    assert [row["key"] for row in result["steps"]] == ["auth", "categories", "products", "compute_platforms", "analysis", "versions", "weights"]



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
    assert [row["key"] for row in result["steps"]] == ["auth", "categories", "products", "compute_platforms", "analysis", "versions", "weights"]
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
    def products(self):
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
        "analyses_by_product": {"p1": [{"analysisId": "a1"}]},
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
