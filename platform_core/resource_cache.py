"""Small thread-safe cache for slow, externally detected resources.

The deployment UI must be responsive even when importing a vendor SDK takes
several seconds.  This cache keeps the last real scan, marks stale data, and
allows exactly one refresh worker at a time.  Callers can still request a
synchronous refresh for an explicit user action.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import threading
import time
from typing import Any, Callable, Iterable


class ResourceCache:
    def __init__(self, ttl_seconds: float = 30.0):
        self.ttl_seconds = max(0.0, float(ttl_seconds))
        self._lock = threading.RLock()
        self._items: list[dict[str, Any]] = []
        self._updated_at = 0.0
        self._updated_iso = ""
        self._refreshing = False
        self._error = ""

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            age = max(0.0, time.monotonic() - self._updated_at) if self._updated_at else float("inf")
            stale = not self._items or age >= self.ttl_seconds
            return {
                "items": deepcopy(self._items),
                "stale": stale,
                "refreshing": self._refreshing,
                "age_seconds": None if age == float("inf") else round(age, 3),
                "updated_at": self._updated_iso,
                "error": self._error,
            }

    def replace(self, items: Iterable[dict[str, Any]]) -> dict[str, Any]:
        with self._lock:
            self._items = deepcopy([dict(item) for item in items])
            self._updated_at = time.monotonic()
            self._updated_iso = datetime.now(timezone.utc).isoformat()
            self._error = ""
        return self.snapshot()

    def invalidate(self) -> None:
        with self._lock:
            self._updated_at = 0.0

    def get_or_refresh(self, detector: Callable[[], Iterable[dict[str, Any]]]) -> dict[str, Any]:
        current = self.snapshot()
        if current["items"] and not current["stale"]:
            return current
        try:
            return self.replace(detector())
        except Exception as error:
            with self._lock:
                self._error = str(error)
            raise

    def refresh_in_background(self, detector: Callable[[], Iterable[dict[str, Any]]]) -> bool:
        with self._lock:
            if self._refreshing:
                return False
            self._refreshing = True

        def worker() -> None:
            try:
                self.replace(detector())
            except Exception as error:
                with self._lock:
                    self._error = str(error)
            finally:
                with self._lock:
                    self._refreshing = False

        threading.Thread(target=worker, daemon=True, name="resource-cache-refresh").start()
        return True
