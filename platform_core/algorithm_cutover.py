"""Isolated algorithm-domain cutover: admission gates and rollback evidence (T8.3).

Admission is deliberately narrow and auditable:

* a clean, freshly recomputed migration report (ids, counts, associations,
  revision, JSON, NULL/empty, content digest) is required;
* the PostgreSQL schema must be at the explicit target version;
* no import may be running for the project;
* the caller must present the current writer generation, so two operators can
  never admit two authoritative writers;
* the operator and the reason are recorded, and the declared provider
  capability gap must be acknowledged explicitly;
* the local admission record is only written after the database state commits.

Reverse restoration (PostgreSQL -> SQLite) is blocked unless the database can
prove both "no writes since admission" and "the SQLite copy still equals the
admitted content".
"""
from __future__ import annotations

import json
import os
import sqlite3
import tempfile
import uuid
from contextlib import contextmanager, closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .algorithm_migration import (
    build_report,
    content_digest,
    export_source_snapshot,
    restore_source_snapshot,
    run_status,
)
from .algorithm_postgres_schema import (
    require_current_schema,
    require_idle_transaction,
    schema_status,
)
from .algorithm_postgres_store import UNSUPPORTED_OPERATIONS, export_target_snapshot
from .algorithm_repository import (
    CONTRACT_VERSION,
    PROVIDER_POSTGRESQL,
    PROVIDER_SQLITE,
    admission_switch_lock,
    admission_transition_path,
    load_admission_record,
)
from .algorithm_shadow import validate_snapshot


class AlgorithmCutoverError(RuntimeError):
    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


class AlgorithmCutoverRefused(AlgorithmCutoverError):
    """A policy refusal (stale request, window already open, gate not met).

    It is still a cutover error for callers, but the CLI reports it with the
    documented "refused by policy" exit code (3) instead of the generic error
    code (1): an operator asked for something the safety contract declines, and
    nothing was written.
    """


def _condition(code: str, ok: bool, detail: str = "") -> dict[str, Any]:
    return {"code": code, "ok": bool(ok), "detail": str(detail or "")}


def _state_row(connection, project_id: str, *, for_update: bool = False) -> dict | None:
    from psycopg.rows import dict_row

    statement = (
        "SELECT project_id,authoritative_provider,algorithm_revision,snapshot_digest,"
        "content_digest,writer_generation,admission_id,admitted_at,revoked_at,evidence "
        "FROM w5_algorithm.cutover_state WHERE project_id=%s"
    )
    if for_update:
        statement += " FOR UPDATE"
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(statement, (str(project_id),))
        row = cursor.fetchone()
    if row is None:
        return None
    value = dict(row)
    for key in ("admitted_at", "revoked_at"):
        value[key] = None if value.get(key) is None else str(value[key])
    return value


def cutover_status(connection, project_id: str) -> dict[str, Any]:
    """Current authoritative provider, generation and migration runs."""
    state = _state_row(connection, project_id)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT algorithm_revision FROM w5_algorithm.store_revision WHERE project_id=%s",
            (str(project_id),),
        )
        row = cursor.fetchone()
    target_revision = int(row[0]) if row else 0
    runs = run_status(connection, project_id)
    active = [item for item in runs["runs"] if item["status"] == "RUNNING"]
    return {
        "project_id": str(project_id),
        "authoritative_provider": (
            str(state["authoritative_provider"]) if state else PROVIDER_SQLITE
        ),
        "writer_generation": int(state["writer_generation"]) if state else 0,
        "admission_id": state["admission_id"] if state else None,
        "admitted_at": state["admitted_at"] if state else None,
        "revoked_at": state["revoked_at"] if state else None,
        "admitted_revision": int(state["algorithm_revision"]) if state else None,
        "admitted_content_digest": state["content_digest"] if state else None,
        "target_revision": target_revision,
        "active_runs": active,
        "schema": schema_status(connection),
        "declared_unported_operations": list(UNSUPPORTED_OPERATIONS),
    }


def _report_summary(report: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "verdict": report.get("verdict"),
        "summary_digest": report.get("summary_digest"),
        "blocking_findings": list(report.get("blocking_findings") or []),
        "source_revision": (report.get("source") or {}).get("revision"),
        "target_revision": (report.get("target") or {}).get("revision"),
        "source_content_digest": (report.get("source") or {}).get("content_digest"),
        "target_content_digest": (report.get("target") or {}).get("content_digest"),
    }


def _cleanup_domain_pending(db_path: str | Path) -> tuple[bool, str]:
    """Whether this project still owns cleanup state that PostgreSQL cannot hold.

    The cleanup ledger and the algorithm retirement flags share one transaction
    and are not part of the migrated schema. Admitting such a project would leave
    its receipts (and any pending retirement) behind in a copy that may no longer
    be written: the domain is therefore a hard admission gate that cannot be
    waived by acknowledging the presentation gap.
    """
    path = Path(db_path)
    if not path.is_file():
        return False, ""
    try:
        with closing(
            sqlite3.connect(str(path), timeout=1.0)
        ) as connection:
            tables = {
                str(row[0])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            pending = 0
            if "external_algorithm_cleanup" in tables:
                pending = int(connection.execute(
                    "SELECT COUNT(*) FROM external_algorithm_cleanup"
                ).fetchone()[0])
            if pending:
                return True, (
                    f"cleanup_receipts={pending}; the external algorithm cleanup "
                    "domain is not migrated to PostgreSQL"
                )
            flagged = 0
            if "algorithms" in tables:
                flagged = int(connection.execute(
                    "SELECT COUNT(*) FROM algorithms WHERE project_id=? AND "
                    "json_extract(payload_json,'$.external_delete_pending') IN (1,'true')",
                    (path.parent.name,),
                ).fetchone()[0])
            if flagged:
                return True, (
                    f"algorithms_pending_delete={flagged}; the external algorithm "
                    "cleanup domain is not migrated to PostgreSQL"
                )
    except sqlite3.Error as error:
        return True, f"cleanup state cannot be read: {type(error).__name__}: {error}"
    return False, ""


def evaluate_admission(
    connection,
    *,
    db_path: str | Path,
    project_id: str,
    expected_generation: int,
    operator: str,
    reason: str,
    acknowledge_unported: bool = False,
    maintenance: Mapping[str, Any] | None = None,
    previous_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Recompute every admission condition; never trusts an earlier report."""
    require_current_schema(connection)
    schema = schema_status(connection)
    source = export_source_snapshot(db_path, project_id)
    target = export_target_snapshot(connection, project_id)
    report = build_report(source, target, schema=schema)
    state = _state_row(connection, project_id)
    current_generation = int(state["writer_generation"]) if state else 0
    current_provider = str(state["authoritative_provider"]) if state else PROVIDER_SQLITE
    conditions = [
        _condition(
            "MIGRATION_REPORT_CLEAN",
            report["verdict"] == "OK",
            detail=f"verdict={report['verdict']} blocking={report['blocking_findings']}",
        ),
        _condition(
            "SCHEMA_AT_TARGET_VERSION",
            bool(schema["up_to_date"]),
            detail=f"version={schema['version']} target={schema['target_version']}",
        ),
        _condition(
            "NO_IMPORT_RUNNING",
            not any(
                item["status"] == "RUNNING"
                for item in run_status(connection, project_id)["runs"]
            ),
            detail="an import holds the project writer slot",
        ),
        _condition(
            "TARGET_CONTENT_MATCHES_SOURCE",
            bool(report["checks"]["content_digest"]["ok"]),
            detail=str(report["checks"]["content_digest"]),
        ),
        _condition(
            "WRITER_GENERATION_MATCHES",
            current_generation == int(expected_generation),
            detail=f"database={current_generation} expected={int(expected_generation)}",
        ),
        _condition(
            "SINGLE_AUTHORITATIVE_WRITER",
            current_provider == PROVIDER_SQLITE,
            detail=(
                f"provider={current_provider}; PostgreSQL is already authoritative"
                if current_provider == PROVIDER_POSTGRESQL else ""
            ),
        ),
        _condition(
            "OPERATOR_AND_REASON_RECORDED",
            bool(str(operator or "").strip()) and bool(str(reason or "").strip()),
            detail="operator and reason are required for the audit trail",
        ),
        _condition(
            "UNPORTED_OPERATIONS_ACKNOWLEDGED",
            acknowledge_unported or not UNSUPPORTED_OPERATIONS,
            detail=f"unported={list(UNSUPPORTED_OPERATIONS)}",
        ),
    ]
    cleanup_pending, cleanup_detail = _cleanup_domain_pending(db_path)
    conditions.append(_condition(
        "CLEANUP_DOMAIN_MIGRATED",
        not cleanup_pending,
        detail=cleanup_detail,
    ))
    if previous_report is not None:
        conditions.append(_condition(
            "REPORT_NOT_STALE",
            str(previous_report.get("summary_digest") or "")
            == str(report["summary_digest"])
            and str(previous_report.get("project_id") or "") == str(project_id),
            detail="supplied report no longer matches freshly recomputed evidence",
        ))
    blocking = [item["code"] for item in conditions if not item["ok"]]
    return {
        "admitted": not blocking,
        "blocking": blocking,
        "conditions": conditions,
        "report": report,
        "report_summary": _report_summary(report),
        "current_generation": current_generation,
        "current_provider": current_provider,
    }


def admit_cutover(
    connection,
    *,
    db_path: str | Path,
    project_id: str,
    expected_generation: int,
    operator: str,
    reason: str,
    acknowledge_unported: bool = False,
    previous_report: Mapping[str, Any] | None = None,
    maintenance: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Atomically flip the project to PostgreSQL when every gate passes."""
    from psycopg.rows import dict_row

    project_id = str(project_id)
    if maintenance is None:
        # The legacy entry point must not bypass the maintenance contract: an
        # open window (or a settled one written by it) owns the switch.
        window = read_maintenance(connection, project_id)
        if window is not None:
            raise AlgorithmCutoverRefused(
                "ALGORITHM_MAINTENANCE_CONTRACT_REQUIRED",
                "this project has a recorded maintenance window; use the "
                "maintenance switch instead of the legacy admission",
                detail=f"phase={window.get('phase')} operation={window.get('operation_id')}",
            )
    attempt_generation = int(expected_generation) + 1
    maintenance_record = dict(maintenance) if maintenance else {}
    legacy_authority = not maintenance_record
    evaluation = evaluate_admission(
        connection,
        db_path=db_path,
        project_id=project_id,
        expected_generation=expected_generation,
        operator=operator,
        reason=reason,
        acknowledge_unported=acknowledge_unported,
        maintenance=maintenance,
        previous_report=previous_report,
    )
    if not evaluation["admitted"]:
        return {
            "admitted": False,
            "blocking": evaluation["blocking"],
            "conditions": evaluation["conditions"],
            "report_summary": evaluation["report_summary"],
            "report": evaluation["report"],
        }
    report = evaluation["report"]
    admission_id = f"admit-{uuid.uuid4().hex}"
    evidence = {
        "operator": str(operator).strip(),
        "reason": str(reason).strip(),
        "report_summary_digest": report["summary_digest"],
        "report_verdict": report["verdict"],
        "conditions": evaluation["conditions"],
        "unported_operations": list(UNSUPPORTED_OPERATIONS),
        "schema_version": (report.get("schema") or {}).get("target_version"),
        "source_db_path": str(db_path),
    }
    # The legacy admission (used by tools and tests) must not become a second
    # authority path that switches PostgreSQL without the persistent local
    # barrier: the same blocking evidence is written before the commit.
    if legacy_authority:
        _authority_barrier(
            db_path, project_id=project_id, phase=MAINTENANCE_SWITCHING,
            # The target generation is not committed yet.
            writer_generation=int(expected_generation),
        )
    require_idle_transaction(connection, purpose="cutover admission")
    with connection.transaction():
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"algorithm-cutover:{project_id}",),
            )
            cursor.execute(
                "SELECT writer_generation,authoritative_provider FROM "
                "w5_algorithm.cutover_state WHERE project_id=%s FOR UPDATE",
                (project_id,),
            )
            locked = cursor.fetchone()
            locked_generation = int(locked["writer_generation"]) if locked else 0
            if locked_generation != int(expected_generation):
                raise AlgorithmCutoverError(
                    "ALGORITHM_CUTOVER_WRITER_GENERATION_CONFLICT",
                    "another cutover changed the writer generation",
                    detail=f"database={locked_generation} expected={int(expected_generation)}",
                )
            # Revalidate the target inside the admission transaction: a write
            # that landed after the report was computed must not be admitted.
            with connection.cursor() as interior:
                interior.execute(
                    "SELECT algorithm_revision FROM w5_algorithm.store_revision "
                    "WHERE project_id=%s",
                    (project_id,),
                )
                revision_row = interior.fetchone()
            locked_revision = int(revision_row[0]) if revision_row else 0
            fresh_target = export_target_snapshot(connection, project_id)
            if (
                locked_revision != int(report["source"]["revision"])
                or fresh_target is None
                or content_digest(fresh_target) != str(report["source"]["content_digest"])
            ):
                raise AlgorithmCutoverError(
                    "ALGORITHM_CUTOVER_TARGET_CHANGED",
                    "target content changed between verification and admission",
                    detail=(
                        f"locked_revision={locked_revision} "
                        f"report_revision={report['source']['revision']}"
                    ),
                )
            cursor.execute(
                "INSERT INTO w5_algorithm.cutover_state (project_id,authoritative_provider,"
                "algorithm_revision,snapshot_digest,content_digest,writer_generation,admission_id,"
                "admitted_at,revoked_at,evidence) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,now(),NULL,%s::jsonb) "
                "ON CONFLICT(project_id) DO UPDATE SET "
                "authoritative_provider=EXCLUDED.authoritative_provider,"
                "algorithm_revision=EXCLUDED.algorithm_revision,"
                "snapshot_digest=EXCLUDED.snapshot_digest,"
                "content_digest=EXCLUDED.content_digest,"
                "writer_generation=EXCLUDED.writer_generation,"
                "admission_id=EXCLUDED.admission_id,admitted_at=now(),revoked_at=NULL,"
                "evidence=CASE WHEN w5_algorithm.cutover_state.evidence ? 'maintenance' "
                "AND NOT (EXCLUDED.evidence ? 'maintenance') "
                "THEN w5_algorithm.cutover_state.evidence || EXCLUDED.evidence "
                "ELSE EXCLUDED.evidence END",
                (
                    project_id, PROVIDER_POSTGRESQL,
                    int(report["source"]["revision"]),
                    str(report["source"]["snapshot_digest"]),
                    str(report["source"]["content_digest"]),
                    int(expected_generation) + 1, admission_id,
                    json.dumps(
                        {
                            **evidence,
                            "phase": str(
                                maintenance_record.get("phase") or "steady"
                            ),
                            **({"maintenance": maintenance_record} if maintenance_record else {}),
                        },
                        ensure_ascii=False,
                    ),
                ),
            )
    # A SQLite writer cannot be locked from PostgreSQL.  If the source moved
    # while we were admitting, fail closed by immediately giving authority back
    # to SQLite instead of leaving two possible writers.
    try:
        post_source = export_source_snapshot(db_path, project_id)
        source_moved = (
            content_digest(post_source) != str(report["source"]["content_digest"])
        )
    except Exception:
        source_moved = True
    if source_moved:
        _emergency_revoke(
            connection, project_id, admission_id,
            reason="source SQLite content changed during cutover admission",
        )
        if legacy_authority:
            try:
                _authority_barrier(
                    db_path, project_id=project_id, phase=MAINTENANCE_SQLITE_ACTIVE,
                    writer_generation=attempt_generation,
                    require_phase=MAINTENANCE_SWITCHING,
                )
            except Exception:  # noqa: BLE001 - the barrier stays blocking if unprovable
                pass
        raise AlgorithmCutoverError(
            "ALGORITHM_CUTOVER_SOURCE_CHANGED_AFTER_ADMIT",
            "source changed during admission; authority was returned to SQLite",
            detail=f"admission_id={admission_id}",
        )
    admission = {
        "contract_version": CONTRACT_VERSION,
        "admission_id": admission_id,
        "project_id": project_id,
        "authoritative_provider": PROVIDER_POSTGRESQL,
        "algorithm_revision": int(report["source"]["revision"]),
        "snapshot_digest": str(report["source"]["snapshot_digest"]),
        "content_digest": str(report["source"]["content_digest"]),
        "writer_generation": int(expected_generation) + 1,
        "admitted_at": datetime.now(timezone.utc).isoformat(),
        "operator": str(operator).strip(),
        "reason": str(reason).strip(),
        "summary_digest": report["summary_digest"],
        "schema_version": (report.get("schema") or {}).get("target_version"),
        "capabilities": ["ensure_ready", "revision", "read_all", "read_one", "write"],
        "unported_operations": list(UNSUPPORTED_OPERATIONS),
    }
    # The authority really moved: settle the barrier the legacy path wrote. The
    # maintenance path settles its own barrier under the window contract.
    if legacy_authority:
        _authority_barrier(
            db_path, project_id=project_id, phase=MAINTENANCE_POSTGRES_ACTIVE,
            writer_generation=int(expected_generation) + 1,
            admission_id=admission_id,
            require_phase=MAINTENANCE_SWITCHING,
        )
    return {
        "admitted": True,
        "blocking": [],
        "conditions": evaluation["conditions"],
        "report_summary": evaluation["report_summary"],
        "admission": admission,
    }


