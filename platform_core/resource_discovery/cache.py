"""SQLite-backed cache for machine resource discovery.

Discovery tasks may take a long time and can finish out of order.  This cache
therefore separates generation allocation from publication: a scan receives a
monotonic generation when its durable task is created and may atomically
publish only while it is not older than the currently completed scan.
"""
from __future__ import annotations

import base64
import json
import math
import ntpath
import os
import posixpath
import re
import sqlite3
from contextlib import closing, contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Iterator, Mapping, Sequence

from filelock import FileLock


_SCHEMA = """
CREATE TABLE IF NOT EXISTS cache_meta (
    cache_kind TEXT PRIMARY KEY,
    allocated_generation INTEGER NOT NULL DEFAULT 0,
    completed_generation INTEGER NOT NULL DEFAULT 0,
    completed_scan_id TEXT,
    completed_at TEXT,
    row_count INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS environment_candidates (
    normalized_python_path TEXT PRIMARY KEY,
    python_path TEXT NOT NULL,
    status TEXT NOT NULL,
    recommendation_rank INTEGER NOT NULL DEFAULT 0,
    scan_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_environment_candidates_order
ON environment_candidates(recommendation_rank DESC, python_path ASC);
CREATE INDEX IF NOT EXISTS ix_environment_candidates_scan
ON environment_candidates(scan_id);
CREATE TABLE IF NOT EXISTS model_files (
    normalized_path TEXT PRIMARY KEY,
    path TEXT NOT NULL,
    name TEXT NOT NULL,
    format TEXT NOT NULL,
    size_bytes INTEGER NOT NULL DEFAULT 0,
    modified_at TEXT NOT NULL DEFAULT '',
    volume TEXT NOT NULL DEFAULT '',
    scan_id TEXT NOT NULL,
    generation INTEGER NOT NULL,
    payload_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_model_files_name
ON model_files(name COLLATE NOCASE, normalized_path);
CREATE INDEX IF NOT EXISTS ix_model_files_scan
ON model_files(scan_id);
"""

_SCHEMA_VERSION = 1
_INIT_LOCK_TIMEOUT = 30

_KIND_ALIASES = {
    "environment": "environment",
    "environments": "environment",
    "ultralytics_environment": "environment",
    "models": "models",
    "model": "models",
    "local_models": "models",
}
_SENSITIVE_KEY = re.compile(
    r"(?i)(?:secret|password|passwd|token|credential|authorization|cookie|"
    r"api[_-]?key|access[_-]?key|private[_-]?key)"
)
_ENVIRONMENT_KEYS = {
    "env",
    "environ",
    "environment",
    "environment_var",
    "environment_vars",
    "environment_variables",
    "os_environ",
    "process_environment",
    "process_env",
}
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL|API_KEY|"
    r"ACCESS_KEY|PRIVATE_KEY)[A-Z0-9_]*)\s*[:=]\s*([^\s,;]+)"
)
_BEARER = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]+")
_CURSOR_TEXT = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")
_MAX_TEXT = 16_384
_MAX_SEQUENCE = 1024
_MAX_DEPTH = 8


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _kind(value: object) -> str:
    raw = str(value or "").strip().lower()
    try:
        return _KIND_ALIASES[raw]
    except KeyError as error:
        raise ValueError(f"unsupported discovery cache kind: {raw or '<empty>'}") from error


def _scan_id(value: object) -> str:
    result = _redact_text(value).strip()
    if not result or len(result) > 256 or "\x00" in result:
        raise ValueError("scan_id must be a nonempty identifier")
    return result


