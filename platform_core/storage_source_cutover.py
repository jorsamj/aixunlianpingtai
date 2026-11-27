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
    import_snapshot_sqlite,
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
    if (
        record is not None
        and not record.get("revoked_at")
        and str(record.get("authoritative_provider") or "") == PROVIDER_POSTGRESQL
    ):
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


def rollback_cutover(
    connection,
    sqlite_path: str | Path,
    *,
    operator: str,
    reason: str,
    expected_target_digest: str | None = None,
) -> dict[str, Any]:
    """Reverse cutover: publish the *current* PostgreSQL state back into SQLite.

    A rollback is not "switch back to the old SQLite file": PostgreSQL may have
    created, updated or deleted sources after the cutover. The protocol therefore
    freezes both sides, exports PostgreSQL as the authoritative snapshot, imports
    it into SQLite in one transaction, reconciles the result, publishes a durable
    ``ROLLBACK_APPLIED`` row, then the local SQLite admission, and only then
    releases the transition marker.

    Refusals (all fail-closed, local state unchanged or fully recoverable):

    * the local record is not a published PostgreSQL admission;
    * the durable cutover row is missing or does not match the record;
    * PostgreSQL's snapshot does not match the operator's expectation;
    * SQLite holds a row newer than PostgreSQL (the local copy kept writing);
    * the post-import SQLite copy does not reconcile with the snapshot.
    """
    if not str(operator).strip() or not str(reason).strip():
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_AUDIT_REQUIRED",
            "operator and reason are required for the audit trail",
        )
    owner = Path(sqlite_path)
    record_path = admission_record_path(owner)
    require_idle_connection(connection, purpose="storage-source rollback")
    try:
        with storage_source_switch_lock(owner, timeout=60):
            require_idle_connection(connection, purpose="storage-source rollback")
            state = cutover_status(owner)
            if state["state"] != STATE_POSTGRES:
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_ROLLBACK_REQUIRES_POSTGRES_AUTHORITY",
                    "a rollback needs a published PostgreSQL admission",
                    detail=f"state={state['state']!r}",
                )
            record = state["admission_record"]
            scope = str(record.get("scope") or DEFAULT_SCOPE)
            operation_id = uuid.uuid4().hex
            marker = {
                "contract_version": TRANSITION_CONTRACT_VERSION,
                "operation_id": operation_id,
                "scope": scope,
                "phase": PHASE_SWITCHING,
                "started_at": _now(),
                "operator": str(operator).strip(),
                "reason": str(reason).strip(),
                "previous_admission_id": str(record.get("admission_id") or ""),
                "direction": "ROLLBACK",
            }
            _write_json_atomic(admission_transition_path(record_path), marker)
            durable_frozen = False
            durable_rollback = False
            try:
                # Freeze PostgreSQL durably: the provider refuses a non-writable
                # phase, and the FOR UPDATE wait makes an in-flight writer finish
                # before the export starts.
                with connection.transaction():
                    _lock_cutover_scope(connection, scope)
                    from psycopg.rows import dict_row

                    with connection.cursor(row_factory=dict_row) as cursor:
                        cursor.execute(
                            f"SELECT admission_id,writer_generation,phase "
                            f"FROM {SCHEMA_NAME}.cutover_state WHERE scope=%s FOR UPDATE",
                            (scope,),
                        )
                        row = cursor.fetchone()
                    if not row or str(row["phase"]) != PHASE_POSTGRES_ACTIVE:
                        raise StorageSourceCutoverError(
                            "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                            "the durable cutover state is not an active PostgreSQL switch",
                        )
                    if (
                        str(row["admission_id"]) != str(record.get("admission_id") or "")
                        or int(row["writer_generation"])
                        != int(record.get("writer_generation") or 0)
                    ):
                        raise StorageSourceCutoverError(
                            "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                            "the durable cutover state does not match the admission record",
                        )
                    with connection.cursor() as cursor:
                        # Identity-conditioned: only the exact published forward
                        # operation may be frozen. A different operation's row is
                        # never silently taken over.
                        cursor.execute(
                            f"UPDATE {SCHEMA_NAME}.cutover_state SET phase=%s, "
                            "updated_at=now() WHERE scope=%s AND admission_id=%s "
                            "AND writer_generation=%s AND phase=%s",
                            (
                                PHASE_SWITCHING,
                                scope,
                                str(record.get("admission_id") or ""),
                                int(record.get("writer_generation") or 0),
                                PHASE_POSTGRES_ACTIVE,
                            ),
                        )
                        if cursor.rowcount != 1:
                            raise StorageSourceCutoverError(
                                "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                                "the durable cutover state was replaced during the rollback",
                            )
                durable_frozen = True
                # A read inside its own transaction: an implicit transaction here
                # would turn the later cutover_state update into a SAVEPOINT.
                with connection.transaction():
                    _lock_cutover_scope(connection, scope)
                    snapshot = export_target_snapshot(connection, scope)
                require_idle_connection(connection, purpose="storage-source rollback")
                if expected_target_digest and str(snapshot["content_digest"]) != str(
                    expected_target_digest
                ):
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_ROLLBACK_TARGET_CHANGED",
                        "PostgreSQL changed after the operator snapshot was taken",
                        detail=(
                            f"expected={expected_target_digest} "
                            f"current={snapshot['content_digest']}"
                        ),
                    )
                imported = import_snapshot_sqlite(owner, snapshot)
                current = export_snapshot(owner, scope)
                report = reconcile(snapshot, current)
                if not report["same"]:
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_ROLLBACK_TARGET_MISMATCH",
                        "SQLite does not reconcile with the PostgreSQL snapshot",
                        detail=json.dumps(report["blocking_findings"], ensure_ascii=False),
                    )
                generation = int(record.get("writer_generation") or 0) + 1
                admission_id = uuid.uuid4().hex
                marker["writer_generation"] = generation
                _write_json_atomic(admission_transition_path(record_path), marker)
                with connection.transaction():
                    _lock_cutover_scope(connection, scope)
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"UPDATE {SCHEMA_NAME}.cutover_state SET "
                            "admission_id=%s, writer_generation=%s, phase=%s, "
                            "source_digest=%s, target_digest=%s, operation_id=%s, "
                            "updated_at=now() WHERE scope=%s AND admission_id=%s "
                            "AND writer_generation=%s AND phase=%s",
                            (
                                admission_id,
                                generation,
                                PHASE_ROLLBACK_APPLIED,
                                str(snapshot["content_digest"]),
                                str(current["content_digest"]),
                                operation_id,
                                scope,
                                str(record.get("admission_id") or ""),
                                int(record.get("writer_generation") or 0),
                                PHASE_SWITCHING,
                            ),
                        )
                        if cursor.rowcount != 1:
                            raise StorageSourceCutoverError(
                                "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                                "the frozen cutover state changed before the rollback could publish",
                            )
                durable_rollback = True
                require_idle_connection(connection, purpose="storage-source rollback")
                admission = {
                    "contract_version": CONTRACT_VERSION,
                    "admission_id": admission_id,
                    "scope": scope,
                    "authoritative_provider": "sqlite",
                    "source_count": int(current["counts"]["sources"]),
                    "content_digest": str(current["content_digest"]),
                    "target_digest": str(current["content_digest"]),
                    "writer_generation": generation,
                    "operation_id": operation_id,
                    "previous_admission_id": str(record.get("admission_id") or ""),
                    "admitted_at": _now(),
                    "revoked_at": None,
                    "operator": str(operator).strip(),
                    "reason": str(reason).strip(),
                }
                _write_json_atomic(record_path, admission)
                admission_transition_path(record_path).unlink(missing_ok=True)
            except BaseException:
                if durable_rollback:
                    # The durable rollback is published and SQLite already holds
                    # the imported data: keep the marker so both providers stay
                    # blocked until finish_cutover proves the state.
                    raise
                if durable_frozen:
                    # Restore PostgreSQL authority: the rollback never completed,
                    # so the forward switch is still the truth. Conditioned on the
                    # same forward identity we froze.
                    try:
                        with connection.transaction():
                            _lock_cutover_scope(connection, scope)
                            with connection.cursor() as cursor:
                                cursor.execute(
                                    f"UPDATE {SCHEMA_NAME}.cutover_state SET "
                                    "phase=%s, updated_at=now() WHERE scope=%s "
                                    "AND admission_id=%s AND writer_generation=%s "
                                    "AND phase=%s",
                                    (
                                        PHASE_POSTGRES_ACTIVE,
                                        scope,
                                        str(record.get("admission_id") or ""),
                                        int(record.get("writer_generation") or 0),
                                        PHASE_SWITCHING,
                                    ),
                                )
                                if cursor.rowcount != 1:
                                    raise StorageSourceCutoverError(
                                        "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                                        "the frozen cutover state changed; keep the marker",
                                    )
                    except Exception:
                        # Unprovable: keep the marker (both sides blocked).
                        raise
                admission_transition_path(record_path).unlink(missing_ok=True)
                raise
    except FileLockTimeout as error:
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_BUSY",
            "a storage-source write is in progress; retry the rollback",
        ) from error
    return {
        "rolled_back": True,
        "admission_id": admission_id,
        "writer_generation": generation,
        "operation_id": operation_id,
        "source_digest": str(snapshot["content_digest"]),
        "target_digest": str(current["content_digest"]),
        "imported": imported,
        "record": str(record_path),
    }


