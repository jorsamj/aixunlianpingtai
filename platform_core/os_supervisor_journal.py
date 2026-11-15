"""Phase 1B durable pre-launch OS intent, without a process spawn backend.

Only a protected Supervisor may use this file in production. It is not a
scheduler, central task owner, stop proof, or evidence that a worker is EXITED.
No production runtime imports this module yet.
"""
from __future__ import annotations

from contextlib import closing
import json
import os
from pathlib import Path
import re
import secrets
import sqlite3
import stat
import time
from typing import Mapping

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .os_supervisor_authorization import (
    BINDING_FIELDS, GrantRejected, verify_central_execution_grant,
)

PROTECTED_PATH = Path("/var/lib/changlian-os-supervisor/executions.sqlite3")
_CHALLENGE_FIELDS = BINDING_FIELDS - {"challenge"}
_SCHEMA = """
CREATE TABLE IF NOT EXISTS challenges (
    challenge TEXT PRIMARY KEY,
    binding_json TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS execution_intents (
    handle_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    task_attempt INTEGER NOT NULL CHECK(task_attempt > 0),
    node_id TEXT NOT NULL,
    worker_id TEXT NOT NULL,
    lease_sha256 TEXT NOT NULL,
    grant_digest TEXT NOT NULL,
    challenge TEXT NOT NULL UNIQUE,
    boot_id TEXT NOT NULL,
    unit_name TEXT NOT NULL UNIQUE,
    state TEXT NOT NULL CHECK(state IN ('PREPARED', 'STARTING', 'RUNNING', 'UNKNOWN', 'EXITED')),
    event_seq INTEGER NOT NULL CHECK(event_seq > 0),
    created_at INTEGER NOT NULL,
    UNIQUE(task_id, task_attempt)
);
CREATE TABLE IF NOT EXISTS cpu_unit_identities (
    handle_id TEXT PRIMARY KEY REFERENCES execution_intents(handle_id),
    invocation_id TEXT NOT NULL UNIQUE,
    control_group TEXT NOT NULL,
    main_pid INTEGER NOT NULL CHECK(main_pid > 1),
    recorded_at INTEGER NOT NULL
);
"""


