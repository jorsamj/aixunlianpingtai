"""U5 readiness diagnostics are read-only, status/stage-accurate and fail closed."""
from __future__ import annotations

import sqlite3

import pytest

from platform_core.task_runtime import TaskKind, TaskRecord, TaskRepository
from platform_core.task_store_readiness import TaskStoreReadinessError, readiness

NOW = "2026-11-27T00:00:00+00:00"


def _store(tmp_path):
    repository = TaskRepository(tmp_path / "task_runtime" / "tasks.sqlite3")
    task = TaskRecord.new("t-1", "p1", TaskKind.TRAINING, "request.json", "cpu")
    repository.create(task)
    return repository, task


PROOF = {"workers_stopped": True, "evidence": "systemctl stop changlian-worker; nodes drained"}


def _update(repository, sql, parameters=()):
    with sqlite3.connect(repository.path) as database:
        database.execute(sql, parameters)


def test_missing_store_is_reported_and_blocks(tmp_path):
    report = readiness(tmp_path, now=NOW, stop_proof=PROOF)
    assert report["present"] is False
    assert report["blockers"] == ["task_store_missing"]
    assert report["ready_for_cutover"] is False and report["read_only"] is True


def test_active_expired_and_unknown_leases_are_distinguished(tmp_path):
    repository, task = _store(tmp_path)
    _update(repository, "UPDATE tasks SET status='RUNNING', lease_expires_at=? WHERE task_id=?",
            ("2026-11-27T01:00:00+00:00", task.task_id))
    active = readiness(tmp_path, now=NOW)
    assert active["active_leases"] == 1 and active["expired_leases"] == 0
    assert "active_leases_require_drain" in active["blockers"]

    _update(repository, "UPDATE tasks SET lease_expires_at=? WHERE task_id=?",
            ("2026-11-26T23:00:00+00:00", task.task_id))
    expired = readiness(tmp_path, now=NOW)
    assert expired["expired_leases"] == 1
    assert "expired_leases_require_recovery" in expired["blockers"]

    _update(repository, "UPDATE tasks SET lease_expires_at=NULL WHERE task_id=?", (task.task_id,))
    unknown = readiness(tmp_path, now=NOW)
    assert unknown["unknown_lease"] == 1
    assert "unproven_lease_window" in unknown["blockers"]


def test_unverified_stop_and_recovery_are_read_from_the_real_stage(tmp_path):
    repository, task = _store(tmp_path)
    _update(repository, "UPDATE tasks SET status='CANCEL_REQUESTED', stage='cancelling' WHERE task_id=?",
            (task.task_id,))
    report = readiness(tmp_path, now=NOW, stop_proof=PROOF)
    assert report["unverified_stop"] == 1
    assert "unverified_stop_proof" in report["blockers"]

    # recovery_blocked_* are stages, not TaskStatus values.
    _update(repository, "UPDATE tasks SET stage='recovery_blocked_process_inspection' WHERE task_id=?",
            (task.task_id,))
    blocked = readiness(tmp_path, now=NOW)
    assert blocked["recovery_blocked"] == 1
    assert "recovery_blocked_owner" in blocked["blockers"]


def test_incomplete_or_unsupported_schema_fails_closed(tmp_path):
    runtime = tmp_path / "task_runtime"
    runtime.mkdir(parents=True)
    path = runtime / "tasks.sqlite3"
    with sqlite3.connect(path) as database:
        database.execute("PRAGMA user_version=8")
        database.execute("CREATE TABLE tasks (task_id TEXT PRIMARY KEY, status TEXT)")
    report = readiness(tmp_path, now=NOW, stop_proof=PROOF)
    assert report["blockers"] and any(
        b.startswith("tasks_incomplete:") for b in report["blockers"]
    )
    assert report["ready_for_cutover"] is False

    with sqlite3.connect(path) as database:
        database.execute("PRAGMA user_version=7")
    unsupported = readiness(tmp_path, now=NOW)
    assert unsupported["blockers"] == ["unsupported_task_schema:7"]
    assert unsupported["ready_for_cutover"] is False


def test_sql_read_failure_raises_instead_of_reporting_zero(tmp_path):
    runtime = tmp_path / "task_runtime"
    runtime.mkdir(parents=True)
    (runtime / "tasks.sqlite3").write_bytes(b"not a sqlite database at all")
    with pytest.raises(TaskStoreReadinessError) as failure:
        readiness(tmp_path, now=NOW)
    assert failure.value.code == "TASK_STORE_READ_FAILED"


def test_readiness_never_mutates_the_store(tmp_path):
    repository, task = _store(tmp_path)
    _update(repository, "UPDATE tasks SET status='RUNNING', lease_expires_at=? WHERE task_id=?",
            ("2026-11-27T01:00:00+00:00", task.task_id))
    with sqlite3.connect(repository.path) as database:
        before = database.execute(
            "SELECT task_id,status,stage,attempt,lease_expires_at,updated_at FROM tasks"
        ).fetchall()
    readiness(tmp_path, now=NOW)
    with sqlite3.connect(repository.path) as database:
        after = database.execute(
            "SELECT task_id,status,stage,attempt,lease_expires_at,updated_at FROM tasks"
        ).fetchall()
    assert before == after