def _durable_row_for_update(connection, scope: str):
    from psycopg.rows import dict_row

    with connection.transaction():
        _lock_cutover_scope(connection, scope)
        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                f"SELECT admission_id,writer_generation,phase,source_digest,"
                f"target_digest,operation_id FROM {SCHEMA_NAME}.cutover_state "
                "WHERE scope=%s FOR UPDATE",
                (scope,),
            )
            return cursor.fetchone()


def _finish_rollback(
    connection, owner: Path, record_path: Path, record: Mapping[str, Any], durable: Mapping[str, Any], scope: str
) -> dict[str, Any]:
    """Complete a rollback whose durable state is published but local isn't.

    The whole recovery is an *identity chain*, not a digest comparison: the marker
    must be the rollback operation that wrote this durable row, the local record
    must be either that operation's predecessor (still the forward admission) or
    the operation's own published result, and the SQLite copy must be the exact
    target the durable row froze. A matching target digest alone is never enough to
    publish a new authority record.
    """
    marker = read_transition(record_path)
    if marker is None:
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
            "the transition marker disappeared before the rollback could be finished",
        )
    if str(marker.get("direction") or "") != "ROLLBACK":
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
            "the marker is not the rollback that produced this durable state",
            detail=f"direction={marker.get('direction')!r}",
        )
    if str(marker.get("scope") or "") != scope or str(durable["operation_id"]) != str(
        marker.get("operation_id") or ""
    ):
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
            "the marker does not own this durable rollback",
            detail=(
                f"marker={marker.get('operation_id')!r} "
                f"durable={durable.get('operation_id')!r}"
            ),
        )
    if marker.get("writer_generation") is not None and int(
        marker["writer_generation"]
    ) != int(durable["writer_generation"]):
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
            "the marker generation does not match the durable rollback generation",
        )
    previous_admission_id = str(marker.get("previous_admission_id") or "")
    record_admission_id = str(record.get("admission_id") or "")
    published = (
        str(record.get("authoritative_provider") or "") == "sqlite"
        and record_admission_id == str(durable["admission_id"])
        and str(record.get("operation_id") or "") == str(durable["operation_id"])
        and int(record.get("writer_generation") or 0) == int(durable["writer_generation"])
    )
    predecessor = (
        str(record.get("authoritative_provider") or "") == PROVIDER_POSTGRESQL
        and record_admission_id == previous_admission_id
        and str(record.get("operation_id") or "") != str(durable["operation_id"])
    )
    if not (published or predecessor):
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
            "the local admission record is neither this rollback nor its predecessor",
            detail=(
                f"record={record_admission_id!r} provider={record.get('authoritative_provider')!r} "
                f"previous={previous_admission_id!r} durable={durable['admission_id']!r}"
            ),
        )
    current = export_snapshot(owner, scope)
    if str(current["content_digest"]) != str(durable["target_digest"]):
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_TARGET_CHANGED",
            "the SQLite copy diverged from the published rollback",
            detail=(
                f"durable={durable['target_digest']} "
                f"current={current['content_digest']}"
            ),
        )
    recovered = not published
    if recovered:
        # The rollback committed but the local record was never published. The
        # durable row plus the marker prove the operation; rewrite the record from
        # that identity (never from a bare digest match).
        admission = {
            "contract_version": CONTRACT_VERSION,
            "admission_id": str(durable["admission_id"]),
            "scope": scope,
            "authoritative_provider": "sqlite",
            "source_count": int(current["counts"]["sources"]),
            "content_digest": str(durable["target_digest"]),
            "target_digest": str(durable["target_digest"]),
            "writer_generation": int(durable["writer_generation"]),
            "operation_id": str(durable["operation_id"]),
            "previous_admission_id": previous_admission_id,
            "admitted_at": _now(),
            "revoked_at": None,
            "operator": "finish_cutover",
            "reason": "completed an interrupted rollback from its verified identity chain",
        }
        _write_json_atomic(record_path, admission)
    admission_transition_path(record_path).unlink(missing_ok=True)
    return {
        "finished": True,
        "direction": "ROLLBACK",
        "recovered_local_record": recovered,
        "admission_id": str(durable["admission_id"]),
    }