class ExecutionJournal:
    """Full-sync SQLite reservation; one task/attempt -> one OS handle."""

    def __init__(self, path: Path = PROTECTED_PATH, *,
                 test_only_unprivileged: bool = False,
                 boot_id_for_tests: str | None = None):
        self.path = Path(path)
        self.test_only_unprivileged = test_only_unprivileged
        if not test_only_unprivileged:
            if (os.name != "posix" or not hasattr(os, "geteuid")
                    or os.geteuid() != 0 or self.path != PROTECTED_PATH
                    or boot_id_for_tests is not None):
                raise GrantRejected("JOURNAL_PROTECTED_OS_IDENTITY_REQUIRED_HOLD")
        if not self.path.is_absolute():
            raise GrantRejected("JOURNAL_ABSOLUTE_PATH_REQUIRED_HOLD")
        if test_only_unprivileged and boot_id_for_tests is not None:
            self.boot_id = boot_id_for_tests
        else:
            try:
                self.boot_id = Path("/proc/sys/kernel/random/boot_id").read_text(
                    encoding="ascii").strip()
            except OSError as exc:
                raise GrantRejected("JOURNAL_BOOT_ID_UNAVAILABLE_HOLD") from exc
        parent = self.path.parent
        if not parent.exists():
            parent.mkdir(mode=0o700, parents=False)
        info = parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or parent.is_symlink():
            raise GrantRejected("JOURNAL_DIRECTORY_UNSAFE_HOLD")
        if not test_only_unprivileged and (
                info.st_uid != 0 or stat.S_IMODE(info.st_mode) & 0o077):
            raise GrantRejected("JOURNAL_DIRECTORY_PERMISSIONS_UNSAFE_HOLD")
        if self.path.is_symlink():
            raise GrantRejected("JOURNAL_FILE_SYMLINK_DENIED_HOLD")
        if self.path.exists():
            file_info = self.path.lstat()
            if not stat.S_ISREG(file_info.st_mode):
                raise GrantRejected("JOURNAL_NOT_REGULAR_FILE_HOLD")
            if not test_only_unprivileged and (
                    file_info.st_uid != 0 or stat.S_IMODE(file_info.st_mode) & 0o077):
                raise GrantRejected("JOURNAL_FILE_PERMISSIONS_UNSAFE_HOLD")
        # Only the root-owned, non-writable-by-Agent directory is trusted.
        with closing(self._connect()) as db:
            db.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(str(self.path), timeout=5,
                                   isolation_level=None)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA foreign_keys=ON")
        database.execute("PRAGMA journal_mode=DELETE")
        database.execute("PRAGMA synchronous=FULL")
        if not self.test_only_unprivileged and os.name == "posix":
            os.chmod(self.path, 0o600)
        return database

    def issue_challenge(self, binding: Mapping[str, object], *,
                        now: int | None = None) -> str:
        """Persist a fresh OS-bound nonce. A nonce alone cannot start a worker."""
        if not isinstance(binding, Mapping) or set(binding) != _CHALLENGE_FIELDS:
            raise GrantRejected("JOURNAL_CHALLENGE_SCOPE_INVALID_HOLD")
        if binding["boot_id"] != self.boot_id:
            raise GrantRejected("JOURNAL_BOOT_SCOPE_MISMATCH_HOLD")
        if (binding["runner_profile"] != "fixed-cpu-v1"
                or binding["gpu_uuid"] != "CPU_ONLY"):
            raise GrantRejected("JOURNAL_PROFILE_DISABLED_HOLD")
        if type(binding["task_attempt"]) is not int or binding["task_attempt"] <= 0:
            raise GrantRejected("JOURNAL_ATTEMPT_INVALID_HOLD")
        current = int(time.time()) if now is None else now
        if type(current) is not int:
            raise GrantRejected("JOURNAL_CLOCK_INVALID_HOLD")
        challenge = secrets.token_hex(16)
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("INSERT INTO challenges VALUES (?,?,?)", (
                challenge, json.dumps(dict(binding), sort_keys=True),
                current + 90,
            ))
            db.commit()
        return challenge

    def register_intent(self, envelope: object, *,
                        trusted_public_key: Ed25519PublicKey,
                        now: int | None = None) -> dict:
        """Signed exact binding + single durable handle, before any future spawn.

        Duplicate replies preserve the same handle. Conflicting same-attempt
        intents and unknown/expired challenges always HOLD.
        """
        current = int(time.time()) if now is None else now
        if type(current) is not int:
            raise GrantRejected("JOURNAL_CLOCK_INVALID_HOLD")
        if not isinstance(envelope, dict) or not isinstance(envelope.get("claims"), dict):
            raise GrantRejected("JOURNAL_GRANT_INVALID_HOLD")
        challenge = envelope["claims"].get("challenge")
        if not isinstance(challenge, str):
            raise GrantRejected("JOURNAL_CHALLENGE_MISSING_HOLD")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            challenge_row = db.execute(
                "SELECT * FROM challenges WHERE challenge=?", (challenge,)
            ).fetchone()
            if challenge_row is None or current >= challenge_row["expires_at"]:
                raise GrantRejected("JOURNAL_CHALLENGE_UNKNOWN_OR_EXPIRED_HOLD")
            expected = json.loads(challenge_row["binding_json"])
            expected["challenge"] = challenge
            grant = verify_central_execution_grant(
                envelope, trusted_public_key=trusted_public_key,
                expected_binding=expected, now=current,
            )
            existing = db.execute(
                "SELECT * FROM execution_intents WHERE task_id=? AND task_attempt=?",
                (grant.task_id, grant.task_attempt),
            ).fetchone()
            if existing is not None:
                if (existing["grant_digest"] != grant.grant_digest
                        or existing["challenge"] != challenge):
                    raise GrantRejected("JOURNAL_ATTEMPT_ALREADY_RESERVED_HOLD")
                db.commit()
                return {"handle_id": existing["handle_id"],
                        "task_attempt": grant.task_attempt,
                        "state": "UNKNOWN", "replayed": True}
            handle = secrets.token_hex(16)
            unit_name = "changlian-os-" + handle + ".service"
            db.execute(
                """INSERT INTO execution_intents
                (handle_id,task_id,task_attempt,node_id,worker_id,lease_sha256,
                 grant_digest,challenge,boot_id,unit_name,state,event_seq,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (handle, grant.task_id, grant.task_attempt, grant.node_id,
                 grant.worker_id, grant.execution_lease_sha256,
                 grant.grant_digest, grant.challenge, grant.boot_id,
                 unit_name, "PREPARED", 1, current),
            )
            db.commit()
        return {"handle_id": handle, "task_attempt": grant.task_attempt,
                "state": "UNKNOWN", "replayed": False}

    def inspect(self, handle_id: str, task_attempt: int) -> dict:
        with closing(self._connect()) as db:
            row = db.execute(
                "SELECT handle_id,task_attempt FROM execution_intents "
                "WHERE handle_id=? AND task_attempt=?",
                (handle_id, task_attempt),
            ).fetchone()
        if row is None:
            raise GrantRejected("JOURNAL_EXECUTION_NOT_REGISTERED_HOLD")
        return {"handle_id": row["handle_id"], "task_attempt": row["task_attempt"],
                "state": "UNKNOWN"}

    def claim_cpu_launch(self, handle_id: str, task_attempt: int,
                         envelope: object, *,
                         trusted_public_key: Ed25519PublicKey,
                         now: int | None = None) -> dict:
        """One durable PREPARED->STARTING CAS *before* systemd-run.

        A start retry, crash window, expired grant or wrong OS boot stays HOLD.
        No second unit can be launched for this task attempt.
        """
        current = int(time.time()) if now is None else now
        if type(current) is not int or not isinstance(envelope, dict):
            raise GrantRejected("CPU_LAUNCH_REQUEST_INVALID_HOLD")
        claims = envelope.get("claims")
        if not isinstance(claims, dict) or not isinstance(claims.get("challenge"), str):
            raise GrantRejected("CPU_LAUNCH_GRANT_INVALID_HOLD")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT * FROM execution_intents
                    WHERE handle_id=? AND task_attempt=?""",
                (handle_id, task_attempt),
            ).fetchone()
            challenge = db.execute(
                "SELECT * FROM challenges WHERE challenge=?",
                (claims["challenge"],),
            ).fetchone()
            if row is None or challenge is None or current >= challenge["expires_at"]:
                raise GrantRejected("CPU_LAUNCH_IDENTITY_OR_CHALLENGE_UNKNOWN_HOLD")
            if (row["state"] != "PREPARED"
                    or row["boot_id"] != self.boot_id):
                raise GrantRejected("CPU_LAUNCH_ALREADY_ATTEMPTED_OR_BOOT_CHANGED_HOLD")
            expected = json.loads(challenge["binding_json"])
            expected["challenge"] = claims["challenge"]
            grant = verify_central_execution_grant(
                envelope, trusted_public_key=trusted_public_key,
                expected_binding=expected, now=current)
            if (grant.grant_digest != row["grant_digest"]
                    or grant.task_id != row["task_id"]
                    or grant.task_attempt != row["task_attempt"]
                    or grant.node_id != row["node_id"]
                    or grant.worker_id != row["worker_id"]
                    or grant.execution_lease_sha256 != row["lease_sha256"]):
                raise GrantRejected("CPU_LAUNCH_JOURNAL_SCOPE_MISMATCH_HOLD")
            changed = db.execute(
                """UPDATE execution_intents
                   SET state='STARTING',event_seq=event_seq+1
                   WHERE handle_id=? AND task_attempt=? AND state='PREPARED'""",
                (handle_id, task_attempt),
            ).rowcount
            if changed != 1:
                raise GrantRejected("CPU_LAUNCH_CONCURRENT_REPLAY_HOLD")
            db.commit()
            return {"handle_id": handle_id, "task_attempt": task_attempt,
                    "unit_name": row["unit_name"]}

    def record_cpu_identity(self, handle_id: str, task_attempt: int, *,
                            invocation_id: str, control_group: str,
                            main_pid: int) -> None:
        """Durably bind real systemd InvocationID before reporting RUNNING."""
        if (not isinstance(invocation_id, str)
                or not re.fullmatch(r"[0-9a-f]{32}", invocation_id)
                or type(main_pid) is not int or main_pid <= 1):
            raise GrantRejected("CPU_IDENTITY_INVALID_HOLD")
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM execution_intents WHERE handle_id=? AND task_attempt=?",
                (handle_id, task_attempt),
            ).fetchone()
            if (row is None or row["state"] != "STARTING"
                    or row["boot_id"] != self.boot_id
                    or control_group != "/system.slice/" + row["unit_name"]):
                raise GrantRejected("CPU_IDENTITY_SCOPE_UNVERIFIED_HOLD")
            db.execute(
                """INSERT INTO cpu_unit_identities
                   (handle_id,invocation_id,control_group,main_pid,recorded_at)
                   VALUES (?,?,?,?,?)""",
                (handle_id, invocation_id, control_group, main_pid, int(time.time())),
            )
            changed = db.execute(
                """UPDATE execution_intents
                   SET state='RUNNING',event_seq=event_seq+1
                   WHERE handle_id=? AND task_attempt=? AND state='STARTING'""",
                (handle_id, task_attempt),
            ).rowcount
            if changed != 1:
                raise GrantRejected("CPU_IDENTITY_CONCURRENT_CHANGE_HOLD")
            db.commit()

    def cpu_identity(self, handle_id: str, task_attempt: int) -> dict:
        with closing(self._connect()) as db:
            row = db.execute(
                """SELECT i.*, o.invocation_id,o.control_group,o.main_pid
                   FROM execution_intents i
                   JOIN cpu_unit_identities o ON o.handle_id=i.handle_id
                   WHERE i.handle_id=? AND i.task_attempt=?""",
                (handle_id, task_attempt),
            ).fetchone()
        if (row is None or row["boot_id"] != self.boot_id
                or row["state"] != "RUNNING"):
            raise GrantRejected("CPU_IDENTITY_NOT_VERIFIED_HOLD")
        return {"handle_id": handle_id, "task_attempt": task_attempt,
                "unit_name": row["unit_name"],
                "invocation_id": row["invocation_id"],
                "control_group": row["control_group"],
                "main_pid": int(row["main_pid"])}

    def mark_cpu_unknown(self, handle_id: str, task_attempt: int) -> None:
        """Crash/launch failure is UNKNOWN, *never* recyclable PREPARED."""
        with closing(self._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                """UPDATE execution_intents
                   SET state='UNKNOWN',event_seq=event_seq+1
                   WHERE handle_id=? AND task_attempt=?
                     AND state IN ('STARTING','RUNNING')""",
                (handle_id, task_attempt),
            )
            db.commit()