def _emergency_revoke(connection, project_id: str, admission_id: str, *, reason: str) -> None:
    """Give authority back to SQLite without requiring prior evidence."""
    from psycopg.rows import dict_row

    require_idle_transaction(connection, purpose="emergency cutover revocation")
    with connection.transaction():
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"algorithm-cutover:{project_id}",),
            )
            cursor.execute(
                "UPDATE w5_algorithm.cutover_state SET authoritative_provider=%s,"
                "writer_generation=writer_generation+1,revoked_at=now(),"
                "evidence=evidence || %s::jsonb WHERE project_id=%s AND admission_id=%s",
                (
                    PROVIDER_SQLITE,
                    json.dumps({"emergency_revocation": {"reason": reason}}, ensure_ascii=False),
                    project_id,
                    admission_id,
                ),
            )


@contextmanager
def cutover_transition(
    record_path: str | Path,
    *,
    project_id: str,
    kind: str,
    expect_provider: str = PROVIDER_POSTGRESQL,
):
    """Publish a persisted "switch in progress" marker for the whole switch.

    The marker exists from before PostgreSQL commits the new authority until the
    local admission record is durable, so a crash in that window leaves an
    explicit, recoverable state in which neither provider accepts writes.

    It is removed only when the switch actually completed: the body returned
    normally *and* the durable admission record now names the expected
    authoritative provider. Any exception keeps the marker, because an
    unfinished or unproven switch must keep blocking writes instead of silently
    erasing the evidence that it was interrupted.
    """
    marker = admission_transition_path(record_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_marker(marker)
    if (
        isinstance(existing, Mapping)
        and str(existing.get("schema") or "") == MAINTENANCE_SCHEMA
        and str(existing.get("phase") or "") not in SETTLED_MAINTENANCE_PHASES
    ):
        # The legacy transition marker would overwrite the uncommitted phase of
        # a formal window and hide which operation owns the project.
        raise AlgorithmCutoverRefused(
            "ALGORITHM_MAINTENANCE_CONTRACT_REQUIRED",
            "a maintenance marker already owns this project; finish or recover "
            "that window instead of opening a legacy transition",
            detail=f"phase={existing.get('phase')} operation={existing.get('operation_id')}",
        )
    record = {
        "schema": "algorithm-cutover-transition/1",
        "project_id": str(project_id),
        "kind": str(kind),
        "expected_provider": str(expect_provider),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "an unresolved cutover blocks both providers; finish or roll back "
            "the cutover, then remove this marker"
        ),
    }
    # Hold the same switch lock the SQLite writers take, so no write can slip
    # through between the authority change and the marker publication.
    with admission_switch_lock(record_path):
        marker.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        yield marker
    except BaseException:
        raise
    else:
        if not _admission_provider_is(record_path, project_id, expect_provider):
            return
        with admission_switch_lock(record_path):
            try:
                marker.unlink()
            except FileNotFoundError:
                pass


def _admission_provider_is(record_path: str | Path, project_id: str, provider: str) -> bool:
    """True only when the durable record proves the switch reached its target."""
    try:
        record = load_admission_record(record_path)
    except Exception:
        return False
    if not isinstance(record, Mapping):
        return False
    if str(record.get("project_id") or "") != str(project_id):
        return False
    if str(record.get("authoritative_provider") or "") != str(provider):
        return False
    revoked = bool(record.get("revoked_at"))
    if str(provider) == PROVIDER_POSTGRESQL:
        # A revoked admission never proves PostgreSQL authority.
        return not revoked
    # SQLite authority after a rollback is *proven by* revoked_at; a settled
    # SQLite window that never admitted also carries its settled phase.
    return revoked or str(record.get("maintenance_phase") or "") in {
        MAINTENANCE_SQLITE_ACTIVE, MAINTENANCE_ROLLBACK_APPLIED,
    }


