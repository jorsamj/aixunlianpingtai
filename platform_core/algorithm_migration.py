"""Single-domain algorithm migration: export, import, resume, dry run, report.

This is the real cutover tool for the algorithm domain only (T8.2).  The source
is the existing SQLite ``algorithms.sqlite3``; the target is the relational
``w5_algorithm`` PostgreSQL schema created by
:mod:`platform_core.algorithm_postgres_schema`.  The legacy read-only shadow
(``w5_shadow``) is untouched and keeps its own reconciliation role.

Guarantees implemented here:

* original ids (algorithm, version, external analysis) are copied verbatim and
  the report proves the primary-key sets are equal, never regenerated;
* object-storage references stay strings (never resolved, never copied);
* SecretStore credentials are never read or exported; any credential-looking
  payload is refused instead of silently copied;
* imports are transactional, idempotent, interruption-safe and resumable;
* JSON, NULL/empty and revision semantics are compared in the report.

The tool never runs an implicit schema migration: callers must initialise the
schema explicitly first.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from .algorithm_postgres_schema import (
    require_current_schema,
    require_idle_transaction,
    schema_status,
)
from .algorithm_postgres_store import export_target_snapshot
from .algorithm_shadow import _digest, _snapshot_body, export_snapshot_from_path, validate_snapshot
from .algorithm_sql_store import SCHEMA_VERSION as SQLITE_SCHEMA_VERSION
from .algorithm_sql_store import AlgorithmSqlStore

CONTRACT_VERSION = "algorithm-migration-v1"
DEFAULT_ACTOR = "algorithm-migration-cli"
DEFAULT_STALE_RUN_SECONDS = 300

TABLES = ("algorithms", "versions", "analyses")
_JSON_FIELDS = {
    "algorithms": ("payload_json",),
    "versions": ("payload_json",),
    "analyses": ("payload_json", "compute_platform_ids_json"),
}
_BOOL_FIELDS = {
    "algorithms": ("external_active", "master_data_readonly"),
    "versions": ("artifact_verified", "trainable"),
    "analyses": ("is_default", "active"),
}
_OBJECT_REFERENCE_COLUMNS = ("stored_path",)
_OBJECT_REFERENCE_KEYS = frozenset({
    "stored_path", "model_path", "artifact_path", "checkpoint_path", "dataset_path",
    "bundle_path", "object_key", "oss_key", "oss_uri", "s3_uri", "storage_key",
    "artifact_ref", "model_uri", "weight_path", "weights_path",
})
_SENSITIVE_KEYS = frozenset({
    "password", "passwd", "secret", "token", "access_token", "refresh_token",
    "api_key", "apikey", "access_key", "access_key_id", "secret_key",
    "secret_access_key", "credential", "credentials", "private_key",
    "client_secret", "authorization", "auth_token",
})
_SECRET_REFERENCE = re.compile(r"^(secret|vault|keyring|env|ref):|^\$\{[^}]+\}$", re.IGNORECASE)

# SQLite row shape used for reverse restoration.  Column names and order match
# the existing store schema; values are copied, not reinterpreted.
_SQLITE_COLUMNS = {
    "algorithms": (
        "id, project_id, name, remark, industry, algorithm_type, current_version_id, "
        "source_type, provider_type, external_product_id, external_product_code, "
        "external_category_id, external_analysis_id, external_active, master_data_readonly, "
        "external_last_synced_at, created_at, updated_at, sort_index, payload_json"
    ),
    "versions": (
        "id, algorithm_id, version_name, version_no, training_job_id, framework, "
        "training_status, stored_path, model_name, artifact_verified, trainable, "
        "external_analysis_id, external_algo_version_id, external_publish_status, "
        "created_at, finished_at, sort_index, payload_json"
    ),
    "analyses": (
        "algorithm_id, external_analysis_id, analysis_name, analysis_type, is_default, "
        "active, compute_platform_ids_json, sort_index, payload_json"
    ),
}
_SQLITE_ORDER = {
    "algorithms": "ORDER BY project_id, id",
    "versions": "ORDER BY algorithm_id, id",
    "analyses": "ORDER BY algorithm_id, external_analysis_id",
}
_SQLITE_TABLES = {
    "algorithms": "algorithms",
    "versions": "algorithm_versions",
    "analyses": "algorithm_external_analyses",
}


class AlgorithmMigrationError(RuntimeError):
    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


class _DryRunRollback(Exception):
    pass


# ---------------------------------------------------------------------------
# normalization, digests
# ---------------------------------------------------------------------------
def _json_value(field: str, raw: Any) -> Any:
    if not isinstance(raw, str):
        return raw
    empty: Any = {} if field == "payload_json" else []
    if not raw.strip():
        return empty
    try:
        return json.loads(raw)
    except ValueError:
        return raw


def normalize_row(name: str, row: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(row)
    for field in _JSON_FIELDS.get(name, ()):
        if field in value:
            value[field] = _json_value(field, value[field])
    for field in _BOOL_FIELDS.get(name, ()):
        if field in value:
            raw = value[field]
            value[field] = None if raw is None else (1 if bool(raw) else 0)
    return value


def normalized_tables(snapshot: Mapping[str, Any]) -> dict[str, list[dict]]:
    tables = snapshot.get("tables") or {}
    return {
        name: [normalize_row(name, row) for row in tables.get(name) or []]
        for name in TABLES
    }


def normalize_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return a valid snapshot whose JSON cells compare structurally."""
    tables = normalized_tables(snapshot)
    body = _snapshot_body(
        str(snapshot["project_id"]), int(snapshot["algorithm_revision"]), tables
    )
    body["snapshot_digest"] = _digest(body)
    body["captured_at"] = str(snapshot["captured_at"])
    return validate_snapshot(body)


