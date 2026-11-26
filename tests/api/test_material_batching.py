import threading
import uuid

import pytest
from PIL import Image


def create_project(client) -> str:
    response = client.post(
        "/api/projects",
        json={"name": f"batch-{uuid.uuid4().hex[:8]}", "labels": ["target"]},
    )
    response.raise_for_status()
    return response.json()["id"]


def write_png(path, color: str):
    Image.new("RGB", (64, 64), color).save(path, format="PNG")


@pytest.mark.parametrize("operation", ["MOVE_DATASET", "CLASSIFY_SPLIT"])
def test_assignment_freeze_replays_original_receipts_without_rewriting(client, tmp_path, monkeypatch, operation):
    import app as app_module
    from platform_core.material_batches import BatchSelection, MaterialBatchHandler, SELECTION_REF
    from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRepository
    from contextlib import closing

    project = create_project(client)
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)
    scheduler = Scheduler(repository, artifacts, "assignment-worker",
        {TaskKind.MATERIAL_BATCH: MaterialBatchHandler(app_module.DATA_DIR)}, {"materials.batch"})
    store = app_module.material_store(project)
    dataset = client.post(f"/api/projects/{project}/datasets", json={"name": "Review"}).json()["id"]
    for image_id in ("apply", "drift", "exclude"):
        store.upsert({"id": image_id, "filename": image_id + ".png", "content_sha256": "a" * 64,
                      "split": "unassigned", "dataset_id": "default"})
    base = f"/api/v62/projects/{project}/material-batches"
    field, target = ("dataset_id", dataset) if operation == "MOVE_DATASET" else ("split", "val")
    packet = {"operation": operation, "selection_spec": {"scope": "FILTERED", "excluded_image_ids": ["exclude"]},
              "options": {field: target}, "request_id": str(uuid.uuid4())}
    preview = client.post(base + "/estimate", json=packet)
    assert preview.status_code == 200, preview.text
    assert preview.json()["count"] == 2
    packet["selection_spec"] = preview.json()["selection_spec"]
    if "dataset_revision" in preview.json():
        packet["options"]["dataset_revision"] = preview.json()["dataset_revision"]
    created = client.post(base, json=packet)
    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]
    assert client.get(base + "/by-request/" + packet["request_id"]).json()["task_id"] == task_id
    assert client.post(base, json=packet).json()["task_id"] == task_id
    assert client.post(base, json={**packet, "options": {field: "train" if field == "split" else "default",
                **({"dataset_revision": "f" * 64} if field == "dataset_id" else {})}}).status_code == 409
    store.patch({"drift": {"content_sha256": "b" * 64}})

    # Lose the selection checkpoint after a material transaction commits.
    apply = type(store).apply_assignment_batch
    def lost_checkpoint(self, *args, **kwargs):
        apply(self, *args, **kwargs)
        raise RuntimeError("simulated interruption after material commit")
    monkeypatch.setattr(type(store), "apply_assignment_batch", lost_checkpoint)
    assert scheduler.run_once()
    assert store.get("apply")[field] == target
    revision = store.read().revision
    page = client.get(f"{base}/{task_id}/results?limit=1").json()
    assert page["items"][0]["outcome"] == "updated"
    assert page["next_cursor"] == "apply"

    monkeypatch.setattr(type(store), "apply_assignment_batch", apply)
    assert client.post(f"{base}/{task_id}/retry").status_code == 202
    assert scheduler.run_once()
    assert store.read().revision == revision
    assert store.get("drift")[field] != target
    assert store.get("exclude")[field] != target
    assert client.get(f"{base}/{task_id}").json()["status"] == "PARTIAL_SUCCESS"
    assert client.get(f"{base}/{task_id}/results?cursor=apply").json()["items"] == [{
        "image_id": "drift", "item_state": "failed", "outcome": "conflict", "item_error": "MATERIAL_IDENTITY_CHANGED",
    }]
    with closing(BatchSelection(artifacts.artifact_path(task_id, SELECTION_REF))) as selection:
        assert selection.summary()["total"] == 2


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
    # One bounded Material identity transaction plus one bounded annotation
    # projection transaction; never one Material revision per image.
    assert snapshot.revision == outside_revision + 2
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
    annotation_repository = app_module.AnnotationRepository(project_path)
    assert upload_path.exists()
    # Formal GT cannot precede its canonical Material identity.
    assert not annotation_repository.exists(record["id"])
    app_module.atomic_write_json(app_module.datasets_file(project_id), [
        value for value in app_module.read_json(app_module.datasets_file(project_id), [])
        if value['id'] != dataset_id])

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
    assert upload_path.is_file()
    with app_module.material_store(project_id)._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM material_cleanup_deferred').fetchone()[0] == 1
    assert not annotation_repository.exists(record["id"])


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
    token = uuid.uuid4().hex
    app_module._v50_register_dataset_delete_token(token, project_id, deleting_dataset)
    try:
        with pytest.raises(app_module.HTTPException) as raised:
            app_module._v50_end_image_batch(save=True)
    finally:
        app_module._v50_unregister_dataset_delete_token(token)
        if app_module._v50_active_image_batch(project_id):
            app_module._v50_end_image_batch(save=False)
    assert raised.value.status_code == 409
    rows = app_module.material_store(project_id).read().rows
    assert {str(row.get("id")) for row in rows}.isdisjoint(
        {first["id"], second["id"]}
    )
    project_path = app_module.project_dir(project_id)
    annotation_repository = app_module.AnnotationRepository(project_path)
    for record in (first, second):
        assert (project_path / "uploads" / record["stored_name"]).is_file()
        assert not annotation_repository.exists(record["id"])

    assert app_module.material_store(project_id).get(seed['id']) is not None
    with app_module.material_store(project_id)._connect() as db:
        assert db.execute('SELECT COUNT(*) FROM material_cleanup_deferred').fetchone()[0] == 2
