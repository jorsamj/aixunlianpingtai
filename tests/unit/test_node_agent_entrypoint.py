from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

import node_agent


class OneLoopEvent:
    def __init__(self):
        self._set = False

    def is_set(self):
        return self._set

    def set(self):
        self._set = True

    def wait(self, _timeout=None):
        self._set = True
        return True


class FakeExecutor:
    def __init__(self, effective_capabilities=None):
        self.start_calls = 0
        self.stop_calls = 0
        self._effective_capabilities = effective_capabilities

    def effective_capabilities(self):
        if self._effective_capabilities is None:
            return ("deployment-test",)
        return tuple(self._effective_capabilities)

    def active_tasks(self):
        return ()

    def last_error(self):
        return ""

    def status(self):
        return SimpleNamespace(
            running=self.start_calls > self.stop_calls,
            active_tasks=(),
            last_outcome="",
        )

    def start(self):
        self.start_calls += 1

    def stop(self, *, timeout=10.0):
        self.stop_calls += 1


def _identity():
    return SimpleNamespace(node_id="node-entrypoint", source="test")


def _patch_common(monkeypatch, tmp_path):
    monkeypatch.setattr(node_agent, "resolve_node_identity", lambda **_kwargs: _identity())
    monkeypatch.setattr(node_agent, "resolve_build_id", lambda _path: "build-test")
    monkeypatch.setattr(
        node_agent,
        "collect_runtime_probe",
        lambda _data_dir: {"python_executable": sys.executable},
    )
    monkeypatch.setattr(
        node_agent,
        "collect_local_snapshot",
        lambda **_kwargs: {
            "host": {"hostname": "node-entrypoint"},
            "resources": {},
            "runtime": dict(_kwargs.get("runtime_probe") or {}),
            "process": {},
        },
    )
    monkeypatch.setattr(node_agent, "_install_stop_handlers", lambda _event: {})
    monkeypatch.setattr(node_agent, "_restore_stop_handlers", lambda _previous: None)
    monkeypatch.setattr(node_agent.threading, "Event", OneLoopEvent)


def test_check_mode_reports_only_capabilities_this_agent_build_can_execute(
    tmp_path, monkeypatch, capsys
):
    _patch_common(monkeypatch, tmp_path)

    code = node_agent.main([
        "--check",
        "--state-dir",
        str(tmp_path),
        "--capabilities",
        "training",
        "deployment-test",
        "conversion",
        "material-import",
        "cleaning",
    ])

    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["capabilities"] == ["cleaning", "conversion", "deployment-test", "material-import", "training"]
    assert body["reported_capabilities"] == ["cleaning", "conversion", "deployment-test", "material-import", "training"]
    assert body["unsupported_remote_capabilities"] == []
    assert body["executor"]["enabled"] is True
    assert body["executor"]["supported_task_kinds"] == [
        "DEPLOYMENT_TEST",
        "MATERIAL_BATCH",
        "MATERIAL_IMPORT",
        "MODEL_CONVERSION",
        "TRAINING",
    ]


def test_executor_starts_only_after_successful_control_plane_heartbeat(
    tmp_path, monkeypatch
):
    _patch_common(monkeypatch, tmp_path)
    executor = FakeExecutor()
    monkeypatch.setattr(node_agent, "_build_executor", lambda **_kwargs: executor)
    heartbeat_calls = []

    def heartbeat(*_args, **_kwargs):
        heartbeat_calls.append("heartbeat")
        return {"node": {"status": "ONLINE"}, "desired": {}}

    monkeypatch.setattr(node_agent, "send_heartbeat", heartbeat)

    code = node_agent.main([
        "--control-plane",
        "https://control.example.test",
        "--token",
        "node-secret",
        "--node-id",
        "node-entrypoint",
        "--state-dir",
        str(tmp_path),
        "--capabilities",
        "deployment-test",
        "--interval",
        "3",
    ])

    assert code == 0
    assert heartbeat_calls == ["heartbeat"]
    assert executor.start_calls == 1
    assert executor.stop_calls == 1


