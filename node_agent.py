from __future__ import annotations

import argparse
import json
import os
import signal
import sys
import threading
from pathlib import Path

import requests

from platform_core.build_identity import resolve_build_id
from platform_core.node_agent_deployment_runtime import AgentDeploymentRunner
from platform_core.node_agent_executor_loop import (
    NodeAgentExecutorLoop,
    executable_agent_capabilities,
)
from platform_core.node_agent_executor_runtime import (
    AgentExecutionWorkdir,
    NodeExecutorClient,
)
from platform_core.node_agent_runtime import (
    build_heartbeat_payload,
    collect_local_snapshot,
    collect_runtime_probe,
    normalize_agent_capabilities,
    send_heartbeat,
)
from platform_core.node_identity import default_node_state_dir, resolve_node_identity


def _env_capabilities() -> list[str]:
    raw = str(os.environ.get("MC_NODE_CAPABILITIES") or "")
    return [value.strip() for value in raw.split(",") if value.strip()]


def _env_float(name: str, fallback: float) -> float:
    raw = str(os.environ.get(name) or "").strip()
    if not raw:
        return float(fallback)
    try:
        return float(raw)
    except ValueError:
        return float(fallback)


def _state_dir(value: object) -> Path:
    raw = str(value or "").strip()
    return (
        Path(raw).expanduser().resolve()
        if raw
        else default_node_state_dir()
    )


