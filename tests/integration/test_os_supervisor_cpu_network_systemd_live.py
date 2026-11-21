"""2D-2C3 isolated Ubuntu true-OS E2E: nonroot Agent -> HTTP -> root Unix -> systemd.

This deliberately requires sudo/root on an ephemeral GitHub Ubuntu-24.04
runner. A fixed CPU worker and a single random unit are the only OS side effects.
No real conversion, production node, GPU, trusted stop, or central finalization.
"""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timedelta, timezone
import multiprocessing
import os
from pathlib import Path
import pwd
import secrets
import socket
import subprocess
import threading
import time

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI
import uvicorn

from platform_core.agent_execution import agent_executor_router
from platform_core.os_supervisor_cpu_systemd import FixedCpuSystemd
from platform_core.os_supervisor_journal import ExecutionJournal
from platform_core.os_supervisor_service import SupervisorService
from platform_core.service_nodes import ServiceNodeRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository
import platform_core.os_supervisor_central_api as central_api

NODE = "cpu2c3linux"
TASK = "conv_2c3_systemd_trial"
LEASE = "ci-original-execution-lease-only"


def _unprivileged_agent(conn, uid, gid, socket_path, port, token, boot_id):
    """Separate OS process: no root privileges for the networking Agent."""
    from platform_core.os_supervisor_cpu_network_pilot import IsolatedCpuNetworkPilot
    from platform_core.os_supervisor_protocol import SupervisorClient
    try:
        os.setgroups([])
        os.setgid(gid)
        os.setuid(uid)
        client = SupervisorClient(socket_path, expected_supervisor_uid=0)
        pilot = IsolatedCpuNetworkPilot(
            supervisor=client, central_base_url=f"http://127.0.0.1:{port}",
            node_id=NODE, task_id=TASK, execution_generation=3,
            node_token=token, execution_lease_token=LEASE, boot_id=boot_id)
        handle = pilot.prepare()
        assert client.call("start")["ok"] is False
        assert pilot.launch_once().handle_id == handle.handle_id
        # The genuine systemd unit prints once and then exits naturally.
        first_log = b""
        cursor = None
        last = None
        deadline = time.monotonic() + 38
        while time.monotonic() < deadline:
            last = handle.poll()
            if not first_log:
                try:
                    page = handle.read_log_page()
                    first_log = page["data"]
                    cursor = page["cursor"]
                except Exception:
                    pass
            if last is not None:
                break
            time.sleep(0.4)
        assert last == 0, f"natural terminal not verified: {last!r}"
        assert b"changlian-fixed-cpu-trial-start" in first_log
        assert cursor
        assert handle.read_log_page(cursor)["data"].find(
            b"changlian-fixed-cpu-trial-start") < 0
        try:
            pilot.launch_once()
        except Exception:
            pass
        else:
            raise AssertionError("second launch must be rejected")
        conn.send({"ok": True, "handle_id": handle.handle_id,
                   "exit_code": last, "log_cursor": cursor,
                   "agent_uid": os.geteuid()})
    except BaseException as exc:
        conn.send({"ok": False, "error": repr(exc),
                   "agent_uid": os.geteuid()})
    finally:
        conn.close()


class _IsolatedRootSocketSupervisor(SupervisorService):
    """CI-only setup: root socket group access to exactly the nonroot test Agent."""

    def bind(self, *, test_only_unprivileged=False):
        super().bind(test_only_unprivileged=True)
        os.chown(self.path, 0, self.allowed_gid)
        os.chmod(self.path, 0o660)


