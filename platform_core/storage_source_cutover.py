"""Explicit, fenced cutover for the U2 storage-source owner.

The migration tool cannot simply compare an operator snapshot with PostgreSQL and
then write an admission record: the SQLite owner may have changed after the
snapshot was taken, and a writer that started before the record exists could
still commit after it.  The protocol below closes both windows by reusing the
existing pieces instead of introducing a second migration system:

1. take the shared switch lock (the same mutex every SQLite writer takes across
   *authority check -> write*), so no SQLite write can begin or finish inside the
   switch;
2. refuse unknown states (malformed record/marker, marker plus published record);
3. publish a transition marker atomically (both providers then refuse writes);
4. re-export the current SQLite inside the fence and require it to match the
   operator snapshot if one was supplied;
5. import + reconcile + publish the durable cutover row in ONE PostgreSQL
   transaction, so the target can never be admitted half-written;
6. write the admission record atomically with a real monotonic writer
   generation;
7. remove the transition marker; a crash between 6 and 7 leaves both providers
   blocked and ``finish_cutover`` verifies the published state before releasing.

Recovery:

* ``finish_cutover`` - only when a record is published; verifies the durable
  PostgreSQL state and the frozen SQLite copy, then removes the marker.
* ``abort_cutover`` - only when no admission is published; removes the marker so
  SQLite becomes writable again.  PostgreSQL writes stay impossible because they
  require the local admission record.
* anything else stays fail-closed (unknown state, marker plus record, generation
  mismatch).
"""
from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from filelock import Timeout as FileLockTimeout

from .storage.source_repository import (
    CONTRACT_VERSION,
    DEFAULT_SCOPE,
    PROVIDER_POSTGRESQL,
    StorageSourceAdmissionRequired,
    _refuse_stale_sqlite,
    admission_record_path,
    admission_transition_path,
    load_storage_source_admission_record,
    storage_source_switch_lock,
)
from .storage_source_migration import (
    StorageSourceMigrationError,
    export_snapshot,
    export_target_snapshot,
    import_snapshot,
    reconcile,
)
from .storage_source_postgres_schema import SCHEMA_NAME

TRANSITION_CONTRACT_VERSION = "storage-source-cutover-transition-v1"
PHASE_SWITCHING = "SWITCHING"
PHASE_POSTGRES_ACTIVE = "POSTGRES_ACTIVE"
PHASE_ROLLBACK_APPLIED = "ROLLBACK_APPLIED"

STATE_SQLITE = "STEADY_SQLITE"
STATE_POSTGRES = "STEADY_POSTGRES"
STATE_SWITCHING = "SWITCHING"
STATE_INCONSISTENT = "INCONSISTENT"