def content_digest(snapshot: Mapping[str, Any]) -> str:
    """Engine-independent digest over normalized project content."""
    return _digest({
        "project_id": str(snapshot["project_id"]),
        "algorithm_revision": int(snapshot["algorithm_revision"]),
        "tables": normalized_tables(snapshot),
    })


def _natural_key(name: str, row: Mapping[str, Any]) -> str:
    if name == "algorithms" or name == "versions":
        return str(row.get("id") or "")
    return f"{row.get('algorithm_id')}:{row.get('external_analysis_id')}"


# ---------------------------------------------------------------------------
# source export
# ---------------------------------------------------------------------------
def export_source_snapshot(db_path: str | Path, project_id: str) -> dict[str, Any]:
    snapshot = export_snapshot_from_path(db_path, project_id)
    _scan_secret_material(snapshot)
    return snapshot


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------
def import_snapshot(
    connection,
    snapshot: Mapping[str, Any],
    *,
    dry_run: bool = False,
    resume: bool = False,
    actor: str = DEFAULT_ACTOR,
    run_id: str | None = None,
    stale_after_seconds: int = DEFAULT_STALE_RUN_SECONDS,
) -> dict[str, Any]:
    """Import one project snapshot into ``w5_algorithm`` (idempotent, resumable)."""
    snapshot = validate_snapshot(snapshot)
    require_current_schema(connection)
    _scan_secret_material(snapshot)
    require_idle_transaction(connection, purpose="algorithm import")
    project_id = str(snapshot["project_id"])
    revision = int(snapshot["algorithm_revision"])
    digest = str(snapshot["snapshot_digest"])
    content = content_digest(snapshot)
    mode = "DRY_RUN" if dry_run else "APPLY"
    run, resumed = _begin_run(
        connection,
        project_id=project_id,
        digest=digest,
        content=content,
        revision=revision,
        mode=mode,
        actor=str(actor or DEFAULT_ACTOR),
        run_id=run_id,
        resume=resume,
        stale_after_seconds=int(stale_after_seconds),
    )
    counts = {name: len(snapshot["tables"][name]) for name in TABLES}
    result: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "run_id": run,
        "resumed": resumed,
        "mode": mode,
        "project_id": project_id,
        "source_revision": revision,
        "snapshot_digest": digest,
        "content_digest": content,
        "counts": counts,
        "dry_run": bool(dry_run),
        "action": "noop",
        "changed": False,
        "target_revision_before": None,
        "target_revision_after": None,
    }
    try:
        try:
            with connection.transaction():
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (f"algorithm-import:{project_id}",),
                    )
                target = export_target_snapshot(connection, project_id)
                target_revision = (
                    int(target["algorithm_revision"]) if target is not None else None
                )
                result["target_revision_before"] = target_revision
                action = _import_action(target, revision, content)
                result["action"] = action
                if action == "apply":
                    with connection.cursor() as cursor:
                        _delete_target_graph(cursor, project_id)
                        _write_target_rows(cursor, snapshot)
                        _set_target_revision(cursor, project_id, revision)
                    result["target_revision_after"] = revision
                    if not dry_run:
                        result["changed"] = True
                if dry_run:
                    raise _DryRunRollback()
        except _DryRunRollback:
            result["dry_run"] = True
            result["changed"] = False
            result["target_revision_after"] = result["target_revision_before"]
    except BaseException as error:
        _finish_run(connection, run, "FAILED", {
            "error": type(error).__name__,
            "detail": str(error),
            "action": result["action"],
        })
        raise
    _finish_run(connection, run, "COMPLETED", {
        "action": result["action"],
        "counts": counts,
        "content_digest": content,
        "mode": mode,
    })
    return result


def _import_action(target: Mapping[str, Any] | None, revision: int, content: str) -> str:
    if target is None:
        return "apply"
    target_revision = int(target["algorithm_revision"])
    if target_revision > revision:
        raise AlgorithmMigrationError(
            "ALGORITHM_MIGRATION_REVISION_REGRESSION",
            "target already holds newer algorithm writes",
            detail=f"target={target_revision} source={revision}",
        )
    if target_revision == revision:
        if content_digest(target) == content:
            return "noop"
        raise AlgorithmMigrationError(
            "ALGORITHM_MIGRATION_DIGEST_CONFLICT",
            "same algorithm revision has different content",
            detail="refusing to overwrite a divergent target at the same revision",
        )
    return "apply"


