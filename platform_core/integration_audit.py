from __future__ import annotations

import json
import re
import sqlite3
import uuid
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


_SENSITIVE = re.compile(r"(?i)(authorization|access[_-]?secret|access[_-]?key|secret|password|token|signature|cookie)")
_MAX_JSON_CHARS = 12000


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def redact(value: Any) -> Any:
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for key, item in value.items():
            text = str(key)
            result[text] = "***" if _SENSITIVE.search(text) else redact(item)
        return result
    if isinstance(value, (list, tuple)):
        return [redact(item) for item in value]
    if isinstance(value, bytes):
        return f"<bytes:{len(value)}>"
    if isinstance(value, Path):
        return str(value)
    return value


def _safe_json(value: Any) -> str:
    try:
        text = json.dumps(redact(value), ensure_ascii=False, default=str, separators=(",", ":"))
    except Exception:
        text = json.dumps({"value": str(value)}, ensure_ascii=False)
    if len(text) > _MAX_JSON_CHARS:
        return text[:_MAX_JSON_CHARS] + "…"
    return text


_SCHEMA = """
CREATE TABLE IF NOT EXISTS external_interaction_logs (
    log_id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    operation TEXT NOT NULL,
    stage TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL,
    method TEXT NOT NULL DEFAULT '',
    endpoint TEXT NOT NULL DEFAULT '',
    http_status INTEGER,
    business_code TEXT NOT NULL DEFAULT '',
    duration_ms INTEGER NOT NULL DEFAULT 0,
    request_id TEXT NOT NULL DEFAULT '',
    correlation_id TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    algorithm_id TEXT NOT NULL DEFAULT '',
    version_id TEXT NOT NULL DEFAULT '',
    artifact_id TEXT NOT NULL DEFAULT '',
    external_product_id TEXT NOT NULL DEFAULT '',
    external_analysis_id TEXT NOT NULL DEFAULT '',
    external_algo_version_id TEXT NOT NULL DEFAULT '',
    external_weight_id TEXT NOT NULL DEFAULT '',
    retry_count INTEGER NOT NULL DEFAULT 0,
    request_json TEXT NOT NULL DEFAULT '{}',
    response_json TEXT NOT NULL DEFAULT '{}',
    error_code TEXT NOT NULL DEFAULT '',
    error_message TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_external_interaction_logs_created
ON external_interaction_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS ix_external_interaction_logs_provider_status
ON external_interaction_logs(provider, status, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_external_interaction_logs_operation
ON external_interaction_logs(operation, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_external_interaction_logs_algorithm
ON external_interaction_logs(project_id, algorithm_id, version_id, created_at DESC);
"""


class IntegrationAuditRepository:
    """Structured, secret-redacted audit trail for external platform interactions."""

    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir) / "integration_audit"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "interactions.sqlite3"
        with closing(self._connect()) as database:
            database.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA busy_timeout=5000")
        return database

    def record(self, event: Mapping[str, Any]) -> dict[str, Any]:
        log_id = str(event.get("log_id") or uuid.uuid4().hex)
        status = str(event.get("status") or "FAILED").upper()
        if status not in {"SUCCESS", "FAILED", "UNKNOWN"}:
            status = "FAILED"
        created_at = str(event.get("created_at") or utc_now())
        values = (
            log_id,
            str(event.get("provider") or "changlian"),
            str(event.get("operation") or "http_request"),
            str(event.get("stage") or ""),
            status,
            str(event.get("method") or "").upper(),
            str(event.get("endpoint") or ""),
            int(event["http_status"]) if event.get("http_status") not in (None, "") else None,
            str(event.get("business_code") or ""),
            max(0, int(event.get("duration_ms") or 0)),
            str(event.get("request_id") or ""),
            str(event.get("correlation_id") or log_id),
            str(event.get("project_id") or ""),
            str(event.get("algorithm_id") or ""),
            str(event.get("version_id") or ""),
            str(event.get("artifact_id") or ""),
            str(event.get("external_product_id") or ""),
            str(event.get("external_analysis_id") or ""),
            str(event.get("external_algo_version_id") or ""),
            str(event.get("external_weight_id") or ""),
            max(0, int(event.get("retry_count") or 0)),
            _safe_json(event.get("request") or {}),
            _safe_json(event.get("response") or {}),
            str(event.get("error_code") or ""),
            str(event.get("error_message") or "")[:4000],
            created_at,
        )
        with closing(self._connect()) as database:
            database.execute(
                """
                INSERT INTO external_interaction_logs (
                    log_id, provider, operation, stage, status, method, endpoint, http_status,
                    business_code, duration_ms, request_id, correlation_id, project_id,
                    algorithm_id, version_id, artifact_id, external_product_id,
                    external_analysis_id, external_algo_version_id, external_weight_id,
                    retry_count, request_json, response_json, error_code, error_message, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                values,
            )
        return self.get(log_id) or {}

    @staticmethod
    def _public(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
        item = dict(row)
        for key in ("request_json", "response_json"):
            try:
                item[key.removesuffix("_json")] = json.loads(item.pop(key) or "{}")
            except (TypeError, json.JSONDecodeError):
                item[key.removesuffix("_json")] = {}
        return item

    def get(self, log_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as database:
            row = database.execute(
                "SELECT * FROM external_interaction_logs WHERE log_id = ?", (str(log_id),)
            ).fetchone()
        return self._public(row) if row else None

    def list(
        self,
        *,
        provider: str = "changlian",
        status: str = "",
        operation: str = "",
        project_id: str = "",
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["provider = ?"]
        args: list[Any] = [str(provider)]
        if status:
            clauses.append("status = ?")
            args.append(str(status).upper())
        if operation:
            clauses.append("operation = ?")
            args.append(str(operation))
        if project_id:
            clauses.append("project_id = ?")
            args.append(str(project_id))
        args.extend([max(1, min(200, int(limit))), max(0, int(offset))])
        sql = (
            "SELECT * FROM external_interaction_logs WHERE " + " AND ".join(clauses)
            + " ORDER BY created_at DESC, log_id DESC LIMIT ? OFFSET ?"
        )
        with closing(self._connect()) as database:
            rows = database.execute(sql, args).fetchall()
        return [self._public(row) for row in rows]

    def summary(self, *, provider: str = "changlian", hours: int = 24) -> dict[str, Any]:
        hours = max(1, min(24 * 30, int(hours)))
        with closing(self._connect()) as database:
            row = database.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status='SUCCESS' THEN 1 ELSE 0 END) AS success,
                    SUM(CASE WHEN status='FAILED' THEN 1 ELSE 0 END) AS failed,
                    SUM(CASE WHEN status='UNKNOWN' THEN 1 ELSE 0 END) AS unknown,
                    COALESCE(ROUND(AVG(duration_ms)), 0) AS avg_duration_ms
                FROM external_interaction_logs
                WHERE provider = ? AND created_at >= datetime('now', ?)
                """,
                (str(provider), f"-{hours} hours"),
            ).fetchone()
        return {
            "hours": hours,
            "total": int(row["total"] or 0),
            "success": int(row["success"] or 0),
            "failed": int(row["failed"] or 0),
            "unknown": int(row["unknown"] or 0),
            "avg_duration_ms": int(row["avg_duration_ms"] or 0),
        }
