"""Isolated CPU pilot: real loopback HTTP central grant + protected Unix RPC.

No production Node Agent/Runner imports this module. It cannot launch arbitrary
commands, provide stop receipts, or publish results. Every failure is HOLD.
"""
from __future__ import annotations

import hashlib
import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .os_supervisor_protocol import (
    SupervisedProcessHandle, SupervisorClient, SupervisorProtocolError,
)

_CHALLENGE = re.compile(r"[0-9a-f]{32}\Z")
_TASK = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{7,127}\Z")
_NODE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_MAX_RESPONSE = 8192


class IsolatedCpuNetworkPilot:
    """Single, non-retryable launch for a pre-existing central task attempt."""

    def __init__(self, *, supervisor: SupervisorClient, central_base_url: str,
                 node_id: str, task_id: str, execution_generation: int,
                 node_token: str, execution_lease_token: str, boot_id: str):
        url = urlsplit(central_base_url)
        if (url.scheme != "http" or url.hostname != "127.0.0.1"
                or url.username is not None or url.password is not None
                or not url.port or url.path not in ("", "/")
                or url.query or url.fragment):
            raise ValueError("CPU pilot requires a loopback-only test control plane")
        if (not isinstance(supervisor, SupervisorClient)
                or not isinstance(node_id, str) or not _NODE.fullmatch(node_id)
                or not isinstance(task_id, str) or not _TASK.fullmatch(task_id)
                or type(execution_generation) is not int
                or execution_generation <= 0
                or not isinstance(node_token, str) or not node_token
                or not isinstance(execution_lease_token, str)
                or not execution_lease_token or not isinstance(boot_id, str)):
            raise ValueError("CPU pilot fixed execution identity required")
        self.supervisor = supervisor
        self.grant_url = (
            f"http://127.0.0.1:{url.port}/api/v63/node-executor/"
            f"{node_id}/executions/{task_id}/supervisor-cpu/grant")
        self.node_id = node_id
        self.task_id = task_id
        self.generation = execution_generation
        self.node_token = node_token
        self.execution_lease_token = execution_lease_token
        self.boot_id = boot_id
        self.handle: SupervisedProcessHandle | None = None
        self._launch_attempted = False

    @staticmethod
    def _require_reply(reply: dict, label: str) -> dict:
        if reply.get("ok") is not True or not isinstance(reply.get("result"), dict):
            raise SupervisorProtocolError(label + "_HOLD")
        return reply["result"]

    def _grant(self, challenge: str) -> dict:
        if not isinstance(challenge, str) or not _CHALLENGE.fullmatch(challenge):
            raise SupervisorProtocolError("CPU_NETWORK_NONCE_INVALID_HOLD")
        body = json.dumps({
            "execution_generation": self.generation,
            "execution_lease_token": self.execution_lease_token,
            "boot_id": self.boot_id,
            "challenge": challenge,
        }, separators=(",", ":")).encode("utf-8")
        request = Request(
            self.grant_url, data=body, method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self.node_token})
        try:
            with urlopen(request, timeout=3.0) as response:
                if response.status != 200:
                    raise SupervisorProtocolError("CPU_CENTRAL_GRANT_HTTP_HOLD")
                data = response.read(_MAX_RESPONSE + 1)
        except (HTTPError, URLError, TimeoutError, OSError) as exc:
            raise SupervisorProtocolError("CPU_CENTRAL_GRANT_UNAVAILABLE_HOLD") from exc
        if len(data) > _MAX_RESPONSE:
            raise SupervisorProtocolError("CPU_CENTRAL_GRANT_OVERSIZE_HOLD")
        try:
            result = json.loads(data)
        except (ValueError, UnicodeError) as exc:
            raise SupervisorProtocolError("CPU_CENTRAL_GRANT_MALFORMED_HOLD") from exc
        if (not isinstance(result, dict)
                or result.get("launch_authorized") is not False
                or result.get("trusted_stop_receipt_available") is not False
                or not isinstance(result.get("grant"), dict)
                or set(result["grant"]) != {"claims", "signature"}):
            raise SupervisorProtocolError("CPU_CENTRAL_GRANT_CONTRACT_HOLD")
        return result["grant"]

    def prepare(self) -> SupervisedProcessHandle:
        if self.handle is not None:
            raise SupervisorProtocolError("CPU_PILOT_ALREADY_PREPARED_HOLD")
        scope = {
            "task_id": self.task_id, "task_attempt": self.generation,
            "node_id": self.node_id, "worker_id": "agent:" + self.node_id,
            "execution_lease_sha256": hashlib.sha256(
                self.execution_lease_token.encode("utf-8")).hexdigest(),
            "gpu_uuid": "CPU_ONLY", "boot_id": self.boot_id,
            "runner_profile": "fixed-cpu-v1",
        }
        challenged = self._require_reply(
            self.supervisor.call("challenge", scope), "CPU_INITIAL_CHALLENGE")
        if challenged.get("boot_id") != self.boot_id:
            raise SupervisorProtocolError("CPU_INITIAL_BOOT_MISMATCH_HOLD")
        initial = self._grant(challenged.get("challenge"))
        saved = self._require_reply(
            self.supervisor.call("authorize_intent", {"envelope": initial}),
            "CPU_INTENT_REGISTRATION")
        if (saved.get("replayed") is not False
                or not isinstance(saved.get("handle_id"), str)
                or not re.fullmatch(r"[0-9a-f]{32}", saved["handle_id"])):
            raise SupervisorProtocolError("CPU_INTENT_REPLAY_OR_ID_INVALID_HOLD")
        self.handle = SupervisedProcessHandle(
            self.supervisor, saved["handle_id"], self.generation)
        return self.handle

    def launch_once(self) -> SupervisedProcessHandle:
        if self.handle is None or self._launch_attempted:
            raise SupervisorProtocolError("CPU_PILOT_LAUNCH_NOT_ALLOWED_HOLD")
        # Set before attempting a single HTTP or IPC operation: no second
        # spawn after a timeout or an ambiguous supervisor response.
        self._launch_attempted = True
        scope = self.handle._scope()
        nonce = self._require_reply(
            self.supervisor.call("launch_challenge", scope),
            "CPU_LAUNCH_CHALLENGE")
        if nonce.get("boot_id") != self.boot_id:
            raise SupervisorProtocolError("CPU_LAUNCH_BOOT_MISMATCH_HOLD")
        fresh = self._grant(nonce.get("challenge"))
        started = self._require_reply(
            self.supervisor.call("start_rechecked", {
                **scope, "launch_envelope": fresh}),
            "CPU_START_RECHECKED")
        if (started.get("handle_id") != self.handle.handle_id
                or started.get("task_attempt") != self.generation
                or started.get("state") != "RUNNING"
                or started.get("trusted_stop_receipt_available") is not False
                or started.get("central_recovery_allowed") is not False):
            raise SupervisorProtocolError("CPU_START_IDENTITY_UNVERIFIED_HOLD")
        return self.handle
