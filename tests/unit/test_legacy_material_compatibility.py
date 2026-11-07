import hashlib
import json

import pytest
from PIL import Image

from platform_core.material_repository import MaterialRepository
from platform_core.annotation_repository import AnnotationRepository
from platform_core.legacy_material_compatibility import LegacyMaterialCompatibilityService


def setup_project(tmp_path):
    data = tmp_path / "data"
    project = data / "projects/p"
    (project / "uploads").mkdir(parents=True)
    Image.new("RGB", (8, 6), "red").save(project / "uploads/a.png")
    materials = MaterialRepository(project)
    materials.upsert_many([{"id": "a", "filename": "a.png", "width": 8, "height": 6}])
    annotations = AnnotationRepository(project)
    return LegacyMaterialCompatibilityService(data, "p"), materials, annotations, project


def test_legacy_scan_is_readonly_and_json_apply_is_unsupported(tmp_path):
    project = tmp_path / "projects/p"
    (project / "uploads").mkdir(parents=True)
    Image.new("RGB", (8, 6)).save(project / "uploads/a.png")
    (project / "images.json").write_text(json.dumps([{"id": "a", "filename": "a.png"}]))
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    service = LegacyMaterialCompatibilityService(tmp_path, "p")
    result = service.scan(limit=1)
    assert result["items"][0]["status"] == "unsupported"
    assert result["items"][0]["material_owner"] == "legacy_json"
    assert not (project / "materials.sqlite3").exists()
    assert not (project / "annotations.sqlite3").exists()
    assert before == {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}


def test_confirmed_metadata_apply_backed_up_idempotent_and_keeps_original_gt(tmp_path):
    service, materials, annotations, project = setup_project(tmp_path)
    original = (project / "uploads/a.png").read_bytes()
    annotations.upsert("a", [], annotation_state="unannotated", project_material=False)
    gt = annotations.get("a")
    preview = service.preview(["a"])
    assert preview["items"][0]["status"] == "candidate"
    with pytest.raises(ValueError):
        service.apply(["a"], expected_fingerprint=preview["fingerprint"], task_id="compat-a", confirmed=False)
    receipt = service.apply(["a"], expected_fingerprint=preview["fingerprint"], task_id="compat-a", confirmed=True)
    assert receipt["status"] == "applied"
    assert json.loads((project / receipt["backup_ref"]).read_text())["fingerprint"] == preview["fingerprint"]
    assert materials.get("a")["content_sha256"] == hashlib.sha256(original).hexdigest()
    assert (project / "uploads/a.png").read_bytes() == original
    assert annotations.get("a") == gt
    assert service.apply(["a"], expected_fingerprint=preview["fingerprint"], task_id="compat-a", confirmed=True)["status"] == "already_applied"
    assert service.scan()["items"][0]["status"] == "normal"


def test_concurrent_material_or_source_change_rejects_stale_preview(tmp_path):
    service, materials, _, project = setup_project(tmp_path)
    preview = service.preview(["a"])
    Image.new("RGB", (8, 6), "blue").save(project / "uploads/a.png")
    with pytest.raises(RuntimeError, match="STALE"):
        service.apply(["a"], expected_fingerprint=preview["fingerprint"], task_id="compat-a", confirmed=True)
    assert not materials.get("a")["content_sha256"]


def test_backup_failure_prevents_metadata_write_and_disable_blocks_apply(tmp_path, monkeypatch):
    service, materials, _, _ = setup_project(tmp_path)
    preview = service.preview(["a"])
    monkeypatch.setattr(service, "_write_backup", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError):
        service.apply(["a"], expected_fingerprint=preview["fingerprint"], task_id="compat-a", confirmed=True)
    assert not materials.get("a")["content_sha256"]
    service.enabled = False
    with pytest.raises(RuntimeError, match="DISABLED"):
        service.scan()


def test_existing_conflicting_identity_is_reported_without_repair(tmp_path):
    service, materials, _, _ = setup_project(tmp_path)
    row = materials.get("a")
    materials.upsert_many([{**row, "content_sha256": "b" * 64}])
    assert service.preview(["a"])["items"][0]["status"] == "conflict"


@pytest.mark.parametrize("field", ["annotation_source_content_sha256", "annotation_version"])
def test_gt_binding_conflict_cannot_be_repaired_as_missing_metadata(tmp_path, field):
    service, materials, annotations, _ = setup_project(tmp_path)
    annotations.upsert("a", [], annotation_state="unannotated", project_material=False)
    gt = annotations.get("a")
    value = "f" * 64 if field.endswith("sha256") else gt["version"] + 1
    materials.upsert_many([{**materials.get("a"), field: value}])
    before = materials.get("a")
    preview = service.preview(["a"])
    assert preview["items"][0]["status"] == "conflict"
    with pytest.raises(ValueError):
        service.apply(["a"], expected_fingerprint=preview["fingerprint"], task_id="gt-conflict", confirmed=True)
    assert materials.get("a") == before
    assert annotations.get("a") == gt


def test_shared_object_alias_is_report_only_and_cannot_modify_unselected_row(tmp_path):
    service, materials, _, _ = setup_project(tmp_path)
    materials.upsert_many([{**materials.get("a"), "id": "alias"}])
    result = service.preview(["a"])
    assert result["items"][0]["status"] == "conflict"
    with pytest.raises(ValueError):
        service.apply(["a"], expected_fingerprint=result["fingerprint"], task_id="alias-test", confirmed=True)
    assert not materials.get("a")["content_sha256"]
    assert not materials.get("alias")["content_sha256"]


