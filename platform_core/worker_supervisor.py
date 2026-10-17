from __future__ import annotations

import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Iterable, Sequence


TRAINING_ROLES = ("training",)
BACKGROUND_ROLES = (
    "discovery",
    "storage",
    "materials",
    "video",
    "annotation",
    "conversion",
    "deployment-test",
    "training-prep",
)
SUPERVISOR_POLL_SECONDS = 0.25


def isolated_role_groups(roles: Iterable[str]) -> tuple[tuple[str, ...], ...]:
    """Resolve the process-level role groups used by the compatibility `all` mode.

    `all` remains a supported CLI surface, but it no longer means one Scheduler
    serially owns training and every non-training task kind.  The compatibility
    mode supervises a dedicated training Worker and a separate background Worker.
    Explicit role selections retain their existing single-Worker semantics.
    """

    normalized = {str(role).strip().lower() for role in roles if str(role).strip()}
    if normalized == {"all"}:
        return (TRAINING_ROLES, BACKGROUND_ROLES)
    return (tuple(sorted(normalized)),)


def child_worker_command(
    *,
    script: Path,
    data_dir: Path,
    roles: Sequence[str],
    worker_id: str,
    once: bool = False,
) -> list[str]:
    command = [
        sys.executable,
        str(script),
        "--data-dir",
        str(data_dir),
        "--roles",
        *[str(role) for role in roles],
        "--worker-id",
        str(worker_id),
    ]
    if once:
        command.append("--once")
    return command


def _terminate_processes(processes: Sequence[subprocess.Popen]) -> None:
    for process in processes:
        if process.poll() is None:
            try:
                process.terminate()
            except OSError:
                pass

    deadline = time.monotonic() + 5.0
    for process in processes:
        if process.poll() is not None:
            continue
        remaining = max(0.0, deadline - time.monotonic())
        try:
            process.wait(timeout=remaining)
        except (subprocess.TimeoutExpired, OSError):
            try:
                process.kill()
            except OSError:
                pass


def run_isolated_all_roles(
    *,
    data_dir: Path,
    worker_id: str,
    once: bool = False,
    script: Path | None = None,
) -> int:
    """Run legacy `--roles all` as isolated Worker processes.

    This is deliberately a supervisor only.  It does not own a Scheduler,
    heartbeat or task lease itself, so the existing Worker Runtime remains the
    single source of execution truth for each child Worker.
    """

    worker_script = script or (Path(__file__).resolve().parent.parent / "task_worker.py")
    root = worker_script.parent
    groups = isolated_role_groups({"all"})
    labels = ("training", "background")
    processes: list[subprocess.Popen] = []

    previous_handlers: dict[int, object] = {}
    stop_requested = False

    def request_stop(_signum, _frame) -> None:
        nonlocal stop_requested
        stop_requested = True

    try:
        for label, roles in zip(labels, groups, strict=True):
            command = child_worker_command(
                script=worker_script,
                data_dir=data_dir,
                roles=roles,
                worker_id=f"{worker_id}-{label}",
                once=once,
            )
            processes.append(
                subprocess.Popen(
                    command,
                    cwd=str(root),
                    shell=False,
                )
            )

        if once:
            codes = [process.wait() for process in processes]
            return next((int(code) for code in codes if int(code) != 0), 0)

        for signum in (signal.SIGINT, signal.SIGTERM):
            try:
                previous_handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, request_stop)
            except (ValueError, OSError):
                # signal.signal is only legal from the main thread and some
                # platforms expose fewer signal handlers.  Launcher shutdown
                # still terminates the supervisor process normally.
                continue

        while not stop_requested:
            for process in processes:
                code = process.poll()
                if code is not None:
                    # A continuously running child exiting is unhealthy even
                    # with code 0: without it one execution class would silently
                    # disappear while the supervisor looked healthy.
                    return int(code) if int(code) != 0 else 1
            time.sleep(SUPERVISOR_POLL_SECONDS)
        return 0
    finally:
        _terminate_processes(processes)
        for signum, handler in previous_handlers.items():
            try:
                signal.signal(signum, handler)
            except (ValueError, OSError):
                pass


__all__ = [
    "BACKGROUND_ROLES",
    "SUPERVISOR_POLL_SECONDS",
    "TRAINING_ROLES",
    "child_worker_command",
    "isolated_role_groups",
    "run_isolated_all_roles",
]
