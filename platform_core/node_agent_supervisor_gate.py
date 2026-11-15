"""Opt-in fail-closed migration gate for remote execution supervision.

The existing Agent-side training / conversion runners use subprocess.Popen and
their own process identity/cleanup contracts. Merely receiving a successful IPC
handshake would NOT transfer process ownership to a separate OS supervisor.

Until a supervised process handle, lifecycle polling, cancellation, durable
execution identity and trusted StopReceipt are integrated end-to-end, a node
configured to REQUIRE supervision must never fall back to direct launch.

Default 'legacy' preserves existing deployments exactly. This switch does not
authorize central recovery or change remote lease fencing/GPU reservations.
"""
from __future__ import annotations

import os
from typing import Mapping


ENV_KEY = "CHANGLIAN_AGENT_EXECUTION_BOUNDARY"
LEGACY = "legacy"
REQUIRED = "supervisor-required"


class SupervisorExecutionBoundaryRequired(PermissionError):
    """Direct process launch blocked because a protected supervisor is required."""


class SupervisorExecutionBoundaryInvalid(ValueError):
    """Bad configuration: do not guess a weaker process launch policy."""


def execution_boundary_mode(
        environ: Mapping[str, str] | None = None) -> str:
    source = os.environ if environ is None else environ
    value = source.get(ENV_KEY, LEGACY)
    if not isinstance(value, str):
        raise SupervisorExecutionBoundaryInvalid(
            "REMOTE_EXECUTION_BOUNDARY_CONFIG_INVALID: mode must be a string")
    if value == LEGACY:
        return LEGACY
    if value == REQUIRED:
        return REQUIRED
    raise SupervisorExecutionBoundaryInvalid(
        "REMOTE_EXECUTION_BOUNDARY_CONFIG_INVALID: expected 'legacy' or "
        "'supervisor-required'; refusing direct process launch")


def assert_direct_remote_launch_permitted(
        environ: Mapping[str, str] | None = None) -> None:
    """Called at the single spawn point in each remote Agent runner.

    A required-but-unavailable supervisor is a deliberate NO-GO, not an
    opportunity to quietly launch unsupervised or accept Agent-supplied
    stop_proof booleans.
    """
    if execution_boundary_mode(environ) == REQUIRED:
        raise SupervisorExecutionBoundaryRequired(
            "SUPERVISOR_REQUIRED_DIRECT_LAUNCH_BLOCKED: protected process "
            "supervisor launch and lifecycle adapter are not installed; "
            "remote training/conversion must not start unsupervised")
