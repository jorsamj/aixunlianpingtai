"""N5: app.py job.json writers share the numeric-publisher lock contract.

The numeric evidence publisher and the conversion worker persist through
``<job.json>.lock`` + whole-file ``os.replace``. Every app.py job writer now
uses the same identity, so concurrent progress writes can neither tear the
record nor silently drop a delivered quality projection.
"""
from platform_core.conversion_management_service import ConversionManagementService
import platform_core.conversion_management_service as conversion_management_owner
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import app as api


_PROJECTION = {
    "verification_id": "nv_" + "1" * 32,
    "status": "completed",
    "verdict": "consistent",
    "content_digest": "d" * 64,
    "evidence_ref": "numeric-validations/nv_x/evidence/nv_x.json",
}


def _seed_job(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "id": "convert-1", "status": "running", "progress": 10,
        "numeric_status": "consistent",
        "publication_status": "numeric_consistent_delivery_evidence_incomplete",
        "numeric_validation": _PROJECTION,
        "numeric_validation_binding_status": "verified",
    }), encoding="utf-8")


def _record_lock_paths(monkeypatch):
    """Record the exact lock identity used by the app job writer."""
    acquired = []
    real_lock = api.FileLock

    class _RecordingLock:
        def __init__(self, path, *args, **kwargs):
            acquired.append(str(path))
            self._lock = real_lock(path, *args, **kwargs)

        def __enter__(self):
            return self._lock.__enter__()

        def __exit__(self, *exc_info):
            return self._lock.__exit__(*exc_info)

    monkeypatch.setattr(api, "FileLock", _RecordingLock)
    monkeypatch.setattr(conversion_management_owner, 'FileLock', api.FileLock)
    return acquired


def test_app_job_writer_uses_shared_lock_atomic_replace_and_keeps_projection(tmp_path, monkeypatch):
    job_file = tmp_path / "jobs" / "convert-1" / "job.json"
    _seed_job(job_file)
    acquired = _record_lock_paths(monkeypatch)
    # A stale read-modify-write snapshot predates the numeric projection.
    stale = {"id": "convert-1", "status": "running", "progress": 55, "stage": "导出 ONNX"}

    written = api._write_job_json(job_file, stale)
    on_disk = json.loads(job_file.read_text(encoding="utf-8"))
    assert on_disk["progress"] == 55 and on_disk["stage"] == "导出 ONNX"
    assert on_disk["numeric_status"] == "consistent"
    assert on_disk["publication_status"] == "numeric_consistent_delivery_evidence_incomplete"
    assert on_disk["numeric_validation"] == _PROJECTION
    assert on_disk["numeric_validation_binding_status"] == "verified"
    assert written["numeric_validation"] == _PROJECTION
    # The numeric publisher / conversion worker lock identity, not a private one.
    assert acquired == [str(job_file) + ".lock"]
    assert not list(job_file.parent.glob(".job.json.*.tmp"))

    # A payload explicitly resetting a projection field to None must not erase it.
    api._write_job_json(job_file, {"id": "convert-1", "numeric_status": None, "progress": 90})
    on_disk = json.loads(job_file.read_text(encoding="utf-8"))
    assert on_disk["numeric_status"] == "consistent"
    assert on_disk["progress"] == 90
    assert on_disk["numeric_validation"] == _PROJECTION
    assert acquired == [str(job_file) + ".lock"] * 2


def test_concurrent_app_job_writes_never_tear_or_drop_the_projection(tmp_path, monkeypatch):
    job_file = tmp_path / "jobs" / "convert-1" / "job.json"
    _seed_job(job_file)
    acquired = _record_lock_paths(monkeypatch)
    errors = []
    stop = threading.Event()

    def writer(index: int) -> None:
        try:
            api._write_job_json(
                job_file,
                {"id": "convert-1", "progress": index, "writer": f"w{index}"},
            )
        except Exception as error:  # noqa: BLE001 - collected for assertion
            errors.append(error)

    def reader() -> None:
        while not stop.is_set():
            try:
                raw = job_file.read_text(encoding="utf-8")
            except PermissionError:
                # Windows may transiently deny a read while the atomic replace is
                # in flight; app readers use read_json(), which degrades the same
                # way. This is not a torn record.
                continue
            except FileNotFoundError:
                continue
            try:
                value = json.loads(raw)
            except json.JSONDecodeError as error:
                errors.append(error)  # a partially written file is a real failure
                return
            if value.get("numeric_validation") != _PROJECTION:
                errors.append(AssertionError("numeric projection was dropped"))
                return

    reader_thread = threading.Thread(target=reader)
    reader_thread.start()
    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(writer, range(40)))
    finally:
        stop.set()
        reader_thread.join(timeout=10)

    assert not errors
    final = json.loads(job_file.read_text(encoding="utf-8"))
    assert final["id"] == "convert-1"
    assert final["numeric_validation"] == _PROJECTION
    assert final["numeric_status"] == "consistent"
    assert not list(job_file.parent.glob(".job.json.*.tmp"))
    assert set(acquired) == {str(job_file) + ".lock"}
    assert len(acquired) == 40


def test_write_deploy_job_uses_the_same_job_json_lock(tmp_path, monkeypatch):
    root = tmp_path / "project"
    monkeypatch.setattr(
        ConversionManagementService, "_deploy_job_dir",
        staticmethod(lambda project_id, job_id: root / "deployment" / "jobs" / job_id),
    )
    job_dir = root / "deployment" / "jobs" / "job-1"
    job_file = job_dir / "job.json"
    _seed_job(job_file)
    acquired = _record_lock_paths(monkeypatch)

    api._write_deploy_job("p1", {
        "id": "job-1", "status": "done", "progress": 100,
        "hardware_verified": False,
    })
    on_disk = json.loads(job_file.read_text(encoding="utf-8"))
    assert on_disk["status"] == "done" and on_disk["progress"] == 100
    assert on_disk["numeric_validation"] == _PROJECTION
    assert acquired == [str(job_file) + ".lock"]
    assert not list(job_dir.glob(".job.json.*.tmp"))
