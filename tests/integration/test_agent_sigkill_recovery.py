from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

from platform_core.node_agent_execution_slots import BoundedExecutionSlots
from platform_core.node_agent_executor_runtime import AgentExecutionWorkdir, RemoteExecutionLease
from platform_core.node_agent_recovery import NodeRecoveryCoordinator
from platform_core.task_runtime.process_control import ProcessController, launch_process


CHILD = r"""
import json, sys, time
from pathlib import Path
from types import SimpleNamespace

from platform_core.node_agent_execution_slots import BoundedExecutionSlots
from platform_core.node_agent_executor_runtime import AgentExecutionWorkdir, RemoteExecutionLease
from platform_core.task_runtime.process_control import launch_process

root = Path(sys.argv[1])
manifest = Path(sys.argv[2])
lease = RemoteExecutionLease(
    task_id="sigkill-task", kind="TRAINING", project_id="p",
    generation=1, lease_token="secret", lease_expires_at="2026-09-18T10:00:00+00:00",
    worker_id="agent:node", payload={}, assignment={}, transport={},
)
workdirs = AgentExecutionWorkdir(root)
target = workdirs.prepare(lease)
handle = launch_process([sys.executable, "-c", "import time; time.sleep(60)"])
workdirs.persist_process_identity(lease, handle.identity)
intents = root / "dual-slot-intents.json"
slots = BoundedExecutionSlots(2, persist_path=intents)
slots.reserve(SimpleNamespace(task_id="sigkill-task", generation=1), gpu_uuid="GPU-A")
manifest.write_text(json.dumps({
    "agent_pid": __import__("os").getpid(),
    "child_pid": handle.process.pid,
    "create_time": handle.identity.create_time,
    "command_hash": handle.identity.command_hash,
    "state_dir": str(root),
}), encoding="utf-8")
time.sleep(60)
"""


@pytest.mark.skipif(os.name != "posix", reason="POSIX SIGKILL recovery proof")
def test_sigkilled_agent_recovery_uses_real_process_identity(tmp_path):
    manifest = tmp_path / "manifest.json"
    state = tmp_path / "agent-state"
    script = tmp_path / "agent_child.py"
    script.write_text(CHILD, encoding="utf-8")
    env = {**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[2])}
    agent = subprocess.Popen(
        [sys.executable, str(script), str(state), str(manifest)],
        env=env, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
    )
    deadline = time.monotonic() + 20
    while not manifest.is_file() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert manifest.is_file(), agent.stderr.read()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    agent.send_signal(signal.SIGKILL)
    agent.wait(timeout=5)
    child_pid = int(data["child_pid"])
    assert ProcessController()._execution_alive(__import__("psutil").Process(child_pid))
    workdirs = AgentExecutionWorkdir(Path(data["state_dir"]))
    coordinator = NodeRecoveryCoordinator(workdirs, ProcessController())
    try:
        error = coordinator.prepare()
        assert error == "", error
        assert not __import__("psutil").pid_exists(child_pid)
        assert workdirs.list_process_identities() == []
    finally:
        # The persisted dual-slot intent intentionally remains for central
        # reconciliation; it must not be silently treated as released.
        intents = Path(data["state_dir"]) / "dual-slot-intents.json"
        assert intents.is_file()
        if __import__("psutil").pid_exists(child_pid):
            try:
                os.kill(child_pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