def _combined_error(heartbeat_error: str, executor: NodeAgentExecutorLoop | None) -> str:
    values = [str(heartbeat_error or "").strip()]
    if executor is not None:
        values.append(str(executor.last_error() or "").strip())
    return " | ".join(value for value in values if value)[:4000]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="畅联云服务节点 Agent")
    parser.add_argument("--control-plane", default=os.environ.get("MC_CONTROL_PLANE_URL", ""))
    parser.add_argument("--node-id", default=os.environ.get("MC_NODE_ID", ""))
    parser.add_argument("--token", default=os.environ.get("MC_NODE_AGENT_TOKEN", ""))
    parser.add_argument("--data-dir", default=os.environ.get("MC_TRAIN_DATA_DIR", ""))
    parser.add_argument("--state-dir", default=os.environ.get("MC_NODE_STATE_DIR", ""))
    parser.add_argument("--capabilities", nargs="*", default=_env_capabilities())
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument(
        "--executor-poll-interval",
        type=float,
        default=_env_float("MC_NODE_EXECUTOR_POLL_SECONDS", 2.0),
    )
    parser.add_argument(
        "--execution-heartbeat-interval",
        type=float,
        default=_env_float("MC_NODE_EXECUTION_HEARTBEAT_SECONDS", 5.0),
    )
    parser.add_argument(
        "--ultralytics-python",
        default=os.environ.get("MC_AGENT_ULTRALYTICS_PYTHON", ""),
    )
    parser.add_argument(
        "--paddle-python",
        default=os.environ.get("MC_AGENT_PADDLE_PYTHON", ""),
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser


def _install_stop_handlers(stop_event: threading.Event):
    previous = {}

    def request_stop(_signum, _frame):
        stop_event.set()

    for name in ("SIGINT", "SIGTERM"):
        signum = getattr(signal, name, None)
        if signum is None:
            continue
        try:
            previous[signum] = signal.getsignal(signum)
            signal.signal(signum, request_stop)
        except (ValueError, OSError):
            continue
    return previous


def _restore_stop_handlers(previous) -> None:
    for signum, handler in dict(previous or {}).items():
        try:
            signal.signal(signum, handler)
        except (ValueError, OSError):
            pass


def _build_executor(
    *,
    control_plane: str,
    node_id: str,
    token: str,
    state_dir: Path,
    runtime_probe: dict,
    reported_capabilities: list[str],
    args,
) -> NodeAgentExecutorLoop | None:
    if not reported_capabilities:
        return None
    client = NodeExecutorClient(control_plane, node_id, token)
    workdirs = AgentExecutionWorkdir(state_dir / "executor")
    ultralytics_python = str(args.ultralytics_python or "").strip() or str(
        runtime_probe.get("python_executable") or sys.executable
    )
    paddle_python = str(args.paddle_python or "").strip() or sys.executable
    deployment_runner = AgentDeploymentRunner(
        client,
        workdirs,
        runtime_root=Path(__file__).resolve().parent,
        python_by_framework={
            "ultralytics": ultralytics_python,
            "paddle": paddle_python,
        },
        heartbeat_interval=max(1.0, float(args.execution_heartbeat_interval)),
    )
    return NodeAgentExecutorLoop(
        client,
        deployment_runner,
        capabilities=reported_capabilities,
        poll_interval=max(0.5, float(args.executor_poll_interval)),
    )


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir).expanduser().resolve() if str(args.data_dir).strip() else None
    state_dir = _state_dir(args.state_dir)
    identity = (
        resolve_node_identity(state_dir=state_dir)
        if str(args.state_dir or "").strip()
        else resolve_node_identity()
    )
    node_id = str(args.node_id or identity.node_id).strip()
    try:
        requested_capabilities = normalize_agent_capabilities(args.capabilities)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    reported_capabilities = executable_agent_capabilities(requested_capabilities)
    unsupported_remote_capabilities = sorted(
        set(requested_capabilities) - set(reported_capabilities)
    )
    runtime_probe = collect_runtime_probe(data_dir)
    build_id = resolve_build_id(Path(__file__).resolve().parent)

    if args.check:
        snapshot = collect_local_snapshot(data_dir=data_dir, runtime_probe=runtime_probe)
        print(json.dumps({
            "ok": True,
            "node_id": node_id,
            "node_identity_source": identity.source,
            "capabilities": requested_capabilities,
            "reported_capabilities": reported_capabilities,
            "unsupported_remote_capabilities": unsupported_remote_capabilities,
            "executor": {
                "enabled": bool(reported_capabilities),
                "supported_task_kinds": ["DEPLOYMENT_TEST"],
                "state_dir": str(state_dir / "executor"),
                "ultralytics_python": str(args.ultralytics_python or "").strip()
                or str(runtime_probe.get("python_executable") or sys.executable),
                "paddle_python": str(args.paddle_python or "").strip() or sys.executable,
            },
            "build_id": build_id,
            "snapshot": snapshot,
        }, ensure_ascii=False))
        return 0

    control_plane = str(args.control_plane or "").strip()
    token = str(args.token or "").strip()
    if not control_plane or not token:
        print(
            "Node Agent requires --control-plane/MC_CONTROL_PLANE_URL and --token/MC_NODE_AGENT_TOKEN",
            file=sys.stderr,
        )
        return 2

    if unsupported_remote_capabilities:
        print(
            "Node Agent will not report unimplemented remote capabilities: "
            + ", ".join(unsupported_remote_capabilities),
            file=sys.stderr,
            flush=True,
        )

    interval = max(3.0, float(args.interval))
    heartbeat_session = requests.Session()
    heartbeat_error = ""
    executor: NodeAgentExecutorLoop | None = None
    executor_started = False
    # Preserve --once semantics: one heartbeat only, never claim remote work.
    if not args.once:
        executor = _build_executor(
            control_plane=control_plane,
            node_id=node_id,
            token=token,
            state_dir=state_dir,
            runtime_probe=runtime_probe,
            reported_capabilities=reported_capabilities,
            args=args,
        )

    stop_event = threading.Event()
    previous_handlers = _install_stop_handlers(stop_event)
    try:
        while not stop_event.is_set():
            snapshot = collect_local_snapshot(data_dir=data_dir, runtime_probe=runtime_probe)
            payload = build_heartbeat_payload(
                snapshot,
                capabilities=reported_capabilities,
                build_id=build_id,
                active_tasks=executor.active_tasks() if executor is not None else (),
                last_error=_combined_error(heartbeat_error, executor),
            )
            try:
                response = send_heartbeat(
                    control_plane,
                    node_id,
                    token,
                    payload,
                    session=heartbeat_session,
                )
                heartbeat_error = ""
                if executor is not None and not executor_started:
                    executor.start()
                    executor_started = True
                executor_status = executor.status() if executor is not None else None
                print(json.dumps({
                    "ok": True,
                    "node_id": node_id,
                    "status": response.get("node", {}).get("status"),
                    "desired": response.get("desired", {}),
                    "executor": {
                        "enabled": bool(executor is not None),
                        "running": bool(executor_status.running) if executor_status else False,
                        "active_tasks": list(executor_status.active_tasks) if executor_status else [],
                        "last_outcome": executor_status.last_outcome if executor_status else "",
                    },
                }, ensure_ascii=False), flush=True)
            except (OSError, ValueError, RuntimeError, requests.RequestException) as error:
                heartbeat_error = f"{type(error).__name__}: {error}"
                print(heartbeat_error, file=sys.stderr, flush=True)
                if args.once:
                    return 3
            if args.once:
                return 0
            stop_event.wait(interval)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        if executor is not None:
            executor.stop(timeout=10.0)
        try:
            heartbeat_session.close()
        except Exception:
            pass
        _restore_stop_handlers(previous_handlers)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
