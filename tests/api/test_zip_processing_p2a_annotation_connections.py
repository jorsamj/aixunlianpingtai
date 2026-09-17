import uuid


def test_annotation_upsert_returns_persisted_row_without_followup_get(tmp_path, monkeypatch):
    from platform_core.annotation_repository import AnnotationRepository

    repository = AnnotationRepository(tmp_path)

    def forbidden_get(_image_id):
        raise AssertionError("upsert must not open a follow-up get() read")

    monkeypatch.setattr(repository, "get", forbidden_get)
    boxes = [{
        "id": "box-1",
        "class_id": 0,
        "label": "target",
        "x1": 1,
        "y1": 2,
        "x2": 10,
        "y2": 12,
    }]
    first = repository.upsert("image-1", boxes, "annotated", project_material=False)
    assert first["image_id"] == "image-1"
    assert first["annotation_state"] == "annotated"
    assert first["boxes"] == boxes
    assert first["version"] == 1
    assert first["content_digest"]

    # Same digest is a no-op in SQLite; the return contract must still return
    # the persisted row from the same write connection, without calling get().
    second = repository.upsert("image-1", boxes, "annotated", project_material=False)
    assert second["content_digest"] == first["content_digest"]
    assert second["version"] == 1


def test_v50_image_batch_reuses_one_annotation_repository(client):
    import app as app_module

    project = client.post(
        "/api/projects",
        json={"name": f"p2a-{uuid.uuid4().hex[:8]}", "labels": ["target"]},
    ).json()
    project_id = project["id"]

    app_module._v50_begin_image_batch(project_id)
    try:
        app_module.write_annotation(project_id, "p2a-image-1", [], "unannotated")
        batch = app_module._v50_active_image_batch(project_id)
        assert batch is not None
        first_repository = batch.get("annotation_repository")
        assert first_repository is not None

        app_module.write_annotation(project_id, "p2a-image-2", [], "unannotated")
        assert batch.get("annotation_repository") is first_repository
    finally:
        app_module._v50_end_image_batch(save=False)