def test_runtime_heartbeat_can_withdraw_conversion_when_runner_marks_it_unsafe(
    tmp_path, monkeypatch
):
    _patch_common(monkeypatch, tmp_path)
    executor = FakeExecutor(effective_capabilities=("deployment-test",))
    monkeypatch.setattr(node_agent, "_build_executor", lambda **_kwargs: executor)
    captured = {}

    def build_payload(_snapshot, *, capabilities, build_id, active_tasks, last_error):
        captured["capabilities"] = list(capabilities)
        return {
            "capabilities": list(capabilities),
            "build_id": build_id,
            "active_tasks": list(active_tasks),
            "last_error": last_error,
        }

    monkeypatch.setattr(node_agent, "build_heartbeat_payload", build_payload)
    monkeypatch.setattr(
        node_agent,
        "send_heartbeat",
        lambda *_args, **_kwargs: {
            "node": {"status": "ONLINE"},
            "desired": {},
        },
    )

    code = node_agent.main([
        "--control-plane",
        "https://control.example.test",
        "--token",
        "node-secret",
        "--node-id",
        "node-entrypoint",
        "--state-dir",
        str(tmp_path),
        "--capabilities",
        "conversion",
        "deployment-test",
        "--interval",
        "3",
    ])

    assert code == 0
    assert captured["capabilities"] == ["deployment-test"]
    assert executor.start_calls == 1
    assert executor.stop_calls == 1


def test_runtime_heartbeat_withdraws_training_when_executor_marks_it_unsafe(
    tmp_path, monkeypatch
):
    _patch_common(monkeypatch, tmp_path)
    executor = FakeExecutor(effective_capabilities=("deployment-test",))
    monkeypatch.setattr(node_agent, "_build_executor", lambda **_kwargs: executor)
    captured = {}

    def build_payload(_snapshot, *, capabilities, build_id, active_tasks, last_error):
        captured["capabilities"] = list(capabilities)
        return {
            "capabilities": list(capabilities),
            "build_id": build_id,
            "active_tasks": list(active_tasks),
            "last_error": last_error,
        }

    monkeypatch.setattr(node_agent, "build_heartbeat_payload", build_payload)
    monkeypatch.setattr(
        node_agent,
        "send_heartbeat",
        lambda *_args, **_kwargs: {
            "node": {"status": "ONLINE"},
            "desired": {},
        },
    )

    code = node_agent.main([
        "--control-plane",
        "https://control.example.test",
        "--token",
        "node-secret",
        "--node-id",
        "node-entrypoint",
        "--state-dir",
        str(tmp_path),
        "--capabilities",
        "training",
        "deployment-test",
        "--interval",
        "3",
    ])

    assert code == 0
    assert captured["capabilities"] == ["deployment-test"]
    assert executor.start_calls == 1
    assert executor.stop_calls == 1


def test_failed_initial_heartbeat_never_starts_executor(tmp_path, monkeypatch):
    _patch_common(monkeypatch, tmp_path)
    executor = FakeExecutor()
    monkeypatch.setattr(node_agent, "_build_executor", lambda **_kwargs: executor)

    def failed_heartbeat(*_args, **_kwargs):
        raise OSError("control plane unavailable")

    monkeypatch.setattr(node_agent, "send_heartbeat", failed_heartbeat)

    code = node_agent.main([
        "--control-plane",
        "https://control.example.test",
        "--token",
        "node-secret",
        "--node-id",
        "node-entrypoint",
        "--state-dir",
        str(tmp_path),
        "--capabilities",
        "deployment-test",
        "--interval",
        "3",
    ])

    assert code == 0
    assert executor.start_calls == 0
    assert executor.stop_calls == 1


