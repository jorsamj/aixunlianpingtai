import hashlib
import io
from pathlib import Path

from PIL import Image


def _png_bytes(index: int) -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (96, 72), (index % 255, 80, 160)).save(output, format="PNG")
    return output.getvalue()


def test_plain_multi_image_upload_uses_batched_sqlite_truth(client, monkeypatch):
    import app as app_module
    from platform_core.annotation_repository import AnnotationRepository
    from platform_core.material_repository import MaterialRepository

    project_id = client.post(
        "/api/projects", json={"name": "plain-upload-batch", "labels": []}
    ).json()["id"]

    original_storage_manager = app_module.storage_manager
    storage_manager_calls = 0
    original_add_image_record = app_module.add_image_record
    direct_stream_sources = []

    def tracked_add_image_record(project_id, source, *args, **kwargs):
        direct_stream_sources.append(not isinstance(source, (str, Path)))
        return original_add_image_record(project_id, source, *args, **kwargs)

    monkeypatch.setattr(app_module, "add_image_record", tracked_add_image_record)

    def counted_storage_manager(project):
        nonlocal storage_manager_calls
        storage_manager_calls += 1
        return original_storage_manager(project)

    monkeypatch.setattr(app_module, "storage_manager", counted_storage_manager)

    def unexpected_material_upsert(_self, _record):
        raise AssertionError("plain multi-image upload must not commit materials one image at a time")

    def unexpected_annotation_upsert(_self, *args, **kwargs):
        raise AssertionError("new-image annotations must be committed with upsert_many")

    def unexpected_source_rehash(_path):
        raise AssertionError("multipart receive hash must be reused by add_image_record")

    monkeypatch.setattr(MaterialRepository, "upsert", unexpected_material_upsert)
    monkeypatch.setattr(AnnotationRepository, "upsert", unexpected_annotation_upsert)
    monkeypatch.setattr(app_module, "sha256_file", unexpected_source_rehash)

    payloads = [_png_bytes(index) for index in range(12)]
    response = client.post(
        f"/api/projects/{project_id}/images",
        files=[
            ("files", (f"image-{index}.png", payload, "image/png"))
            for index, payload in enumerate(payloads)
        ],
        data={"dataset_id": "default"},
    )
    response.raise_for_status()
    body = response.json()
    assert body["uploaded_count"] == 12, body
    assert body["failed_count"] == 0
    assert storage_manager_calls == 1
    assert direct_stream_sources == [True] * 12
    assert all(item.get("annotation_summary_at") for item in body["uploaded"])
    assert all(item.get("annotation_state") == "unannotated" for item in body["uploaded"])

    materials = MaterialRepository(app_module.project_dir(project_id))
    rows = materials.read().rows
    assert len(rows) == 12
    # One bounded Material identity batch plus one bounded, version-fenced
    # Annotation projection batch; never one transaction per image.
    assert materials.current_revision() == 2
    expected_hashes = {hashlib.sha256(payload).hexdigest() for payload in payloads}
    assert {row["content_sha256"] for row in rows} == expected_hashes

    annotations = AnnotationRepository(app_module.project_dir(project_id)).summary()
    assert annotations["unannotated"] == 12
    assert annotations["total"] == 12


def test_plain_upload_keeps_per_file_failure_isolation(client):
    project_id = client.post(
        "/api/projects", json={"name": "plain-upload-partial", "labels": []}
    ).json()["id"]
    response = client.post(
        f"/api/projects/{project_id}/images",
        files=[
            ("files", ("good.png", _png_bytes(1), "image/png")),
            ("files", ("bad.txt", b"not-an-image", "text/plain")),
            ("files", ("also-good.png", _png_bytes(2), "image/png")),
        ],
        data={"dataset_id": "default"},
    )
    response.raise_for_status()
    body = response.json()
    assert body["uploaded_count"] == 2
    assert body["failed_count"] == 1
    assert body["failed"][0]["name"] == "bad.txt"


def test_plain_upload_request_id_replays_without_duplicate_materials(client):
    import app as app_module
    project_id = client.post("/api/projects", json={"name": "plain-upload-idempotent", "labels": []}).json()["id"]
    request_id = "upload-replay-001"
    payloads = [_png_bytes(21), _png_bytes(22)]
    def send():
        return client.post(
            f"/api/projects/{project_id}/images",
            files=[("files", (f"image-{index}.png", payload, "image/png")) for index, payload in enumerate(payloads)],
            data={"dataset_id": "default", "storage_source_id": "default_local", "upload_request_id": request_id},
        )
    first = send(); first.raise_for_status(); first_body = first.json()
    assert first_body["replayed"] is False
    assert first_body["uploaded_count"] == 2
    second = send(); second.raise_for_status(); second_body = second.json()
    assert second_body["replayed"] is True
    assert second_body["uploaded_image_ids"] == first_body["uploaded_image_ids"]
    assert app_module.material_store(project_id).count() == 2
    receipt = client.get(f"/api/v55/projects/{project_id}/upload-batches/{request_id}")
    receipt.raise_for_status(); receipt_body = receipt.json()
    assert receipt_body["upload_request_status"] == "SUCCEEDED"
    assert [item["image"]["id"] for item in receipt_body["items"]] == first_body["uploaded_image_ids"]


def test_plain_upload_request_id_rejects_manifest_reuse_and_preserves_partial_failure(client):
    import app as app_module
    project_id = client.post("/api/projects", json={"name": "plain-upload-manifest-fence", "labels": []}).json()["id"]
    request_id = "upload-replay-002"
    first = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("good.png", _png_bytes(31), "image/png")), ("files", ("bad.txt", b"not-an-image", "text/plain"))],
        data={"dataset_id": "default", "upload_request_id": request_id},
    )
    first.raise_for_status(); body = first.json()
    assert body["uploaded_count"] == 1
    assert body["failed_count"] == 1
    replay = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("good.png", _png_bytes(31), "image/png")), ("files", ("bad.txt", b"not-an-image", "text/plain"))],
        data={"dataset_id": "default", "upload_request_id": request_id},
    )
    replay.raise_for_status()
    assert replay.json()["failed"] == body["failed"]
    assert app_module.material_store(project_id).count() == 1
    conflict = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", ("different.png", _png_bytes(32), "image/png"))],
        data={"dataset_id": "default", "upload_request_id": request_id},
    )
    assert conflict.status_code == 409
    assert "已用于不同文件" in str(conflict.json().get("detail"))
    assert app_module.material_store(project_id).count() == 1
