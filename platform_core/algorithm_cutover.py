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
import tempfile
import uuid
from contextlib import contextmanager
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
    admission_transition_path,
    load_admission_record,
)
from .algorithm_shadow import validate_snapshot


class AlgorithmCutoverError(RuntimeError):
    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


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


def evaluate_admission(
    connection,
    *,
    db_path: str | Path,
    project_id: str,
    expected_generation: int,
    operator: str,
    reason: str,
    acknowledge_unported: bool = False,
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
) -> dict[str, Any]:
    """Atomically flip the project to PostgreSQL when every gate passes."""
    from psycopg.rows import dict_row

    project_id = str(project_id)
    evaluation = evaluate_admission(
        connection,
        db_path=db_path,
        project_id=project_id,
        expected_generation=expected_generation,
        operator=operator,
        reason=reason,
        acknowledge_unported=acknowledge_unported,
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
                "evidence=EXCLUDED.evidence",
                (
                    project_id, PROVIDER_POSTGRESQL,
                    int(report["source"]["revision"]),
                    str(report["source"]["snapshot_digest"]),
                    str(report["source"]["content_digest"]),
                    int(expected_generation) + 1, admission_id,
                    json.dumps(evidence, ensure_ascii=False),
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
def cutover_transition(record_path: str | Path, *, project_id: str, kind: str):
    """Publish a persisted "switch in progress" marker for the whole switch.

    The marker exists from before PostgreSQL commits the new authority until the
    local admission record is durable, so a crash in that window leaves an
    explicit, recoverable state in which neither provider accepts writes. It is
    removed only after the local record has been written.
    """
    marker = admission_transition_path(record_path)
    marker.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema": "algorithm-cutover-transition/1",
        "project_id": str(project_id),
        "kind": str(kind),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "an unresolved cutover blocks both providers; finish or roll back "
            "the cutover, then remove this marker"
        ),
    }
    marker.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        yield marker
    finally:
        try:
            marker.unlink()
        except FileNotFoundError:
            pass


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
    revoked_at = datetime.now(timezone.utc).isoformat()
    require_idle_transaction(connection, purpose="cutover revocation")
    with connection.transaction():
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (f"algorithm-cutover:{project_id}",),
            )
            cursor.execute(
                "SELECT writer_generation,admission_id,evidence FROM "
                "w5_algorithm.cutover_state WHERE project_id=%s FOR UPDATE",
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
            evidence["revocation"] = {
                "operator": str(operator).strip(),
                "reason": str(reason).strip(),
                "assessment": {
                    "allowed": assessment.get("allowed"),
                    "blocking": list(assessment.get("blocking") or []),
                    "conditions": list(assessment.get("conditions") or []),
                },
            }
            cursor.execute(
                "UPDATE w5_algorithm.cutover_state SET authoritative_provider=%s,"
                "writer_generation=writer_generation+1,revoked_at=now(),evidence=%s::jsonb "
                "WHERE project_id=%s",
                (PROVIDER_SQLITE, json.dumps(evidence, ensure_ascii=False), project_id),
            )
    return {
        "contract_version": CONTRACT_VERSION,
        "admission_id": admission_id,
        "project_id": project_id,
        "authoritative_provider": PROVIDER_SQLITE,
        "algorithm_revision": int(assessment.get("admitted_revision") or 0),
        "content_digest": assessment.get("admitted_content_digest"),
        "snapshot_digest": "",
        "writer_generation": int(expected_generation) + 1,
        "admitted_at": None,
        "revoked_at": revoked_at,
        "operator": str(operator).strip(),
        "reason": str(reason).strip(),
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
    """Assess, restore SQLite from the admitted PostgreSQL content, then revoke."""
    admission = load_admission_record(admission_path)
    if admission is None:
        raise AlgorithmCutoverError(
            "ALGORITHM_ROLLBACK_ADMISSION_MISSING",
            "rollback requires the admission record written by cutover-admit",
        )
    project_id = str(admission.get("project_id") or "")
    assessment = assess_rollback(connection, db_path=db_path, admission=admission)
    if not assessment["allowed"]:
        return {"rolled_back": False, "assessment": assessment}
    if not confirmed:
        raise AlgorithmCutoverError(
            "ALGORITHM_ROLLBACK_CONFIRMATION_REQUIRED",
            "reverse restoration requires explicit --confirm",
        )
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
    restored = restore_source_snapshot(
        db_path,
        project_id,
        validate_snapshot(snapshot),
        assessment=assessment,
        confirmed=True,
    )
    revoked = revoke_admission(
        connection,
        project_id=project_id,
        admission_id=str(admission.get("admission_id") or ""),
        expected_generation=int(admission.get("writer_generation") or 0),
        operator=operator,
        reason=reason,
        assessment=assessment,
    )
    record = {
        **revoked,
        "snapshot_digest": str(admission.get("snapshot_digest") or ""),
        "rolled_back_at": datetime.now(timezone.utc).isoformat(),
    }
    write_admission_record(record, admission_path)
    return {
        "rolled_back": True,
        "assessment": assessment,
        "restored": restored,
        "admission": record,
    }


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
]
