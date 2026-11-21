"""Isolated P0-01C-3B stop-receipt bridge; all cases pure CPU fakes."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "poc"))
import central_stop_recovery_contract as central
import linux_stop_receipt_bridge as bridge


def fixture():
    unit = "clpoc-" + "a" * 24 + ".service"
    base = {
        "challenge_id": "c" * 32, "nonce": "fake-test-nonce",
        "task_id": "poc-task-" + "b" * 24,
        "execution_generation": 3, "worker_id": "agent:isolated-poc-node",
        "boot_id": "01234567-89ab-cdef-0123-456789abcdef",
        "invocation_id": "d" * 32, "unit": unit,
        "cgroup": "/user.slice/app.slice/" + unit
    }
    scope = {k: base[k] for k in ("task_id", "execution_generation",
             "worker_id", "boot_id", "invocation_id", "unit", "cgroup")}
    observations = [
        {"type": "ready_before_stop_request", "populated": 1,
         "monotonic_ns": 100, "after_stop_armed": True},
        {"type": "poll", "mask": 10, "populated": 0,
         "monotonic_ns": 120, "after_stop_armed": True},
    ]
    kernel_result = {
        "outcome": "LOCAL_CGROUP_POC_PASS_NOT_CENTRAL_STOP_PROOF",
        "stop_proof_verified": False,
        "central_recovery_allowed": False,
        "membership_verified": True,
        "identity_binding_verified": True,
        "three_process_sessions_bound": True,
        "launcher_sigkill": True,
        "both_descendants_survived_launcher": True,
        "cgroup_empty_verified": True,
        "known_processes_stopped": True,
        "systemd_stop_returncode": 0,
        "stop_requested_ns": 110,
        "empty_observed_ns": 120,
        "empty_before_stop_requested": False,
        "synthetic_execution_identity": {
            k: base[k] for k in ("task_id", "execution_generation", "boot_id",
                                 "invocation_id", "unit")},
        "unit": unit, "cgroup_observations": observations,
    }
    return base, kernel_result, scope


def test_consistent_kernel_observation_links_live_event_to_challenge():
    challenge, result, scope = fixture()
    assert bridge.observation_is_usable(challenge, result, scope)
    receipt = bridge.make_simulated_receipt(challenge, result, scope,
                                            b"ci-simulation-only-key")
    assert central.test_only_witness_verifier(b"ci-simulation-only-key")(receipt)
    assert not central.test_only_witness_verifier(b"attacker-key")(receipt)
    assert receipt["payload"]["stop_requested_ns"] == 110
    assert receipt["payload"]["empty_observed_ns"] == 120


@pytest.mark.parametrize("field, value", [
    ("outcome", "STOP_OR_MEMBERSHIP_UNVERIFIED_HOLD"),
    ("stop_proof_verified", True),
    ("central_recovery_allowed", True),
    ("membership_verified", None),
    ("identity_binding_verified", False),
    ("three_process_sessions_bound", 1),
    ("launcher_sigkill", False),
    ("both_descendants_survived_launcher", False),
    ("cgroup_empty_verified", False),
    ("known_processes_stopped", False),
    ("systemd_stop_returncode", 1),
    ("empty_before_stop_requested", True),
    ("stop_requested_ns", 0),
    ("empty_observed_ns", 109),
    ("empty_observed_ns", None),
    ("empty_observed_ns", True),
])
def test_unverified_kernel_result_never_gets_receipt(field, value):
    challenge, result, scope = fixture()
    result[field] = value
    assert not bridge.observation_is_usable(challenge, result, scope)
    with pytest.raises(central.RecoveryRejected):
        bridge.make_simulated_receipt(challenge, result, scope, b"testkey")


@pytest.mark.parametrize("field, new_value", [
    ("task_id", "poc-task-" + "1" * 24),
    ("execution_generation", 4),
    ("execution_generation", True),
    ("boot_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
    ("invocation_id", "e" * 32),
    ("unit", "clpoc-" + "9" * 24 + ".service"),
    ("worker_id", "agent:wrong-node"),
    ("cgroup", "/user.slice/app.slice/clpoc-wrong.service"),
])
def test_old_generation_or_other_cgroup_cannot_bind(field, new_value):
    challenge, result, scope = fixture()
    scope[field] = new_value
    assert not bridge.observation_is_usable(challenge, result, scope)


@pytest.mark.parametrize("field, new_value", [
    ("task_id", "poc-task-" + "1" * 24),
    ("execution_generation", 10),
    ("boot_id", "ffffffff-ffff-ffff-ffff-ffffffffffff"),
    ("invocation_id", "e" * 32),
    ("unit", "clpoc-" + "9" * 24 + ".service"),
])
def test_kernel_execution_identity_cannot_be_swapped_after_stop(field, new_value):
    challenge, result, scope = fixture()
    result["synthetic_execution_identity"][field] = new_value
    assert not bridge.observation_is_usable(challenge, result, scope)


@pytest.mark.parametrize("value", [
    None, "", {}, [1], [{"populated": 0, "monotonic_ns": 120}]
])
def test_empty_or_forged_cgroup_timeline_never_passes(value):
    challenge, result, scope = fixture()
    result["cgroup_observations"] = value
    assert not bridge.observation_is_usable(challenge, result, scope)


def test_zero_before_request_is_not_reliable_stop_evidence():
    challenge, result, scope = fixture()
    result["cgroup_observations"][1]["monotonic_ns"] = 105
    result["empty_observed_ns"] = 105
    assert not bridge.observation_is_usable(challenge, result, scope)


def test_zero_without_prior_live_event_is_not_stop_proof():
    challenge, result, scope = fixture()
    result["cgroup_observations"] = result["cgroup_observations"][1:]
    assert not bridge.observation_is_usable(challenge, result, scope)


def test_direct_entrypoint_is_inert_without_opt_in(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["linux_stop_receipt_bridge.py"])
    monkeypatch.setattr(bridge, "run_isolated_bridge",
                        lambda: (_ for _ in ()).throw(AssertionError("must not execute")))
    assert bridge.main() == 2
    assert "NOT_EXECUTED" in capsys.readouterr().out


def test_bridge_rejects_non_github_runner_without_any_spawn(monkeypatch):
    monkeypatch.setenv("GITHUB_ACTIONS", "false")
    monkeypatch.setenv("RUNNER_ENVIRONMENT", "self-hosted")
    monkeypatch.setattr(bridge.kernel, "run_poc",
                        lambda **kw: (_ for _ in ()).throw(AssertionError("must not spawn")))
    result, code = bridge.run_isolated_bridge()
    assert code == 2
    assert result["outcome"] == "NOT_ISOLATED_GITHUB_RUNNER_HOLD"
    assert result["production_recovery_allowed"] is False


def test_synthetic_kernel_cannot_bypass_central_independent_witness():
    challenge, result, scope = fixture()
    receipt = bridge.make_simulated_receipt(challenge, result, scope, b"test-key")
    # The signed result can verify only with the *test* witness key and
    # absolutely does not identify the caller as a trusted real OS authority.
    assert not central.test_only_witness_verifier(b"other-key")(receipt)
    assert bridge.observation_is_usable(challenge, result, scope)


def test_ed25519_bridge_requires_the_exact_real_kernel_observation_fixture():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    import pt_stop_receipt_ed25519_contract as signed
    challenge, result, scope = fixture()
    private = Ed25519PrivateKey.generate()
    envelope = bridge.make_ed25519_simulated_receipt(
        challenge, result, scope, private,
    )
    assert envelope["payload"]["stop_requested_ns"] == 110
    assert envelope["payload"]["empty_observed_ns"] == 120
    assert signed.isolated_test_witness_verifier(
        private.public_key(), isolated_test_only=True,
    )(envelope)
    assert not signed.isolated_test_witness_verifier(
        Ed25519PrivateKey.generate().public_key(), isolated_test_only=True,
    )(envelope)


@pytest.mark.parametrize("field,value", [
    ("known_processes_stopped", False),
    ("cgroup_empty_verified", False),
    ("identity_binding_verified", False),
    ("stop_requested_ns", 0),
    ("empty_observed_ns", 109),
])
def test_ed25519_bridge_never_signs_invalid_kernel_evidence(field, value):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    challenge, result, scope = fixture()
    result[field] = value
    with pytest.raises(central.RecoveryRejected, match="KERNEL_EVIDENCE"):
        bridge.make_ed25519_simulated_receipt(
            challenge, result, scope, Ed25519PrivateKey.generate(),
        )
