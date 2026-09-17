import threading
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
    temp_path = job_path.with_suffix(job_path.suffix + ".tmp")
    original_write_text = Path.write_text
    write_started = threading.Event()
    allow_finish = threading.Event()

    def slow_write_text(self, data, *args, **kwargs):
        if self not in {job_path, temp_path}:
            return original_write_text(self, data, *args, **kwargs)
        encoding = kwargs.get("encoding") or "utf-8"
        errors = kwargs.get("errors") or None
        payload = str(data)
        midpoint = max(1, len(payload) // 2)
        with self.open("w", encoding=encoding, errors=errors) as handle:
            handle.write(payload[:midpoint])
            handle.flush()
            write_started.set()
            assert allow_finish.wait(5), "test writer was not released"
            handle.write(payload[midpoint:])
        return len(payload)

    monkeypatch.setattr(Path, "write_text", slow_write_text)

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
    assert write_started.wait(5), "job writer did not enter persistence window"

    observed = app_module.v19_read_job(project_id, job_id)
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
