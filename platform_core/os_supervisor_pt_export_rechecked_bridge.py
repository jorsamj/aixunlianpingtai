"""2C-01: CI-only wiring of ORIGINAL PT central launch CAS to real systemd.

This module is NOT registered with the production Agent, API or Supervisor.
It accepts a separately issued signed central launch envelope, never central
credentials or an arbitrary command. It stages only the pilot's trusted
CI-generated pickle and consumes the one root-owned OS intent before systemd.
"""
from __future__ import annotations

from contextlib import closing
import hashlib
import json
import os
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .os_supervisor_authorization import GrantRejected
from .os_supervisor_cpu_pt_export_admission import (
    FrozenPtExportAdmission, VerifiedPtBytes,
)
from .os_supervisor_pt_export_grant import _BINDING, _check_binding, PT_PROFILE
from .os_supervisor_pt_export_launch import (
    PtExportJournal, verify_pt_export_launch_grant,
)
from .os_supervisor_pt_export_cpu_systemd_pilot import (
    IsolatedPtExportCpuPilot, StagedPtCpuFixture,
)

_FIXED_PARAMS = {
    "input_size": 32, "batch": 1, "opset": 12,
    "dynamic": False, "simplify": False,
}


def _hold(code: str) -> None:
    raise GrantRejected("PT_BRIDGE_" + code + "_HOLD")


