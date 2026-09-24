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
