"""Durable, machine-scoped resource discovery task handlers.

HTTP routes only allocate generations and queue these tasks.  Filesystem
traversal and Python subprocess probes are deliberately confined to the
discovery worker.
"""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import closing
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping

from ..task_runtime import TaskKind, TaskStatus
from .cache import DiscoveryCache
from .candidates import DiscoveryContext, discover_fast_python_candidates
from .probe import probe_python_environment, rank_environments
from .scanner import scan_model_files, scan_python_candidates


CACHE_FILENAME = "resource_discovery.sqlite3"
PROGRESS_REF = "progress.json"
RESULT_REF = "result.json"
_MODEL_MANIFEST_REF = "discovery/models.sqlite3"
_MODEL_BATCH_SIZE = 256


def _path_key(value: str | os.PathLike[str]) -> str:
    return os.path.normcase(os.path.normpath(os.path.abspath(os.fspath(value))))


def _read_json_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError):
        return {}
    return dict(value) if isinstance(value, Mapping) else {}


class _ModelManifest:
    """Task-local bounded-memory spool used before atomic cache publication."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._pending: list[dict[str, Any]] = []
        with closing(self._connect()) as database:
            with database:
                database.execute(
                    "CREATE TABLE IF NOT EXISTS models "
                    "(path_key TEXT PRIMARY KEY, payload_json TEXT NOT NULL)"
                )

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.path, timeout=30)
        database.execute("PRAGMA busy_timeout=30000")
        return database

    def reset(self) -> None:
        with closing(self._connect()) as database:
            with database:
                database.execute("DELETE FROM models")

    def add(self, row: Mapping[str, Any]) -> None:
        self._pending.append(dict(row))
        if len(self._pending) >= _MODEL_BATCH_SIZE:
            self.flush()

    def flush(self) -> None:
        if not self._pending:
            return
        rows = self._pending
        self._pending = []
        with closing(self._connect()) as database:
            with database:
                database.executemany(
                    "INSERT OR REPLACE INTO models(path_key,payload_json) VALUES (?,?)",
                    (
                        (
                            _path_key(str(row.get("path") or "")),
                            json.dumps(row, ensure_ascii=False, sort_keys=True),
                        )
                        for row in rows
                    ),
                )

    def count(self) -> int:
        self.flush()
        with closing(self._connect()) as database:
            return int(database.execute("SELECT COUNT(*) FROM models").fetchone()[0])

    def rows(self) -> Iterable[dict[str, Any]]:
        self.flush()
        with closing(self._connect()) as database:
            with closing(database.execute(
                "SELECT payload_json FROM models ORDER BY path_key"
            )) as cursor:
                for row in cursor:
                    yield dict(json.loads(row[0]))


class ResourceDiscoveryHandler:
    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir).expanduser().resolve()
        self.cache = DiscoveryCache(self.data_dir / CACHE_FILENAME)

    @staticmethod
    def _request(context) -> dict[str, Any]:
        request = context.artifacts.read_json(
            context.task.task_id, context.task.payload_ref, default=None
        )
        if not isinstance(request, dict):
            raise ValueError("resource discovery request is missing or invalid")
        return request

    @staticmethod
    def _cancelled(context) -> bool:
        return context.cancel_requested()

    def _publish_progress(
        self,
        context,
        *,
        discovery_type: str,
        stage: str,
        counters: Mapping[str, Any],
        current_item: object = "",
    ) -> None:
        current = str(current_item or "")
        payload = {
            "discovery_type": discovery_type,
            "stage": stage,
            "progress_determinate": False,
            "current_item": current,
            **{
                key: max(0, int(value))
                for key, value in counters.items()
                if isinstance(value, (int, float)) and not isinstance(value, bool)
            },
        }
        context.artifacts.atomic_write_json(context.task.task_id, PROGRESS_REF, payload)
        context.save_checkpoint(payload)
        context.repository.heartbeat(
            context.task.task_id,
            context.lease.lease_token,
            stage=stage,
            current_item=current,
        )
        if self._cancelled(context):
            raise InterruptedError("resource discovery cancelled")

    def _environment(self, context, request: Mapping[str, Any]):
        scope = str(request.get("scope") or "auto").strip().lower()
        if scope not in {"auto", "fast", "full"}:
            raise ValueError("environment discovery scope must be auto, fast, or full")
        generation = int(request.get("generation") or 0)
        if generation < 1:
            raise ValueError("resource discovery generation is invalid")
        raw_roots = request.get("roots")
        roots = [Path(str(item)).expanduser() for item in raw_roots] if isinstance(raw_roots, list) else []
        saved = _read_json_file(self.data_dir / "ultralytics_env.json")
        discovery_context = DiscoveryContext.from_system(
            project_root=Path.cwd(), saved_environment=saved
        )
        if roots:
            discovery_context = replace(
                discovery_context, ultralytics_roots=tuple(roots)
            )

        counters: dict[str, int] = {
            "scanned_dirs": 0,
            "python_candidates": 0,
            "validated_environments": 0,
            "available_environments": 0,
            "permission_errors": 0,
        }
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()

        def probe(path: Path, sources: Iterable[str]) -> None:
            key = _path_key(path)
            if key in seen:
                return
            seen.add(key)
            counters["python_candidates"] += 1
            self._publish_progress(
                context,
                discovery_type="ultralytics_environment",
                stage="validating_environment",
                counters=counters,
                current_item=path,
            )
            result = probe_python_environment(path)
            result["sources"] = sorted(set(str(item) for item in sources))
            rows.append(result)
            counters["validated_environments"] += 1
            if str(result.get("status") or "").upper() == "AVAILABLE":
                counters["available_environments"] += 1

        self._publish_progress(
            context,
            discovery_type="ultralytics_environment",
            stage="fast_discovery",
            counters=counters,
        )
        for candidate in discover_fast_python_candidates(discovery_context):
            probe(candidate.path, candidate.sources)

        should_scan = scope == "full" or (
            scope == "auto" and counters["available_environments"] == 0
        )
        if should_scan:
            self._publish_progress(
                context,
                discovery_type="ultralytics_environment",
                stage="deep_discovery",
                counters=counters,
            )

            def on_progress(progress: dict[str, Any]) -> None:
                counters["scanned_dirs"] = int(progress.get("scanned_dirs") or 0)
                counters["permission_errors"] = int(progress.get("permission_errors") or 0)
                self._publish_progress(
                    context,
                    discovery_type="ultralytics_environment",
                    stage="deep_discovery",
                    counters=counters,
                    current_item=progress.get("current_path") or "",
                )

            report = scan_python_candidates(
                roots or None,
                on_item=lambda path: probe(path, ("deep_scan",)),
                on_progress=on_progress,
                cancel_requested=lambda: self._cancelled(context),
            )
            if report.cancelled:
                raise InterruptedError("resource discovery cancelled")
            counters["scanned_dirs"] = report.scanned_dirs
            counters["permission_errors"] = report.permission_errors

        ranked = rank_environments(rows)
        total = len(ranked)
        for index, row in enumerate(ranked):
            row["recommendation_rank"] = total - index
        published = self.cache.replace_environments(
            context.task.task_id, ranked, generation
        )
        result = {
            "ok": True,
            "discovery_type": "ultralytics_environment",
            "scope": scope,
            "generation": generation,
            "published": published,
            **counters,
        }
        context.artifacts.atomic_write_json(context.task.task_id, RESULT_REF, result)
        self._publish_progress(
            context,
            discovery_type="ultralytics_environment",
            stage="completed",
            counters=counters,
        )
        return TaskStatus.SUCCEEDED, RESULT_REF

    def _models(self, context, request: Mapping[str, Any]):
        scope = str(request.get("scope") or "directory").strip().lower()
        if scope not in {"directory", "full"}:
            raise ValueError("model discovery scope must be directory or full")
        generation = int(request.get("generation") or 0)
        if generation < 1:
            raise ValueError("resource discovery generation is invalid")
        raw_roots = request.get("roots")
        roots = [Path(str(item)).expanduser() for item in raw_roots] if isinstance(raw_roots, list) else []
        if scope == "directory" and not roots:
            raise ValueError("directory model discovery requires at least one root")

        manifest = _ModelManifest(
            context.artifacts.artifact_path(context.task.task_id, _MODEL_MANIFEST_REF)
        )
        # A recovered scan may repeat safely. Rebuilding the task-local spool
        # makes removed files disappear while final cache publication remains atomic.
        manifest.reset()
        counters: dict[str, int] = {
            "scanned_dirs": 0,
            "models_found": 0,
            "permission_errors": 0,
        }
        self._publish_progress(
            context,
            discovery_type="local_models",
            stage="scanning_models",
            counters=counters,
        )

        def on_item(row: dict[str, Any]) -> None:
            manifest.add(row)

        def on_progress(progress: dict[str, Any]) -> None:
            counters["scanned_dirs"] = int(progress.get("scanned_dirs") or 0)
            counters["models_found"] = int(progress.get("models_found") or 0)
            counters["permission_errors"] = int(progress.get("permission_errors") or 0)
            self._publish_progress(
                context,
                discovery_type="local_models",
                stage="scanning_models",
                counters=counters,
                current_item=progress.get("current_path") or "",
            )

        report = scan_model_files(
            None if scope == "full" else roots,
            on_item=on_item,
            on_progress=on_progress,
            cancel_requested=lambda: self._cancelled(context),
        )
        if report.cancelled:
            raise InterruptedError("resource discovery cancelled")
        manifest.flush()
        counters.update(
            scanned_dirs=report.scanned_dirs,
            models_found=manifest.count(),
            permission_errors=report.permission_errors,
        )
        self._publish_progress(
            context,
            discovery_type="local_models",
            stage="publishing_cache",
            counters=counters,
        )
        published = self.cache.replace_models(
            context.task.task_id, manifest.rows(), generation
        )
        result = {
            "ok": True,
            "discovery_type": "local_models",
            "scope": scope,
            "generation": generation,
            "published": published,
            **counters,
        }
        context.artifacts.atomic_write_json(context.task.task_id, RESULT_REF, result)
        self._publish_progress(
            context,
            discovery_type="local_models",
            stage="completed",
            counters=counters,
        )
        return TaskStatus.SUCCEEDED, RESULT_REF

    def run(self, context):
        request = self._request(context)
        discovery_type = str(request.get("discovery_type") or "").strip()
        if discovery_type == "ultralytics_environment":
            return self._environment(context, request)
        if discovery_type == "local_models":
            return self._models(context, request)
        raise ValueError("unsupported resource discovery type")

    def recover(self, context):
        # Discovery is read-only until atomic cache publication. Repeating it
        # is deterministic and never exposes a partial cache snapshot.
        return self.run(context)


def worker_registration(data_dir: Path):
    return {
        "handlers": {TaskKind.RESOURCE_DISCOVERY: ResourceDiscoveryHandler(data_dir)},
        "capabilities": {"resource.discovery"},
    }


__all__ = [
    "CACHE_FILENAME",
    "PROGRESS_REF",
    "RESULT_REF",
    "ResourceDiscoveryHandler",
    "worker_registration",
]
