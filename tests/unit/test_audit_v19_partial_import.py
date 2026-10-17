"""Read-only regression coverage for partial V19 import integrity inspection."""
import hashlib
import json
import sqlite3

from tools.audit_v19_partial_import import audit


JOB = "test_zip_job"


def _fixture(root):
    (root / "import_jobs" / JOB).mkdir(parents=True)
    (root / "uploads").mkdir()
    source = root / "uploads" / "image.jpg"
    source.write_bytes(b"image-original")
    source_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    gt_digest = "a" * 64
    box = {"label": "target", "source_task_id": JOB, "import_batch_id": JOB}
    material = {
        "id": "image001", "storage_source_id": "default_local",
        "storage_type": "local", "object_key": "uploads/image.jpg",
        "content_sha256": source_hash, "size_bytes": source.stat().st_size,
        "annotation_state": "annotated", "annotation_version": 1,
        "annotation_hash": gt_digest, "annotation_source_content_sha256": source_hash,
        "box_count": 1,
    }
    (root / "import_jobs" / JOB / "job.json").write_text(
        json.dumps({"status": "failed", "error": "500 admission"}), encoding="utf-8")
    (root / "import_jobs" / JOB / "report.json").write_text(
        json.dumps({"imported_images": 1, "annotated_images": 1, "boxes": 1,
                    "imported_image_ids": ["image001"]}), encoding="utf-8")
    with sqlite3.connect(root / "materials.sqlite3") as db:
        db.execute("CREATE TABLE materials(id TEXT PRIMARY KEY,payload_json TEXT)")
        db.execute("INSERT INTO materials VALUES (?,?)",
                   ("image001", json.dumps(material)))
    with sqlite3.connect(root / "annotations.sqlite3") as db:
        db.execute("CREATE TABLE annotations(image_id TEXT PRIMARY KEY,"
                   "annotation_state TEXT,version INTEGER,content_digest TEXT,boxes_json TEXT)")
        db.execute("INSERT INTO annotations VALUES (?,?,?,?,?)",
                   ("image001", "annotated", 1, gt_digest, json.dumps([box])))
    return source


def test_auditor_checks_source_digest_boxes_and_provenance_without_mutating(tmp_path):
    source = _fixture(tmp_path)
    before = {f: f.read_bytes() for f in (
        tmp_path / "materials.sqlite3", tmp_path / "annotations.sqlite3",
        source, tmp_path / "import_jobs" / JOB / "report.json")}
    result = audit(tmp_path, JOB)
    assert result["issues"] == {}
    assert result["verified_default_local_source_files"] == 1
    assert result["verified_source_sha256_matches"] == 1
    assert result["verified_ground_truth_boxes"] == 1
    assert result["verified_annotated_images"] == 1
    assert result["training_approved"] is False
    for path, original in before.items():
        assert path.read_bytes() == original


def test_auditor_detects_same_size_source_corruption_and_wrong_gt_projection(tmp_path):
    source = _fixture(tmp_path)
    source.write_bytes(b"image-changed!")  # same length is not essential: verify the hash
    with sqlite3.connect(tmp_path / "materials.sqlite3") as db:
        material = json.loads(db.execute(
            "SELECT payload_json FROM materials WHERE id='image001'").fetchone()[0])
        material["annotation_hash"] = "b" * 64
        db.execute("UPDATE materials SET payload_json=? WHERE id='image001'",
                   (json.dumps(material),))
    result = audit(tmp_path, JOB)
    assert result["issues"]["source_sha256_mismatch"] == 1
    assert result["issues"]["annotation_projection_digest_mismatch"] == 1
    assert result["verified_source_sha256_matches"] == 0
    assert result["training_approved"] is False


def test_auditor_reports_missing_annotation_db_and_report_identity_errors(tmp_path):
    _fixture(tmp_path)
    (tmp_path / "annotations.sqlite3").unlink()
    report = tmp_path / "import_jobs" / JOB / "report.json"
    payload = json.loads(report.read_text())
    payload["imported_image_ids"].append("image001")
    report.write_text(json.dumps(payload))
    result = audit(tmp_path, JOB)
    assert result["issues"]["missing_annotation_database"] == 1
    assert result["issues"]["duplicate_report_image_id_occurrences"] == 1
    assert result["issues"]["report_image_count_mismatch"] == 1
    assert result["issues"]["missing_formal_annotation"] == 1
    assert result["training_approved"] is False


def test_auditor_rejects_path_escape_without_reading_foreign_file(tmp_path):
    _fixture(tmp_path)
    with sqlite3.connect(tmp_path / "materials.sqlite3") as db:
        payload = json.loads(db.execute(
            "SELECT payload_json FROM materials WHERE id='image001'").fetchone()[0])
        payload["object_key"] = "../out-of-project.jpg"
        db.execute("UPDATE materials SET payload_json=? WHERE id='image001'",
                   (json.dumps(payload),))
    result = audit(tmp_path, JOB)
    assert result["issues"]["invalid_source_path"] == 1
