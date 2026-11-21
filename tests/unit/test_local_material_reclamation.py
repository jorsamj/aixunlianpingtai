from dataclasses import replace
from PIL import Image
from pathlib import Path
import hashlib
import os
import sys
from types import SimpleNamespace

import pytest

from platform_core.material_repository import MaterialRepository
from platform_core.storage.local import LocalStorageProvider
from platform_core.storage.source_repository import StorageSourceRepository
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus
from platform_core.local_material_reclamation import LocalMaterialReclamationService


def setup_gc(tmp_path, monkeypatch):
    monkeypatch.setenv("MC_CONTROLLED_LOCAL_MATERIAL_GC", "1")
    # The isolated data fixture declares a known offline process inventory.
    # Hosted Linux runners can contain unrelated/uninspectable Python processes;
    # production must refuse those, not make this unit fixture host-dependent.
    import platform_core.local_material_reclamation as module
    process = SimpleNamespace(info={"pid": os.getpid(), "name": Path(sys.executable).name,
        "exe": sys.executable, "cmdline": [sys.executable, "isolated-gc-unit-test"],
        "cwd": str(tmp_path)})
    monkeypatch.setattr(module.psutil, "process_iter", lambda *a, **kw: [process])
    data = tmp_path / "data"
    project = data / "projects/p"
    (project / "uploads").mkdir(parents=True)
    original = project / "uploads/a.png"
    Image.new("RGB", (8, 6), "red").save(original)
    materials = MaterialRepository(project)
    row = {"id": "a", "filename": "a.png", "content_sha256": hashlib.sha256(original.read_bytes()).hexdigest(), "size_bytes": original.stat().st_size}
    materials.upsert(row)
    materials.retire_many(["a"], task_id="retire", actor_id="test")
    tasks = TaskRepository(data / "task_runtime/tasks.sqlite3")
    tasks.create(replace(TaskRecord.new("retire", "p", TaskKind.MATERIAL_BATCH, "payload.json", "material"), status=TaskStatus.SUCCEEDED))
    artifacts = ArtifactStore(data / "task_runtime/artifacts")
    StorageSourceRepository(data / "storage/storage_sources.sqlite3")
    return LocalMaterialReclamationService(data, tasks, artifacts, controlled_local_writers=True), materials, original, tasks


def apply(service, truth, **kwargs):
    return service.apply("p", "retire", "a", expected_fingerprint=truth["fingerprint"], operation_id="gc-a", confirmed=True, actor="test-user", **kwargs)


def test_explicit_local_reclamation_is_scoped_audited_and_idempotent(tmp_path, monkeypatch):
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    truth = service.preview("p", "retire", "a")
    assert truth["eligible"], truth
    assert original.exists()
    size = original.stat().st_size
    receipt = apply(service, truth)
    assert receipt["status"] == "deleted" and receipt["deleted_logical_bytes"] == size
    assert not original.exists()
    assert materials.retirement("retire", "a")["reclaimed_bytes"] == 0
    assert apply(service, truth)["status"] == "already_deleted"
    with pytest.raises(ValueError):
        materials.upsert({"id": "new", "filename": "a.png"})


def test_active_task_and_open_source_reader_protect_retired_original(tmp_path, monkeypatch):
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    task = TaskRecord.new("active", "p", TaskKind.TRAINING, "payload.json", "training")
    tasks.create(task)
    assert "ACTIVE_TASK" in service.preview("p", "retire", "a")["blockers"]
    with tasks._connect() as db:
        db.execute("UPDATE tasks SET status='CANCELLED' WHERE task_id='active'")
    truth = service.preview("p", "retire", "a")
    provider = LocalStorageProvider("default_local", original.parent.parent)
    with provider.open_reader("uploads/a.png") as reader:
        with pytest.raises(RuntimeError, match="BUSY"):
            apply(service, truth)
        assert reader.read() == original.read_bytes()
    assert apply(service, truth)["status"] == "deleted"