def write_admission_record(record: Mapping[str, Any], path: str | Path) -> Path:
    """Atomically persist the local admission record used by the provider factory."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=str(target.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(dict(record), ensure_ascii=False, indent=2, sort_keys=True))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, target)
        # The rename is only durable once the directory entry is flushed; without
        # it a crash can lose the admission record the marker was cleared for.
        _fsync_directory(target.parent)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise
    return target


def assess_rollback(
    connection,
    *,
    db_path: str | Path,
    admission: Mapping[str, Any],
) -> dict[str, Any]:
    """Reverse restoration is allowed only with provable safety evidence."""
    project_id = str(admission.get("project_id") or "")
    if not project_id:
        raise AlgorithmCutoverError(
            "ALGORITHM_ROLLBACK_ADMISSION_INVALID", "admission record has no project"
        )
    require_current_schema(connection)
    state = _state_row(connection, project_id)
    active = (
        state is not None
        and str(state["authoritative_provider"]) == PROVIDER_POSTGRESQL
        and not state.get("revoked_at")
        and str(state["admission_id"]) == str(admission.get("admission_id") or "")
    )
    target = export_target_snapshot(connection, project_id) if active else None
    admitted_revision = int(state["algorithm_revision"]) if active else None
    admitted_content = str(state["content_digest"]) if active else None
    target_revision = int(target["algorithm_revision"]) if target is not None else None
    target_content = content_digest(target) if target is not None else None
    source = None
    source_error = ""
    if active:
        try:
            source = export_source_snapshot(db_path, project_id)
        except Exception as error:  # missing/unreadable SQLite must fail closed
            source_error = f"{type(error).__name__}: {error}"
    source_content = content_digest(source) if source is not None else None
    conditions = [
        _condition(
            "CUTOVER_CURRENTLY_ACTIVE",
            active,
            detail="no active PostgreSQL admission matches this record",
        ),
        _condition(
            "TARGET_HAS_NO_NEW_WRITES",
            active and target is not None and target_revision == admitted_revision
            and target_content == admitted_content,
            detail=(
                f"admitted_revision={admitted_revision} current={target_revision} "
                f"admitted_digest={admitted_content} current={target_content}"
            ),
        ),
        _condition(
            "SQLITE_COPY_MATCHES_ADMITTED_CONTENT",
            active and source is not None and source_content == admitted_content,
            detail=(
                f"sqlite={source_content} admitted={admitted_content} error={source_error}"
                if source_error else f"sqlite={source_content} admitted={admitted_content}"
            ),
        ),
        _condition(
            "NO_IMPORT_RUNNING",
            not any(
                item["status"] == "RUNNING"
                for item in run_status(connection, project_id)["runs"]
            ),
            detail="an import is still running",
        ),
    ]
    blocking = [item["code"] for item in conditions if not item["ok"]]
    return {
        "allowed": not blocking,
        "blocking": blocking,
        "conditions": conditions,
        "project_id": project_id,
        "admission_id": admission.get("admission_id"),
        "admitted_revision": admitted_revision,
        "admitted_content_digest": admitted_content,
        "target": None if target is None else {
            "revision": target_revision,
            "content_digest": target_content,
        },
        "source": None if source is None else {
            "revision": int(source["algorithm_revision"]),
            "content_digest": source_content,
        },
        "source_error": source_error,
        "restore_content_digest": admitted_content,
    }


def revoke_admission(
    connection,
    *,
    project_id: str,
    admission_id: str,
    expected_generation: int,
    operator: str,
    reason: str,
    assessment: Mapping[str, Any],
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Flip authority back to SQLite only after a passing rollback assessment."""
    from psycopg.rows import dict_row

    if not assessment.get("allowed") or assessment.get("blocking"):
        raise AlgorithmCutoverError(
            "ALGORITHM_ROLLBACK_BLOCKED",
            "refusing to revoke admission without safety evidence",
            detail=f"blocking={assessment.get('blocking')}",
        )
    project_id = str(project_id)
    window = read_maintenance(connection, project_id)
    if window is not None and str(window.get("phase") or "") in (
        MAINTENANCE_QUIESCING, MAINTENANCE_SOURCE_FROZEN,
        MAINTENANCE_VERIFIED, MAINTENANCE_SWITCHING,
    ):
        # A switch window is open: revoking under it would settle an authority
        # the window does not permit. Recovery must finish or reject it first.
        raise AlgorithmCutoverRefused(
            "ALGORITHM_MAINTENANCE_CONTRACT_REQUIRED",
            "an algorithm cutover window owns this project; revoke through the "
            "maintenance contract",
            detail=f"phase={window.get('phase')} operation={window.get('operation_id')}",
        )
    revoked_at = datetime.now(timezone.utc).isoformat()
    require_idle_transaction(connection, purpose="cutover revocation")
    with connection.transaction():
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"algorithm-cutover:{project_id}",),
            )
            cursor.execute(
                "SELECT writer_generation,admission_id,evidence,algorithm_revision,"
                "content_digest,revoked_at,authoritative_provider "
                "FROM w5_algorithm.cutover_state WHERE project_id=%s FOR UPDATE",
                (project_id,),
            )
            locked = cursor.fetchone()
            if locked is None:
                raise AlgorithmCutoverError(
                    "ALGORITHM_ROLLBACK_ADMISSION_MISSING",
                    "no cutover state to revoke",
                )
            if int(locked["writer_generation"]) != int(expected_generation):
                raise AlgorithmCutoverError(
                    "ALGORITHM_CUTOVER_WRITER_GENERATION_CONFLICT",
                    "writer generation changed before revocation",
                )
            if str(locked["admission_id"]) != str(admission_id):
                raise AlgorithmCutoverError(
                    "ALGORITHM_ROLLBACK_ADMISSION_MISSING",
                    "admission id no longer matches the database",
                )
            evidence = dict(locked["evidence"] or {})
            authority = str(locked["authoritative_provider"] or "")
            admitted_revision = int(locked["algorithm_revision"] or 0)
            admitted_content = str(locked["content_digest"] or "")
            if locked.get("revoked_at") is not None or authority != PROVIDER_POSTGRESQL:
                raise AlgorithmCutoverError(
                    "ALGORITHM_ROLLBACK_ADMISSION_INVALID",
                    "the admission is not an active PostgreSQL authority",
                    detail=f"provider={authority} revoked={locked.get('revoked_at') is not None}",
                )
            # The revocation is only legal inside this rollback window: the
            # durable phase and operation identity must be the ones the caller
            # is rolling back.
            maintenance = evidence.get("maintenance")
            maintenance = dict(maintenance) if isinstance(maintenance, Mapping) else {}
            durable_phase = str(maintenance.get("phase") or "")
            durable_operation = str(maintenance.get("operation_id") or "")
            if durable_phase != MAINTENANCE_ROLLBACK_QUIESCING:
                raise AlgorithmCutoverError(
                    "ALGORITHM_ROLLBACK_PHASE_INVALID",
                    "the durable phase does not allow a revocation",
                    detail=f"phase={durable_phase}",
                )
            if operation_id is not None and durable_operation != str(operation_id):
                raise AlgorithmCutoverError(
                    "ALGORITHM_ROLLBACK_OPERATION_MISMATCH",
                    "the rollback operation does not own this project",
                    detail=f"record={durable_operation} requested={operation_id}",
                )
            # The caller's assessment is not trusted: re-read the authoritative
            # content inside this transaction and refuse any drift (a new
            # PostgreSQL write, or a target that no longer matches the admitted
            # digest) before revoking.
            with connection.cursor() as interior:
                interior.execute(
                    "SELECT algorithm_revision FROM w5_algorithm.store_revision "
                    "WHERE project_id=%s",
                    (project_id,),
                )
                revision_row = interior.fetchone()
            target_revision = int(revision_row[0]) if revision_row else 0
            target_snapshot = export_target_snapshot(connection, project_id)
            target_content = (
                None if target_snapshot is None else content_digest(target_snapshot)
            )
            # The durable admitted values are authoritative; the caller's
            # assessment is only a cross-check. A revision of 0 is a valid
            # revision and is compared like any other.
            if not admitted_content or target_content != admitted_content:
                raise AlgorithmCutoverError(
                    "ALGORITHM_ROLLBACK_TARGET_CHANGED",
                    "PostgreSQL content changed before the revocation",
                    detail=f"target={target_content} admitted={admitted_content}",
                )
            caller_digest = str(assessment.get("restore_content_digest") or "")
            if caller_digest and caller_digest != admitted_content:
                raise AlgorithmCutoverError(
                    "ALGORITHM_ROLLBACK_ASSESSMENT_MISMATCH",
                    "the assessment does not describe the admitted content",
                    detail=f"assessment={caller_digest} admitted={admitted_content}",
                )
            if target_revision != admitted_revision:
                raise AlgorithmCutoverError(
                    "ALGORITHM_ROLLBACK_TARGET_HAS_NEW_WRITES",
                    "PostgreSQL received new writes after admission",
                    detail=f"target_revision={target_revision} admitted={admitted_revision}",
                )
            evidence["revocation"] = {
                "operator": str(operator).strip(),
                "reason": str(reason).strip(),
                "target_revision": target_revision,
                "target_content_digest": target_content,
                "assessment": {
                    "allowed": assessment.get("allowed"),
                    "blocking": list(assessment.get("blocking") or []),
                    "conditions": list(assessment.get("conditions") or []),
                },
            }
            cursor.execute(
                "UPDATE w5_algorithm.cutover_state SET authoritative_provider=%s,"
                "writer_generation=writer_generation+1,revoked_at=now(),evidence=%s::jsonb "
                "WHERE project_id=%s "
                "RETURNING writer_generation,revoked_at",
                (PROVIDER_SQLITE, json.dumps(evidence, ensure_ascii=False), project_id),
            )
            committed = cursor.fetchone()
            if committed is None:
                raise AlgorithmCutoverError(
                    "ALGORITHM_ROLLBACK_NOT_SETTLED",
                    "the revocation did not report its committed row",
                )
            committed_generation = int(committed["writer_generation"])
            # Use the revocation evidence the database committed; never a local
            # approximation of the timestamp.
            revoked_at = str(committed["revoked_at"])
    return {
        "contract_version": CONTRACT_VERSION,
        "admission_id": admission_id,
        "project_id": project_id,
        "authoritative_provider": PROVIDER_SQLITE,
        "algorithm_revision": int(assessment.get("admitted_revision") or 0),
        "content_digest": assessment.get("admitted_content_digest"),
        "snapshot_digest": "",
        "writer_generation": committed_generation,
        "admitted_at": None,
        "revoked_at": revoked_at,
        "operator": str(operator).strip(),
        "reason": str(reason).strip(),
        "committed_generation": committed_generation,
    }


