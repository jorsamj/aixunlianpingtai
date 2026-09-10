from __future__ import annotations

import argparse
import json
import sqlite3
import socket
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

from platform_core.runtime_paths import resolve_data_dir
from platform_core.task_runtime import (
    ArtifactStore,
    DuplicateWorkerInstance,
    ProcessController,
    Scheduler,
    TaskRepository,
    WorkerInstanceService,
    launch_process,
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


def _role_worker_command(args, data_dir: Path, role: str, worker_id: str) -> list[str]:
    command = [
        sys.executable,
        str(Path(__file__).resolve()),
        "--data-dir", str(data_dir),
        "--worker-id", worker_id,
        "--roles", role,
    ]
    if role == "training" and args.training_slot:
        command.extend(["--training-slot", str(args.training_slot)])
    return command


def _serve_all_roles(args, data_dir: Path) -> int:
    """Supervise one OS process per role so long tasks cannot block unrelated work.

    Historically ``--roles all`` put import, annotation, video, training and
    conversion handlers behind one serial Scheduler. A 50k import could
    therefore prevent a queued training/annotation task from starting for
    hours. Role-isolated processes keep the same durable SQLite queue and
    resource fencing while providing independent execution lanes.
    """
    if args.allow_parallel or args.worker_slot:
        print("--roles all uses isolated role workers automatically; do not combine it with --allow-parallel/--worker-slot",
              file=sys.stderr)
        return 2

    base_worker_id = args.worker_id or f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"
    children = {}
    next_retry: dict[str, float] = {role: 0.0 for role in ROLE_MODULES}
    controller = ProcessController()

    def start(role: str) -> None:
        child_id = f"{base_worker_id}-{role}"
        command = _role_worker_command(args, data_dir, role, child_id)
        launched = launch_process(command, cwd=Path(__file__).resolve().parent)
        children[role] = launched
        print(f"[worker-supervisor] started role={role} pid={launched.process.pid}", flush=True)

    def stop_all() -> None:
        # Use the same PID birth-time/command/group/token fencing as task
        # subprocesses. This also terminates grandchildren on Windows/Linux,
        # preventing an abrupt supervisor exit from orphaning YOLO/conversion.
        for launched in list(children.values()):
            if launched.process.poll() is not None:
                continue
            try:
                controller.terminate_tree(launched.identity, timeout=8.0)
            except (ProcessLookupError, PermissionError):
                pass

    try:
        for role in sorted(ROLE_MODULES):
            start(role)
        while True:
            now = time.monotonic()
            for role in sorted(ROLE_MODULES):
                launched = children.get(role)
                if launched is None:
                    if now >= next_retry[role]:
                        start(role)
                    continue
                return_code = launched.process.poll()
                if return_code is None:
                    continue
                children.pop(role, None)
                # Exit code 3 means another durable instance already owns this
                # role. Do not spin; retry slowly so takeover can occur later.
                delay = 30.0 if return_code == 3 else 2.0
                next_retry[role] = now + delay
                print(
                    f"[worker-supervisor] role={role} exited code={return_code}; retry in {int(delay)}s",
                    file=sys.stderr,
                    flush=True,
                )
            time.sleep(0.5)
    except KeyboardInterrupt:
        return 0
    finally:
        stop_all()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    data_dir = resolve_data_dir(args.data_dir)
    roles = set(args.roles)
    if "all" in roles and len(roles) != 1:
        print("--roles all cannot be combined with explicit roles", file=sys.stderr)
        return 2
    unknown_roles = roles - ({"all"} | set(ROLE_MODULES))
    if unknown_roles:
        print(f"unknown worker roles: {', '.join(sorted(unknown_roles))}", file=sys.stderr)
        return 2

    # Preserve the historical --once/--check semantics. Continuous all-role
    # mode becomes a supervisor; each child owns one Scheduler and one role.
    if roles == {"all"} and not args.once and not args.check:
        if args.training_slot is not None and (not str(args.training_slot).strip() or args.training_slot == "default"):
            print("--training-slot must be a non-default, non-empty slot name", file=sys.stderr)
            return 2
        return _serve_all_roles(args, data_dir)

    runtime_dir = data_dir / "task_runtime"
    database_path = (runtime_dir / "tasks.sqlite3").resolve()
    failures = 0
    while True:
        try:
            # The API owns first-time schema creation. A Worker must never
            # turn a missing/unmounted production database into an empty one.
            repository = TaskRepository(database_path, allow_create=False)
            break
        except sqlite3.Error as error:
            failures += 1
            try:
                runtime_dir.mkdir(parents=True, exist_ok=True)
                status_path = runtime_dir / "worker-status.json"
                status_path.write_text(json.dumps({
                    "status": "DATABASE_ERROR", "database": str(database_path),
                    "parent": str(database_path.parent), "parent_exists": database_path.parent.is_dir(),
                    "error": f"{type(error).__name__}: {error}", "attempt": failures,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }, ensure_ascii=False, indent=2), encoding="utf-8")
            except OSError:
                pass
            print(f"任务数据库不可用（第 {failures} 次）：{database_path}；{error}", file=sys.stderr)
            if args.once or args.check:
                return 4
            time.sleep(min(30.0, 0.5 * (2 ** min(failures, 6))))
    artifacts = ArtifactStore(runtime_dir / "artifacts")
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
                    "role_isolation": "subprocess-per-role" if roles == {"all"} else "single-role-or-explicit-set",
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
