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
from .algorithm_shadow import (
    CONTRACT_VERSION as SNAPSHOT_CONTRACT_V1,
    CONTRACT_VERSION_V2 as SNAPSHOT_CONTRACT_V2,
    SCHEMA_VERSION as SNAPSHOT_SCHEMA_V1,
    SCHEMA_VERSION_V2 as SNAPSHOT_SCHEMA_V2,
    _digest,
    _snapshot_body,
    export_snapshot_from_path,
    validate_snapshot,
)
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


def _normalized_timestamp(value: Any) -> str:
    """One UTC representation for SQLite TEXT and PostgreSQL timestamptz."""
    text = str(value or "").strip()
    if not text:
        return ""
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        # Keep the raw evidence; comparing an unparsable value as-is is safer
        # than silently dropping it.
        return text
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


def _normalized_cleanup_row(row: Mapping[str, Any]) -> dict:
    payload = row.get("payload")
    if payload is None:
        payload = row.get("payload_json")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except ValueError as error:
            raise AlgorithmMigrationError(
                "ALGORITHM_MIGRATION_CLEANUP_PAYLOAD_INVALID",
                "cleanup payload is not valid JSON",
                detail=str(error),
            ) from error
    if not isinstance(payload, dict):
        raise AlgorithmMigrationError(
            "ALGORITHM_MIGRATION_CLEANUP_PAYLOAD_INVALID",
            "cleanup payload is not an object",
            detail=str(row.get("operation_id") or ""),
        )
    return {
        "project_id": str(row.get("project_id") or ""),
        "operation_id": str(row.get("operation_id") or ""),
        "algorithm_id": str(row.get("algorithm_id") or ""),
        "product_id": str(row.get("product_id") or ""),
        "generation": str(row.get("generation") or ""),
        "state": str(row.get("state") or ""),
        "created_at": _normalized_timestamp(row.get("created_at")),
        "updated_at": _normalized_timestamp(row.get("updated_at")),
        "payload": payload if isinstance(payload, dict) else {},
    }


def normalized_tables(snapshot: Mapping[str, Any]) -> dict[str, list[dict]]:
    tables = snapshot.get("tables") or {}
    names = tuple(TABLES) + (("cleanup",) if "cleanup" in tables else ())
    normalized: dict[str, list[dict]] = {}
    for name in names:
        if name == "cleanup":
            normalized[name] = [
                _normalized_cleanup_row(row) for row in tables.get(name) or []
            ]
        else:
            normalized[name] = [
                normalize_row(name, row) for row in tables.get(name) or []
            ]
    return normalized


def normalize_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Return a valid snapshot whose JSON cells compare structurally."""
    tables = normalized_tables(snapshot)
    body = _snapshot_body(
        str(snapshot["project_id"]), int(snapshot["algorithm_revision"]), tables,
        contract_version=str(snapshot.get("contract_version") or SNAPSHOT_CONTRACT_V1),
        schema_version=int(snapshot.get("schema_version") or SNAPSHOT_SCHEMA_V1),
        cleanup_capability=snapshot.get("cleanup_capability"),
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
    if name == "cleanup":
        return str(row.get("operation_id") or "")
    return f"{row.get('algorithm_id')}:{row.get('external_analysis_id')}"


# ---------------------------------------------------------------------------
# source export
# ---------------------------------------------------------------------------
def export_source_snapshot(db_path: str | Path, project_id: str) -> dict[str, Any]:
    snapshot = export_snapshot_from_path(db_path, project_id)
    _scan_secret_material(snapshot)
    return snapshot


def export_source_snapshot_v2(db_path: str | Path, project_id: str) -> dict[str, Any]:
    """Export the four-domain V2 snapshot from one consistent SQLite read.

    The cleanup domain is read in the same transaction; a source without the
    ledger table is recorded as ``cleanup_capability = "ABSENT"``. The V1 export
    above is untouched and remains the one every current caller uses.
    """
    snapshot = export_snapshot_from_path(db_path, project_id, include_cleanup=True)
    _scan_secret_material(snapshot)
    return snapshot


# ---------------------------------------------------------------------------
# import
# ---------------------------------------------------------------------------
def _cutover_state(cursor, project_id: str) -> dict[str, Any]:
    """Read (and row-lock) this project's durable writer state."""
    from psycopg.rows import dict_row

    cursor.execute(
        "SELECT authoritative_provider,writer_generation,revoked_at,evidence "
        "FROM w5_algorithm.cutover_state WHERE project_id=%s FOR UPDATE",
        (str(project_id),),
    )
    row = cursor.fetchone()
    if row is None:
        return {}
    value = dict(row) if isinstance(row, Mapping) else dict(zip(
        ("authoritative_provider", "writer_generation", "revoked_at", "evidence"), row
    ))
    evidence = value.get("evidence")
    value["evidence"] = dict(evidence) if isinstance(evidence, Mapping) else {}
    return value


