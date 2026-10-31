from starlette.requests import Request
from starlette.responses import Response

import app as app_module


def _request(*, scheme: str = "http", forwarded_proto: str = "") -> Request:
    headers = []
    if forwarded_proto:
        headers.append((b"x-forwarded-proto", forwarded_proto.encode("ascii")))
    return Request(
        {
            "type": "http",
            "http_version": "1.1",
            "method": "GET",
            "scheme": scheme,
            "path": "/api/auth/session",
            "raw_path": b"/api/auth/session",
            "query_string": b"",
            "headers": headers,
            "client": ("127.0.0.1", 12345),
            "server": ("example.test", 443 if scheme == "https" else 80),
        }
    )


def _cookie_header(request: Request) -> str:
    response = Response()
    app_module._set_auth_cookie(
        response,
        request,
        "signed-session",
        {"exp": 4_000_000_000},
    )
    return response.headers["set-cookie"]


def test_http_login_cookie_remains_usable_without_secure_flag():
    header = _cookie_header(_request(scheme="http"))
    assert "HttpOnly" in header
    assert "SameSite=lax" in header
    assert "Secure" not in header


def test_https_login_cookie_uses_secure_flag():
    header = _cookie_header(_request(scheme="https"))
    assert "Secure" in header


def test_https_reverse_proxy_sets_secure_cookie_from_forwarded_proto():
    header = _cookie_header(_request(scheme="http", forwarded_proto="https"))
    assert "Secure" in header


def test_forwarded_proto_uses_first_hop_and_never_downgrades_direct_https():
    assert app_module._auth_request_is_secure(
        _request(scheme="http", forwarded_proto="https,http")
    ) is True
    assert app_module._auth_request_is_secure(
        _request(scheme="https", forwarded_proto="http")
    ) is True
