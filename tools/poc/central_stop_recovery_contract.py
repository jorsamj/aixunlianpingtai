"""P0-01C-3A: isolated CENTRAL recovery transaction contract, NOT a platform API.

Only runs on anonymous SQLite :memory: connections. No production repository,
Node Agent, network, GPU, or real task can reach this test-only module.

The HMAC witness in the companion tests is a SIMULATED independent OS witness,
not a trusted attestation implementation. Never release a real held execution
based on a Node Agent JSON claim or this demonstration's signer.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import secrets
import sqlite3
from typing import Any, Callable, Mapping

HOLD = "recovery_blocked_remote_agent_unverified"
EMPTY = object()


class RecoveryRejected(RuntimeError):
    """Safety gate rejected; caller must preserve the original HOLD."""


def _memory_only(db: sqlite3.Connection) -> None:
    rows = db.execute("PRAGMA database_list").fetchall()
    if len(rows) != 1 or rows[0][1] != "main" or rows[0][2] != "":
        raise RecoveryRejected("ISOLATED_MEMORY_DATABASE_REQUIRED")


def _now(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise RecoveryRejected("UTC_CLOCK_REQUIRED")
    return value.astimezone(timezone.utc)


def _deadline(value: str) -> datetime:
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError("naive")
        return result.astimezone(timezone.utc)
    except (AttributeError, ValueError) as exc:
        raise RecoveryRejected("LEASE_DEADLINE_UNKNOWN") from exc


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _row(db: sqlite3.Connection, query: str, params: tuple) -> dict | None:
    cursor = db.execute(query, params)
    data = cursor.fetchone()
    if data is None:
        return None
    return dict(zip((column[0] for column in cursor.description), data))


def _valid_boundary(boot_id: str, invocation_id: str, unit: str, cgroup: str) -> bool:
    return (isinstance(boot_id, str) and bool(re.fullmatch(
                r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", boot_id))
            and isinstance(invocation_id, str) and bool(re.fullmatch(
                r"[a-f0-9]{32}", invocation_id))
            and invocation_id != "0" * 32
            and isinstance(unit, str) and bool(re.fullmatch(
                r"clpoc-[a-f0-9]{24}\.service", unit))
            and isinstance(cgroup, str) and cgroup.startswith("/")
            and ".." not in cgroup.split("/")
            and cgroup.rsplit("/", 1)[-1] == unit)


def init_scratch_schema(db: sqlite3.Connection) -> None:
    """Create a representative subset of the EXISTING task/GPU schema in RAM.

    The extra challenge/audit tables model future protocol metadata, not a
    second owner, task queue, or production schema migration.
    """
    _memory_only(db)
    db.executescript("""
        CREATE TABLE tasks (
          task_id TEXT PRIMARY KEY, attempt INTEGER NOT NULL, status TEXT NOT NULL,
          stage TEXT NOT NULL, worker_id TEXT, lease_token TEXT, lease_expires_at TEXT,
          resource_wait_reason TEXT, process_pid INTEGER, process_create_time REAL,
          process_command_hash TEXT, updated_at TEXT, finished_at TEXT
        );
        CREATE TABLE gpu_reservations (
          task_id TEXT PRIMARY KEY, worker_id TEXT, lease_token TEXT, policy TEXT
        );
        CREATE TABLE recovery_challenges (
          challenge_id TEXT PRIMARY KEY, task_id TEXT NOT NULL,
          execution_generation INTEGER NOT NULL, worker_id TEXT NOT NULL,
          lease_hash TEXT NOT NULL, nonce_hash TEXT NOT NULL,
          boot_id TEXT NOT NULL, invocation_id TEXT NOT NULL,
          unit TEXT NOT NULL, cgroup TEXT NOT NULL,
          issued_at TEXT NOT NULL, expires_at TEXT NOT NULL,
          consumed_at TEXT, decision TEXT,
          UNIQUE(task_id, execution_generation)
        );
        CREATE TABLE recovery_audit (
          challenge_id TEXT PRIMARY KEY, task_id TEXT, execution_generation INTEGER,
          old_worker TEXT, next_status TEXT, decided_at TEXT
        );
    """)


def _held_task(db: sqlite3.Connection, task_id: str, node_id: str,
               now: datetime) -> dict:
    task = _row(db, "SELECT * FROM tasks WHERE task_id=?", (task_id,))
    if (task is None or task["status"] not in ("RUNNING", "CANCEL_REQUESTED")
            or task["stage"] != HOLD
            or task["worker_id"] != "agent:" + node_id
            or type(task["attempt"]) is not int or task["attempt"] < 1
            or not isinstance(task["lease_token"], str)
            or len(task["lease_token"]) < 20
            or not task["lease_expires_at"]
            or _deadline(task["lease_expires_at"]) > now):
        raise RecoveryRejected("HELD_OWNER_GENERATION_OR_EXPIRED_LEASE_MISMATCH")
    return task


def _reservation_safe(db: sqlite3.Connection, task: Mapping[str, Any]) -> None:
    reserved = _row(db, "SELECT * FROM gpu_reservations WHERE task_id=?",
                    (task["task_id"],))
    if reserved is not None and (reserved["worker_id"] != task["worker_id"] or
                                 not hmac.compare_digest(
                                     str(reserved["lease_token"] or ""),
                                     task["lease_token"])):
        raise RecoveryRejected("GPU_RESERVATION_OWNER_MISMATCH")


def issue_challenge(db: sqlite3.Connection, *, task_id: str, node_id: str,
                    boot_id: str, invocation_id: str, unit: str, cgroup: str,
                    now: datetime, ttl_seconds: int = 45) -> dict:
    """Simulation assumes node authentication and OS boundary registration.

    Authentication and prior trusted boundary registration are NOT implemented.
    This deliberately cannot be called against the production database.
    """
    _memory_only(db)
    clock = _now(now)
    if not isinstance(task_id, str) or not task_id or not isinstance(node_id, str) or (
            not node_id or ":" in node_id) or (
            type(ttl_seconds) is not int or ttl_seconds < 5 or ttl_seconds > 120) or (
            not _valid_boundary(boot_id, invocation_id, unit, cgroup)):
        raise RecoveryRejected("CHALLENGE_SCOPE_INVALID")
    challenge_id = secrets.token_hex(16)
    nonce = secrets.token_urlsafe(32)
    db.execute("BEGIN IMMEDIATE")
    try:
        task = _held_task(db, task_id, node_id, clock)
        _reservation_safe(db, task)
        db.execute("""INSERT INTO recovery_challenges
           (challenge_id,task_id,execution_generation,worker_id,lease_hash,
            nonce_hash,boot_id,invocation_id,unit,cgroup,issued_at,expires_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
           (challenge_id, task_id, task["attempt"], task["worker_id"],
            _digest(task["lease_token"]), _digest(nonce), boot_id,
            invocation_id, unit, cgroup, clock.isoformat(),
            (clock + timedelta(seconds=ttl_seconds)).isoformat()))
        db.commit()
        return {"challenge_id": challenge_id, "nonce": nonce,
                "task_id": task_id, "execution_generation": task["attempt"],
                "worker_id": task["worker_id"], "boot_id": boot_id,
                "invocation_id": invocation_id, "unit": unit, "cgroup": cgroup}
    except Exception:
        db.rollback()
        raise


