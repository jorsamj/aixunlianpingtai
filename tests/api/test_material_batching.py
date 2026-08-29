import threading
import uuid

from PIL import Image


def create_project(client) -> str:
    response = client.post(
        "/api/projects",
        json={"name": f"batch-{uuid.uuid4().hex[:8]}", "labels": []},
    )
    response.raise_for_status()
    return response.json()["id"]


def write_png(path, color: str):
    Image.new("RGB", (64, 64), color).save(path, format="PNG")


def test_image_batch_commits_once_and_rebases_concurrent_upsert(client, tmp_path):
    import app as app_module

    project_id = create_project(client)
    store = app_module.material_store(project_id)
    store.upsert({"id": "existing", "filename": "existing.png", "split": "unassigned"})
    baseline_revision = store.read().revision
    first_source = tmp_path / "first.png"
    second_source = tmp_path / "second.png"
    write_png(first_source, "white")
    write_png(second_source, "black")

    app_module._v50_begin_image_batch(project_id)
    committed = False
    try:
        app_module._v18_set_image_split(project_id, "existing", "test")
        first = app_module.add_image_record(
            project_id, first_source, "first.png", "imported_yolo", "default"
        )
        app_module.write_annotation(
            project_id,
            first["id"],
            [{"class_id": 0, "label": "target", "x1": 1, "y1": 1, "x2": 20, "y2": 20}],
        )
        app_module._v18_set_image_split(project_id, first["id"], "train")
        second = app_module.add_image_record(
            project_id, second_source, "second.png", "imported_yolo", "default"
        )
        app_module._v18_set_image_split(project_id, second["id"], "val")
        app_module._v50_mark_image_processed(
            project_id, second["id"], annotated=True
        )

        assert store.read().revision == baseline_revision
        outside = {"id": "outside", "filename": "outside.png", "split": "test"}
        outcome = {}

        def outside_upsert():
            outcome["batch"] = app_module._v50_active_image_batch(project_id)
            outcome["row"] = app_module.material_store(project_id).upsert(outside)

        thread = threading.Thread(target=outside_upsert)
        thread.start()
        thread.join(5)
        assert not thread.is_alive()
        assert outcome == {"batch": None, "row": outside}
        outside_revision = store.read().revision
        assert outside_revision == baseline_revision + 1

        app_module._v50_end_image_batch(save=True)
        committed = True
    finally:
        if not committed and app_module._v50_active_image_batch(project_id):
            app_module._v50_end_image_batch(save=False)

    snapshot = store.read()
    assert snapshot.revision == outside_revision + 1
    assert [row["id"] for row in snapshot.rows] == [
        "existing",
        "outside",
        first["id"],
        second["id"],
    ]
    rows = {row["id"]: row for row in snapshot.rows}
    assert rows["existing"]["split"] == "test"
    assert rows[first["id"]]["split"] == "train"
    assert rows[first["id"]]["box_count"] == 1
    assert rows[first["id"]]["annotated"] is True
    assert rows[second["id"]]["split"] == "val"
    assert rows[second["id"]]["box_count"] == 0
    assert rows[second["id"]]["annotated"] is False
    assert rows[second["id"]]["processing_status"] == "processed"
    assert rows[second["id"]]["annotated_at"]
    assert app_module._v50_active_image_batch(project_id) is None


def test_image_batch_save_false_discards_metadata_without_revision(client, tmp_path):
    import app as app_module

    project_id = create_project(client)
    store = app_module.material_store(project_id)
    baseline_revision = store.read().revision
    source = tmp_path / "discard.png"
    write_png(source, "gray")

    app_module._v50_begin_image_batch(project_id)
    record = app_module.add_image_record(
        project_id, source, "discard.png", "imported_yolo", "default"
    )
    app_module.write_annotation(
        project_id,
        record["id"],
        [{"class_id": 0, "label": "target", "x1": 1, "y1": 1, "x2": 20, "y2": 20}],
    )
    app_module._v18_set_image_split(project_id, record["id"], "train")
    app_module._v50_end_image_batch(save=False)

    snapshot = store.read()
    assert snapshot.revision == baseline_revision
    assert all(row.get("id") != record["id"] for row in snapshot.rows)
    assert app_module._v50_active_image_batch(project_id) is None