def rollback(
    connection,
    *,
    db_path: str | Path,
    admission_path: str | Path,
    confirmed: bool,
    operator: str,
    reason: str,
) -> dict[str, Any]:
    """Block PostgreSQL first, then restore SQLite and revoke the admission.

    Order matters: the previous implementation restored SQLite and only then
    revoked PostgreSQL, so PostgreSQL writes could land in the restored copy or
    be silently lost. The window now persists ROLLBACK_QUIESCING before any
    restore work, which makes PostgreSQL refuse business writes (its gate only
    accepts a settled phase) while the marker keeps SQLite blocked, so the
    restore happens on drained data.
    """
    admission = load_admission_record(admission_path)
    if admission is None:
        raise AlgorithmCutoverError(
            "ALGORITHM_ROLLBACK_ADMISSION_MISSING",
            "rollback requires the admission record written by cutover-admit",
        )
    project_id = str(admission.get("project_id") or "")
    assessment = assess_rollback(connection, db_path=db_path, admission=admission)
    if not assessment["allowed"]:
        # Refuses unsafe reverse restoration, including "PostgreSQL has new
        # writes since admission" (TARGET_HAS_NO_NEW_WRITES).
        return {"rolled_back": False, "assessment": assessment}
    if not confirmed:
        raise AlgorithmCutoverError(
            "ALGORITHM_ROLLBACK_CONFIRMATION_REQUIRED",
            "reverse restoration requires explicit --confirm",
        )

    record_path = Path(admission_path)
    marker_path = admission_transition_path(record_path)
    current = read_maintenance(connection, project_id)
    if current is not None and str(current.get("phase") or "") not in (
        SETTLED_MAINTENANCE_PHASES | {MAINTENANCE_ROLLBACK_QUIESCING}
    ):
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_PHASE_INVALID",
            "a different maintenance phase owns this project",
            detail=f"phase={current.get('phase')}",
        )
    operation_id = str((current or {}).get("operation_id") or "")
    resuming = (
        current is not None
        and str(current.get("phase") or "") == MAINTENANCE_ROLLBACK_QUIESCING
        and str(current.get("project_id") or "") == project_id
    )
    # The CAS must name what the database actually records *now*: the operation
    # that settled the switch (a first rollback) or this rollback operation
    # itself (a resumed one). The new operation id is what gets written, never
    # what is expected to be there already.
    previous_operation = str((current or {}).get("operation_id") or "")
    previous_phase = str((current or {}).get("phase") or "")
    if not operation_id or not resuming:
        operation_id = uuid.uuid4().hex

    # 1. Block PostgreSQL writes (persisted phase) and SQLite writes (marker).
    quiescing = _maintenance_record(
        MAINTENANCE_ROLLBACK_QUIESCING,
        operation_id=operation_id,
        project_id=project_id,
        generation=int(admission.get("writer_generation") or 0),
        source_provider=PROVIDER_POSTGRESQL,
        target_provider=PROVIDER_SQLITE,
        snapshot_digest=str(admission.get("snapshot_digest") or ""),
        verification_digest=str(assessment.get("restore_content_digest") or ""),
        operator=operator,
        reason=reason,
    )
    _publish_marker(marker_path, quiescing)
    try:
        _set_maintenance(
            connection, project_id, quiescing,
            expected_phase=previous_phase if current is not None else None,
            expected_operation_id=previous_operation if current is not None else None,
            expected_generation=int(admission.get("writer_generation") or 0),
        )
    except BaseException:
        state = _maintenance_commit_state(
            connection, project_id,
            operation_id=operation_id, phase=MAINTENANCE_ROLLBACK_QUIESCING,
            previous_operation=previous_operation if current is not None else None,
            previous_phase=previous_phase if current is not None else None,
        )
        try:
            if state == "known_not_committed":
                _remove_marker(marker_path, operation_id)
        finally:
            raise

    # 2. Re-verify the target after the block: the assessment digest must still
    #    describe what PostgreSQL holds now.
    snapshot = export_target_snapshot(connection, project_id)
    if snapshot is None:
        raise AlgorithmCutoverError(
            "ALGORITHM_ROLLBACK_TARGET_MISSING", "PostgreSQL project content is missing"
        )
    if content_digest(snapshot) != assessment["restore_content_digest"]:
        raise AlgorithmCutoverError(
            "ALGORITHM_ROLLBACK_TARGET_CHANGED",
            "PostgreSQL content changed after the rollback assessment",
        )

    # 3. Restore, then revoke; the blocking phase keeps writers out meanwhile.
    restored = restore_source_snapshot(
        db_path,
        project_id,
        validate_snapshot(snapshot),
        assessment=assessment,
        confirmed=True,
    )
    # Prove the SQLite restore really happened before the authority is handed
    # back: the revoked admission must describe the copy SQLite will serve.
    restored_snapshot = export_source_snapshot(db_path, project_id)
    if content_digest(restored_snapshot) != content_digest(snapshot):
        raise AlgorithmCutoverError(
            "ALGORITHM_ROLLBACK_RESTORE_UNPROVEN",
            "the SQLite restore does not match the PostgreSQL content",
        )
    revoked = revoke_admission(
        connection,
        project_id=project_id,
        admission_id=str(admission.get("admission_id") or ""),
        expected_generation=int(admission.get("writer_generation") or 0),
        operator=operator,
        reason=reason,
        assessment=assessment,
        operation_id=operation_id,
    )
    if str(revoked.get("authoritative_provider") or "") != PROVIDER_SQLITE:
        raise AlgorithmCutoverError(
            "ALGORITHM_ROLLBACK_NOT_SETTLED",
            "the revoke did not return authority to SQLite",
            detail=str(revoked.get("authoritative_provider")),
        )
    if not revoked.get("revoked_at"):
        raise AlgorithmCutoverError(
            "ALGORITHM_ROLLBACK_NOT_SETTLED",
            "the revoke did not record revoked_at; the window stays blocked",
        )

    # 4. Settle: durable local record first, then the phase, then the marker.
    applied = _maintenance_record(
        MAINTENANCE_ROLLBACK_APPLIED,
        operation_id=operation_id,
        project_id=project_id,
        generation=int(revoked.get("writer_generation") or 0),
        source_provider=PROVIDER_SQLITE,
        target_provider=PROVIDER_POSTGRESQL,
        snapshot_digest=str(admission.get("snapshot_digest") or ""),
        verification_digest=str(assessment.get("restore_content_digest") or ""),
        operator=operator,
        reason=reason,
    )
    record = {
        **revoked,
        "operation_id": operation_id,
        "maintenance_phase": MAINTENANCE_ROLLBACK_APPLIED,
        "snapshot_digest": str(admission.get("snapshot_digest") or ""),
        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
    }
    write_admission_record(record, record_path)
    _set_maintenance(
        connection, project_id, applied,
        expected_phase=MAINTENANCE_ROLLBACK_QUIESCING,
        expected_operation_id=operation_id,
        expected_generation=int(revoked.get("writer_generation") or 0),
    )
    # Only a completed, verified rollback releases the local barrier.
    _authority_barrier(
        db_path, project_id=project_id, phase=MAINTENANCE_ROLLBACK_APPLIED,
        operation_id=operation_id,
        writer_generation=int(revoked.get("writer_generation") or 0),
        admission_id=str(revoked.get("admission_id") or ""),
        record_path=record_path,
        require_phase=MAINTENANCE_POSTGRES_ACTIVE,
    )
    _remove_marker(marker_path, operation_id)
    return {
        "rolled_back": True,
        "assessment": assessment,
        "restored": restored,
        "admission": record,
        "operation_id": operation_id,
        "phase": MAINTENANCE_ROLLBACK_APPLIED,
    }

# --------------------------------------------------------------- maintenance
#
# One controlled maintenance window per project. The phases are persisted in
# ``cutover_state.evidence`` (top-level ``phase`` for the PostgreSQL write gate,
# ``maintenance`` for the full operation identity) and mirrored into the local
# transition marker so the SQLite writers block as well:
#
#   SQLITE_ACTIVE -> QUIESCING -> SOURCE_FROZEN -> VERIFIED -> SWITCHING
#                 -> POSTGRES_ACTIVE
#
# A rollback runs the mirror sequence ROLLBACK_QUIESCING -> ROLLBACK_APPLIED.
# Every blocking phase leaves both providers refusing business writes, so a
# crash anywhere keeps the system fail-closed and recoverable instead of
# silently letting one side write the other's stale data.

MAINTENANCE_SCHEMA = "algorithm-maintenance/1"
MAINTENANCE_SQLITE_ACTIVE = "SQLITE_ACTIVE"
MAINTENANCE_QUIESCING = "QUIESCING"
MAINTENANCE_SOURCE_FROZEN = "SOURCE_FROZEN"
MAINTENANCE_VERIFIED = "VERIFIED"
MAINTENANCE_SWITCHING = "SWITCHING"
MAINTENANCE_POSTGRES_ACTIVE = "POSTGRES_ACTIVE"
MAINTENANCE_ROLLBACK_QUIESCING = "ROLLBACK_QUIESCING"
MAINTENANCE_ROLLBACK_APPLIED = "ROLLBACK_APPLIED"

#: Phases in which the persisted state itself forbids business writes.
BLOCKING_MAINTENANCE_PHASES = frozenset({
    MAINTENANCE_QUIESCING,
    MAINTENANCE_SOURCE_FROZEN,
    MAINTENANCE_VERIFIED,
    MAINTENANCE_SWITCHING,
    MAINTENANCE_ROLLBACK_QUIESCING,
})
#: Phases that prove the window finished (marker may be cleared).
SETTLED_MAINTENANCE_PHASES = frozenset({
    MAINTENANCE_SQLITE_ACTIVE,
    MAINTENANCE_POSTGRES_ACTIVE,
    MAINTENANCE_ROLLBACK_APPLIED,
})
MAINTENANCE_PHASES = BLOCKING_MAINTENANCE_PHASES | SETTLED_MAINTENANCE_PHASES


def _maintenance_record(
    phase: str,
    *,
    operation_id: str,
    project_id: str,
    generation: int,
    source_provider: str,
    target_provider: str,
    snapshot_digest: str = "",
    verification_digest: str = "",
    content_digest: str = "",
    source_revision: int | None = None,
    operator: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """One immutable phase record: the identity a phase is allowed to act on.

    The digests are distinct facts and are never interchangeable:

    * ``snapshot_digest`` is the snapshot contract digest (it changes with every
      export because it covers ``captured_at``);
    * ``content_digest`` is the normalized project content - the identity of the
      frozen source that a recovery may replay;
    * ``verification_digest`` is the real source/target reconciliation summary;
    * ``source_revision`` is the frozen algorithm revision.
    """
    return {
        "schema": MAINTENANCE_SCHEMA,
        "phase": str(phase),
        "operation_id": str(operation_id),
        "project_id": str(project_id),
        "generation": int(generation),
        "source_provider": str(source_provider),
        "target_provider": str(target_provider),
        "snapshot_digest": str(snapshot_digest or ""),
        "content_digest": str(content_digest or ""),
        "source_revision": None if source_revision is None else int(source_revision),
        "verification_digest": str(verification_digest or ""),
        "operator": str(operator or ""),
        "reason": str(reason or ""),
        "write_blocked": str(phase) in BLOCKING_MAINTENANCE_PHASES,
        "at": datetime.now(timezone.utc).isoformat(),
    }


def _publish_marker(marker_path: str | Path, record: Mapping[str, Any]) -> Path:
    """Atomically publish the local transition marker for this operation.

    A marker belonging to a *different* unfinished operation is never
    overwritten: that would erase the evidence of a switch nobody finished.
    """
    marker = Path(marker_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    with admission_switch_lock(marker):
        existing = _read_marker(marker)
        if existing is not None:
            same_operation = str(existing.get("operation_id") or "") == str(record["operation_id"])
            unfinished = str(existing.get("phase") or "") not in SETTLED_MAINTENANCE_PHASES
            if unfinished and not same_operation:
                raise AlgorithmCutoverError(
                    "ALGORITHM_MAINTENANCE_OPERATION_CONFLICT",
                    "another unfinished algorithm maintenance operation owns this project",
                    detail=(
                        f"existing_operation={existing.get('operation_id')} "
                        f"phase={existing.get('phase')} "
                        f"requested_operation={record['operation_id']}"
                    ),
                )
        descriptor, temporary = tempfile.mkstemp(
            prefix=f".{marker.name}.", suffix=".tmp", dir=str(marker.parent)
        )
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
                json.dump(dict(record), stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, marker)
            _fsync_directory(marker.parent)
            return marker
        finally:
            try:
                Path(temporary).unlink()
            except FileNotFoundError:
                pass


def _read_marker(marker_path: str | Path) -> dict[str, Any] | None:
    marker = Path(marker_path)
    if not marker.is_file():
        return None
    try:
        value = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"phase": "UNREADABLE", "operation_id": ""}
    return value if isinstance(value, dict) else {"phase": "INVALID", "operation_id": ""}


def _remove_marker(marker_path: str | Path, operation_id: str) -> bool:
    """Remove the marker only when it belongs to this operation."""
    marker = Path(marker_path)
    with admission_switch_lock(marker):
        existing = _read_marker(marker)
        if existing is None:
            return True
        if str(existing.get("operation_id") or "") != str(operation_id):
            raise AlgorithmCutoverError(
                "ALGORITHM_MAINTENANCE_MARKER_FOREIGN",
                "refusing to clear another operation's maintenance marker",
                detail=f"marker_operation={existing.get('operation_id')}",
            )
        marker.unlink()
        _fsync_directory(marker.parent)
        return True


def _fsync_directory(path: Path) -> None:
    if os.name == "nt":
        return
    try:
        descriptor = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _set_maintenance(
    connection,
    project_id: str,
    record: Mapping[str, Any],
    *,
    expected_phase: str | None = None,
    expected_operation_id: str | None = None,
    expected_generation: int | None = None,
) -> dict[str, Any]:
    """Persist one phase under the cutover advisory lock + row lock.

    The phase lives in ``cutover_state.evidence`` so it survives this
    transaction: a later writer cannot assume a transaction-scoped lock still
    protects it. Each call commits on its own (``require_idle_transaction``
    refuses to downgrade this to a savepoint), so a crash after a phase keeps
    that phase instead of losing the whole window.
    """
    from psycopg.rows import dict_row

    require_current_schema(connection)
    require_idle_transaction(connection, purpose="maintenance phase publication")
    payload = json.dumps(
        {"phase": str(record["phase"]), "maintenance": dict(record)}, ensure_ascii=False
    )
    with connection.transaction():
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"algorithm-cutover:{project_id}",),
            )
            cursor.execute(
                "SELECT project_id FROM w5_algorithm.cutover_state "
                "WHERE project_id=%s FOR UPDATE",
                (project_id,),
            )
            row = cursor.fetchone()
            exists = row is not None
            if exists and (
                expected_phase is not None
                or expected_operation_id is not None
                or expected_generation is not None
            ):
                # Compare-and-swap inside the same advisory + row lock: a step
                # may only advance the state it was planned against.
                cursor.execute(
                    "SELECT writer_generation, evidence FROM w5_algorithm.cutover_state "
                    "WHERE project_id=%s",
                    (project_id,),
                )
                current = cursor.fetchone() or {}
                evidence_now = current.get("evidence")
                maintenance_now = (
                    evidence_now.get("maintenance")
                    if isinstance(evidence_now, Mapping) else None
                )
                phase_now = str(
                    (maintenance_now or {}).get("phase")
                    or (evidence_now or {}).get("phase")
                    or ""
                )
                operation_now = str((maintenance_now or {}).get("operation_id") or "")
                generation_now = int(current.get("writer_generation") or 0)
                if expected_phase is not None and phase_now != str(expected_phase):
                    raise AlgorithmCutoverError(
                        "ALGORITHM_MAINTENANCE_PHASE_CONFLICT",
                        "maintenance phase moved while the step was being prepared",
                        detail=f"expected={expected_phase} current={phase_now}",
                    )
                if (
                    expected_operation_id is not None
                    and operation_now != str(expected_operation_id)
                ):
                    raise AlgorithmCutoverError(
                        "ALGORITHM_MAINTENANCE_OPERATION_MISMATCH",
                        "maintenance operation changed while the step was being prepared",
                        detail=f"expected={expected_operation_id} current={operation_now}",
                    )
                if (
                    expected_generation is not None
                    and generation_now != int(expected_generation)
                ):
                    raise AlgorithmCutoverError(
                        "ALGORITHM_MAINTENANCE_GENERATION_MISMATCH",
                        "writer generation moved while the step was being prepared",
                        detail=f"expected={expected_generation} current={generation_now}",
                    )
            if exists:
                cursor.execute(
                    "UPDATE w5_algorithm.cutover_state "
                    "SET evidence = evidence || %s::jsonb WHERE project_id=%s",
                    (payload, project_id),
                )
            else:
                cursor.execute(
                    "INSERT INTO w5_algorithm.cutover_state (project_id,"
                    "authoritative_provider,algorithm_revision,snapshot_digest,"
                    "content_digest,writer_generation,admission_id,admitted_at,"
                    "revoked_at,evidence) VALUES (%s,%s,0,%s,%s,0,%s,now(),now(),%s::jsonb)",
                    (
                        project_id, PROVIDER_SQLITE, "", "",
                        f"maintenance-{record['operation_id']}", payload,
                    ),
                )
    return dict(record)


