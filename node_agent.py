from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import requests

from platform_core.build_identity import resolve_build_id
from platform_core.node_agent_runtime import (
    build_heartbeat_payload,
    collect_local_snapshot,
    collect_runtime_probe,
    normalize_agent_capabilities,
    send_heartbeat,
)
from platform_core.node_identity import resolve_node_identity


def _env_capabilities() -> list[str]:
    raw = str(os.environ.get("MC_NODE_CAPABILITIES") or "")
    return [value.strip() for value in raw.split(",") if value.strip()]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="畅联云服务节点 Agent")
    parser.add_argument("--control-plane", default=os.environ.get("MC_CONTROL_PLANE_URL", ""))
    parser.add_argument("--node-id", default=os.environ.get("MC_NODE_ID", ""))
    parser.add_argument("--token", default=os.environ.get("MC_NODE_AGENT_TOKEN", ""))
    parser.add_argument("--data-dir", default=os.environ.get("MC_TRAIN_DATA_DIR", ""))
    parser.add_argument("--capabilities", nargs="*", default=_env_capabilities())
    parser.add_argument("--interval", type=float, default=10.0)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = Path(args.data_dir).expanduser().resolve() if str(args.data_dir).strip() else None
    identity = resolve_node_identity()
    node_id = str(args.node_id or identity.node_id).strip()
    try:
        capabilities = normalize_agent_capabilities(args.capabilities)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    runtime_probe = collect_runtime_probe(data_dir)
    build_id = resolve_build_id(Path(__file__).resolve().parent)

    if args.check:
        snapshot = collect_local_snapshot(data_dir=data_dir, runtime_probe=runtime_probe)
        print(json.dumps({
            "ok": True,
            "node_id": node_id,
            "node_identity_source": identity.source,
            "capabilities": capabilities,
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

    interval = max(3.0, float(args.interval))
    session = requests.Session()
    last_error = ""
    while True:
        snapshot = collect_local_snapshot(data_dir=data_dir, runtime_probe=runtime_probe)
        payload = build_heartbeat_payload(
            snapshot,
            capabilities=capabilities,
            build_id=build_id,
            last_error=last_error,
        )
        try:
            response = send_heartbeat(
                control_plane,
                node_id,
                token,
                payload,
                session=session,
            )
            last_error = ""
            print(json.dumps({
                "ok": True,
                "node_id": node_id,
                "status": response.get("node", {}).get("status"),
                "desired": response.get("desired", {}),
            }, ensure_ascii=False), flush=True)
        except (OSError, ValueError, RuntimeError, requests.RequestException) as error:
            last_error = f"{type(error).__name__}: {error}"
            print(last_error, file=sys.stderr, flush=True)
            if args.once:
                return 3
        if args.once:
            return 0
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
