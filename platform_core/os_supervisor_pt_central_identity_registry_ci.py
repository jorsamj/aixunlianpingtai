"""2C-03E: TEST-ONLY independently registered ORIGINAL PT OS identity.

No production API, node authentication, durable central registration, central
recovery, result publication, GPU release, or second scheduler is implemented.
The central registry here is an isolated SQLite :memory: test database, not
the real TaskRepository storage. It rejects unregistered Agent-supplied
boot/InvocationID/PID and permits one central STOP grant issuance only.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

from .os_supervisor_authorization import GrantRejected
from .os_supervisor_pt_export_grant import PT_TEST_RESOURCE
from .os_supervisor_pt_export_launch import PtExportJournal
from .os_supervisor_pt_stop_grant import CentralPtStopTrialIssuer
from .task_runtime import TaskRepository

_PURPOSE = "changlian-ci-original-pt-os-identity-registration-v1"
_DOMAIN = b"changlian-ci-original-pt-os-identity-registration-v1\x00"
_HEX32 = re.compile(r"[0-9a-f]{32}\Z")
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_BOOT = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}\Z")
_NODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_FIELDS = frozenset({
    "purpose", "test_only", "registration_nonce",
    "task_id", "task_attempt", "node_id", "worker_id",
    "execution_lease_sha256", "handle_id", "boot_id", "unit_name",
    "invocation_id", "control_group", "main_pid",
    "launch_grant_digest", "issued_at", "expires_at",
})


def _hold(reason: str) -> None:
    raise GrantRejected("PT_CI_CENTRAL_OS_REGISTRATION_" + reason + "_HOLD")


def _bytes(claims: object) -> bytes:
    if not isinstance(claims, dict) or set(claims) != _FIELDS:
        _hold("SCHEMA")
    handle = claims["handle_id"]
    unit = claims["unit_name"]
    if (claims["purpose"] != _PURPOSE or claims["test_only"] is not True
            or not isinstance(claims["registration_nonce"], str)
            or not _HEX32.fullmatch(claims["registration_nonce"])
            or not isinstance(claims["task_id"], str)
            or not _TASK.fullmatch(claims["task_id"])
            or type(claims["task_attempt"]) is not int
            or claims["task_attempt"] <= 0
            or not isinstance(claims["node_id"], str)
            or not _NODE.fullmatch(claims["node_id"])
            or claims["worker_id"] != "agent:" + claims["node_id"]
            or not isinstance(claims["execution_lease_sha256"], str)
            or not _HEX64.fullmatch(claims["execution_lease_sha256"])
            or not isinstance(handle, str)
            or not _HEX32.fullmatch(handle)
            or not isinstance(claims["boot_id"], str)
            or not _BOOT.fullmatch(claims["boot_id"])
            or unit != "changlian-os-" + handle + ".service"
            or not isinstance(claims["invocation_id"], str)
            or not _HEX32.fullmatch(claims["invocation_id"])
            or claims["invocation_id"] == "0" * 32
            or claims["control_group"] != "/system.slice/" + unit
            or type(claims["main_pid"]) is not int
            or claims["main_pid"] <= 1
            or not isinstance(claims["launch_grant_digest"], str)
            or not _HEX64.fullmatch(claims["launch_grant_digest"])
            or type(claims["issued_at"]) is not int
            or type(claims["expires_at"]) is not int
            or not 0 < claims["expires_at"] - claims["issued_at"] <= 30):
        _hold("BOUNDARY")
    try:
        raw = _DOMAIN + json.dumps(
            claims, sort_keys=True, separators=(",", ":"), allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, OverflowError) as exc:
        raise GrantRejected("PT_CI_CENTRAL_OS_REGISTRATION_INVALID_JSON_HOLD") from exc
    if len(raw) > 4096:
        _hold("OVERSIZED")
    return raw


def _ci_host() -> bool:
    return (os.name == "posix" and hasattr(os, "geteuid")
            and os.geteuid() == 0
            and os.environ.get("GITHUB_ACTIONS") == "true"
            and os.environ.get("RUNNER_ENVIRONMENT") == "github-hosted")


class CiOnlyRootPtOriginalIdentityRegistration:
    """CI-only signing from exact root-owned PT journal, no supplied OS tuple."""

    def __init__(self, journal: PtExportJournal, *, isolated_ci_only=False):
        if (isolated_ci_only is not True or not _ci_host()
                or type(journal) is not PtExportJournal
                or journal.journal.test_only_unprivileged is not True):
            _hold("PRODUCTION_DISABLED")
        self.journal = journal
        self._key = Ed25519PrivateKey.generate()
        self.public_key = self._key.public_key()

    def sign_original(self, handle_id: str, task_attempt: int, *,
                      now: int | None = None) -> dict:
        identity = self.journal.verified_pt_identity(handle_id, task_attempt)
        with closing(self.journal.journal._connect()) as db:
            row = db.execute(
                """SELECT task_id,task_attempt,node_id,worker_id,lease_sha256,
                          boot_id,unit_name,state
                   FROM execution_intents
                   WHERE handle_id=? AND task_attempt=?""",
                (handle_id, task_attempt),
            ).fetchone()
        if (row is None or row["state"] != "RUNNING"
                or row["boot_id"] != identity["boot_id"]
                or row["unit_name"] != identity["unit_name"]):
            _hold("ROOT_ORIGINAL_NOT_RUNNING")
        wall = int(time.time()) if now is None else now
        if type(wall) is not int or wall <= 0:
            _hold("CLOCK_INVALID")
        claims = {
            "purpose": _PURPOSE, "test_only": True,
            "registration_nonce": secrets.token_hex(16),
            "task_id": row["task_id"], "task_attempt": row["task_attempt"],
            "node_id": row["node_id"], "worker_id": row["worker_id"],
            "execution_lease_sha256": row["lease_sha256"],
            "handle_id": handle_id, "boot_id": row["boot_id"],
            "unit_name": identity["unit_name"],
            "invocation_id": identity["invocation_id"],
            "control_group": identity["control_group"],
            "main_pid": identity["main_pid"],
            "launch_grant_digest": identity["launch_grant_digest"],
            "issued_at": wall, "expires_at": wall + 30,
        }
        return {"claims": claims, "signature": self._key.sign(_bytes(claims)).hex()}


class CiOnlyCentralPtOriginalRegistry:
    """One isolated original-identity registration and one STOP grant.

    Keeps only test metadata in :memory:, and continues to use the EXISTING
    TaskRepository / CentralPtStopTrialIssuer for task/lease authority.
    """

    def __init__(
        self, repository: TaskRepository, *,
        root_public_key: Ed25519PublicKey,
        central_key: Ed25519PrivateKey,
        isolated_ci_only=False,
    ):
        if (isolated_ci_only is not True or not _ci_host()
                or type(repository) is not TaskRepository
                or not isinstance(root_public_key, Ed25519PublicKey)
                or not isinstance(central_key, Ed25519PrivateKey)):
            _hold("PRODUCTION_DISABLED")
        self.repository = repository
        self.root_public_key = root_public_key
        self.central = CentralPtStopTrialIssuer(
            repository, central_key, isolated_test_only=True,
        )
        self._lock = threading.RLock()
        self._db = sqlite3.connect(":memory:", check_same_thread=False,
                                   isolation_level=None)
        if self._db.execute("PRAGMA database_list").fetchone()[2] != "":
            _hold("IN_MEMORY_ONLY")
        self._db.execute(
            """CREATE TABLE registrations (
                task_id TEXT NOT NULL, task_attempt INTEGER NOT NULL,
                handle_id TEXT NOT NULL UNIQUE, claims_json TEXT NOT NULL,
                registration_nonce TEXT NOT NULL UNIQUE,
                stop_issued_at INTEGER,
                PRIMARY KEY(task_id, task_attempt)
            )""",
        )

    def _original_task(self, claims: Mapping[str, object], *,
                       require_running: bool) -> None:
        with closing(self.repository._connect()) as db:
            task = db.execute(
                """SELECT task_id,attempt,kind,resource_key,worker_id,
                          lease_token,lease_expires_at,status,stage
                   FROM tasks WHERE task_id=?""", (claims["task_id"],),
            ).fetchone()
        if (task is None or task["task_id"] != claims["task_id"]
                or task["attempt"] != claims["task_attempt"]
                or task["kind"] != "MODEL_CONVERSION"
                or task["resource_key"] != PT_TEST_RESOURCE
                or task["worker_id"] != claims["worker_id"]
                or not isinstance(task["lease_token"], str)
                or hashlib.sha256(task["lease_token"].encode("utf-8")).hexdigest()
                    != claims["execution_lease_sha256"]
                or (require_running and (task["status"] != "RUNNING"
                                         or task["stage"] != "running"))):
            _hold("ORIGINAL_TASK_OR_LEASE_CHANGED")

    def register(self, signed_original: object, *, now: int | None = None) -> dict:
        if (not isinstance(signed_original, dict)
                or set(signed_original) != {"claims", "signature"}
                or not isinstance(signed_original["signature"], str)
                or not re.fullmatch(r"[0-9a-f]{128}", signed_original["signature"])):
            _hold("ENVELOPE_INVALID")
        claims = signed_original["claims"]
        raw = _bytes(claims)
        now_seconds = int(time.time()) if now is None else now
        if (type(now_seconds) is not int
                or not claims["issued_at"] - 2 <= now_seconds < claims["expires_at"]):
            _hold("STALE_OR_FUTURE_IDENTITY")
        try:
            self.root_public_key.verify(
                bytes.fromhex(signed_original["signature"]), raw,
            )
        except InvalidSignature as exc:
            raise GrantRejected(
                "PT_CI_CENTRAL_OS_REGISTRATION_ROOT_SIGNATURE_UNTRUSTED_HOLD",
            ) from exc
        with self._lock:
            self._original_task(claims, require_running=True)
            try:
                self._db.execute(
                    """INSERT INTO registrations
                       (task_id,task_attempt,handle_id,claims_json,registration_nonce)
                       VALUES (?,?,?,?,?)""",
                    (claims["task_id"], claims["task_attempt"],
                     claims["handle_id"], json.dumps(claims, sort_keys=True),
                     claims["registration_nonce"]),
                )
            except sqlite3.IntegrityError as exc:
                raise GrantRejected(
                    "PT_CI_CENTRAL_OS_REGISTRATION_REPLAY_OR_DUPLICATE_HOLD",
                ) from exc
        return {
            "original_identity_registered_for_ci": True,
            "task_id": claims["task_id"],
            "task_attempt": claims["task_attempt"],
            "production_stop_allowed": False,
            "production_recovery_allowed": False,
        }

    def issue_original_stop(
        self, *, task_id: str, task_attempt: int, node_id: str,
        root_stop_challenge: str,
    ) -> dict:
        """NO OS-scope arguments. Read registered root identity and central owner."""
        if (not isinstance(task_id, str) or not _TASK.fullmatch(task_id)
                or type(task_attempt) is not int or task_attempt <= 0
                or not isinstance(node_id, str) or not _NODE.fullmatch(node_id)
                or not isinstance(root_stop_challenge, str)
                or not _HEX32.fullmatch(root_stop_challenge)):
            _hold("ISSUE_ARGUMENTS_INVALID")
        with self._lock:
            row = self._db.execute(
                """SELECT claims_json,stop_issued_at FROM registrations
                   WHERE task_id=? AND task_attempt=?""",
                (task_id, task_attempt),
            ).fetchone()
            if row is None or row[1] is not None:
                _hold("ORIGINAL_UNREGISTERED_OR_STOP_REPLAY")
            claims = json.loads(row[0])
            if claims["node_id"] != node_id:
                _hold("REGISTERED_NODE_MISMATCH")
            self._original_task(claims, require_running=False)
            now_seconds = int(time.time())
            signed = self.central.issue(
                task_id=task_id, task_attempt=task_attempt, node_id=node_id,
                boot_id=claims["boot_id"], handle_id=claims["handle_id"],
                invocation_id=claims["invocation_id"],
                main_pid=claims["main_pid"], challenge=root_stop_challenge,
                now=datetime.fromtimestamp(now_seconds, timezone.utc),
            )
            issued_claims = signed.get("claims")
            if (not isinstance(issued_claims, Mapping)
                    or any(issued_claims.get(k) != claims[k] for k in (
                        "task_id", "task_attempt", "node_id", "worker_id",
                        "execution_lease_sha256", "boot_id", "handle_id",
                        "unit_name", "invocation_id", "control_group",
                        "main_pid",
                    ))):
                _hold("SIGNED_SCOPE_NOT_REGISTERED")
            result = self._db.execute(
                """UPDATE registrations SET stop_issued_at=?
                   WHERE task_id=? AND task_attempt=? AND stop_issued_at IS NULL""",
                (now_seconds, task_id, task_attempt),
            ).rowcount
            if result != 1:
                _hold("STOP_GRANT_CAS_LOST")
        return signed