def _require_import_authority(
    cursor, *, project_id: str, maintenance_operation: str | None
) -> dict[str, Any]:
    """Prove the importer is allowed to write this project's data right now.

    The verdict is a combination of the *actual* durable facts, never of
    ``revoked_at`` alone. A project whose first maintenance window created its
    SQLite authority row carries ``revoked_at = now()`` (nothing has been revoked
    there yet), and a safely rolled-back project is legitimate SQLite authority
    again - so both must accept a window-owned final import. What the final
    import does require is a frozen window, that window's operation, and the
    frozen content it claims to import.

    A plain (shadow) import is a tool operation: it may only write while SQLite
    owns the project and no window owns it, and it is refused entirely once
    PostgreSQL is authoritative.
    """
    from .algorithm_cutover import (
        BLOCKING_MAINTENANCE_PHASES,
        MAINTENANCE_SQLITE_ACTIVE,
        MAINTENANCE_SOURCE_FROZEN,
    )

    state = _cutover_state(cursor, project_id)
    provider = str(state.get("authoritative_provider") or "sqlite")
    evidence = state.get("evidence") or {}
    maintenance = evidence.get("maintenance") if isinstance(evidence, Mapping) else None
    maintenance = dict(maintenance) if isinstance(maintenance, Mapping) else {}
    phase = str(
        maintenance.get("phase") or (evidence.get("phase") if isinstance(evidence, Mapping) else "") or ""
    )
    operation = str(maintenance.get("operation_id") or "")
    generation = int(state.get("writer_generation") or 0)
    if maintenance_operation is not None:
        if provider != "sqlite":
            raise AlgorithmMigrationError(
                "ALGORITHM_MIGRATION_AUTHORITY_INVALID",
                "the final import belongs to a window that no longer owns SQLite",
                detail=f"provider={provider} phase={phase}",
            )
        if phase != MAINTENANCE_SOURCE_FROZEN:
            # QUIESCING/SWITCHING/ROLLBACK_QUIESCING must never import: the
            # source is not frozen yet, or a switch/rollback is in flight.
            raise AlgorithmMigrationError(
                "ALGORITHM_MIGRATION_AUTHORITY_INVALID",
                "the final import requires the frozen window phase",
                detail=f"phase={phase}",
            )
        if operation != str(maintenance_operation):
            raise AlgorithmMigrationError(
                "ALGORITHM_MIGRATION_OPERATION_MISMATCH",
                "the maintenance operation does not own this project",
                detail=f"record={operation} requested={maintenance_operation}",
            )
        frozen_content = str(
            maintenance.get("content_digest") or maintenance.get("snapshot_digest") or ""
        )
        if not frozen_content:
            raise AlgorithmMigrationError(
                "ALGORITHM_MIGRATION_FROZEN_EVIDENCE_MISSING",
                "the window records no frozen content digest",
                detail=f"operation={operation}",
            )
        return {
            "phase": phase, "provider": provider, "generation": generation,
            "maintenance_operation": operation,
            "frozen_content_digest": frozen_content,
            "frozen_revision": maintenance.get("source_revision"),
        }
    if provider == "postgresql":
        # PostgreSQL is authoritative. A revoked (rolled back) admission is only
        # SQLite authority again when the window settled; a stale/unsettled
        # record must not be read as permission.
        if phase not in {MAINTENANCE_SQLITE_ACTIVE, "ROLLBACK_APPLIED"}:
            raise AlgorithmMigrationError(
                "ALGORITHM_MIGRATION_AUTHORITY_REQUIRED",
                "PostgreSQL owns the writer slot; a direct import is refused",
                detail=f"provider={provider} phase={phase}",
            )
    if phase in BLOCKING_MAINTENANCE_PHASES:
        raise AlgorithmMigrationError(
            "ALGORITHM_MIGRATION_WINDOW_ACTIVE",
            "a maintenance window owns this project; name its operation to import",
            detail=f"phase={phase} operation={operation}",
        )
    return {"phase": phase, "provider": provider, "generation": generation,
            "maintenance_operation": ""}


