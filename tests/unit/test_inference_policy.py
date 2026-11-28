import json
import time
from platform_core.inference_policy import config_fingerprint, resolve_inference_policy


def test_legacy_env_credential_attestation_matches_frozen_configuration(monkeypatch, tmp_path):
    from platform_core.annotation_runtime import freeze_model_config
    monkeypatch.setenv('LEGACY_INFERENCE_TEST_KEY', 'isolated-secret')
    cfg = dict(config(), secret_ref='env:LEGACY_INFERENCE_TEST_KEY')
    install(monkeypatch, tmp_path, cfg, expires_at=time.time()+60)
    frozen, _ = freeze_model_config(cfg)
    assert config_fingerprint(cfg) == config_fingerprint(frozen)
    assert frozen['inference_execution_policy']['concurrency'] == 2
    assert 'isolated-secret' not in json.dumps(frozen)


def config():
    return {"id": "test", "provider_adapter": "wevisone_vl", "base_url": "http://gateway/v1", "model_name": "2b", "coordinate_config_revision": "a"}


def install(monkeypatch, tmp_path, cfg, **changes):
    entry = {"config_fingerprint": config_fingerprint(cfg), "expires_at": 200,
             "mode": "native_gateway", "concurrency": 2, "execution_deadline_seconds": 120,
             "request_load_balancing_verified": True,
             "instances": [{"instance_id": value, "model_revision": "revision-sha", "native_route_verified": True} for value in ("one", "two")]}
    entry.update(changes)
    path = tmp_path / "operator.json"
    path.write_text(json.dumps({"configs": {cfg["id"]: entry}}))
    monkeypatch.setenv("INFERENCE_CAPACITY_MANIFEST", str(path))


def test_unknown_and_browser_forgery_stay_serial(monkeypatch):
    monkeypatch.delenv("INFERENCE_CAPACITY_MANIFEST", raising=False)
    cfg = config()
    cfg.update(inference_policy={"concurrency": 8}, capacity_evidence={"verified": True})
    result = resolve_inference_policy(cfg, now=100)
    assert result["concurrency"] == result["max_attempts"] == 1
    assert result["evidence_status"] == "unknown"


def test_server_native_gateway_attestation_expires_and_invalidates(monkeypatch, tmp_path):
    cfg = config()
    install(monkeypatch, tmp_path, cfg)
    result = resolve_inference_policy(cfg, now=100)
    assert result["concurrency"] == 2
    assert result["upstream_deadline_seconds"] == 120
    assert result["evidence_status"] == "operator_attested"
    assert resolve_inference_policy(cfg, now=200)["concurrency"] == 1
    cfg["coordinate_config_revision"] = "changed"
    assert resolve_inference_policy(cfg, now=100)["concurrency"] == 1


def test_duplicate_instances_wrong_revision_native_route_or_deadline_fail_closed(monkeypatch, tmp_path):
    cfg = config()
    for updates in ({"instances": []}, {"execution_deadline_seconds": 0},
                    {"execution_deadline_seconds": float("inf")},
                    {"request_load_balancing_verified": False},
                    {"instances": [{"instance_id": "one", "model_revision": "r", "native_route_verified": True}] * 2}):
        install(monkeypatch, tmp_path, cfg, **updates)
        assert resolve_inference_policy(cfg, now=100)["concurrency"] == 1


def test_quota_domain_shared_across_configs_models_separate_accounts(monkeypatch):
    monkeypatch.delenv("INFERENCE_CAPACITY_MANIFEST", raising=False)
    first = dict(config(), inference_account_identity="opaque-account")
    other = dict(first, id="another", model_name="another-model")
    assert resolve_inference_policy(first)["domain"] == resolve_inference_policy(other)["domain"]
    other["inference_account_identity"] = "separate-account"
    assert resolve_inference_policy(first)["domain"] != resolve_inference_policy(other)["domain"]
    assert "opaque-account" not in resolve_inference_policy(first)["domain"]