def read_maintenance(connection, project_id: str) -> dict[str, Any] | None:
    """Current persisted maintenance record, or None when the window is closed."""
    require_current_schema(connection)
    state = _state_row(connection, project_id)
    if state is None:
        return None
    evidence = state.get("evidence")
    if not isinstance(evidence, Mapping):
        return None
    record = evidence.get("maintenance")
    if not isinstance(record, Mapping):
        return None
    return dict(record)


def _maintenance_commit_state(
    connection,
    project_id: str,
    *,
    operation_id: str,
    phase: str,
    previous_operation: str | None = None,
    previous_phase: str | None = None,
) -> str:
    """Prove whether a phase write landed: ``committed``/``known_not_committed``/``unknown``.

    A failed transaction usually means nothing was written, but a connection
    that died after the server committed looks identical to the caller. Only the
    state that can be re-read proves the difference; anything else keeps the
    marker so writes stay blocked instead of being released on a guess.
    """
    try:
        current = read_maintenance(connection, project_id)
    except Exception:  # noqa: BLE001 - an unreadable state is an unknown commit
        return "unknown"
    if current is not None:
        current_phase = str(current.get("phase") or "")
        current_operation = str(current.get("operation_id") or "")
        if current_operation == str(operation_id) and current_phase == str(phase):
            return "committed"
        if (
            previous_operation is not None
            and current_operation == str(previous_operation)
            and current_phase == str(previous_phase or "")
        ):
            return "known_not_committed"
        return "unknown"
    return "known_not_committed" if previous_operation is None else "unknown"


def begin_maintenance_window(
    connection,
    *,
    project_id: str,
    db_path: str | Path,
    record_path: str | Path,
    expected_generation: int,
    operator: str = "",
    reason: str = "",
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Open the window: block both writers first, then record the operation."""
    current = read_maintenance(connection, project_id)
    previous_phase = str((current or {}).get("phase") or MAINTENANCE_SQLITE_ACTIVE)
    if current is not None and str(current.get("phase") or "") in BLOCKING_MAINTENANCE_PHASES:
        raise AlgorithmCutoverRefused(
            "ALGORITHM_MAINTENANCE_IN_PROGRESS",
            "an algorithm maintenance window is already open for this project",
            detail=f"operation={current.get('operation_id')} phase={current.get('phase')}",
        )
    # The caller must present the generation it planned against. This is a
    # refusal, not an internal failure: a stale request changes nothing.
    state = _state_row(connection, project_id)
    current_generation = int((state or {}).get("writer_generation") or 0)
    if current_generation != int(expected_generation):
        raise AlgorithmCutoverRefused(
            "ALGORITHM_MAINTENANCE_GENERATION_MISMATCH",
            "writer generation moved before the maintenance window opened",
            detail=f"database={current_generation} expected={int(expected_generation)}",
        )
    operation = str(operation_id or uuid.uuid4().hex)
    record = _maintenance_record(
        MAINTENANCE_QUIESCING,
        operation_id=operation,
        project_id=project_id,
        generation=int(expected_generation),
        source_provider=PROVIDER_SQLITE,
        target_provider=PROVIDER_POSTGRESQL,
        operator=operator,
        reason=reason,
    )
    record["previous_phase"] = previous_phase
    marker = _publish_marker(admission_transition_path(record_path), record)
    try:
        # CAS against what was actually recorded: the *previous* operation (if
        # any) and its settled phase, never the new operation identity - a new
        # window after a completed one is a new operation by definition.
        previous_operation = str((current or {}).get("operation_id") or "")
        _set_maintenance(
            connection, project_id, record,
            expected_phase=previous_phase if current is not None else None,
            expected_operation_id=previous_operation if current is not None else None,
            expected_generation=int(expected_generation),
        )
    except BaseException:
        # A phase that may have committed is never released: the marker stays
        # until recovery proves the durable state. Only a provably unwritten
        # phase may clear its own marker.
        state = _maintenance_commit_state(
            connection, project_id,
            operation_id=operation, phase=MAINTENANCE_QUIESCING,
            previous_operation=previous_operation if current is not None else None,
            previous_phase=previous_phase if current is not None else None,
        )
        try:
            if state == "known_not_committed":
                _remove_marker(marker, operation)
        finally:
            raise
    return {"operation_id": operation, "phase": MAINTENANCE_QUIESCING,
            "previous_phase": previous_phase, "marker": str(marker),
            "write_blocked": True}


def _authority_barrier(
    db_path: str | Path,
    *,
    project_id: str,
    phase: str,
    operation_id: str = "",
    writer_generation: int = 0,
    admission_id: str = "",
    record_path: str | Path | None = None,
    require_operation: str | None = None,
    require_phase: str | None = None,
    allowed_phases: Sequence[str] | None = None,
    require_existing: bool = False,
) -> bool:
    """Write this project's local authority barrier next to the SQLite catalog.

    The barrier is the persistent local evidence that SQLite is (or is not) the
    admitted writer, so a lost admission record cannot silently re-open it. It is
    written *before* PostgreSQL becomes authoritative; failing to record it stops
    the switch instead of proceeding without blocking evidence.
    """
    from .algorithm_repository import write_authority_barrier

    json_path = Path(db_path).parent / "algorithms.json"
    try:
        recorded = write_authority_barrier(
            json_path,
            project_id=project_id,
            phase=phase,
            operation_id=operation_id,
            writer_generation=writer_generation,
            admission_id=admission_id,
            record_path=record_path,
            require_operation=require_operation,
            require_phase=require_phase,
            allowed_phases=allowed_phases,
            require_existing=require_existing,
        )
    except Exception as error:  # unresolved barrier must not be guessed past
        raise AlgorithmCutoverError(
            "ALGORITHM_CUTOVER_BARRIER_UNAVAILABLE",
            "the local authority barrier could not be recorded",
            detail=f"{type(error).__name__}: {error}",
        ) from error
    if not recorded:
        raise AlgorithmCutoverError(
            "ALGORITHM_CUTOVER_BARRIER_UNAVAILABLE",
            "the local SQLite catalog cannot hold the authority barrier",
            detail=f"expected an initialized catalog at {json_path}",
        )
    return True


def _require_phase(
    connection, project_id: str, operation_id: str, allowed: frozenset[str]
) -> dict[str, Any]:
    current = read_maintenance(connection, project_id)
    if current is None:
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_NOT_OPEN", "no maintenance window is open"
        )
    if str(current.get("project_id")) != str(project_id):
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_OPERATION_MISMATCH",
            "maintenance record belongs to another project",
        )
    if str(current.get("operation_id")) != str(operation_id):
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_OPERATION_MISMATCH",
            "maintenance operation identity does not match",
            detail=f"record={current.get('operation_id')} requested={operation_id}",
        )
    if str(current.get("phase") or "") not in allowed:
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_PHASE_INVALID",
            "maintenance phase does not allow this step",
            detail=f"phase={current.get('phase')} allowed={sorted(allowed)}",
        )
    return current


def freeze_maintenance_source(
    connection,
    *,
    project_id: str,
    db_path: str | Path,
    operation_id: str,
) -> dict[str, Any]:
    """Drain checkpoint: freeze the final SQLite snapshot inside the window."""
    current = _require_phase(
        connection, project_id, operation_id, frozenset({MAINTENANCE_QUIESCING})
    )
    snapshot = export_source_snapshot(db_path, project_id)
    digest = content_digest(snapshot)
    record = _maintenance_record(
        MAINTENANCE_SOURCE_FROZEN,
        operation_id=operation_id,
        project_id=project_id,
        generation=int(current["generation"]),
        source_provider=PROVIDER_SQLITE,
        target_provider=PROVIDER_POSTGRESQL,
        # Keep the three identities apart: the contract digest changes with every
        # export, the content digest is what a recovery must replay, and the
        # revision pins the frozen catalog version.
        snapshot_digest=str(snapshot["snapshot_digest"]),
        content_digest=digest,
        source_revision=int(snapshot["algorithm_revision"]),
        operator=str(current.get("operator") or ""),
        reason=str(current.get("reason") or ""),
    )
    return _set_maintenance(
        connection, project_id, record,
        expected_phase=MAINTENANCE_QUIESCING,
        expected_operation_id=operation_id,
        expected_generation=int(current["generation"]),
    )


def verify_maintenance_window(
    connection,
    *,
    project_id: str,
    operation_id: str,
    verification_digest: str,
) -> dict[str, Any]:
    """Record the import/reconciliation digest that the switch is allowed on."""
    current = _require_phase(
        connection, project_id, operation_id, frozenset({MAINTENANCE_SOURCE_FROZEN})
    )
    record = _maintenance_record(
        MAINTENANCE_VERIFIED,
        operation_id=operation_id,
        project_id=project_id,
        generation=int(current["generation"]),
        source_provider=PROVIDER_SQLITE,
        target_provider=PROVIDER_POSTGRESQL,
        snapshot_digest=str(current.get("snapshot_digest") or ""),
        content_digest=str(current.get("content_digest") or ""),
        source_revision=current.get("source_revision"),
        verification_digest=str(verification_digest or ""),
        operator=str(current.get("operator") or ""),
        reason=str(current.get("reason") or ""),
    )
    return _set_maintenance(
        connection, project_id, record,
        expected_phase=MAINTENANCE_SOURCE_FROZEN,
        expected_operation_id=operation_id,
        expected_generation=int(current["generation"]),
    )


def switch_maintenance_owner(
    connection,
    *,
    project_id: str,
    db_path: str | Path,
    record_path: str | Path,
    operation_id: str,
    expected_generation: int,
    operator: str = "",
    reason: str = "",
    acknowledge_unported: bool = False,
    previous_report: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Switch the single writer to PostgreSQL and settle the window."""
    current = _require_phase(
        connection, project_id, operation_id, frozenset({MAINTENANCE_VERIFIED})
    )
    if int(current["generation"]) != int(expected_generation):
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_GENERATION_MISMATCH",
            "writer generation moved since the window opened",
            detail=f"window={current['generation']} requested={expected_generation}",
        )
    switching = _maintenance_record(
        MAINTENANCE_SWITCHING,
        operation_id=operation_id,
        project_id=project_id,
        generation=int(expected_generation),
        source_provider=PROVIDER_SQLITE,
        target_provider=PROVIDER_POSTGRESQL,
        snapshot_digest=str(current.get("snapshot_digest") or ""),
        content_digest=str(current.get("content_digest") or ""),
        source_revision=current.get("source_revision"),
        verification_digest=str(current.get("verification_digest") or ""),
        operator=operator, reason=reason,
    )
    _set_maintenance(
        connection, project_id, switching,
        expected_phase=MAINTENANCE_VERIFIED,
        expected_operation_id=operation_id,
        expected_generation=int(expected_generation),
    )
    # Blocking evidence first: from here on the local catalog itself says SQLite
    # is not the writer, even if the admission record is lost during the switch.
    _authority_barrier(
        db_path, project_id=project_id, phase=MAINTENANCE_SWITCHING,
        operation_id=operation_id,
        # The admission generation is not committed yet: the barrier records the
        # generation this attempt starts from and settles at the committed one.
        writer_generation=int(expected_generation),
        record_path=record_path,
    )
    admitted = admit_cutover(
        connection,
        db_path=db_path,
        project_id=project_id,
        expected_generation=int(expected_generation),
        operator=operator,
        reason=reason,
        acknowledge_unported=acknowledge_unported,
        previous_report=previous_report,
        # The owner switch is one transaction: the row keeps the SWITCHING
        # phase (and the operation identity) while it becomes authoritative, so
        # there is never a window with no phase at all.
        maintenance=switching,
    )
    if not admitted.get("admitted"):
        # Nothing was written, so restore the phase the project was in and
        # release the marker: an unchanged project must not stay blocked.
        # Restore what the durable state actually says, not a guess: the
        # refusal may be "PostgreSQL is already the writer".
        state_now = _state_row(connection, project_id)
        restore_phase = (
            MAINTENANCE_POSTGRES_ACTIVE
            if state_now is not None
            and str(state_now["authoritative_provider"]) == PROVIDER_POSTGRESQL
            and not state_now.get("revoked_at")
            else MAINTENANCE_SQLITE_ACTIVE
        )
        restore = _maintenance_record(
            str(restore_phase),
            operation_id=operation_id,
            project_id=project_id,
            generation=int(expected_generation),
            source_provider=PROVIDER_SQLITE,
            target_provider=PROVIDER_POSTGRESQL,
            snapshot_digest=str(current.get("snapshot_digest") or ""),
            content_digest=str(current.get("content_digest") or ""),
            source_revision=current.get("source_revision"),
            verification_digest=str(current.get("verification_digest") or ""),
            operator=operator, reason=reason,
        )
        # The row still carries the SWITCHING phase written above (admission was
        # refused, so nothing was committed), and the restore returns it to the
        # proven authority under the same operation identity.
        _set_maintenance(
            connection, project_id, restore,
            expected_phase=MAINTENANCE_SWITCHING,
            expected_operation_id=operation_id,
            expected_generation=int(expected_generation),
        )
        # The refused switch wrote a blocking barrier; release it to whatever the
        # durable authority actually is (SQLite_ACTIVE releases, PostgreSQL keeps
        # blocking SQLite).
        _authority_barrier(
            db_path, project_id=project_id, phase=str(restore_phase),
            operation_id=operation_id,
            writer_generation=int(expected_generation),
            record_path=record_path,
            require_operation=operation_id,
            require_phase=MAINTENANCE_SWITCHING,
        )
        _remove_marker(admission_transition_path(record_path), operation_id)
        raise AlgorithmCutoverRefused(
            "ALGORITHM_MAINTENANCE_SWITCH_REFUSED",
            "cutover admission refused inside the maintenance window",
            detail=json.dumps(admitted.get("blocking"), ensure_ascii=False)[:600],
        )
    settled = _maintenance_record(
        MAINTENANCE_POSTGRES_ACTIVE,
        operation_id=operation_id,
        project_id=project_id,
        generation=int(admitted["admission"]["writer_generation"]),
        source_provider=PROVIDER_POSTGRESQL,
        target_provider=PROVIDER_SQLITE,
        snapshot_digest=str(current.get("snapshot_digest") or ""),
        content_digest=str(current.get("content_digest") or ""),
        source_revision=current.get("source_revision"),
        verification_digest=str(current.get("verification_digest") or ""),
        operator=operator, reason=reason,
    )
    admission = dict(admitted["admission"])
    admission["operation_id"] = operation_id
    admission["maintenance_phase"] = MAINTENANCE_POSTGRES_ACTIVE
    # An admission written by the maintenance contract is distinguishable from
    # a legacy one, so the provider can refuse a missing phase only here.
    admission["admission_mode"] = "maintenance"
    admission["verification_digest"] = str(current.get("verification_digest") or "")
    path = write_admission_record(admission, record_path)
    # Prove the local record against the durable row before the marker is
    # cleared: only a proven switch may unblock SQLite (a marker that outlives a
    # failed local write keeps both sides blocked, which is the safe direction).
    durable = _durable_admission(connection, project_id)
    if not _local_record_matches(
        record_path, project_id=project_id, operation_id=operation_id,
        phase=MAINTENANCE_POSTGRES_ACTIVE, durable=durable,
    ):
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_LOCAL_RECORD_UNPROVEN",
            "the local admission record does not prove the durable switch",
            detail=f"record={path}",
        )
    _set_maintenance(
        connection, project_id, settled,
        expected_phase=MAINTENANCE_SWITCHING,
        expected_operation_id=operation_id,
        expected_generation=int(admitted["admission"]["writer_generation"]),
    )
    _authority_barrier(
        db_path, project_id=project_id, phase=MAINTENANCE_POSTGRES_ACTIVE,
        operation_id=operation_id,
        writer_generation=int(admitted["admission"]["writer_generation"]),
        admission_id=str(admission.get("admission_id") or ""),
        record_path=record_path,
        require_operation=operation_id,
        require_phase=MAINTENANCE_SWITCHING,
        require_existing=True,
    )
    _remove_marker(admission_transition_path(record_path), operation_id)
    return {
        "operation_id": operation_id,
        "phase": MAINTENANCE_POSTGRES_ACTIVE,
        "admission": admission,
        "admission_path": str(path),
        "write_blocked": False,
    }


