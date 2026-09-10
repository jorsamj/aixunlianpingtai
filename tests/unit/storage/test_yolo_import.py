"""Focused detection quality, source boundary and disk-backed discovery cases."""
import io
from types import SimpleNamespace

import pytest

from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.storage.local import LocalStorageProvider
from platform_core.storage.models import ObjectMetadata, StorageType
from platform_core.storage.yolo_import import (
    YoloImportError, YoloImportScanner, parse_detection_line, resolve_reference,
)


class MemoryProvider:
    storage_type = StorageType.S3

    def __init__(self, files):
        self.files = files

    def open_reader(self, key):
        return io.BytesIO(self.files[key])


def objects(provider, prefix, recursive):
    for key, data in sorted(provider.files.items()):
        if not prefix or key == prefix or key.startswith(prefix.rstrip("/") + "/"):
            yield ObjectMetadata(key, len(data))


@pytest.mark.parametrize("line,code", [
    ("0 .5 .5 nan .1", "NONFINITE_BOX"),
    ("1 .5 .5 .1 .1", "UNKNOWN_CLASS_ID"),
    ("0 .5 .5 0 .1", "ZERO_SIZE_BOX"),
    ("0 2 .5 .1 .1", "FULLY_OUTSIDE_BOX"),
    ("0 .1 .1 .2 .2 .3 .3", "INVALID_DETECTION_FORMAT"),
])
def test_invalid_detection(line, code):
    assert parse_detection_line(line, {0}) == (None, [code])


def test_severe_overflow_keeps_positive_intersection():
    box, issues = parse_detection_line("0 -1 .5 3 .5", {0})
    assert box["w"] == .5
    assert box["cx"] == .25
    assert "SEVERE_BOX_OVERFLOW" in issues


def test_source_boundaries(tmp_path):
    provider = SimpleNamespace(storage_type=StorageType.LOCAL, root=tmp_path)
    assert resolve_reference(provider, str(tmp_path / "data.yaml")) == "data.yaml"
    assert resolve_reference(provider, "../images", "dataset") == "images"
    with pytest.raises(YoloImportError, match="escapes"):
        resolve_reference(provider, str(tmp_path.parent / "outside.yaml"))
    with pytest.raises(YoloImportError):
        resolve_reference(MemoryProvider({}), "C:/dataset/data.yaml")
    with pytest.raises(YoloImportError):
        resolve_reference(MemoryProvider({}), "../../outside", "dataset")


def test_discovery_labels_and_bounded_summary(tmp_path):
    provider = MemoryProvider({
        "data.yaml": b"names: [cat]\ntrain: images/train\nval: val/images\n",
        "images/train/a.jpg": b"image", "labels/train/a.txt": b"0 -.1 .5 .4 .2\n0 .5 .5 nan .1\n",
        "images/train/b.jpg": b"image", "labels/train/b.txt": b"",
        "images/train/c.jpg": b"image",
        "val/images/d.png": b"image", "val/labels/d.txt": b"0 .5 .5 .2 .2\n",
    })
    store = ImportCandidateStore(tmp_path / "candidates.sqlite3")
    scanner = YoloImportScanner(provider, store, objects)
    assert scanner.prepare("auto") == "yolo"
    assert len(list(scanner.iter_images())) == 4
    quality = scanner.scan_annotations()
    assert quality["boxes"] == 2
    assert quality["annotation_status"] == {"annotated": 2, "confirmed_empty": 1, "unannotated": 1}
    assert quality["issues"]["NONFINITE_BOX"] == 1
    assert len(store.quality_summary(1)["examples"]) == 1
    assert "candidates" not in quality


def test_yaml_and_label_ambiguity(tmp_path):
    provider = MemoryProvider({"data.yaml": b"names: [cat]\ntrain: train/images\n",
                               "dataset.yaml": b"{}", "train/images/a.jpg": b"image",
                               "train/images/a.txt": b"", "train/labels/a.txt": b""})
    store = ImportCandidateStore(tmp_path / "candidates.sqlite3")
    scanner = YoloImportScanner(provider, store, objects)
    with pytest.raises(YoloImportError) as error:
        scanner.prepare("auto")
    assert error.value.code == "YOLO_YAML_AMBIGUOUS"
    assert scanner.prepare("yolo", dataset_yaml="data.yaml") == "yolo"
    assert scanner.scan_annotations()["issues"] == {"YOLO_LABEL_AMBIGUOUS": 1}