def import_snapshot(
    connection,
    snapshot: Mapping[str, Any],
    *,
    dry_run: bool = False,
    resume: bool = False,
    actor: str = DEFAULT_ACTOR,
    run_id: str | None = None,
    stale_after_seconds: int = DEFAULT_STALE_RUN_SECONDS,
    maintenance_operation: str | None = None,
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
    is_v2 = str(snapshot.get("contract_version") or "") == SNAPSHOT_CONTRACT_V2
    # The three legacy domains are the upgrade comparison basis for V1 -> V2.
    legacy_tables = {
        name: snapshot["tables"][name] for name in TABLES if name in snapshot["tables"]
    }
    legacy_content = (
        content if not is_v2 else _digest({
            "project_id": project_id,
            "algorithm_revision": revision,
            "tables": normalized_tables({"tables": legacy_tables, **{
                key: value for key, value in snapshot.items() if key != "tables"
            }}),
        })
    )
    mode = "DRY_RUN" if dry_run else "APPLY"
    if maintenance_operation is not None:
        # The final import is an APPLY step of one frozen window and one run id:
        # a dry run or an unnamed run must never stand in for it.
        if dry_run:
            raise AlgorithmMigrationError(
                "ALGORITHM_MIGRATION_DRY_RUN_NOT_FINAL",
                "a dry run cannot be the window's final import",
                detail=f"operation={maintenance_operation}",
            )
        # Prove the window ownership *before* registering a run row: an illegal
        # request must not create, abort or otherwise touch the legitimate
        # operation's migration_run history. The same verdict is re-checked
        # inside the data transaction below, so a switch that lands in between
        # still fails.
        require_idle_transaction(connection, purpose="algorithm import authority precheck")
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"algorithm-cutover:{project_id}",),
                )
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (f"algorithm-import:{project_id}",),
                )
                _require_import_authority(
                    cursor,
                    project_id=project_id,
                    maintenance_operation=maintenance_operation,
                )
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
        refuse_running_reopen=maintenance_operation is not None,
    )
    counts = {
        name: len(rows) for name, rows in snapshot["tables"].items()
    }
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
                    # Same lock order as the cutover owner: the project's cutover
                    # mutex first, then the import slot, so an import and a
                    # switch/rollback can never interleave.
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (f"algorithm-cutover:{project_id}",),
                    )
                    cursor.execute(
                        "SELECT pg_advisory_xact_lock(hashtext(%s))",
                        (f"algorithm-import:{project_id}",),
                    )
                    if not dry_run:
                        # The ownership verdict and the data write are one
                        # transaction: a cutover/rollback cannot land between
                        # the check and the rows.
                        authority = _require_import_authority(
                            cursor,
                            project_id=project_id,
                            maintenance_operation=maintenance_operation,
                        )
                        if maintenance_operation is not None:
                            # Ownership is proven above; only then is the run id
                            # bound, so a wrong operation still reports the
                            # established operation-mismatch code.
                            if str(run) != str(maintenance_operation):
                                raise AlgorithmMigrationError(
                                    "ALGORITHM_MIGRATION_RUN_IDENTITY_REQUIRED",
                                    "the final import must run under the window operation id",
                                    detail=f"run_id={run!r} operation={maintenance_operation}",
                                )
                            # The window's frozen evidence must describe exactly
                            # this import: same content, same revision.
                            frozen_content = str(
                                authority.get("frozen_content_digest") or ""
                            )
                            if frozen_content != content:
                                raise AlgorithmMigrationError(
                                    "ALGORITHM_MIGRATION_FROZEN_CONTENT_MISMATCH",
                                    "the import content differs from the frozen window",
                                    detail=f"frozen={frozen_content} import={content}",
                                )
                            frozen_revision = authority.get("frozen_revision")
                            if frozen_revision is not None and int(frozen_revision) != revision:
                                raise AlgorithmMigrationError(
                                    "ALGORITHM_MIGRATION_FROZEN_REVISION_MISMATCH",
                                    "the import revision differs from the frozen window",
                                    detail=f"frozen={frozen_revision} import={revision}",
                                )
                # The target is always exported with its ledger: the safety
                # evidence must not depend on what the source claims to be.
                target = export_target_snapshot(
                    connection, project_id, include_cleanup=True,
                )
                target_revision = (
                    int(target["algorithm_revision"]) if target is not None else None
                )
                result["target_revision_before"] = target_revision
                action = _import_action(
                    target, revision, content,
                    source_is_v2=is_v2, legacy_content=legacy_content,
                    target_legacy_content=(
                        None if target is None else _legacy_content(target)
                    ),
                    target_v2_evidence=_v2_completed_evidence(
                        connection, project_id,
                    ),
                )
                result["action"] = action
                if is_v2 and not dry_run and action == "noop":
                    with connection.cursor() as cursor:
                        _record_v2_completion(
                            cursor, run=run, project_id=project_id,
                            revision=revision, content=content, counts=counts,
                        )
                if action == "apply":
                    if is_v2:
                        _assert_target_receipts_preserved(target, snapshot)
                    with connection.cursor() as cursor:
                        _delete_target_graph(
                            cursor, project_id, include_cleanup=is_v2,
                        )
                        _write_target_rows(cursor, snapshot)
                        if is_v2:
                            _write_target_cleanup_rows(cursor, snapshot)
                            # The V2 completion evidence commits atomically with
                            # the data it describes, so a crash cannot leave
                            # migrated data without the protection marker.
                            _record_v2_completion(
                                cursor, run=run, project_id=project_id,
                                revision=revision, content=content, counts=counts,
                            )
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
        "contract_version": str(snapshot.get("contract_version") or ""),
        "cleanup_rows": int(counts.get("cleanup") or 0),
    })
    return result