def _delete_target_graph(cursor, project_id: str) -> None:
    cursor.execute(
        "DELETE FROM w5_algorithm.algorithm_version WHERE project_id=%s",
        (project_id,),
    )
    cursor.execute(
        "DELETE FROM w5_algorithm.algorithm_external_analysis WHERE project_id=%s",
        (project_id,),
    )
    cursor.execute("DELETE FROM w5_algorithm.algorithm WHERE project_id=%s", (project_id,))


def _bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


def _json_text(value: Any, field: str) -> str:
    raw = _json_value(field, value)
    if isinstance(raw, str):
        raise AlgorithmMigrationError(
            "ALGORITHM_MIGRATION_JSON_INVALID",
            "snapshot JSON field is not valid JSON",
            detail=f"field={field}",
        )
    return json.dumps(raw, ensure_ascii=False, separators=(",", ":"))


def _write_target_rows(cursor, snapshot: Mapping[str, Any]) -> None:
    project_id = str(snapshot["project_id"])
    algorithms = snapshot["tables"]["algorithms"]
    versions = snapshot["tables"]["versions"]
    analyses = snapshot["tables"]["analyses"]
    if algorithms:
        cursor.executemany(
            "INSERT INTO w5_algorithm.algorithm (id,project_id,name,remark,industry,"
            "algorithm_type,current_version_id,source_type,provider_type,external_product_id,"
            "external_product_code,external_category_id,external_analysis_id,external_active,"
            "master_data_readonly,external_last_synced_at,created_at,updated_at,sort_index,payload)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            [
                (
                    str(row["id"]), project_id, str(row.get("name") or ""),
                    str(row.get("remark") or ""), str(row.get("industry") or ""),
                    str(row.get("algorithm_type") or ""),
                    row.get("current_version_id"), row.get("source_type"),
                    row.get("provider_type"), row.get("external_product_id"),
                    row.get("external_product_code"), row.get("external_category_id"),
                    row.get("external_analysis_id"),
                    _bool(row.get("external_active")),
                    _bool(row.get("master_data_readonly")),
                    row.get("external_last_synced_at"), row.get("created_at"),
                    row.get("updated_at"), int(row.get("sort_index") or 0),
                    _json_text(row.get("payload_json"), "payload_json"),
                )
                for row in algorithms
            ],
        )
    if versions:
        cursor.executemany(
            "INSERT INTO w5_algorithm.algorithm_version (project_id,id,algorithm_id,version_name,"
            "version_no,training_job_id,framework,training_status,stored_path,model_name,"
            "artifact_verified,trainable,external_analysis_id,external_algo_version_id,"
            "external_publish_status,created_at,finished_at,sort_index,payload)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            [
                (
                    project_id, str(row["id"]), str(row["algorithm_id"]), row.get("version_name"),
                    row.get("version_no"), row.get("training_job_id"), row.get("framework"),
                    row.get("training_status"), row.get("stored_path"), row.get("model_name"),
                    _bool(row.get("artifact_verified")), _bool(row.get("trainable")),
                    row.get("external_analysis_id"), row.get("external_algo_version_id"),
                    row.get("external_publish_status"), row.get("created_at"),
                    row.get("finished_at"), int(row.get("sort_index") or 0),
                    _json_text(row.get("payload_json"), "payload_json"),
                )
                for row in versions
            ],
        )
    if analyses:
        cursor.executemany(
            "INSERT INTO w5_algorithm.algorithm_external_analysis "
            "(project_id,algorithm_id,external_analysis_id,analysis_name,analysis_type,is_default,"
            "active,compute_platform_ids,sort_index,payload)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)",
            [
                (
                    project_id, str(row["algorithm_id"]), str(row["external_analysis_id"]),
                    row.get("analysis_name"), row.get("analysis_type"),
                    bool(row.get("is_default")), bool(row.get("active")),
                    _json_text(row.get("compute_platform_ids_json"), "compute_platform_ids_json"),
                    int(row.get("sort_index") or 0),
                    _json_text(row.get("payload_json"), "payload_json"),
                )
                for row in analyses
            ],
        )


def _set_target_revision(cursor, project_id: str, revision: int) -> None:
    cursor.execute(
        "INSERT INTO w5_algorithm.store_revision(project_id,algorithm_revision,updated_at) "
        "VALUES(%s,%s,now()) ON CONFLICT(project_id) DO UPDATE "
        "SET algorithm_revision=EXCLUDED.algorithm_revision, updated_at=now()",
        (project_id, int(revision)),
    )


