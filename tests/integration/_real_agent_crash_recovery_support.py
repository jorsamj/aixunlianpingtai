"""Shared harness for the real ``node_agent.py`` OS process crash-recovery E2E.

The harness starts the *production* ``node_agent.py`` entrypoint as a separate
OS process against a staged runtime root:

* ``node_agent.py`` is copied byte-for-byte from the repository;
* ``platform_core`` is a symlink (POSIX) / junction or copy (Windows) to the
  repository package, so the Agent imports the real production runtime;
* only ``train_worker.py`` is the established test-double worker from
  ``tests/unit/test_node_agent_training_runtime.py``;
* ``torch`` / ``ultralytics`` engine shims keep the real resource resolver
  importable on CI hosts that intentionally do not install the ML stack.

Central HTTP is a real FastAPI/uvicorn server in an in-process thread that
mounts the production routers ``service_node_router`` and
``agent_executor_router``. Training bundles are downloaded over a real local
HTTP server; the Agent process talks to the central server over 127.0.0.1 HTTP
only. Nothing here is a fake central client.
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import psutil
import pytest
import uvicorn
from fastapi import FastAPI

from platform_core.agent_execution import AgentExecutionService, agent_executor_router
from platform_core.node_agent_executor_runtime import AgentExecutionWorkdir, NodeExecutorClient
from platform_core.service_nodes import ServiceNodeRepository, service_node_router
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


REPO_ROOT = Path(__file__).resolve().parents[2]
NODE_ID = "real-agent-recovery"
AGENT_VERSION = "node-agent-v1"
GPU_A = "GPU-A"
GPU_B = "GPU-B"
FIXTURES_MODULE_NAME = "real_agent_crash_recovery_training_fixtures"

_TORCH_SHIM = '''"""Import-only torch shim for the isolated Agent resource resolver.

It never performs numerical work.  It exists so the *real* production
``platform_core.training_metrics`` CLI can run on a CI host that intentionally
does not install the multi-gigabyte ML stack; the resolver is executed with a
CPU device contract and never calls CUDA.
"""
__version__ = "0.0.0-agent-e2e-shim"


class _Version:
    cuda = None


version = _Version()


class _Cuda:
    @staticmethod
    def is_available():
        return False

    @staticmethod
    def device_count():
        return 0

    @staticmethod
    def get_device_properties(index):
        raise RuntimeError("torch shim has no CUDA devices")


cuda = _Cuda()


def empty(*_args, **_kwargs):
    raise RuntimeError("torch shim cannot allocate tensors")
'''


_ULTRALYTICS_SHIM = '''"""Import-only ultralytics shim for the isolated Agent resource resolver."""


class _Parameters:
    @staticmethod
    def parameters():
        return []


class YOLO:
    def __init__(self, model):
        self.model = _Parameters()
        self.model_name = str(model)

    def __str__(self):
        return self.model_name
'''


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def unit_fixtures():
    """Load the established fake-worker / bundle fixtures by file path."""
    cached = sys.modules.get(FIXTURES_MODULE_NAME)
    if cached is not None:
        return cached
    path = REPO_ROOT / "tests" / "unit" / "test_node_agent_training_runtime.py"
    spec = importlib.util.spec_from_file_location(FIXTURES_MODULE_NAME, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class BundleStorage:
    """Real local HTTP object storage for training bundle GET and upload PUT."""

    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}
        self._lock = threading.Lock()
        self.puts: list[dict] = []
        owner = self

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *_args):  # noqa: D401 - silence test server log
                return None

            def do_GET(self):  # noqa: N802 - http.server contract
                key = self.path.lstrip("/")
                with owner._lock:
                    payload = owner._objects.get(key)
                if payload is None:
                    self.send_response(404)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def do_PUT(self):  # noqa: N802 - http.server contract
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length) if length else b""
                with owner._lock:
                    owner.puts.append({
                        "path": self.path,
                        "sha256": hashlib.sha256(body).hexdigest(),
                        "size_bytes": len(body),
                        "headers": dict(self.headers),
                    })
                self.send_response(200)
                self.send_header("Content-Length", "2")
                self.end_headers()
                self.wfile.write(b"ok")

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.server.daemon_threads = True
        self.port = int(self.server.server_address[1])
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def url(self, key: str) -> str:
        return f"http://127.0.0.1:{self.port}/{key.lstrip('/')}"

    def register(self, key: str, payload: bytes) -> str:
        with self._lock:
            self._objects[key.lstrip("/")] = bytes(payload)
        return self.url(key)

    def stop(self) -> None:
        try:
            self.server.shutdown()
        except Exception:
            pass
        try:
            self.server.server_close()
        except Exception:
            pass
        self.thread.join(timeout=5)


def write_staged_runtime(
    root: Path,
    *,
    sleep_seconds: float = 900.0,
) -> dict:
    """Create the staged runtime root without modifying production files."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    source_agent = (REPO_ROOT / "node_agent.py").resolve()
    staged_agent = root / "node_agent.py"
    shutil.copyfile(source_agent, staged_agent)
    assert staged_agent.read_bytes() == source_agent.read_bytes(), (
        "staged node_agent.py must be byte-identical to the repository file"
    )

    package = root / "platform_core"
    if not package.exists():
        linked = False
        try:
            os.symlink(REPO_ROOT / "platform_core", package, target_is_directory=True)
            linked = True
        except (OSError, NotImplementedError):
            linked = False
        if not linked and os.name == "nt":
            completed = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(package), str(REPO_ROOT / "platform_core")],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode == 0:
                linked = True
        if not linked:
            if os.name == "posix":
                raise RuntimeError(
                    "unable to symlink the staged platform_core package: "
                    f"{REPO_ROOT / 'platform_core'}"
                )
            shutil.copytree(
                REPO_ROOT / "platform_core",
                package,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )

    # The real resource resolver runs ``python -m platform_core.training_metrics``
    # with cwd/PYTHONPATH on the staged root.  Import-only engine shims keep that
    # production code path executable without the GPU training stack.
    (root / "torch.py").write_text(_TORCH_SHIM, encoding="utf-8")
    ultralytics = root / "ultralytics"
    ultralytics.mkdir(exist_ok=True)
    (ultralytics / "__init__.py").write_text(_ULTRALYTICS_SHIM, encoding="utf-8")
    # Import marker that never ships a real model file.
    (root / "model-contract.txt").write_text(
        "official model reference is resolved by the resource resolver shim",
        encoding="utf-8",
    )

    fixtures = unit_fixtures()
    worker = fixtures.write_fake_train_worker(root, sleep_seconds=float(sleep_seconds))
    assert (root / "train_worker.py") == worker and worker.is_file()
    return {
        "root": root,
        "agent": staged_agent,
        "worker": worker,
        "sleep_seconds": float(sleep_seconds),
    }


