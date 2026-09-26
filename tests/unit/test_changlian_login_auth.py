import importlib.util
import json
from pathlib import Path

import pytest
import requests


MODULE_PATH = Path(__file__).resolve().parents[2] / "platform_core" / "changlian_login_auth.py"
SPEC = importlib.util.spec_from_file_location("changlian_login_auth_contract", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
AUTH = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUTH)

DEFAULT_CHANGLIAN_LOGIN_BASE_URL = AUTH.DEFAULT_CHANGLIAN_LOGIN_BASE_URL
DEFAULT_SESSION_IDLE_TTL_SECONDS = AUTH.DEFAULT_SESSION_IDLE_TTL_SECONDS
DEFAULT_SESSION_ABSOLUTE_TTL_SECONDS = AUTH.DEFAULT_SESSION_ABSOLUTE_TTL_SECONDS
ChangLianLoginClient = AUTH.ChangLianLoginClient
ChangLianLoginError = AUTH.ChangLianLoginError
SignedSessionManager = AUTH.SignedSessionManager
auth_guard_decision = AUTH.auth_guard_decision


class FakeResponse:
    def __init__(self, body, status_code=200):
        self._body = body
        self.status_code = status_code

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class FakeSession:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_login_uses_documented_changlian_login_endpoint_and_fields():
    session = FakeSession(FakeResponse({"code": 200, "msg": "登录成功", "token": "secret-token"}))
    client = ChangLianLoginClient(session=session)

    result = client.login(
        username="admin",
        password="123456",
        code="ABCD",
        uuid="uuid-1",
    )

    assert result["ok"] is True
    assert result["token_present"] is True
    assert session.calls == [
        (
            f"{DEFAULT_CHANGLIAN_LOGIN_BASE_URL}/login",
            {
                "json": {
                    "username": "admin",
                    "password": "123456",
                    "code": "ABCD",
                    "uuid": "uuid-1",
                },
                "timeout": 12.0,
            },
        )
    ]


def test_login_does_not_send_blank_optional_captcha_fields():
    session = FakeSession(FakeResponse({"success": True, "error": False}))
    client = ChangLianLoginClient(session=session)

    client.login(username="user", password="pw", code="", uuid="")

    assert session.calls[0][1]["json"] == {"username": "user", "password": "pw"}


def test_login_rejects_business_failure_even_when_http_is_200():
    session = FakeSession(FakeResponse({"code": 500, "msg": "用户名或密码错误"}))
    client = ChangLianLoginClient(session=session)

    with pytest.raises(ChangLianLoginError) as captured:
        client.login(username="bad", password="bad")

    assert captured.value.code == "CHANGLIAN_LOGIN_REJECTED"
    assert captured.value.status_code == 401
    assert "用户名或密码错误" in captured.value.detail


def test_login_reports_unavailable_transport_without_exposing_password():
    class BrokenSession:
        def post(self, *_args, **_kwargs):
            raise requests.ConnectionError("network down")

    client = ChangLianLoginClient(session=BrokenSession())

    with pytest.raises(ChangLianLoginError) as captured:
        client.login(username="user", password="super-secret-password")

    assert captured.value.code == "CHANGLIAN_LOGIN_UNAVAILABLE"
    assert "super-secret-password" not in captured.value.detail


def test_signed_session_is_http_cookie_payload_safe_and_tamper_evident(tmp_path: Path):
    manager = SignedSessionManager(tmp_path / "auth", ttl_seconds=600)
    token = manager.issue("alice", now=1000)

    claims = manager.verify(token, now=1200)
    assert claims is not None
    assert claims["username"] == "alice"
    assert "password" not in json.dumps(claims)

    payload, signature = token.rsplit(".", 1)
    tampered = payload[:-1] + ("A" if payload[-1] != "A" else "B") + "." + signature
    assert manager.verify(tampered, now=1200) is None
    assert manager.verify(token, now=1600) is None