# ---------------------------------------------------------------------------
# run bookkeeping (interruption-safe)
# ---------------------------------------------------------------------------
def _begin_run(
    connection,
    *,
    project_id: str,
    digest: str,
    content: str,
    revision: int,
    mode: str,
    actor: str,
    run_id: str | None,
    resume: bool,
    stale_after_seconds: int,
) -> tuple[str, bool]:
    from psycopg.rows import dict_row

    run = str(run_id or f"run-{uuid.uuid4().hex}")
    resumed = False
    require_idle_transaction(connection, purpose="algorithm import run")
    with connection.transaction():
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"algorithm-import:{project_id}",),
            )
            # A caller may supply a stable run id for one logical operation (the
            # maintenance switch does). Re-running it must reuse that recorded
            # attempt instead of inserting a second row that hides the identity
            # conflict: completed runs are never reopened, and an interrupted or
            # failed attempt is revived under the same id.
            cursor.execute(
                "SELECT run_id,project_id,status,snapshot_digest,content_digest,"
                "algorithm_revision,mode,"
                "EXTRACT(EPOCH FROM (now()-heartbeat_at)) AS age_seconds "
                "FROM w5_algorithm.migration_run WHERE run_id=%s",
                (run,),
            )
            recorded = cursor.fetchone()
            if recorded is not None:
                if (
                    str(recorded["project_id"]) != project_id
                    or str(recorded["snapshot_digest"]) != digest
                    or str(recorded["content_digest"]) != content
                    or int(recorded["algorithm_revision"]) != revision
                    or str(recorded["mode"]) != mode
                ):
                    raise AlgorithmMigrationError(
                        "ALGORITHM_MIGRATION_RUN_CONFLICT",
                        "this run id belongs to different import content",
                        detail=f"run_id={run}",
                    )
                recorded_status = str(recorded["status"])
                if recorded_status == "COMPLETED":
                    raise AlgorithmMigrationError(
                        "ALGORITHM_MIGRATION_RUN_ALREADY_COMPLETED",
                        "this run id already completed; prove the target instead",
                        detail=f"run_id={run}",
                    )
                if recorded_status == "RUNNING":
                    if not resume:
                        raise AlgorithmMigrationError(
                            "ALGORITHM_MIGRATION_RUN_IN_PROGRESS",
                            "this run id is already running",
                            detail=f"run_id={run} age={int(recorded['age_seconds'])}s",
                        )
                    if float(recorded["age_seconds"]) < stale_after_seconds:
                        raise AlgorithmMigrationError(
                            "ALGORITHM_MIGRATION_RUN_ACTIVE",
                            "the running import is still heartbeating; refusing takeover",
                            detail=f"run_id={run} age={int(recorded['age_seconds'])}s",
                        )
                cursor.execute(
                    "UPDATE w5_algorithm.migration_run SET status='RUNNING',"
                    "heartbeat_at=now(),finished_at=NULL,"
                    "detail=COALESCE(detail,'{}'::jsonb) || %s::jsonb WHERE run_id=%s",
                    (
                        json.dumps({"reopened": True, "previous_status": recorded_status}),
                        run,
                    ),
                )
                return run, True
            cursor.execute(
                "SELECT run_id,snapshot_digest,content_digest,algorithm_revision,mode,"
                "EXTRACT(EPOCH FROM (now()-heartbeat_at)) AS age_seconds "
                "FROM w5_algorithm.migration_run WHERE project_id=%s AND status='RUNNING' "
                "FOR UPDATE",
                (project_id,),
            )
            active = cursor.fetchone()
            if active is not None:
                if not resume:
                    raise AlgorithmMigrationError(
                        "ALGORITHM_MIGRATION_RUN_IN_PROGRESS",
                        "another algorithm import is running for this project",
                        detail=f"run_id={active['run_id']} age={int(active['age_seconds'])}s",
                    )
                if float(active["age_seconds"]) < stale_after_seconds:
                    raise AlgorithmMigrationError(
                        "ALGORITHM_MIGRATION_RUN_ACTIVE",
                        "the running import is still heartbeating; refusing takeover",
                        detail=f"run_id={active['run_id']} age={int(active['age_seconds'])}s",
                    )
                if (
                    str(active["snapshot_digest"]) != digest
                    or str(active["content_digest"]) != content
                    or int(active["algorithm_revision"]) != revision
                ):
                    raise AlgorithmMigrationError(
                        "ALGORITHM_MIGRATION_RUN_CONFLICT",
                        "the interrupted run belongs to different snapshot content",
                        detail=(
                            f"run_id={active['run_id']} digest={active['snapshot_digest']} "
                            f"requested={digest}"
                        ),
                    )
                cursor.execute(
                    "UPDATE w5_algorithm.migration_run SET status='ABORTED',finished_at=now(),"
                    "detail=detail || %s::jsonb WHERE run_id=%s",
                    (json.dumps({"aborted_by_resume": run}), active["run_id"]),
                )
                resumed = True
            cursor.execute(
                "INSERT INTO w5_algorithm.migration_run "
                "(run_id,project_id,snapshot_digest,content_digest,algorithm_revision,mode,"
                "status,actor,detail) VALUES (%s,%s,%s,%s,%s,%s,'RUNNING',%s,%s::jsonb)",
                (
                    run, project_id, digest, content, revision, mode, actor,
                    json.dumps({"resumed": resumed}),
                ),
            )
    return run, resumed


