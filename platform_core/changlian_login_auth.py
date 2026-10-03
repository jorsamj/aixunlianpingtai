from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import time
from pathlib import Path
from typing import Any, Mapping, Optional

import requests


DEFAULT_CHANGLIAN_LOGIN_BASE_URL = "http://vip.24hlink.cn/prod-api"
SESSION_COOKIE_NAME = "mc_changlian_session"
DEFAULT_SESSION_IDLE_TTL_SECONDS = 7 * 24 * 60 * 60
DEFAULT_SESSION_ABSOLUTE_TTL_SECONDS = 30 * 24 * 60 * 60
DEFAULT_SESSION_RENEW_WINDOW_SECONDS = 24 * 60 * 60
# Compatibility alias for callers that still describe the rolling idle lifetime as ttl.
DEFAULT_SESSION_TTL_SECONDS = DEFAULT_SESSION_IDLE_TTL_SECONDS
_MACHINE_NODE_EXECUTOR_PREFIX = "/api/v63/node-executor/"
_MACHINE_HEARTBEAT_RE = re.compile(r"^/api/v63/service-nodes/[^/]+/heartbeat/?$")
_PROTECTED_PAGE_PATHS = {"/", "/docs", "/redoc", "/openapi.json"}


class ChangLianLoginError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        detail: str,
        *,
        solution: str = "",
        status_code: int = 401,
    ) -> None:
        super().__init__(message)
        self.code = str(code)
        self.message = str(message)
        self.detail = str(detail)
        self.solution = str(solution)
        self.status_code = int(status_code)


def _clean_base_url(value: Any) -> str:
    text = str(value or DEFAULT_CHANGLIAN_LOGIN_BASE_URL).strip()
    return text.rstrip("/")


def _business_message(body: Mapping[str, Any]) -> str:
    for key in ("msg", "message", "reason"):
        value = body.get(key)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _candidate_mappings(body: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = [body]
    data = body.get("data")
    if isinstance(data, Mapping):
        candidates.append(data)
    return candidates


def _extract_login_token(body: Mapping[str, Any]) -> str:
    for candidate in _candidate_mappings(body):
        for key in ("token", "accessToken", "access_token"):
            value = candidate.get(key)
            if value is not None and str(value).strip():
                return str(value).strip()
    return ""


def _extract_explicit_expires_in(body: Mapping[str, Any]) -> Optional[int]:
    for candidate in _candidate_mappings(body):
        for key in ("expiresIn", "expires_in"):
            value = candidate.get(key)
            if value is None or isinstance(value, bool):
                continue
            try:
                seconds = int(float(value))
            except (TypeError, ValueError):
                continue
            if seconds > 0:
                return seconds
    return None


def _jwt_exp(token: str) -> Optional[int]:
    value = str(token or "").strip()
    parts = value.split(".")
    if len(parts) != 3 or not parts[1]:
        return None
    try:
        payload = json.loads(_b64decode(parts[1]).decode("utf-8"))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, Mapping):
        return None
    raw = payload.get("exp")
    if raw is None or isinstance(raw, bool):
        return None
    try:
        expires_at = int(float(raw))
    except (TypeError, ValueError):
        return None
    return expires_at if expires_at > 0 else None


def _upstream_expiry_metadata(
    body: Mapping[str, Any],
    token: str,
    *,
    now: Optional[int] = None,
) -> dict[str, Any]:
    current = int(time.time() if now is None else now)
    explicit = _extract_explicit_expires_in(body)
    if explicit is not None:
        return {
            "upstream_expires_in": explicit,
            "upstream_expires_at": current + explicit,
            "upstream_expiry_source": "expires_in",
        }
    jwt_expires_at = _jwt_exp(token)
    if jwt_expires_at is not None:
        return {
            "upstream_expires_in": max(0, jwt_expires_at - current),
            "upstream_expires_at": jwt_expires_at,
            "upstream_expiry_source": "jwt_exp",
        }
    return {
        "upstream_expires_in": None,
        "upstream_expires_at": None,
        "upstream_expiry_source": "undocumented",
    }


def _business_login_succeeded(body: Mapping[str, Any]) -> bool:
    if body.get("success") is False or body.get("error") is True:
        return False
    code = body.get("code")
    if code is not None:
        return str(code).strip() in {"0", "200"}
    if body.get("success") is True:
        return True
    if _extract_login_token(body):
        return True
    if body.get("error") is False:
        return True
    return False


