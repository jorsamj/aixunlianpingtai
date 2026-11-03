"""Bounded, read-only `.pt` inventory for existing service-node heartbeats.

Discovery is *not* checkpoint validation: neither a filename nor a heartbeat is
evidence that a remote model can be loaded, transferred, or trained. The Agent
never scans a machine root unless one was explicitly configured as a root.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


MAX_MODEL_RESULTS = 64
MAX_SCAN_DIRECTORIES = 1500
MAX_SCAN_ENTRIES = 20000
MAX_SCAN_DEPTH = 5
MAX_MODEL_BYTES = 1024 * 1024 * 1024


def _bounded_roots(roots: Iterable[str | Path]) -> list[Path]:
    result: list[Path] = []
    seen: set[str] = set()
    for item in roots:
        if not str(item).strip():
            continue
        candidate = Path(str(item)).expanduser()
        if candidate.is_symlink() or not candidate.is_dir():
            continue
        try:
            resolved = candidate.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        key = os.path.normcase(str(resolved))
        if key not in seen:
            result.append(resolved)
            seen.add(key)
        if len(result) >= 8:
            break
    return result


def scan_mother_models(
    roots: Iterable[str | Path],
    *,
    max_models: int = MAX_MODEL_RESULTS,
    max_dirs: int = MAX_SCAN_DIRECTORIES,
    max_depth: int = MAX_SCAN_DEPTH,
) -> dict[str, Any]:
    """Stat bounded paths only: no model import, unpickle, or content read."""
    selected = _bounded_roots(roots)
    result: dict[str, Any] = {
        "status": "COMPLETED",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "roots": [str(path) for path in selected],
        "items": [],
        "scanned_dirs": 0,
        "scanned_entries": 0,
        "permission_errors": 0,
        "truncated": False,
    }
    if not selected:
        result["status"] = "NOT_CONFIGURED"
        return result
    model_limit = max(1, min(int(max_models), MAX_MODEL_RESULTS))
    dir_limit = max(1, min(int(max_dirs), MAX_SCAN_DIRECTORIES))
    depth_limit = max(0, min(int(max_depth), MAX_SCAN_DEPTH))
    visited: set[tuple[int, int]] = set()
    for root in selected:
        pending: list[tuple[Path, int]] = [(root, 0)]
        while pending:
            if result["scanned_dirs"] >= dir_limit or len(result["items"]) >= model_limit:
                result["truncated"] = True
                return result
            current, depth = pending.pop()
            try:
                info = current.stat(follow_symlinks=False)
                identity = (int(info.st_dev), int(info.st_ino))
                if identity in visited:
                    continue
                visited.add(identity)
                result["scanned_dirs"] += 1
                with os.scandir(current) as entries:
                    for entry in entries:
                        result["scanned_entries"] += 1
                        if result["scanned_entries"] > MAX_SCAN_ENTRIES:
                            result["truncated"] = True
                            return result
                        try:
                            if entry.is_symlink():
                                continue
                            if entry.is_dir(follow_symlinks=False):
                                if depth < depth_limit:
                                    pending.append((Path(entry.path), depth + 1))
                                continue
                            if not entry.name.lower().endswith(".pt") or not entry.is_file(follow_symlinks=False):
                                continue
                            stat = entry.stat(follow_symlinks=False)
                            if stat.st_size < 1024 or stat.st_size > MAX_MODEL_BYTES:
                                continue
                            result["items"].append({
                                "name": entry.name[:160],
                                "path": str(Path(entry.path)),
                                "size_bytes": int(stat.st_size),
                                "modified_ns": int(stat.st_mtime_ns),
                                "status": "DISCOVERED_UNVERIFIED",
                                "trainable": False,
                            })
                            if len(result["items"]) >= model_limit:
                                result["truncated"] = True
                                return result
                        except (PermissionError, OSError):
                            result["permission_errors"] += 1
            except (PermissionError, OSError):
                result["permission_errors"] += 1
    return result


class AgentMotherModelInventory:
    """Background refresh with truthful old snapshot while scan is in flight."""

    def __init__(self, roots: Iterable[str | Path], *, interval_seconds: float = 300.0):
        self.roots = tuple(str(path) for path in roots if str(path).strip())
        self.interval_seconds = max(30.0, float(interval_seconds))
        self._lock = threading.Lock()
        self._next_refresh = 0.0
        self._working = False
        self._report = scan_mother_models(())

    def scan_now(self) -> dict[str, Any]:
        result = scan_mother_models(self.roots)
        with self._lock:
            self._report = result
            self._next_refresh = time.monotonic() + self.interval_seconds
            self._working = False
        return dict(result)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            if self.roots and not self._working and time.monotonic() >= self._next_refresh:
                self._working = True
                self._next_refresh = time.monotonic() + self.interval_seconds
                threading.Thread(target=self._refresh, name="agent-model-inventory", daemon=True).start()
            report = dict(self._report)
            report["items"] = list(self._report.get("items") or [])
            if self._working:
                report["status"] = "SCANNING"
            return report

    def _refresh(self) -> None:
        try:
            self.scan_now()
        except Exception:
            with self._lock:
                self._working = False
                self._next_refresh = time.monotonic() + self.interval_seconds
                self._report = {"status": "FAILED", "items": [], "roots": [], "scanned_at": "", "truncated": False}


def project_node_inventory(nodes: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Trust node heartbeat for discovery only, never for training eligibility."""
    output = []
    for node in nodes:
        if str(node.get("connection_mode")) != "agent":
            continue
        runtime = node.get("runtime")
        inventory = runtime.get("mother_model_inventory") if isinstance(runtime, Mapping) else None
        report = inventory if isinstance(inventory, Mapping) else {}
        items = report.get("items")
        models: list[dict[str, Any]] = []
        if isinstance(items, list):
            for row in items[:MAX_MODEL_RESULTS]:
                if not isinstance(row, Mapping):
                    continue
                name = str(row.get("name") or "")[:160]
                path = str(row.get("path") or "")[:600]
                size = row.get("size_bytes")
                if not name.lower().endswith(".pt") or not isinstance(size, int) or size < 1024 or size > MAX_MODEL_BYTES:
                    continue
                models.append({"name": name, "path": path, "size_bytes": size,
                               "status": "DISCOVERED_UNVERIFIED", "trainable": False})
        online = bool(node.get("online"))
        output.append({
            "node_id": str(node.get("node_id") or ""),
            "display_name": str(node.get("display_name") or node.get("node_id") or "")[:120],
            "online": online,
            "status": str(report.get("status") or "NOT_REPORTED") if online else "OFFLINE",
            "scanned_at": str(report.get("scanned_at") or "")[:48],
            "truncated": bool(report.get("truncated")),
            "items": models,
        })
    return output
