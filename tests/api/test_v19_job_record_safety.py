import json
import threading
import time
import uuid

import pytest

import app as m


def make_job(client, status="running", phase="ANNOTATION_PARSE"):
    p = client.post("/api/projects", json={"name": "zip-safety-" + uuid.uuid4().hex[:8], "labels": []}).json()["id"]
    j = uuid.uuid4().hex[:16]
    m.v19_write_job(p, {"id": j, "project_id": p, "status": status, "phase": phase,
                        "file_name": "safety.zip", "progress": 72.7, "created_at": m.now_iso(),
                        "report": {"imported_images": 2, "annotated_images": 1, "boxes": 3}})
    (m.v19_job_dir(p, j) / "source.zip").write_bytes(b"owned-temporary-zip")
    return p, j


@pytest.mark.parametrize("status,phase", [("uploading", "UPLOAD"), ("paused", "UPLOAD"),
    ("queued", "QUEUE"), ("selecting", "WAITING_CONFIRMATION"),
    ("running", "ANNOTATION_PARSE"), ("running", "DB_COMMIT")])
def test_active_job_cannot_be_deleted(client, status, phase):
    p, j = make_job(client, status, phase)
    r = client.delete(f"/api/v19/projects/{p}/import/jobs/{j}")
    assert r.status_code == 409
    assert m.v19_read_job(p, j)["status"] == status
    assert (m.v19_job_dir(p, j) / "source.zip").is_file()


def test_clear_terminal_keeps_evidence_and_reports_each_result(client):
    p, done = make_job(client, "done", "DONE")
    for j, s in [("failed-job", "failed"), ("active-job", "running"), ("review-job", "selecting")]:
        m.v19_write_job(p, {"id": j, "status": s, "phase": "ANNOTATION_PARSE", "file_name": j})
    r = client.delete(f"/api/v19/projects/{p}/import/jobs")
    assert r.status_code == 200
    body = r.json()
    assert set(body["deleted_ids"]) == {done, "failed-job"}
    assert {x["id"] for x in body["kept"]} == {"active-job", "review-job"}
    assert all(x["reason"] for x in body["kept"])
    evidence = client.get(f"/api/v19/projects/{p}/import/jobs/{done}").json()
    assert evidence["status"] == "done"
    assert evidence["history_hidden"] is True
    assert evidence["report"]["boxes"] == 3
    assert not (m.v19_job_dir(p, done) / "source.zip").exists()
    assert done not in {x["id"] for x in client.get(f"/api/v19/projects/{p}/import/jobs").json()["items"]}
    repeated = client.delete(f"/api/v19/projects/{p}/import/jobs", params={"job_ids": done}).json()
    assert done in repeated["deleted_ids"]


def test_delete_and_start_share_existing_stop_fence(client):
    p, j = make_job(client, "failed", "FAILED")
    result = []
    with m._v19_stop_fence(p, j):
        thread = threading.Thread(target=lambda: result.append(client.delete(f"/api/v19/projects/{p}/import/jobs/{j}")))
        thread.start()
        time.sleep(.08)
        assert not result, "delete must wait for the existing stop/commit fence"
        # Simulate validated retry owning the very same fence before deletion.
        job = m.v19_read_job(p, j)
        job.update(status="running", phase="QUEUE")
        m.v19_write_job(p, job, allow_restart=True)
    thread.join(5)
    assert not thread.is_alive()
    assert result[0].status_code == 409
    assert m.v19_job_file(p, j).exists()


def test_missing_state_update_is_not_silently_successful(client):
    p, j = make_job(client)
    m.v19_job_file(p, j).unlink()
    with pytest.raises(Exception):
        m.v19_update_job(p, j, progress=85)


def test_late_progress_cannot_overwrite_terminal(client):
    p, j = make_job(client, "done", "DONE")
    with pytest.raises(Exception):
        m.v19_update_job(p, j, status="running", phase="ANNOTATION_PARSE", progress=88)
    assert m.v19_read_job(p, j)["status"] == "done"


def test_stale_direct_writer_cannot_resurrect_cancelled_record(client):
    p, j = make_job(client, "uploading", "UPLOAD")
    stale = m.v19_read_job(p, j)
    job = dict(stale, status="cancelled", phase="CANCELLED")
    m.v19_write_job(p, job)
    with pytest.raises(Exception):
        m.v19_write_job(p, stale)
    assert m.v19_read_job(p, j)["status"] == "cancelled"