def resume_maintenance(
    connection,
    *,
    project_id: str,
    record_path: str | Path,
    operation_id: str | None = None,
) -> dict[str, Any]:
    """Controlled recovery entry: report the phase and settle only when proven.

    It never guesses and never deletes a foreign or unfinished marker: an
    unknown state stays blocking, which is the safe direction.
    """
    marker_path = admission_transition_path(record_path)
    marker = _read_marker(marker_path)
    current = read_maintenance(connection, project_id)
    phase = str((current or {}).get("phase") or (marker or {}).get("phase") or "")
    owner = str((current or {}).get("operation_id") or (marker or {}).get("operation_id") or "")
    result: dict[str, Any] = {
        "project_id": project_id,
        "phase": phase or None,
        "operation_id": owner or None,
        "marker_present": marker is not None,
        "write_blocked": phase in BLOCKING_MAINTENANCE_PHASES or marker is not None,
        "settled": False,
    }
    if operation_id and owner and str(operation_id) != owner:
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_OPERATION_MISMATCH",
            "recovery request names a different maintenance operation",
            detail=f"record={owner} requested={operation_id}",
        )
    if phase not in SETTLED_MAINTENANCE_PHASES:
        result["next_step"] = {
            MAINTENANCE_QUIESCING: "freeze_maintenance_source",
            MAINTENANCE_SOURCE_FROZEN: "verify_maintenance_window",
            MAINTENANCE_VERIFIED: "switch_maintenance_owner",
            MAINTENANCE_SWITCHING: "recover_maintenance(apply=True): finish or restore",
            MAINTENANCE_ROLLBACK_QUIESCING: "recover_maintenance(apply=True): resume rollback",
        }.get(phase, "inspect: an unknown or missing phase must be resolved manually")
        return result
    # A settled phase is only clearable when the durable admission agrees.
    expected = (
        PROVIDER_POSTGRESQL if phase == MAINTENANCE_POSTGRES_ACTIVE else PROVIDER_SQLITE
    )
    if not _admission_provider_is(record_path, project_id, expected):
        result["next_step"] = (
            "the local admission record does not prove the settled provider; "
            "the marker is kept so writes stay blocked"
        )
        return result
    if marker is not None:
        _remove_marker(marker_path, owner)
    result["settled"] = True
    result["write_blocked"] = False
    return result


def _durable_admission(connection, project_id: str) -> dict[str, Any] | None:
    require_current_schema(connection)
    state = _state_row(connection, project_id)
    return dict(state) if state is not None else None


def _durable_maintenance(state: Mapping[str, Any] | None) -> dict[str, Any]:
    """The maintenance record inside a durable cutover-state row (if any)."""
    if not isinstance(state, Mapping):
        return {}
    evidence = state.get("evidence")
    if not isinstance(evidence, Mapping):
        return {}
    record = evidence.get("maintenance")
    return dict(record) if isinstance(record, Mapping) else {}


def _local_record_matches(
    record_path: str | Path,
    *,
    project_id: str,
    operation_id: str,
    phase: str,
    durable: Mapping[str, Any] | None,
) -> bool:
    """Whether the local admission record proves the *durable* authority exactly.

    Every identity field is compared against the durable row: project, operation,
    admission, writer generation, phase, snapshot/content/verification digests,
    authoritative provider and revocation. A record that merely names the right
    provider is not proof, and a missing/foreign/corrupt record is never treated
    as SQLite authority.
    """
    if not isinstance(durable, Mapping) or not durable:
        return False
    try:
        record = load_admission_record(record_path)
    except Exception:
        return False
    if not isinstance(record, Mapping):
        return False
    operation = str(operation_id or "")
    if not operation or str(record.get("operation_id") or "") != operation:
        return False
    if str(record.get("project_id") or "") != str(project_id):
        return False
    if str(record.get("project_id") or "") != str(durable.get("project_id") or ""):
        return False
    if str(record.get("maintenance_phase") or "") != str(phase):
        return False
    if str(record.get("admission_id") or "") != str(durable.get("admission_id") or ""):
        return False
    if int(record.get("writer_generation") or 0) != int(durable.get("writer_generation") or 0):
        return False
    if str(record.get("authoritative_provider") or "") != str(
        durable.get("authoritative_provider") or ""
    ):
        return False
    if str(record.get("snapshot_digest") or "") != str(durable.get("snapshot_digest") or ""):
        return False
    if str(record.get("content_digest") or "") != str(durable.get("content_digest") or ""):
        return False
    record_revoked = bool(record.get("revoked_at"))
    durable_revoked = bool(durable.get("revoked_at"))
    if record_revoked != durable_revoked:
        return False
    if record_revoked and str(record.get("revoked_at")) != str(durable.get("revoked_at")):
        return False
    maintenance = _durable_maintenance(durable)
    durable_verification = str(maintenance.get("verification_digest") or "")
    if durable_verification and str(record.get("verification_digest") or "") != durable_verification:
        return False
    # A settled phase is only proven by the provider it settles *to*.
    if str(phase) == MAINTENANCE_POSTGRES_ACTIVE:
        return (
            str(record.get("authoritative_provider") or "") == PROVIDER_POSTGRESQL
            and not record_revoked
        )
    if str(phase) in (MAINTENANCE_SQLITE_ACTIVE, MAINTENANCE_ROLLBACK_APPLIED):
        return (
            str(record.get("authoritative_provider") or "") == PROVIDER_SQLITE
            and record_revoked
        )
    return False


#: A crash during the final local step may complete a recorded phase into the
#: settled phase it was about to publish. Nothing else may be completed.
_DURABLE_PHASE_COMPLETIONS = frozenset({
    (MAINTENANCE_SWITCHING, MAINTENANCE_POSTGRES_ACTIVE),
    (MAINTENANCE_ROLLBACK_QUIESCING, MAINTENANCE_ROLLBACK_APPLIED),
})