def test_list_file_same_directory_and_safe_yaml(tmp_path):
    provider = MemoryProvider({"data.yaml": b"names: {0: cat}\ntrain: lists/train.txt\n",
                               "lists/train.txt": b"../samples/a.png\n",
                               "samples/a.png": b"image", "samples/a.txt": b""})
    store = ImportCandidateStore(tmp_path / "candidates.sqlite3")
    scanner = YoloImportScanner(provider, store, objects)
    scanner.prepare("yolo")
    assert scanner.scan_annotations()["annotation_status"] == {"confirmed_empty": 1}
    provider.files["data.yaml"] = b"!!python/object/apply:os.system ['echo unsafe']"
    with pytest.raises(YoloImportError) as error:
        scanner.prepare("yolo")
    assert error.value.code == "YOLO_INVALID_YAML"


def test_prefix_scanner_does_not_reinventory_entire_storage_for_self_contained_zip(tmp_path):
    provider = MemoryProvider({
        "zip-a/data.yaml": b"names: [cat]\ntrain: images/train\nval: images/val\n",
        "zip-a/images/train/a.jpg": b"image",
        "zip-a/labels/train/a.txt": b"0 .5 .5 .2 .2\n",
        "zip-a/images/val/b.jpg": b"image",
        "zip-a/labels/val/b.txt": b"0 .5 .5 .2 .2\n",
        "old-dataset/images/old.jpg": b"unrelated",
    })
    calls = []

    def recording_objects(provider, prefix, recursive):
        calls.append((prefix, recursive))
        yield from objects(provider, prefix, recursive)

    store = ImportCandidateStore(tmp_path / "candidates.sqlite3")
    scanner = YoloImportScanner(provider, store, recording_objects)
    assert scanner.prepare("yolo", prefix="zip-a", dataset_yaml="zip-a/data.yaml") == "yolo"
    assert calls == [("zip-a", True)]
    assert len(list(scanner.iter_images())) == 2


def test_cross_prefix_yaml_keeps_compatibility_by_explicit_full_inventory(tmp_path):
    provider = MemoryProvider({
        "zip-a/data.yaml": b"path: ..\nnames: [cat]\ntrain: shared/images\n",
        "shared/images/a.jpg": b"image",
        "shared/labels/a.txt": b"0 .5 .5 .2 .2\n",
    })
    calls = []

    def recording_objects(provider, prefix, recursive):
        calls.append((prefix, recursive))
        yield from objects(provider, prefix, recursive)

    store = ImportCandidateStore(tmp_path / "candidates.sqlite3")
    scanner = YoloImportScanner(provider, store, recording_objects)
    assert scanner.prepare("yolo", prefix="zip-a", dataset_yaml="zip-a/data.yaml") == "yolo"
    assert calls == [("zip-a", True), ("", True)]
    assert len(list(scanner.iter_images())) == 1


def test_local_inventory_metadata_does_not_hash_contents(tmp_path, monkeypatch):
    root = tmp_path / "storage"
    root.mkdir()
    (root / "data.yaml").write_text("names: [cat]\ntrain: images\n", encoding="utf-8")
    (root / "labels.txt").write_text("0 .5 .5 .2 .2\n", encoding="utf-8")
    (root / "image.jpg").write_bytes(b"not-read-by-inventory")

    def unexpected_hash(_path):
        raise AssertionError("cheap inventory must not hash file contents")

    monkeypatch.setattr("platform_core.storage.local._sha256", unexpected_hash)
    provider = LocalStorageProvider("local", root)
    rows = list(provider.iter_objects_metadata())
    assert {row.key for row in rows} == {"data.yaml", "image.jpg", "labels.txt"}
    assert all(row.sha256 == "" for row in rows)
