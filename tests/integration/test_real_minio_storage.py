from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path

import pytest
import requests

from platform_core.material_repository import MaterialRepository
from platform_core.secrets import MemorySecretStore, SecretCredentialStore
from platform_core.storage import StorageManager, StorageSourceRepository
from platform_core.training_tasks import materialize_portable_dataset


pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL_MINIO") != "1",
    reason="set RUN_REAL_MINIO=1 with an actual S3-compatible endpoint",
)


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _image_bytes(color: tuple[int, int, int]) -> bytes:
    from PIL import Image

    stream = io.BytesIO()
    Image.new("RGB", (32, 24), color).save(stream, format="JPEG")
    return stream.getvalue()


def test_real_minio_upload_preview_cache_and_mixed_training_bundle(tmp_path: Path) -> None:
    import boto3

    endpoint = os.environ["MINIO_ENDPOINT"]
    access_key = os.environ["MINIO_ACCESS_KEY"]
    secret_key = os.environ["MINIO_SECRET_KEY"]
    bucket = os.environ.get("MINIO_BUCKET", "materials")
    client = boto3.client(
        "s3",
        endpoint_url=endpoint,
        region_name="us-east-1",
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )
    try:
        client.create_bucket(Bucket=bucket)
    except client.exceptions.BucketAlreadyOwnedByYou:
        pass

    data_dir = tmp_path / "data"
    project_dir = data_dir / "projects" / "p1"
    materials = MaterialRepository(project_dir)
    sources = StorageSourceRepository(data_dir / "storage" / "storage_sources.sqlite3")
    secret_backend = MemorySecretStore()
    credentials = SecretCredentialStore(secret_backend)
    source = sources.create(
        {
            "id": "minio_acceptance",
            "name": "MinIO acceptance",
            "type": "s3",
            "config": {
                "endpoint": endpoint,
                "region": "us-east-1",
                "bucket": bucket,
                "prefix": "acceptance",
                "use_ssl": False,
            },
            "secret_ref": "xjalgo:storage-source:minio_acceptance",
        }
    )
    credentials.set(
        source.secret_ref,
        {"access_key_id": access_key, "secret_access_key": secret_key},
    )
    manager = StorageManager(
        data_dir=data_dir,
        project_id="p1",
        materials=materials,
        sources=sources,
        credentials=credentials,
    )
    provider = manager.provider_for(source.id)
    assert provider.health_check().ok is True

    remote_bytes = _image_bytes((220, 80, 20))
    remote_hash = _sha256(remote_bytes)
    remote_meta = provider.upload(
        "fire/remote.jpg",
        io.BytesIO(remote_bytes),
        content_type="image/jpeg",
        metadata={"sha256": remote_hash},
    )
    assert remote_meta.size_bytes == len(remote_bytes)
    assert provider.exists("fire/remote.jpg") is True
    assert [item.key for item in provider.list_objects("fire").items] == ["fire/remote.jpg"]
    preview_url = provider.generate_preview_url("fire/remote.jpg", expires_seconds=60)
    response = requests.get(preview_url, timeout=10)
    response.raise_for_status()
    assert response.content == remote_bytes

    local_bytes = _image_bytes((20, 100, 220))
    local_hash = _sha256(local_bytes)
    local_path = project_dir / "uploads" / "local.jpg"
    local_path.parent.mkdir(parents=True, exist_ok=True)
    local_path.write_bytes(local_bytes)
    rows = [
        {
            "id": "local-1",
            "filename": "local.jpg",
            "stored_name": "local.jpg",
            "storage_source_id": "default_local",
            "storage_type": "local",
            "object_key": "uploads/local.jpg",
            "content_sha256": local_hash,
            "size_bytes": len(local_bytes),
            "width": 32,
            "height": 24,
            "labels": ["fire"],
            "boxes": [{"label": "fire", "x1": 2, "y1": 2, "x2": 20, "y2": 18}],
        },
        {
            "id": "remote-1",
            "filename": "remote.jpg",
            "storage_source_id": source.id,
            "storage_type": "s3",
            "object_key": "fire/remote.jpg",
            "content_sha256": remote_hash,
            "size_bytes": len(remote_bytes),
            "etag": remote_meta.etag,
            "width": 32,
            "height": 24,
            "labels": ["fire"],
            "boxes": [{"label": "fire", "x1": 4, "y1": 3, "x2": 24, "y2": 20}],
        },
    ]
    materials.upsert_many(rows)

    first = manager.materialize("remote-1")
    second = manager.materialize("remote-1")
    assert first.cache_hit is False
    assert second.cache_hit is True
    assert first.path.read_bytes() == remote_bytes
    assert data_dir / "cache" / "materials" in first.path.parents
    assert not (project_dir / "uploads" / "remote.jpg").exists()

    snapshot = {
        "snapshot_id": "mixed-storage-snapshot",
        "label_schema": [{"code": "fire", "class_id": 0}],
        "ids": {"train": ["local-1"], "validation": [], "test": ["remote-1"]},
        "images": [
            {"image_id": "local-1", "content_sha256": local_hash},
            {"image_id": "remote-1", "content_sha256": remote_hash},
        ],
    }
    bundle = materialize_portable_dataset(
        tmp_path / "training-task",
        snapshot,
        rows,
        lambda row: manager.materialize(row).path,
    )
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    assert [item["image_id"] for item in manifest["splits"]["train"]] == ["local-1"]
    assert [item["image_id"] for item in manifest["splits"]["test"]] == ["remote-1"]
    assert (bundle / "dataset" / "images" / "train" / "local-1.jpg").is_file()
    assert (bundle / "dataset" / "images" / "test" / "remote-1.jpg").is_file()

    materials.remove(["remote-1"])
    assert materials.get("remote-1") is None
    assert provider.exists("fire/remote.jpg") is True

    provider.delete("fire/remote.jpg")
    assert provider.exists("fire/remote.jpg") is False