def test_cloud_server_quota_bounds(monkeypatch, tmp_path):
    cfg = dict(config(), provider_adapter="aliyun_qwen")
    install(monkeypatch, tmp_path, cfg, mode="cloud_quota", quota_scope="account-server-scope", concurrency=100,
            max_attempts=100, total_retry_seconds=100)
    result = resolve_inference_policy(cfg, now=100)
    assert result["concurrency"] == 8
    assert result["max_attempts"] == 3
    assert result["total_retry_seconds"] == 30


def test_invalid_evidence_cannot_change_domain(monkeypatch, tmp_path):
    cfg = config()
    baseline = resolve_inference_policy(cfg, now=100)["domain"]
    install(monkeypatch, tmp_path, cfg, quota_scope="forged-scope", config_fingerprint="wrong")
    assert resolve_inference_policy(cfg, now=100)["domain"] == baseline
    install(monkeypatch, tmp_path, cfg, quota_scope="expired-scope", expires_at=99)
    assert resolve_inference_policy(cfg, now=100)["domain"] == baseline


def test_explicit_service_capacity_and_custom_cloud(monkeypatch, tmp_path):
    for adapter, mode in (("ollama", "service_quota"), ("local_openai", "cloud_quota")):
        cfg = dict(config(), provider_adapter=adapter)
        install(monkeypatch, tmp_path, cfg, mode=mode, quota_scope="operator-quota", service_capacity_verified=True)
        result = resolve_inference_policy(cfg, now=100)
        assert result["concurrency"] == 2
        assert result["evidence_expires_at"] == 200


def test_malformed_operator_values_fail_closed(monkeypatch, tmp_path):
    cfg = config()
    for updates in ({"instances": [{"instance_id": ["bad"], "model_revision": "r", "native_route_verified": True}] * 2},
                    {"instances": [{"instance_id": "a", "model_revision": {}, "native_route_verified": True}] * 2},
                    {"expires_at": float("inf")}, {"expires_at": float("nan")},
                    {"quota_scope": ["bad"]}, {"quota_scope": {}}, {"quota_scope": "  "},
                    {"instances": "two"}, {"mode": ["native_gateway"]}):
        install(monkeypatch, tmp_path, cfg, **updates)
        assert resolve_inference_policy(cfg, now=100)["concurrency"] == 1
    path = tmp_path / "bad.json"
    monkeypatch.setenv("INFERENCE_CAPACITY_MANIFEST", str(path))
    for content in ("{", "[]", '{"configs": []}', '{"configs":{"test":[]}}'):
        path.write_text(content)
        assert resolve_inference_policy(cfg, now=100)["concurrency"] == 1


def test_raw_legacy_fingerprint_matches_frozen_normalization(monkeypatch):
    from platform_core.annotation_runtime import freeze_model_config
    monkeypatch.delenv("INFERENCE_CAPACITY_MANIFEST", raising=False)
    raw = {"id": "legacy", "model_name": "old", "provider_type": "local_openai",
           "base_url": "http://old.invalid/v1", "api_key": "secret-value", "access_secret": "hidden",
           "headers_json": {" Authorization ": "Bearer hidden", "X-Access-Token": "hidden", "X-Trace": "keep"}}
    snapshot, _ = freeze_model_config(raw)
    assert config_fingerprint(raw) == config_fingerprint(snapshot)


def test_accepted_scope_is_additional_domain_not_replacement(monkeypatch, tmp_path):
    cfg = config()
    baseline = resolve_inference_policy(cfg, now=100)["domain"]
    install(monkeypatch, tmp_path, cfg, quota_scope="shared-quota")
    accepted = resolve_inference_policy(cfg, now=100)
    assert accepted["domain"] == baseline
    assert accepted["shared_domain"] != baseline
    expired = resolve_inference_policy(cfg, now=201)
    assert expired["domain"] == baseline
    assert expired["concurrency"] == 1
    assert expired["shared_domain"] == accepted["shared_domain"]
