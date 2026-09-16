import hashlib
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

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


def test_unknown_file_identity_rebuilds_destination(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.jpg"
    destination = tmp_path / "destination.jpg"
    source.write_bytes(b"same-image-bytes")
    destination.write_bytes(source.read_bytes())
    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    replacements = []
    real_replace = os.replace

    monkeypatch.setattr(training_tasks.os.path, "samefile", lambda *_args: (_ for _ in ()).throw(OSError("unknown")))

    def replace(source_path, destination_path):
        replacements.append((Path(source_path), Path(destination_path)))
        real_replace(source_path, destination_path)

    monkeypatch.setattr(training_tasks.os, "replace", replace)
    training_tasks._copy_verified_isolated(source, destination, expected_hash)

    assert len(replacements) == 1
    assert destination.read_bytes() == source.read_bytes()


def test_final_destination_symlink_is_replaced_lexically(tmp_path: Path):
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source-image-bytes")
    task_root = tmp_path / "task"
    bundle = _materialize(task_root, source)
    destination = bundle / "dataset" / "images" / "train" / "image-one.jpg"
    redirected = destination.with_name("redirected.jpg")
    redirected.write_bytes(source.read_bytes())
    destination.unlink()
    try:
        destination.symlink_to(redirected.name)
    except OSError as error:
        pytest.skip(f"symlinks are not supported on this filesystem: {error}")

    _materialize(task_root, source)

    assert not destination.is_symlink()
    assert destination.read_bytes() == source.read_bytes()
    assert redirected.read_bytes() == source.read_bytes()


def test_cleanup_refuses_linked_bundle_root_and_preserves_active_copy(tmp_path: Path):
    external = tmp_path / "external"
    external.mkdir()
    protected = external / f".training-bundle-copy.{os.getpid()}.active.copy"
    protected.write_bytes(b"active")
    os.utime(protected, (time.time() - 172800, time.time() - 172800))
    task_root = tmp_path / "task"
    task_root.mkdir()
    try:
        (task_root / "bundle").symlink_to(external, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"directory symlinks are not supported on this filesystem: {error}")
    source = tmp_path / "source.jpg"
    source.write_bytes(b"source-image-bytes")

    with pytest.raises(ValueError, match="bundle.*link|real bundle"):
        _materialize(task_root, source)

    assert protected.read_bytes() == b"active"


def test_process_liveness_probe_never_sends_os_signal(monkeypatch: pytest.MonkeyPatch):
    observed: list[int] = []

    monkeypatch.setattr(
        training_tasks.psutil,
        "pid_exists",
        lambda process_id: observed.append(int(process_id)) or True,
    )
    monkeypatch.setattr(
        training_tasks.os,
        "kill",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("process liveness probe must never signal a process")
        ),
    )

    assert training_tasks._process_is_running(43210) is True
    assert observed == [43210]
    assert training_tasks._process_is_running(0) is False
    assert observed == [43210]


def test_cleanup_requires_work_boundary_and_keeps_live_owner_copy(tmp_path: Path):
    work = tmp_path / "work"
    bundle = work / "bundle"
    bundle.mkdir(parents=True)
    active = bundle / f".training-bundle-copy.{os.getpid()}.active.copy"
    active.write_bytes(b"active")
    old = time.time() - 172800
    os.utime(active, (old, old))
    storage_source = tmp_path / "storage-source"
    storage_source.mkdir()
    protected = storage_source / ".training-bundle-copy.999999.orphan.copy"
    protected.write_bytes(b"source")
    os.utime(protected, (old, old))

    with pytest.raises(ValueError, match="work boundary"):
        training_tasks._cleanup_orphan_bundle_copies(storage_source, expected_work=work, now=time.time())
    training_tasks._cleanup_orphan_bundle_copies(bundle, expected_work=work, now=time.time())

    assert protected.read_bytes() == b"source"
    assert active.read_bytes() == b"active"