def test_actual_nonroot_agent_central_http_root_systemd_end_to_end(
        tmp_path, monkeypatch):
    assert os.geteuid() == 0, "requires isolated GitHub Ubuntu root"
    assert Path("/run/systemd/system").is_dir(), "requires real systemd PID1"
    backend = FixedCpuSystemd()  # checks running manager >= v250 before launch
    nobody = pwd.getpwnam("nobody")
    assert nobody.pw_uid > 0
    tasks = TaskRepository(tmp_path / "tasks" / "tasks.sqlite3")
    nodes = ServiceNodeRepository(tasks)
    _, token = nodes.create({
        "node_id": NODE, "display_name": "CI CPU 2C3 only",
        "connection_mode": "agent", "allowed_capabilities": ["conversion"]})
    nodes.heartbeat(NODE, token, {"reported_capabilities": ["conversion"]})
    tasks.create(TaskRecord.new(
        task_id=TASK, project_id="ci_cpu_trial", kind=TaskKind.MODEL_CONVERSION,
        payload_ref="ci.json", resource_key="supervisor-cpu-v1",
        required_capabilities=("conversion",)))
    with closing(tasks._connect()) as db:
        db.execute("BEGIN IMMEDIATE")
        db.execute(
            """UPDATE tasks SET status='RUNNING',stage='running',attempt=3,
                      worker_id=?,lease_token=?,lease_expires_at=? WHERE task_id=?""",
            ("agent:" + NODE, LEASE,
             (datetime.now(timezone.utc) + timedelta(seconds=150)).isoformat(), TASK))
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
        app, lifespan="off", log_level="critical", access_log=False))
    http_thread = threading.Thread(
        target=lambda: http.run(sockets=[http_sock]), daemon=True)
    http_thread.start()
    for _ in range(300):
        if http.started:
            break
        time.sleep(0.01)
    assert http.started
    run_dir = Path("/run") / ("changlian-2c3-" + secrets.token_hex(8))
    run_dir.mkdir(mode=0o700)
    os.chown(run_dir, 0, nobody.pw_gid)
    run_dir.chmod(0o710)
    journal = ExecutionJournal(
        run_dir / "executions.sqlite3", test_only_unprivileged=True)
    service = _IsolatedRootSocketSupervisor(
        run_dir / "control.sock", allowed_uid=nobody.pw_uid,
        allowed_gid=nobody.pw_gid,
        authorization_journal=journal, trusted_public_key=key.public_key(),
        cpu_trial_backend=backend, cpu_prelaunch_recheck_enabled=True)
    svc_thread = threading.Thread(
        target=lambda: service.serve(test_only_unprivileged=True),
        daemon=True)
    svc_thread.start()
    for _ in range(300):
        if service.path.is_socket():
            break
        time.sleep(0.01)
    assert service.path.is_socket()
    ctx = multiprocessing.get_context("spawn")
    reader, writer = ctx.Pipe(duplex=False)
    child = ctx.Process(
        target=_unprivileged_agent,
        args=(writer, nobody.pw_uid, nobody.pw_gid, str(service.path),
              port, token, journal.boot_id))
    handle_id = None
    try:
        child.start()
        writer.close()
        child.join(timeout=52)
        assert not child.is_alive(), "isolated Agent did not finish"
        assert reader.poll(1), f"isolated Agent exited without evidence: {child.exitcode}"
        result = reader.recv()
        assert result["ok"], result
        assert result["agent_uid"] == nobody.pw_uid
        assert result["exit_code"] == 0
        handle_id = result["handle_id"]
        assert journal.inspect(handle_id, 3)["state"] == "EXITED"
        with closing(tasks._connect()) as db:
            row = db.execute(
                "SELECT attempt,status,worker_id,lease_token FROM tasks WHERE task_id=?",
                (TASK,)).fetchone()
        assert tuple(row) == (3, "RUNNING", "agent:" + NODE, LEASE)
    finally:
        if child.is_alive():
            child.terminate()
            child.join(timeout=5)
        reader.close()
        service.close()
        svc_thread.join(timeout=5)
        # Only the unique journal-recorded systemd unit is touched.
        if handle_id is None:
            with closing(journal._connect()) as db:
                row = db.execute(
                    "SELECT unit_name FROM execution_intents LIMIT 1").fetchone()
                unit = row["unit_name"] if row else None
        else:
            unit = "changlian-os-" + handle_id + ".service"
        if unit:
            subprocess.run(
                ["/usr/bin/systemctl", "--system", "stop", "--", unit],
                capture_output=True, timeout=8, check=False)
        http.should_exit = True
        http_thread.join(timeout=5)
        http_sock.close()
        for file in run_dir.iterdir():
            if file.is_file() or file.is_socket():
                file.unlink()
        run_dir.rmdir()