def _write_local_from_durable(
    connection,
    *,
    project_id: str,
    record_path: str | Path,
    operation_id: str,
    phase: str,
    durable_phase: str | None = None,
) -> dict[str, Any]:
    """Republish the local admission record from the durable PostgreSQL row.

    ``phase`` is the settled phase being published; ``durable_phase`` is what the
    durable row actually records (a crash may leave SWITCHING or
    ROLLBACK_QUIESCING there). Only the two completion transitions above are
    allowed, so this is not a general relaxation of the phase check.
    """
    state = _durable_admission(connection, project_id)
    if state is None:
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_STATE_MISSING",
            "no durable cutover state to republish",
        )
    if str(state.get("project_id") or "") != str(project_id):
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_STATE_MISMATCH",
            "the durable state belongs to another project",
            detail=f"record={state.get('project_id')} requested={project_id}",
        )
    maintenance = _durable_maintenance(state)
    recorded_phase = str(maintenance.get("phase") or "")
    expected_durable = str(durable_phase or phase)
    if recorded_phase != expected_durable:
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_PHASE_MISMATCH",
            "the durable phase does not match the phase being republished",
            detail=f"durable={recorded_phase} expected={expected_durable} target={phase}",
        )
    # A target phase is only reachable from the recorded phase it finishes: a
    # crash may settle SWITCHING into POSTGRES_ACTIVE and ROLLBACK_QUIESCING into
    # ROLLBACK_APPLIED, but nothing may jump from an unrelated phase, and a
    # settled phase only republishes itself.
    if expected_durable != str(phase) and (
        str(expected_durable), str(phase)
    ) not in _DURABLE_PHASE_COMPLETIONS:
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_PHASE_INVALID",
            "the recorded phase cannot be completed into the requested phase",
            detail=f"durable={expected_durable} target={phase}",
        )
    if str(maintenance.get("operation_id") or "") != str(operation_id):
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_OPERATION_MISMATCH",
            "the durable maintenance operation does not match the local repair",
            detail=f"durable={maintenance.get('operation_id')} requested={operation_id}",
        )
    provider = str(state["authoritative_provider"])
    record = {
        "contract_version": CONTRACT_VERSION,
        "admission_id": str(state.get("admission_id") or ""),
        "project_id": str(project_id),
        "authoritative_provider": provider,
        "algorithm_revision": int(state.get("algorithm_revision") or 0),
        "snapshot_digest": str(state.get("snapshot_digest") or ""),
        "content_digest": str(state.get("content_digest") or ""),
        "verification_digest": str(maintenance.get("verification_digest") or ""),
        "writer_generation": int(state.get("writer_generation") or 0),
        "admitted_at": str(state.get("admitted_at") or ""),
        "revoked_at": state.get("revoked_at"),
        "operation_id": str(operation_id),
        "maintenance_phase": str(phase),
        "admission_mode": "maintenance",
    }
    if str(phase) == MAINTENANCE_POSTGRES_ACTIVE and provider != PROVIDER_POSTGRESQL:
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_STATE_MISMATCH",
            "the durable authority is not PostgreSQL",
            detail=f"provider={provider}",
        )
    if str(phase) in (MAINTENANCE_SQLITE_ACTIVE, MAINTENANCE_ROLLBACK_APPLIED):
        if provider != PROVIDER_SQLITE or not state.get("revoked_at"):
            raise AlgorithmCutoverError(
                "ALGORITHM_MAINTENANCE_STATE_MISMATCH",
                "the durable authority is not a revoked PostgreSQL admission",
                detail=f"provider={provider} revoked={bool(state.get('revoked_at'))}",
            )
    write_admission_record(record, record_path)
    return record


def _import_run(connection, *, project_id: str, run_id: str) -> dict[str, Any] | None:
    """The migration_run row this maintenance operation already owns, if any."""
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT run_id,project_id,status,snapshot_digest,content_digest,"
            "algorithm_revision,mode FROM w5_algorithm.migration_run "
            "WHERE run_id=%s AND project_id=%s",
            (str(run_id), str(project_id)),
        )
        row = cursor.fetchone()
    return dict(row) if row is not None else None