def test_missing_mode_live_alias_unknown_project_and_changed_bytes_fail_closed(tmp_path, monkeypatch):
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    service.controlled_local_writers = False
    assert "CONTROLLED_MODE_REQUIRED" in service.preview("p", "retire", "a")["blockers"]
    service.controlled_local_writers = True
    materials.upsert({"id": "live", "filename": "a.png"})
    assert "LIVE_REFERENCE" in service.preview("p", "retire", "a")["blockers"]
    materials.remove(["live"])
    (service.data_dir / "projects/unknown").mkdir()
    assert "UNKNOWN_PROJECT_INDEX" in service.preview("p", "retire", "a")["blockers"]
    (service.data_dir / "projects/unknown").rmdir()
    with tasks._connect() as db:
        db.execute("UPDATE tasks SET process_create_time=1 WHERE task_id='retire'")
    assert "PROCESS_INSPECTION_UNKNOWN" in service.preview("p", "retire", "a")["blockers"]
    with tasks._connect() as db:
        db.execute("UPDATE tasks SET process_create_time=NULL WHERE task_id='retire'")
    service.artifacts.atomic_write_json("retire", "failure.json", [])
    assert "UNKNOWN_RECOVERY_EVIDENCE" in service.preview("p", "retire", "a")["blockers"]
    service.artifacts.artifact_path("retire", "failure.json").unlink()
    truth = service.preview("p", "retire", "a")
    original.write_bytes(b"changed")
    with pytest.raises(RuntimeError):
        apply(service, truth)
    assert original.read_bytes() == b"changed"


def test_quarantined_interruption_recovers_from_original_receipt(tmp_path, monkeypatch):
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    truth = service.preview("p", "retire", "a")
    unlink = service._unlink_quarantined
    monkeypatch.setattr(service, "_unlink_quarantined", lambda path: (_ for _ in ()).throw(OSError("busy")))
    with pytest.raises(OSError):
        apply(service, truth)
    assert not original.exists()
    monkeypatch.setattr(service, "_unlink_quarantined", unlink)
    assert apply(service, truth)["status"] == "deleted"


def test_retired_model_or_unknown_binary_is_not_an_original_image(tmp_path, monkeypatch):
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    weights = original.with_name("weights.pt")
    weights.write_bytes(b"checkpoint")
    materials.upsert({"id": "weights", "filename": "weights.pt", "size_bytes": len(b"checkpoint"),
                      "content_sha256": hashlib.sha256(b"checkpoint").hexdigest()})
    materials.retire_many(["weights"], task_id="retire", actor_id="test")
    truth = service.preview("p", "retire", "weights")
    assert not truth["eligible"]
    assert "UNSUPPORTED_CONTENT_TYPE" in truth["blockers"]
    assert weights.read_bytes() == b"checkpoint"


def test_preview_never_initializes_or_changes_any_data_file(tmp_path, monkeypatch):
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    before = {str(path.relative_to(service.data_dir)): path.read_bytes() for path in service.data_dir.rglob("*") if path.is_file()}
    assert service.preview("p", "retire", "a")["eligible"]
    after = {str(path.relative_to(service.data_dir)): path.read_bytes() for path in service.data_dir.rglob("*") if path.is_file()}
    assert before == after
    assert not (original.parent.parent / ".material-byte-leases").exists()


def test_receipt_failure_after_unlink_recovers_as_absent_without_claiming_new_bytes(tmp_path, monkeypatch):
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    truth = service.preview("p", "retire", "a")
    write = service._write_receipt
    def fail_terminal(task_id, ref, receipt):
        if receipt["status"] == "deleted":
            raise OSError("audit disk unavailable")
        write(task_id, ref, receipt)
    monkeypatch.setattr(service, "_write_receipt", fail_terminal)
    with pytest.raises(OSError):
        apply(service, truth)
    assert not original.exists()
    monkeypatch.setattr(service, "_write_receipt", write)
    recovered = apply(service, truth)
    assert recovered["status"] == "absent_after_detach"
    assert recovered["deleted_logical_bytes"] == 0 and recovered["physical_space_released"] is None
    assert apply(service, truth)["status"] == "already_absent"