def test_entrypoint_keeps_executor_start_after_heartbeat_and_stop_in_finally():
    path = Path(node_agent.__file__).resolve()
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    main = next(
        item
        for item in tree.body
        if isinstance(item, ast.FunctionDef) and item.name == "main"
    )

    send_lines = []
    start_lines = []
    stop_in_finally = False
    for item in ast.walk(main):
        if isinstance(item, ast.Call):
            func = item.func
            if isinstance(func, ast.Name) and func.id == "send_heartbeat":
                send_lines.append(item.lineno)
            if isinstance(func, ast.Attribute) and func.attr == "start":
                if isinstance(func.value, ast.Name) and func.value.id == "executor":
                    start_lines.append(item.lineno)
        if isinstance(item, ast.Try) and item.finalbody:
            for final_item in ast.walk(ast.Module(body=item.finalbody, type_ignores=[])):
                if not isinstance(final_item, ast.Call):
                    continue
                func = final_item.func
                if (
                    isinstance(func, ast.Attribute)
                    and func.attr == "stop"
                    and isinstance(func.value, ast.Name)
                    and func.value.id == "executor"
                ):
                    stop_in_finally = True

    assert len(send_lines) == 1
    assert len(start_lines) == 1
    assert send_lines[0] < start_lines[0]
    assert stop_in_finally is True


def test_check_mode_reports_rknn_capability_only_when_toolkit_probe_succeeds(tmp_path, monkeypatch, capsys):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(node_agent, "probe_rknn_toolkit", lambda _python: {
        "available": True, "python_executable": sys.executable, "version": "2.3.2",
        "supported_chips": ["rk3568", "rk3576"], "error": "",
    })
    code = node_agent.main(["--check", "--state-dir", str(tmp_path), "--capabilities", "conversion.rknn"])
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["reported_capabilities"] == ["conversion.rknn"]
    assert body["unsupported_remote_capabilities"] == []
    assert body["snapshot"]["runtime"]["rknn_toolkit2"]["version"] == "2.3.2"
    assert "MODEL_CONVERSION" in body["executor"]["supported_task_kinds"]


def test_check_mode_withholds_rknn_capability_when_toolkit_probe_fails(tmp_path, monkeypatch, capsys):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(node_agent, "probe_rknn_toolkit", lambda _python: {
        "available": False, "python_executable": sys.executable, "version": "",
        "supported_chips": [], "error": "missing toolkit",
    })
    code = node_agent.main(["--check", "--state-dir", str(tmp_path), "--capabilities", "conversion.rknn"])
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["reported_capabilities"] == []
    assert body["unsupported_remote_capabilities"] == ["conversion.rknn"]


def test_check_mode_reports_rknn_board_capability_only_after_real_board_probe(tmp_path, monkeypatch, capsys):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(node_agent, "probe_rknn_board_runtime", lambda _python: {
        "available": True,
        "chip": "rk3568",
        "architecture": "aarch64",
        "compatible": "rockchip,rk3568",
        "python_executable": sys.executable,
        "rknn_lite_version": "2.3.2",
        "error": "",
    })

    code = node_agent.main([
        "--check", "--state-dir", str(tmp_path),
        "--capabilities", "deployment-test.rknn",
    ])
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["reported_capabilities"] == ["deployment-test.rknn"]
    assert body["snapshot"]["runtime"]["rknn_board"]["chip"] == "rk3568"
    assert body["executor"]["supported_task_kinds"] == ["DEPLOYMENT_TEST"]


def test_check_mode_withholds_rknn_board_capability_when_probe_fails(tmp_path, monkeypatch, capsys):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(node_agent, "probe_rknn_board_runtime", lambda _python: {
        "available": False,
        "chip": "",
        "architecture": "x86_64",
        "compatible": "",
        "python_executable": sys.executable,
        "rknn_lite_version": "",
        "error": "not a Rockchip board",
    })
    code = node_agent.main([
        "--check", "--state-dir", str(tmp_path),
        "--capabilities", "deployment-test.rknn",
    ])
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["reported_capabilities"] == []
    assert body["unsupported_remote_capabilities"] == ["deployment-test.rknn"]


def test_doctor_requires_requested_rknn_board_capability_to_be_real(tmp_path, monkeypatch, capsys):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(node_agent, "probe_rknn_board_runtime", lambda _python: {
        "available": True,
        "chip": "rk3568",
        "architecture": "aarch64",
        "compatible": "rockchip,rk3568",
        "python_executable": sys.executable,
        "rknn_lite_version": "2.3.2",
        "error": "",
    })
    code = node_agent.main([
        "--doctor", "--state-dir", str(tmp_path),
        "--capabilities", "deployment-test.rknn",
    ])
    assert code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is True
    assert body["doctor"]["ready"] is True
    assert body["doctor"]["issues"] == []
    assert body["reported_capabilities"] == ["deployment-test.rknn"]
    assert body["snapshot"]["runtime"]["rknn_board"]["chip"] == "rk3568"