def _v2_completed_evidence(connection, project_id: str) -> bool:
    """Whether a COMPLETED APPLY run recorded a V2 (four-domain) migration."""
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT 1 AS present FROM w5_algorithm.migration_run "
            "WHERE project_id=%s AND status='COMPLETED' AND mode='APPLY' "
            "AND detail->>'contract_version'=%s LIMIT 1",
            (str(project_id), SNAPSHOT_CONTRACT_V2),
        )
        return cursor.fetchone() is not None


def _legacy_content(snapshot: Mapping[str, Any]) -> str:
    """Content digest over the three legacy domains only."""
    tables = snapshot.get("tables") or {}
    return _digest({
        "project_id": str(snapshot["project_id"]),
        "algorithm_revision": int(snapshot["algorithm_revision"]),
        "tables": normalized_tables({
            "tables": {name: tables[name] for name in TABLES if name in tables},
        }),
    })


def _record_v2_completion(
    cursor, *, run: str, project_id: str, revision: int, content: str,
    counts: Mapping[str, int],
) -> None:
    """Write the V2 completion evidence inside the data transaction."""
    cursor.execute(
        "UPDATE w5_algorithm.migration_run SET status='COMPLETED',"
        "finished_at=now(),heartbeat_at=now(),"
        "detail=COALESCE(detail,'{}'::jsonb) || %s::jsonb "
        "WHERE run_id=%s AND project_id=%s",
        (
            json.dumps({
                "contract_version": SNAPSHOT_CONTRACT_V2,
                "cleanup_rows": int(counts.get("cleanup") or 0),
                "algorithm_revision": int(revision),
                "content_digest": str(content),
                "action": "apply",
            }, ensure_ascii=False),
            str(run), str(project_id),
        ),
    )


