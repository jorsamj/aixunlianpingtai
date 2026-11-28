"""P0-01C-3B-4: read-only GPU-launch / Supervisor gap audit.

This script reads source text and parses AST. It does not import the platform,
invoke training, inspect devices, access private nodes, or modify files.

An audit success means the KNOWN SAFETY GAP was detected, NOT that GPU launches
are safe or that production recovery can be enabled.
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Mapping, Any


RUNNERS = (
    "platform_core/node_agent_training_runtime.py",
    "platform_core/node_agent_conversion_runtime.py",
)
PROCESS_CONTROL = "platform_core/task_runtime/process_control.py"
GPU_RESERVATIONS = "platform_core/gpu_reservations_v2.py"
AGENT_ENTRYPOINT = "node_agent.py"


def _read_ast(repo_root: Path, path: str) -> tuple[str, ast.Module]:
    full = (repo_root / path).resolve()
    if not full.is_relative_to(repo_root.resolve()) or not full.is_file():
        raise ValueError("REQUIRED_SOURCE_MISSING_OR_OUTSIDE_REPOSITORY")
    content = full.read_text(encoding="utf-8")
    return content, ast.parse(content, filename=path)


def _call_positions(tree: ast.Module, name: str) -> list[int]:
    return [
        node.lineno for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name) and node.func.id == name
    ]


def _source_references_environment(src: str) -> bool:
    return "**os.environ" in src


def audit_current_launch_paths(repo_root: Path) -> dict[str, Any]:
    """Observe launch routes, not the runtime OS permissions."""
    if not isinstance(repo_root, Path):
        raise ValueError("REPOSITORY_ROOT_REQUIRED")
    runners = {}
    for path in RUNNERS:
        src, tree = _read_ast(repo_root, path)
        launches = _call_positions(tree, "launch_process")
        runners[path] = {
            "direct_launch_calls": len(launches),
            "direct_launch_lines": launches,
            "process_intent_recorded": "begin_process_launch(lease)" in src,
            "pid_identity_persisted": "persist_process_identity(" in src,
            "inherits_agent_environment": _source_references_environment(src),
            "imports_process_controller": "ProcessController" in src,
            "uses_protected_supervisor_api": False,  # not observable in current code
        }
    control_src, control = _read_ast(repo_root, PROCESS_CONTROL)
    reservations_src, _ = _read_ast(repo_root, GPU_RESERVATIONS)
    entry_src, _ = _read_ast(repo_root, AGENT_ENTRYPOINT)
    observed_direct_launch = all(
        item["direct_launch_calls"] == 1 for item in runners.values()
    )
    return {
        "scope": "READ_ONLY_GITHUB_SOURCE_AUDIT",
        "sources_checked": [*RUNNERS, PROCESS_CONTROL,
                            GPU_RESERVATIONS, AGENT_ENTRYPOINT],
        "runners": runners,
        "process_control": {
            "owns_subprocess_popen": bool(_call_positions(control, "Popen")) or
            "subprocess.Popen" in control_src,
            "uses_posix_session": "start_new_session" in control_src,
            "uses_windows_process_group": "CREATE_NEW_PROCESS_GROUP" in control_src,
        },
        "resource_reservations_exist": "gpu_reservations" in reservations_src,
        "agent_executor_started_directly": "executor.start()" in entry_src,
        "known_unprotected_direct_launch_detected": observed_direct_launch,
        "actual_linux_uid_and_sudo_verified": False,
        "actual_nvidia_device_permissions_verified": False,
        "actual_ascend_or_rockchip_permissions_verified": False,
        "gpu_runtime_isolation_verified": False,
        "production_supervisor_enforced": False,
        "production_recovery_allowed": False,
        "audit_outcome": (
            "DIRECT_GPU_CAPABLE_LAUNCH_BYPASSES_SUPERVISOR_HOLD"
            if observed_direct_launch
            else "CODE_PATH_CHANGED_REQUIRES_REAUDIT_HOLD"
        ),
    }


REQUIRED_BOUNDARY = (
    "task_id", "execution_generation", "worker_id", "node_id",
    "lease_token_hash", "gpu_uuid", "boot_id", "invocation_id",
    "unit", "cgroup", "challenge_id", "nonce",
)


def simulated_launch_admission(
        registered: Mapping[str, Any], submitted: Mapping[str, Any],
        checks: Mapping[str, Any]) -> dict[str, Any]:
    """Pure TEST-ONLY binding contract; never authorizes a real GPU spawn.

    A real protected OS service MUST independently establish UID, device ACL,
    process boundary and identity from system APIs. These booleans only model
    which inputs the future contract needs to check, not their authenticity.
    """
    ok = False
    reason = "SCOPE_OR_OS_EVIDENCE_UNKNOWN_HOLD"
    if not (isinstance(registered, Mapping) and
            isinstance(submitted, Mapping) and isinstance(checks, Mapping)):
        reason = "MALFORMED_ADMISSION_HOLD"
    elif set(registered) != set(REQUIRED_BOUNDARY) or (
            set(submitted) != set(REQUIRED_BOUNDARY)):
        reason = "INCOMPLETE_OR_EXTRA_SCOPE_HOLD"
    elif (type(registered["execution_generation"]) is not int or
          registered["execution_generation"] <= 0 or
          type(submitted["execution_generation"]) is not int):
        reason = "INVALID_EXECUTION_GENERATION_HOLD"
    elif any(
            not isinstance(registered[k], str) or
            not registered[k] or
            not isinstance(submitted[k], str) or
            not submitted[k]
            for k in REQUIRED_BOUNDARY if k != "execution_generation"):
        reason = "UNVERIFIED_SCOPE_VALUE_HOLD"
    elif any(type(registered[k]) is not type(submitted[k]) or
             registered[k] != submitted[k] for k in REQUIRED_BOUNDARY):
        reason = "REGISTERED_EXECUTION_MISMATCH_HOLD"
    elif set(checks) != {
            "agent_gpu_device_denied",
            "workload_gpu_device_allowed",
            "supervisor_unprivileged_agent_separation",
            "supervisor_launch_before_gpu",
            "registered_boundary_from_os",
            "central_lease_fenced",
            "no_agent_direct_gpu_spawn"}:
        reason = "OS_CONTROL_EVIDENCE_INCOMPLETE_HOLD"
    elif not all(value is True for value in checks.values()):
        reason = "GPU_ISOLATION_CONTROL_NOT_VERIFIED_HOLD"
    else:
        ok = True
        reason = "SIMULATED_POLICY_FIELDS_MATCH_NOT_A_TRUSTED_OS_PROOF"
    return {
        "simulated_policy_inputs_match": ok,
        "reason": reason,
        "production_gpu_launch_allowed": False,
        "production_recovery_allowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--read-only-audit", action="store_true")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2])
    opts = parser.parse_args()
    if not opts.read_only_audit:
        print(json.dumps({"outcome": "NOT_EXECUTED", "production_recovery_allowed": False}))
        return 2
    try:
        finding = audit_current_launch_paths(opts.repo_root)
    except (ValueError, OSError, SyntaxError) as exc:
        print(json.dumps({"outcome": "SOURCE_AUDIT_FAILED_HOLD",
                          "error_type": type(exc).__name__,
                          "production_recovery_allowed": False}))
        return 3
    print(json.dumps(finding, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if finding["known_unprotected_direct_launch_detected"] else 3


if __name__ == "__main__":
    raise SystemExit(main())
