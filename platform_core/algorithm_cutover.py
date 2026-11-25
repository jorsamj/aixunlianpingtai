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
    return (
        str(record.get("project_id") or "") == str(project_id)
        and str(record.get("authoritative_provider") or "") == str(provider)
        and not record.get("revoked_at")
    )


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
    _set_maintenance(connection, project_id, quiescing)

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
    revoked = revoke_admission(
        connection,
        project_id=project_id,
        admission_id=str(admission.get("admission_id") or ""),
        expected_generation=int(admission.get("writer_generation") or 0),
        operator=operator,
        reason=reason,
        assessment=assessment,
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
    _set_maintenance(connection, project_id, applied)
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
    operator: str = "",
    reason: str = "",
) -> dict[str, Any]:
    """One immutable phase record: the identity a phase is allowed to act on."""
    return {
        "schema": MAINTENANCE_SCHEMA,
        "phase": str(phase),
        "operation_id": str(operation_id),
        "project_id": str(project_id),
        "generation": int(generation),
        "source_provider": str(source_provider),
        "target_provider": str(target_provider),
        "snapshot_digest": str(snapshot_digest or ""),
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


def _set_maintenance(connection, project_id: str, record: Mapping[str, Any]) -> dict[str, Any]:
    """Persist one phase under the cutover advisory lock + row lock.

    The phase lives in ``cutover_state.evidence`` so it survives this
    transaction: a later writer cannot assume a transaction-scoped lock still
    protects it.
    """
    from psycopg.rows import dict_row

    require_current_schema(connection)
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
            exists = cursor.fetchone() is not None
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
        raise AlgorithmCutoverError(
            "ALGORITHM_MAINTENANCE_IN_PROGRESS",
            "an algorithm maintenance window is already open for this project",
            detail=f"operation={current.get('operation_id')} phase={current.get('phase')}",
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
        _set_maintenance(connection, project_id, record)
    except BaseException:
        try:
            _remove_marker(marker, operation)
        finally:
            raise
    return {"operation_id": operation, "phase": MAINTENANCE_QUIESCING,
            "previous_phase": previous_phase, "marker": str(marker),
            "write_blocked": True}


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
        snapshot_digest=digest,
        operator=str(current.get("operator") or ""),
        reason=str(current.get("reason") or ""),
    )
    return _set_maintenance(connection, project_id, record)


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
        verification_digest=str(verification_digest or ""),
        operator=str(current.get("operator") or ""),
        reason=str(current.get("reason") or ""),
    )
    return _set_maintenance(connection, project_id, record)


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
        verification_digest=str(current.get("verification_digest") or ""),
        operator=operator, reason=reason,
    )
    _set_maintenance(connection, project_id, switching)
    admitted = admit_cutover(
        connection,
        db_path=db_path,
        project_id=project_id,
        expected_generation=int(expected_generation),
        operator=operator,
        reason=reason,
        acknowledge_unported=acknowledge_unported,
        previous_report=previous_report,
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
            verification_digest=str(current.get("verification_digest") or ""),
            operator=operator, reason=reason,
        )
        _set_maintenance(connection, project_id, restore)
        _remove_marker(admission_transition_path(record_path), operation_id)
        raise AlgorithmCutoverError(
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
        verification_digest=str(current.get("verification_digest") or ""),
        operator=operator, reason=reason,
    )
    admission = dict(admitted["admission"])
    admission["operation_id"] = operation_id
    admission["maintenance_phase"] = MAINTENANCE_POSTGRES_ACTIVE
    path = write_admission_record(admission, record_path)
    _set_maintenance(connection, project_id, settled)
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
            MAINTENANCE_SWITCHING: "switch_maintenance_owner (re-run; admission was refused)",
            MAINTENANCE_ROLLBACK_QUIESCING: "rollback (re-run; PG writes stay blocked)",
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
]
