import threading
import uuid

import pytest
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
        assert outcome["batch"] is None
        assert {key: outcome["row"][key] for key in outside} == outside
        assert outcome["row"]["storage_source_id"] == "default_local"
        outside_revision = store.read().revision
        assert outside_revision == baseline_revision + 1

        app_module._v50_end_image_batch(save=True)
        committed = True
    finally:
        if not committed and app_module._v50_active_image_batch(project_id):
            app_module._v50_end_image_batch(save=False)

    snapshot = store.read()
    assert snapshot.revision == outside_revision + 1
    assert {row["id"] for row in snapshot.rows} == {
        "existing", "outside", first["id"], second["id"]
    }
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


def test_image_batch_rejects_dataset_deleted_before_commit(client, tmp_path):
    import app as app_module

    project_id = create_project(client)
    dataset_id = client.post(
        f"/api/projects/{project_id}/datasets",
        json={"name": "short-lived", "description": ""},
    ).json()["id"]
    source = tmp_path / "buffered.png"
    write_png(source, "purple")

    app_module._v50_begin_image_batch(project_id)
    record = app_module.add_image_record(
        project_id, source, "buffered.png", "imported_yolo", dataset_id
    )
    project_path = app_module.project_dir(project_id)
    upload_path = project_path / "uploads" / record["stored_name"]
    annotation_path = project_path / "annotations" / f"{record['id']}.json"
    assert upload_path.exists()
    assert annotation_path.exists()
    assert app_module.delete_dataset(project_id, dataset_id) == {"ok": True}

    try:
        with pytest.raises(app_module.HTTPException) as raised:
            app_module._v50_end_image_batch(save=True)
    finally:
        if app_module._v50_active_image_batch(project_id):
            app_module._v50_end_image_batch(save=False)

    assert raised.value.status_code == 409
    assert all(
        str(row.get("id")) != record["id"]
        for row in app_module.material_store(project_id).read().rows
    )
    assert not upload_path.exists()
    assert not annotation_path.exists()


def test_rejected_multi_dataset_batch_cleans_all_buffered_files(
    client, tmp_path, monkeypatch
):
    import app as app_module

    project_id = create_project(client)
    deleting_dataset = client.post(
        f"/api/projects/{project_id}/datasets",
        json={"name": "deleting", "description": ""},
    ).json()["id"]
    other_dataset = client.post(
        f"/api/projects/{project_id}/datasets",
        json={"name": "other", "description": ""},
    ).json()["id"]
    seed_source = tmp_path / "seed.png"
    first_source = tmp_path / "first.png"
    second_source = tmp_path / "second.png"
    write_png(seed_source, "red")
    write_png(first_source, "green")
    write_png(second_source, "blue")
    seed = app_module.add_image_record(
        project_id, seed_source, "seed.png", "raw", deleting_dataset
    )

    app_module._v50_begin_image_batch(project_id)
    first = app_module.add_image_record(
        project_id, first_source, "first.png", "imported_yolo", deleting_dataset
    )
    second = app_module.add_image_record(
        project_id, second_source, "second.png", "imported_yolo", other_dataset
    )
    reached = threading.Event()
    resume = threading.Event()
    original_stage = app_module._v50_stage_material_file

    def paused_stage(source, destination):
        if threading.current_thread().name == "batch-delete" and not reached.is_set():
            reached.set()
            assert resume.wait(5), "dataset deletion did not resume"
        return original_stage(source, destination)

    monkeypatch.setattr(app_module, "_v50_stage_material_file", paused_stage)
    outcome = {}

    def run_delete():
        try:
            outcome["value"] = app_module.delete_dataset(
                project_id, deleting_dataset
            )
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=run_delete, name="batch-delete")
    thread.start()
    try:
        assert reached.wait(5)
        with pytest.raises(app_module.HTTPException) as raised:
            app_module._v50_end_image_batch(save=True)
    finally:
        resume.set()
        thread.join(5)
        if app_module._v50_active_image_batch(project_id):
            app_module._v50_end_image_batch(save=False)

    assert raised.value.status_code == 409
    assert outcome == {"value": {"ok": True}}
    rows = app_module.material_store(project_id).read().rows
    assert {str(row.get("id")) for row in rows}.isdisjoint(
        {seed["id"], first["id"], second["id"]}
    )
    project_path = app_module.project_dir(project_id)
    for record in (first, second):
        assert not (project_path / "uploads" / record["stored_name"]).exists()
        assert not (project_path / "annotations" / f"{record['id']}.json").exists()