def _payload_resolver(_task, payload, _assignment):
    return payload


def start_central(tmp_path: Path) -> dict:
    """Start a real central HTTP server and register the Agent node."""
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    app = FastAPI()
    app.include_router(service_node_router(lambda: repository))
    app.include_router(agent_executor_router(
        lambda: repository,
        lambda: artifacts,
        execution_payload_resolver=_payload_resolver,
    ))
    port = free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.02)
    assert server.started, "central HTTP server did not start"
    nodes = ServiceNodeRepository(repository)
    node, token = nodes.create({
        "node_id": NODE_ID,
        "display_name": NODE_ID,
        "connection_mode": "agent",
        "allowed_capabilities": ["training", "execution-slots:2"],
    })
    base_url = f"http://127.0.0.1:{port}"
    stack = {
        "repository": repository,
        "artifacts": artifacts,
        "app": app,
        "server": server,
        "thread": thread,
        "port": port,
        "base_url": base_url,
        "nodes": nodes,
        "node": node,
        "token": token,
        "service": AgentExecutionService(repository, artifacts),
    }
    heartbeat_with_gpus(stack)
    return stack


def stop_central(stack: dict) -> None:
    stack["server"].should_exit = True
    stack["thread"].join(timeout=10)


def heartbeat_with_gpus(stack: dict) -> dict:
    """Attach the two test GPU identities to the central node snapshot.

    The real Agent heartbeat reports the *actual* host resources (no GPU on CI
    runners), so a GPU-backed central assignment must be created from the test
    harness snapshot before the Agent claims it.  This is the same node
    heartbeat contract the Agent itself uses; it is not a fake scheduler.
    """
    return stack["nodes"].heartbeat(NODE_ID, stack["token"], {
        "hostname": NODE_ID,
        "os_name": "test",
        "architecture": "test",
        "agent_version": AGENT_VERSION,
        "build_id": "real-agent-e2e",
        "reported_capabilities": ["training", "execution-slots:2"],
        "resources": {
            "cpu": {"logical_cores": 8, "physical_cores": 4},
            "memory": {"available_bytes": 32 * 1024 ** 3, "total_bytes": 64 * 1024 ** 3},
            "disk": {"free_bytes": 64 * 1024 ** 3, "total_bytes": 256 * 1024 ** 3},
            "gpu": {"available": True, "gpus": [
                {"id": "cuda:0", "index": 0, "uuid": GPU_A,
                 "name": "Test GPU A", "memory_free_bytes": 8 * 1024 ** 3,
                 "memory_total_bytes": 8 * 1024 ** 3, "utilization_percent": 0},
                {"id": "cuda:1", "index": 1, "uuid": GPU_B,
                 "name": "Test GPU B", "memory_free_bytes": 8 * 1024 ** 3,
                 "memory_total_bytes": 8 * 1024 ** 3, "utilization_percent": 0},
            ]},
        },
        "runtime": {},
        "process": {},
        "active_tasks": [],
        "last_error": "",
    })