def _finish_run(connection, run_id: str, status: str, detail: Mapping[str, Any]) -> None:
    try:
        require_idle_transaction(connection, purpose="algorithm import bookkeeping")
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "UPDATE w5_algorithm.migration_run SET status=%s,finished_at=now(),"
                    "heartbeat_at=now(),detail=%s::jsonb WHERE run_id=%s",
                    (status, json.dumps(dict(detail), ensure_ascii=False), str(run_id)),
                )
    except Exception:
        # Never mask the original failure; the RUNNING row is itself the
        # interruption evidence that a later --resume run will consume.
        pass


def run_status(connection, project_id: str) -> dict[str, Any]:
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT run_id,snapshot_digest,content_digest,algorithm_revision,mode,status,"
            "actor,started_at,heartbeat_at,finished_at,detail "
            "FROM w5_algorithm.migration_run WHERE project_id=%s "
            "ORDER BY started_at DESC LIMIT 20",
            (str(project_id),),
        )
        runs = [dict(row) for row in cursor.fetchall()]
    for row in runs:
        for key in ("started_at", "heartbeat_at", "finished_at"):
            if row.get(key) is not None:
                row[key] = str(row[key])
    return {"project_id": str(project_id), "runs": runs}


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
def _check(ok: bool, **detail: Any) -> dict[str, Any]:
    return {"ok": bool(ok), **detail}


