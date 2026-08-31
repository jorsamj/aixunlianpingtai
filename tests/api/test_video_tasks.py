from pathlib import Path

import cv2
import numpy as np

import app as app_module
from platform_core.task_runtime import TaskKind, TaskStatus


def make_video_bytes(tmp_path):
    path = tmp_path / "upload.avi"
    writer = cv2.VideoWriter(
        str(path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        6.0,
        (64, 48),
    )
    assert writer.isOpened()
    for index in range(12):
        writer.write(np.full((48, 64, 3), index * 15, dtype=np.uint8))
    writer.release()
    return path.read_bytes()


def test_create_video_task_only_persists_upload_and_enqueues(
    client,
    seeded_project,
    tmp_path,
    monkeypatch,
):
    project_id, _ = seeded_project

    class ForbiddenThread:
        def __init__(self, *args, **kwargs):
            raise AssertionError("HTTP route must not start a video thread")

    monkeypatch.setattr(app_module.threading, "Thread", ForbiddenThread)
    response = client.post(
        f"/api/v33/projects/{project_id}/video-tasks",
        files={"video": ("upload.avi", make_video_bytes(tmp_path), "video/x-msvideo")},
        data={
            "mode": "fixed_count",
            "fixed_count": "3",
            "dataset_id": "default",
            "split": "unassigned",
            "backend": "opencv",
            "priority": "7",
        },
    )
    assert response.status_code == 202
    task = response.json()
    assert task["kind"] == TaskKind.VIDEO_FRAMES.value
    assert task["status"] == TaskStatus.QUEUED.value
    assert task["priority"] == 7
    assert task["video_name"] == "upload.avi"
    assert task["mode"] == "fixed_count"
    assert task["fixed_count"] == 3
    assert "video_path" not in task
    assert "source_ref" not in task

    persisted = app_module.shared_task_repository().get(task["id"])
    assert persisted is not None
    payload = app_module.shared_task_artifacts().read_json(task["id"], persisted.payload_ref)
    assert payload["mode"] == "fixed_count"
    assert payload["fixed_count"] == 3
    assert not Path(payload["source_ref"]).is_absolute()
    assert app_module.shared_task_artifacts().artifact_path(task["id"], payload["source_ref"]).stat().st_size > 0


def test_video_task_list_and_cancel_use_persistent_repository(client, seeded_project, tmp_path):
    project_id, _ = seeded_project
    created = client.post(
        f"/api/v33/projects/{project_id}/video-tasks",
        files={"video": ("upload.avi", make_video_bytes(tmp_path), "video/x-msvideo")},
        data={"mode": "fixed_count", "fixed_count": "2", "backend": "opencv"},
    )
    assert created.status_code == 202
    task_id = created.json()["id"]

    listing = client.get(f"/api/v33/projects/{project_id}/video-tasks")
    assert listing.status_code == 200
    assert task_id in {item["id"] for item in listing.json()["items"]}
    cancelled = client.post(f"/api/v33/projects/{project_id}/video-tasks/{task_id}/stop")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == TaskStatus.CANCELLED.value
    assert app_module.shared_task_repository().get(task_id).status is TaskStatus.CANCELLED