def create_training_task(
    stack: dict,
    tmp_path: Path,
    storage: BundleStorage,
    *,
    task_id: str,
    gpu_uuid: str,
) -> dict:
    """Persist one TRAINING task with a real HTTP bundle download contract."""
    fixtures = unit_fixtures()
    lease, downloads = fixtures.training_lease(tmp_path / task_id)
    bundle_bytes = next(iter(downloads.values()))
    bundle_url = storage.register(f"bundles/{task_id}.zip", bundle_bytes)
    payload = copy.deepcopy(lease.payload)
    payload.setdefault("remote_execution", {
        "version": 1, "task_kind": "TRAINING", "transport": "object-storage-v1",
    })
    payload["resource_requirements"] = {
        "gpu_count": 1, "gpu_uuids": [gpu_uuid], "min_gpu_memory_bytes": 1,
    }
    # Single concurrently reserved task: the deterministic resource resolver must
    # not fail merely because the CI host reports shared RAM contention.
    payload["concurrent_reservations"] = 1
    # CPU execution contract: no real GPU is required for the crash proof and the
    # production resource resolver therefore never touches CUDA.
    payload["selected_device"] = "cpu"
    payload.pop("selected_gpu", None)
    payload["requested_device"] = "auto"
    payload.setdefault("params", {})["precision"] = "fp32"
    payload["bundle"]["download"]["url"] = bundle_url
    stack["artifacts"].atomic_write_json(task_id, "request.json", payload)
    stack["repository"].create(TaskRecord.new(
        task_id=task_id,
        project_id="project-real-agent",
        kind=TaskKind.TRAINING,
        payload_ref="request.json",
        resource_key=f"training:{task_id}",
    ), artifacts=stack["artifacts"])
    return {"task_id": task_id, "payload": payload, "gpu_uuid": gpu_uuid}


def assign_next(stack: dict) -> dict:
    assignment = stack["service"].allocator.assign_next()
    assert assignment is not None, "central allocator did not assign the queued task"
    return assignment