class StorageSourceCutoverError(StorageSourceAdmissionRequired):
    """Cutover failure that must leave both providers blocked."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        temporary.write_text(
            json.dumps(dict(payload), ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def read_transition(record_path: str | Path) -> dict[str, Any] | None:
    """Read the transition marker; a malformed marker is refused, not ignored."""
    target = admission_transition_path(record_path)
    if not target.is_file():
        return None
    try:
        value = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_TRANSITION_INVALID",
            "the cutover transition marker cannot be read",
            detail=str(error),
        ) from error
    if not isinstance(value, dict):
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_TRANSITION_INVALID",
            "the cutover transition marker is not an object",
        )
    if str(value.get("contract_version") or "") != TRANSITION_CONTRACT_VERSION:
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_TRANSITION_INVALID",
            "the cutover transition marker contract does not match this tool",
            detail=f"contract={value.get('contract_version')!r}",
        )
    phase = str(value.get("phase") or "")
    if phase not in (PHASE_SWITCHING, PHASE_POSTGRES_ACTIVE):
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_TRANSITION_INVALID",
            "the cutover transition marker has an unknown phase",
            detail=f"phase={phase!r}",
        )
    return value


def cutover_status(sqlite_path: str | Path) -> dict[str, Any]:
    """Classify the current local state (never guesses).

    A record whose provider cannot be validated is ``INCONSISTENT``: the tool must
    be able to report the broken state, while every writer still refuses it (the
    loader raises for them).
    """
    record_path = admission_record_path(sqlite_path)
    record_error: dict[str, Any] | None = None
    record: dict[str, Any] | None = None
    try:
        record = load_storage_source_admission_record(record_path)
    except StorageSourceAdmissionRequired as error:
        record_error = {"code": error.code, "detail": error.detail}
    marker = read_transition(record_path)
    state = STATE_SQLITE
    if record_error is not None:
        state = STATE_INCONSISTENT
    elif marker is not None and record is None:
        state = STATE_SWITCHING
    elif marker is not None and record is not None:
        state = STATE_INCONSISTENT
    elif record is not None and not record.get("revoked_at") and str(
        record.get("authoritative_provider") or ""
    ) == PROVIDER_POSTGRESQL:
        state = STATE_POSTGRES
    return {
        "sqlite_path": str(sqlite_path),
        "admission_record": record,
        "admission_error": record_error,
        "transition": marker,
        "state": state,
        "sqlite_writable": state == STATE_SQLITE,
        "postgres_writable": state == STATE_POSTGRES,
    }


def require_idle_connection(connection, *, purpose: str) -> None:
    """Refuse to run a cutover on a connection with an open transaction.

    Psycopg's ``connection.transaction()`` becomes a SAVEPOINT when a transaction
    is already in progress, so a caller's uncommitted work would make the switch
    "commit" only to a savepoint and publish the local admission before
    PostgreSQL really committed. The tool never silently takes over such a
    connection.
    """
    from psycopg.pq import TransactionStatus

    status = connection.info.transaction_status
    if status != TransactionStatus.IDLE:
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_TRANSACTION_BUSY",
            f"{purpose} requires an idle PostgreSQL connection",
            detail=f"transaction_status={status!r}",
        )


def _lock_cutover_scope(connection, scope: str) -> None:
    """Serialise same-scope switches inside the transaction (advisory lock)."""
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (f"storage_source_cutover:{scope}",),
        )


def _next_generation(connection, scope: str, *, local_generation: int) -> int:
    """Monotonic generation, read inside the switch transaction.

    The advisory lock above serialises concurrent admits for this scope, so the
    read and the ``cutover_state`` write cannot interleave and two switches can
    never publish the same generation.
    """
    from psycopg.rows import dict_row

    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            f"SELECT writer_generation FROM {SCHEMA_NAME}.cutover_state WHERE scope=%s",
            (scope,),
        )
        row = cursor.fetchone()
    durable = int(row["writer_generation"]) if row else 0
    return max(int(local_generation), durable) + 1


def _require_clean_source(
    sqlite_path: str | Path, *, state: Mapping[str, Any]
) -> None:
    """Only a SQLite-authoritative, marker-free project can be switched."""
    if str(state.get("state") or "") == STATE_INCONSISTENT and state.get("admission_error"):
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
            "the local admission record is not a valid authority record",
            detail=json.dumps(state.get("admission_error"), ensure_ascii=False),
        )
    marker = state["transition"]
    record = state["admission_record"]
    if marker is not None:
        phase = str(marker.get("phase") or "")
        if phase == PHASE_SWITCHING and record is None:
            # Resume the same operation (the marker is the durable intent).
            return
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
            "a cutover is already in an unrecoverable phase",
            detail=f"phase={phase!r} record_published={record is not None}",
        )
    if record is not None and not record.get("revoked_at"):
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_ALREADY_ADMITTED",
            "PostgreSQL already owns this storage-source scope",
            detail=f"admission_id={record.get('admission_id')!r}",
        )


def admit_cutover(
    connection,
    sqlite_path: str | Path,
    *,
    scope: str = DEFAULT_SCOPE,
    operator: str,
    reason: str,
    expected_source_digest: str | None = None,
) -> dict[str, Any]:
    """Publish PostgreSQL as the storage-source writer under the switch fence."""
    if not str(operator).strip() or not str(reason).strip():
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_AUDIT_REQUIRED",
            "operator and reason are required for the audit trail",
        )
    record_path = admission_record_path(sqlite_path)
    owner = Path(sqlite_path)
    # The switch is its own top-level PostgreSQL transaction. A caller that
    # already opened one would turn ``connection.transaction()`` into a SAVEPOINT
    # and the local admission could then be published before PostgreSQL really
    # committed, so an unfinished caller transaction is refused, never adopted.
    require_idle_connection(connection, purpose="storage-source cutover admission")
    try:
        # Canonical lock identity: the SQLite writers hold the same lock (they
        # pass the database path, this tool passes the owner path).
        with storage_source_switch_lock(owner, timeout=60):
            require_idle_connection(connection, purpose="storage-source cutover admission")
            state = cutover_status(owner)
            _require_clean_source(owner, state=state)
            existing_marker = state["transition"]
            record = state["admission_record"]
            operation_id = str(
                (existing_marker or {}).get("operation_id") or uuid.uuid4().hex
            )
            local_generation = int((record or {}).get("writer_generation") or 0)
            marker = {
                "contract_version": TRANSITION_CONTRACT_VERSION,
                "operation_id": operation_id,
                "scope": str(scope),
                "phase": PHASE_SWITCHING,
                "started_at": (existing_marker or {}).get("started_at") or _now(),
                "operator": str(operator).strip(),
                "reason": str(reason).strip(),
                "previous_admission_id": str(
                    (record or {}).get("admission_id") or ""
                ),
            }
            _write_json_atomic(admission_transition_path(record_path), marker)
            # Recovery depends on whether PostgreSQL really committed: before
            # the commit nothing durable exists (the marker may be removed);
            # after it, the marker must stay and finish/abort resolves the state.
            durable_committed = False
            try:
                # Writers are now blocked. Re-export the *current* SQLite copy:
                # an operator snapshot may be older than the switch fence.
                snapshot = export_snapshot(owner, scope)
                if expected_source_digest and str(snapshot["content_digest"]) != str(
                    expected_source_digest
                ):
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_CUTOVER_SOURCE_CHANGED",
                        "SQLite changed after the operator snapshot was taken",
                        detail=(
                            f"expected={expected_source_digest} "
                            f"current={snapshot['content_digest']}"
                        ),
                    )
                admission_id = str(uuid.uuid4().hex)
                # ONE real top-level transaction: scope lock, generation, import,
                # reconcile and the durable cutover row commit together, or none
                # of them does.
                with connection.transaction():
                    _lock_cutover_scope(connection, scope)
                    generation = _next_generation(
                        connection, scope, local_generation=local_generation
                    )
                    marker["writer_generation"] = generation
                    _write_json_atomic(admission_transition_path(record_path), marker)
                    import_snapshot(connection, snapshot)
                    target = export_target_snapshot(connection, scope)
                    report = reconcile(snapshot, target)
                    if not report["same"]:
                        raise StorageSourceCutoverError(
                            "STORAGE_SOURCE_CUTOVER_TARGET_MISMATCH",
                            "PostgreSQL does not reconcile with the current SQLite copy",
                            detail=json.dumps(
                                report["blocking_findings"], ensure_ascii=False
                            ),
                        )
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"INSERT INTO {SCHEMA_NAME}.cutover_state"
                            "(scope,admission_id,writer_generation,phase,source_digest,"
                            "target_digest,operation_id,admitted_at,updated_at) "
                            "VALUES(%s,%s,%s,%s,%s,%s,%s,now(),now()) "
                            "ON CONFLICT (scope) DO UPDATE SET "
                            "admission_id=EXCLUDED.admission_id,"
                            "writer_generation=EXCLUDED.writer_generation,"
                            "phase=EXCLUDED.phase,"
                            "source_digest=EXCLUDED.source_digest,"
                            "target_digest=EXCLUDED.target_digest,"
                            "operation_id=EXCLUDED.operation_id,"
                            "admitted_at=now(),updated_at=now()",
                            (
                                scope,
                                admission_id,
                                generation,
                                PHASE_POSTGRES_ACTIVE,
                                str(snapshot["content_digest"]),
                                str(target["content_digest"]),
                                operation_id,
                            ),
                        )
                # The transaction committed for real (no savepoint, verified by the
                # transaction status) before the local admission may exist.
                require_idle_connection(
                    connection, purpose="storage-source cutover admission"
                )
                durable_committed = True
                admission = {
                    "contract_version": CONTRACT_VERSION,
                    "admission_id": admission_id,
                    "scope": str(scope),
                    "authoritative_provider": PROVIDER_POSTGRESQL,
                    "source_count": int(snapshot["counts"]["sources"]),
                    "content_digest": str(snapshot["content_digest"]),
                    "target_digest": str(target["content_digest"]),
                    "writer_generation": generation,
                    "operation_id": operation_id,
                    "previous_admission_id": marker["previous_admission_id"],
                    "admitted_at": _now(),
                    "revoked_at": None,
                    "operator": str(operator).strip(),
                    "reason": str(reason).strip(),
                }
                # PostgreSQL committed: publish the local record atomically, then
                # release the marker. A crash in between leaves both providers
                # blocked until finish_cutover proves the published state.
                _write_json_atomic(record_path, admission)
                _write_json_atomic(
                    admission_transition_path(record_path),
                    {**marker, "phase": PHASE_POSTGRES_ACTIVE},
                )
                admission_transition_path(record_path).unlink(missing_ok=True)
            except BaseException:
                if not durable_committed:
                    # Nothing was published locally *and* PostgreSQL rolled back:
                    # the marker is removed so SQLite stays writable, while
                    # PostgreSQL writes still require a local admission record.
                    if not record_path.is_file():
                        try:
                            admission_transition_path(record_path).unlink(missing_ok=True)
                        except OSError:
                            pass
                # After a durable commit the marker is deliberately kept: both
                # providers stay blocked until finish_cutover (record published)
                # or abort_cutover (record not published) proves the state.
                raise
    except FileLockTimeout as error:
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_BUSY",
            "a storage-source write is in progress; retry the switch",
        ) from error
    return {
        "admitted": True,
        "admission_id": admission_id,
        "writer_generation": generation,
        "operation_id": operation_id,
        "source_digest": str(snapshot["content_digest"]),
        "target_digest": str(target["content_digest"]),
        "record": str(record_path),
    }


def finish_cutover(connection, sqlite_path: str | Path) -> dict[str, Any]:
    """Release a published but unresolved transition after proving its state."""
    record_path = admission_record_path(sqlite_path)
    owner = Path(sqlite_path)
    require_idle_connection(connection, purpose="storage-source cutover finish")
    try:
        # Same canonical lock as the SQLite writers and admit_cutover.
        with storage_source_switch_lock(owner, timeout=60):
            record = load_storage_source_admission_record(record_path)
            marker = read_transition(record_path)
            if record is None:
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_NOT_ADMITTED",
                    "no admission record is published; use abort for a failed switch",
                )
            if marker is None:
                return {"finished": False, "reason": "no unresolved transition"}
            if record.get("revoked_at"):
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                    "the admission was revoked while a transition marker remained",
                )
            if str(marker.get("operation_id") or "") != str(
                record.get("operation_id") or ""
            ):
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                    "the transition marker belongs to another operation",
                    detail=(
                        f"marker={marker.get('operation_id')!r} "
                        f"record={record.get('operation_id')!r}"
                    ),
                )
            scope = str(record.get("scope") or DEFAULT_SCOPE)
            # Verification reads inside one explicit transaction: the durable row
            # is locked and the target digest is read from the same snapshot.
            with connection.transaction():
                _lock_cutover_scope(connection, scope)
                from psycopg.rows import dict_row

                with connection.cursor(row_factory=dict_row) as cursor:
                    cursor.execute(
                        f"SELECT admission_id,writer_generation,phase,source_digest,"
                        f"target_digest FROM {SCHEMA_NAME}.cutover_state "
                        "WHERE scope=%s FOR UPDATE",
                        (scope,),
                    )
                    row = cursor.fetchone()
                if not row:
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                        "the durable cutover state is missing",
                    )
                if (
                    str(row["admission_id"]) != str(record.get("admission_id") or "")
                    or int(row["writer_generation"])
                    != int(record.get("writer_generation") or 0)
                    or str(row["phase"]) != PHASE_POSTGRES_ACTIVE
                ):
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                        "the durable cutover state does not match the admission record",
                    )
                target = export_target_snapshot(connection, scope)
                if str(target["content_digest"]) != str(row["target_digest"]):
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_CUTOVER_TARGET_CHANGED",
                        "PostgreSQL changed while the transition was unresolved",
                        detail=(
                            f"durable={row['target_digest']} "
                            f"current={target['content_digest']}"
                        ),
                    )
                if str(target["content_digest"]) != str(
                    record.get("content_digest") or ""
                ):
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_CUTOVER_TARGET_CHANGED",
                        "the published admission does not describe the current target",
                    )
            require_idle_connection(connection, purpose="storage-source cutover finish")
            # The frozen SQLite copy must still be the admitted source.
            current_source = export_snapshot(owner, scope)
            if str(current_source["content_digest"]) != str(
                record.get("content_digest") or ""
            ):
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_SOURCE_CHANGED",
                    "the frozen SQLite copy diverged from the admitted source",
                )
            admission_transition_path(record_path).unlink(missing_ok=True)
    except FileLockTimeout as error:
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_BUSY",
            "a storage-source write is in progress; retry finish",
        ) from error
    return {"finished": True, "admission_id": record["admission_id"]}


def abort_cutover(sqlite_path: str | Path) -> dict[str, Any]:
    """Abort a switch that never published an admission (SQLite stays/writable).

    This only releases the local marker: it is **not** a PostgreSQL rollback. Rows
    an interrupted switch already committed stay in the target database; they are
    inert while no admission record exists (the provider refuses writes) and a
    later admission re-imports and re-reconciles them. The result therefore reports
    ``target_may_hold_unadmitted_rows``.
    """
    record_path = admission_record_path(sqlite_path)
    owner = Path(sqlite_path)
    try:
        # Same canonical lock as the SQLite writers and admit_cutover.
        with storage_source_switch_lock(owner, timeout=60):
            record = load_storage_source_admission_record(record_path)
            if record is not None and not record.get("revoked_at") and str(
                record.get("authoritative_provider") or ""
            ) == PROVIDER_POSTGRESQL:
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_ALREADY_ADMITTED",
                    "an admission is published; a verified rollback is required",
                    detail=f"admission_id={record.get('admission_id')!r}",
                )
            marker = read_transition(record_path)
            if marker is None:
                return {"aborted": False, "reason": "no transition marker"}
            admission_transition_path(record_path).unlink(missing_ok=True)
    except FileLockTimeout as error:
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_BUSY",
            "a storage-source write is in progress; retry abort",
        ) from error
    return {
        "aborted": True,
        "operation_id": marker.get("operation_id"),
        "target_may_hold_unadmitted_rows": True,
    }


def summarize_error(error: BaseException) -> dict[str, Any]:
    """CLI-friendly, stable error rendering."""
    if isinstance(error, (StorageSourceCutoverError, StorageSourceAdmissionRequired)):
        return {"code": error.code, "detail": error.detail}
    if isinstance(error, StorageSourceMigrationError):
        return {"code": error.code, "detail": error.detail}
    return {"code": type(error).__name__, "detail": str(error)}
