"""Bounded CPU-only worker loop for the isolated real-bulk browser test.

Runs the real FencedTaskRepository/Scheduler with the production
FormalBulkAnnotationHandler. It stops after MC_WORKER_SECONDS and never talks to
production task tables.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import app  # noqa: E402
from platform_core.annotation_bulk_execution import FormalBulkAnnotationHandler  # noqa: E402
from platform_core.task_runtime import TaskKind  # noqa: E402
from platform_core.task_runtime.fenced_repository import FencedTaskRepository  # noqa: E402
from platform_core.task_runtime.scheduler import Scheduler  # noqa: E402

seconds = float(os.environ.get("MC_WORKER_SECONDS", "180"))
repository = app.shared_task_repository()
fenced = FencedTaskRepository(repository.path)
scheduler = Scheduler(
    fenced,
    app.shared_task_artifacts(),
    "browser-bulk-worker",
    {TaskKind.ANNOTATION_FORMAL_BULK: FormalBulkAnnotationHandler()},
    {"annotation.formal_bulk"},
)
deadline = time.monotonic() + seconds
while time.monotonic() < deadline:
    try:
        scheduler.run_once()
    except Exception:
        pass
    time.sleep(0.2)
