import hashlib
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from platform_core import training_tasks


def _dataset(source: Path) -> tuple[list[dict], dict]:
    content_sha256 = hashlib.sha256(source.read_bytes()).hexdigest()
    rows = [
        {
            "id": "image-one",
            "stored_name": source.name,
            "width": 4,
            "height": 4,
            "size_bytes": source.stat().st_size,
            "content_sha256": content_sha256,
            "boxes": [],
        }
    ]
    snapshot = {
        "schema_version": 2,
        "snapshot_id": "snapshot-one",
        "ids": {"train": ["image-one"], "validation": [], "test": []},
        "label_schema": [],
        "images": [
            {
                "image_id": "image-one",
                "role": "train",
                "stored_name": source.name,
                "content_sha256": content_sha256,
            }
        ],
    }
    return rows, snapshot


def _materialize(task_root: Path, source: Path, *, safety_reserve_bytes: int = 0) -> Path:
    rows, snapshot = _dataset(source)
    return training_tasks.materialize_portable_dataset(
        task_root,
        snapshot,
        rows,
        lambda _row: source,
        safety_reserve_bytes=safety_reserve_bytes,
    )


def _same_file(left: Path, right: Path) -> bool:
    return os.path.samefile(left, right)


def test_materialized_image_is_an_independent_copy(tmp_path: Path):
    source = tmp_path / "source.jpg"
    original = b"source-image-bytes"
    source.write_bytes(original)

    bundle = _materialize(tmp_path / "task", source)
    destination = bundle / "dataset" / "images" / "train" / "image-one.jpg"

    assert destination.read_bytes() == original
    assert not _same_file(source, destination)
    destination.write_bytes(b"rewritten-by-training")
    assert source.read_bytes() == original
    assert source.stat().st_size == len(original)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == hashlib.sha256(original).hexdigest()


def test_rematerialization_atomically_repairs_legacy_hardlink(tmp_path: Path):
    source = tmp_path / "source.jpg"
    original = b"immutable-source-image"
    source.write_bytes(original)
    task_root = tmp_path / "task"
    bundle = _materialize(task_root, source)
    destination = bundle / "dataset" / "images" / "train" / "image-one.jpg"
    destination.unlink()
    try:
        os.link(source, destination)
    except OSError as error:
        pytest.skip(f"hardlinks are not supported on this filesystem: {error}")
    assert _same_file(source, destination)

    bundle = _materialize(task_root, source)
    destination = bundle / "dataset" / "images" / "train" / "image-one.jpg"

    assert not _same_file(source, destination)
    destination.write_bytes(b"ultralytics-rewrite")
    assert source.read_bytes() == original
    assert source.stat().st_size == len(original)
    assert hashlib.sha256(source.read_bytes()).hexdigest() == hashlib.sha256(original).hexdigest()


def test_disk_preflight_fails_without_publishing_or_linking(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source-image-bytes")
    monkeypatch.setattr(training_tasks.shutil, "disk_usage", lambda _path: SimpleNamespace(free=0))

    with pytest.raises(OSError, match="Insufficient disk space for training bundle"):
        _materialize(tmp_path / "task", source)

    destination = tmp_path / "task" / "bundle" / "dataset" / "images" / "train" / "image-one.jpg"
    assert not destination.exists()
