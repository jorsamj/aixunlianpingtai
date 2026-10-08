"""Storage Source lifecycle admission for normal image upload and retirement."""

import io
import uuid

from PIL import Image

import app as app_module


def _project(client):
    response = client.post("/api/projects", json={
        "name": "storage-fence-" + uuid.uuid4().hex[:9],
        "labels": [{"code": "smoke", "display_name": "烟雾"}],
    })
    response.raise_for_status()
    return response.json()["id"]


def _source(client, tmp_path):
    source_id = "upload_src_" + uuid.uuid4().hex[:10]
    original_root = tmp_path / "before"
    next_root = tmp_path / "after"
    response = client.post("/api/v61/storage-sources", json={
        "id": source_id, "name": source_id, "type": "local",
        "config": {"root": str(original_root)}, "enabled": True,
    })
    assert response.status_code == 201, response.text
    return source_id, original_root, next_root


def _send(client, project_id, source_id, request_id):
    data = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(data, format="JPEG")
    return client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("capture.jpg", data.getvalue(), "image/jpeg"))],
        data={"dataset_id": "default",
              "storage_source_id": source_id,
              "upload_request_id": request_id},
    )


def test_plain_upload_rejects_config_change_before_material_commit(client, tmp_path, monkeypatch):
    project_id = _project(client)
    source_id, original_root, next_root = _source(client, tmp_path)
    original = app_module.add_image_record
    updated = []

    def change_source_after_object_upload(*args, **kwargs):
        record = original(*args, **kwargs)
        if record and not updated:
            with app_module._storage_source_fence():
                app_module.storage_source_repository().update(
                    source_id, {"config": {"root": str(next_root)}},
                )
            updated.append(True)
        return record

    with monkeypatch.context() as patch:
        patch.setattr(app_module, "add_image_record", change_source_after_object_upload)
        response = _send(client, project_id, source_id, "src-change-" + uuid.uuid4().hex[:10])
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "UPLOAD_STORAGE_SOURCE_CHANGED"
    assert app_module.material_store(project_id).count() == 0
    assert list((original_root / "uploads").glob("*")) == []
    assert not (next_root / "uploads").exists()


def test_plain_upload_rejects_source_deletion_before_material_commit(client, tmp_path, monkeypatch):
    project_id = _project(client)
    source_id, original_root, _ = _source(client, tmp_path)
    original = app_module.add_image_record
    retired = []

    def retire_after_object_upload(*args, **kwargs):
        record = original(*args, **kwargs)
        if record and not retired:
            # Source had no durable Material references yet.
            result = app_module.delete_storage_source(source_id)
            assert result["ok"] is True
            retired.append(True)
        return record

    with monkeypatch.context() as patch:
        patch.setattr(app_module, "add_image_record", retire_after_object_upload)
        response = _send(client, project_id, source_id, "src-delete-" + uuid.uuid4().hex[:10])
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "UPLOAD_STORAGE_SOURCE_CHANGED"
    assert app_module.material_store(project_id).count() == 0
    assert list((original_root / "uploads").glob("*")) == []


def test_source_name_only_update_does_not_break_normal_image_upload(client, tmp_path, monkeypatch):
    project_id = _project(client)
    source_id, original_root, _ = _source(client, tmp_path)
    original = app_module.add_image_record
    renamed = []

    def rename_source_after_object_upload(*args, **kwargs):
        record = original(*args, **kwargs)
        if record and not renamed:
            with app_module._storage_source_fence():
                app_module.storage_source_repository().update(
                    source_id, {"name": "renamed-without-generation-change"},
                )
            renamed.append(True)
        return record

    with monkeypatch.context() as patch:
        patch.setattr(app_module, "add_image_record", rename_source_after_object_upload)
        response = _send(client, project_id, source_id, "src-rename-" + uuid.uuid4().hex[:10])
    assert response.status_code == 200, response.text
    image_id = response.json()["uploaded_image_ids"][0]
    material = app_module.material_store(project_id).get(image_id)
    assert material is not None
    assert material["storage_source_id"] == source_id
    assert app_module.storage_manager(project_id).materialize(material).path.is_file()
    assert list((original_root / "uploads").glob("*.jpg"))


def test_source_retirement_checks_active_task_dependencies(client, tmp_path, monkeypatch):
    source_id, _, _ = _source(client, tmp_path)
    visited = []

    def reject_active_task(candidate):
        visited.append(candidate)
        raise app_module.PlatformError(
            "STORAGE_SOURCE_ACTIVE_TASK_DEPENDENCY",
            "存储源正被活动任务使用", "active task",
            "请等待活动任务结束", 409,
        )

    with monkeypatch.context() as patch:
        patch.setattr(app_module, "_assert_storage_source_mutation_allowed", reject_active_task)
        response = client.delete(f"/api/v61/storage-sources/{source_id}")
    assert response.status_code == 409, response.text
    assert visited == [source_id]
    assert app_module.storage_source_repository().get(source_id) is not None


def test_deleted_and_recreated_source_id_is_not_the_original_generation(
    client, tmp_path, monkeypatch,
):
    project_id = _project(client)
    source_id, original_root, _ = _source(client, tmp_path)
    original = app_module.add_image_record
    recreated = []

    def replace_source_generation_after_upload(*args, **kwargs):
        record = original(*args, **kwargs)
        if record and not recreated:
            with app_module._storage_source_fence():
                repository = app_module.storage_source_repository()
                before = repository.get(source_id)
                assert before is not None
                assert repository.delete(source_id) is True
                after = repository.create({
                    "id": source_id, "name": "same-id-new-owner",
                    "type": "local", "config": {"root": str(original_root)},
                    "enabled": True,
                })
                assert after.created_at != before.created_at
            recreated.append(True)
        return record

    with monkeypatch.context() as patch:
        patch.setattr(app_module, "add_image_record", replace_source_generation_after_upload)
        response = _send(client, project_id, source_id, "src-aba-" + uuid.uuid4().hex[:10])
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "UPLOAD_STORAGE_SOURCE_CHANGED"
    assert app_module.material_store(project_id).count() == 0
    assert list((original_root / "uploads").glob("*")) == []
