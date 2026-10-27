"""Bounded task SQLite retries; ownership failures are never retryable."""
from contextvars import ContextVar
from datetime import datetime, timezone
from functools import wraps
import logging
import math
import random
import sqlite3
import time

_DEADLINE = ContextVar("task_sqlite_busy_deadline", default=None)
logger = logging.getLogger(__name__)


def retry_context_active():
    return _DEADLINE.get() is not None


def is_sqlite_busy(error):
    if not isinstance(error, sqlite3.OperationalError):
        return False
    code = getattr(error, "sqlite_errorcode", None)
    if code is not None:
        return (int(code) & 0xff) in {sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED}
    return str(error).lower().strip() in {"database is locked", "database table is locked", "database is busy"}


def confirmed_deadline(expires_at):
    value = datetime.fromisoformat(str(expires_at).replace("Z", "+00:00"))
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return time.monotonic() + max(0.0, (value - datetime.now(timezone.utc)).total_seconds())


def busy_timeout_ms(default=5000):
    deadline = _DEADLINE.get()
    return default if deadline is None else max(1, min(100, int((deadline-time.monotonic())*1000)))


def run_with_busy_retry(operation, *, deadline=None, timeout=5.0):
    if _DEADLINE.get() is not None:
        return operation()
    started = time.monotonic()
    end = started + timeout if deadline is None else float(deadline)
    token = _DEADLINE.set(end)
    retries = 0
    maximum_attempts = max(1, math.ceil(max(0, end-started) / .01) + 1)
    try:
        while True:
            if time.monotonic() >= end:
                raise sqlite3.OperationalError("database is locked")
            try:
                return operation()
            except sqlite3.OperationalError as error:
                if not is_sqlite_busy(error):
                    raise
                retries += 1
                remaining = end - time.monotonic()
                if retries >= maximum_attempts or remaining <= 0:
                    raise
                time.sleep(min(remaining, random.uniform(.01, min(.25, .02 * 2**min(retries, 4)))))
    finally:
        _DEADLINE.reset(token)
        elapsed = time.monotonic() - started
        if retries and elapsed >= .5:
            logger.warning("task SQLite busy retries=%d elapsed=%.3fs budget=%.3fs", retries, elapsed, max(0, end-started))


def retry_busy(function):
    @wraps(function)
    def wrapped(*args, **kwargs):
        return run_with_busy_retry(lambda: function(*args, **kwargs))
    return wrapped
