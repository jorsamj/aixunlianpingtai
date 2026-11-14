"""Isolation-only POSIX crash-window proof for Node Agent process launching.

No real training, GPU, control plane, OSS, or external host is used.  An Agent
process is SIGKILLed AFTER creating a child and BEFORE persisting its PID. The
test asserts that a newly started Agent refuses BOTH compute task kinds.
The test supervisor independently cleans only the known synthetic child.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest

from platform_core.node_agent_conversion_runtime import AgentConversionRunner
from platform_core.node_agent_executor_runtime import AgentExecutionWorkdir
from platform_core.node_agent_training_runtime import AgentTrainingRunner

# The child interpreter is a *simulated Agent process*. It must die before
# persist_process_identity(), which is the real crash window under test.
_AGENT_SCRIPT = """
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from platform_core.node_agent_executor_runtime import AgentExecutionWorkdir, RemoteExecutionLease
from platform_core.task_runtime.process_control import launch_process

state, signal_file, kind = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3]
lease = RemoteExecutionLease(
    task_id='crash-window-task', kind=kind, project_id='isolated-project',
    generation=7, lease_token='test-only-token',
    lease_expires_at='2026-11-14T00:00:00Z', worker_id='agent:test',
    payload={}, assignment={}, transport={},
)
workdirs = AgentExecutionWorkdir(state)
workdirs.prepare(lease)
workdirs.begin_process_launch(lease)
child = launch_process(
    [sys.executable, '-c', 'import time; time.sleep(40)'],
    cwd=state, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
)
temporary = signal_file.with_suffix('.tmp')
temporary.write_text(json.dumps({
    'pid': child.identity.pid,
    'create_time': child.identity.create_time,
}), encoding='utf-8')
os.replace(temporary, signal_file)
# Never persist the child identity: test supervisor force-kills this Agent.
time.sleep(40)
"""


def _until(predicate, seconds: float = 10.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.05)
    return bool(predicate())


def _exact_child(pid: int, create_time: float):
    try:
        p = psutil.Process(pid)
        if abs(p.create_time() - create_time) <= 0.01:
            return p
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
        pass
    return None


def _alive(p) -> bool:
    if p is None:
        return False
    try:
        return p.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.ZombieProcess):
        return False


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGKILL and detached-session regression")
@pytest.mark.parametrize("kind", ["TRAINING", "MODEL_CONVERSION"])
def test_sigkill_between_spawn_and_pid_persist_blocks_both_compute_runners(
    tmp_path: Path, kind: str,
):
    state = tmp_path / "agent-state"
    signal_file = tmp_path / "spawned.json"
    agent = subprocess.Popen(
        [sys.executable, "-c", _AGENT_SCRIPT, str(state), str(signal_file), kind],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    child_identity = None
    try:
        assert _until(signal_file.is_file), "synthetic Agent did not spawn its child"
        child_identity = json.loads(signal_file.read_text(encoding="utf-8"))
        pid = int(child_identity["pid"])
        created = float(child_identity["create_time"])
        child = _exact_child(pid, created)
        assert _alive(child), "expected synthetic work to be alive before Agent SIGKILL"
        assert agent.poll() is None, "Agent exited before controlled SIGKILL"
        assert os.getpgid(pid) == pid, "synthetic child must own a private POSIX process group"

        os.kill(agent.pid, signal.SIGKILL)
        assert agent.wait(timeout=5) == -signal.SIGKILL
        assert _alive(_exact_child(pid, created)), "Agent death unexpectedly killed child"

        restarted = AgentExecutionWorkdir(state)
        assert restarted.list_process_identities() == []
        hazards = restarted.list_unverified_process_launch_intents()
        assert hazards == [{
            "task_id": "crash-window-task", "generation": 7, "kind": kind,
        }]
        marker = state / "executions" / "crash-window-task" / "7" / "process-launch-intent.json"
        assert marker.is_file()
        serialized = marker.read_text(encoding="utf-8")
        assert "test-only-token" not in serialized
        assert "pid" not in serialized.lower()

        training = AgentTrainingRunner(object(), restarted, runtime_root=tmp_path)
        conversion = AgentConversionRunner(object(), restarted, runtime_root=tmp_path)
        assert training.ready is False
        assert conversion.ready is False
        assert kind in training.recovery_error
        assert kind in conversion.recovery_error

        with pytest.raises(ValueError, match="unverified process launch"):
            restarted.cleanup(SimpleNamespace(task_id="crash-window-task", generation=7))
        assert marker.is_file(), "recovery evidence must survive forbidden cleanup"
        assert _alive(_exact_child(pid, created)), "read-only recovery must not silently kill unknown child"
    finally:
        if agent.poll() is None:
            agent.kill()
        try:
            agent.wait(timeout=5)
        except subprocess.TimeoutExpired:
            pass
        # Test-only cleanup of a known synthetic PID+birth time. Not a product
        # stop-proof implementation and never releases a central task hold.
        if child_identity is not None:
            proc = _exact_child(
                int(child_identity["pid"]), float(child_identity["create_time"])
            )
            if _alive(proc):
                try:
                    proc.kill()
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    pass
                assert _until(lambda: not _alive(proc), 5), (
                    "synthetic child remained alive after test cleanup"
                )
