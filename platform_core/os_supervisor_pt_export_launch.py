"""2D-2D2B2B-2A isolated PT export rechecked launch *claim*.

No SupervisorService/Runner imports this module. The original root-owned
ExecutionJournal is the ONLY OS intent store; its existing UNIQUE(task_id,
task_attempt) fences simultaneous fixed CPU and PT registrations. Claiming a
PT launch is a durable one-shot audit CAS, NOT permission to run PT pickle.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime
import hashlib
import json
import secrets
import sqlite3
import time
from typing import Mapping

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

from .os_supervisor_authorization import GrantRejected
from .os_supervisor_journal import ExecutionJournal
from .os_supervisor_pt_export_grant import (
    CentralPtExportAdmissionIssuer, PT_PROFILE, PT_PURPOSE, _BINDING,
    _check_binding, _canonical, _hold, verify_pt_export_admission_grant,
)

_LAUNCH_PURPOSE = "changlian-pt-export-cpu-launch-rechecked-v1"
_LAUNCH_DOMAIN = b"changlian-pt-export-cpu-launch-rechecked-v1\x00"
_LAUNCH_FIELDS = _BINDING | {
    "purpose", "issued_at", "expires_at", "handle_id",
    "registered_grant_digest",
}
_PT_SCHEMA = """
-- Additional evidence indexed by ORIGINAL execution_intents.handle_id.
-- No second owner, scheduler, attempt or runnable service in these tables.
CREATE TABLE IF NOT EXISTS pt_export_admission_challenges (
    challenge TEXT PRIMARY KEY,
    binding_json TEXT NOT NULL,
    expires_at INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS pt_export_bound_inputs (
    handle_id TEXT PRIMARY KEY REFERENCES execution_intents(handle_id),
    binding_json TEXT NOT NULL,
    registered_grant_digest TEXT NOT NULL,
    manifest_sha256 TEXT NOT NULL,
    source_sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pt_export_launch_challenges (
    handle_id TEXT PRIMARY KEY REFERENCES execution_intents(handle_id),
    challenge TEXT NOT NULL UNIQUE,
    issued_at INTEGER NOT NULL,
    expires_at INTEGER NOT NULL
);
-- Immutable audit of the exact rechecked signature consumed by the one CAS.
CREATE TABLE IF NOT EXISTS pt_export_claims (
    handle_id TEXT PRIMARY KEY REFERENCES execution_intents(handle_id),
    launch_grant_digest TEXT NOT NULL,
    claimed_at INTEGER NOT NULL
);
-- OS identity lives in SAME root journal and is NOT a second task owner.
CREATE TABLE IF NOT EXISTS pt_export_unit_identities (
    handle_id TEXT PRIMARY KEY REFERENCES execution_intents(handle_id),
    invocation_id TEXT NOT NULL UNIQUE,
    control_group TEXT NOT NULL,
    main_pid INTEGER NOT NULL CHECK(main_pid>1),
    recorded_at INTEGER NOT NULL
);
"""
_MAX_ACTIVE_CHALLENGES = 512
_MAX_NODE_CHALLENGES = 64
_MAX_ATTEMPT_CHALLENGES = 4
_MAX_LAUNCH_GRANT_SECONDS = 15


def _now(value: int | None) -> int:
    current = int(time.time()) if value is None else value
    if type(current) is not int:
        _hold("CLOCK_INVALID")
    return current


def _launch_payload(claims: Mapping[str, object]) -> bytes:
    return _LAUNCH_DOMAIN + json.dumps(
        claims, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("utf-8")


def issue_pt_export_launch_grant(
    issuer: CentralPtExportAdmissionIssuer, *, task_id: str, task_attempt: int,
    node_id: str, node_token: str, execution_lease_token: str,
    boot_id: str, challenge: str, handle_id: str,
    registered_grant_digest: str, now: datetime | None = None,
) -> dict:
    """Central recheck: re-read ORIGINAL task/lease/source before launch sign.

    The fresh admission is used for a new trusted central snapshot and is NOT
    itself a valid launch grant. Signature is domain separated and additionally
    binds the one registered OS handle plus initial admission digest.
    """
    if (not isinstance(issuer, CentralPtExportAdmissionIssuer)
            or not isinstance(handle_id, str) or len(handle_id) != 32
            or not all(c in "0123456789abcdef" for c in handle_id)
            or not isinstance(registered_grant_digest, str)
            or len(registered_grant_digest) != 64
            or not all(c in "0123456789abcdef" for c in registered_grant_digest)):
        _hold("LAUNCH_REQUEST_INVALID")
    fresh = issuer.issue(
        task_id=task_id, task_attempt=task_attempt, node_id=node_id,
        node_token=node_token, execution_lease_token=execution_lease_token,
        boot_id=boot_id, challenge=challenge, now=now,
    )
    signed_claims = fresh["claims"]
    if signed_claims["purpose"] != PT_PURPOSE:
        _hold("LAUNCH_CENTRAL_RECHECK_INVALID")
    claims = {
        **{k: signed_claims[k] for k in _BINDING},
        "purpose": _LAUNCH_PURPOSE,
        "issued_at": signed_claims["issued_at"],
        "expires_at": signed_claims["expires_at"],
        "handle_id": handle_id,
        "registered_grant_digest": registered_grant_digest,
    }
    payload = _launch_payload(claims)
    if len(payload) > 4096:
        _hold("LAUNCH_PAYLOAD_OVERSIZE")
    return {
        "claims": claims,
        "signature": issuer._private_key.sign(payload).hex(),
    }


def verify_pt_export_launch_grant(
    envelope: object, *, trusted_public_key: Ed25519PublicKey,
    expected_binding: Mapping[str, object], handle_id: str,
    registered_grant_digest: str, now: int,
    launch_challenge_issued_at: int,
) -> str:
    """Verify root-frozen input AND newer central source/lease recheck."""
    if (not isinstance(trusted_public_key, Ed25519PublicKey)
            or type(now) is not int
            or type(launch_challenge_issued_at) is not int
            or not isinstance(expected_binding, Mapping)):
        _hold("LAUNCH_TRUST_CONTEXT_MISSING")
    _check_binding(expected_binding)
    if not isinstance(envelope, dict) or set(envelope) != {"claims", "signature"}:
        _hold("LAUNCH_ENVELOPE_INVALID")
    claims = envelope["claims"]
    if not isinstance(claims, dict) or set(claims) != _LAUNCH_FIELDS:
        _hold("LAUNCH_SCHEMA_INVALID")
    _check_binding({k: claims[k] for k in _BINDING})
    if (claims["purpose"] != _LAUNCH_PURPOSE
            or claims["handle_id"] != handle_id
            or claims["registered_grant_digest"] != registered_grant_digest
            or any(claims[k] != expected_binding[k] for k in _BINDING)
            or type(claims["issued_at"]) is not int
            or type(claims["expires_at"]) is not int
            or not 0 < claims["expires_at"] - claims["issued_at"]
                 <= _MAX_LAUNCH_GRANT_SECONDS
            or not claims["issued_at"] - 5 <= now < claims["expires_at"]
            or claims["issued_at"] < launch_challenge_issued_at
            or claims["issued_at"] > now
            or now - claims["issued_at"] > 3):
        _hold("LAUNCH_SCOPE_OR_FRESHNESS_MISMATCH")
    signature = envelope["signature"]
    if (not isinstance(signature, str) or len(signature) != 128
            or not all(c in "0123456789abcdef" for c in signature)):
        _hold("LAUNCH_SIGNATURE_INVALID")
    signed = _launch_payload(claims)
    if len(signed) > 4096:
        _hold("LAUNCH_PAYLOAD_OVERSIZE")
    try:
        trusted_public_key.verify(bytes.fromhex(signature), signed)
    except InvalidSignature as exc:
        raise GrantRejected("PT_GRANT_LAUNCH_SIGNATURE_INVALID_HOLD") from exc
    return hashlib.sha256(signed).hexdigest()


class PtExportJournal:
    """PT-only stage beside the existing root-owned, full-sync OS journal.

    This helper must never be constructed as a second file/owner. Production
    default code does not instantiate it and none of its methods starts units.
    """

    def __init__(self, journal: ExecutionJournal):
        if type(journal) is not ExecutionJournal:
            _hold("ORIGINAL_JOURNAL_REQUIRED")
        self.journal = journal
        with closing(self.journal._connect()) as db:
            db.executescript(_PT_SCHEMA)

    def issue_admission_challenge(
        self, binding: Mapping[str, object], *, now: int | None = None,
    ) -> str:
        current = _now(now)
        if not isinstance(binding, Mapping) or set(binding) != (_BINDING - {"challenge"}):
            _hold("ADMISSION_BINDING_INVALID")
        _check_binding({**binding, "challenge": "0" * 32})
        if binding["boot_id"] != self.journal.boot_id:
            _hold("ADMISSION_BOOT_MISMATCH")
        nonce = secrets.token_hex(16)
        with closing(self.journal._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "DELETE FROM pt_export_admission_challenges WHERE expires_at <= ?",
                (current,),
            )
            active = db.execute(
                "SELECT binding_json FROM pt_export_admission_challenges WHERE expires_at > ?",
                (current,),
            ).fetchall()
            if len(active) >= _MAX_ACTIVE_CHALLENGES:
                _hold("ADMISSION_CHALLENGE_QUOTA")
            node_count = attempt_count = 0
            try:
                for entry in active:
                    old = json.loads(entry["binding_json"])
                    if old["node_id"] == binding["node_id"]:
                        node_count += 1
                    if (old["task_id"] == binding["task_id"]
                            and old["task_attempt"] == binding["task_attempt"]):
                        attempt_count += 1
            except (ValueError, TypeError, KeyError) as exc:
                raise GrantRejected("PT_GRANT_ADMISSION_JOURNAL_CORRUPT_HOLD") from exc
            if node_count >= _MAX_NODE_CHALLENGES or attempt_count >= _MAX_ATTEMPT_CHALLENGES:
                _hold("ADMISSION_CHALLENGE_SCOPE_QUOTA")
            db.execute(
                """INSERT INTO pt_export_admission_challenges
                   (challenge,binding_json,expires_at) VALUES (?,?,?)""",
                (nonce, json.dumps(dict(binding), sort_keys=True, separators=(",", ":")),
                 current + 90),
            )
            db.commit()
        return nonce

    def register_admission(
        self, envelope: object, *, trusted_public_key: Ed25519PublicKey,
        now: int | None = None,
    ) -> dict:
        current = _now(now)
        if not isinstance(envelope, dict) or not isinstance(envelope.get("claims"), dict):
            _hold("REGISTER_ENVELOPE_INVALID")
        challenge = envelope["claims"].get("challenge")
        if not isinstance(challenge, str):
            _hold("REGISTER_CHALLENGE_MISSING")
        with closing(self.journal._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT binding_json,expires_at
                   FROM pt_export_admission_challenges WHERE challenge=?""",
                (challenge,),
            ).fetchone()
            if row is None or current >= row["expires_at"]:
                _hold("REGISTER_CHALLENGE_EXPIRED")
            try:
                expected = json.loads(row["binding_json"])
            except (ValueError, TypeError) as exc:
                raise GrantRejected("PT_GRANT_REGISTER_BINDING_CORRUPT_HOLD") from exc
            expected["challenge"] = challenge
            verified = verify_pt_export_admission_grant(
                envelope, trusted_public_key=trusted_public_key,
                expected_binding=expected, now=current,
            )
            old = db.execute(
                """SELECT handle_id,grant_digest,challenge FROM execution_intents
                   WHERE task_id=? AND task_attempt=?""",
                (verified.task_id, verified.task_attempt),
            ).fetchone()
            if old is not None:
                pt = db.execute(
                    "SELECT handle_id FROM pt_export_bound_inputs WHERE handle_id=?",
                    (old["handle_id"],),
                ).fetchone()
                if (pt is None or old["grant_digest"] != verified.grant_digest
                        or old["challenge"] != challenge):
                    _hold("REGISTER_TASK_ATTEMPT_ALREADY_RESERVED")
                db.commit()
                return {
                    "handle_id": old["handle_id"],
                    "task_attempt": verified.task_attempt,
                    "replayed": True, "state": "UNKNOWN",
                    "launch_authorized": False,
                }
            handle = secrets.token_hex(16)
            db.execute(
                """INSERT INTO execution_intents
                   (handle_id,task_id,task_attempt,node_id,worker_id,
                    lease_sha256,grant_digest,challenge,boot_id,unit_name,
                    state,event_seq,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (handle, verified.task_id, verified.task_attempt,
                 expected["node_id"], expected["worker_id"],
                 expected["execution_lease_sha256"], verified.grant_digest,
                 challenge, expected["boot_id"],
                 "changlian-os-" + handle + ".service", "PREPARED", 1, current),
            )
            binding = {k: expected[k] for k in _BINDING - {"challenge"}}
            db.execute(
                """INSERT INTO pt_export_bound_inputs
                   (handle_id,binding_json,registered_grant_digest,
                    manifest_sha256,source_sha256) VALUES (?,?,?,?,?)""",
                (handle,
                 json.dumps(binding, sort_keys=True, separators=(",", ":")),
                 verified.grant_digest, verified.manifest_sha256,
                 verified.source_sha256),
            )
            db.commit()
        return {
            "handle_id": handle, "task_attempt": verified.task_attempt,
            "replayed": False, "state": "UNKNOWN",
            "launch_authorized": False,
        }

    def issue_launch_challenge(
        self, handle_id: str, task_attempt: int, *, now: int | None = None,
    ) -> str:
        current = _now(now)
        if not isinstance(handle_id, str) or type(task_attempt) is not int:
            _hold("LAUNCH_CHALLENGE_REQUEST_INVALID")
        with closing(self.journal._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT i.boot_id,i.state FROM execution_intents i
                     JOIN pt_export_bound_inputs p ON i.handle_id=p.handle_id
                    WHERE i.handle_id=? AND i.task_attempt=?""",
                (handle_id, task_attempt),
            ).fetchone()
            if (row is None or row["state"] != "PREPARED"
                    or row["boot_id"] != self.journal.boot_id):
                _hold("LAUNCH_INTENT_NOT_PREPARED")
            existing = db.execute(
                """SELECT challenge,expires_at FROM pt_export_launch_challenges
                   WHERE handle_id=?""", (handle_id,),
            ).fetchone()
            if existing is not None:
                if current >= existing["expires_at"]:
                    _hold("LAUNCH_CHALLENGE_EXPIRED")
                db.commit()
                return existing["challenge"]
            nonce = secrets.token_hex(16)
            db.execute(
                """INSERT INTO pt_export_launch_challenges
                   (handle_id,challenge,issued_at,expires_at) VALUES (?,?,?,?)""",
                (handle_id, nonce, current, current + 15),
            )
            db.commit()
            return nonce

    def claim_rechecked_launch(
        self, handle_id: str, task_attempt: int, launch_envelope: object, *,
        trusted_public_key: Ed25519PublicKey, now: int | None = None,
    ) -> dict:
        """Verify central fresh grant; consume the single OS intent with CAS.

        No systemd-run call here. STARTING without a protected PT executor
        remains a deliberate UNKNOWN/HOLD and cannot publish a result.
        """
        current = _now(now)
        if not isinstance(handle_id, str) or type(task_attempt) is not int:
            _hold("CLAIM_REQUEST_INVALID")
        with closing(self.journal._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT i.*,p.binding_json,p.registered_grant_digest
                   FROM execution_intents i JOIN pt_export_bound_inputs p
                        ON i.handle_id=p.handle_id
                  WHERE i.handle_id=? AND i.task_attempt=?""",
                (handle_id, task_attempt),
            ).fetchone()
            nonce = db.execute(
                """SELECT challenge,issued_at,expires_at
                   FROM pt_export_launch_challenges WHERE handle_id=?""",
                (handle_id,),
            ).fetchone()
            if (row is None or nonce is None or row["state"] != "PREPARED"
                    or row["boot_id"] != self.journal.boot_id
                    or current >= nonce["expires_at"]):
                _hold("CLAIM_NOT_PREPARED_OR_EXPIRED")
            try:
                binding = json.loads(row["binding_json"])
            except (ValueError, TypeError) as exc:
                raise GrantRejected("PT_GRANT_CLAIM_BOUND_INPUT_CORRUPT_HOLD") from exc
            binding["challenge"] = nonce["challenge"]
            verified_digest = verify_pt_export_launch_grant(
                launch_envelope, trusted_public_key=trusted_public_key,
                expected_binding=binding, handle_id=handle_id,
                registered_grant_digest=row["registered_grant_digest"],
                now=current, launch_challenge_issued_at=nonce["issued_at"],
            )
            if (row["grant_digest"] != row["registered_grant_digest"]
                    or row["task_id"] != binding["task_id"]
                    or row["task_attempt"] != binding["task_attempt"]
                    or row["lease_sha256"] != binding["execution_lease_sha256"]
                    or row["worker_id"] != binding["worker_id"]
                    or row["node_id"] != binding["node_id"]):
                _hold("CLAIM_JOURNAL_SCOPE_MISMATCH")
            changed = db.execute(
                """UPDATE execution_intents
                      SET state='STARTING',event_seq=event_seq+1
                    WHERE handle_id=? AND task_attempt=? AND state='PREPARED'""",
                (handle_id, task_attempt),
            ).rowcount
            if changed != 1:
                _hold("CLAIM_CONCURRENT_REPLAY")
            db.execute(
                """INSERT INTO pt_export_claims
                   (handle_id,launch_grant_digest,claimed_at)
                   VALUES (?,?,?)""",
                (handle_id, verified_digest, current),
            )
            db.commit()
        return {
            "handle_id": handle_id, "task_attempt": task_attempt,
            "state": "UNKNOWN", "launch_authorized": False,
            "os_executor_connected": False, "replayed": False,
            "launch_grant_digest": verified_digest,
        }

    def record_pt_systemd_identity(
        self, handle_id: str, task_attempt: int, *,
        invocation_id: str, control_group: str, main_pid: int,
    ) -> None:
        """Record systemd identity after one-shot CAS and a live OS snapshot.

        Missing OS confirmation keeps STARTING/UNKNOWN; NEVER starts again.
        The receipt carries no trusted stop, publish, or recovery permission.
        """
        if (not isinstance(handle_id, str)
                or not isinstance(invocation_id, str)
                or len(invocation_id) != 32
                or any(x not in "0123456789abcdef" for x in invocation_id)
                or type(task_attempt) is not int
                or type(main_pid) is not int or main_pid <= 1
                or control_group != "/system.slice/changlian-os-" + handle_id + ".service"):
            _hold("IDENTITY_FORMAT_UNVERIFIED")
        with closing(self.journal._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT i.boot_id,i.state,i.task_attempt,i.unit_name,
                          c.launch_grant_digest,
                          o.invocation_id,o.control_group,o.main_pid
                   FROM execution_intents i
                   JOIN pt_export_bound_inputs p ON p.handle_id=i.handle_id
                   JOIN pt_export_claims c ON c.handle_id=i.handle_id
                   LEFT JOIN pt_export_unit_identities o ON o.handle_id=i.handle_id
                   WHERE i.handle_id=? AND i.task_attempt=?""",
                (handle_id, task_attempt),
            ).fetchone()
            if (row is None or row["boot_id"] != self.journal.boot_id
                    or row["unit_name"] != "changlian-os-" + handle_id + ".service"
                    or row["task_attempt"] != task_attempt):
                _hold("IDENTITY_JOURNAL_SCOPE_MISMATCH")
            if row["state"] == "RUNNING":
                if (row["invocation_id"] != invocation_id
                        or row["control_group"] != control_group
                        or row["main_pid"] != main_pid):
                    _hold("IDENTITY_ALREADY_DIFFERENT")
                db.commit()
                return
            if row["state"] != "STARTING" or row["invocation_id"] is not None:
                _hold("IDENTITY_REPLAY_OR_NOT_STARTING")
            db.execute(
                """INSERT INTO pt_export_unit_identities
                   (handle_id,invocation_id,control_group,main_pid,recorded_at)
                   VALUES (?,?,?,?,?)""",
                (handle_id, invocation_id, control_group, main_pid,
                 int(time.time())),
            )
            changed = db.execute(
                """UPDATE execution_intents SET state='RUNNING',event_seq=event_seq+1
                   WHERE handle_id=? AND task_attempt=? AND state='STARTING'""",
                (handle_id, task_attempt),
            ).rowcount
            if changed != 1:
                _hold("IDENTITY_CONCURRENT_CHANGE")
            db.commit()

    def verified_pt_identity(self, handle_id: str, task_attempt: int) -> dict:
        """Read only exact original PT systemd identity, not stop evidence."""
        if not isinstance(handle_id, str) or type(task_attempt) is not int:
            _hold("IDENTITY_READ_SCOPE_INVALID")
        with closing(self.journal._connect()) as db:
            row = db.execute(
                """SELECT i.boot_id,i.state,i.unit_name,c.launch_grant_digest,
                          o.invocation_id,o.control_group,o.main_pid
                   FROM execution_intents i
                   JOIN pt_export_bound_inputs p ON p.handle_id=i.handle_id
                   JOIN pt_export_claims c ON c.handle_id=i.handle_id
                   JOIN pt_export_unit_identities o ON o.handle_id=i.handle_id
                   WHERE i.handle_id=? AND i.task_attempt=?""",
                (handle_id, task_attempt),
            ).fetchone()
        if (row is None or row["boot_id"] != self.journal.boot_id
                or row["state"] != "RUNNING"
                or row["unit_name"] != "changlian-os-" + handle_id + ".service"
                or row["control_group"] != "/system.slice/" + row["unit_name"]):
            _hold("IDENTITY_UNVERIFIED")
        return {
            "handle_id": handle_id, "task_attempt": task_attempt,
            "unit_name": row["unit_name"],
            "invocation_id": row["invocation_id"],
            "control_group": row["control_group"],
            "main_pid": int(row["main_pid"]),
            "launch_grant_digest": row["launch_grant_digest"],
            "trusted_stop_receipt_available": False,
            "result_publish_allowed": False,
        }
