"""Server-owned, fail-closed inference capacity evidence.

INFERENCE_CAPACITY_MANIFEST names an operator-controlled JSON file, never a web
payload. Entries are keyed by configuration id. /models is not capacity proof.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import time
from pathlib import Path
from urllib.parse import urlsplit


def _hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def config_fingerprint(config):
    # Match freeze_model_config normalization so an old raw saved configuration
    # and its executable snapshot describe exactly the same evidence binding.
    from .auto_label import coordinate_contract
    canonical = dict(config)
    if not canonical.get("inference_account_identity") and canonical.get("secret_ref"):
        from .secrets import KeyringSecretStore
        reference = str(canonical["secret_ref"])
        try:
            credential = (os.environ.get(reference[4:]) if reference.startswith("env:")
                          else KeyringSecretStore().get(reference))
        except Exception:
            # Unavailable credentials cannot validate capacity evidence.
            credential = None
        if credential:
            canonical["inference_account_identity"] = hashlib.sha256(credential.encode()).hexdigest()
    canonical.update(coordinate_contract(canonical))
    secret_headers = {"authorization", "x-api-key", "api-key", "apikey", "x-access-key", "x-access-token"}
    headers = canonical.get("headers_json")
    canonical["headers_json"] = {str(key): value for key, value in headers.items()
                                 if str(key).strip().lower() not in secret_headers} if isinstance(headers, dict) else {}
    return _hash({key: value for key, value in canonical.items() if key not in {
        "inference_policy", "inference_execution_policy", "capacity_evidence", "created_at", "updated_at",
        "coordinate_validation", "default_for_annotation", "default_for_training_ai", "enabled",
    } and key not in {"api_key", "_api_key", "access_key", "access_key_id", "access_key_secret",
                        "access_secret", "password", "secret", "token"}})


def _bounded(value, default, maximum):
    try:
        return max(1, min(maximum, int(value)))
    except (ValueError, TypeError, OverflowError):
        return default


def _manifest_entry(config):
    try:
        path = os.environ.get("INFERENCE_CAPACITY_MANIFEST", "")
        if not path:
            return {}
        content = json.loads(Path(path).read_text(encoding="utf-8"))
        entry = content.get("configs", {}).get(str(config.get("id") or ""), {})
        return entry if isinstance(entry, dict) else {}
    except (OSError, ValueError, TypeError, AttributeError):
        return {}


def resolve_inference_policy(config, now=None):
    """Resolve at preparation time; persist the result in the task snapshot.

    Never re-resolve on resume: expiry does not change the frozen configuration; the executor must
    downgrade expired capacity to serial dispatch. Browser-provided inference_policy/capacity_evidence are always ignored.
    """
    now = time.time() if now is None else float(now)
    url = urlsplit(str(config.get("base_url") or config.get("detect_url") or ""))
    backend = f"{url.scheme.lower()}://{url.netloc.lower()}"
    account = config.get("inference_account_identity") or "legacy-unknown-account"
    entry = _manifest_entry(config)
    # Quota identities are server assigned, allowing shared accounts/aliases/models.
    scope = [backend, account]
    policy = {"version": 1, "concurrency": 1, "domain": "inference:" + _hash(scope),
              "requests_per_minute": None, "max_attempts": 1,
              "total_retry_seconds": 30, "evidence_status": "unknown"}
    if not entry:
        return policy
    if entry.get("config_fingerprint") != config_fingerprint(config):
        policy["evidence_status"] = "configuration_changed"
        return policy
    quota_scope = entry.get("quota_scope")
    if quota_scope is not None and (not isinstance(quota_scope, str) or not quota_scope.strip()):
        policy["evidence_status"] = "insufficient_evidence"
        return policy
    if quota_scope:
        # The trusted identity binding remains an ADDITIONAL constraint after
        # capacity expiry. Dropping it would let a newly serial alias bypass
        # an old task still holding this account's shared reservation.
        policy["shared_domain"] = "inference:" + _hash(["quota", quota_scope])
    try:
        expiry = float(entry.get("expires_at", 0))
        valid = math.isfinite(expiry) and expiry > now
    except (ValueError, TypeError):
        valid = False
    if not valid:
        policy["evidence_status"] = "expired"
        return policy
    mode = entry.get("mode")
    replicas = entry.get("instances") or []
    # An operator attests actual distinct native-route instances and equivalent
    # model revision. Mere URL count, model names, GPU names or health is insufficient.
    equivalent = (isinstance(replicas, list) and len(replicas) >= 2
                  and all(isinstance(row, dict) and isinstance(row.get("instance_id"), str) and row["instance_id"].strip() and
                          isinstance(row.get("model_revision"), str) and row["model_revision"].strip() and row.get("native_route_verified") is True for row in replicas)
                  and len({row["instance_id"] for row in replicas}) == len(replicas)
                  and len({row["model_revision"] for row in replicas}) == 1)
    adapter = config.get("provider_adapter") or config.get("provider_type")
    deadline = entry.get("execution_deadline_seconds")
    deadline_valid = isinstance(deadline, (int, float)) and not isinstance(deadline, bool) and 1 <= deadline <= 600
    if mode == "native_gateway" and deadline_valid and adapter == "wevisone_vl" and equivalent and entry.get("request_load_balancing_verified") is True:
        policy["concurrency"] = min(len(replicas), _bounded(entry.get("concurrency"), 1, 8))
    elif mode == "cloud_quota" and adapter in {"volcengine_ark", "aliyun_qwen", "local_openai"} and entry.get("quota_scope"):
        policy["concurrency"] = _bounded(entry.get("concurrency"), 1, 8)
    elif mode == "service_quota" and adapter in {"local_openai", "ollama"} and entry.get("quota_scope") and entry.get("service_capacity_verified") is True and deadline_valid:
        policy["concurrency"] = _bounded(entry.get("concurrency"), 1, 8)
    else:
        policy["evidence_status"] = "insufficient_evidence"
        return policy
    if mode in {"native_gateway", "service_quota"}:
        policy["upstream_deadline_seconds"] = deadline
    policy["evidence_expires_at"] = float(entry["expires_at"])
    policy["evidence_status"] = "operator_attested"
    if entry.get("requests_per_minute") is not None:
        policy["requests_per_minute"] = _bounded(entry["requests_per_minute"], 1, 100000)
    policy["max_attempts"] = _bounded(entry.get("max_attempts"), 1, 3)
    policy["total_retry_seconds"] = _bounded(entry.get("total_retry_seconds"), 30, 30)
    return policy
