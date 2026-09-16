"""Freeze discovery scan roots before durable task creation.

Whole-machine discovery is an explicit user action, but the worker must still
receive concrete roots. Resolving visible local filesystems at the HTTP/task
creation boundary makes a queued task auditable and replayable while preserving
the scanner's network/virtual-filesystem exclusions.
"""
from __future__ import annotations

import os
from collections.abc import Iterable

from .scanner import local_scan_roots


def _clean_roots(roots: Iterable[object] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in roots or ():
        value = str(item or "").strip()
        if not value:
            continue
        key = os.path.normcase(
            os.path.normpath(os.path.abspath(os.path.expanduser(value)))
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def resolve_discovery_request_roots(
    scope: str,
    roots: Iterable[object] | None,
) -> list[str]:
    """Return roots that are safe to persist in a durable discovery request.

    Non-full scopes preserve caller-supplied roots. ``full`` always means all
    visible local filesystems on the API host; arbitrary caller roots are not
    accepted as a substitute for machine scope.
    """

    normalized_scope = str(scope or "").strip().lower()
    if normalized_scope != "full":
        return _clean_roots(roots)

    resolved = _clean_roots(os.fspath(path) for path in local_scan_roots())
    if not resolved:
        raise ValueError("全机扫描未发现可用的本地磁盘根目录")
    return resolved


__all__ = ["resolve_discovery_request_roots"]
