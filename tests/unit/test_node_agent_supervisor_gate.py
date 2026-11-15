"""P0-01C: migration guard for real remote Agent training/conversion.

Small regression suite only. Legacy path must remain the default; when a
protected Supervisor is required, old direct Popen must be denied (no false
claim of a trusted OS StopReceipt or permission to release central HOLD).
"""
from pathlib import Path

import pytest

from platform_core import node_agent_supervisor_gate as gate


ROOT = Path(__file__).resolve().parents[2]


def test_unset_mode_preserves_existing_agent_and_runners(monkeypatch):
    monkeypatch.delenv(gate.ENV_KEY, raising=False)
    assert gate.execution_boundary_mode() == gate.LEGACY
    assert gate.assert_direct_remote_launch_permitted() is None
    capabilities = ["training", "conversion", "conversion.rknn", "model-upload"]
    assert gate.allowed_remote_capabilities(capabilities) == capabilities


def test_required_mode_hides_only_direct_compute_capabilities():
    source = {gate.ENV_KEY: gate.REQUIRED}
    original = ["training", "conversion", "conversion.rknn", "cleaning",
                "material-import", "model-upload", "deployment-test"]
    output = gate.allowed_remote_capabilities(original, source)
    assert output == ["cleaning", "material-import", "model-upload", "deployment-test"]
    assert original[0] == "training"  # no caller data mutation


def test_required_mode_refuses_direct_launch_with_explicit_reason():
    with pytest.raises(gate.SupervisorExecutionBoundaryRequired,
                       match="SUPERVISOR_REQUIRED_DIRECT_LAUNCH_BLOCKED"):
        gate.assert_direct_remote_launch_permitted({gate.ENV_KEY: gate.REQUIRED})


@pytest.mark.parametrize("bad", ["", "required", "supervisor", "disabled",
                                  "LEGACY", "legacy ", "0", "1", "true"])
def test_invalid_config_must_not_fall_back_to_popen(bad):
    env = {gate.ENV_KEY: bad}
    with pytest.raises(gate.SupervisorExecutionBoundaryInvalid):
        gate.execution_boundary_mode(env)
    with pytest.raises(gate.SupervisorExecutionBoundaryInvalid):
        gate.assert_direct_remote_launch_permitted(env)
    with pytest.raises(gate.SupervisorExecutionBoundaryInvalid):
        gate.allowed_remote_capabilities(["training"], env)


def test_non_string_config_fails_closed():
    with pytest.raises(gate.SupervisorExecutionBoundaryInvalid):
        gate.execution_boundary_mode({gate.ENV_KEY: True})


@pytest.mark.parametrize("path", [
    "platform_core/node_agent_training_runtime.py",
    "platform_core/node_agent_conversion_runtime.py",
])
def test_actual_runner_blocks_before_durable_launch_intent_and_popen(path):
    source = (ROOT / path).read_text(encoding="utf-8")
    assert "from .node_agent_supervisor_gate import (" in source
    guard = source.index("assert_direct_remote_launch_permitted()", source.index("with runtime_log.open"))
    intent = source.index("self.workdirs.begin_process_launch(lease)", guard)
    spawn = source.index("launched = launch_process(", intent)
    assert guard < intent < spawn
    assert "raise RemoteExecutionFenced(str(error)) from error" in source


def test_real_node_entrypoint_filters_advertised_capabilities():
    source = (ROOT / "node_agent.py").read_text(encoding="utf-8")
    assert "reported_capabilities = allowed_remote_capabilities(" in source
    assert "executable_agent_capabilities(requested_capabilities)" in source
    assert '"execution_boundary_mode": boundary_mode' in source


def test_migration_gate_does_not_claim_production_supervisor_available():
    source = (ROOT / "platform_core/node_agent_supervisor_gate.py").read_text()
    assert "production_recovery_allowed = True" not in source
    assert "launch_process(" not in source
    assert "systemctl" not in source
    assert "stop_proof_verified" not in source
