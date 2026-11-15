"""P0-01C-3B-4: source-only audit and simulated launch admission contracts.

Tests cannot start, stop, inspect, or authorize a real GPU task.
"""
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "poc"))
import gpu_supervisor_gate_audit as audit


def request():
    return {
        "task_id": "train_dummy",
        "execution_generation": 9,
        "worker_id": "agent:simulated-node",
        "node_id": "simulated-node",
        "lease_token_hash": "a" * 64,
        "gpu_uuid": "GPU-SIMULATED-NOT-A-REAL-DEVICE",
        "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
        "invocation_id": "b" * 32,
        "unit": "clgpu-" + "c" * 24 + ".service",
        "cgroup": "/system.slice/clgpu-" + "c" * 24 + ".service",
        "challenge_id": "d" * 32,
        "nonce": "e" * 32,
    }


def os_checks():
    return {
        "agent_gpu_device_denied": True,
        "workload_gpu_device_allowed": True,
        "supervisor_unprivileged_agent_separation": True,
        "supervisor_launch_before_gpu": True,
        "registered_boundary_from_os": True,
        "central_lease_fenced": True,
        "no_agent_direct_gpu_spawn": True,
    }


def test_actual_training_and_conversion_still_direct_launch_no_supervisor():
    findings = audit.audit_current_launch_paths(ROOT)
    assert findings["known_unprotected_direct_launch_detected"] is True
    assert findings["audit_outcome"] == "DIRECT_GPU_CAPABLE_LAUNCH_BYPASSES_SUPERVISOR_HOLD"
    assert findings["production_recovery_allowed"] is False
    assert findings["gpu_runtime_isolation_verified"] is False
    assert findings["actual_nvidia_device_permissions_verified"] is False
    for path in audit.RUNNERS:
        current = findings["runners"][path]
        assert current["direct_launch_calls"] == 1
        assert current["process_intent_recorded"] is True
        assert current["pid_identity_persisted"] is True
        assert current["inherits_agent_environment"] is True
        assert current["uses_protected_supervisor_api"] is False
    assert findings["process_control"]["uses_posix_session"] is True
    assert findings["process_control"]["uses_windows_process_group"] is True
    assert findings["resource_reservations_exist"] is True


def test_simulated_complete_identity_does_not_grant_production_gpu_access():
    test = audit.simulated_launch_admission(request(), request(), os_checks())
    assert test["simulated_policy_inputs_match"] is True
    assert test["production_gpu_launch_allowed"] is False
    assert test["production_recovery_allowed"] is False


@pytest.mark.parametrize("field,value", [
    ("task_id", "other-task"),
    ("execution_generation", 10),
    ("execution_generation", True),
    ("execution_generation", 9.0),
    ("execution_generation", "9"),
    ("worker_id", "agent:different"),
    ("node_id", "different"),
    ("lease_token_hash", "f" * 64),
    ("gpu_uuid", "GPU-WRONG"),
    ("boot_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
    ("invocation_id", "f" * 32),
    ("unit", "clgpu-" + "d" * 24 + ".service"),
    ("cgroup", "/system.slice/other.service"),
    ("challenge_id", "f" * 32),
    ("nonce", "old_nonce"),
])
def test_wrong_execution_scope_denied(field, value):
    registered = request()
    supplied = {**registered, field: value}
    result = audit.simulated_launch_admission(registered, supplied, os_checks())
    assert result["simulated_policy_inputs_match"] is False
    assert result["production_gpu_launch_allowed"] is False


@pytest.mark.parametrize("field", list(os_checks().keys()))
def test_any_missing_gpu_control_denies_simulated_admission(field):
    checks = os_checks()
    checks[field] = False
    result = audit.simulated_launch_admission(request(), request(), checks)
    assert result["simulated_policy_inputs_match"] is False
    assert result["reason"] == "GPU_ISOLATION_CONTROL_NOT_VERIFIED_HOLD"


@pytest.mark.parametrize("field", list(os_checks().keys()))
def test_boolean_type_required_for_each_gpu_control(field):
    checks = os_checks()
    checks[field] = 1  # Python 1 == True must never count as OS evidence
    assert audit.simulated_launch_admission(
        request(), request(), checks)["simulated_policy_inputs_match"] is False


def test_new_unapproved_control_key_never_silently_succeeds():
    checks = os_checks()
    checks["allow_root_agent_gpu_access"] = True
    assert not audit.simulated_launch_admission(
        request(), request(), checks)["simulated_policy_inputs_match"]


def test_missing_gpu_control_never_silently_succeeds():
    checks = os_checks()
    del checks["agent_gpu_device_denied"]
    assert not audit.simulated_launch_admission(
        request(), request(), checks)["simulated_policy_inputs_match"]


@pytest.mark.parametrize("bad_generation", [0, -1, True, 1.0, "1"])
def test_bad_registered_generation_is_rejected(bad_generation):
    registered = {**request(), "execution_generation": bad_generation}
    assert not audit.simulated_launch_admission(
        registered, registered, os_checks())["simulated_policy_inputs_match"]


@pytest.mark.parametrize("key", list(request().keys()))
def test_missing_registered_field_fails_closed(key):
    registered = request()
    del registered[key]
    assert not audit.simulated_launch_admission(
        registered, request(), os_checks())["simulated_policy_inputs_match"]


@pytest.mark.parametrize("key", list(request().keys()))
def test_missing_request_field_fails_closed(key):
    submitted = request()
    del submitted[key]
    assert not audit.simulated_launch_admission(
        request(), submitted, os_checks())["simulated_policy_inputs_match"]


def test_static_audit_does_not_import_or_execute_platform(monkeypatch):
    # The implementation uses ast.parse/source-only scanning by construction.
    assert "ast.parse" in Path(audit.__file__).read_text()
    assert "subprocess.run" not in Path(audit.__file__).read_text()
    assert "torch.cuda" not in Path(audit.__file__).read_text()


def test_source_missing_causes_hold_not_safe(tmp_path):
    with pytest.raises(ValueError, match="REQUIRED_SOURCE_MISSING"):
        audit.audit_current_launch_paths(tmp_path)


def test_cli_is_inert_without_read_only_flag(monkeypatch,capsys):
    monkeypatch.setattr(sys, "argv", ["gpu-supervisor-audit"])
    assert audit.main() == 2
    assert "NOT_EXECUTED" in capsys.readouterr().out
