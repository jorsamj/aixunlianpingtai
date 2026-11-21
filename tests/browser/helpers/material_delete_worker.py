"""Bounded MaterialBatch worker for the isolated Vue delete browser test."""
import os
import sys
import time
import traceback
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import app  # noqa: E402
from platform_core.material_batches import worker_registration  # noqa: E402
from platform_core.task_runtime.fenced_repository import FencedTaskRepository  # noqa: E402
from platform_core.task_runtime.scheduler import Scheduler  # noqa: E402

registration = worker_registration(os.environ["MC_TRAIN_DATA_DIR"])
repository = app.shared_task_repository()
scheduler = Scheduler(
    FencedTaskRepository(repository.path),
    app.shared_task_artifacts(),
    "browser-material-delete-worker",
    registration["handlers"],
    registration["capabilities"],
)
log_path = os.environ.get("MC_WORKER_LOG")
deadline = time.monotonic() + float(os.environ.get("MC_WORKER_SECONDS", "180"))
while time.monotonic() < deadline:
    try:
        scheduler.run_once()
    except Exception:
        if log_path:
            with open(log_path, "a", encoding="utf-8") as log:
                log.write(f"[{time.strftime('%Y-%m-%dT%H:%M:%S')}] material batch failed\n")
                traceback.print_exc(file=log)
    time.sleep(0.2)