def test_interrupted_after_durable_backup_can_resume_without_overwriting_backup(tmp_path, monkeypatch):
    service, materials, _, project = setup_project(tmp_path)
    preview = service.preview(["a"])
    real = MaterialRepository.reconcile_storage_batch
    monkeypatch.setattr(MaterialRepository, "reconcile_storage_batch", lambda *a, **kw: (_ for _ in ()).throw(OSError("interrupted")))
    with pytest.raises(OSError):
        service.apply(["a"], expected_fingerprint=preview["fingerprint"], task_id="resume", confirmed=True)
    backup = project / ".legacy-material-compatibility/resume.json"
    before = backup.read_bytes()
    monkeypatch.setattr(MaterialRepository, "reconcile_storage_batch", real)
    assert service.apply(["a"], expected_fingerprint=preview["fingerprint"], task_id="resume", confirmed=True)["status"] == "applied"
    assert backup.read_bytes() == before


def test_material_change_after_preview_cannot_be_overwritten(tmp_path):
    service, materials, _, _ = setup_project(tmp_path)
    preview = service.preview(["a"])
    materials.upsert_many([{**materials.get("a"), "filename": "new-ui-name.png"}])
    with pytest.raises(RuntimeError, match="STALE"):
        service.apply(["a"], expected_fingerprint=preview["fingerprint"], task_id="cas", confirmed=True)
    assert materials.get("a")["filename"] == "new-ui-name.png"
    assert not materials.get("a")["content_sha256"]


def test_configured_default_source_cannot_be_silently_replaced_by_project_uploads(tmp_path):
    import sqlite3
    service, materials, _, project = setup_project(tmp_path)
    storage = service.data_dir / "storage"
    storage.mkdir()
    with sqlite3.connect(storage / "storage_sources.sqlite3") as db:
        db.execute("CREATE TABLE storage_sources(id TEXT, type TEXT, config_json TEXT, enabled INTEGER)")
        db.execute("INSERT INTO storage_sources VALUES('default_local','local',?,1)",
                   (json.dumps({"root": str(tmp_path / "another-root")}),))
    result = service.preview(["a"])
    assert result["items"][0]["status"] == "unsupported"
    assert not result["needs_migration"]


def test_transaction_cas_catches_write_after_durable_preview(tmp_path, monkeypatch):
    service, materials, _, _ = setup_project(tmp_path)
    preview = service.preview(["a"])
    reconcile = MaterialRepository.reconcile_storage_batch
    def concurrent(owner, *args, **kwargs):
        materials.upsert_many([{**materials.get("a"), "filename": "latest-name.png"}])
        return reconcile(owner, *args, **kwargs)
    monkeypatch.setattr(MaterialRepository, "reconcile_storage_batch", concurrent)
    with pytest.raises(RuntimeError, match="STALE"):
        service.apply(["a"], expected_fingerprint=preview["fingerprint"], task_id="last-gap", confirmed=True)
    assert materials.get("a")["filename"] == "latest-name.png"
    assert not materials.get("a")["content_sha256"]
    with materials._connect() as db:
        assert db.execute("SELECT COUNT(*) FROM material_storage_audit WHERE task_id='last-gap'").fetchone()[0] == 0


def test_full_scan_cursor_counts_readonly_and_rejects_changed_catalog(tmp_path):
    service, materials, annotations, project = setup_project(tmp_path)
    source = (project / "uploads/a.png").read_bytes()
    rows = []
    for i in range(119):
        name = f"full-{i:03d}"
        (project / "uploads" / f"{name}.png").write_bytes(source)
        rows.append({"id": name, "filename": f"{name}.png", "width": 8, "height": 6})
    materials.upsert_many(rows)
    before = {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    first = service.scan(limit=50)
    assert first["total"] == 120
    batches = [first]
    while batches[-1]["next_cursor"] is not None:
        batches.append(service.scan(limit=50, cursor=batches[-1]["next_cursor"],
                                    expected_catalog=first["catalog_fingerprint"]))
    assert [len(x["items"]) for x in batches] == [50, 50, 20]
    assert len({row["image_id"] for batch in batches for row in batch["items"]}) == 120
    assert all(x["catalog_fingerprint"] == first["catalog_fingerprint"] for x in batches)
    assert before == {p.relative_to(project): p.read_bytes() for p in project.rglob("*") if p.is_file()}
    (project / "uploads/a.png").unlink()
    with pytest.raises(RuntimeError, match="STALE"):
        service.scan(cursor=first["next_cursor"], expected_catalog=first["catalog_fingerprint"])
    (project / "uploads/a.png").write_bytes(source)
    first = service.scan(limit=50)
    annotations.upsert("a", [], annotation_state="unannotated", project_material=False)
    with pytest.raises(RuntimeError, match="STALE"):
        service.scan(cursor=first["next_cursor"], expected_catalog=first["catalog_fingerprint"])
    first = service.scan(limit=50)
    materials.upsert_many([{**materials.get("full-000"), "filename": "updated-name.png"}])
    with pytest.raises(RuntimeError, match="STALE"):
        service.scan(cursor=first["next_cursor"], expected_catalog=first["catalog_fingerprint"])


def test_scan_reports_gt_and_thumbnail_anomalies_without_writing(tmp_path):
    service, materials, annotations, project = setup_project(tmp_path)
    annotations.upsert("a", [], annotation_state="unannotated", project_material=False)
    materials.upsert_many([{**materials.get("a"), "thumbnail_path": "thumbnails/missing.jpg"}])
    result = service.scan()
    assert "thumbnail_issue" in result["items"][0]["categories"]
    materials.upsert_many([{**materials.get("a"), "annotation_version": 999}])
    item = service.scan()["items"][0]
    assert "gt_issue" in item["categories"] and "conflict" in item["categories"]
