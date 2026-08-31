import hashlib
import json
import shutil

import pytest

from platform_core.training_tasks import resolve_remote_training_bundle


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _seed_portable_bundle(root):
    (root / "dataset" / "images" / "train").mkdir(parents=True)
    (root / "dataset" / "labels" / "train").mkdir(parents=True)
    image = root / "dataset" / "images" / "train" / "a image.jpg"
    label = root / "dataset" / "labels" / "train" / "a image.txt"
    yaml_path = root / "dataset" / "data.yaml"
    snapshot = root / "snapshot.json"
    image.write_bytes(b"real-image-bytes")
    label.write_text("0 0.5 0.5 0.2 0.2", encoding="utf-8")
    yaml_path.write_text("path: .\ntrain: images/train\nval: images/train\ntest: images/train\nnames: {0: object}\n", encoding="utf-8")
    snapshot.write_text(json.dumps({"snapshot_id": "snap-one"}), encoding="utf-8")
    manifest = {
        "schema_version": 2,
        "snapshot_id": "snap-one",
        "snapshot_ref": "snapshot.json",
        "snapshot_sha256": _sha256(snapshot),
        "data_yaml_ref": "dataset/data.yaml",
        "splits": {
            "train": [{
                "image_id": "a",
                "image_ref": "dataset/images/train/a image.jpg",
                "label_ref": "dataset/labels/train/a image.txt",
                "content_sha256": _sha256(image),
                "label_sha256": _sha256(label),
            }],
            "validation": [],
            "test": [],
        },
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return manifest


def test_remote_bundle_rebases_only_relative_manifest_refs(tmp_path):
    source = tmp_path / "source bundle"
    source.mkdir()
    manifest = _seed_portable_bundle(source)
    received = tmp_path / "received on linux worker"
    shutil.copytree(source, received)

    resolved = resolve_remote_training_bundle(received / "manifest.json")

    assert resolved.data_yaml == received / "dataset" / "data.yaml"
    assert resolved.snapshot == received / "snapshot.json"
    references = [manifest["data_yaml_ref"], manifest["snapshot_ref"]]
    references += [member[key] for rows in manifest["splits"].values() for member in rows for key in ("image_ref", "label_ref")]
    assert not any(":" in ref or ref.startswith(("/", "\\")) for ref in references)


def test_remote_bundle_rejects_tampered_content(tmp_path):
    root = tmp_path / "bundle"
    root.mkdir()
    _seed_portable_bundle(root)
    (root / "dataset" / "images" / "train" / "a image.jpg").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="SHA256"):
        resolve_remote_training_bundle(root / "manifest.json")
