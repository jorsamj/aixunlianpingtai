"""Prevent training children from touching GPU/run data before durable PID binding."""
import json
import os
import sqlite3
import time
from contextlib import closing

from .process_control import ProcessController, ProcessIdentity
from .sqlite_busy import confirmed_deadline, is_sqlite_busy


ENV_KEY = "CHANGLIAN_TRAINING_EXECUTION_GATE"


def execution_environment(context):
    path = getattr(context.repository, "path", None)
    if path is None:  # legacy in-memory test ports have no durable execution
        return {}
    current = context.assert_current_execution()
    return {ENV_KEY: json.dumps({
        "database": str(path), "task_id": context.task.task_id,
        "token": context.lease.lease_token, "generation": context.execution_generation,
        "expires_at": current.lease_expires_at,
    })}


def wait_for_execution_binding():
    value = os.environ.get(ENV_KEY)
    if not value:  # standalone/legacy invocation retains its original contract
        return
    gate = json.loads(value)
    deadline = confirmed_deadline(gate["expires_at"]) - .25
    while time.monotonic() < deadline:
        try:
            with closing(sqlite3.connect(f"file:{gate['database']}?mode=ro", uri=True, timeout=.05)) as database:
                database.row_factory = sqlite3.Row
                row = database.execute("SELECT * FROM tasks WHERE task_id=?", (gate["task_id"],)).fetchone()
            if (row is None or row["lease_token"] != gate["token"]
                    or row["attempt"] != gate["generation"]
                    or row["status"] not in {"RUNNING", "CANCEL_REQUESTED"}):
                raise PermissionError("training execution changed before process binding")
            if row["process_pid"] == os.getpid():
                ProcessController().inspect(ProcessIdentity(row["process_pid"], row["process_create_time"], row["process_command_hash"]))
                # The parent binds PID/create-time/hash together after proving
                # ownership. The child must not enter training on an expired row.
                if confirmed_deadline(row["lease_expires_at"]) <= time.monotonic():
                    raise PermissionError("training execution expired before process binding")
                return
        except sqlite3.OperationalError as error:
            if not is_sqlite_busy(error):
                raise
        time.sleep(.025)
    raise PermissionError("training process binding was not confirmed before deadline")
