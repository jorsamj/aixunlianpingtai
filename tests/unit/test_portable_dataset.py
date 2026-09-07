import hashlib
import json
import shutil
from pathlib import Path

import pytest
import yaml
from PIL import Image

from platform_core.training_tasks import (
    materialize_portable_dataset,
    resolve_dataset_yaml,
    resolve_remote_training_bundle,
    verify_portable_dataset,
)


def _source(tmp_path: Path):
    project = tmp_path / "project"
    uploads = project / "uploads"
    uploads.mkdir(parents=True)
    rows = []
    ids = {"train": [], "validation": [], "test": []}
    for index, role in enumerate(("train", "train", "validation", "test")):
        image_id = f"image-{index}"
        stored_name = f"{image_id}.jpg"
        path = uploads / stored_name
        Image.new("RGB", (40, 20), (index * 20, 10, 10)).save(path, format="JPEG")
        content_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        ids[role].append(image_id)
        rows.append(
            {
                "id": image_id,
                "stored_name": stored_name,
                "width": 40,
                "height": 20,
                "content_sha256": content_hash,
                "boxes": [{"label": "fire", "x1": 4, "y1": 2, "x2": 20, "y2": 10}],
            }
        )
    snapshot = {
        "schema_version": 2,
        "snapshot_id": "snapshot-one",
        "ids": ids,
        "label_schema": [{"code": "fire", "class_id": 0}],
        "images": [
            {
                "image_id": row["id"],
                "role": next(role for role, values in ids.items() if row["id"] in values),
                "stored_name": row["stored_name"],
                "content_sha256": row["content_sha256"],
            }
            for row in rows
        ],
    }
    return project, rows, snapshot


def test_materialized_yaml_is_relative_verified_and_relocatable(tmp_path: Path):
    project, rows, snapshot = _source(tmp_path)
    requested = []

    def materialize(row):
        requested.append(row["id"])
        return project / "uploads" / row["stored_name"]

    bundle = materialize_portable_dataset(tmp_path / "task", snapshot, rows, materialize)
    assert requested == ["image-0", "image-1", "image-2", "image-3"]
    data = yaml.safe_load((bundle / "dataset" / "data.yaml").read_text(encoding="utf-8"))
    assert data["path"] == "."
    assert data["train"] == "images/train"
    assert data["val"] == "images/validation"
    assert data["test"] == "images/test"
    assert verify_portable_dataset(bundle / "manifest.json")["verified_files"] == 4

    moved = tmp_path / "linux-received"
    shutil.move(str(bundle), moved)
    assert resolve_dataset_yaml(moved / "manifest.json") == moved / "dataset" / "data.yaml"
    assert verify_portable_dataset(moved / "manifest.json")["verified_files"] == 4
    remote = resolve_remote_training_bundle(moved / "manifest.json")
    assert remote.snapshot == moved / "snapshot.json"
    assert remote.snapshot_id == "snapshot-one"


def test_verifier_rejects_tampered_image(tmp_path: Path):
    project, rows, snapshot = _source(tmp_path)
    bundle = materialize_portable_dataset(
        tmp_path / "task",
        snapshot,
        rows,
        lambda row: project / "uploads" / row["stored_name"],
    )
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    member = manifest["splits"]["train"][0]
    (bundle / member["image_ref"]).write_bytes(b"tampered")
    with pytest.raises(ValueError, match="SHA256"):
        verify_portable_dataset(bundle / "manifest.json")


def test_manifest_resolver_rejects_path_traversal(tmp_path: Path):
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"data_yaml_ref": "../outside.yaml", "splits": {}}), encoding="utf-8")
    with pytest.raises(ValueError, match="relative"):
        resolve_dataset_yaml(manifest)
