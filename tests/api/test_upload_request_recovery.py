"""Crash-window recovery and duplicate admission for regular image uploads."""

import asyncio
import io
import uuid

import pytest
from PIL import Image

import app as platform_app
from platform_core.upload_batches import UploadBatchStore, UploadRequestBusy


def _project(client):
    response = client.post("/api/projects", json={
        "name": f"upload-recovery-{uuid.uuid4().hex[:8]}",
        "labels": ["smoke"],
    })
    response.raise_for_status()
    return response.json()["id"]


def _image_bytes():
    buffer = io.BytesIO()
    Image.new("RGB", (48, 48), "white").save(buffer, format="JPEG")
    return buffer.getvalue()


def _upload(client, project_id, request_id, image_bytes=None):
    return client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("recovery.jpg", _image_bytes() if image_bytes is None else image_bytes, "image/jpeg"))],
        data={"dataset_id": "default", "storage_source_id": "default_local",
              "upload_request_id": request_id},
    )


def test_commit_then_receipt_write_crash_reconciles_without_duplicate(client, monkeypatch):
    project_id = _project(client)
    request_id = "receipt-" + uuid.uuid4().hex[:16]
    complete = UploadBatchStore.complete_upload_request

    def crash_after_commit(self, *args, **kwargs):
        raise RuntimeError("synthetic receipt write crash")

    with monkeypatch.context() as patch:
        patch.setattr(UploadBatchStore, "complete_upload_request", crash_after_commit)
        with pytest.raises(RuntimeError, match="synthetic receipt"):
            _upload(client, project_id, request_id)

    store = platform_app.upload_batch_store(project_id)
    pending = store.read(request_id)
    assert pending["upload_request_status"] == "PROCESSING"
    expected = pending["upload_prepared_image_ids"]
    assert len(expected) == 1
    assert platform_app.material_store(project_id).get(expected[0]) is not None
    replay = _upload(client, project_id, request_id)
    assert replay.status_code == 200, replay.text
    data = replay.json()
    assert data["replayed"] is True
    assert data["uploaded_image_ids"] == expected
    assert store.read(request_id)["upload_request_status"] == "SUCCEEDED"
    assert platform_app.material_store(project_id).count() == 1
    repeated = _upload(client, project_id, request_id)
    assert repeated.status_code == 200
    assert repeated.json()["uploaded_image_ids"] == expected
    assert platform_app.material_store(project_id).count() == 1


def test_prepared_but_uncommitted_crash_never_reports_success(client, monkeypatch):
    project_id = _project(client)
    request_id = "uncommitted-" + uuid.uuid4().hex[:12]
    finish = platform_app._v50_end_image_batch

    def crash_before_commit(save=True):
        if save:
            raise RuntimeError("synthetic pre-commit crash")
        return finish(save=False)

    with monkeypatch.context() as patch:
        patch.setattr(platform_app, "_v50_end_image_batch", crash_before_commit)
        with pytest.raises(RuntimeError, match="pre-commit"):
            _upload(client, project_id, request_id)

    pending = platform_app.upload_batch_store(project_id).read(request_id)
    assert pending["upload_request_status"] == "PROCESSING"
    assert pending["upload_prepared_image_ids"]
    assert platform_app.material_store(project_id).count() == 0
    response = _upload(client, project_id, request_id)
    assert response.status_code == 409, response.text
    assert response.json()["code"] == "UPLOAD_REQUEST_RECOVERY_UNCONFIRMED"
    assert platform_app.upload_batch_store(project_id).read(request_id)["upload_request_status"] == "FAILED"
    assert platform_app.material_store(project_id).count() == 0


def test_partial_annotation_commit_is_not_mistaken_for_full_success(client, monkeypatch):
    project_id = _project(client)
    request_id = "partial-" + uuid.uuid4().hex[:12]

    def fail_receipt(self, *args, **kwargs):
        raise RuntimeError("synthetic post-commit receipt error")

    with monkeypatch.context() as patch:
        patch.setattr(UploadBatchStore, "complete_upload_request", fail_receipt)
        with pytest.raises(RuntimeError, match="post-commit"):
            _upload(client, project_id, request_id)

    store = platform_app.upload_batch_store(project_id)
    image_id = store.read(request_id)["upload_prepared_image_ids"][0]
    platform_app._v50_annotation_repository(project_id).remove([image_id])
    failed = _upload(client, project_id, request_id)
    assert failed.status_code == 409
    assert store.read(request_id)["upload_request_status"] == "FAILED"
    assert platform_app.material_store(project_id).get(image_id) is not None


def test_same_id_cannot_be_owned_twice_during_an_async_request(tmp_path):
    store = UploadBatchStore(tmp_path)

    async def exercise():
        async with store.claim_upload_request("same-request"):
            with pytest.raises(UploadRequestBusy):
                async with UploadBatchStore(tmp_path).claim_upload_request("same-request"):
                    pytest.fail("concurrent ownership must not be possible")
        async with UploadBatchStore(tmp_path).claim_upload_request("same-request"):
            pass

    asyncio.run(exercise())


def test_annotation_commit_error_does_not_delete_committed_material_bytes(client, monkeypatch):
    project_id = _project(client)
    request_id = "gt-failure-" + uuid.uuid4().hex[:12]

    def abort_annotation_commit(self, *args, **kwargs):
        raise RuntimeError("synthetic annotation sqlite failure")

    with monkeypatch.context() as patch:
        patch.setattr(
            platform_app.AnnotationRepository, "upsert_many", abort_annotation_commit,
        )
        with pytest.raises(RuntimeError, match="已保留源文件"):
            _upload(client, project_id, request_id)

    receipt = platform_app.upload_batch_store(project_id).read(request_id)
    assert receipt["upload_request_status"] == "PROCESSING"
    image_id = receipt["upload_prepared_image_ids"][0]
    material = platform_app.material_store(project_id).get(image_id)
    assert material is not None
    assert platform_app.storage_manager(project_id).materialize(material).path.is_file()
    retry = _upload(client, project_id, request_id)
    assert retry.status_code == 409, retry.text
    assert retry.json()["code"] == "UPLOAD_REQUEST_RECOVERY_UNCONFIRMED"


def test_same_metadata_different_bytes_cannot_replay_upload_receipt(client):
    project_id = _project(client)
    request_id = "content-fence-" + uuid.uuid4().hex[:12]
    original = _image_bytes()
    first = _upload(client, project_id, request_id, original)
    assert first.status_code == 200, first.text
    first_ids = first.json()["uploaded_image_ids"]
    assert len(first_ids) == 1

    # Identical name, MIME and byte length, but distinct content.
    changed = bytearray(original)
    changed[20] ^= 1
    assert len(changed) == len(original)
    conflict = _upload(client, project_id, request_id, bytes(changed))
    assert conflict.status_code == 409, conflict.text
    assert conflict.json()["code"] == "UPLOAD_REQUEST_MANIFEST_MISMATCH"
    assert platform_app.material_store(project_id).count() == 1
    assert platform_app.upload_batch_store(project_id).read(request_id)["upload_request_status"] == "SUCCEEDED"

    replay = _upload(client, project_id, request_id, original)
    assert replay.status_code == 200, replay.text
    assert replay.json()["replayed"] is True
    assert replay.json()["uploaded_image_ids"] == first_ids
    assert platform_app.material_store(project_id).count() == 1