def test_doctor_returns_nonzero_and_actionable_issue_when_rknn_board_is_not_ready(
    tmp_path, monkeypatch, capsys
):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(node_agent, "probe_rknn_board_runtime", lambda _python: {
        "available": False,
        "chip": "",
        "architecture": "aarch64",
        "compatible": "vendor,unknown",
        "python_executable": sys.executable,
        "rknn_lite_version": "",
        "error": "device-tree compatible is not an RK3568/RK3576 board",
    })
    code = node_agent.main([
        "--doctor", "--state-dir", str(tmp_path),
        "--capabilities", "deployment-test.rknn",
    ])
    assert code == 3
    body = json.loads(capsys.readouterr().out)
    assert body["ok"] is False
    assert body["doctor"]["ready"] is False
    assert body["unsupported_remote_capabilities"] == ["deployment-test.rknn"]
    assert body["doctor"]["issues"] == [{
        "capability": "deployment-test.rknn",
        "message": "device-tree compatible is not an RK3568/RK3576 board",
    }]


def test_executor_state_lock_recovers_after_sigkill(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    env = {**os.environ, "PYTHONPATH": str(repo)}
    script = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from node_agent import _claim_node_executor_state\n"
        "try:\n"
        "    _claim_node_executor_state(Path(sys.argv[1]))\n"
        "    print('OK', flush=True)\n"
        "    time.sleep(float(sys.argv[2]))\n"
        "except RuntimeError:\n"
        "    print('LOCKED', flush=True)\n"
    )
    holder = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path), "30"],
        cwd=str(repo), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        assert holder.stdout.readline().strip() == "OK"
        holder.kill()
        holder.wait(timeout=20)
        probe = subprocess.Popen(
            [sys.executable, "-c", script, str(tmp_path), "0"],
            cwd=str(repo), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        assert probe.communicate(timeout=20)[0].strip() == "OK"
    finally:
        if holder.poll() is None:
            holder.kill()
            holder.wait(timeout=20)


def test_executor_state_lock_is_cross_process_and_released_on_exit(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    (tmp_path / "other").mkdir()
    env = {**os.environ, "PYTHONPATH": str(repo)}
    script = (
        "import sys,time\n"
        "from pathlib import Path\n"
        "from node_agent import _claim_node_executor_state\n"
        "try:\n"
        "    _claim_node_executor_state(Path(sys.argv[1]))\n"
        "    print('OK', flush=True)\n"
        "    time.sleep(float(sys.argv[2]))\n"
        "except RuntimeError:\n"
        "    print('LOCKED', flush=True)\n"
    )

    def spawn(directory: Path, hold: float):
        return subprocess.Popen(
            [sys.executable, "-c", script, str(directory), str(hold)],
            cwd=str(repo), env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True,
        )

    first = spawn(tmp_path, 30)
    try:
        assert first.stdout.readline().strip() == "OK"
        second = spawn(tmp_path, 0)
        assert second.communicate(timeout=20)[0].strip() == "LOCKED"
        other = spawn(tmp_path / "other", 0)
        assert other.communicate(timeout=20)[0].strip() == "OK"
    finally:
        first.terminate()
        first.wait(timeout=20)
    third = spawn(tmp_path, 0)
    assert third.communicate(timeout=20)[0].strip() == "OK"


def _slot_build_args():
    return SimpleNamespace(
        ultralytics_python="",
        paddle_python="",
        rknn_python="",
        rknn_lite_python="",
        mother_model_install_dir="",
        execution_heartbeat_interval=5.0,
        executor_poll_interval=2.0,
    )


def test_dual_slot_execution_is_explicit_opt_in_and_defaults_to_one_slot(tmp_path, monkeypatch):
    """W15/W16: production default must stay single-slot.

    The two-slot executor requires BOTH the local runtime opt-in
    (DSH_AGENT_EXECUTION_SLOTS=2) and the central authorization capability.
    Without the env opt-in the Agent must build a one-slot loop and advertises
    only its normal capability, never execution-slots:2.

    Building the real training runner wiring needs the optional training
    dependency surface; focused Agent contract jobs that do not install it must
    skip instead of failing on an unrelated ImportError.
    """
    pytest.importorskip("psutil", reason="training runner surface requires psutil")
    pytest.importorskip("yaml", reason="training runner surface requires PyYAML")
    pytest.importorskip("PIL", reason="training runner surface requires Pillow")
    monkeypatch.delenv("DSH_AGENT_EXECUTION_SLOTS", raising=False)
    single = node_agent._build_executor(
        control_plane="http://127.0.0.1:9",
        node_id="default-slot-node",
        token="node-token",
        state_dir=tmp_path / "state-default",
        runtime_probe={"python_executable": sys.executable},
        reported_capabilities=["training"],
        args=_slot_build_args(),
    )
    assert single is not None
    assert single.max_slots == 1
    assert single._slots is None
    assert single.effective_capabilities() == ("training",)

    monkeypatch.setenv("DSH_AGENT_EXECUTION_SLOTS", "2")
    dual = node_agent._build_executor(
        control_plane="http://127.0.0.1:9",
        node_id="opt-in-dual-node",
        token="node-token",
        state_dir=tmp_path / "state-dual",
        runtime_probe={"python_executable": sys.executable},
        reported_capabilities=["training"],
        args=_slot_build_args(),
    )
    assert dual is not None
    assert dual.max_slots == 2
    assert dual._slots is not None
    assert dual.effective_capabilities() == ("training", "execution-slots:2")


class FakeRecoveryCoordinator:
    """Record the node-level recovery verdict without touching real processes."""

    instances = []
    error = ""

    def __init__(self, workdirs, controller, *, client=None, intent_path=None):
        self.workdirs = workdirs
        self.controller = controller
        self.client = client
        self.intent_path = intent_path
        self.prepare_calls = 0
        FakeRecoveryCoordinator.instances.append(self)

    def prepare(self):
        self.prepare_calls += 1
        return FakeRecoveryCoordinator.error


def _write_persisted_identity(state_dir: Path) -> Path:
    target = state_dir / "executor" / "executions" / "stale-task" / "1"
    target.mkdir(parents=True)
    path = target / "process-identity.json"
    path.write_text(json.dumps({
        "pid": 4321, "create_time": 1234.5,
        "command_hash": "a" * 64, "group_token": "",
        "task_id": "stale-task", "generation": 1,
    }), encoding="utf-8")
    return path


def _build_for_recovery_test(state_dir: Path, capabilities):
    return node_agent._build_executor(
        control_plane="http://127.0.0.1:9",
        node_id="recovery-evidence-node",
        token="node-token",
        state_dir=state_dir,
        runtime_probe={"python_executable": sys.executable},
        reported_capabilities=list(capabilities),
        args=_slot_build_args(),
    )


def test_stale_recovery_evidence_withdraws_non_training_capabilities(
    tmp_path, monkeypatch
):
    """A persisted worker from a previous Agent run must be adjudicated even
    when the restarted Agent no longer requests training/conversion.

    Otherwise the old Worker is orphaned and the central dual-slot Hold stays
    HELD forever. Unsafe recovery must withdraw *every* remote execution
    capability, not just the one that used to own the process.
    """
    monkeypatch.setattr(node_agent, "NodeRecoveryCoordinator", FakeRecoveryCoordinator)
    FakeRecoveryCoordinator.instances = []
    FakeRecoveryCoordinator.error = "central recovery status is unavailable: OSError"
    state_dir = tmp_path / "state-cleaning"
    _write_persisted_identity(state_dir)

    executor = _build_for_recovery_test(state_dir, ["deployment-test"])

    assert FakeRecoveryCoordinator.instances, "recovery coordinator was not constructed"
    assert FakeRecoveryCoordinator.instances[0].prepare_calls >= 1
    assert executor is not None
    assert executor.enabled is False
    assert executor.effective_capabilities() == ()
    assert "central recovery status is unavailable" in executor.last_error()


def test_stale_recovery_evidence_with_empty_capabilities_still_fails_closed(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(node_agent, "NodeRecoveryCoordinator", FakeRecoveryCoordinator)
    FakeRecoveryCoordinator.instances = []
    FakeRecoveryCoordinator.error = "persisted process identity is unsafe or unreadable"
    state_dir = tmp_path / "state-empty"
    # An unpaired launch intent is also recovery evidence.
    target = state_dir / "executor" / "executions" / "stale-task" / "1"
    target.mkdir(parents=True)
    (target / "process-launch-intent.json").write_text(json.dumps({
        "task_id": "stale-task", "generation": 1, "kind": "TRAINING",
    }), encoding="utf-8")

    executor = _build_for_recovery_test(state_dir, [])

    assert FakeRecoveryCoordinator.instances, "recovery coordinator was not constructed"
    assert executor is not None
    assert executor.enabled is False
    assert executor.effective_capabilities() == ()
    assert "unsafe or unreadable" in executor.last_error()
    assert executor.status().last_error == executor.last_error()


def test_safe_recovery_evidence_keeps_capabilities_and_no_evidence_is_unchanged(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(node_agent, "NodeRecoveryCoordinator", FakeRecoveryCoordinator)
    FakeRecoveryCoordinator.instances = []
    FakeRecoveryCoordinator.error = ""
    state_dir = tmp_path / "state-safe"
    _write_persisted_identity(state_dir)

    executor = _build_for_recovery_test(state_dir, ["deployment-test"])
    assert FakeRecoveryCoordinator.instances
    assert executor is not None
    assert executor.enabled is True
    # deployment-test is registered by every Agent build without optional deps.
    assert executor.effective_capabilities() == ("deployment-test",)
    assert executor.last_error() == ""

    # Evidence adjudicated successfully but no capability requested: keep the
    # historical "no executor" heartbeat shape instead of a disabled loop.
    FakeRecoveryCoordinator.instances = []
    empty_state = tmp_path / "state-safe-empty"
    _write_persisted_identity(empty_state)
    assert _build_for_recovery_test(empty_state, []) is None
    assert FakeRecoveryCoordinator.instances
    assert FakeRecoveryCoordinator.instances[0].prepare_calls >= 1

    # Without recovery evidence the entrypoint must not construct a recovery
    # coordinator or change the existing no-capability behavior.
    FakeRecoveryCoordinator.instances = []
    clean_state = tmp_path / "state-clean"
    assert _build_for_recovery_test(clean_state, []) is None
    assert FakeRecoveryCoordinator.instances == []
    assert node_agent._persistent_recovery_evidence(clean_state) is False


def test_dual_slot_intent_evidence_requires_non_empty_records(tmp_path):
    state_dir = tmp_path / "intent-state"
    state_dir.mkdir()
    (state_dir / "dual-slot-intents.json").write_text("[]", encoding="utf-8")
    assert node_agent._persistent_recovery_evidence(state_dir) is False
    (state_dir / "dual-slot-intents.json").write_text(
        json.dumps([{"task_id": "intent-task", "generation": 1}]),
        encoding="utf-8",
    )
    assert node_agent._persistent_recovery_evidence(state_dir) is True



def test_cli_accepts_tokens_that_start_with_a_dash():
    """token_urlsafe may start with '-'; the CLI must not treat it as an option."""
    assert node_agent._normalized_argv([
        "--token", "-abc_123", "--node-id", "node-1",
    ]) == ["--token=-abc_123", "--node-id", "node-1"]
    # Ordinary values and already-normalized forms stay untouched.
    plain = ["--token", "abc123", "--token=def456", "-h"]
    assert node_agent._normalized_argv(plain) == plain
    # A bare lone dash is a conventional stdin marker, not an option.
    assert node_agent._normalized_argv(["--token", "-"]) == ["--token", "-"]
    # argparse must accept the normalized argv and keep the exact secret.
    parsed = node_agent.build_parser().parse_args(node_agent._normalized_argv([
        "--token", "-opaque_secret", "--control-plane", "http://127.0.0.1:9",
        "--node-id", "node-1",
    ]))
    assert parsed.token == "-opaque_secret"