def test_cleanup_failure_is_reported_and_history_not_hidden(client, monkeypatch):
    p, j = make_job(client, "done", "DONE")
    def fail(*args, **kwargs):
        raise OSError("isolated cleanup denial")
    monkeypatch.setattr(m, "_v19_cleanup_uncommitted_job", fail)
    result = client.delete(f"/api/v19/projects/{p}/import/jobs").json()
    assert j not in result["deleted_ids"]
    assert result["kept"][0]["id"] == j
    assert not m.v19_read_job(p, j).get("history_hidden")


def run_real_image_import(client, monkeypatch, *, lose_record=False, fail_final_write=False):
    import io
    import zipfile
    from PIL import Image
    p, _ = make_job(client, "done", "DONE")
    png = io.BytesIO()
    Image.new("RGB", (24, 24), "white").save(png, "PNG")
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("images/sample.png", png.getvalue())
    response = client.post(f"/api/v19/projects/{p}/datasets/default/import/jobs",
                           files={"file": ("real.zip", archive.getvalue(), "application/zip")})
    response.raise_for_status()
    j = response.json()["id"]
    if lose_record:
        original = m._v18_import_yolo
        def after_parse(*args, **kwargs):
            result = original(*args, **kwargs)
            m.v19_job_file(p, j).unlink()
            return result
        monkeypatch.setattr(m, "_v18_import_yolo", after_parse)
    if fail_final_write:
        original_write = m.v19_write_job
        def write(project, job, **kwargs):
            if job["id"] == j and job.get("status") == "done":
                raise OSError("isolated final status write failure")
            return original_write(project, job, **kwargs)
        monkeypatch.setattr(m, "v19_write_job", write)
    m.v19_import_worker(p, "default", j, [])
    return p, j


def test_missing_record_after_parse_rolls_back_uncommitted_inputs(client, monkeypatch):
    p, j = run_real_image_import(client, monkeypatch, lose_record=True)
    assert not m.v19_job_file(p, j).exists()
    assert m.material_store(p).read().rows == []
    assert m._v50_active_image_batch(p) is None
    assert (m.v19_import_jobs_dir(p) / ".diagnostics" / f"{j}.json").is_file()


def test_final_status_write_failure_does_not_delete_committed_material(client, monkeypatch):
    p, j = run_real_image_import(client, monkeypatch, fail_final_write=True)
    rows = m.material_store(p).read().rows
    assert len(rows) == 1
    assert m.v19_read_job(p, j)["status"] != "done"
    assert m.v19_read_job(p, j)["formal_commit_completed"] is True
    assert m.AnnotationRepository(m.project_dir(p)).exists(rows[0]["id"])
    evidence = json.loads((m.v19_import_jobs_dir(p) / ".diagnostics" / f"{j}.json").read_text(encoding="utf-8"))
    assert evidence["formal_commit_completed"] is True


def test_success_keeps_counts_and_releases_owned_temporary_files(client, monkeypatch):
    p, j = run_real_image_import(client, monkeypatch)
    job = m.v19_read_job(p, j)
    assert job["status"] == "done"
    assert job["progress"] == 100
    assert job["report"]["imported_images"] == 1
    assert len(m.material_store(p).read().rows) == 1
    # Explicit history cleanup only touches the task's own temporary files.
    client.delete(f"/api/v19/projects/{p}/import/jobs/{j}").raise_for_status()
    assert m.v19_read_job(p, j)["report"]["imported_images"] == 1
    assert len(m.material_store(p).read().rows) == 1


def test_worker_missing_initial_record_leaves_diagnostic_without_recreating_success(client):
    p, j = make_job(client)
    m.v19_job_file(p, j).unlink()
    m.v19_import_worker(p, "default", j, [])
    assert not m.v19_job_file(p, j).exists()
    diagnostic = json.loads((m.v19_import_jobs_dir(p) / ".diagnostics" / f"{j}.json").read_text(encoding="utf-8"))
    assert diagnostic["job_id"] == j
    assert diagnostic["project_id"] == p
    assert diagnostic["outcome"] == "unknown"
    assert diagnostic["code"] == "ZIP_JOB_RECORD_UNAVAILABLE"


def test_normal_status_query_never_scans_material_or_other_job_files(client, monkeypatch):
    p, j = make_job(client)
    def forbidden(*args, **kwargs):
        raise AssertionError("status polling must directly locate project+job")
    monkeypatch.setattr(m, "material_store", forbidden)
    monkeypatch.setattr(m, "_v19_fifo_queue_position", forbidden)
    monkeypatch.setattr(m, "v19_read_import_report", forbidden)
    r = client.get(f"/api/v19/projects/{p}/import/jobs/{j}")
    assert r.status_code == 200
    assert r.json()["progress"] == 72.7


