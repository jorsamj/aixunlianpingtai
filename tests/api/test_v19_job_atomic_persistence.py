import threading
import json
from pathlib import Path


def _project(client) -> str:
    response = client.post(
        "/api/projects",
        json={"name": "v19-atomic-job", "description": "", "labels": []},
    )
    response.raise_for_status()
    return response.json()["id"]


def test_v19_progress_reader_never_observes_partial_job_json(client, monkeypatch):
    import app as app_module

    project_id = _project(client)
    job_id = "atomic-progress"
    app_module.v19_write_job(
        project_id,
        {
            "id": job_id,
            "project_id": project_id,
            "dataset_id": "default",
            "status": "running",
            "stage": "正在解压数据集",
            "progress": 12.3,
            "processed": 3600,
            "image_count": 10_000,
            "created_at": app_module.now_iso(),
        },
    )

    job_path = app_module.v19_job_file(project_id, job_id)
    original_dump = json.dump
    write_started = threading.Event()
    allow_finish = threading.Event()

    def slow_dump(data, handle, *args, **kwargs):
        staging = Path(handle.name)
        if staging.parent != job_path.parent or not staging.name.startswith(f".{job_path.name}."):
            return original_dump(data, handle, *args, **kwargs)
        payload = json.dumps(data, *args, **kwargs)
        midpoint = max(1, len(payload) // 2)
        handle.write(payload[:midpoint])
        handle.flush()
        write_started.set()
        assert allow_finish.wait(5), "test writer was not released"
        handle.write(payload[midpoint:])

    monkeypatch.setattr(json, "dump", slow_dump)

    writer = threading.Thread(
        target=app_module.v19_update_job,
        args=(project_id, job_id),
        kwargs={
            "status": "running",
            "stage": "正在解压数据集",
            "progress": 13.4,
            "processed": 4500,
        },
        daemon=True,
    )
    writer.start()
    try:
        assert write_started.wait(5), "job writer did not enter persistence window"
        observed = app_module.v19_read_job(project_id, job_id)
    finally:
        allow_finish.set()
        writer.join(timeout=5)
    assert not writer.is_alive()

    assert observed["status"] == "running"
    assert observed["stage"] == "正在解压数据集"
    assert observed["progress"] == 12.3
    assert observed["processed"] == 3600

    final = app_module.v19_read_job(project_id, job_id)
    assert final["status"] == "running"
    assert final["progress"] == 13.4
    assert final["processed"] == 4500
