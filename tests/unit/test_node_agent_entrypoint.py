from __future__ import annotations

import ast
import json
import sys
from pathlib import Path
from types import SimpleNamespace

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
            "runtime": {},
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