def test_finished_bound_jobs_do_not_permanently_protect_historical_original(tmp_path, monkeypatch):
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    historical = replace(TaskRecord.new("old-train", "p", TaskKind.TRAINING, "payload.json", "training"), status=TaskStatus.SUCCEEDED)
    tasks.create(historical)
    folder = original.parent.parent / "jobs/old-train"
    folder.mkdir(parents=True)
    (folder / "job.json").write_text('{"status":"succeeded"}')
    run = original.parent.parent / "runs/train_old-train/weights"
    run.mkdir(parents=True)
    (run / "best.pt").write_bytes(b"retain-model")
    truth = service.preview("p", "retire", "a")
    assert truth["eligible"], truth
    assert apply(service, truth)["status"] == "deleted"
    assert (run / "best.pt").read_bytes() == b"retain-model"


def test_audit_conflict_is_detected_before_any_source_detach(tmp_path, monkeypatch):
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    truth = service.preview("p", "retire", "a")
    key = "physical_" + service._audit_key(["p", "retire", "a"], "gc-a")
    with materials._connect() as db:
        db.execute("INSERT INTO material_storage_audit VALUES(?,?,?,?,?,?)", (key, "a", "WRONG", "x", "", "now"))
    with pytest.raises(RuntimeError, match="AUDIT_CONFLICT"):
        apply(service, truth)
    assert original.exists()
    assert not (original.parent.parent / ".material-reclaim/gc-a").exists()


def test_registered_worker_and_startup_gate_refuse_maintenance(tmp_path, monkeypatch):
    from platform_core.task_runtime.worker_instances import WorkerInstanceService
    from platform_core.storage.local import controlled_local_startup_guard
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    lease = WorkerInstanceService(tasks).acquire(service.data_dir, ["training"], "test", "worker", node_id="test-node")
    assert "WORKER_INSTANCE_PRESENT" in service.preview("p", "retire", "a")["blockers"]
    lease.release()
    truth = service.preview("p", "retire", "a")
    with controlled_local_startup_guard(service.data_dir):
        with pytest.raises(RuntimeError, match="BUSY"):
            apply(service, truth)
    assert original.exists()


def test_new_reference_writer_waits_for_original_project_fence_then_rejects_missing_source(tmp_path, monkeypatch):
    import threading
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    truth = service.preview("p", "retire", "a")
    started, done = threading.Event(), threading.Event()
    failures, writers = [], []
    unlink = service._unlink_quarantined
    def writer():
        started.set()
        try:
            materials.upsert({"id": "new-reference", "filename": "a.png"})
        except ValueError as error:
            failures.append(str(error))
        finally:
            done.set()
    def during_delete(path):
        thread = threading.Thread(target=writer)
        writers.append(thread)
        thread.start()
        assert started.wait(1)
        assert not done.wait(0.05)
        unlink(path)
    monkeypatch.setattr(service, "_unlink_quarantined", during_delete)
    assert apply(service, truth)["status"] == "deleted"
    assert done.wait(2)
    for thread in writers:
        thread.join()
    assert failures and materials.get("new-reference") is None


def test_network_filesystem_and_nonpython_webserver_are_unsupported(tmp_path, monkeypatch):
    from types import SimpleNamespace
    import platform_core.local_material_reclamation as module
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    monkeypatch.setattr(service, "_local_disk", lambda path: False)
    assert "UNSUPPORTED_FILESYSTEM" in service.preview("p", "retire", "a")["blockers"]
    monkeypatch.setattr(module.psutil, "process_iter", lambda *a, **kw: [SimpleNamespace(info={
        "pid": 12345, "name": "uvicorn.exe", "exe": "C:/apps/uvicorn.exe", "cmdline": [], "cwd": "C:/apps"})])
    assert "OFFLINE_MAINTENANCE_REQUIRED" in service.preview("p", "retire", "a")["blockers"]