def launch_agent(
    staged: dict,
    stack: dict,
    *,
    state_dir: Path,
    data_dir: Path,
    log_path: Path,
    interval: float = 2.0,
    executor_poll_interval: float = 0.5,
    execution_heartbeat_interval: float = 1.0,
) -> dict:
    """Start the real ``node_agent.py`` entrypoint as a child OS process."""
    state_dir = Path(state_dir)
    data_dir = Path(data_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = Path(log_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join([
        str(Path(staged["root"]).resolve()),
        str(REPO_ROOT),
    ]) + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    env["DSH_AGENT_EXECUTION_SLOTS"] = "2"
    env.pop("CHANGLIAN_AGENT_EXECUTION_BOUNDARY", None)
    stream = log_path.open("w", encoding="utf-8", errors="replace")
    command = [
        sys.executable,
        str(Path(staged["agent"])),
        "--control-plane", stack["base_url"],
        "--node-id", NODE_ID,
        # tokens are token_urlsafe and may start with '-'; the '=' form keeps
        # argparse from mistaking an opaque secret for an option.
        "--token=" + str(stack["token"]),
        "--state-dir", str(state_dir),
        "--data-dir", str(data_dir),
        "--capabilities", "training",
        "--interval", str(interval),
        "--executor-poll-interval", str(executor_poll_interval),
        "--execution-heartbeat-interval", str(execution_heartbeat_interval),
    ]
    process = subprocess.Popen(
        command,
        cwd=str(Path(staged["root"])),
        env=env,
        stdout=stream,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return {
        "process": process,
        "log_path": log_path,
        "log_stream": stream,
        "command": command,
    }


def read_log(agent: dict, *, limit: int = 6000) -> str:
    try:
        value = Path(agent["log_path"]).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    return value[-limit:]


def stop_agent(agent: dict, *, timeout: float = 15.0) -> None:
    process = agent.get("process")
    stream = agent.get("log_stream")
    if process is not None and process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass
    if process is not None:
        try:
            process.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            pass
    if stream is not None:
        try:
            stream.close()
        except Exception:
            pass


def wait_for(predicate, *, timeout: float, message: str, context=None):
    context = context or {}
    deadline = time.monotonic() + float(timeout)
    last = None
    while time.monotonic() < deadline:
        try:
            last = predicate()
        except AssertionError:
            raise
        except Exception as error:  # keep polling on transient read races
            last = None
            context.setdefault("transient_errors", []).append(f"{type(error).__name__}: {error}")
        if last:
            return last
        process = (context.get("agent") or {}).get("process")
        if process is not None and process.poll() is not None:
            break
        time.sleep(0.05)
    raise AssertionError(
        f"{message}\n--- diagnostics ---\n{diagnostics(context)}"
    )


def diagnostics(context: dict) -> str:
    parts: list[str] = []
    agent = context.get("agent")
    if agent is not None:
        parts.append(f"agent exit code: {agent['process'].poll()}")
        parts.append("agent log tail:")
        parts.append(read_log(agent))
    state_dir = context.get("state_dir")
    if state_dir is not None:
        root = Path(state_dir)
        parts.append(f"state dir files: {sorted(str(path.relative_to(root)) for path in root.rglob('*') if path.is_file())[:80]}")
    repository = context.get("repository")
    if repository is not None:
        try:
            with repository._connect() as database:
                tasks = [tuple(row) for row in database.execute(
                    "SELECT task_id,status,attempt,process_pid,stage,error FROM tasks ORDER BY task_id"
                )]
                holds = [tuple(row) for row in database.execute(
                    "SELECT task_id,state,assignment_generation,execution_attempt,gpu_uuid "
                    "FROM execution_resource_holds ORDER BY task_id"
                )]
                nodes = [tuple(row) for row in database.execute(
                    "SELECT node_id,reported_capabilities,last_error FROM service_nodes"
                )]
            parts.append(f"central tasks: {tasks}")
            parts.append(f"central holds: {holds}")
            parts.append(f"central nodes: {nodes}")
        except Exception as error:
            parts.append(f"central diagnostics failed: {type(error).__name__}: {error}")
    return "\n".join(parts)


def central_status(stack: dict, task_id: str) -> dict:
    client = NodeExecutorClient(stack["base_url"], NODE_ID, stack["token"])
    return client.execution_status(task_id)


def task_row(repository: TaskRepository, task_id: str) -> dict:
    task = repository.get(task_id)
    assert task is not None, f"task {task_id} disappeared"
    return {
        "task_id": task.task_id,
        "status": task.status.value,
        "attempt": int(task.attempt),
        "process_pid": task.process_pid,
        "worker_id": task.worker_id,
        "payload_ref": task.payload_ref,
    }


def hold_row(repository: TaskRepository, task_id: str) -> dict | None:
    with repository._connect() as database:
        row = database.execute(
            "SELECT node_id,state,assignment_generation,execution_attempt,gpu_uuid,"
            "proof_type,proof_sha256 FROM execution_resource_holds WHERE task_id=?",
            (task_id,),
        ).fetchone()
    return dict(row) if row is not None else None


def assignment_rows(repository: TaskRepository, task_id: str) -> list[dict]:
    with repository._connect() as database:
        rows = database.execute(
            "SELECT generation,node_id,state,release_reason FROM task_node_assignments "
            "WHERE task_id=? ORDER BY generation",
            (task_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def attempt_rows(repository: TaskRepository, task_id: str) -> list[dict]:
    with repository._connect() as database:
        tables = {
            str(row[0]) for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        if "task_execution_attempts" not in tables:
            return []
        rows = database.execute(
            "SELECT * FROM task_execution_attempts WHERE task_id=? ORDER BY attempt",
            (task_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def local_workdirs(state_dir: Path) -> AgentExecutionWorkdir:
    return AgentExecutionWorkdir(Path(state_dir) / "executor")


def local_identity(state_dir: Path, task_id: str, generation: int) -> dict | None:
    lease = SimpleNamespace(task_id=task_id, generation=int(generation))
    return local_workdirs(state_dir).read_process_identity(lease)


def intent_records(state_dir: Path) -> list:
    path = Path(state_dir) / "dual-slot-intents.json"
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return [{"state": "UNREADABLE"}]
    return value if isinstance(value, list) else [{"state": "INVALID"}]


def canonical_json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def expected_stop_proof_digest(
    *,
    node_id: str,
    task_id: str,
    assignment_generation: int,
    execution_generation: int,
    gpu_uuid: str,
    identity: dict,
) -> str:
    """Recompute the central stop-proof digest from the local original evidence."""
    proof = {
        "proof_type": "PROCESS_STOP_VERIFIED",
        "node_id": str(node_id),
        "task_id": str(task_id),
        "assignment_generation": int(assignment_generation),
        "execution_attempt": int(execution_generation),
        "gpu_uuid": str(gpu_uuid),
        "process_identity": {
            "pid": int(identity["pid"]),
            "create_time": float(identity["create_time"]),
            "command_hash": str(identity["command_hash"]),
        },
        "stop_verified": True,
        "no_process_launched": False,
        "no_launch_evidence": {},
    }
    return hashlib.sha256(canonical_json(proof).encode("utf-8")).hexdigest()


def process_alive(identity: dict) -> bool:
    try:
        process = psutil.Process(int(identity["pid"]))
        return (
            abs(float(process.create_time()) - float(identity["create_time"])) <= 0.02
            and process.status() != psutil.STATUS_ZOMBIE
        )
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
        return False


def kill_process_identity(identity: dict | None) -> None:
    """Test-only cleanup of a known synthetic PID + creation time."""
    if not identity:
        return
    try:
        process = psutil.Process(int(identity["pid"]))
        if abs(float(process.create_time()) - float(identity["create_time"])) > 0.02:
            return
        for child in process.children(recursive=True):
            try:
                child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        process.kill()
        try:
            process.wait(timeout=5)
        except psutil.TimeoutExpired:
            pass
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
        return


def wait_process_gone(identity: dict, *, timeout: float = 20.0) -> bool:
    deadline = time.monotonic() + float(timeout)
    while time.monotonic() < deadline:
        if not process_alive(identity):
            return True
        time.sleep(0.05)
    return not process_alive(identity)


def node_public(stack: dict) -> dict:
    return stack["nodes"].get_public(NODE_ID)


def assert_no_duplicate_execution(repository: TaskRepository, task_id: str) -> None:
    rows = assignment_rows(repository, task_id)
    assert len(rows) == 1, f"original task {task_id} was assigned more than once: {rows}"
    assert rows[0]["state"] == "RELEASED", f"original assignment is not released: {rows}"
    assert rows[0]["release_reason"] == "execution_started", (
        f"original assignment was not consumed by the execution start: {rows}"
    )


def require_linux_posix() -> None:
    if os.name != "posix":
        pytest.skip("POSIX SIGKILL process-recovery proof requires a POSIX host")


RESTART_ORIGINAL_TASK = "restart-original-task"
RESTART_CANDIDATE_TASK = "restart-candidate-task"
JOB_OBJECT_ERROR = "Job Object descendant stop proof"
INTENT_ERROR = "PERSISTED_DUAL_SLOT_INTENT_REQUIRES_RECONCILIATION"
_TERMINAL_STATUSES = frozenset({
    "SUCCEEDED", "PARTIAL_SUCCESS", "CANCELLED", "FAILED",
    "BLOCKED_BY_ENVIRONMENT", "BLOCKED_BY_HARDWARE",
})


def wait_worker_started(
    stack: dict,
    staged: dict,
    state_dir: Path,
    context: dict,
    *,
    task_id: str,
    generation: int = 1,
) -> dict:
    """Wait until the real Agent persisted identity and central start identity."""
    def identity_or_terminal():
        identity = local_identity(state_dir, task_id, generation)
        if identity is not None:
            return identity
        row = task_row(stack["repository"], task_id)
        if row["status"] in _TERMINAL_STATUSES:
            raise AssertionError(
                f"execution {task_id} ended before spawning its worker: {row}"
            )
        return None

    identity = wait_for(
        identity_or_terminal, timeout=90,
        message="real Agent did not persist the worker ProcessIdentity",
        context=context,
    )
    wait_for(
        lambda: task_row(stack["repository"], task_id)["process_pid"] == identity["pid"],
        timeout=45,
        message="central did not register the worker start identity",
        context=context,
    )
    wait_for(
        lambda: (Path(staged["root"]) / "started.marker").is_file(),
        timeout=45,
        message="test-double training worker did not start",
        context=context,
    )
    wait_for(
        lambda: (hold_row(stack["repository"], task_id) or {}).get("state") == "HELD",
        timeout=30,
        message="central did not create the dual-slot HELD resource hold",
        context=context,
    )
    return identity


def run_restart_fail_closed_scenario(tmp_path: Path) -> None:
    """Real Agent restart boundary: cross-platform fail-closed contract.

    Windows: forced Agent stop leaves the worker and its identity behind; the
    restarted Agent must fail closed because no Job Object descendant stop proof
    exists, publish that error in the node heartbeat and never claim new work.

    POSIX: the first Agent performs its ordinary graceful shutdown (worker
    stopped, identity cleared) but the persisted dual-slot intent still requires
    central reconciliation, so the restarted Agent must not advertise remote
    capabilities or claim new work either.
    """
    unit_fixtures()
    tmp_path = Path(tmp_path)
    state_dir = tmp_path / "agent-state"
    data_dir = tmp_path / "agent-data"
    staged = write_staged_runtime(tmp_path / "runtime", sleep_seconds=900.0)
    stack = start_central(tmp_path)
    storage = BundleStorage()
    agents: list[dict] = []
    worker_identity = None
    context: dict = {"state_dir": state_dir, "repository": stack["repository"]}
    try:
        create_training_task(
            stack, tmp_path, storage, task_id=RESTART_ORIGINAL_TASK, gpu_uuid=GPU_A,
        )
        assign_next(stack)
        first = launch_agent(
            staged, stack, state_dir=state_dir, data_dir=data_dir,
            log_path=tmp_path / "agent-first.log",
        )
        agents.append(first)
        context["agent"] = first
        worker_identity = wait_worker_started(
            stack, staged, state_dir, context, task_id=RESTART_ORIGINAL_TASK,
        )
        assert process_alive(worker_identity)
        assert task_row(stack["repository"], RESTART_ORIGINAL_TASK)["status"] == "RUNNING"
        held_status = central_status(stack, RESTART_ORIGINAL_TASK)
        assert held_status["hold_state"] == "HELD"
        # SQL NULL stop-proof fields must stay null while the execution is HELD.
        assert held_status["proof_type"] is None
        assert held_status["proof_sha256"] is None

        # Ordinary process termination request (SIGTERM semantics on POSIX,
        # TerminateProcess on Windows: Python does not run SIGTERM handlers there).
        first["process"].terminate()
        exit_code = first["process"].wait(timeout=60)

        if os.name == "nt":
            # An abruptly stopped Windows Agent cannot prove descendant cleanup;
            # neither the worker nor its durable identity may be discarded.
            assert process_alive(worker_identity), (
                "forced Windows Agent stop must not kill the training worker"
            )
            assert local_identity(state_dir, RESTART_ORIGINAL_TASK, 1) is not None
            assert [
                record for record in intent_records(state_dir)
                if record.get("task_id") == RESTART_ORIGINAL_TASK
            ], "dual-slot intent must survive the forced Windows Agent stop"
        else:
            assert exit_code == 0, f"graceful Agent shutdown returned {exit_code}"
            assert wait_process_gone(worker_identity, timeout=30), (
                "graceful POSIX Agent shutdown must stop the owned training worker"
            )
            assert local_identity(state_dir, RESTART_ORIGINAL_TASK, 1) is None, (
                "graceful POSIX Agent shutdown must clear the verified process identity"
            )

        # A new task is already assigned to the node before the restarted Agent
        # comes up.  The restarted Agent must never turn it into a RUNNING lease
        # while recovery is fail-closed.
        heartbeat_with_gpus(stack)
        create_training_task(
            stack, tmp_path, storage, task_id=RESTART_CANDIDATE_TASK, gpu_uuid=GPU_B,
        )
        assign_next(stack)

        restarted = launch_agent(
            staged, stack, state_dir=state_dir, data_dir=data_dir,
            log_path=tmp_path / "agent-restarted.log",
        )
        agents.append(restarted)
        context["agent"] = restarted

        heartbeat_errors: list[str] = []

        def node_withdrew_capabilities():
            node = node_public(stack)
            heartbeat_errors.append(str(node.get("last_error") or ""))
            return node if node["reported_capabilities"] == [] else None

        wait_for(
            node_withdrew_capabilities,
            timeout=90,
            message="restarted real Agent did not withdraw all remote capabilities",
            context=context,
        )
        node = node_public(stack)
        assert "training" not in node["reported_capabilities"]
        assert "execution-slots:2" not in node["reported_capabilities"]
        assert restarted["process"].poll() is None, (
            "restarted real Agent must stay alive while failing closed"
        )

        if os.name == "nt":
            wait_for(
                lambda: JOB_OBJECT_ERROR in (node_public(stack).get("last_error") or ""),
                timeout=45,
                message=(
                    "Windows restart must publish the Job Object stop-proof error in the "
                    f"node heartbeat; observed errors={heartbeat_errors[-10:]}"
                ),
                context=context,
            )
            assert process_alive(worker_identity), (
                "fail-closed Windows restart must not kill an unproven worker"
            )
            assert local_identity(state_dir, RESTART_ORIGINAL_TASK, 1) is not None, (
                "fail-closed Windows restart must retain the persisted process identity"
            )
        else:
            wait_for(
                lambda: INTENT_ERROR in (node_public(stack).get("last_error") or ""),
                timeout=45,
                message=(
                    "POSIX restart must keep blocking on the persisted dual-slot intent; "
                    f"observed errors={heartbeat_errors[-10:]}"
                ),
                context=context,
            )

        # Give the restarted executor several poll cycles to prove it never claims.
        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            candidate = task_row(stack["repository"], RESTART_CANDIDATE_TASK)
            assert candidate["status"] == "QUEUED", (
                f"fail-closed restart claimed the candidate task: {candidate}"
            )
            assert int(candidate["attempt"]) == 0
            assert hold_row(stack["repository"], RESTART_CANDIDATE_TASK) is None
            time.sleep(0.2)
        assignments = assignment_rows(stack["repository"], RESTART_CANDIDATE_TASK)
        assert len(assignments) == 1
        assert assignments[0]["state"] == "ASSIGNED", (
            f"restarted Agent must not claim the assignment: {assignments}"
        )
        original = task_row(stack["repository"], RESTART_ORIGINAL_TASK)
        assert original["status"] == "RUNNING", (
            "the original execution must stay RUNNING until a central stop proof exists: "
            f"{original}"
        )
        assert_no_duplicate_execution(stack["repository"], RESTART_ORIGINAL_TASK)
    finally:
        for agent in agents:
            stop_agent(agent)
        if worker_identity is not None:
            kill_process_identity(worker_identity)
        try:
            for record in local_workdirs(state_dir).list_process_identities():
                kill_process_identity(record)
        except Exception:
            pass
        storage.stop()
        stop_central(stack)


__all__ = [
    "AGENT_VERSION", "BundleStorage", "GPU_A", "GPU_B", "INTENT_ERROR",
    "JOB_OBJECT_ERROR", "NODE_ID", "REPO_ROOT", "RESTART_CANDIDATE_TASK",
    "RESTART_ORIGINAL_TASK", "assert_no_duplicate_execution", "assign_next",
    "attempt_rows", "canonical_json", "central_status", "create_training_task",
    "diagnostics", "expected_stop_proof_digest", "free_port", "heartbeat_with_gpus",
    "hold_row", "intent_records", "kill_process_identity", "launch_agent",
    "local_identity", "local_workdirs", "node_public", "process_alive", "read_log",
    "require_linux_posix", "run_restart_fail_closed_scenario", "start_central",
    "stop_agent", "stop_central", "task_row", "unit_fixtures", "wait_for",
    "wait_process_gone", "wait_worker_started", "write_staged_runtime",
]