class ChangLianLoginClient:
    def __init__(
        self,
        *,
        base_url: str = DEFAULT_CHANGLIAN_LOGIN_BASE_URL,
        timeout_seconds: float = 12.0,
        session: Optional[requests.Session] = None,
    ) -> None:
        self.base_url = _clean_base_url(base_url)
        self.timeout_seconds = max(1.0, float(timeout_seconds))
        self.session = session or requests.Session()

    @property
    def login_url(self) -> str:
        return f"{self.base_url}/login"

    def login(
        self,
        *,
        username: str,
        password: str,
        code: Optional[str] = None,
        uuid: Optional[str] = None,
    ) -> dict[str, Any]:
        user = str(username or "").strip()
        secret = str(password or "")
        if not user or not secret:
            raise ChangLianLoginError(
                "CHANGLIAN_LOGIN_INPUT_REQUIRED",
                "请输入畅联云用户名和密码",
                "username/password 为畅联云登录接口必填字段。",
                solution="请补充账号和密码后重试。",
                status_code=422,
            )

        payload: dict[str, Any] = {"username": user, "password": secret}
        if code is not None and str(code).strip():
            payload["code"] = str(code).strip()
        if uuid is not None and str(uuid).strip():
            payload["uuid"] = str(uuid).strip()

        try:
            response = self.session.post(
                self.login_url,
                json=payload,
                timeout=self.timeout_seconds,
            )
        except requests.RequestException as error:
            raise ChangLianLoginError(
                "CHANGLIAN_LOGIN_UNAVAILABLE",
                "暂时无法连接畅联云登录服务",
                f"{type(error).__name__}: {error}",
                solution="请检查服务器到畅联云正式环境的网络后重试。",
                status_code=502,
            ) from error

        try:
            body = response.json()
        except (ValueError, json.JSONDecodeError) as error:
            raise ChangLianLoginError(
                "CHANGLIAN_LOGIN_RESPONSE_INVALID",
                "畅联云登录服务返回了无法识别的数据",
                f"HTTP {response.status_code}; response is not valid JSON",
                solution="请确认畅联云登录接口当前可用。",
                status_code=502,
            ) from error
        if not isinstance(body, Mapping):
            raise ChangLianLoginError(
                "CHANGLIAN_LOGIN_RESPONSE_INVALID",
                "畅联云登录服务返回格式不正确",
                f"HTTP {response.status_code}; JSON root must be an object",
                solution="请确认畅联云登录接口返回格式。",
                status_code=502,
            )

        message = _business_message(body)
        if response.status_code >= 500:
            raise ChangLianLoginError(
                "CHANGLIAN_LOGIN_UNAVAILABLE",
                "畅联云登录服务暂时不可用",
                message or f"HTTP {response.status_code}",
                solution="请稍后重试；若持续失败，请检查畅联云服务状态。",
                status_code=502,
            )
        if response.status_code >= 400 or not _business_login_succeeded(body):
            raise ChangLianLoginError(
                "CHANGLIAN_LOGIN_REJECTED",
                "畅联云账号登录失败",
                message or f"畅联云拒绝登录（HTTP {response.status_code}）",
                solution="请检查用户名、密码以及验证码信息。",
                status_code=401,
            )

        token = _extract_login_token(body)
        expiry = _upstream_expiry_metadata(body, token)
        return {
            "ok": True,
            "username": user,
            "code": body.get("code"),
            "message": message,
            "token_present": bool(token),
            **expiry,
        }


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("ascii"))