class CiOnlyPtExportRecheckedBridge:
    """One OS-journal owner, one signed central launch, one real CI unit.

    Unlike production, the CI test builds its own trusted fixture. There is
    deliberately no method to supply user/Agent weights, URLs, argv or env.
    """

    def __init__(
        self, journal: PtExportJournal, pilot: IsolatedPtExportCpuPilot,
        trusted_public_key: Ed25519PublicKey, *, isolated_ci_only: bool = False,
    ):
        if (isolated_ci_only is not True
                or type(journal) is not PtExportJournal
                or type(pilot) is not IsolatedPtExportCpuPilot
                or not isinstance(trusted_public_key, Ed25519PublicKey)
                or os.name != "posix" or os.geteuid() != 0
                or journal.journal.test_only_unprivileged is not True):
            _hold("PRODUCTION_DISABLED")
        self.journal = journal
        self.pilot = pilot
        self.key = trusted_public_key

    def start(
        self, *, handle_id: str, task_attempt: int,
        central_launch_envelope: object, trusted_fixture: StagedPtCpuFixture,
    ) -> dict:
        """Fail closed before stage; CAS before any systemd-run.

        A crash after CAS (or a failed systemd-run/identity write) is UNKNOWN,
        never a reason to reuse the launch grant or create another unit.
        """
        if (type(handle_id) is not str or len(handle_id) != 32
                or any(c not in "0123456789abcdef" for c in handle_id)
                or type(task_attempt) is not int or task_attempt <= 0
                or type(trusted_fixture) is not StagedPtCpuFixture):
            _hold("START_SCOPE_INVALID")
        # Read the original durable journal, not a purported Agent binding.
        with closing(self.journal.journal._connect()) as db:
            row = db.execute(
                """SELECT i.task_id,i.task_attempt,i.node_id,i.worker_id,
                          i.lease_sha256,i.boot_id,i.state,i.unit_name,
                          p.binding_json,p.registered_grant_digest,
                          l.challenge,l.issued_at,l.expires_at
                   FROM execution_intents i
                   JOIN pt_export_bound_inputs p ON p.handle_id=i.handle_id
                   JOIN pt_export_launch_challenges l ON l.handle_id=i.handle_id
                   WHERE i.handle_id=? AND i.task_attempt=?""",
                (handle_id, task_attempt),
            ).fetchone()
        current = int(time.time())
        if (row is None or row["state"] != "PREPARED"
                or row["boot_id"] != self.journal.journal.boot_id
                or row["unit_name"] != "changlian-os-" + handle_id + ".service"
                or not row["issued_at"] <= current < row["expires_at"]):
            _hold("ONE_SHOT_NOT_PREPARED")
        try:
            binding = json.loads(row["binding_json"])
        except (ValueError, TypeError) as exc:
            raise GrantRejected("PT_BRIDGE_FROZEN_BINDING_CORRUPT_HOLD") from exc
        binding["challenge"] = row["challenge"]
        _check_binding(binding)
        if (binding["task_id"] != row["task_id"]
                or binding["task_attempt"] != row["task_attempt"]
                or binding["node_id"] != row["node_id"]
                or binding["worker_id"] != row["worker_id"]
                or binding["execution_lease_sha256"] != row["lease_sha256"]
                or binding["runner_profile"] != PT_PROFILE
                or binding["source_name"] != "source.pt"
                or binding["output_name"] != "source.onnx"
                or binding["params"] != _FIXED_PARAMS):
            _hold("PILOT_FIXED_CONTRACT_MISMATCH")
        # The pilot has exactly one fixed image size/format/options. We never
        # ignore central options in order to run a different conversion.
        if (trusted_fixture.source_sha256 != binding["source_sha256"]
                or trusted_fixture.source_size_bytes != binding["source_size_bytes"]):
            _hold("SOURCE_BYTES_NOT_CENTRAL")
        frozen = FrozenPtExportAdmission(
            task_id=binding["task_id"],
            task_attempt=binding["task_attempt"],
            node_id=binding["node_id"],
            worker_id=binding["worker_id"],
            execution_lease_sha256=binding["execution_lease_sha256"],
            source_sha256=binding["source_sha256"],
            source_size_bytes=binding["source_size_bytes"],
            source_name=binding["source_name"],
            output_name=binding["output_name"],
            **binding["params"],
        )
        verified_manifest_digest = hashlib.sha256(
            frozen.freeze_nonexecutable_manifest(
                VerifiedPtBytes(
                    binding["source_sha256"], binding["source_size_bytes"],
                ),
            ),
        ).hexdigest()
        if verified_manifest_digest != binding["manifest_sha256"]:
            _hold("CENTRAL_FROZEN_MANIFEST_MISMATCH")
        # Verify the fresh independent central grant BEFORE touching any
        # files. journal.claim_rechecked_launch verifies again in its
        # BEGIN IMMEDIATE transaction, so a replay/race loses its CAS.
        verify_pt_export_launch_grant(
            central_launch_envelope, trusted_public_key=self.key,
            expected_binding=binding, handle_id=handle_id,
            registered_grant_digest=row["registered_grant_digest"],
            now=current, launch_challenge_issued_at=row["issued_at"],
        )
        bound_fixture = self.pilot.rebind_trusted_fixture(
            trusted_fixture, handle_id,
        )
        claimed = self.journal.claim_rechecked_launch(
            handle_id, task_attempt, central_launch_envelope,
            trusted_public_key=self.key,
        )
        # This is the first (and only) path in this CI bridge which can spawn
        # a systemd unit; the journal STARTING CAS is already durable.
        snapshot = self.pilot.launch(bound_fixture)
        if (snapshot["unit_name"] != row["unit_name"]
                or snapshot["active_state"] != "active"
                or snapshot["sub_state"] != "running"):
            _hold("OS_UNIT_NOT_VERIFIED")
        self.journal.record_pt_systemd_identity(
            handle_id, task_attempt,
            invocation_id=snapshot["invocation_id"],
            control_group=snapshot["control_group"],
            main_pid=snapshot["main_pid"],
        )
        return {
            "handle_id": handle_id,
            "task_attempt": task_attempt,
            "state": "RUNNING",
            "unit_name": snapshot["unit_name"],
            "invocation_id": snapshot["invocation_id"],
            "control_group": snapshot["control_group"],
            "main_pid": snapshot["main_pid"],
            "launch_grant_digest": claimed["launch_grant_digest"],
            "os_executor_connected": True,
            "production_launch_allowed": False,
            "result_publish_allowed": False,
            "trusted_stop_receipt_available": False,
        }
