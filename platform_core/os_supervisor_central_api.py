"""CPU-only grant endpoint on the existing authenticated Node Executor router.

This endpoint is always off unless the CONTROL PLANE operator explicitly sets
CHANGLIAN_SUPERVISOR_CPU_GRANTS_ENABLED=1 and provisions an owner-only key.
It does not create tasks, dispatch work, change leases, or launch processes.
"""
from __future__ import annotations

import os

from fastapi import Body, Header, HTTPException

def load_control_issuer_private_key():
    """Delay optional cryptography import until the CPU-only route is enabled."""
    from .os_supervisor_trust import load_control_issuer_private_key as loader
    return loader()


def register_supervisor_cpu_grant_route(router, task_repository) -> None:
    @router.post("/executions/{task_id}/supervisor-cpu/grant")
    def issue_supervisor_cpu_grant(
        node_id: str,
        task_id: str,
        payload: dict = Body(...),
        authorization: str | None = Header(default=None),
    ):
        if os.environ.get("CHANGLIAN_SUPERVISOR_CPU_GRANTS_ENABLED") != "1":
            raise HTTPException(
                409, detail={"code": "CENTRAL_CPU_ISSUER_DISABLED_HOLD"})
        if set(payload) != {
                "execution_generation", "execution_lease_token",
                "boot_id", "challenge"}:
            raise HTTPException(422, detail={
                "code": "CENTRAL_GRANT_REQUEST_INVALID_HOLD"})
        token = str(authorization or "")
        if not token.lower().startswith("bearer ") or not token[7:].strip():
            raise HTTPException(401, detail={"code": "NODE_TOKEN_REQUIRED"})
        # Default legacy paths must not need the Supervisor crypto dependency
        # just to build the existing FastAPI router.
        from .os_supervisor_authorization import GrantRejected
        from .os_supervisor_central_grants import CentralExecutionGrantIssuer
        try:
            # Neither the private key nor a key path is ever supplied by Agent.
            private_key = load_control_issuer_private_key()
            issuer = CentralExecutionGrantIssuer(
                task_repository(), private_key, cpu_trial_enabled=True)
            envelope = issuer.issue(
                task_id=task_id,
                task_attempt=payload["execution_generation"],
                node_id=node_id,
                node_token=token[7:].strip(),
                execution_lease_token=payload["execution_lease_token"],
                boot_id=payload["boot_id"],
                challenge=payload["challenge"],
            )
        except GrantRejected as exc:
            # Never include a token, key, request body, or task payload in error.
            code = str(exc)
            raise HTTPException(
                409, detail={"code": code if code.endswith("_HOLD")
                              else "CENTRAL_GRANT_UNVERIFIED_HOLD"}) from exc
        return {"grant": envelope, "launch_authorized": False,
                "trusted_stop_receipt_available": False}
