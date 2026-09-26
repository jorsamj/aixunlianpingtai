import io
import threading
import time
import zipfile

import app as app_module


def _small_zip():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_STORED) as archive:
        archive.writestr("images/train/a.jpg", b"scan-only-image")
        archive.writestr("data.yaml", "train: images/train\nnames: [object]\n")
    return payload.getvalue()


def _upload_parts(client, project_id, payload):
    created = client.post(
        f"/api/v19/projects/{project_id}/datasets/default/import/uploads",
        json={
            "file_name": "background.zip",
            "file_size": len(payload),
            "fingerprint": "background-finalize",
            "part_size": 4 * 1024 * 1024,
        },
    )
    assert created.status_code == 200, created.text
    session = created.json()
    assert session["total_parts"] == 1
    uploaded = client.put(
        f"/api/v19/projects/{project_id}/import/uploads/{session['upload_id']}/parts/0",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 200, uploaded.text
    return session


def _wait_status(client, project_id, job_id, expected, timeout=5.0):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        response = client.get(f"/api/v19/projects/{project_id}/import/jobs/{job_id}")
        assert response.status_code == 200, response.text
        last = response.json()
        if last.get("status") in expected:
            return last
        time.sleep(0.03)
    raise AssertionError(f"ZIP job did not reach {expected}: {last}")


def test_multipart_complete_returns_before_background_scan_finishes(client, monkeypatch):
    project = client.post("/api/projects", json={"name": "zip-background", "labels": []}).json()
    payload = _small_zip()
    session = _upload_parts(client, project["id"], payload)

    scan_started = threading.Event()
    release_scan = threading.Event()
    original_scan = app_module.v19_scan_zip

    def blocked_scan(path):
        scan_started.set()
        assert release_scan.wait(5.0)
        return original_scan(path)

    monkeypatch.setattr(app_module, "v19_scan_zip", blocked_scan)
    try:
        started = time.monotonic()
        completed = client.post(
            f"/api/v19/projects/{project['id']}/import/uploads/{session['upload_id']}/complete"
        )
        elapsed = time.monotonic() - started
        assert completed.status_code == 202, completed.text
        assert completed.json()["status"] in {"merging", "validating"}
        assert elapsed < 1.0
        assert scan_started.wait(2.0)

        active = client.get(
            f"/api/v19/projects/{project['id']}/import/jobs/{session['upload_id']}"
        ).json()
        assert active["status"] in {"merging", "validating"}
        assert "后台" in str(active.get("message") or "")
    finally:
        release_scan.set()

    final = _wait_status(
        client, project["id"], session["upload_id"], {"selecting", "failed"}
    )
    assert final["status"] == "selecting", final
    assert final["image_count"] == 1
    assert final["scan_images_ref"] == "scan-images.json"


def test_job_read_recovers_interrupted_multipart_finalize(client, monkeypatch):
    project = client.post("/api/projects", json={"name": "zip-recover", "labels": []}).json()
    payload = _small_zip()
    session = _upload_parts(client, project["id"], payload)
    app_module.v19_update_job(
        project["id"], session["upload_id"],
        status="merging", stage="正在合并 ZIP 分片",
        upload_progress=100, message="模拟服务重启后的恢复任务",
    )

    scan_started = threading.Event()
    release_scan = threading.Event()
    original_scan = app_module.v19_scan_zip

    def blocked_scan(path):
        scan_started.set()
        assert release_scan.wait(5.0)
        return original_scan(path)

    monkeypatch.setattr(app_module, "v19_scan_zip", blocked_scan)
    try:
        recovered = client.get(
            f"/api/v19/projects/{project['id']}/import/jobs/{session['upload_id']}"
        )
        assert recovered.status_code == 200, recovered.text
        assert scan_started.wait(2.0)
    finally:
        release_scan.set()

    final = _wait_status(
        client, project["id"], session["upload_id"], {"selecting", "failed"}
    )
    assert final["status"] == "selecting", final