def test_copy_verification_compares_exact_source_size(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    source = tmp_path / "source.jpg"
    destination = tmp_path / "destination.jpg"
    source.write_bytes(b"complete-source-image")
    expected_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    monkeypatch.setattr(training_tasks, "_sha256", lambda _path: expected_hash)
    monkeypatch.setattr(
        training_tasks.shutil,
        "copyfileobj",
        lambda _input, output, length: output.write(b"truncated"),
    )

    with pytest.raises(OSError, match="size verification failed"):
        training_tasks._copy_verified_isolated(source, destination, expected_hash)

    assert not destination.exists()

def test_missing_jpeg_eoi_is_normalized_before_ultralytics_without_mutating_source(tmp_path: Path):
    source = tmp_path / "WEB07552.jpg"
    Image.new("RGB", (8, 8), (120, 30, 10)).save(source, format="JPEG")
    valid = source.read_bytes()
    assert valid[:2] == b"\xff\xd8"
    assert valid[-2:] == b"\xff\xd9"
    broken = valid[:-2] + b"t\n"
    source.write_bytes(broken)
    source_sha = hashlib.sha256(broken).hexdigest()
    source_size = len(broken)

    bundle = _materialize(tmp_path / "task-jpeg-repair", source)
    destination = bundle / "dataset/images/train/image-one.jpg"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    member = manifest["splits"]["train"][0]

    assert source.read_bytes() == broken
    assert source.stat().st_size == source_size
    assert hashlib.sha256(source.read_bytes()).hexdigest() == source_sha
    assert destination.read_bytes()[-2:] == b"\xff\xd9"
    assert member["source_content_sha256"] == source_sha
    assert member["source_size_bytes"] == source_size
    assert member["content_sha256"] == hashlib.sha256(destination.read_bytes()).hexdigest()
    assert member["size_bytes"] == destination.stat().st_size
    assert member["normalized"] is True
    assert member["normalization_reason"] == "jpeg_missing_eoi"
    assert member["training_input_policy"] == "ultralytics_jpeg_repair_v1"
    assert manifest["training_input_policy"] == "ultralytics_jpeg_repair_v1"
    assert training_tasks.verify_portable_dataset(bundle / "manifest.json")["verified_files"] == 1


def test_standard_jpeg_keeps_exact_training_bytes(tmp_path: Path):
    source = tmp_path / "normal.jpg"
    Image.new("RGB", (8, 8), (20, 40, 60)).save(source, format="JPEG")
    original = source.read_bytes()
    bundle = _materialize(tmp_path / "task-jpeg-normal", source)
    destination = bundle / "dataset/images/train/image-one.jpg"
    manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
    member = manifest["splits"]["train"][0]

    assert destination.read_bytes() == original
    assert member["source_content_sha256"] == member["content_sha256"]
    assert member["source_size_bytes"] == member["size_bytes"]
    assert member["normalized"] is False
    assert member["normalization_reason"] is None


def test_jpg_extension_without_jpeg_magic_remains_format_neutral(tmp_path: Path):
    source = tmp_path / "opaque.jpg"
    original = b"opaque-test-payload"
    source.write_bytes(original)
    bundle = _materialize(tmp_path / "task-opaque", source)
    destination = bundle / "dataset/images/train/image-one.jpg"
    assert destination.read_bytes() == original


def test_training_bundle_mutation_error_reports_image_id_and_expected_actual_sha(tmp_path: Path):
    source = tmp_path / "normal-error.jpg"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(source, format="JPEG")
    bundle = _materialize(tmp_path / "task-jpeg-error", source)
    destination = bundle / "dataset/images/train/image-one.jpg"
    destination.write_bytes(b"mutated-after-materialization")

    with pytest.raises(ValueError) as error:
        training_tasks.verify_portable_dataset(bundle / "manifest.json")
    message = str(error.value)
    assert "TRAINING_BUNDLE_IMAGE_MUTATED" in message
    assert "image_id=image-one" in message
    assert "expected_training_sha256=" in message
    assert "actual_sha256=" in message