def _assert_target_receipts_preserved(
    target: Mapping[str, Any] | None, snapshot: Mapping[str, Any],
) -> None:
    """Refuse to rebuild a ledger when a completed target receipt would be lost."""
    target_rows = {
        str(row.get("operation_id")): row
        for row in ((target or {}).get("tables") or {}).get("cleanup") or []
        if str(row.get("state") or "") == "CLEANUP_COMPLETED"
    }
    if not target_rows:
        return
    source_rows = {
        str(row.get("operation_id")): row
        for row in snapshot["tables"].get("cleanup") or []
        if str(row.get("state") or "") == "CLEANUP_COMPLETED"
    }
    missing = sorted(set(target_rows) - set(source_rows))
    if missing:
        raise AlgorithmMigrationError(
            "ALGORITHM_MIGRATION_TARGET_RECEIPT_LOST",
            "the snapshot would drop a completed cleanup receipt",
            detail=f"operation_ids={missing[:10]}",
        )
    for operation_id, row in target_rows.items():
        if _normalized_cleanup_row(source_rows[operation_id]) != _normalized_cleanup_row(row):
            raise AlgorithmMigrationError(
                "ALGORITHM_MIGRATION_TARGET_RECEIPT_CONFLICT",
                "the snapshot rewrites a completed cleanup receipt",
                detail=f"operation_id={operation_id}",
            )


def _import_action(
    target: Mapping[str, Any] | None,
    revision: int,
    content: str,
    *,
    source_is_v2: bool = False,
    legacy_content: str | None = None,
    target_legacy_content: str | None = None,
    target_v2_evidence: bool = False,
) -> str:
    if target is None:
        return "apply"
    target_revision = int(target["algorithm_revision"])
    if target_revision > revision:
        raise AlgorithmMigrationError(
            "ALGORITHM_MIGRATION_REVISION_REGRESSION",
            "target already holds newer algorithm writes",
            detail=f"target={target_revision} source={revision}",
        )
    target_rows = (target.get("tables") or {}).get("cleanup") or []
    if not source_is_v2 and (target_rows or target_v2_evidence):
        # A V1 document carries no cleanup evidence: it can never replace a
        # target that already owns receipts or completed V2 migration evidence.
        raise AlgorithmMigrationError(
            "ALGORITHM_MIGRATION_V1_CANNOT_OVERWRITE_V2",
            "a V1 snapshot cannot overwrite a V2 project",
            detail=(
                f"target_cleanup_rows={len(target_rows)} "
                f"v2_evidence={target_v2_evidence}"
            ),
        )
    if target_revision == revision:
        if source_is_v2:
            if content_digest(target) == content:
                return "noop"
            # V1 -> V2 upgrade: identical three-domain content, no receipts and
            # no prior V2 evidence; the fourth domain then comes from the source.
            if (
                legacy_content is not None
                and target_legacy_content is not None
                and not target_rows
                and not target_v2_evidence
                and legacy_content == target_legacy_content
            ):
                return "apply"
        elif target_legacy_content is not None and target_legacy_content == content:
            return "noop"
        raise AlgorithmMigrationError(
            "ALGORITHM_MIGRATION_DIGEST_CONFLICT",
            "same algorithm revision has different content",
            detail="refusing to overwrite a divergent target at the same revision",
        )
    return "apply"


def _delete_target_graph(cursor, project_id: str, *, include_cleanup: bool = False) -> None:
    if include_cleanup:
        cursor.execute(
            "DELETE FROM w5_algorithm.external_algorithm_cleanup WHERE project_id=%s",
            (project_id,),
        )
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


