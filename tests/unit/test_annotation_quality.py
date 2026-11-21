import json

from platform_core.annotation_quality import audit_cleaning_annotations, read_annotation_audit
from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_batches import BatchSelection
from platform_core.material_repository import MaterialRepository


def test_annotation_quality_audit_is_warning_only_and_uses_formal_ground_truth(tmp_path):
    (tmp_path / "meta.json").write_text(
        json.dumps({
            "labels": ["smoke", "legacy"],
            "label_meta": [{"status": "active"}, {"status": "active"}],
        }),
        encoding="utf-8",
    )
    materials = MaterialRepository(tmp_path)
    for image_id in ("annotated", "negative", "plain"):
        materials.upsert({
            "id": image_id, "filename": image_id + ".jpg",
            "stored_name": image_id + ".jpg",
            "object_key": "uploads/" + image_id + ".jpg",
            "processing_status": "processed", "width": 1000, "height": 1000,
        })
    annotations = AnnotationRepository(tmp_path)
    saved = annotations.upsert(
        "annotated",
        [
            {"id": "a", "class_id": 0, "label": "smoke", "x1": 1, "y1": 1, "x2": 5, "y2": 5, "source": "manual"},
            {"id": "b", "class_id": 0, "label": "smoke", "x1": 1, "y1": 1, "x2": 5, "y2": 5, "source": "manual"},
            {"id": "c", "class_id": 1, "label": "legacy", "x1": 100, "y1": 100, "x2": 300, "y2": 300, "source": "manual"},
        ],
        annotation_state="annotated",
    )
    annotations.upsert("negative", [], annotation_state="confirmed_empty", annotation_scope=["smoke"])
    annotations.upsert("plain", [], annotation_state="unannotated")
    before = annotations.get("annotated")
    (tmp_path / "meta.json").write_text(
        json.dumps({
            "labels": ["smoke", "legacy"],
            "label_meta": [{"status": "active"}, {"status": "disabled"}],
        }),
        encoding="utf-8",
    )

    manifest = BatchSelection(tmp_path / "selection.sqlite3")
    try:
        with manifest.transaction():
            manifest.database.executemany(
                "INSERT INTO selection(image_id,state) VALUES (?,?)",
                [("annotated", "succeeded"), ("negative", "succeeded"), ("plain", "succeeded")],
            )
            manifest.database.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('frozen','now')")
            manifest.database.execute(
                """CREATE TABLE IF NOT EXISTS clean_results (
                    image_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    flagged INTEGER NOT NULL DEFAULT 0
                )"""
            )
            for image_id in ("annotated", "negative", "plain"):
                manifest.database.execute(
                    "INSERT INTO clean_results(image_id,result_json,flagged) VALUES (?,?,0)",
                    (image_id, json.dumps({
                        "image_id": image_id,
                        "metrics": {"width": 1000, "height": 1000},
                        "issues": [],
                    })),
                )

        summary = audit_cleaning_annotations(tmp_path, manifest.database, materials, enabled=True)
        assert summary["audited_images"] == 1
        assert summary["review_images"] == 1
        assert summary["state_counts"] == {
            "annotated": 1, "unannotated": 1, "confirmed_empty": 1,
        }
        assert summary["class_balance"][0]["label"] == "smoke"
        assert summary["provenance_counts"]["manual"] == 1

        page = read_annotation_audit(manifest.database)
        assert page["next_cursor"] is None
        assert len(page["items"]) == 1
        item = page["items"][0]
        codes = {issue["code"] for issue in item["issues"]}
        assert "box_tiny" in codes
        assert "box_duplicate_exact" in codes
        assert "label_disabled" in codes
        assert item["annotation_digest"] == saved["content_digest"]
    finally:
        manifest.close()

    after = annotations.get("annotated")
    assert after["content_digest"] == before["content_digest"]
    assert after["boxes"] == before["boxes"]


