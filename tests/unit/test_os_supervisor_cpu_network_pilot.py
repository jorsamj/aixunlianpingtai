"""2D-2C3 real loopback HTTP + kernel AF_UNIX + rechecked CPU gate.

The OS backend is intentionally fake here. Separate protected systemd tests
verify the real InvocationID/cgroup/terminal evidence on Ubuntu CI.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
import platform
import socket
import threading
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
import pytest
import uvicorn

from platform_core.agent_execution import agent_executor_router
from platform_core.os_supervisor_cpu_network_pilot import IsolatedCpuNetworkPilot
from platform_core.os_supervisor_cpu_systemd import FixedCpuSystemd
from platform_core.os_supervisor_journal import ExecutionJournal
from platform_core.os_supervisor_protocol import SupervisorClient, SupervisorProtocolError
from platform_core.os_supervisor_service import SupervisorService
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository
import platform_core.os_supervisor_central_api as central_api

NODE = "agent2c3"
TASK = "conv_2c3_network_trial"
LEASE = "isolated-2c3-existing-execution-lease"


class FakeCpuBackend(FixedCpuSystemd):
    def __init__(self):
        self.starts = 0
        self.finished = False
        self.unit = None

    def launch(self, unit):
        self.starts += 1
        self.unit = unit
        return {"invocation_id": "a" * 32,
                "control_group": "/system.slice/" + unit,
                "main_pid": 54321}

    def inspect(self, unit, invocation):
        if unit != self.unit or invocation != "a" * 32:
            raise ValueError("wrong original invocation")
        return {"active_state": "active",
                "sub_state": "exited" if self.finished else "running",
                "control_group": "/system.slice/" + unit,
                "main_pid": 0 if self.finished else 54321}

    def verified_natural_exit(self, unit, invocation, **kwargs):
        if not self.finished or invocation != "a" * 32:
            raise ValueError("not verified terminal")
        return {"invocation_id": invocation, "main_pid": 54321,
                "exit_code": 0, "unit_result": "success",
                "cgroup_exit_type_verified": True}

    def read_log_page(self, unit, invocation, *, cursor=None):
        if unit != self.unit or invocation != "a" * 32:
            raise ValueError("log identity mismatch")
        return {"data": b"cpu-2c3-started\n" if cursor is None else b"",
                "cursor": "s=cpu2c3;i=1", "offset_contract_available": True}


@pytest.fixture
def isolated_network(tmp_path, monkeypatch):
    if (platform.system() != "Linux" or not hasattr(socket, "SO_PEERCRED")
            or os.geteuid() == 0):
        pytest.skip("unprivileged Linux SO_PEERCRED integration only")
    tasks = TaskRepository(tmp_path / "tasks" / "tasks.sqlite3")
    nodes = ServiceNodeRepository(tasks)
    _, token = nodes.create({
        "node_id": NODE, "display_name": "isolated CPU network",
        "connection_mode": "agent", "allowed_capabilities": ["conversion"]})
    nodes.heartbeat(NODE, token, {"reported_capabilities": ["conversion"]})
    tasks.create(TaskRecord.new(
        task_id=TASK, project_id="isolation",
        kind=TaskKind.MODEL_CONVERSION, payload_ref="test.json",
        resource_key="supervisor-cpu-v1",
        required_capabilities=("conversion",)))
    with closing(tasks._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """UPDATE tasks SET status='RUNNING',stage='running',attempt=3,
                      worker_id=?,lease_token=?,lease_expires_at=? WHERE task_id=?""",
            ("agent:" + NODE, LEASE,
             (datetime.now(timezone.utc) + timedelta(seconds=120)).isoformat(), TASK))
        db.commit()
    key = Ed25519PrivateKey.generate()
    monkeypatch.setenv("CHANGLIAN_SUPERVISOR_CPU_GRANTS_ENABLED", "1")
    monkeypatch.setattr(central_api, "load_control_issuer_private_key", lambda: key)
    app = FastAPI()
    app.include_router(agent_executor_router(
        lambda: tasks, lambda: ArtifactStore(tmp_path / "artifacts")))
    http_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    http_sock.bind(("127.0.0.1", 0))
    port = http_sock.getsockname()[1]
    http_sock.listen(16)
    http = uvicorn.Server(uvicorn.Config(
        app, log_level="critical", lifespan="off", access_log=False))
    http_thread = threading.Thread(
        target=lambda: http.run(sockets=[http_sock]), daemon=True)
    http_thread.start()
    for _ in range(300):
        if http.started:
            break
        time.sleep(0.01)
    assert http.started, "central HTTP test server did not start"
    backend = FakeCpuBackend()
    journal = ExecutionJournal(
        tmp_path / "os" / "journal.sqlite3", test_only_unprivileged=True)
    os_service = SupervisorService(
        tmp_path / "cpu.sock", allowed_uid=os.geteuid(), allowed_gid=os.getegid(),
        authorization_journal=journal, trusted_public_key=key.public_key(),
        cpu_trial_backend=backend, cpu_prelaunch_recheck_enabled=True)
    os_thread = threading.Thread(
        target=lambda: os_service.serve(test_only_unprivileged=True),
        daemon=True)
    os_thread.start()
    for _ in range(300):
        if os_service.path.is_socket():
            # bind() creates the path before listen(); probing until connect
            # succeeds avoids racing the bind->listen window (ECONNREFUSED).
            probe = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            try:
                probe.connect(str(os_service.path))
            except OSError:
                pass
            else:
                break
            finally:
                probe.close()
        time.sleep(0.01)
    assert os_service.path.is_socket()
    supervisor = SupervisorClient(
        str(os_service.path), expected_supervisor_uid=os.geteuid())
    pilot = IsolatedCpuNetworkPilot(
        supervisor=supervisor, central_base_url=f"http://127.0.0.1:{port}",
        node_id=NODE, task_id=TASK, execution_generation=3,
        node_token=token, execution_lease_token=LEASE, boot_id=journal.boot_id)
    try:
        yield tasks, journal, backend, pilot, supervisor
    finally:
        os_service.close()
        os_thread.join(timeout=4)
        http.should_exit = True
        http_thread.join(timeout=5)
        http_sock.close()


def test_http_unix_rechecked_launch_log_and_terminal(isolated_network):
    tasks, journal, backend, pilot, supervisor = isolated_network
    handle = pilot.prepare()
    assert backend.starts == 0
    assert supervisor.call("start")["ok"] is False
    launched = pilot.launch_once()
    assert launched is handle
    assert backend.starts == 1
    assert handle.poll() is None
    assert handle.read_log_page()["data"] == b"cpu-2c3-started\n"
    assert handle.read_log_page("s=cpu2c3;i=1")["data"] == b""
    with pytest.raises(SupervisorProtocolError):
        pilot.launch_once()
    assert backend.starts == 1
    backend.finished = True
    assert handle.poll() == 0
    with closing(tasks._connect()) as db:
        row = db.execute(
            "SELECT attempt,status,lease_token,worker_id FROM tasks WHERE task_id=?",
            (TASK,)).fetchone()
    assert tuple(row) == (3, "RUNNING", LEASE, "agent:" + NODE)
    assert journal.inspect(handle.handle_id, 3)["state"] == "EXITED"


def test_central_cancellation_after_registration_blocks_launch(isolated_network):
    tasks, journal, backend, pilot, supervisor = isolated_network
    handle = pilot.prepare()
    with closing(tasks._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute("UPDATE tasks SET status='CANCEL_REQUESTED' WHERE task_id=?",
                   (TASK,))
        db.commit()
    with pytest.raises(SupervisorProtocolError, match="CPU_CENTRAL_GRANT_HTTP_HOLD"):
        pilot.launch_once()
    assert backend.starts == 0
    with pytest.raises(SupervisorProtocolError):
        pilot.launch_once()
    assert backend.starts == 0
    assert journal.inspect(handle.handle_id, 3)["state"] == "UNKNOWN"


def test_pilot_rejects_nonlocal_destination():
    with pytest.raises(ValueError, match="loopback"):
        IsolatedCpuNetworkPilot(
            supervisor=SupervisorClient("/tmp/absent.sock"),
            central_base_url="https://production.example.com",
            node_id=NODE, task_id=TASK, execution_generation=3,
            node_token="example", execution_lease_token=LEASE,
            boot_id="65ad39e5-7bfa-4b46-9b1e-7f1f0d0d6c8a")