def _write_target_cleanup_rows(cursor, snapshot: Mapping[str, Any]) -> None:
    rows = snapshot["tables"].get("cleanup") or []
    if not rows:
        return
    project_id = str(snapshot["project_id"])
    cursor.executemany(
        "INSERT INTO w5_algorithm.external_algorithm_cleanup (project_id,operation_id,"
        "algorithm_id,product_id,generation,state,payload,created_at,updated_at) "
        "VALUES (%s,%s,%s,%s,%s,%s,%s::jsonb,%s::timestamptz,%s::timestamptz)",
        [
            (
                project_id, str(row["operation_id"]), str(row["algorithm_id"]),
                str(row["product_id"]), str(row.get("generation") or ""),
                str(row["state"]), json.dumps(
                    _normalized_cleanup_row(row)["payload"], ensure_ascii=False,
                    sort_keys=True,
                ),
                _normalized_timestamp(row.get("created_at")),
                _normalized_timestamp(row.get("updated_at")),
            )
            for row in rows
        ],
    )


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
    refuse_running_reopen: bool = False,
) -> tuple[str, bool]:
    from psycopg.rows import dict_row

    run = str(run_id or f"run-{uuid.uuid4().hex}")
    resumed = False
    require_idle_transaction(connection, purpose="algorithm import run")
    with connection.transaction():
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"algorithm-cutover:{project_id}",),
            )
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
                    if refuse_running_reopen:
                        # A window-owned import proves nothing from a heartbeat
                        # age: reopening it could run beside a live executor.
                        raise AlgorithmMigrationError(
                            "ALGORITHM_MIGRATION_RUN_IN_PROGRESS",
                            "the window import is still recorded as running",
                            detail=f"run_id={run}",
                        )
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
                # A stale heartbeat is evidence, not proof that the old executor
                # stopped. A run owned by a recorded maintenance window is never
                # taken over implicitly: that window's own recovery must resolve
                # its identity first.
                window = _cutover_state(cursor, project_id)
                evidence = window.get("evidence") or {}
                maintenance = evidence.get("maintenance") if isinstance(evidence, Mapping) else None
                maintenance = dict(maintenance) if isinstance(maintenance, Mapping) else {}
                if (
                    str(maintenance.get("operation_id") or "")
                    and str(maintenance.get("operation_id")) == str(active["run_id"])
                    and str(maintenance.get("phase") or "")
                ):
                    raise AlgorithmMigrationError(
                        "ALGORITHM_MIGRATION_RUN_IN_PROGRESS",
                        "the maintenance window's final import still owns this project",
                        detail=(
                            f"operation={maintenance.get('operation_id')} "
                            f"phase={maintenance.get('phase')}"
                        ),
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
                    "UPDATE w5_algorithm.migration_run SET "
                    "status=CASE WHEN status='COMPLETED' AND %s<>'COMPLETED' "
                    "THEN 'COMPLETED' ELSE %s END,finished_at=now(),heartbeat_at=now(),"
                    "detail=COALESCE(detail,'{}'::jsonb) || %s::jsonb WHERE run_id=%s",
                    (
                        status, status,
                        json.dumps(dict(detail), ensure_ascii=False), str(run_id),
                    ),
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
    tables = snapshot.get("tables") or {}
    names = tuple(TABLES) + (("cleanup",) if "cleanup" in tables else ())
    for name in names:
        for row in tables.get(name) or []:
            key = f"{name}:{_natural_key(str(name), row)}"
            payload = _json_value("payload_json", row.get("payload_json"))
            if isinstance(payload, (Mapping, list)):
                _walk_secrets(payload, key, findings)
            # A normalized payload (dict) must not bypass the scan just because
            # its JSON text representation is absent.
            structured = row.get("payload")
            if isinstance(structured, (Mapping, list)):
                _walk_secrets(structured, key, findings)
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
    target_v2_evidence: bool = False,
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
    table_names = list(TABLES)
    source_has_cleanup = "cleanup" in source_tables
    target_has_cleanup = target_tables is not None and "cleanup" in target_tables
    if source_has_cleanup:
        table_names.append("cleanup")
    if True:
        checks["snapshot_contract"] = _check(
            target is not None
            and str(source.get("contract_version")) == str(target.get("contract_version"))
            and (
                str(source.get("cleanup_capability") or "")
                == str((target or {}).get("cleanup_capability") or "")
                or (
                    not (source_tables.get("cleanup") or [])
                    and not ((target_tables or {}).get("cleanup") or [])
                )
            ),
            source=str(source.get("contract_version")),
            target=None if target is None else str(target.get("contract_version")),
            source_capability=source.get("cleanup_capability"),
            target_capability=None if target is None else target.get("cleanup_capability"),
        )
        # A V1 document cannot prove anything about a project that owns the
        # fourth domain, and a V2 document cannot be verified against a target
        # that never captured it. The target's real migration capability comes
        # from its persisted evidence (rows / completed V2 run), never from a
        # table or field merely existing.
        checks["capability_evidence"] = _check(
            (not source_has_cleanup and not target_v2_evidence)
            or (source_has_cleanup and target_has_cleanup),
            source_contract=str(source.get("contract_version")),
            target_contract=None if target is None else str(target.get("contract_version")),
            source_has_cleanup=source_has_cleanup,
            target_has_cleanup=target_has_cleanup,
            target_v2_evidence=target_v2_evidence,
        )
    source_counts = {name: len(source_tables.get(name) or []) for name in table_names}
    target_counts = (
        {name: len(target_tables.get(name) or []) for name in table_names}
        if target_tables is not None else None
    )
    if source_has_cleanup and target_has_cleanup:
        source_ledger = {_natural_key("cleanup", row): row for row in source_tables["cleanup"]}
        target_ledger = (
            {_natural_key("cleanup", row): row for row in target_tables["cleanup"]}
            if target_tables is not None and "cleanup" in target_tables else None
        )
        duplicate = len(source_ledger) != len(source_tables["cleanup"])
        checks["cleanup_ledger"] = _check(
            not duplicate
            and target_ledger == source_ledger
            and all(
                str(row.get("project_id") or "") == project_id
                for row in source_tables["cleanup"]
            ),
            duplicate_natural_keys=duplicate,
            source_rows=len(source_tables["cleanup"]),
            target_rows=None if target_ledger is None else len(target_ledger),
            operations=sorted(source_ledger),
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
    secret_findings: list[str] = []
    for side in (source, target):
        if side is None:
            continue
        try:
            _scan_secret_material(side)
        except AlgorithmMigrationError as error:
            secret_findings.append(f"{error.code}:{error.detail}")
    checks["secret_material"] = _check(
        not secret_findings, checked=True, findings=secret_findings,
    )

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
    """Fresh four-domain comparison of a snapshot against the live target.

    The target is always re-read from the database (never the import request),
    and it is exported with its ledger so a V2 source is compared as V2.
    """
    snapshot = validate_snapshot(source)
    project_id = str(snapshot["project_id"])
    # Always include the ledger: a V1 document must not report a clean verdict
    # over a project that already holds V2 data.
    target = export_target_snapshot(connection, project_id, include_cleanup=True)
    target_rows = (target or {}).get("tables", {}).get("cleanup") or []
    return build_report(
        snapshot, target, schema=schema_status(connection),
        target_v2_evidence=bool(target_rows) or _v2_completed_evidence(
            connection, project_id,
        ),
    )

def restore_source_snapshot(
    db_path: str | Path,
    project_id: str,
    snapshot: Mapping[str, Any],
    *,
    assessment: Mapping[str, Any],
    confirmed: bool,
) -> dict[str, Any]:
    """Restore SQLite from a snapshot only with an allowed rollback assessment."""
    is_v2 = str(snapshot.get("contract_version") or "") == SNAPSHOT_CONTRACT_V2
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
            if not is_v2:
                _assert_v1_restore_allowed(connection)
            connection.execute("DELETE FROM algorithm_external_analyses")
            connection.execute("DELETE FROM algorithm_versions")
            connection.execute("DELETE FROM algorithms")
            if is_v2:
                # The ledger table may legitimately not exist yet (a V1 project
                # being restored from a V2 snapshot); create it with single
                # statements - executescript would implicitly commit the open
                # restore transaction.
                for statement in _cleanup_ddl_statements():
                    connection.execute(statement)
                connection.execute("DELETE FROM external_algorithm_cleanup")
            _insert_sqlite_rows(connection, "algorithms", normalized["algorithms"])
            _insert_sqlite_rows(connection, "versions", normalized["versions"])
            _insert_sqlite_rows(connection, "analyses", normalized["analyses"])
            if is_v2:
                _insert_sqlite_cleanup_rows(connection, snapshot["tables"]["cleanup"])
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
            restored = _read_sqlite_tables(
                connection, str(project_id), include_cleanup=is_v2,
            )
            restored_snapshot = _snapshot_from_tables(
                str(project_id), int(snapshot["algorithm_revision"]), restored,
                contract_version=SNAPSHOT_CONTRACT_V2 if is_v2 else CONTRACT_VERSION,
                schema_version=SNAPSHOT_SCHEMA_V2 if is_v2 else SCHEMA_VERSION,
                cleanup_capability=(
                    str(snapshot.get("cleanup_capability") or "PRESENT")
                    if is_v2 else None
                ),
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


def _cleanup_ddl_statements() -> tuple[str, ...]:
    """The cleanup ledger DDL as individual statements (no executescript)."""
    from .algorithm_sql_store import CLEANUP_SCHEMA

    return tuple(
        part.strip() for part in CLEANUP_SCHEMA.split(";") if part.strip()
    )


def _assert_v1_restore_allowed(connection) -> None:
    """A three-domain restore must not erase a project's cleanup evidence."""
    present = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        ("external_algorithm_cleanup",),
    ).fetchone()
    if present is not None:
        rows = int(connection.execute(
            "SELECT COUNT(*) FROM external_algorithm_cleanup"
        ).fetchone()[0])
        if rows:
            raise AlgorithmMigrationError(
                "ALGORITHM_ROLLBACK_V1_CANNOT_OVERWRITE_V2",
                "a V1 snapshot cannot overwrite an existing cleanup ledger",
                detail=f"cleanup_rows={rows}",
            )
    pending = int(connection.execute(
        "SELECT COUNT(*) FROM algorithms WHERE "
        "json_extract(payload_json,'$.external_delete_pending') IN (1,'true')"
    ).fetchone()[0])
    if pending:
        raise AlgorithmMigrationError(
            "ALGORITHM_ROLLBACK_V1_CANNOT_OVERWRITE_V2",
            "a V1 snapshot cannot overwrite a pending external retirement",
            detail=f"pending_algorithms={pending}",
        )


def _insert_sqlite_cleanup_rows(connection, rows: Sequence[Mapping[str, Any]]) -> None:
    for statement in _cleanup_ddl_statements():
        connection.execute(statement)
    for row in rows or []:
        payload = _normalized_cleanup_row(row)["payload"]
        connection.execute(
            "INSERT INTO external_algorithm_cleanup (operation_id,algorithm_id,"
            "product_id,state,payload_json,created_at,updated_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (
                str(row["operation_id"]), str(row["algorithm_id"]),
                str(row["product_id"]), str(row["state"]),
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                _normalized_timestamp(row.get("created_at")),
                _normalized_timestamp(row.get("updated_at")),
            ),
        )


def _read_sqlite_tables(
    connection, project_id: str, *, include_cleanup: bool = False,
) -> dict[str, list[dict]]:
    tables: dict[str, list[dict]] = {}
    if include_cleanup:
        present = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            ("external_algorithm_cleanup",),
        ).fetchone()
        tables["cleanup"] = []
        if present is not None:
            for row in connection.execute(
                "SELECT operation_id,algorithm_id,product_id,state,payload_json,"
                "created_at,updated_at FROM external_algorithm_cleanup "
                "ORDER BY created_at,operation_id"
            ):
                value = dict(row)
                try:
                    payload = json.loads(str(value.get("payload_json") or "{}"))
                except ValueError as error:
                    raise AlgorithmMigrationError(
                        "ALGORITHM_ROLLBACK_RESTORE_LEDGER_INVALID",
                        "restored cleanup payload is not valid JSON",
                        detail=str(error),
                    ) from error
                if not isinstance(payload, Mapping):
                    raise AlgorithmMigrationError(
                        "ALGORITHM_ROLLBACK_RESTORE_LEDGER_INVALID",
                        "restored cleanup payload is not an object",
                        detail=str(value.get("operation_id") or ""),
                    )
                generation = str(payload.get("generation") or "").strip()
                if not generation:
                    raise AlgorithmMigrationError(
                        "ALGORITHM_ROLLBACK_RESTORE_LEDGER_INVALID",
                        "restored cleanup payload carries no generation",
                        detail=str(value.get("operation_id") or ""),
                    )
                value["project_id"] = str(project_id)
                value["generation"] = generation
                tables["cleanup"].append(value)
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
    project_id: str, revision: int, tables: dict[str, list[dict]],
    *, contract_version: str = SNAPSHOT_CONTRACT_V1,
    schema_version: int = SNAPSHOT_SCHEMA_V1,
    cleanup_capability: str | None = None,
) -> dict[str, Any]:
    names = tuple(TABLES) + (("cleanup",) if "cleanup" in tables else ())
    normalized: dict[str, list[dict]] = {}
    for name in names:
        if name == "cleanup":
            normalized[name] = [
                _normalized_cleanup_row(row) for row in tables.get(name) or []
            ]
        else:
            normalized[name] = [
                normalize_row(name, row) for row in tables.get(name) or []
            ]
    body = _snapshot_body(
        str(project_id), int(revision), normalized,
        contract_version=contract_version, schema_version=schema_version,
        cleanup_capability=cleanup_capability,
    )
    body["snapshot_digest"] = _digest(body)
    body["captured_at"] = datetime.now(timezone.utc).isoformat()
    return body
