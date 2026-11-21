"""Phase 1B-2: opt-in, read-only central authorization for a fixed CPU trial.

This is *not* an API endpoint. Keys must be supplied by trusted central
configuration (not Agent JSON); nothing imports or enables the issuer in the
existing production execution path. It never mutates tasks or reservations.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import json
import re
import sqlite3

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .os_supervisor_authorization import (
    PURPOSE, GrantRejected, _claims_payload,
)
from .service_nodes import HEARTBEAT_TTL_SECONDS, verify_service_node_token

# Deliberately cannot match ordinary production conversion resource keys.
_CPU_TEST_RESOURCE = "supervisor-cpu-v1"
_MAX_GRANT_SECONDS = 15
_NODE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TASK_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{7,127}$")


def _parse_utc(value: object) -> datetime:
    try:
        raw = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if raw.tzinfo is None:
            raise ValueError("no timezone")
        return raw.astimezone(timezone.utc)
    except (TypeError, ValueError) as exc:
        raise GrantRejected("CENTRAL_GRANT_DATE_INVALID_HOLD") from exc


class CentralExecutionGrantIssuer:
    """Signs only current *execution* leases from the existing tasks table.

    The central assignment generation is intentionally not accepted. A signed
    grant only authorizes a short registration window; a later OS launch must
    additionally revalidate its central lease and independently verify cgroup
    identity. This cannot release REMOTE_AGENT_STOP_UNVERIFIED.
    """

    def __init__(self, task_repository, private_key: Ed25519PrivateKey, *,
                 cpu_trial_enabled: bool = False):
        self.repository = task_repository
        if not isinstance(private_key, Ed25519PrivateKey):
            raise GrantRejected("CENTRAL_SIGNER_UNTRUSTED_HOLD")
        self._private_key = private_key
        self.enabled = cpu_trial_enabled is True

    def issue(self, *, task_id: str, task_attempt: int, node_id: str,
              node_token: str, execution_lease_token: str,
              boot_id: str, challenge: str,
              now: datetime | None = None) -> dict:
        if not self.enabled:
            raise GrantRejected("CENTRAL_CPU_ISSUER_DISABLED_HOLD")
        if (not isinstance(task_id, str) or not _TASK_ID.fullmatch(task_id)
                or type(task_attempt) is not int or task_attempt <= 0
                or not isinstance(node_id, str) or not _NODE_ID.fullmatch(node_id)
                or not isinstance(node_token, str) or not node_token
                or not isinstance(execution_lease_token, str) or not execution_lease_token
                or not isinstance(challenge, str) or not re.fullmatch(r"[0-9a-f]{32}", challenge)
                or not isinstance(boot_id, str)):
            raise GrantRejected("CENTRAL_GRANT_REQUEST_INVALID_HOLD")
        current = now or datetime.now(timezone.utc)
        if not isinstance(current, datetime) or current.tzinfo is None:
            raise GrantRejected("CENTRAL_GRANT_CLOCK_INVALID_HOLD")
        current = current.astimezone(timezone.utc)
        with closing(self.repository._connect()) as database:
            try:
                # Read one consistent authoritative snapshot; no writer lock,
                # no parallel scheduler or second ownership transaction.
                database.execute("BEGIN")
                task = database.execute(
                    """SELECT task_id,kind,status,stage,attempt,worker_id,
                              lease_token,lease_expires_at,resource_key
                       FROM tasks WHERE task_id=?""", (task_id,),
                ).fetchone()
                node = database.execute(
                    """SELECT node_id,connection_mode,enabled,token_hash,
                              last_heartbeat_at,allowed_capabilities,reported_capabilities
                       FROM service_nodes WHERE node_id=?""", (node_id,),
                ).fetchone()
                if task is None or node is None:
                    raise GrantRejected("CENTRAL_GRANT_OWNER_NOT_FOUND_HOLD")
                if (task["kind"] != "MODEL_CONVERSION"
                        or task["resource_key"] != _CPU_TEST_RESOURCE
                        or task["status"] != "RUNNING" or task["stage"] != "running"):
                    raise GrantRejected("CENTRAL_GRANT_TASK_NOT_CPU_TRIAL_HOLD")
                if (int(task["attempt"]) != task_attempt
                        or task["worker_id"] != "agent:" + node_id):
                    raise GrantRejected("CENTRAL_GRANT_ATTEMPT_OR_WORKER_MISMATCH_HOLD")
                if (not isinstance(task["lease_token"], str)
                        or not hmac.compare_digest(
                            task["lease_token"], execution_lease_token)):
                    raise GrantRejected("CENTRAL_GRANT_EXECUTION_LEASE_MISMATCH_HOLD")
                if (node["connection_mode"] != "agent" or int(node["enabled"]) != 1
                        or not verify_service_node_token(
                            node_id, node_token, str(node["token_hash"] or ""))):
                    raise GrantRejected("CENTRAL_GRANT_AGENT_NOT_AUTHORIZED_HOLD")
                try:
                    capabilities = set(json.loads(node["allowed_capabilities"]))
                    reported = set(json.loads(node["reported_capabilities"]))
                except (TypeError, ValueError) as exc:
                    raise GrantRejected("CENTRAL_GRANT_CAPABILITIES_INVALID_HOLD") from exc
                if "conversion" not in capabilities & reported:
                    raise GrantRejected("CENTRAL_GRANT_NODE_CAPABILITY_MISSING_HOLD")
                heartbeat = _parse_utc(node["last_heartbeat_at"])
                if not 0 <= (current - heartbeat).total_seconds() < HEARTBEAT_TTL_SECONDS:
                    raise GrantRejected("CENTRAL_GRANT_NODE_OFFLINE_HOLD")
                expires = _parse_utc(task["lease_expires_at"])
                # Never authorize beyond the original execution lease.
                expires_at = min(int((current + timedelta(seconds=_MAX_GRANT_SECONDS)).timestamp()),
                                 int(expires.timestamp()))
                now_epoch = int(current.timestamp())
                if expires_at <= now_epoch + 2:
                    raise GrantRejected("CENTRAL_GRANT_LEASE_TOO_CLOSE_HOLD")
                claims = {
                    "purpose": PURPOSE, "issued_at": now_epoch, "expires_at": expires_at,
                    "task_id": task_id, "task_attempt": task_attempt,
                    "node_id": node_id, "worker_id": "agent:" + node_id,
                    "execution_lease_sha256": hashlib.sha256(
                        execution_lease_token.encode("utf-8")).hexdigest(),
                    "gpu_uuid": "CPU_ONLY", "boot_id": boot_id,
                    "challenge": challenge, "runner_profile": "fixed-cpu-v1",
                }
                signature = self._private_key.sign(_claims_payload(claims)).hex()
                database.commit()
            except (sqlite3.Error, KeyError) as exc:
                raise GrantRejected("CENTRAL_GRANT_DB_UNVERIFIED_HOLD") from exc
        return {"claims": claims, "signature": signature}
