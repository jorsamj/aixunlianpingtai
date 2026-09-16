from pathlib import Path
from textwrap import dedent

POLICY = "ultralytics_jpeg_repair_v1"


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"patch anchor missing in {target}: {old[:120]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def replace_between(path: str, start_marker: str, end_marker: str, replacement: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    start = text.index(start_marker)
    end = text.index(end_marker, start)
    target.write_text(text[:start] + dedent(replacement).rstrip() + text[end:], encoding="utf-8")


def append_once(path: str, marker: str, addition: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if marker in text:
        return
    target.write_text(text.rstrip() + "\n\n" + dedent(addition).strip() + "\n", encoding="utf-8")


# Runtime: keep source bytes immutable; normalize only task-local real JPEGs missing EOI.
replace_once(
    "platform_core/training_tasks.py",
    "import tempfile\nimport time\nimport uuid\n",
    "import tempfile\nimport threading\nimport time\nimport uuid\n",
)
replace_once(
    "platform_core/training_tasks.py",
    "import yaml\n\nfrom .annotations import atomic_write_json",
    "import yaml\nfrom PIL import Image, ImageFile, ImageOps, UnidentifiedImageError\n\nfrom .annotations import atomic_write_json",
)
replace_once(
    "platform_core/training_tasks.py",
    "TRAINING_COMPLETION_GRACE_SECONDS = 5.0\n_SUCCESSFUL_TRAINING_OUTCOMES = {",
    f'TRAINING_COMPLETION_GRACE_SECONDS = 5.0\nTRAINING_INPUT_POLICY = "{POLICY}"\n_JPEG_SUFFIXES = {{".jpg", ".jpeg", ".jpe", ".jfif"}}\n_JPEG_NORMALIZATION_LOCK = threading.Lock()\n_SUCCESSFUL_TRAINING_OUTCOMES = {{',
)
normalizer = dedent(r'''

def _normalize_training_image(
    destination: Path,
    source_content_sha256: str,
    source_size_bytes: int,
) -> dict[str, Any]:
    """Normalize a task-local JPEG trainer input without rewriting source material."""
    identity = {
        "source_content_sha256": str(source_content_sha256),
        "source_size_bytes": int(source_size_bytes),
        "training_content_sha256": str(source_content_sha256),
        "training_size_bytes": int(source_size_bytes),
        "training_input_policy": TRAINING_INPUT_POLICY,
        "normalized": False,
        "normalization_reason": None,
    }
    if destination.suffix.lower() not in _JPEG_SUFFIXES:
        return identity
    current_size = destination.stat().st_size
    if current_size < 2:
        raise ValueError(
            f"TRAINING_IMAGE_INVALID: filename={destination.name}; reason=jpeg_too_small"
        )
    with destination.open("rb") as stream:
        jpeg_soi = stream.read(2)
        stream.seek(-2, os.SEEK_END)
        jpeg_eoi = stream.read(2)
    # Extension alone is not proof of JPEG bytes. Keep opaque content format-neutral.
    if jpeg_soi != b"\xff\xd8":
        return identity
    if jpeg_eoi == b"\xff\xd9":
        return identity

    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.normalize.tmp"
    )
    try:
        try:
            # This Pillow switch is process-global, so serialize the narrow repair
            # window and restore the previous value immediately afterwards.
            with _JPEG_NORMALIZATION_LOCK:
                previous_truncated = ImageFile.LOAD_TRUNCATED_IMAGES
                ImageFile.LOAD_TRUNCATED_IMAGES = True
                try:
                    with Image.open(destination) as image:
                        repaired = ImageOps.exif_transpose(image)
                        try:
                            repaired.save(
                                temporary,
                                format="JPEG",
                                subsampling=0,
                                quality=100,
                            )
                        finally:
                            if repaired is not image:
                                repaired.close()
                finally:
                    ImageFile.LOAD_TRUNCATED_IMAGES = previous_truncated
        except (OSError, UnidentifiedImageError) as error:
            raise ValueError(
                f"TRAINING_IMAGE_INVALID: filename={destination.name}; "
                f"reason=jpeg_missing_eoi_repair_failed; detail={error}"
            ) from error
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise ValueError(
                f"TRAINING_IMAGE_INVALID: filename={destination.name}; "
                "reason=jpeg_repair_empty_output"
            )
        with temporary.open("rb") as stream:
            stream.seek(-2, os.SEEK_END)
            if stream.read(2) != b"\xff\xd9":
                raise ValueError(
                    f"TRAINING_IMAGE_INVALID: filename={destination.name}; "
                    "reason=jpeg_repair_missing_eoi"
                )
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    identity.update(
        training_content_sha256=_sha256(destination),
        training_size_bytes=destination.stat().st_size,
        normalized=True,
        normalization_reason="jpeg_missing_eoi",
    )
    return identity
''')
replace_once(
    "platform_core/training_tasks.py",
    "\n\ndef _process_is_running(process_id: int) -> bool:",
    normalizer + "\ndef _process_is_running(process_id: int) -> bool:",
)
replace_once(
    "platform_core/training_tasks.py",
    "    remaining_bytes = total_size_bytes\n    total_items = len(planned)\n",
    "    remaining_bytes = total_size_bytes\n    training_total_size_bytes = 0\n    total_items = len(planned)\n",
)
replace_once(
    "platform_core/training_tasks.py",
    "        _copy_verified_isolated(\n            source_path, destination, expected_hash, bundle_root=root, durable=False\n        )\n        remaining_bytes -= size_bytes\n        lines = []\n",
    "        _copy_verified_isolated(\n            source_path, destination, expected_hash, bundle_root=root, durable=False\n        )\n        image_identity = _normalize_training_image(\n            destination, expected_hash, size_bytes\n        )\n        training_hash = str(image_identity[\"training_content_sha256\"])\n        training_size_bytes = int(image_identity[\"training_size_bytes\"])\n        training_total_size_bytes += training_size_bytes\n        remaining_bytes -= size_bytes\n        lines = []\n",
)
replace_once(
    "platform_core/training_tasks.py",
    '                "content_sha256": expected_hash,\n                "size_bytes": size_bytes,\n                "label_sha256": _sha256(label_path),\n',
    '                "source_content_sha256": expected_hash,\n                "source_size_bytes": size_bytes,\n                "content_sha256": training_hash,\n                "size_bytes": training_size_bytes,\n                "training_input_policy": TRAINING_INPUT_POLICY,\n                "normalized": bool(image_identity["normalized"]),\n                "normalization_reason": image_identity["normalization_reason"],\n                "label_sha256": _sha256(label_path),\n',
)
replace_once(
    "platform_core/training_tasks.py",
    '        "schema_version": 2,\n        "snapshot_id": str(snapshot.get("snapshot_id") or ""),\n',
    '        "schema_version": 3,\n        "snapshot_id": str(snapshot.get("snapshot_id") or ""),\n        "training_input_policy": TRAINING_INPUT_POLICY,\n',
)
replace_once(
    "platform_core/training_tasks.py",
    '        "total_size_bytes": total_size_bytes,\n',
    '        "total_size_bytes": training_total_size_bytes,\n',
)
replace_once(
    "platform_core/training_tasks.py",
    '            "image_integrity": "sha256_verified_during_materialization",\n',
    '            "image_integrity": "source_sha256_verified_then_training_input_normalized",\n            "training_input_policy": TRAINING_INPUT_POLICY,\n',
)
replace_once(
    "platform_core/training_tasks.py",
    '            if not image_path.is_file() or _sha256(image_path) != str(member.get("content_sha256") or ""):\n                raise ValueError(f"portable image SHA256 mismatch: {member.get(\'image_id\')}")\n',
    '            expected_training_sha = str(member.get("content_sha256") or "")\n            actual_training_sha = _sha256(image_path) if image_path.is_file() else ""\n            if not image_path.is_file() or actual_training_sha != expected_training_sha:\n                raise ValueError(\n                    "TRAINING_BUNDLE_IMAGE_MUTATED: portable image SHA256 mismatch; "\n                    f"image_id={member.get(\'image_id\')}; "\n                    f"expected_training_sha256={expected_training_sha or \'<missing>\'}; "\n                    f"actual_sha256={actual_training_sha or \'<missing>\'}; "\n                    f"source_sha256={member.get(\'source_content_sha256\') or expected_training_sha or \'<missing>\'}; "\n                    f"normalization_policy={member.get(\'training_input_policy\') or manifest.get(\'training_input_policy\') or \'<missing>\'}"\n                )\n',
)

# Snapshot identity locks the trainer-input compatibility policy.
replace_once(
    "platform_core/snapshots.py",
    "from .training_splits import SplitManifest\n\n\ndef _canonical",
    f'from .training_splits import SplitManifest\n\n\nTRAINING_INPUT_POLICY = "{POLICY}"\n\n\ndef _canonical',
)
replace_once(
    "platform_core/snapshots.py",
    '    payload = {\n        "seed": int(seed),\n        "train_image_ids": train_ids,\n',
    '    payload = {\n        "seed": int(seed),\n        "training_input_policy": TRAINING_INPUT_POLICY,\n        "train_image_ids": train_ids,\n',
)
replace_once(
    "platform_core/snapshots.py",
    '    payload = {\n        "schema_version": 3,\n        "mode": manifest.mode.value,\n',
    '    payload = {\n        "schema_version": 3,\n        "training_input_policy": TRAINING_INPUT_POLICY,\n        "mode": manifest.mode.value,\n',
)

# Cache v2 may contain writable hardlinks. Reject it; v3 restores task-local copies only.
replace_once(
    "platform_core/training_bundle_cache.py",
    "CACHE_SCHEMA_VERSION = 2",
    "CACHE_SCHEMA_VERSION = 3",
)
replace_once(
    "platform_core/training_bundle_cache.py",
    dedent('''
            try:
                os.link(source_image, destination_image)
                hardlinked_images += 1
                hardlinked_image_bytes += expected_size
            except OSError:
                shutil.copy2(source_image, destination_image)
                copied_images += 1
                copied_image_bytes += expected_size
    ''').lstrip(),
    dedent('''
            # Trainer work is writable. Never share a cache inode with a task.
            # A future reflink/CoW optimization is safe only if writes remain isolated.
            shutil.copy2(source_image, destination_image)
            copied_images += 1
            copied_image_bytes += expected_size
    ''').lstrip(),
)

replace_between(
    "tests/unit/test_training_bundle_cache.py",
    "def test_verified_bundle_cache_publishes_and_restores_with_image_hardlinks",
    "\n\ndef test_cache_resolve_rejects_missing_member_without_rehashing_images",
    '''
    def test_verified_bundle_cache_restores_isolated_trainer_writable_images(tmp_path):
        snapshot_id = "a" * 64
        source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
        cache = TrainingBundleCache(tmp_path / "data", "project-a", max_bytes=0, ttl_seconds=0)

        entry, published = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)
        assert published["published"] is True
        assert published["verified_files"] == 2
        assert published["bundle_bytes"] == entry.bundle_bytes
        assert published["maintenance"]["evicted_entries"] == 0

        resolved = cache.resolve(snapshot_id)
        assert resolved is not None
        restored, stats = cache.restore(resolved, tmp_path / "task-work")

        cache_image = entry.bundle / "dataset/images/train/img-1.jpg"
        restored_image = restored / "dataset/images/train/img-1.jpg"
        cache_label = entry.bundle / "dataset/labels/train/img-1.txt"
        restored_label = restored / "dataset/labels/train/img-1.txt"
        assert restored_image.read_bytes() == b"train-image-bytes"
        assert stats["hardlinked_images"] == 0
        assert stats["hardlinked_image_bytes"] == 0
        assert stats["copied_images"] == 2
        assert stats["copied_image_bytes"] == len(b"train-image-bytes") + len(b"test-image-bytes")
        assert stats["cache_bundle_bytes"] == entry.bundle_bytes
        assert stats["cache_last_access_ns"] > 0
        assert not os.path.samefile(cache_image, restored_image)
        assert not os.path.samefile(cache_label, restored_label)

        restored_image.write_bytes(b"rewritten-by-trainer")
        assert cache_image.read_bytes() == b"train-image-bytes"
    ''',
)
replace_between(
    "tests/unit/test_training_bundle_cache.py",
    "def test_cache_restore_falls_back_to_copy_when_hardlink_is_unavailable",
    "\n\ndef test_cache_publish_requires_final_verified_file_count",
    '''
    def test_cache_restore_never_attempts_image_hardlinks(monkeypatch, tmp_path):
        snapshot_id = "c" * 64
        source_bundle = _write_bundle(tmp_path / "source", snapshot_id=snapshot_id)
        cache = TrainingBundleCache(tmp_path / "data", "project-c", max_bytes=0, ttl_seconds=0)
        entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)

        monkeypatch.setattr(
            training_bundle_cache.os,
            "link",
            lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("hardlink must not be used")),
        )
        restored, stats = cache.restore(entry, tmp_path / "task-work")
        assert stats["hardlinked_images"] == 0
        assert stats["hardlinked_image_bytes"] == 0
        assert stats["copied_images"] == 2
        assert stats["copied_image_bytes"] == len(b"train-image-bytes") + len(b"test-image-bytes")
        assert (restored / "dataset/images/test/img-2.jpg").read_bytes() == b"test-image-bytes"
    ''',
)
append_once(
    "tests/unit/test_training_bundle_cache.py",
    "def test_cache_schema_v2_is_rejected_after_writable_hardlink_fix",
    '''
    def test_cache_schema_v2_is_rejected_after_writable_hardlink_fix(tmp_path):
        snapshot_id = "0" * 64
        source_bundle = _write_bundle(tmp_path / "source-schema", snapshot_id=snapshot_id)
        cache = TrainingBundleCache(tmp_path / "data", "project-schema", max_bytes=0, ttl_seconds=0)
        entry, _ = cache.publish_verified(source_bundle, snapshot_id, verified_files=2)
        marker_path = entry.root / "cache.json"
        marker = json.loads(marker_path.read_text(encoding="utf-8"))
        marker["schema_version"] = 2
        marker_path.write_text(json.dumps(marker, sort_keys=True), encoding="utf-8")

        assert cache.resolve(snapshot_id) is None
    ''',
)

# D-Fire regression tests plus format-neutral suffix behavior.
replace_once(
    "tests/unit/test_training_bundle_isolation.py",
    "import hashlib\nimport os\nimport time\n",
    "import hashlib\nimport json\nimport os\nimport time\n",
)
replace_once(
    "tests/unit/test_training_bundle_isolation.py",
    "import pytest\n\nfrom platform_core import training_tasks\n",
    "import pytest\nfrom PIL import Image\n\nfrom platform_core import training_tasks\n",
)
append_once(
    "tests/unit/test_training_bundle_isolation.py",
    "def test_missing_jpeg_eoi_is_normalized_before_ultralytics_without_mutating_source",
    r'''
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
    ''',
)

replace_once(
    "tests/unit/test_snapshots.py",
    '    assert first["schema_version"] == 3\n',
    '    assert first["schema_version"] == 3\n    assert first["training_input_policy"] == "ultralytics_jpeg_repair_v1"\n',
)

# Permanent workflow now encodes the new safety contract.
workflow = Path(".github/workflows/training-final-validation-hardening.yml")
text = workflow.read_text(encoding="utf-8")
text = text.replace(
    "      - platform_core/training_tasks.py\n      - platform_core/training_bundle_cache.py\n",
    "      - platform_core/training_tasks.py\n      - platform_core/training_bundle_cache.py\n      - platform_core/snapshots.py\n",
    1,
)
text = text.replace(
    "      - tests/unit/test_training_bundle_isolation.py\n",
    "      - tests/unit/test_training_bundle_isolation.py\n      - tests/unit/test_snapshots.py\n",
    1,
)
text = text.replace(
    "          platform_core/training_bundle_cache.py\n          platform_core/training_metrics.py\n",
    "          platform_core/training_bundle_cache.py\n          platform_core/snapshots.py\n          platform_core/training_metrics.py\n",
    1,
)
text = text.replace(
    "          tests/unit/test_training_bundle_isolation.py\n          tests/unit/task_runtime/test_process_control.py\n",
    "          tests/unit/test_training_bundle_isolation.py\n          tests/unit/test_snapshots.py\n          tests/unit/task_runtime/test_process_control.py\n",
    1,
)
text = text.replace("grep -Fq 'CACHE_SCHEMA_VERSION = 2'", "grep -Fq 'CACHE_SCHEMA_VERSION = 3'", 1)
old_guards = (
    "          grep -Fq 'os.link' platform_core/training_bundle_cache.py\n"
    "          grep -Fq 'test_verified_bundle_cache_publishes_and_restores_with_image_hardlinks' tests/unit/test_training_bundle_cache.py\n"
)
new_guards = (
    "          if grep -Fq 'os.link(source_image, destination_image)' platform_core/training_bundle_cache.py; then echo 'trainer-writable cache restore must not hardlink images' >&2; exit 1; fi\n"
    "          grep -Fq 'test_verified_bundle_cache_restores_isolated_trainer_writable_images' tests/unit/test_training_bundle_cache.py\n"
    "          grep -Fq 'test_cache_restore_never_attempts_image_hardlinks' tests/unit/test_training_bundle_cache.py\n"
    "          grep -Fq 'test_cache_schema_v2_is_rejected_after_writable_hardlink_fix' tests/unit/test_training_bundle_cache.py\n"
    "          grep -Fq 'TRAINING_INPUT_POLICY = \"ultralytics_jpeg_repair_v1\"' platform_core/training_tasks.py\n"
    "          grep -Fq 'source_content_sha256' platform_core/training_tasks.py\n"
    "          grep -Fq 'TRAINING_BUNDLE_IMAGE_MUTATED' platform_core/training_tasks.py\n"
    "          grep -Fq '_JPEG_NORMALIZATION_LOCK' platform_core/training_tasks.py\n"
    "          grep -Fq 'test_missing_jpeg_eoi_is_normalized_before_ultralytics_without_mutating_source' tests/unit/test_training_bundle_isolation.py\n"
    "          grep -Fq 'training_input_policy' platform_core/snapshots.py\n"
)
if old_guards not in text:
    raise SystemExit("permanent guard anchor missing")
workflow.write_text(text.replace(old_guards, new_guards, 1), encoding="utf-8")
