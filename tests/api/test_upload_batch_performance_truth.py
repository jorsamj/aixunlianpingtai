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
    assert materials.current_revision() == 1
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