def _rows_by_key(name: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    return {_natural_key(name, row): row for row in rows}


def _null_class(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "false" if not value else "other"
    if isinstance(value, (int, float)) and value == 0:
        return "zero"
    if isinstance(value, str) and value == "":
        return "empty_string"
    return "other"


def _walk_secrets(value: Any, path: str, findings: list[str]) -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            child = f"{path}.{key}" if path else str(key)
            if str(key).lower() in _SENSITIVE_KEYS:
                if item in (None, "", [], {}):
                    continue
                if isinstance(item, str) and _SECRET_REFERENCE.search(item):
                    continue
                findings.append(child)
            _walk_secrets(item, child, findings)
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _walk_secrets(item, f"{path}[{index}]", findings)


def _scan_secret_material(snapshot: Mapping[str, Any]) -> None:
    findings: list[str] = []
    for name in TABLES:
        for row in (snapshot.get("tables") or {}).get(name) or []:
            payload = _json_value("payload_json", row.get("payload_json"))
            if isinstance(payload, (Mapping, list)):
                _walk_secrets(payload, f"{name}:{_natural_key(str(name), row)}", findings)
    if findings:
        raise AlgorithmMigrationError(
            "ALGORITHM_MIGRATION_SECRET_MATERIAL",
            "algorithm payload contains credential material; refusing to export or import it",
            detail=f"fields={findings[:10]}",
        )


def _object_references(name: str, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    count = 0
    non_string: list[str] = []
    for row in rows:
        key = _natural_key(name, row)
        for column in _OBJECT_REFERENCE_COLUMNS:
            value = row.get(column)
            if value in (None, ""):
                continue
            count += 1
            if not isinstance(value, str):
                non_string.append(f"{name}:{key}.{column}")
        payload = row.get("payload_json")
        if isinstance(payload, Mapping):
            for field, value in payload.items():
                if str(field) not in _OBJECT_REFERENCE_KEYS or value in (None, ""):
                    continue
                count += 1
                if not isinstance(value, str):
                    non_string.append(f"{name}:{key}.payload.{field}")
    return {"count": count, "non_string": sorted(non_string)}


def build_report(
    source: Mapping[str, Any],
    target: Mapping[str, Any] | None,
    *,
    schema: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Full migration report: isolation, counts, keys, relations, JSON, NULLs."""
    source = validate_snapshot(source)
    project_id = str(source["project_id"])
    source_tables = normalized_tables(source)
    target_tables = normalized_tables(target) if target is not None else None
    checks: dict[str, dict[str, Any]] = {}

    # project isolation -----------------------------------------------------
    foreign: list[str] = []
    for row in source_tables["algorithms"]:
        if str(row.get("project_id") or "") != project_id:
            foreign.append(str(row.get("id")))
    target_foreign: list[str] = []
    if target_tables is not None:
        for row in target_tables["algorithms"]:
            if str(row.get("project_id") or "") != project_id:
                target_foreign.append(str(row.get("id")))
    checks["project_isolation"] = _check(
        not foreign and not target_foreign,
        project_id=project_id,
        source_mismatched=foreign,
        target_mismatched=target_foreign,
    )

    # row counts ------------------------------------------------------------
    source_counts = {name: len(source_tables[name]) for name in TABLES}
    target_counts = (
        {name: len(target_tables[name]) for name in TABLES} if target_tables is not None else None
    )
    checks["row_counts"] = _check(
        target_counts is not None and target_counts == source_counts,
        source=source_counts,
        target=target_counts,
    )

    # primary keys ----------------------------------------------------------
    key_report: dict[str, Any] = {}
    key_ok = target_tables is not None
    regenerated_total = 0
    for name in TABLES:
        source_rows = _rows_by_key(name, source_tables[name])
        target_rows = _rows_by_key(name, target_tables[name]) if target_tables is not None else {}
        missing = sorted(set(source_rows) - set(target_rows))
        extra = sorted(set(target_rows) - set(source_rows))
        regenerated: list[dict[str, str]] = []
        if name == "algorithms":
            fingerprint = lambda row: (str(row.get("name") or ""), str(row.get("created_at") or ""))
        elif name == "versions":
            fingerprint = lambda row: (
                str(row.get("algorithm_id") or ""),
                str(row.get("version_name") or ""),
                str(row.get("created_at") or ""),
            )
        else:
            fingerprint = lambda row: (
                str(row.get("algorithm_id") or ""),
                str(row.get("analysis_name") or ""),
            )
        for key in missing:
            wanted = fingerprint(source_rows[key])
            for other_key in extra:
                if fingerprint(target_rows[other_key]) == wanted:
                    regenerated.append({"source_id": key, "target_id": other_key})
        key_report[name] = {
            "source": len(source_rows),
            "target": len(target_rows),
            "missing": missing,
            "extra": extra,
            "regenerated": regenerated,
        }
        regenerated_total += len(regenerated)
        if missing or extra or regenerated:
            key_ok = False
    checks["primary_keys"] = _check(
        key_ok, tables=key_report, ids_regenerated=regenerated_total
    )

    # associations / foreign keys ------------------------------------------
    unknown_versions: list[str] = []
    unknown_analyses: list[str] = []
    dangling_current: list[str] = []
    duplicate_versions: list[str] = []
    duplicate_analyses: list[str] = []
    if target_tables is not None:
        algorithm_ids = {str(row.get("id")) for row in target_tables["algorithms"]}
        version_ids = [str(row.get("id")) for row in target_tables["versions"]]
        duplicate_versions = sorted(
            {value for value in version_ids if version_ids.count(value) > 1}
        )
        for row in target_tables["versions"]:
            if str(row.get("algorithm_id")) not in algorithm_ids:
                unknown_versions.append(str(row.get("id")))
        analysis_keys: list[str] = []
        for row in target_tables["analyses"]:
            key = _natural_key("analyses", row)
            analysis_keys.append(key)
            if str(row.get("algorithm_id")) not in algorithm_ids:
                unknown_analyses.append(key)
        duplicate_analyses = sorted(
            {value for value in analysis_keys if analysis_keys.count(value) > 1}
        )
        by_algorithm: dict[str, set[str]] = {}
        for row in target_tables["versions"]:
            by_algorithm.setdefault(str(row.get("algorithm_id")), set()).add(str(row.get("id")))
        for row in target_tables["algorithms"]:
            current = str(row.get("current_version_id") or "")
            if not current:
                continue
            if current not in by_algorithm.get(str(row.get("id")), set()):
                dangling_current.append(str(row.get("id")))
    checks["associations"] = _check(
        target_tables is not None
        and not (unknown_versions or unknown_analyses or dangling_current
                 or duplicate_versions or duplicate_analyses),
        versions_without_algorithm=sorted(unknown_versions),
        analyses_without_algorithm=sorted(unknown_analyses),
        current_version_missing=sorted(dangling_current),
        duplicate_version_ids=duplicate_versions,
        duplicate_analysis_keys=duplicate_analyses,
    )

    # revision --------------------------------------------------------------
    source_revision = int(source["algorithm_revision"])
    target_revision = int(target["algorithm_revision"]) if target is not None else None
    relation = "missing"
    if target_revision is not None:
        relation = (
            "equal" if target_revision == source_revision
            else ("target_ahead" if target_revision > source_revision else "target_behind")
        )
    checks["revision"] = _check(
        relation == "equal", source=source_revision, target=target_revision, relation=relation
    )

    # JSON fields -----------------------------------------------------------
    invalid_json: list[str] = []
    payload_type_mismatch: list[str] = []
    field_differences: list[str] = []
    if target_tables is not None:
        for name in TABLES:
            source_rows = _rows_by_key(name, source_tables[name])
            target_rows = _rows_by_key(name, target_tables[name])
            for key in set(source_rows) & set(target_rows):
                source_payload = source_rows[key].get("payload_json")
                target_payload = target_rows[key].get("payload_json")
                if isinstance(source_payload, str):
                    invalid_json.append(f"{name}:{key}.payload_json")
                if isinstance(target_payload, str):
                    invalid_json.append(f"{name}:{key}.payload_json(target)")
                if not isinstance(target_payload, dict):
                    payload_type_mismatch.append(f"{name}:{key}.payload_json")
                if isinstance(source_payload, dict) and isinstance(target_payload, dict):
                    missing_fields = sorted(set(source_payload) - set(target_payload))
                    extra_fields = sorted(set(target_payload) - set(source_payload))
                    if missing_fields or extra_fields:
                        field_differences.append(
                            f"{name}:{key} missing={missing_fields} extra={extra_fields}"
                        )
                if name == "analyses":
                    ids = target_rows[key].get("compute_platform_ids_json")
                    if not isinstance(ids, list):
                        payload_type_mismatch.append(f"{name}:{key}.compute_platform_ids_json")
    checks["json_fields"] = _check(
        target_tables is not None
        and not (invalid_json or payload_type_mismatch or field_differences),
        invalid_json=sorted(invalid_json),
        type_mismatch=sorted(payload_type_mismatch),
        field_differences=sorted(field_differences),
    )

    # NULL vs empty semantics ----------------------------------------------
    null_differences: list[str] = []
    source_classes = {"null": 0, "empty_string": 0, "zero": 0, "false": 0}
    target_classes = {"null": 0, "empty_string": 0, "zero": 0, "false": 0}
    if target_tables is not None:
        for name in TABLES:
            source_rows = _rows_by_key(name, source_tables[name])
            target_rows = _rows_by_key(name, target_tables[name])
            for key in set(source_rows) & set(target_rows):
                for column in set(source_rows[key]) & set(target_rows[key]):
                    left = _null_class(source_rows[key][column])
                    right = _null_class(target_rows[key][column])
                    if left in source_classes:
                        source_classes[left] += 1
                    if right in target_classes:
                        target_classes[right] += 1
                    if left != right:
                        null_differences.append(f"{name}:{key}.{column} {left}!={right}")
    checks["null_vs_empty"] = _check(
        target_tables is not None and not null_differences,
        differences=sorted(null_differences)[:50],
        source_counts=source_classes,
        target_counts=target_classes,
    )

    # object references -----------------------------------------------------
    references = {
        name: _object_references(
            name, target_tables[name] if target_tables is not None else source_tables[name]
        )
        for name in TABLES
    }
    non_string = [item for value in references.values() for item in value["non_string"]]
    checks["object_references"] = _check(
        not non_string,
        count=sum(value["count"] for value in references.values()),
        resolved=False,
        non_string=non_string,
        per_table=references,
    )

    # secret material -------------------------------------------------------
    checks["secret_material"] = _check(True, checked=True, findings=[])

    # content digest --------------------------------------------------------
    source_content = content_digest(source)
    target_content = content_digest(target) if target is not None else None
    checks["content_digest"] = _check(
        target is not None and source_content == target_content,
        source=source_content,
        target=target_content,
    )

    blocking = sorted(name for name, value in checks.items() if not value["ok"])
    if target is None:
        verdict = "TARGET_MISSING"
    elif not blocking:
        verdict = "OK"
    else:
        verdict = "MISMATCH"
    report: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "project_id": project_id,
        "schema": dict(schema) if schema is not None else None,
        "source": {
            "revision": source_revision,
            "snapshot_digest": str(source["snapshot_digest"]),
            "content_digest": source_content,
            "counts": source_counts,
            "captured_at": str(source["captured_at"]),
        },
        "target": None if target is None else {
            "revision": target_revision,
            "snapshot_digest": str(target["snapshot_digest"]),
            "content_digest": target_content,
            "counts": target_counts,
            "captured_at": str(target["captured_at"]),
        },
        "checks": checks,
        "blocking_findings": blocking,
        "warnings": [],
        "verdict": verdict,
    }
    report["summary_digest"] = _digest({
        "contract_version": CONTRACT_VERSION,
        "project_id": project_id,
        "source": {
            "revision": source_revision,
            "content_digest": source_content,
        },
        "target": None if target is None else {
            "revision": target_revision,
            "content_digest": target_content,
        },
        "checks": {name: value["ok"] for name, value in checks.items()},
        "verdict": verdict,
    })
    return report


def verify_migration(connection, source: Mapping[str, Any]) -> dict[str, Any]:
    """Fresh target read plus full report; never trusts a previous run."""
    source = validate_snapshot(source)
    target = export_target_snapshot(connection, str(source["project_id"]))
    return build_report(source, target, schema=schema_status(connection))


# ---------------------------------------------------------------------------
# reverse restoration (blocked unless safety evidence exists)
# ---------------------------------------------------------------------------
def restore_source_snapshot(
    db_path: str | Path,
    project_id: str,
    snapshot: Mapping[str, Any],
    *,
    assessment: Mapping[str, Any],
    confirmed: bool,
) -> dict[str, Any]:
    """Restore SQLite from a snapshot only with an allowed rollback assessment."""
    if not confirmed:
        raise AlgorithmMigrationError(
            "ALGORITHM_ROLLBACK_CONFIRMATION_REQUIRED",
            "reverse restoration requires explicit confirmation",
        )
    blocking = list(assessment.get("blocking") or [])
    if not assessment.get("allowed") or blocking:
        raise AlgorithmMigrationError(
            "ALGORITHM_ROLLBACK_BLOCKED",
            "reverse restoration is blocked by missing safety evidence",
            detail=f"blocking={blocking}",
        )
    snapshot = validate_snapshot(snapshot)
    if str(snapshot["project_id"]) != str(project_id):
        raise AlgorithmMigrationError(
            "ALGORITHM_ROLLBACK_PROJECT_MISMATCH",
            "snapshot does not belong to the requested project",
        )
    expected = str(assessment.get("restore_content_digest") or "")
    normalized = normalized_tables(snapshot)
    if expected and content_digest(snapshot) != expected:
        raise AlgorithmMigrationError(
            "ALGORITHM_ROLLBACK_SNAPSHOT_CHANGED",
            "snapshot content no longer matches the assessed rollback evidence",
        )
    database_path = Path(db_path)
    store = AlgorithmSqlStore(database_path.parent / "algorithms.json")
    if store.db_path.resolve() != database_path.resolve():
        raise AlgorithmMigrationError(
            "ALGORITHM_ROLLBACK_DB_PATH_MISMATCH",
            "database path does not match the algorithm store layout",
        )
    store.ensure_ready()
    connection = sqlite3.connect(str(database_path), timeout=30.0, isolation_level=None)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        try:
            connection.execute("DELETE FROM algorithm_external_analyses")
            connection.execute("DELETE FROM algorithm_versions")
            connection.execute("DELETE FROM algorithms")
            _insert_sqlite_rows(connection, "algorithms", normalized["algorithms"])
            _insert_sqlite_rows(connection, "versions", normalized["versions"])
            _insert_sqlite_rows(connection, "analyses", normalized["analyses"])
            connection.execute(
                "INSERT INTO algorithm_store_meta(key,value) VALUES('algorithm_revision',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(int(snapshot["algorithm_revision"])),),
            )
            connection.execute(
                "INSERT INTO algorithm_store_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SQLITE_SCHEMA_VERSION),),
            )
            restored = _read_sqlite_tables(connection, str(project_id))
            restored_snapshot = _snapshot_from_tables(
                str(project_id), int(snapshot["algorithm_revision"]), restored
            )
            actual = content_digest(restored_snapshot)
            if actual != content_digest(snapshot):
                raise AlgorithmMigrationError(
                    "ALGORITHM_ROLLBACK_ROUND_TRIP_MISMATCH",
                    "restored SQLite content does not match the snapshot",
                    detail=f"actual={actual} expected={content_digest(snapshot)}",
                )
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
    finally:
        connection.close()
    return {
        "restored": True,
        "project_id": str(project_id),
        "db_path": str(database_path),
        "revision": int(snapshot["algorithm_revision"]),
        "content_digest": content_digest(snapshot),
        "verified": True,
    }


def _insert_sqlite_rows(connection, name: str, rows: Sequence[Mapping[str, Any]]) -> None:
    if not rows:
        return
    columns = [value.strip() for value in _SQLITE_COLUMNS[name].split(",")]
    placeholders = ",".join("?" for _ in columns)
    statement = (
        f"INSERT INTO {_SQLITE_TABLES[name]} ({_SQLITE_COLUMNS[name]}) "
        f"VALUES ({placeholders})"
    )
    payload = []
    for row in rows:
        values = []
        for column in columns:
            value = row.get(column)
            if column in {"payload_json", "compute_platform_ids_json"}:
                value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            elif column in {"external_active", "master_data_readonly", "artifact_verified",
                            "trainable", "is_default", "active"}:
                value = None if value is None else (1 if bool(value) else 0)
            values.append(value)
        payload.append(tuple(values))
    connection.executemany(statement, payload)


def _read_sqlite_tables(connection, project_id: str) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = {}
    for name in TABLES:
        statement = f"SELECT {_SQLITE_COLUMNS[name]} FROM {_SQLITE_TABLES[name]}"
        if name == "algorithms":
            statement += " WHERE project_id=?"
        else:
            statement += " WHERE algorithm_id IN (SELECT id FROM algorithms WHERE project_id=?)"
        statement += " " + _SQLITE_ORDER[name]
        tables[name] = [dict(row) for row in connection.execute(statement, (project_id,))]
    return tables


def _snapshot_from_tables(
    project_id: str, revision: int, tables: dict[str, list[dict]]
) -> dict[str, Any]:
    normalized = {
        name: [normalize_row(name, row) for row in tables.get(name) or []]
        for name in TABLES
    }
    body = _snapshot_body(str(project_id), int(revision), normalized)
    body["snapshot_digest"] = _digest(body)
    body["captured_at"] = datetime.now(timezone.utc).isoformat()
    return body
