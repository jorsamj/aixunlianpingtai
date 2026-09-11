from __future__ import annotations

import argparse
import json
import socket
import sys
import uuid

from platform_core.runtime_paths import resolve_data_dir
from platform_core.task_runtime import (
    ArtifactStore,
    DuplicateWorkerInstance,
    FencedTaskRepository,
    Scheduler,
    WorkerInstanceService,
)
from platform_core.gpu_resources import GPUResourceManager
from platform_core.training_devices import training_python
from platform_core.worker_registry import ROLE_MODULES, build_worker_registration


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="畅联云后台任务 Worker")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--worker-id", default=None)
    parser.add_argument("--roles", nargs="+", default=["all"])
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--training-slot", default=None,
                        help="Named training-only slot for intentional GPU concurrency (requires --roles training)")
    parser.add_argument("--allow-parallel", action="store_true")
    parser.add_argument("--worker-slot", default=None,
                        help="Named process slot for an explicitly parallel Worker (requires --allow-parallel)")
    return parser


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = resolve_data_dir(args.data_dir)
    runtime_dir = data_dir / "task_runtime"
    repository = FencedTaskRepository(runtime_dir / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime_dir / "artifacts")
    roles = set(args.roles)
    worker_slot = (args.worker_slot or "").strip()
    if args.allow_parallel and (not worker_slot or worker_slot == "default"):
        print("--allow-parallel requires a non-default named --worker-slot", file=sys.stderr)
        return 2
    if worker_slot and not args.allow_parallel:
        print("--worker-slot requires --allow-parallel", file=sys.stderr)
        return 2
    if args.training_slot is not None and (roles != {"training"} or not args.training_slot.strip() or args.training_slot == "default"):
        print("--training-slot requires --roles training and a non-default, non-empty slot name", file=sys.stderr)
        return 2
    handlers, capabilities = build_worker_registration(data_dir, roles)
    worker_id = args.worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    instance_roles = sorted(set(ROLE_MODULES) if "all" in roles else roles)
    instance_slot = worker_slot if args.allow_parallel else "default"

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
                    "training_slot": args.training_slot or "default",
                    "worker_slot": instance_slot,
                    "execution_fencing": True,
                },
                ensure_ascii=False,
            )
        )
        return 0
    if not handlers:
        print("当前 Worker 角色没有可用的任务处理器", file=sys.stderr)
        return 2

    try:
        instance_lease = WorkerInstanceService(repository).acquire(
            data_dir, instance_roles, instance_slot, worker_id
        )
    except DuplicateWorkerInstance as error:
        print(
            "Worker 启动被拒绝：相同数据目录、主机、角色和 slot 已有活动实例 "
            f"(worker_id={error.worker_id}, pid={error.pid})。"
            "如需有意并行，请使用 --allow-parallel --worker-slot NAME。",
            file=sys.stderr,
        )
        return 3

    try:
        scheduler = Scheduler(
            repository,
            artifacts,
            worker_id,
            handlers,
            capabilities,
            gpu_resources=GPUResourceManager(repository, artifacts, worker_slot=args.training_slot or "default",
                                             python_executable=training_python(data_dir)) if "training.ultralytics" in capabilities else None,
            worker_instance=instance_lease,
        )
        if args.once:
            scheduler.run_once()
            return 0
        scheduler.serve_forever()
        return 0
    finally:
        instance_lease.release()


if __name__ == "__main__":
    raise SystemExit(main())