def test_corrupt_receipt_cannot_redirect_isolated_reclamation(tmp_path, monkeypatch):
    import json
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    truth = service.preview("p", "retire", "a")
    monkeypatch.setattr(service, "_unlink_quarantined", lambda path: (_ for _ in ()).throw(OSError("busy")))
    with pytest.raises(OSError):
        apply(service, truth)
    ref = "physical-reclamation/gc-a.json"
    receipt = service.artifacts.read_json("retire", ref)
    receipt["quarantine"] = str(tmp_path / "unrelated-file")
    service.artifacts.atomic_write_json("retire", ref, receipt)
    with pytest.raises(RuntimeError, match="RECEIPT_UNVERIFIED"):
        apply(service, truth)
    assert (original.parent.parent / ".material-reclaim/gc-a").exists()


def test_absent_recovery_remains_detached_if_task_gate_rejects_and_can_retry(tmp_path, monkeypatch):
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    truth = service.preview("p", "retire", "a")
    write = service._write_receipt
    monkeypatch.setattr(service, "_write_receipt", lambda task_id, ref, receipt:
        (_ for _ in ()).throw(OSError("final receipt failed")) if receipt["status"] == "deleted" else write(task_id, ref, receipt))
    with pytest.raises(OSError):
        apply(service, truth)
    inserted = []
    def inject_active(task_id, ref, receipt):
        write(task_id, ref, receipt)
        if receipt["status"] == "detached" and not inserted:
            tasks.create(TaskRecord.new("intervening", "p", TaskKind.TRAINING, "payload.json", "training"))
            inserted.append(True)
    monkeypatch.setattr(service, "_write_receipt", inject_active)
    with pytest.raises(RuntimeError, match="ACTIVE_TASK"):
        apply(service, truth)
    assert service.artifacts.read_json("retire", "physical-reclamation/gc-a.json")["status"] == "detached"
    with tasks._connect() as db:
        db.execute("UPDATE tasks SET status='CANCELLED' WHERE task_id='intervening'")
    monkeypatch.setattr(service, "_write_receipt", write)
    recovered = apply(service, truth)
    assert recovered["status"] == "absent_after_detach" and recovered["deleted_logical_bytes"] == 0


def test_foreign_task_runtime_or_retirement_journal_path_is_rejected(tmp_path, monkeypatch):
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    foreign_tasks = TaskRepository(tmp_path / "foreign/tasks.sqlite3")
    with pytest.raises(ValueError, match="canonical"):
        LocalMaterialReclamationService(service.data_dir, foreign_tasks, service.artifacts, controlled_local_writers=True)
    truth = service.preview("p", "retire", "a")
    root = service.artifacts.root / "retire"
    root.mkdir(exist_ok=True)
    root.rename(root.with_name("retire-saved"))
    try:
        root.symlink_to(tmp_path / "foreign", target_is_directory=True)
    except OSError:
        pytest.skip("host cannot create directory symlinks")
    with pytest.raises(RuntimeError, match="UNSAFE_RECLAMATION_RECEIPT"):
        apply(service, truth)
    assert original.exists()


@pytest.mark.parametrize("unknown_field", ["cmdline", "cwd"])
def test_unknown_python_process_evidence_still_refuses_real_reclamation(tmp_path, monkeypatch, unknown_field):
    import platform_core.local_material_reclamation as module
    service, materials, original, tasks = setup_gc(tmp_path, monkeypatch)
    evidence = {"pid": 987654, "name": "python", "exe": "/usr/bin/python",
                "cmdline": ["python", "unidentified.py"], "cwd": str(tmp_path)}
    evidence[unknown_field] = None
    monkeypatch.setattr(module.psutil, "process_iter", lambda *a, **kw: [SimpleNamespace(info=evidence)])
    truth = service.preview("p", "retire", "a")
    assert "PROCESS_INSPECTION_UNKNOWN" in truth["blockers"]
    with pytest.raises(RuntimeError, match="PROCESS_INSPECTION_UNKNOWN"):
        apply(service, truth)
    assert original.exists()