def _strict_witness_fields(payload: Mapping[str, Any]) -> bool:
    if not isinstance(payload, Mapping):
        return False
    if any(payload.get(k) is not True for k in (
            "os_cgroup_empty", "known_processes_stopped", "stop_command_succeeded")):
        return False
    start, stop = payload.get("stop_requested_ns"), payload.get("empty_observed_ns")
    return (type(start) is int and type(stop) is int
            and 0 < start <= stop)


def commit_test_recovery(db: sqlite3.Connection, *, attestation: Mapping[str, Any],
                         now: datetime,
                         independent_witness_verifier: Callable[[Mapping[str, Any]], bool] | None
                         ) -> dict:
    """Test the central atomic CAS, not actual trusted OS stop verification.

    If no independent verification is available, ALWAYS reject. Never trust a
    mere agent-side boolean or heartbeat. HMAC example verifier lives in tests.
    """
    _memory_only(db)
    clock = _now(now)
    if not isinstance(attestation, Mapping):
        raise RecoveryRejected("STOP_ATTESTATION_REQUIRED")
    payload = attestation.get("payload")
    if (not _strict_witness_fields(payload) or
            independent_witness_verifier is None or
            independent_witness_verifier(attestation) is not True):
        raise RecoveryRejected("INDEPENDENT_OS_STOP_WITNESS_UNVERIFIED")
    challenge_id = payload.get("challenge_id")
    nonce = payload.get("nonce")
    if (not isinstance(challenge_id, str) or
            not isinstance(nonce, str) or not nonce):
        raise RecoveryRejected("CHALLENGE_INVALID")
    db.execute("BEGIN IMMEDIATE")
    try:
        challenge = _row(db, "SELECT * FROM recovery_challenges WHERE challenge_id=?",
                         (challenge_id,))
        if challenge is None or challenge["consumed_at"] is not None or (
                _deadline(challenge["expires_at"]) <= clock):
            raise RecoveryRejected("CHALLENGE_MISSING_EXPIRED_OR_CONSUMED")
        if not hmac.compare_digest(challenge["nonce_hash"], _digest(nonce)):
            raise RecoveryRejected("CHALLENGE_NONCE_MISMATCH")
        match_fields = (
            ("task_id", "task_id"),
            ("execution_generation", "execution_generation"),
            ("worker_id", "worker_id"),
            ("boot_id", "boot_id"),
            ("invocation_id", "invocation_id"),
            ("unit", "unit"),
            ("cgroup", "cgroup"))
        if any(type(payload.get(p)) is not type(challenge[c]) or
               payload[p] != challenge[c] for p, c in match_fields):
            raise RecoveryRejected("CHALLENGE_EXECUTION_IDENTITY_MISMATCH")
        node_id = challenge["worker_id"][len("agent:"):]
        task = _held_task(db, challenge["task_id"], node_id, clock)
        if (task["attempt"] != challenge["execution_generation"] or
                not hmac.compare_digest(
                    _digest(task["lease_token"]), challenge["lease_hash"])):
            raise RecoveryRejected("TASK_GENERATION_OR_LEASE_CHANGED")
        _reservation_safe(db, task)
        cancelled = task["status"] == "CANCEL_REQUESTED"
        next_status = "CANCELLED" if cancelled else "QUEUED"
        stage = "cancelled" if cancelled else "recovered"
        changed = db.execute("""UPDATE tasks
            SET status=?, stage=?, worker_id=NULL, lease_token=NULL,
                lease_expires_at=NULL, resource_wait_reason=NULL,
                process_pid=NULL, process_create_time=NULL,
                process_command_hash=NULL, updated_at=?,
                finished_at=CASE WHEN ? THEN ? ELSE finished_at END
            WHERE task_id=? AND attempt=? AND worker_id=? AND lease_token=?
              AND stage=? AND status IN ('RUNNING','CANCEL_REQUESTED')""",
            (next_status, stage, clock.isoformat(), int(cancelled),
             clock.isoformat(), task["task_id"], task["attempt"],
             task["worker_id"], task["lease_token"], HOLD)).rowcount
        if changed != 1:
            raise RecoveryRejected("ATOMIC_RECOVERY_COMPARE_AND_SWAP_LOST")
        db.execute("DELETE FROM gpu_reservations WHERE task_id=?", (task["task_id"],))
        result = db.execute("""UPDATE recovery_challenges
            SET consumed_at=?, decision=? WHERE challenge_id=? AND consumed_at IS NULL""",
            (clock.isoformat(), next_status, challenge_id)).rowcount
        if result != 1:
            raise RecoveryRejected("CHALLENGE_REPLAYED")
        db.execute("""INSERT INTO recovery_audit
            (challenge_id,task_id,execution_generation,old_worker,next_status,decided_at)
            VALUES (?,?,?,?,?,?)""",
            (challenge_id, task["task_id"], task["attempt"],
             task["worker_id"], next_status, clock.isoformat()))
        db.commit()
        return {"task_id": task["task_id"], "status": next_status,
                "previous_execution_generation": task["attempt"],
                "challenge_consumed": True, "scratch_only": True}
    except Exception:
        db.rollback()
        raise


def test_only_sign_witness(payload: dict, key: bytes) -> dict:
    """SIMULATED trusted witness. Real OS attestation implementation absent."""
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return {"payload": dict(payload),
            "signature": hmac.new(key, data, hashlib.sha256).hexdigest()}


def test_only_witness_verifier(key: bytes):
    """SIMULATION ONLY: a MAC cannot independently attest OS process death."""
    def verify(attestation: Mapping[str, Any]) -> bool:
        try:
            payload = attestation["payload"]
            claimed = attestation["signature"]
            expected = test_only_sign_witness(dict(payload), key)["signature"]
            return (isinstance(claimed, str) and
                    hmac.compare_digest(claimed, expected))
        except (TypeError, KeyError, ValueError):
            return False
    return verify
