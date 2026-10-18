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
    assert "test" not in data
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    test_member = manifest["splits"]["test"][0]
    assert test_member["image_ref"] == "dataset/images/test/image-3.jpg"
    assert test_member["label_ref"] == "evaluation/ground_truth/test/image-3.txt"
    assert (bundle / test_member["label_ref"]).is_file()
    assert not (bundle / "dataset" / "labels" / "test").exists()
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


def test_real_materialized_test_bytes_bind_to_immutable_snapshot_and_hidden_gt(tmp_path: Path):
    """Not just a synthetic digest: verify the exact created image/GT files."""
    from platform_core.training_evaluation import (
        build_evaluation_benchmark_scope, build_evaluation_truth,
    )

    project, rows, snapshot = _source(tmp_path)
    snapshot["schema_version"] = 3
    snapshot["snapshot_id"] = "f" * 64
    for row in snapshot["images"]:
        row["annotation_hash"] = hashlib.sha256(
            ("formal:" + row["image_id"]).encode()
        ).hexdigest()
        row["annotation_state"] = "annotated"
    bundle = materialize_portable_dataset(
        tmp_path / "strict-test",
        snapshot, rows, lambda row: project / "uploads" / row["stored_name"],
    )
    path = bundle / "manifest.json"
    assert verify_portable_dataset(path)["verified_files"] == 4
    manifest = json.loads(path.read_text(encoding="utf-8"))
    strict = build_evaluation_benchmark_scope(
        json.loads((bundle / "snapshot.json").read_text(encoding="utf-8")),
        manifest,
    )
    assert strict["binding_level"] == "bundle_verified"
    assert strict["test_image_count"] == 1
    assert len(strict["evaluation_input_digest"]) == 64
    assert "test" not in yaml.safe_load(
        (bundle / "dataset" / "data.yaml").read_text(encoding="utf-8")
    )
    frozen = build_evaluation_truth(
        {"status": "succeeded", "image_count": 1,
         "metrics": {"metrics/mAP50(B)": 0.97}},
        task_id="strict-verified-bundle",
        benchmark_scope=strict,
    )
    assert frozen["benchmark_scope"]["scope_id"] == strict["scope_id"]
    assert frozen["benchmark_scope"]["binding_level"] == "bundle_verified"

    # The post-training verifier protects the hidden GT bytes, not only images.
    test = manifest["splits"]["test"][0]
    gt_file = bundle / test["label_ref"]
    gt_file.write_text("0 0.0 0.0 1.0 1.0", encoding="utf-8")
    with pytest.raises(ValueError, match="label SHA256"):
        verify_portable_dataset(path)
    assert (project / "uploads" / "image-3.jpg").is_file()


def test_mutated_test_image_fails_before_strict_binding_can_be_claimed(tmp_path: Path):
    project, rows, snapshot = _source(tmp_path)
    snapshot["schema_version"] = 3
    snapshot["snapshot_id"] = "e" * 64
    for row in snapshot["images"]:
        row["annotation_hash"] = "a" * 64
        row["annotation_state"] = "annotated"
    bundle = materialize_portable_dataset(
        tmp_path / "tampered-test",
        snapshot, rows, lambda row: project / "uploads" / row["stored_name"],
    )
    manifest_path = bundle / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    test_ref = manifest["splits"]["test"][0]["image_ref"]
    (bundle / test_ref).write_bytes(b"tampered independent Test image")
    with pytest.raises(ValueError, match="TRAINING_BUNDLE_IMAGE_MUTATED"):
        verify_portable_dataset(manifest_path)