def _generation(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("generation must be a positive integer")
    try:
        result = int(value)
    except (TypeError, ValueError, OverflowError) as error:
        raise ValueError("generation must be a positive integer") from error
    if result < 1 or result > 2**63 - 1:
        raise ValueError("generation must be a positive integer")
    return result


def _bounded_int(value: object, *, minimum: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    try:
        result = int(value or 0)
    except (TypeError, ValueError, OverflowError):
        return minimum
    return max(minimum, min(result, 2**63 - 1))


def _redact_text(value: object) -> str:
    text = str(value or "")[:_MAX_TEXT]
    text = _SECRET_ASSIGNMENT.sub(lambda match: f"{match.group(1)}=[REDACTED]", text)
    return _BEARER.sub("Bearer [REDACTED]", text)


def _safe_json(value: object, *, key: str = "", depth: int = 0) -> Any:
    """Return bounded JSON data while excluding credentials and process envs."""
    key_lower = key.strip().lower()
    if key_lower in _ENVIRONMENT_KEYS or _SENSITIVE_KEY.search(key_lower):
        return None
    if depth > _MAX_DEPTH:
        return None
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, (str, Path)):
        return _redact_text(value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for child_key, child_value in list(value.items())[:_MAX_SEQUENCE]:
            raw_child_name = str(child_key)[:256]
            if raw_child_name.lower() in _ENVIRONMENT_KEYS or _SENSITIVE_KEY.search(raw_child_name):
                continue
            child_name = _redact_text(raw_child_name)
            result[child_name] = _safe_json(
                child_value, key=child_name, depth=depth + 1
            )
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            _safe_json(item, key=key, depth=depth + 1)
            for item in list(value)[:_MAX_SEQUENCE]
        ]
    return _redact_text(value)


def _safe_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    value = _safe_json(row)
    return value if isinstance(value, dict) else {}


def _path_parts(value: object) -> tuple[str, str]:
    """Return a portable normalized identity and an absolute display path."""
    raw = _redact_text(value).strip()
    if not raw or "\x00" in raw:
        raise ValueError("path must be nonempty")

    windows = PureWindowsPath(raw)
    if windows.drive or raw.startswith("\\\\"):
        display = ntpath.normpath(raw)
        if not (ntpath.isabs(display) or display.startswith("\\\\")):
            raise ValueError("path must be absolute")
        return "windows:" + display.replace("\\", "/").casefold(), display

    posix = PurePosixPath(raw)
    if posix.is_absolute():
        display = posixpath.normpath(raw)
        return "posix:" + display, display

    display = str(Path(raw).expanduser().resolve(strict=False))
    native_key = os.path.normcase(os.path.normpath(display)).replace("\\", "/")
    return "native:" + native_key, display


def _basename(value: str) -> str:
    if "\\" in value:
        return PureWindowsPath(value).name
    return PurePosixPath(value).name


def _encode_cursor(generation: int, normalized_path: str) -> str:
    body = json.dumps(
        {"v": 1, "generation": generation, "path": normalized_path},
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return base64.urlsafe_b64encode(body).decode("ascii").rstrip("=")


def _decode_cursor(value: object) -> tuple[int, str]:
    raw = str(value or "")
    try:
        if not raw or not _CURSOR_TEXT.fullmatch(raw):
            raise ValueError
        padded = raw + "=" * (-len(raw) % 4)
        decoded = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        payload = json.loads(decoded.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {"v", "generation", "path"}:
            raise ValueError
        if payload["v"] != 1 or isinstance(payload["generation"], bool):
            raise ValueError
        generation = int(payload["generation"])
        normalized_path = str(payload["path"])
        if generation < 0 or not normalized_path or len(normalized_path) > _MAX_TEXT:
            raise ValueError
        return generation, normalized_path
    except Exception as error:
        raise ValueError("invalid model cursor") from error


@dataclass(frozen=True)
class ModelPage:
    items: tuple[dict[str, Any], ...]
    next_cursor: str | None


class DiscoveryCache:
    """Persist completed discovery snapshots independently by resource kind."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        try:
            database.row_factory = sqlite3.Row
            database.execute("PRAGMA foreign_keys=ON")
            database.execute("PRAGMA busy_timeout=30000")
            return database
        except BaseException:
            database.close()
            raise

    def _initialize(self) -> None:
        # journal_mode is persistent database state. Reasserting WAL on every
        # connection can participate in startup lock races, so schema/WAL setup
        # has one cross-process owner and is version-gated.
        lock = FileLock(f"{self.path}.init.lock", timeout=_INIT_LOCK_TIMEOUT)
        with lock:
            with closing(self._connect()) as database:
                version = int(database.execute("PRAGMA user_version").fetchone()[0])
                if version > _SCHEMA_VERSION:
                    raise RuntimeError(
                        f"resource discovery cache schema {version} is newer than supported {_SCHEMA_VERSION}"
                    )
                if version == _SCHEMA_VERSION:
                    return
                mode = str(database.execute("PRAGMA journal_mode").fetchone()[0]).lower()
                if mode != "wal":
                    mode = str(database.execute("PRAGMA journal_mode=WAL").fetchone()[0]).lower()
                if mode != "wal":
                    raise RuntimeError(f"resource discovery cache requires WAL mode, got {mode}")
                database.executescript(_SCHEMA)
                database.executemany(
                    "INSERT OR IGNORE INTO cache_meta(cache_kind) VALUES (?)",
                    (("environment",), ("models",)),
                )
                database.execute(f"PRAGMA user_version={_SCHEMA_VERSION}")

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with closing(self._connect()) as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                yield database
            except BaseException:
                if database.in_transaction:
                    database.rollback()
                raise
            else:
                database.commit()

    def journal_mode(self) -> str:
        with closing(self._connect()) as database:
            return str(database.execute("PRAGMA journal_mode").fetchone()[0]).lower()

    def next_generation(self, cache_kind: str) -> int:
        kind = _kind(cache_kind)
        with self._transaction() as database:
            database.execute(
                """
                UPDATE cache_meta
                SET allocated_generation = allocated_generation + 1
                WHERE cache_kind = ?
                """,
                (kind,),
            )
            return int(
                database.execute(
                    "SELECT allocated_generation FROM cache_meta WHERE cache_kind = ?",
                    (kind,),
                ).fetchone()[0]
            )

    @staticmethod
    def _publication_decision(
        database: sqlite3.Connection, kind: str, scan_id: str, generation: int
    ) -> str:
        row = database.execute(
            """
            SELECT completed_generation, completed_scan_id
            FROM cache_meta WHERE cache_kind = ?
            """,
            (kind,),
        ).fetchone()
        completed_generation = int(row["completed_generation"])
        completed_scan_id = str(row["completed_scan_id"] or "")
        if generation < completed_generation:
            return "stale"
        if generation == completed_generation and completed_scan_id not in {"", scan_id}:
            return "stale"
        if generation == completed_generation and completed_scan_id == scan_id:
            return "unchanged"
        return "publish"

    @staticmethod
    def _complete(
        database: sqlite3.Connection,
        kind: str,
        scan_id: str,
        generation: int,
        row_count: int,
    ) -> None:
        database.execute(
            """
            UPDATE cache_meta
            SET allocated_generation = MAX(allocated_generation, ?),
                completed_generation = ?, completed_scan_id = ?,
                completed_at = ?, row_count = ?
            WHERE cache_kind = ?
            """,
            (generation, generation, scan_id, _now(), row_count, kind),
        )

    def replace_environments(
        self,
        scan_id: str,
        rows: Iterable[Mapping[str, Any]],
        generation: int,
    ) -> bool:
        owner = _scan_id(scan_id)
        generation_value = _generation(generation)
        with self._transaction() as database:
            decision = self._publication_decision(
                database, "environment", owner, generation_value
            )
            if decision == "stale":
                return False
            if decision == "unchanged":
                return True
            database.execute(
                "DELETE FROM environment_candidates WHERE scan_id = ?", (owner,)
            )
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("environment candidate must be a mapping")
                normalized_path, python_path = _path_parts(row.get("python_path"))
                payload = _safe_payload(row)
                status = str(payload.get("status") or "UNAVAILABLE").strip().upper()
                rank = _bounded_int(payload.get("recommendation_rank"), minimum=-(2**31))
                payload.update(
                    {
                        "python_path": python_path,
                        "status": status,
                        "recommendation_rank": rank,
                    }
                )
                payload.pop("recommended", None)
                database.execute(
                    """
                    INSERT INTO environment_candidates
                    (normalized_python_path, python_path, status, recommendation_rank,
                     scan_id, generation, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(normalized_python_path) DO UPDATE SET
                      python_path=excluded.python_path, status=excluded.status,
                      recommendation_rank=excluded.recommendation_rank,
                      scan_id=excluded.scan_id, generation=excluded.generation,
                      payload_json=excluded.payload_json
                    """,
                    (
                        normalized_path,
                        python_path,
                        status,
                        rank,
                        owner,
                        generation_value,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    ),
                )
            database.execute(
                "DELETE FROM environment_candidates WHERE scan_id <> ?", (owner,)
            )
            count = int(
                database.execute(
                    "SELECT COUNT(*) FROM environment_candidates WHERE scan_id = ?", (owner,)
                ).fetchone()[0]
            )
            self._complete(database, "environment", owner, generation_value, count)
        return True

    def list_environments(self) -> list[dict[str, Any]]:
        with closing(self._connect()) as database:
            rows = database.execute(
                """
                SELECT payload_json, python_path, status, recommendation_rank
                FROM environment_candidates
                ORDER BY recommendation_rank DESC, python_path ASC
                """
            ).fetchall()
        result: list[dict[str, Any]] = []
        recommended_assigned = False
        for row in rows:
            payload = dict(json.loads(row["payload_json"]))
            payload.update(
                {
                    "python_path": str(row["python_path"]),
                    "status": str(row["status"]),
                    "recommendation_rank": int(row["recommendation_rank"]),
                }
            )
            is_recommended = not recommended_assigned and payload["status"] == "AVAILABLE"
            payload["recommended"] = is_recommended
            recommended_assigned = recommended_assigned or is_recommended
            result.append(payload)
        return result

    def replace_models(
        self,
        scan_id: str,
        rows: Iterable[Mapping[str, Any]],
        generation: int,
    ) -> bool:
        owner = _scan_id(scan_id)
        generation_value = _generation(generation)
        with self._transaction() as database:
            decision = self._publication_decision(
                database, "models", owner, generation_value
            )
            if decision == "stale":
                return False
            if decision == "unchanged":
                return True
            database.execute("DELETE FROM model_files WHERE scan_id = ?", (owner,))
            for row in rows:
                if not isinstance(row, Mapping):
                    raise ValueError("model file must be a mapping")
                normalized_path, model_path = _path_parts(row.get("path"))
                payload = _safe_payload(row)
                name = str(payload.get("name") or _basename(model_path))
                model_format = str(
                    payload.get("format") or PurePosixPath(name.replace("\\", "/")).suffix.lstrip(".")
                ).strip().lower()
                size_bytes = _bounded_int(payload.get("size_bytes"))
                modified_at = str(payload.get("modified_at") or "")
                volume = str(payload.get("volume") or "")
                payload.update(
                    {
                        "path": model_path,
                        "name": name,
                        "format": model_format,
                        "size_bytes": size_bytes,
                        "modified_at": modified_at,
                        "volume": volume,
                    }
                )
                database.execute(
                    """
                    INSERT INTO model_files
                    (normalized_path, path, name, format, size_bytes, modified_at,
                     volume, scan_id, generation, payload_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(normalized_path) DO UPDATE SET
                      path=excluded.path, name=excluded.name, format=excluded.format,
                      size_bytes=excluded.size_bytes, modified_at=excluded.modified_at,
                      volume=excluded.volume, scan_id=excluded.scan_id,
                      generation=excluded.generation, payload_json=excluded.payload_json
                    """,
                    (
                        normalized_path,
                        model_path,
                        name,
                        model_format,
                        size_bytes,
                        modified_at,
                        volume,
                        owner,
                        generation_value,
                        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    ),
                )
            database.execute("DELETE FROM model_files WHERE scan_id <> ?", (owner,))
            count = int(
                database.execute(
                    "SELECT COUNT(*) FROM model_files WHERE scan_id = ?", (owner,)
                ).fetchone()[0]
            )
            self._complete(database, "models", owner, generation_value, count)
        return True

    @staticmethod
    def _model_payload(row: sqlite3.Row) -> dict[str, Any]:
        payload = dict(json.loads(row["payload_json"]))
        payload.update(
            {
                "path": str(row["path"]),
                "name": str(row["name"]),
                "format": str(row["format"]),
                "size_bytes": int(row["size_bytes"]),
                "modified_at": str(row["modified_at"]),
                "volume": str(row["volume"]),
            }
        )
        return payload

    def list_models(self, limit: int = 200, cursor: str | None = None) -> ModelPage:
        if isinstance(limit, bool):
            raise ValueError("model page limit must be an integer")
        try:
            page_size = int(limit)
        except (TypeError, ValueError, OverflowError) as error:
            raise ValueError("model page limit must be an integer") from error
        if page_size < 1 or page_size > 5000:
            raise ValueError("model page limit must be between 1 and 5000")

        with closing(self._connect()) as database:
            database.execute("BEGIN")
            try:
                meta = database.execute(
                    "SELECT completed_generation FROM cache_meta WHERE cache_kind = 'models'"
                ).fetchone()
                current_generation = int(meta["completed_generation"])
                after = ""
                if cursor is not None:
                    cursor_generation, after = _decode_cursor(cursor)
                    if cursor_generation != current_generation:
                        raise ValueError("stale model cursor")
                rows = database.execute(
                    """
                    SELECT * FROM model_files
                    WHERE normalized_path > ?
                    ORDER BY normalized_path ASC
                    LIMIT ?
                    """,
                    (after, page_size + 1),
                ).fetchall()
                database.execute("COMMIT")
            except BaseException:
                database.execute("ROLLBACK")
                raise
        has_more = len(rows) > page_size
        visible = rows[:page_size]
        next_cursor = (
            _encode_cursor(current_generation, str(visible[-1]["normalized_path"]))
            if has_more and visible
            else None
        )
        return ModelPage(
            items=tuple(self._model_payload(row) for row in visible),
            next_cursor=next_cursor,
        )

    def find_models_by_name(self, names: Sequence[object] | Iterable[object]) -> list[dict[str, Any]]:
        requested = {
            str(name or "").strip().casefold()
            for name in names
            if str(name or "").strip()
        }
        if not requested:
            return []
        found: dict[str, sqlite3.Row] = {}
        ordered_names = sorted(requested)
        with closing(self._connect()) as database:
            for offset in range(0, len(ordered_names), 500):
                chunk = ordered_names[offset : offset + 500]
                placeholders = ",".join("?" for _ in chunk)
                for row in database.execute(
                    f"""
                    SELECT * FROM model_files
                    WHERE lower(name) IN ({placeholders})
                    ORDER BY normalized_path ASC
                    """,
                    tuple(chunk),
                ):
                    found[str(row["normalized_path"])] = row
        return [self._model_payload(found[key]) for key in sorted(found)]

    def model_count(self) -> int:
        with closing(self._connect()) as database:
            return int(database.execute("SELECT COUNT(*) FROM model_files").fetchone()[0])

    def metadata(self) -> dict[str, dict[str, Any]]:
        with closing(self._connect()) as database:
            rows = database.execute(
                """
                SELECT cache_kind, allocated_generation, completed_generation,
                       completed_scan_id, completed_at, row_count
                FROM cache_meta ORDER BY cache_kind
                """
            ).fetchall()
        return {
            str(row["cache_kind"]): {
                "allocated_generation": int(row["allocated_generation"]),
                "completed_generation": int(row["completed_generation"]),
                "scan_id": row["completed_scan_id"],
                "completed_at": row["completed_at"],
                "row_count": int(row["row_count"]),
            }
            for row in rows
        }
