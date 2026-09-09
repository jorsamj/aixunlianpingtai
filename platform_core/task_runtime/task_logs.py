"""Real task logs and child output capture without redirecting global streams."""
from __future__ import annotations

import os
import subprocess
from contextlib import contextmanager

from .models import utc_now
from .process_control import ProcessController, launch_process


def create_task_log(artifacts, task_id: str, log_ref: str = "logs/task.log") -> str:
    path = artifacts.artifact_path(task_id, log_ref)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="") as stream:
        stream.write(f"{utc_now()} task={task_id} phase=created\n")
        stream.flush()
        os.fsync(stream.fileno())
    return log_ref


def append_task_log(context, phase: str, message: str = "") -> None:
    from platform_core.storage.errors import redact_storage_error

    context.artifacts.append_log(
        context.task.task_id, context.task.log_ref,
        f"{utc_now()} task={context.task.task_id} phase={phase} "
        f"{redact_storage_error(message)}\n",
    )


@contextmanager
def child_output(context):
    """Pass this file as both stdout and stderr; output stays bounded on disk."""
    path = context.artifacts.artifact_path(context.task.task_id, context.task.log_ref)
    # Creation belongs to task submission. A missing artifact is an error here.
    descriptor = os.open(path, os.O_WRONLY | os.O_APPEND | getattr(os, "O_BINARY", 0))
    with os.fdopen(descriptor, "ab") as stream:
        yield stream
        stream.flush()


def run_logged_process(context, argv, *, cwd=None, env=None) -> int:
    """Capture a child and terminate its verified tree on cancellation/lost lease."""
    append_task_log(context, "child_started")
    with child_output(context) as output:
        launched = launch_process(argv, cwd=cwd, env=env, stdout=output, stderr=subprocess.STDOUT)
        try:
            context.repository.bind_process(context.task.task_id, context.lease.lease_token, launched.identity)
            while True:
                if context.cancel_requested():
                    raise InterruptedError("task cancelled")
                context.repository.heartbeat(context.task.task_id, context.lease.lease_token)
                try:
                    code = launched.process.wait(timeout=1)
                    break
                except subprocess.TimeoutExpired:
                    continue
        except BaseException:
            ProcessController().terminate_tree(launched.identity)
            raise
    append_task_log(context, "child_exited", f"exit_code={code}")
    if code:
        raise RuntimeError(f"child process exited with code {code}; see task log")
    return code