def test_active_worker_instance_requires_a_real_drain(tmp_path):
    repository, task = _store(tmp_path)
    _update(repository, "UPDATE tasks SET status='SUCCEEDED' WHERE task_id=?", (task.task_id,))
    with sqlite3.connect(repository.path) as database:
        database.execute(
            "INSERT INTO worker_instances (instance_key,owner_token,worker_id,pid,started_at,"
            "heartbeat_at,expires_at) VALUES ('k2','o2','w2',2,?,?,?)",
            ("2026-11-26T00:00:00+00:00", "2026-11-26T23:59:00+00:00", "2026-11-27T01:00:00+00:00"),
        )
    report = readiness(tmp_path, now=NOW, stop_proof=PROOF)
    assert report["worker_instances_active"] == 1
    assert "active_worker_instances_require_drain" in report["blockers"]
    assert report["ready_for_cutover"] is False


def test_expired_worker_instance_is_a_blocker(tmp_path):
    repository, task = _store(tmp_path)
    _update(repository, "UPDATE tasks SET status='SUCCEEDED' WHERE task_id=?", (task.task_id,))
    with sqlite3.connect(repository.path) as database:
        database.execute(
            "INSERT INTO worker_instances (instance_key,owner_token,worker_id,pid,started_at,"
            "heartbeat_at,expires_at) VALUES ('k1','o1','w1',1,?,?,?)",
            ("2026-11-26T00:00:00+00:00", "2026-11-26T00:00:00+00:00", "2026-11-26T23:00:00+00:00"),
        )
    report = readiness(tmp_path, now=NOW, stop_proof=PROOF)
    assert report["worker_instances_expired"] == 1
    assert "expired_worker_instances" in report["blockers"]

def test_required_tables_missing_block_the_cutover(tmp_path):
    repository, task = _store(tmp_path)
    _update(repository, "UPDATE tasks SET status='SUCCEEDED' WHERE task_id=?", (task.task_id,))
    with sqlite3.connect(repository.path) as database:
        database.execute("DROP TABLE worker_instances")
    workers = readiness(tmp_path, now=NOW, stop_proof=PROOF)
    assert workers["blockers"] == ["worker_instances_table_missing"]
    assert workers["ready_for_cutover"] is False

    with sqlite3.connect(repository.path) as database:
        database.execute("DROP TABLE gpu_reservations")
    gpu = readiness(tmp_path, now=NOW, stop_proof=PROOF)
    assert "gpu_reservations_table_missing" in gpu["blockers"]
    assert gpu["ready_for_cutover"] is False


def test_required_table_columns_missing_block_the_cutover(tmp_path):
    repository, task = _store(tmp_path)
    _update(repository, "UPDATE tasks SET status='SUCCEEDED' WHERE task_id=?", (task.task_id,))
    with sqlite3.connect(repository.path) as database:
        database.execute("DROP TABLE worker_instances")
        database.execute("CREATE TABLE worker_instances (instance_key TEXT PRIMARY KEY, owner_token TEXT)")
    report = readiness(tmp_path, now=NOW, stop_proof=PROOF)
    assert any(b.startswith("worker_instances_incomplete:") for b in report["blockers"])
    assert report["ready_for_cutover"] is False

    repository2, task2 = _store(tmp_path / "second")
    _update(repository2, "UPDATE tasks SET status='SUCCEEDED' WHERE task_id=?", (task2.task_id,))
    with sqlite3.connect(repository2.path) as database:
        database.execute("DROP TABLE gpu_reservations")
        database.execute("CREATE TABLE gpu_reservations (task_id TEXT PRIMARY KEY, gpu_uuid TEXT)")
    gpu = readiness(tmp_path / "second", now=NOW, stop_proof=PROOF)
    assert any(b.startswith("gpu_reservations_incomplete:") for b in gpu["blockers"])
    assert gpu["ready_for_cutover"] is False


def test_pragma_failure_is_an_error_not_a_missing_table(tmp_path):
    runtime = tmp_path / "task_runtime"
    runtime.mkdir(parents=True)
    (runtime / "tasks.sqlite3").write_bytes(b"not a sqlite database at all")
    with pytest.raises(TaskStoreReadinessError):
        readiness(tmp_path, now=NOW, stop_proof=PROOF)


def test_worker_stop_proof_is_never_accepted_from_the_caller(tmp_path):
    """Even a completely empty store stays blocked: no trusted verifier exists."""
    repository, task = _store(tmp_path)
    _update(repository, "UPDATE tasks SET status='SUCCEEDED' WHERE task_id=?", (task.task_id,))
    without = readiness(tmp_path, now=NOW)
    assert "external_worker_stop_proof_required" in without["blockers"]
    assert without["stop_proof_status"] == "MISSING"
    assert without["ready_for_cutover"] is False

    self_asserted = readiness(tmp_path, now=NOW, stop_proof=PROOF)
    assert self_asserted["stop_proof_status"] == "UNVERIFIED"
    assert "external_worker_stop_proof_unverified" in self_asserted["blockers"]
    assert self_asserted["external_stop_proof_valid"] is False
    assert self_asserted["ready_for_cutover"] is False

    # An arbitrary string (the previous "proof") is not a proof either.
    text_proof = readiness(tmp_path, now=NOW, stop_proof={"evidence": "systemctl stop worker; nodes drained"})
    assert text_proof["stop_proof_status"] == "UNVERIFIED"
    assert text_proof["ready_for_cutover"] is False

    # The future proof contract is explicit about what must be verified.
    assert set(self_asserted["stop_proof_contract"]) == {
        "nodes", "worker_services", "process_identities", "observed_at",
        "expires_at", "source", "verifier_signature",
    }
