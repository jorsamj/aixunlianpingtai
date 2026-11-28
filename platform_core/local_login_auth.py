"""Standalone intranet login without a network provider or stored plaintext password.

MC_LOCAL_USERNAME / MC_LOCAL_PASSWORD override the requested first-deploy defaults.
The signed browser session remains owned by changlian_login_auth.SignedSessionManager.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import threading
import time
from collections import OrderedDict, deque


DEFAULT_LOCAL_USERNAME = "jiangjs"
DEFAULT_LOCAL_PASSWORD = "123456"


class LocalLoginVerifier:
    def __init__(self, username: str | None = None, password: str | None = None) -> None:
        self.username = (username if username is not None else os.environ.get("MC_LOCAL_USERNAME", DEFAULT_LOCAL_USERNAME)).strip()
        secret = password if password is not None else os.environ.get("MC_LOCAL_PASSWORD", DEFAULT_LOCAL_PASSWORD)
        if not self.username or not secret:
            raise ValueError("local login credentials must be non-empty")
        self._salt = secrets.token_bytes(32)
        self._digest = self._derive(secret)
        self._lock = threading.Lock()
        self._failures: OrderedDict[str, deque[float]] = OrderedDict()

    def _derive(self, secret: str) -> bytes:
        return hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), self._salt, 150_000)

    def authenticate(self, username: str, password: str, *, client_key: str = "", now: float | None = None) -> str:
        """Return ok, rejected or throttled; never make a provider HTTP request."""
        moment = time.monotonic() if now is None else float(now)
        key = str(client_key or "unknown")[:128]
        with self._lock:
            # Bounded memory and a per-client window; account identity is not
            # leaked via different errors for unknown usernames.
            if key not in self._failures and len(self._failures) >= 4096:
                # Cap live as well as expired IP entries. A flood of unique
                # clients must never grow the in-memory limiter indefinitely.
                self._failures.popitem(last=False)
            if key in self._failures:
                self._failures.move_to_end(key)
            attempts = self._failures.setdefault(key, deque())
            while attempts and attempts[0] <= moment - 60:
                attempts.popleft()
            if len(attempts) >= 8:
                return "throttled"

        user_ok = secrets.compare_digest(username.strip().encode("utf-8"), self.username.encode("utf-8"))
        password_ok = secrets.compare_digest(self._derive(password), self._digest)
        if user_ok and password_ok:
            with self._lock:
                self._failures.pop(key, None)
            return "ok"

        with self._lock:
            attempts = self._failures.setdefault(key, deque())
            attempts.append(moment)
        return "rejected"