def recover_maintenance(
    connection,
    *,
    project_id: str,
    db_path: str | Path,
    record_path: str | Path,
    operation_id: str | None = None,
    operator: str = "",
    reason: str = "",
    acknowledge_unported: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    """Resolve an interrupted maintenance window, idempotently.

    ``apply=False`` is a read-only status report. ``apply=True`` performs the
    remaining steps of the *recorded* operation, and only when the durable state
    proves they are still safe:

    - a marker without a committed phase is published into PostgreSQL so both
      sides block consistently (nothing is guessed);
    - an unfinished switch resumes from its phase (freeze -> reconcile ->
      switch), re-running the final import rather than trusting an old report;
    - a switch whose PostgreSQL authority already landed is finished locally
      (admission record + settled phase + marker removal);
    - a rollback whose revocation landed but whose local record did not is
      republished and settled;
    - a settled window clears its own marker.
    """
    marker_path = admission_transition_path(record_path)
    marker = _read_marker(marker_path)
    current = read_maintenance(connection, project_id)
    phase = str((current or {}).get("phase") or (marker or {}).get("phase") or "")
    owner = str((current or {}).get("operation_id") or (marker or {}).get("operation_id") or "")
    if operation_id and owner and str(operation_id) != owner:
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_OPERATION_MISMATCH",
            "recovery request names a different maintenance operation",
            detail=f"record={owner} requested={operation_id}",
        )
    operation = str(owner or operation_id or "")
    state = _durable_admission(connection, project_id)
    durable_provider = str((state or {}).get("authoritative_provider") or "")
    revoked = bool((state or {}).get("revoked_at"))
    result: dict[str, Any] = {
        "project_id": project_id,
        "phase": phase or None,
        "operation_id": operation or None,
        "marker_present": marker is not None,
        "durable_provider": durable_provider or None,
        "durable_revoked": revoked,
        "write_blocked": phase in BLOCKING_MAINTENANCE_PHASES or marker is not None,
        "applied": False,
        "settled": False,
    }
    if not apply:
        result["next_step"] = _recovery_next_step(phase, durable_provider, revoked)
        return result

    # A marker that names another operation is a conflict, never a repair: the
    # durable window and the local evidence must describe the same operation.
    if current is not None and marker is not None:
        marker_operation = str(marker.get("operation_id") or "")
        recorded_operation = str(current.get("operation_id") or "")
        if marker_operation and recorded_operation and marker_operation != recorded_operation:
            raise AlgorithmCutoverError(
                "ALGORITHM_MAINTENANCE_OPERATION_MISMATCH",
                "the transition marker belongs to another maintenance operation",
                detail=f"record={recorded_operation} marker={marker_operation}",
            )

    # -- marker exists but PostgreSQL never recorded the phase ---------------
    if current is None and marker is not None:
        # The marker is a local file: it is evidence, not a database fact. Only a
        # marker that proves this project, this operation, a legal generation and
        # the expected source/target relationship may be published.
        marker_phase = str(marker.get("phase") or "")
        marker_generation = marker.get("generation")
        if marker_phase not in MAINTENANCE_PHASES:
            result["next_step"] = "marker has an unknown phase; inspect it before acting"
            return result
        if not operation:
            result["next_step"] = "marker has no operation identity; inspect it before acting"
            return result
        if str(marker.get("project_id") or "") != str(project_id):
            result["next_step"] = "marker belongs to another project; inspect it before acting"
            return result
        if not isinstance(marker_generation, int) or int(marker_generation) < 0:
            result["next_step"] = "marker has no legal writer generation; inspect it before acting"
            return result
        if str(marker.get("source_provider") or "") not in (PROVIDER_SQLITE, PROVIDER_POSTGRESQL) or str(
            marker.get("target_provider") or ""
        ) not in (PROVIDER_SQLITE, PROVIDER_POSTGRESQL):
            result["next_step"] = "marker does not name a legal provider pair; inspect it"
            return result
        if str(marker.get("source_provider")) == str(marker.get("target_provider")):
            result["next_step"] = "marker names the same source and target; inspect it"
            return result
        if durable_provider == PROVIDER_POSTGRESQL and not revoked and marker_phase != MAINTENANCE_SWITCHING:
            result["next_step"] = (
                "PostgreSQL is already authoritative; the marker cannot be "
                "replayed as a pre-switch phase"
            )
            return result
        _set_maintenance(
            connection, project_id, dict(marker),
            expected_generation=int(marker_generation),
        )
        result.update(applied=True, phase=str(marker.get("phase")), write_blocked=True)
        result["next_step"] = _recovery_next_step(str(marker.get("phase")), durable_provider, revoked)
        return result

    if current is None:
        result["next_step"] = "no maintenance window is recorded for this project"
        return result
    if not operation:
        result["next_step"] = "maintenance window has no operation identity; inspect it"
        return result

    # -- an unfinished switch resumes from its recorded phase ----------------
    if str(current.get("phase")) in (
        MAINTENANCE_QUIESCING, MAINTENANCE_SOURCE_FROZEN, MAINTENANCE_VERIFIED,
    ):
        # The audit identity is the window's own, or the caller's explicit one;
        # it is resolved for every phase that can reach the switch, not only the
        # frozen one (a VERIFIED window resumes straight into the switch).
        stored_operator = str(current.get("operator") or "").strip()
        stored_reason = str(current.get("reason") or "").strip()
        effective_operator = str(operator or stored_operator).strip()
        effective_reason = str(reason or stored_reason).strip()
        if not effective_operator or not effective_reason:
            result["next_step"] = (
                "the window has no recorded operator/reason; supply them explicitly"
            )
            return result
        if durable_provider == PROVIDER_POSTGRESQL and not revoked:
            # PostgreSQL already owns the writer slot: re-importing straight into
            # it would bypass the provider's write gate. Finish the local side
            # instead of touching business data.
            result["next_step"] = (
                "PostgreSQL is already authoritative; recover the recorded phase "
                "without importing again"
            )
            return result
        if str(current.get("phase")) == MAINTENANCE_QUIESCING:
            current = freeze_maintenance_source(
                connection, project_id=project_id, db_path=db_path, operation_id=operation,
            )
        if str(current.get("phase")) == MAINTENANCE_SOURCE_FROZEN:
            from .algorithm_migration import build_report, import_snapshot

            # The frozen *content* is the identity a recovery may replay. Older
            # records stored it in snapshot_digest (before the fields were split),
            # so a record without content_digest still proves the same content.
            frozen_content = str(
                current.get("content_digest") or current.get("snapshot_digest") or ""
            )
            frozen_revision = current.get("source_revision")
            final_snapshot = export_source_snapshot(db_path, project_id)
            # Recovery may only replay the *frozen* source. A source that moved
            # after the freeze is a different dataset and must stay blocked.
            if not frozen_content or content_digest(final_snapshot) != frozen_content:
                result["next_step"] = (
                    "the source changed after the freeze; the window stays blocked"
                )
                return result
            recorded = _import_run(connection, project_id=project_id, run_id=operation)
            if recorded is not None:
                recorded_status = str(recorded.get("status") or "")
                if recorded_status == "RUNNING":
                    result["next_step"] = (
                        "an import attempt for this operation is still running; "
                        "refusing a concurrent takeover"
                    )
                    return result
                if (
                    str(recorded.get("content_digest") or "") != frozen_content
                    # A revision of 0 is a valid revision: only a missing value
                    # is treated as unknown, never "0 or -1".
                    or recorded.get("algorithm_revision") is None
                    or int(recorded.get("algorithm_revision"))
                    != int(final_snapshot["algorithm_revision"])
                    or (
                        frozen_revision is not None
                        and int(recorded.get("algorithm_revision")) != int(frozen_revision)
                    )
                ):
                    result["next_step"] = (
                        "the recorded import belongs to different frozen content; "
                        "the window stays blocked"
                    )
                    return result
                if recorded_status == "COMPLETED":
                    # Never re-insert a completed run: prove the target really is
                    # the frozen content and continue with reconciliation.
                    target = export_target_snapshot(connection, project_id)
                    reconciliation = build_report(
                        final_snapshot, target, schema=schema_status(connection),
                    )
                    if reconciliation.get("verdict") != "OK":
                        result["next_step"] = (
                            "the completed import no longer matches the frozen "
                            "source; the window stays blocked"
                        )
                        return result
                    current = verify_maintenance_window(
                        connection, project_id=project_id, operation_id=operation,
                        verification_digest=str(reconciliation["summary_digest"]),
                    )
                else:
                    # FAILED/ABORTED/INVALID: the same run identity is revived,
                    # never replaced by a new id that hides the conflict.
                    import_snapshot(
                        connection, final_snapshot, actor=effective_operator,
                        run_id=operation, resume=True,
                        maintenance_operation=operation,
                    )
            else:
                import_snapshot(
                    connection, final_snapshot, actor=effective_operator,
                    run_id=operation, resume=True,
                    maintenance_operation=operation,
                )
            if str(current.get("phase")) == MAINTENANCE_SOURCE_FROZEN:
                target = export_target_snapshot(connection, project_id)
                reconciliation = build_report(
                    final_snapshot, target, schema=schema_status(connection),
                )
                if reconciliation.get("verdict") != "OK":
                    result["next_step"] = "reconciliation failed; the window stays blocked"
                    return result
                current = verify_maintenance_window(
                    connection, project_id=project_id, operation_id=operation,
                    verification_digest=str(reconciliation["summary_digest"]),
                )
        switched = switch_maintenance_owner(
            connection,
            project_id=project_id,
            db_path=db_path,
            record_path=record_path,
            operation_id=operation,
            expected_generation=int(current.get("generation") or 0),
            operator=effective_operator,
            reason=effective_reason,
            acknowledge_unported=acknowledge_unported,
        )
        result.update(
            applied=True, settled=True, phase=switched["phase"], write_blocked=False,
            admission_path=switched.get("admission_path"),
        )
        return result

    # -- the switch landed in PostgreSQL; finish the local side --------------
    if str(current.get("phase")) == MAINTENANCE_SWITCHING:
        if durable_provider == PROVIDER_POSTGRESQL and not revoked:
            record = _write_local_from_durable(
                connection, project_id=project_id, record_path=record_path,
                operation_id=operation, phase=MAINTENANCE_POSTGRES_ACTIVE,
                durable_phase=MAINTENANCE_SWITCHING,
            )
            _set_maintenance(connection, project_id, _maintenance_record(
                MAINTENANCE_POSTGRES_ACTIVE,
                operation_id=operation,
                project_id=project_id,
                generation=int(record["writer_generation"]),
                source_provider=PROVIDER_POSTGRESQL,
                target_provider=PROVIDER_SQLITE,
                snapshot_digest=str(record.get("snapshot_digest") or ""),
                verification_digest=str(current.get("verification_digest") or ""),
                operator=operator, reason=reason,
            ),
                expected_phase=MAINTENANCE_SWITCHING,
                expected_operation_id=operation,
                expected_generation=int(record["writer_generation"]),
            )
            # The completion contract: the local record must prove the settled
            # durable state before the marker is cleared, otherwise both sides
            # stay blocked (safe direction) instead of unblocking on a guess.
            durable_after = _durable_admission(connection, project_id)
            if not _local_record_matches(
                record_path, project_id=project_id, operation_id=operation,
                phase=MAINTENANCE_POSTGRES_ACTIVE, durable=durable_after,
            ):
                result["next_step"] = (
                    "the republished admission does not prove the durable state; "
                    "the marker is kept"
                )
                return result
            # The durable phase is SWITCHING, but the local barrier may already
            # be settled for the *same* operation (a crash after the settle
            # write). Both phases are the same operation's evidence; any other
            # phase/operation is refused.
            _authority_barrier(
                db_path, project_id=project_id, phase=MAINTENANCE_POSTGRES_ACTIVE,
                operation_id=operation,
                writer_generation=int(record["writer_generation"]),
                admission_id=str(record.get("admission_id") or ""),
                record_path=record_path,
                require_operation=operation,
                allowed_phases=(MAINTENANCE_SWITCHING, MAINTENANCE_POSTGRES_ACTIVE),
                require_existing=True,
            )
            _remove_marker(marker_path, operation)
            result.update(applied=True, settled=True, phase=MAINTENANCE_POSTGRES_ACTIVE,
                          write_blocked=False)
            return result
        # The switch never committed: restore the proven authority.
        restore_phase = (
            MAINTENANCE_POSTGRES_ACTIVE
            if durable_provider == PROVIDER_POSTGRESQL and not revoked
            else MAINTENANCE_SQLITE_ACTIVE
        )
        _set_maintenance(connection, project_id, _maintenance_record(
            restore_phase,
            operation_id=operation, project_id=project_id,
            generation=int(current.get("generation") or 0),
            source_provider=PROVIDER_SQLITE, target_provider=PROVIDER_POSTGRESQL,
            snapshot_digest=str(current.get("snapshot_digest") or ""),
            content_digest=str(current.get("content_digest") or ""),
            source_revision=current.get("source_revision"),
            verification_digest=str(current.get("verification_digest") or ""),
            operator=operator, reason=reason or "switch did not commit",
        ),
            expected_phase=MAINTENANCE_SWITCHING,
            expected_operation_id=operation,
            expected_generation=int(current.get("generation") or 0),
        )
        # The barrier was written as SWITCHING before the admission attempt: if
        # the restore leaves it there, the durable authority says SQLite again but
        # every SQLite write still refuses. Settle the barrier with the same
        # verdict before the marker is cleared.
        _authority_barrier(
            db_path, project_id=project_id, phase=str(restore_phase),
            operation_id=operation,
            writer_generation=int(current.get("generation") or 0),
            record_path=record_path,
            require_operation=operation,
            require_phase=MAINTENANCE_SWITCHING,
        )
        _remove_marker(marker_path, operation)
        result.update(applied=True, settled=True, phase=restore_phase, write_blocked=False)
        return result

    # -- rollback interrupted -------------------------------------------------
    if str(current.get("phase")) == MAINTENANCE_ROLLBACK_QUIESCING:
        if durable_provider == PROVIDER_SQLITE and revoked:
            record = _write_local_from_durable(
                connection, project_id=project_id, record_path=record_path,
                operation_id=operation, phase=MAINTENANCE_ROLLBACK_APPLIED,
                durable_phase=MAINTENANCE_ROLLBACK_QUIESCING,
            )
            _set_maintenance(connection, project_id, _maintenance_record(
                MAINTENANCE_ROLLBACK_APPLIED,
                operation_id=operation, project_id=project_id,
                generation=int(record["writer_generation"]),
                source_provider=PROVIDER_SQLITE, target_provider=PROVIDER_POSTGRESQL,
                snapshot_digest=str(record.get("snapshot_digest") or ""),
                verification_digest=str(current.get("verification_digest") or ""),
                operator=operator, reason=reason,
            ),
                expected_phase=MAINTENANCE_ROLLBACK_QUIESCING,
                expected_operation_id=operation,
                expected_generation=int(record["writer_generation"]),
            )
            durable_after = _durable_admission(connection, project_id)
            if not _local_record_matches(
                record_path, project_id=project_id, operation_id=operation,
                phase=MAINTENANCE_ROLLBACK_APPLIED, durable=durable_after,
            ):
                result["next_step"] = (
                    "the republished admission does not prove the revoked "
                    "authority; the marker is kept"
                )
                return result
            _authority_barrier(
                db_path, project_id=project_id, phase=MAINTENANCE_ROLLBACK_APPLIED,
                operation_id=operation,
                writer_generation=int(record["writer_generation"]),
                admission_id=str(record.get("admission_id") or ""),
                record_path=record_path,
                require_phase=MAINTENANCE_POSTGRES_ACTIVE,
            )
            _remove_marker(marker_path, operation)
            result.update(applied=True, settled=True, phase=MAINTENANCE_ROLLBACK_APPLIED,
                          write_blocked=False)
            return result
        effective_operator = str(operator or current.get("operator") or "").strip()
        effective_reason = str(reason or current.get("reason") or "").strip()
        if not effective_operator or not effective_reason:
            result["next_step"] = (
                "the window has no recorded operator/reason; supply them explicitly"
            )
            return result
        rolled = rollback(
            connection,
            db_path=db_path,
            admission_path=record_path,
            confirmed=True,
            operator=effective_operator,
            reason=effective_reason,
        )
        result.update(
            applied=bool(rolled.get("rolled_back")),
            settled=bool(rolled.get("rolled_back")),
            phase=(rolled.get("phase") if rolled.get("rolled_back") else current.get("phase")),
            write_blocked=not rolled.get("rolled_back"),
        )
        result["rollback"] = {key: rolled.get(key) for key in ("rolled_back",)}
        return result

    # -- settled window: prove it and clear only its own marker --------------
    if str(current.get("phase")) in SETTLED_MAINTENANCE_PHASES:
        phase_now = str(current.get("phase"))
        durable = _durable_admission(connection, project_id)
        if not _local_record_matches(
            record_path, project_id=project_id, operation_id=operation,
            phase=phase_now, durable=durable,
        ):
            try:
                _write_local_from_durable(
                    connection, project_id=project_id, record_path=record_path,
                    operation_id=operation, phase=phase_now,
                )
            except AlgorithmCutoverError:
                result["next_step"] = (
                    "the local admission record does not prove the settled provider "
                    "and cannot be republished; the marker is kept"
                )
                return result
        if not _local_record_matches(
            record_path, project_id=project_id, operation_id=operation,
            phase=phase_now, durable=durable,
        ):
            result["next_step"] = "the local admission still disagrees; marker kept"
            return result
        # A settled window re-proves (and heals) the local barrier from the
        # durable state, so a catalog that lost the barrier cannot re-open.
        _authority_barrier(
            db_path, project_id=project_id, phase=phase_now,
            operation_id=operation,
            writer_generation=int((durable or {}).get("writer_generation") or 0),
            admission_id=str((durable or {}).get("admission_id") or ""),
            record_path=record_path,
        )
        if marker is not None:
            _remove_marker(marker_path, operation)
        result.update(applied=True, settled=True, write_blocked=False)
        return result

    result["next_step"] = "unknown phase; inspect the marker and the durable state"
    return result


def _recovery_next_step(phase: str, durable_provider: str, revoked: bool) -> str:
    if phase in (MAINTENANCE_QUIESCING, MAINTENANCE_SOURCE_FROZEN, MAINTENANCE_VERIFIED):
        return "recover_maintenance(apply=True) resumes freeze -> reconcile -> switch"
    if phase == MAINTENANCE_SWITCHING:
        if durable_provider == PROVIDER_POSTGRESQL and not revoked:
            return "recover_maintenance(apply=True) finishes the local admission"
        return "recover_maintenance(apply=True) restores the proven authority"
    if phase == MAINTENANCE_ROLLBACK_QUIESCING:
        return "recover_maintenance(apply=True) resumes or settles the rollback"
    if phase in SETTLED_MAINTENANCE_PHASES:
        return "recover_maintenance(apply=True) clears the settled marker"
    return "inspect: no recognised maintenance phase"

__all__ = [
    "AlgorithmCutoverError",
    "admit_cutover",
    "assess_rollback",
    "cutover_status",
    "evaluate_admission",
    "revoke_admission",
    "rollback",
    "cutover_transition",
    "write_admission_record",
    "MAINTENANCE_PHASES",
    "BLOCKING_MAINTENANCE_PHASES",
    "begin_maintenance_window",
    "freeze_maintenance_source",
    "verify_maintenance_window",
    "switch_maintenance_owner",
    "resume_maintenance",
    "read_maintenance",
    "recover_maintenance",
]