def finish_cutover(connection, sqlite_path: str | Path) -> dict[str, Any]:
    """Release a published but unresolved transition after proving its state."""
    record_path = admission_record_path(sqlite_path)
    owner = Path(sqlite_path)
    require_idle_connection(connection, purpose="storage-source cutover finish")
    try:
        # Same canonical lock as the SQLite writers and admit/rollback.
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
            scope = str(record.get("scope") or DEFAULT_SCOPE)
            durable = _durable_row_for_update(connection, scope)
            if not durable:
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                    "the durable cutover state is missing",
                )
            require_idle_connection(connection, purpose="storage-source cutover finish")
            direction = str(marker.get("direction") or "FORWARD")
            if str(durable["phase"]) == PHASE_ROLLBACK_APPLIED:
                if direction != "ROLLBACK":
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                        "a rollback state is recorded but the marker is not a rollback",
                        detail=f"direction={direction!r}",
                    )
                return _finish_rollback(connection, owner, record_path, record, durable, scope)
            if direction == "ROLLBACK":
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                    "a rollback marker exists but the durable state is not a rollback",
                )
            if str(marker.get("scope") or "") != scope or str(
                record.get("scope") or ""
            ) != scope:
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                    "the marker or admission record belongs to another scope",
                )
            if str(marker.get("operation_id") or "") != str(
                record.get("operation_id") or ""
            ) or str(durable.get("operation_id") or "") != str(
                record.get("operation_id") or ""
            ):
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                    "the transition marker belongs to another operation",
                    detail=(
                        f"marker={marker.get('operation_id')!r} "
                        f"record={record.get('operation_id')!r} "
                        f"durable={durable.get('operation_id')!r}"
                    ),
                )
            if str(marker.get("previous_admission_id") or "") != str(
                record.get("previous_admission_id") or ""
            ):
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                    "the marker and the admission record disagree on their predecessor",
                )
            if marker.get("writer_generation") is not None and int(
                marker["writer_generation"]
            ) != int(durable["writer_generation"]):
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                    "the marker generation does not match the durable generation",
                )
            if (
                str(durable["admission_id"]) != str(record.get("admission_id") or "")
                or int(durable["writer_generation"])
                != int(record.get("writer_generation") or 0)
                or str(durable["phase"]) != PHASE_POSTGRES_ACTIVE
            ):
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                    "the durable cutover state does not match the admission record",
                )
            with connection.transaction():
                _lock_cutover_scope(connection, scope)
                target = export_target_snapshot(connection, scope)
            require_idle_connection(connection, purpose="storage-source cutover finish")
            if str(target["content_digest"]) != str(durable["target_digest"]):
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_TARGET_CHANGED",
                    "PostgreSQL changed while the transition was unresolved",
                    detail=(
                        f"durable={durable['target_digest']} "
                        f"current={target['content_digest']}"
                    ),
                )
            if str(target["content_digest"]) != str(record.get("content_digest") or ""):
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_CUTOVER_TARGET_CHANGED",
                    "the published admission does not describe the current target",
                )
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


