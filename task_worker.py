from __future__ import annotations

import argparse
import json
import socket
import sys
import uuid

from platform_core.runtime_paths import resolve_data_dir
from platform_core.task_runtime import ArtifactStore, Scheduler, TaskRepository
from platform_core.worker_registry import ROLE_MODULES, build_worker_registration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="畅联云后台任务 Worker")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--roles", nargs="+", default=["all"])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = resolve_data_dir(args.data_dir)
    runtime_dir = data_dir / "task_runtime"
    repository = TaskRepository(runtime_dir / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime_dir / "artifacts")
    roles = set(args.roles)
    handlers, capabilities = build_worker_registration(data_dir, roles)
    worker_id = args.worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

    if args.check:
        print(
            json.dumps(
                {
                    "ok": True,
                    "data_dir": str(data_dir),
                    "database": str(repository.path),
                    "artifact_dir": str(artifacts.root),
                    "roles": sorted(set(ROLE_MODULES) if "all" in roles else roles),
                    "handlers": sorted(kind.value for kind in handlers),
                    "capabilities": sorted(capabilities),
                    "web_imported": "app" in sys.modules,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if not handlers:
        print("当前 Worker 角色没有可用的任务处理器", file=sys.stderr)
        return 2

    scheduler = Scheduler(
        repository,
        artifacts,
        worker_id,
        handlers,
        capabilities,
    )
    if args.once:
        scheduler.run_once()
        return 0
    scheduler.serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
