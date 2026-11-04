"""Intranet login must not depend on the ChangLian provider or disk credentials."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2] / "platform_core"


def load_isolated(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


LocalLoginVerifier = load_isolated("local_login_auth_contract", ROOT / "local_login_auth.py").LocalLoginVerifier
SignedSessionManager = load_isolated("local_login_session_contract", ROOT / "changlian_login_auth.py").SignedSessionManager


def test_offline_default_credentials(monkeypatch):
    monkeypatch.delenv("MC_LOCAL_USERNAME", raising=False)
    monkeypatch.delenv("MC_LOCAL_PASSWORD", raising=False)
    verifier = LocalLoginVerifier()
    assert verifier.authenticate("jiangjs", "123456", client_key="localhost") == "ok"
    assert verifier.authenticate("jiangjs", "wrong", client_key="localhost") == "rejected"
    assert verifier.authenticate("unknown", "123456", client_key="localhost") == "rejected"


def test_local_password_can_be_rotated_without_a_remote_provider(monkeypatch):
    monkeypatch.setenv("MC_LOCAL_USERNAME", "intranet-admin")
    monkeypatch.setenv("MC_LOCAL_PASSWORD", "rotated-local-secret")
    verifier = LocalLoginVerifier()
    assert verifier.authenticate("intranet-admin", "rotated-local-secret") == "ok"
    assert verifier.authenticate("jiangjs", "123456") == "rejected"
    assert "rotated-local-secret" not in repr(verifier.__dict__)


def test_local_brute_force_throttle_is_scoped_to_client():
    verifier = LocalLoginVerifier(username="owner", password="correct")
    for i in range(8):
        assert verifier.authenticate("owner", "bad", client_key="a", now=float(i)) == "rejected"
    assert verifier.authenticate("owner", "correct", client_key="a", now=8.0) == "throttled"
    assert verifier.authenticate("owner", "correct", client_key="b", now=8.0) == "ok"
    assert verifier.authenticate("owner", "correct", client_key="a", now=70.0) == "ok"


def test_local_provider_survives_signed_cookie_renewal_and_revocation(tmp_path: Path):
    manager = SignedSessionManager(tmp_path / "auth", idle_ttl_seconds=600,
                                   absolute_ttl_seconds=1800, renew_window_seconds=120)
    token = manager.issue("jiangjs", provider="local", upstream_expiry_source="local", now=1000)
    claims = manager.verify(token, now=1490)
    assert claims and claims["provider"] == "local"
    renewal = manager.renew(claims, now=1490)
    assert renewal
    renewed_claims = manager.verify(renewal, now=1491)
    assert renewed_claims and renewed_claims["provider"] == "local"
    assert manager.revoke(renewal, now=1500)
    assert manager.verify(token, now=1501) is None