def test_state_write_failure_is_visible_to_polling_and_later_write_recovers(client, monkeypatch):
    p, j = make_job(client)
    original = m.atomic_write_json
    def fail_job(path, value, *args, **kwargs):
        if path == m.v19_job_file(p, j):
            raise OSError("isolated job state disk error")
        return original(path, value, *args, **kwargs)
    monkeypatch.setattr(m, "atomic_write_json", fail_job)
    with pytest.raises(OSError):
        m.v19_update_job(p, j, progress=88)
    observed = client.get(f"/api/v19/projects/{p}/import/jobs/{j}").json()
    assert observed["status"] == "unknown"
    assert observed["progress"] == 72.7
    assert observed["last_known_status"] == "running"
    monkeypatch.setattr(m, "atomic_write_json", original)
    m.v19_update_job(p, j, progress=89)
    assert client.get(f"/api/v19/projects/{p}/import/jobs/{j}").json()["status"] == "running"


def test_persistent_state_failure_does_not_block_next_independent_zip(client, monkeypatch):
    p, j = make_job(client, "running", "QUEUE")
    original = m.atomic_write_json
    def fail_job(path, value, *args, **kwargs):
        if path == m.v19_job_file(p, j):
            raise OSError("isolated persistent state write failure")
        return original(path, value, *args, **kwargs)
    monkeypatch.setattr(m, "atomic_write_json", fail_job)
    m.v19_import_worker(p, "default", j, [])
    assert m.v19_read_job(p, j)["status"] == "running"  # original evidence remains
    assert client.get(f"/api/v19/projects/{p}/import/jobs/{j}").json()["status"] == "unknown"
    m.v19_write_job(p, {"id": "second-zip", "status": "running", "phase": "QUEUE", "enqueue_sequence": 2})
    assert [row["id"] for row in m._v19_fifo_import_jobs(p)] == ["second-zip"]
    m._v19_wait_fifo_turn(p, "second-zip")


def test_secondary_cleanup_failure_cannot_hide_decisive_worker_exit(client, monkeypatch):
    p, j = make_job(client, "running", "QUEUE")
    (m.v19_job_dir(p, j) / "extracted").mkdir()
    original = m.atomic_write_json
    def fail_job(path, value, *args, **kwargs):
        if path == m.v19_job_file(p, j):
            raise OSError("isolated persistent job write error")
        return original(path, value, *args, **kwargs)
    original_cleanup = m.shutil.rmtree
    def fail_cleanup(path, *args, **kwargs):
        if path == m.v19_job_dir(p, j) / "extracted":
            raise OSError("isolated secondary cleanup failure")
        return original_cleanup(path, *args, **kwargs)
    monkeypatch.setattr(m, "atomic_write_json", fail_job)
    monkeypatch.setattr(m.shutil, "rmtree", fail_cleanup)
    m.v19_import_worker(p, "default", j, [])
    assert client.get(f"/api/v19/projects/{p}/import/jobs/{j}").json()["status"] == "unknown"
    assert m._v19_fifo_import_jobs(p) == []
    evidence = json.loads((m.v19_import_jobs_dir(p) / ".diagnostics" / f"{j}.json").read_text(encoding="utf-8"))
    assert evidence["operation"] == "worker_failure"
    assert evidence["secondary_error"]["operation"] == "extracted_cleanup"


def test_cleared_history_is_not_read_by_active_polling(client, monkeypatch):
    from pathlib import Path
    p, first = make_job(client, "done", "DONE")
    for n in range(120):
        m.v19_write_job(p, {"id": f"history-{n}", "status": "done", "report": {"imported_images": n}})
    cleared = client.delete(f"/api/v19/projects/{p}/import/jobs").json()
    assert cleared["deleted"] == 121
    archived = m.v19_import_jobs_dir(p) / ".history"
    assert len(list(archived.glob("*/job.json"))) == 121
    assert m.v19_read_job(p, first)["report"]["boxes"] == 3
    assert m._v19_stop_fence(p, first).lock_file == str(m.v19_job_dir(p, first) / ".stop.lock")
    original = Path.read_text
    def read(path, *args, **kwargs):
        assert archived not in path.parents, "active discovery must not parse archived history"
        return original(path, *args, **kwargs)
    monkeypatch.setattr(Path, "read_text", read)
    assert client.get(f"/api/v19/projects/{p}/import/jobs").json()["items"] == []
    assert m._v19_fifo_import_jobs(p) == []
