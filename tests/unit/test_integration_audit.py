from pathlib import Path

from platform_core.integration_audit import IntegrationAuditRepository


def test_interaction_audit_redacts_secrets_and_preserves_diagnostic_context(tmp_path: Path):
    repository = IntegrationAuditRepository(tmp_path)

    row = repository.record({
        "provider": "changlian",
        "operation": "weight_create",
        "status": "FAILED",
        "method": "POST",
        "endpoint": "/algorithm-weight/add",
        "http_status": 400,
        "business_code": "INVALID_PLATFORM",
        "duration_ms": 412,
        "request_id": "remote-r1",
        "correlation_id": "local-c1",
        "project_id": "p1",
        "algorithm_id": "a1",
        "version_id": "v1",
        "artifact_id": "artifact-1",
        "external_algo_version_id": "av-1",
        "request": {
            "algoVersionId": "av-1",
            "computePlatformId": "cp-bad",
            "accessSecret": "never-store-me",
            "headers": {"Authorization": "Bearer hidden", "X-Trace": "trace-ok"},
        },
        "response": {"code": 400, "message": "computePlatformId 不存在", "token": "also-hidden"},
        "error_code": "INVALID_PLATFORM",
        "error_message": "computePlatformId 不存在",
    })

    assert row["request"]["accessSecret"] == "***"
    assert row["request"]["headers"]["Authorization"] == "***"
    assert row["request"]["headers"]["X-Trace"] == "trace-ok"
    assert row["response"]["token"] == "***"
    assert row["artifact_id"] == "artifact-1"
    assert row["error_message"] == "computePlatformId 不存在"

    listed = repository.list(status="FAILED", operation="weight_create")
    assert [item["log_id"] for item in listed] == [row["log_id"]]
    summary = repository.summary(hours=24)
    assert summary["total"] == 1
    assert summary["failed"] == 1
    assert summary["success"] == 0


def test_interaction_audit_tracks_unknown_remote_commit_state(tmp_path: Path):
    repository = IntegrationAuditRepository(tmp_path)
    repository.record({
        "provider": "changlian",
        "operation": "version_create",
        "status": "UNKNOWN",
        "method": "POST",
        "endpoint": "/algorithm-version/add",
        "duration_ms": 15000,
        "error_message": "connection reset after server commit",
    })

    summary = repository.summary(hours=24)
    assert summary["unknown"] == 1
    assert repository.list(status="UNKNOWN")[0]["operation"] == "version_create"



def test_interaction_audit_repairs_only_legacy_http_200_code_zero_false_failures(tmp_path: Path):
    repository = IntegrationAuditRepository(tmp_path)
    legacy = repository.record({
        "provider": "changlian",
        "operation": "auth_token",
        "status": "FAILED",
        "method": "POST",
        "endpoint": "/internal/auth/token",
        "http_status": 200,
        "business_code": "",
        "response": {
            "code": 0,
            "msg": "操作成功",
            "data": {"accessToken": "hidden-by-redaction"},
        },
        "error_message": "操作成功",
    })
    real_failure = repository.record({
        "provider": "changlian",
        "operation": "product_list",
        "status": "FAILED",
        "method": "GET",
        "endpoint": "/internal/algorithm/algorithm-product/listAll",
        "http_status": 200,
        "business_code": "99999",
        "response": {"code": 99999, "msg": "系统内部错误，请联系管理员"},
        "error_code": "99999",
        "error_message": "系统内部错误，请联系管理员",
    })

    reopened = IntegrationAuditRepository(tmp_path)

    repaired = reopened.get(legacy["log_id"])
    assert repaired["status"] == "SUCCESS"
    assert repaired["business_code"] == "0"
    assert repaired["error_code"] == ""
    assert repaired["error_message"] == ""

    unchanged = reopened.get(real_failure["log_id"])
    assert unchanged["status"] == "FAILED"
    assert unchanged["business_code"] == "99999"
    assert unchanged["error_message"] == "系统内部错误，请联系管理员"

    summary = reopened.summary(hours=24)
    assert summary["success"] == 1
    assert summary["failed"] == 1
