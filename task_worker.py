from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import uuid
from pathlib import Path

from platform_core.runtime_paths import resolve_data_dir
from platform_core.build_identity import resolve_build_id
from platform_core.node_identity import resolve_node_identity
from platform_core.storage.material_cache_runtime import MaterialCacheRuntimeReporter
from platform_core.upgrade_guard import ensure_worker_build_compatible, write_worker_build_marker
from platform_core.task_runtime import (
    ArtifactStore,
    DuplicateWorkerInstance,
    FencedTaskRepository,
    Scheduler,
    WorkerInstanceService,
)
from platform_core.gpu_resources import GPUResourceManager
from platform_core.training_devices import training_python
from platform_core.worker_registry import resolve_worker_registration
from platform_core.worker_supervisor import run_isolated_all_roles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="畅联云后台任务 Worker")
    parser.add_argument("--data-dir", default=None)
    parser.add_argument("--worker-id", default=None)
    parser.add_argument(
        "--roles",
        nargs="+",
        default=["all"],
        help=(
            "Worker roles. Compatibility role 'all' now supervises an isolated "
            "training Worker plus a separate non-training background Worker."
        ),
    )
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
    node_identity = resolve_node_identity()
    build_id = resolve_build_id(Path(__file__).resolve().parent)
    if not args.check:
        try:
            ensure_worker_build_compatible(
                data_dir,
                build_id,
                allow_active_upgrade=os.environ.get("MC_ALLOW_ACTIVE_TASK_UPGRADE", "").strip() == "1",
            )
        except RuntimeError as error:
            print(f"Worker 启动被升级保护拒绝：{error}", file=sys.stderr)
            return 4

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

    worker_id = args.worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"

    # Backward-compatible `--roles all` no longer means one serial Scheduler
    # owns training plus every background task kind.  That layout allowed a
    # long material scan/annotation/video task to block an otherwise runnable
    # GPU training task.  Keep the CLI surface, but make it a supervisor for
    # two real Worker processes using the existing Worker Runtime/Scheduler.
    if roles == {"all"} and not args.check:
        if args.allow_parallel or worker_slot or args.training_slot is not None:
            print(
                "--roles all is an isolated compatibility supervisor; use explicit roles "
                "when configuring parallel worker/training slots",
                file=sys.stderr,
            )
            return 2
        print(
            "Worker roles=all: starting isolated training and background Worker processes",
            flush=True,
        )
        return run_isolated_all_roles(
            data_dir=data_dir,
            worker_id=worker_id,
            once=bool(args.once),
        )

    runtime_dir = data_dir / "task_runtime"
    repository = FencedTaskRepository(runtime_dir / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime_dir / "artifacts")
    registration = resolve_worker_registration(data_dir, roles)
    handlers = registration.handlers
    capabilities = registration.capabilities
    instance_roles = sorted(registration.roles)
    instance_slot = worker_slot if args.allow_parallel else "default"

    if args.check:
        print(
            json.dumps(
                {
                    "ok": True,
                    "data_dir": str(data_dir),
                    "database": str(repository.path),
                    "artifact_dir": str(artifacts.root),
                    "roles": instance_roles,
                    "handlers": sorted(kind.value for kind in handlers),
                    "capabilities": sorted(capabilities),
                    "web_imported": "app" in sys.modules,
                    "training_slot": args.training_slot or "default",
                    "worker_slot": instance_slot,
                    "execution_fencing": True,
                    "build_id": build_id,
                    "node_id": node_identity.node_id,
                    "hostname": node_identity.hostname,
                    "node_identity_source": node_identity.source,
                    "all_role_execution": "isolated_supervisor" if roles == {"all"} else "single_worker",
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
            data_dir,
            instance_roles,
            instance_slot,
            worker_id,
            node_id=node_identity.node_id,
            hostname=socket.gethostname(),
            build_id=build_id,
            task_kinds=(kind.value for kind in handlers),
            capabilities=capabilities,
        )
    except DuplicateWorkerInstance as error:
        print(
            "Worker 启动被拒绝：相同数据目录、主机、角色和 slot 已有活动实例 "
            f"(worker_id={error.worker_id}, pid={error.pid})。"
            "如需有意并行，请使用 --allow-parallel --worker-slot NAME。",
            file=sys.stderr,
        )
        return 3

    # Cache observability is an observer of the existing Worker heartbeat, not
    # another timer/registry. A reporting failure is intentionally non-fatal.
    cache_reporter = MaterialCacheRuntimeReporter(repository, instance_lease, data_dir)
    try:
        cache_reporter.report()
    except Exception:
        pass
    instance_lease.add_renew_hook(cache_reporter.report)

    try:
        write_worker_build_marker(data_dir, build_id)
        scheduler = Scheduler(
            repository,
            artifacts,
            worker_id,
            handlers,
            capabilities,
            gpu_resources=GPUResourceManager(repository, artifacts, worker_slot=args.training_slot or "default",
                                             python_executable=training_python(data_dir),
                                             node_id=node_identity.node_id,
                                             worker_id=worker_id) if "training.ultralytics" in capabilities else None,
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