def test_browser_guard_keeps_agent_protocol_alive_but_protects_ui_apis():
    assert auth_guard_decision("/static/login.js") == "public"
    assert auth_guard_decision("/login") == "public"
    assert auth_guard_decision("/api/auth/login") == "public"
    assert auth_guard_decision("/api/v12/projects/p1/algorithms") == "session_api"
    assert auth_guard_decision("/api/v63/service-nodes") == "session_api"

    assert auth_guard_decision(
        "/api/v63/node-executor/node-1/assignments/claim",
        authorization="Bearer agent-token",
    ) == "machine"
    assert auth_guard_decision(
        "/api/v63/service-nodes/node-1/heartbeat",
        authorization="Bearer agent-token",
    ) == "machine"
    assert auth_guard_decision(
        "/api/v63/node-executor/node-1/assignments/claim",
    ) == "session_api"
    assert auth_guard_decision(
        "/api/v63/service-nodes/node-1/heartbeat",
    ) == "session_api"


def test_login_extracts_explicit_upstream_expiry_without_returning_token():
    session = FakeSession(
        FakeResponse(
            {
                "code": 200,
                "msg": "登录成功",
                "data": {"accessToken": "server-secret-token", "expiresIn": 7200},
            }
        )
    )
    client = ChangLianLoginClient(session=session)

    result = client.login(username="alice", password="pw")

    assert result["token_present"] is True
    assert result["upstream_expires_in"] == 7200
    assert result["upstream_expiry_source"] == "expires_in"
    assert "server-secret-token" not in json.dumps(result)


def test_login_extracts_jwt_exp_when_explicit_lifetime_is_missing():
    def b64(payload):
        import base64
        return base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()

    token = f"{b64({'alg': 'none'})}.{b64({'exp': 5000})}."
    session = FakeSession(FakeResponse({"code": 200, "token": token}))
    client = ChangLianLoginClient(session=session)

    result = client.login(username="alice", password="pw")

    assert result["upstream_expires_at"] == 5000
    assert result["upstream_expiry_source"] == "jwt_exp"


def test_login_marks_upstream_expiry_undocumented_when_response_does_not_declare_it():
    session = FakeSession(FakeResponse({"code": 200, "token": "opaque-token"}))
    client = ChangLianLoginClient(session=session)

    result = client.login(username="alice", password="pw")

    assert result["upstream_expires_at"] is None
    assert result["upstream_expiry_source"] == "undocumented"


def test_default_browser_session_is_persistent_and_has_absolute_cap(tmp_path: Path):
    manager = SignedSessionManager(tmp_path / "auth-default")
    token = manager.issue("alice", now=1000)
    claims = manager.verify(token, now=1001)

    assert claims is not None
    assert claims["exp"] == 1000 + DEFAULT_SESSION_IDLE_TTL_SECONDS
    assert claims["hard_exp"] == 1000 + DEFAULT_SESSION_ABSOLUTE_TTL_SECONDS


def test_active_session_rolls_forward_near_idle_expiry_but_never_past_absolute_cap(tmp_path: Path):
    manager = SignedSessionManager(
        tmp_path / "auth-roll",
        idle_ttl_seconds=600,
        absolute_ttl_seconds=1800,
        renew_window_seconds=120,
    )
    token = manager.issue("alice", now=1000)
    claims = manager.verify(token, now=1490)
    assert claims is not None
    assert manager.needs_renewal(claims, now=1490) is True

    renewed = manager.renew(claims, now=1490)
    assert renewed is not None
    renewed_claims = manager.verify(renewed, now=1491)
    assert renewed_claims is not None
    assert renewed_claims["exp"] == 2090
    assert renewed_claims["hard_exp"] == 2800

    near_hard = manager.verify(renewed, now=2000)
    assert near_hard is not None
    second = manager.renew(near_hard, now=2000)
    assert second is not None
    second_claims = manager.verify(second, now=2001)
    assert second_claims is not None
    assert second_claims["exp"] == 2600
    assert second_claims["hard_exp"] == 2800


def test_auth_guard_protects_direct_data_and_api_docs_download_surfaces():
    assert auth_guard_decision("/data/projects/p1/images/a.jpg") == "session_resource"
    assert auth_guard_decision("/docs") == "session_page"
    assert auth_guard_decision("/redoc") == "session_page"
    assert auth_guard_decision("/openapi.json") == "session_page"