class SignedSessionManager:
    def __init__(
        self,
        root: Path,
        *,
        idle_ttl_seconds: int = DEFAULT_SESSION_IDLE_TTL_SECONDS,
        absolute_ttl_seconds: int = DEFAULT_SESSION_ABSOLUTE_TTL_SECONDS,
        renew_window_seconds: int = DEFAULT_SESSION_RENEW_WINDOW_SECONDS,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.key_path = self.root / "changlian-session.key"
        # ttl_seconds remains accepted for older focused tests/callers.
        if ttl_seconds is not None:
            idle_ttl_seconds = int(ttl_seconds)
        self.idle_ttl_seconds = max(300, int(idle_ttl_seconds))
        self.absolute_ttl_seconds = max(self.idle_ttl_seconds, int(absolute_ttl_seconds))
        self.renew_window_seconds = max(
            60,
            min(int(renew_window_seconds), self.idle_ttl_seconds - 1),
        )
        self.ttl_seconds = self.idle_ttl_seconds
        self._key = self._load_or_create_key()

    def _load_or_create_key(self) -> bytes:
        if self.key_path.exists():
            key = self.key_path.read_bytes()
            if len(key) >= 32:
                return key
        key = secrets.token_bytes(48)
        try:
            with self.key_path.open("xb") as handle:
                handle.write(key)
        except FileExistsError:
            key = self.key_path.read_bytes()
        try:
            os.chmod(self.key_path, 0o600)
        except OSError:
            pass
        if len(key) < 32:
            raise RuntimeError("invalid changlian auth session key")
        return key

    def issue(
        self,
        username: str,
        *,
        now: Optional[int] = None,
        created_at: Optional[int] = None,
        hard_expires_at: Optional[int] = None,
        upstream_expires_at: Optional[int] = None,
        upstream_expiry_source: str = "undocumented",
    ) -> str:
        issued_at = int(time.time() if now is None else now)
        origin = issued_at if created_at is None else int(created_at)
        hard_exp = (
            origin + self.absolute_ttl_seconds
            if hard_expires_at is None
            else int(hard_expires_at)
        )
        expires_at = min(issued_at + self.idle_ttl_seconds, hard_exp)
        body = {
            "v": 2,
            "username": str(username or "").strip(),
            "iat": issued_at,
            "created_at": origin,
            "exp": expires_at,
            "hard_exp": hard_exp,
            "jti": secrets.token_urlsafe(12),
            "upstream_exp": int(upstream_expires_at) if upstream_expires_at else None,
            "upstream_expiry_source": str(upstream_expiry_source or "undocumented"),
        }
        payload = _b64encode(
            json.dumps(
                body,
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        )
        signature = _b64encode(
            hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).digest()
        )
        return f"{payload}.{signature}"

    def verify(self, token: str, *, now: Optional[int] = None) -> Optional[dict[str, Any]]:
        value = str(token or "").strip()
        if not value or "." not in value:
            return None
        payload, signature = value.rsplit(".", 1)
        expected = _b64encode(
            hmac.new(self._key, payload.encode("ascii"), hashlib.sha256).digest()
        )
        if not hmac.compare_digest(signature, expected):
            return None
        try:
            body = json.loads(_b64decode(payload).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(body, dict) or int(body.get("v") or 0) not in {1, 2}:
            return None
        username = str(body.get("username") or "").strip()
        if not username:
            return None
        current = int(time.time() if now is None else now)
        try:
            expires_at = int(body.get("exp") or 0)
            hard_exp = int(body.get("hard_exp") or 0)
        except (TypeError, ValueError):
            return None
        if expires_at <= current:
            return None
        if hard_exp and hard_exp <= current:
            return None
        return body

    def needs_renewal(self, claims: Mapping[str, Any], *, now: Optional[int] = None) -> bool:
        current = int(time.time() if now is None else now)
        try:
            expires_at = int(claims.get("exp") or 0)
            created_at = int(claims.get("created_at") or claims.get("iat") or current)
            hard_exp = int(claims.get("hard_exp") or (created_at + self.absolute_ttl_seconds))
        except (TypeError, ValueError):
            return False
        if expires_at <= current or hard_exp <= current:
            return False
        return (expires_at - current) <= self.renew_window_seconds

    def renew(self, claims: Mapping[str, Any], *, now: Optional[int] = None) -> Optional[str]:
        current = int(time.time() if now is None else now)
        if not self.needs_renewal(claims, now=current):
            return None
        try:
            created_at = int(claims.get("created_at") or claims.get("iat") or current)
            hard_exp = int(claims.get("hard_exp") or (created_at + self.absolute_ttl_seconds))
            upstream_exp = claims.get("upstream_exp")
            upstream_expires_at = int(upstream_exp) if upstream_exp else None
        except (TypeError, ValueError):
            return None
        return self.issue(
            str(claims.get("username") or ""),
            now=current,
            created_at=created_at,
            hard_expires_at=hard_exp,
            upstream_expires_at=upstream_expires_at,
            upstream_expiry_source=str(
                claims.get("upstream_expiry_source") or "undocumented"
            ),
        )


def _has_bearer(authorization: Optional[str]) -> bool:
    value = str(authorization or "").strip()
    return value.lower().startswith("bearer ") and bool(value[7:].strip())


def auth_guard_decision(
    path: str,
    *,
    authorization: Optional[str] = None,
) -> str:
    value = str(path or "/")
    if value.startswith("/static/"):
        return "public"
    if value in {
        "/login",
        "/api/auth/login",
        "/api/auth/session",
        "/api/auth/logout",
        "/api/health",
    }:
        return "public"
    if _has_bearer(authorization):
        if value.startswith(_MACHINE_NODE_EXECUTOR_PREFIX):
            return "machine"
        if _MACHINE_HEARTBEAT_RE.fullmatch(value):
            return "machine"
    if value.startswith("/api/"):
        return "session_api"
    if value.startswith("/data/"):
        return "session_resource"
    if value in _PROTECTED_PAGE_PATHS:
        return "session_page"
    return "public"


__all__ = [
    "DEFAULT_CHANGLIAN_LOGIN_BASE_URL",
    "DEFAULT_SESSION_IDLE_TTL_SECONDS",
    "DEFAULT_SESSION_ABSOLUTE_TTL_SECONDS",
    "DEFAULT_SESSION_RENEW_WINDOW_SECONDS",
    "DEFAULT_SESSION_TTL_SECONDS",
    "SESSION_COOKIE_NAME",
    "ChangLianLoginClient",
    "ChangLianLoginError",
    "SignedSessionManager",
    "auth_guard_decision",
]