def test_annotation_quality_treats_merged_deleted_and_active_false_labels_as_inactive(tmp_path):
    (tmp_path / "meta.json").write_text(
        json.dumps({
            "labels": ["active", "merged", "deleted", "legacy-active-false"],
            "label_meta": [
                {"code": "active", "status": "active", "active": True},
                {"code": "merged", "status": "active", "active": True},
                {"code": "deleted", "status": "active", "active": True},
                {"code": "legacy-active-false", "status": "active", "active": True},
            ],
        }),
        encoding="utf-8",
    )
    materials = MaterialRepository(tmp_path)
    materials.upsert({
        "id": "image", "filename": "image.jpg", "stored_name": "image.jpg",
        "object_key": "uploads/image.jpg", "processing_status": "processed",
        "width": 1000, "height": 1000,
    })
    annotations = AnnotationRepository(tmp_path)
    annotations.upsert(
        "image",
        [
            {"label": "active", "class_id": 0, "x1": 10, "y1": 10, "x2": 100, "y2": 100},
            {"label": "merged", "class_id": 1, "x1": 120, "y1": 10, "x2": 220, "y2": 100},
            {"label": "deleted", "class_id": 2, "x1": 240, "y1": 10, "x2": 340, "y2": 100},
            {"label": "legacy-active-false", "class_id": 3, "x1": 360, "y1": 10, "x2": 460, "y2": 100},
        ],
        annotation_state="annotated",
    )
    (tmp_path / "meta.json").write_text(
        json.dumps({
            "labels": ["active", "merged", "deleted", "legacy-active-false"],
            "label_meta": [
                {"code": "active", "status": "active", "active": True},
                {"code": "merged", "status": "merged", "active": False},
                {"code": "deleted", "status": "deleted", "active": False},
                {"code": "legacy-active-false", "status": "active", "active": False},
            ],
        }),
        encoding="utf-8",
    )
    manifest = BatchSelection(tmp_path / "selection.sqlite3")
    try:
        with manifest.transaction():
            manifest.database.execute(
                "INSERT INTO selection(image_id,state) VALUES ('image','succeeded')"
            )
            manifest.database.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES ('frozen','now')"
            )
            manifest.database.execute(
                """CREATE TABLE IF NOT EXISTS clean_results (
                    image_id TEXT PRIMARY KEY,
                    result_json TEXT NOT NULL,
                    flagged INTEGER NOT NULL DEFAULT 0
                )"""
            )
            manifest.database.execute(
                "INSERT INTO clean_results(image_id,result_json,flagged) VALUES (?,?,0)",
                ("image", json.dumps({
                    "image_id": "image",
                    "metrics": {"width": 1000, "height": 1000},
                    "issues": [],
                })),
            )

        summary = audit_cleaning_annotations(
            tmp_path, manifest.database, materials, enabled=True,
        )
        assert summary["review_images"] == 1
        item = read_annotation_audit(manifest.database)["items"][0]
        inactive = [
            issue for issue in item["issues"]
            if issue["code"] == "label_disabled"
        ]
        assert sum(int(issue["count"]) for issue in inactive) == 3
    finally:
        manifest.close()


def test_annotation_quality_audit_can_be_disabled_without_touching_ground_truth(tmp_path):
    materials = MaterialRepository(tmp_path)
    materials.upsert({
        "id": "image", "filename": "image.jpg", "stored_name": "image.jpg",
        "object_key": "uploads/image.jpg", "processing_status": "processed",
    })
    annotations = AnnotationRepository(tmp_path)
    annotations.upsert(
        "image",
        [{"label": "x", "class_id": 0, "x1": 1, "y1": 1, "x2": 10, "y2": 10}],
        annotation_state="annotated",
    )
    digest = annotations.get("image")["content_digest"]
    manifest = BatchSelection(tmp_path / "selection.sqlite3")
    try:
        with manifest.transaction():
            manifest.database.execute("INSERT INTO selection(image_id,state) VALUES ('image','succeeded')")
            manifest.database.execute("INSERT OR REPLACE INTO meta(key,value) VALUES ('frozen','now')")
        summary = audit_cleaning_annotations(tmp_path, manifest.database, materials, enabled=False)
        assert summary["enabled"] is False
        assert read_annotation_audit(manifest.database)["items"] == []
    finally:
        manifest.close()
    assert annotations.get("image")["content_digest"] == digest


def test_annotation_audit_numbered_page_reads_index_and_keeps_cursor_contract(tmp_path):
    from platform_core.annotation_quality import AUDIT_META_KEY, _ensure_schema

    manifest = BatchSelection(tmp_path / "selection.sqlite3")
    try:
        with manifest.transaction():
            _ensure_schema(manifest.database)
            manifest.database.execute(
                "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
                (AUDIT_META_KEY, json.dumps({"enabled": True, "review_images": 123})),
            )
            manifest.database.executemany(
                "INSERT INTO annotation_audit_results"
                "(image_id,result_json,target_count,density,flagged) VALUES (?,?,?,?,?)",
                [(f"{number:04d}", json.dumps({"image_id": f"{number:04d}"}), 1, 0.1, 1)
                 for number in range(123)]
                + [("unflagged", json.dumps({"image_id": "unflagged"}), 0, 0.0, 0)],
            )
        first = read_annotation_audit(manifest.database, page=1, page_size=50)
        last = read_annotation_audit(manifest.database, page=3, page_size=50)
        assert (first["total"], first["total_pages"], len(first["items"])) == (123, 3, 50)
        assert first["has_previous"] is False and first["has_next"] is True
        assert (last["page"], len(last["items"]), last["items"][0]["image_id"]) == (3, 23, "0100")
        assert last["has_previous"] is True and last["has_next"] is False
        assert last["next_cursor"] is None
        cursor_first = read_annotation_audit(manifest.database, limit=50)
        assert cursor_first["next_cursor"] == "0049"
        assert "page" not in cursor_first and "total_pages" not in cursor_first
        cursor_next = read_annotation_audit(manifest.database, cursor=cursor_first["next_cursor"], limit=50)
        assert cursor_next["items"][0]["image_id"] == "0050"
        for kwargs in ({"page": 4, "page_size": 50}, {"page": 0}, {"page": 1, "page_size": 0},
                       {"page": 1, "cursor": "0001"}):
            try:
                read_annotation_audit(manifest.database, **kwargs)
            except ValueError:
                pass
            else:
                raise AssertionError(f"expected invalid page request: {kwargs}")
    finally:
        manifest.close()
