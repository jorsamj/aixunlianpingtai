import threading
import json
import errno
from pathlib import Path

import pytest


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


@pytest.mark.parametrize("fault", ["transient_permission", "transient_errno_access", "persistent_permission", "invalid_json", "wrong_identity"])
def test_job_read_failure_never_becomes_successful_empty_progress(client, monkeypatch, fault):
    import app as api
    project_id = _project(client)
    job_id = "read-failure-contract"
    api.v19_write_job(project_id, {"id": job_id, "project_id": project_id, "status": "running", "progress": 77.63})
    path = api.v19_job_file(project_id, job_id)
    original = Path.read_text
    reads = 0
    def fail_read(self, *args, **kwargs):
        nonlocal reads
        if self == path:
            reads += 1
            if fault == "invalid_json":
                return "{"
            if fault == "wrong_identity":
                return json.dumps({"id": "other-task", "status": "running", "progress": 90})
            if fault == "transient_errno_access" and reads == 1:
                raise PermissionError(errno.EACCES, "isolated CRT sharing conflict")
            if fault == "persistent_permission" or (fault == "transient_permission" and reads == 1):
                error = PermissionError("isolated sharing conflict")
                error.winerror = 32
                raise error
        return original(self, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", fail_read)
    response = client.get(f"/api/v19/projects/{project_id}/import/jobs/{job_id}")
    if fault in {"transient_permission", "transient_errno_access"}:
        assert response.status_code == 200
        assert response.json()["id"] == job_id
        assert response.json()["progress"] == 77.63
    else:
        assert response.status_code == 503
        assert "progress" not in response.json()
        if fault == "persistent_permission":
            assert reads == 4
