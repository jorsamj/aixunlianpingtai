"""Focused detection quality, source boundary and disk-backed discovery cases."""
import io
from types import SimpleNamespace

import pytest

from platform_core.storage.import_candidates import ImportCandidateStore
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
    ("1 .5 .5 .1 .1", "UNKNOWN_CLASS"),
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
