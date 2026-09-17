from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest
from PIL import Image

from platform_core import training_tasks
from platform_core.training_bundle_cache import TrainingBundleCache


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dataset(sources: dict[str, Path], snapshot_id: str) -> tuple[list[dict], dict]:
    rows = []
    images = []
    train_ids = []
    for image_id, source in sources.items():
        digest = _sha256(source)
        rows.append(
            {
                "id": image_id,
                "stored_name": source.name,
                "width": 8,
                "height": 8,
                "size_bytes": source.stat().st_size,
                "content_sha256": digest,
                "boxes": [],
            }
        )
        images.append(
            {
                "image_id": image_id,
                "role": "train",
                "stored_name": source.name,
                "content_sha256": digest,
            }
        )
        train_ids.append(image_id)
    snapshot = {
        "schema_version": 2,
        "snapshot_id": snapshot_id,
        "ids": {"train": train_ids, "validation": [], "test": []},
        "label_schema": [],
        "images": images,
    }
    return rows, snapshot


def _materialize(task_root: Path, sources: dict[str, Path], snapshot_id: str) -> Path:
    rows, snapshot = _dataset(sources, snapshot_id)
    return training_tasks.materialize_portable_dataset(
        task_root,
        snapshot,
        rows,
        lambda row: sources[str(row["id"])],
        safety_reserve_bytes=0,
    )


def test_mixed_jpeg_normalization_cache_restore_and_trainer_mutation_are_isolated(tmp_path: Path):
    valid_source = tmp_path / "valid.jpg"
    repair_source = tmp_path / "repair.jpg"
    Image.new("RGB", (8, 8), (20, 40, 60)).save(valid_source, format="JPEG")
    Image.new("RGB", (8, 8), (120, 30, 10)).save(repair_source, format="JPEG")

    valid_original = valid_source.read_bytes()
    repair_valid = repair_source.read_bytes()
    assert repair_valid[-2:] == b"\xff\xd9"
    repair_broken = repair_valid[:-2] + b"t\n"
    repair_source.write_bytes(repair_broken)

    source_hashes = {
        "valid": hashlib.sha256(valid_original).hexdigest(),
        "repair": hashlib.sha256(repair_broken).hexdigest(),
    }
    snapshot_id = "a" * 64
    bundle = _materialize(
        tmp_path / "first-task",
        {"valid": valid_source, "repair": repair_source},
        snapshot_id,
    )

    assert valid_source.read_bytes() == valid_original
    assert repair_source.read_bytes() == repair_broken
    assert _sha256(valid_source) == source_hashes["valid"]
    assert _sha256(repair_source) == source_hashes["repair"]

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    members = {
        member["image_id"]: member
        for member in manifest["splits"]["train"]
    }
    assert members["valid"]["normalized"] is False
    assert members["valid"]["source_content_sha256"] == members["valid"]["content_sha256"]
    assert members["repair"]["normalized"] is True
    assert members["repair"]["normalization_reason"] == "jpeg_missing_eoi"
    assert members["repair"]["source_content_sha256"] == source_hashes["repair"]
    assert members["repair"]["content_sha256"] != source_hashes["repair"]
    assert manifest["training_input_policy"] == training_tasks.TRAINING_INPUT_POLICY

    verified = training_tasks.verify_portable_dataset(bundle / "manifest.json")
    assert verified["verified_files"] == 2

    cache = TrainingBundleCache(
        tmp_path / "platform-data",
        "project-integrity",
        max_bytes=0,
        ttl_seconds=0,
    )
    entry, published = cache.publish_verified(
        bundle,
        snapshot_id,
        verified_files=verified["verified_files"],
    )
    assert published["published"] is True

    repaired_ref = members["repair"]["image_ref"]
    cache_repaired = entry.bundle / repaired_ref
    cache_repaired_sha = _sha256(cache_repaired)

    resolved = cache.resolve(snapshot_id)
    assert resolved is not None
    restored, stats = cache.restore(resolved, tmp_path / "second-task")
    restored_repaired = restored / repaired_ref
    assert stats["hardlinked_images"] == 0
    assert stats["copied_images"] == 2
    assert not os.path.samefile(cache_repaired, restored_repaired)
    assert _sha256(restored_repaired) == cache_repaired_sha

    restored_repaired.write_bytes(b"simulated-ultralytics-rewrite")
    assert _sha256(cache_repaired) == cache_repaired_sha
    assert repair_source.read_bytes() == repair_broken

    with pytest.raises(ValueError) as error:
        training_tasks.verify_portable_dataset(restored / "manifest.json")
    message = str(error.value)
    assert "TRAINING_BUNDLE_IMAGE_MUTATED" in message
    assert "image_id=repair" in message


def test_unrepairable_jpeg_fails_before_cache_publication_and_preserves_source(tmp_path: Path):
    source = tmp_path / "broken.jpg"
    original = b"\xff\xd8not-a-decodable-jpeg-payload"
    source.write_bytes(original)
    snapshot_id = "b" * 64

    with pytest.raises(ValueError, match="TRAINING_IMAGE_INVALID"):
        _materialize(
            tmp_path / "invalid-task",
            {"broken": source},
            snapshot_id,
        )

    assert source.read_bytes() == original
    assert _sha256(source) == hashlib.sha256(original).hexdigest()
    cache = TrainingBundleCache(
        tmp_path / "platform-data-invalid",
        "project-integrity",
        max_bytes=0,
        ttl_seconds=0,
    )
    assert cache.resolve(snapshot_id) is None
