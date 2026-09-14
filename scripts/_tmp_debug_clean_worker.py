import io
import uuid

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import app as app_module
from platform_core.task_runtime import ArtifactStore, FencedTaskRepository, Scheduler
from platform_core.worker_registry import build_worker_registration


def image_bytes():
    image = Image.new("RGB", (400, 300), "gray")
    draw = ImageDraw.Draw(image)
    for x in range(0, 400, 20):
        for y in range(0, 300, 20):
            fill = "white" if (x // 20 + y // 20) % 2 == 0 else "black"
            draw.rectangle((x, y, x + 19, y + 19), fill=fill)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


with TestClient(app_module.app) as client:
    project = client.post("/api/projects", json={"name": "clean-worker-diagnostic", "labels": []}).json()
    pid = project["id"]
    upload = client.post(
        f"/api/projects/{pid}/images",
        files=[("files", ("diagnostic.png", image_bytes(), "image/png"))],
        data={"dataset_id": "default"},
    )
    upload.raise_for_status()
    image_id = upload.json()["uploaded"][0]["id"]
    task_response = client.post(
        f"/api/v47/projects/{pid}/clean-tasks",
        json={"image_ids": [image_id], "task_name": "diagnostic clean"},
    )
    task_response.raise_for_status()
    task_id = task_response.json()["id"]

    runtime = app_module.DATA_DIR / "task_runtime"
    repository = FencedTaskRepository(runtime / "tasks.sqlite3")
    artifacts = ArtifactStore(runtime / "artifacts")
    handlers, capabilities = build_worker_registration(app_module.DATA_DIR, {"materials"})
    scheduler = Scheduler(
        repository,
        artifacts,
        f"diagnostic-{uuid.uuid4().hex[:8]}",
        handlers,
        capabilities,
        lease_seconds=5,
        poll_seconds=0.01,
    )
    assert scheduler.run_once() is True
    task = app_module.shared_task_repository().get(task_id)
    print("DIAGNOSTIC_TASK_STATUS=", task.status.value if task else None)
    print("DIAGNOSTIC_TASK_STAGE=", task.stage if task else None)
    print("DIAGNOSTIC_TASK_ERROR=", task.error if task else None)
    log_path = artifacts.artifact_path(task_id, task.log_ref if task else "task.log")
    print("DIAGNOSTIC_LOG_EXISTS=", log_path.exists())
    if log_path.exists():
        print("DIAGNOSTIC_LOG_BEGIN")
        print(log_path.read_text(encoding="utf-8", errors="replace"))
        print("DIAGNOSTIC_LOG_END")
    if task is None or task.status.value == "FAILED":
        raise SystemExit(1)