def abort_cutover(
    sqlite_path: str | Path, connection=None
) -> dict[str, Any]:
    """Abort a switch (or an unfinished rollback) that published no admission.

    This only releases the local marker: it is **not** a PostgreSQL rollback. The
    decision is phase- and identity-based:

    * durable ``ROLLBACK_APPLIED`` -> the rollback is published, use ``finish``;
    * durable ``SWITCHING`` -> an interrupted reverse switch: the marker must be
      that rollback and the frozen row is restored to ``POSTGRES_ACTIVE``;
    * durable ``POSTGRES_ACTIVE`` that belongs to the local record -> the
      admission is published, use the verified rollback;
    * durable ``POSTGRES_ACTIVE`` that does **not** belong to the local record ->
      an unpublished forward attempt; releasing the marker is safe because the
      provider refuses writes without the matching admission record.

    A connection is required whenever a local admission record exists, because
    only the durable row can distinguish those states.
    """
    record_path = admission_record_path(sqlite_path)
    owner = Path(sqlite_path)
    restored = ""
    try:
        # Same canonical lock as the SQLite writers and admit/rollback.
        with storage_source_switch_lock(owner, timeout=60):
            record = load_storage_source_admission_record(record_path)
            marker = read_transition(record_path)
            if marker is None:
                return {"aborted": False, "reason": "no transition marker"}
            durable = None
            if connection is not None:
                require_idle_connection(connection, purpose="storage-source abort")
                scope = str((record or {}).get("scope") or DEFAULT_SCOPE)
                durable = _durable_row_for_update(connection, scope)
                if durable is not None and str(durable["phase"]) == PHASE_ROLLBACK_APPLIED:
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_CUTOVER_ROLLBACK_PUBLISHED",
                        "the rollback is published; use finish to complete it",
                    )
            if connection is None and record is not None:
                raise StorageSourceCutoverError(
                    "STORAGE_SOURCE_ABORT_REQUIRES_CONNECTION",
                    "resolving this interrupted switch needs the PostgreSQL connection",
                    detail="pass the connection so the durable phase can be proven",
                )
            if durable is not None and str(durable["phase"]) == PHASE_SWITCHING:
                if str(marker.get("direction") or "") != "ROLLBACK":
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                        "the marker does not describe the frozen operation",
                        detail=f"direction={marker.get('direction')!r}",
                    )
                if record is None or str(record.get("admission_id") or "") != str(
                    durable["admission_id"]
                ) or int(record.get("writer_generation") or 0) != int(
                    durable["writer_generation"]
                ):
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                        "the frozen durable state does not belong to the local admission",
                    )
                with connection.transaction():
                    _lock_cutover_scope(connection, scope)
                    with connection.cursor() as cursor:
                        cursor.execute(
                            f"UPDATE {SCHEMA_NAME}.cutover_state SET phase=%s, "
                            "updated_at=now() WHERE scope=%s AND admission_id=%s "
                            "AND writer_generation=%s AND phase=%s",
                            (
                                PHASE_POSTGRES_ACTIVE,
                                scope,
                                str(durable["admission_id"]),
                                int(durable["writer_generation"]),
                                PHASE_SWITCHING,
                            ),
                        )
                        if cursor.rowcount != 1:
                            raise StorageSourceCutoverError(
                                "STORAGE_SOURCE_CUTOVER_STATE_UNKNOWN",
                                "the frozen cutover state was replaced; refusing to restore",
                            )
                restored = PHASE_POSTGRES_ACTIVE
            elif durable is not None and str(durable["phase"]) == PHASE_POSTGRES_ACTIVE:
                owns = (
                    record is not None
                    and str(record.get("authoritative_provider") or "")
                    == PROVIDER_POSTGRESQL
                    and str(record.get("admission_id") or "")
                    == str(durable["admission_id"])
                    and int(record.get("writer_generation") or 0)
                    == int(durable["writer_generation"])
                )
                if owns:
                    raise StorageSourceCutoverError(
                        "STORAGE_SOURCE_CUTOVER_ALREADY_ADMITTED",
                        "an admission is published; a verified rollback is required",
                        detail=f"admission_id={record.get('admission_id')!r}",
                    )
            admission_transition_path(record_path).unlink(missing_ok=True)
    except FileLockTimeout as error:
        raise StorageSourceCutoverError(
            "STORAGE_SOURCE_CUTOVER_BUSY",
            "a storage-source write is in progress; retry abort",
        ) from error
    return {
        "aborted": True,
        "operation_id": marker.get("operation_id"),
        "restored_phase": restored,
        "target_may_hold_unadmitted_rows": True,
    }


def summarize_error(error: BaseException) -> dict[str, Any]:
    """CLI-friendly, stable error rendering."""
    if isinstance(error, (StorageSourceCutoverError, StorageSourceAdmissionRequired)):
        return {"code": error.code, "detail": error.detail}
    if isinstance(error, StorageSourceMigrationError):
        return {"code": error.code, "detail": error.detail}
    return {"code": type(error).__name__, "detail": str(error)}
