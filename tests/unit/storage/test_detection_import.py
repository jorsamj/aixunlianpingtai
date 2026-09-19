from __future__ import annotations

import io
import json
from pathlib import Path

from PIL import Image

from platform_core.storage.detection_import import DetectionDatasetScanner
from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.storage.models import ObjectMetadata


def _jpg(width=100, height=80):
    stream = io.BytesIO()
    Image.new("RGB", (width, height), "orange").save(stream, format="JPEG")
    return stream.getvalue()


class MemoryProvider:
    storage_type = "s3"

    def __init__(self, payloads):
        self.payloads = dict(payloads)

    def open_reader(self, key):
        return io.BytesIO(self.payloads[key])

    def exists(self, key):
        return key in self.payloads


def _metadata(payloads):
    import hashlib
    return [
        ObjectMetadata(
            key=key,
            size_bytes=len(value),
            etag=f'"etag-{index}"',
            content_type="image/jpeg" if Path(key).suffix.lower() in {".jpg", ".jpeg"} else "application/octet-stream",
            sha256=hashlib.sha256(value).hexdigest(),
        )
        for index, (key, value) in enumerate(sorted(payloads.items()))
    ]


def _inspect(provider, item, *, storage_source_id, storage_type, seen_hashes):
    import hashlib
    from PIL import Image
    with provider.open_reader(item.key) as stream:
        raw = stream.read()
    with Image.open(io.BytesIO(raw)) as image:
        width, height = image.size
    digest = hashlib.sha256(raw).hexdigest()
    duplicate = digest in seen_hashes
    seen_hashes.add(digest)
    return {
        "object_key": item.key,
        "filename": Path(item.key).name,
        "storage_source_id": storage_source_id,
        "storage_type": storage_type,
        "content_sha256": digest,
        "size_bytes": len(raw),
        "etag": item.etag,
        "width": width,
        "height": height,
        "status": "DUPLICATE" if duplicate else "IMPORTABLE",
        "error": "",
        "duplicate": duplicate,
    }


def _scanner(tmp_path, payloads):
    provider = MemoryProvider(payloads)
    metadata = _metadata(payloads)
    store = ImportCandidateStore(tmp_path / "candidates.sqlite3")
    scanner = DetectionDatasetScanner(
        provider,
        store,
        lambda _provider, prefix, recursive: (
            item for item in metadata
            if not prefix or item.key == prefix or item.key.startswith(prefix.rstrip("/") + "/")
        ),
        _inspect,
        storage_source_id="s3-source",
        storage_type="s3",
    )
    return scanner, store


def test_coco_scan_preserves_external_classes_splits_and_normalizes_boxes(tmp_path):
    image = _jpg()
    empty = _jpg()
    coco = {
        "images": [
            {"id": 1, "file_name": "a.jpg", "width": 100, "height": 80},
            {"id": 2, "file_name": "empty.jpg", "width": 100, "height": 80},
        ],
        "annotations": [
            {"id": 11, "image_id": 1, "category_id": 7, "bbox": [10, 20, 30, 40]},
        ],
        "categories": [{"id": 7, "name": "smoke"}],
    }
    payloads = {
        "dataset/train/a.jpg": image,
        "dataset/train/empty.jpg": empty,
        "dataset/train/_annotations.coco.json": json.dumps(coco).encode(),
    }
    scanner, store = _scanner(tmp_path, payloads)

    result = scanner.scan("coco", prefix="dataset", recursive=True)

    assert result.classes == ((7, "smoke"),)
    assert result.missing_images == 0
    rows = list(store.iter_candidates())
    assert {row["object_key"] for row in rows} == {
        "dataset/train/a.jpg",
        "dataset/train/empty.jpg",
    }
    annotations = store.annotations_for_keys([row["object_key"] for row in rows])
    first = annotations["dataset/train/a.jpg"]
    assert first["split"] == "train"
    assert first["annotation_status"] == "annotated"
    assert len(first["boxes"]) == 1
    box = first["boxes"][0]
    assert box["class_id"] == 7
    assert round(box["cx"], 4) == 0.25
    assert round(box["cy"], 4) == 0.5
    assert round(box["w"], 4) == 0.3
    assert round(box["h"], 4) == 0.5
    assert annotations["dataset/train/empty.jpg"]["annotation_status"] == "confirmed_empty"


def test_voc_scan_maps_names_and_rejects_unsafe_xml_declarations(tmp_path):
    image = _jpg()
    xml = b"""<annotation><filename>a.jpg</filename><object><name>fire</name><bndbox><xmin>5</xmin><ymin>6</ymin><xmax>55</xmax><ymax>46</ymax></bndbox></object></annotation>"""
    payloads = {
        "dataset/val/JPEGImages/a.jpg": image,
        "dataset/val/Annotations/a.xml": xml,
    }
    scanner, store = _scanner(tmp_path, payloads)

    result = scanner.scan("voc", prefix="dataset", recursive=True)

    assert result.classes == ((0, "fire"),)
    annotation = store.annotations_for_keys(["dataset/val/JPEGImages/a.jpg"])[
        "dataset/val/JPEGImages/a.jpg"
    ]
    assert annotation["split"] == "val"
    assert annotation["annotation_status"] == "annotated"
    assert annotation["boxes"][0]["class_id"] == 0

    unsafe_payloads = dict(payloads)
    unsafe_payloads["dataset/val/Annotations/a.xml"] = b'<!DOCTYPE a [<!ENTITY x "boom">]><annotation></annotation>'
    unsafe, _store = _scanner(tmp_path / "unsafe", unsafe_payloads)
    import pytest
    with pytest.raises(Exception, match="forbidden declarations"):
        unsafe.scan("voc", prefix="dataset", recursive=True)


def test_coco_scan_hashes_real_annotation_json_bytes(tmp_path):
    import hashlib
    image = _jpg()
    coco_bytes = json.dumps({
        "images": [{"id": 1, "file_name": "a.jpg", "width": 100, "height": 80}],
        "annotations": [],
        "categories": [{"id": 7, "name": "smoke"}],
    }, separators=(",", ":")).encode()
    payloads = {
        "dataset/train/a.jpg": image,
        "dataset/train/_annotations.coco.json": coco_bytes,
    }
    provider = MemoryProvider(payloads)
    metadata = [
        ObjectMetadata(
            key=item.key,
            size_bytes=item.size_bytes,
            etag=item.etag,
            content_type=item.content_type,
            sha256="" if item.key.endswith(".json") else item.sha256,
        )
        for item in _metadata(payloads)
    ]
    store = ImportCandidateStore(tmp_path / "verified-coco.sqlite3")
    scanner = DetectionDatasetScanner(
        provider,
        store,
        lambda _provider, prefix, recursive: (
            item for item in metadata
            if not prefix or item.key == prefix or item.key.startswith(prefix.rstrip("/") + "/")
        ),
        _inspect,
        storage_source_id="s3-source",
        storage_type="s3",
    )
    scanner.scan("coco", prefix="dataset", recursive=True)
    identity = store.inventory_for_keys(
        ["dataset/train/_annotations.coco.json"]
    )["dataset/train/_annotations.coco.json"]
    assert identity["sha256"] == hashlib.sha256(coco_bytes).hexdigest()
    assert identity["size_bytes"] == len(coco_bytes)
    assert identity["etag"]


def test_coco_rescan_can_add_unreferenced_images_without_rereading_existing_candidates(tmp_path):
    image = _jpg()
    extra = _jpg(120, 90)
    coco = json.dumps({
        "images": [{"id": 1, "file_name": "a.jpg", "width": 100, "height": 80}],
        "annotations": [],
        "categories": [{"id": 7, "name": "smoke"}],
    }).encode()
    payloads = {
        "dataset/train/a.jpg": image,
        "dataset/extra.jpg": extra,
        "dataset/train/_annotations.coco.json": coco,
    }
    scanner, store = _scanner(tmp_path, payloads)
    scanner.deduplicate_images = False
    scanner.scan("coco", prefix="dataset", recursive=True)
    assert {row["object_key"] for row in store.iter_candidates()} == {"dataset/train/a.jpg"}
    scanner.ensure_all_image_candidates()
    assert {row["object_key"] for row in store.iter_candidates()} == {
        "dataset/train/a.jpg", "dataset/extra.jpg",
    }


def test_coco_scan_rejects_same_image_from_multiple_annotation_documents(tmp_path):
    import pytest

    image = _jpg()
    first = json.dumps({
        "images": [{"id": 1, "file_name": "a.jpg", "width": 100, "height": 80}],
        "annotations": [],
        "categories": [{"id": 7, "name": "smoke"}],
    }).encode()
    second = json.dumps({
        "images": [{"id": 2, "file_name": "a.jpg", "width": 100, "height": 80}],
        "annotations": [],
        "categories": [{"id": 7, "name": "smoke"}],
    }).encode()
    payloads = {
        "dataset/train/a.jpg": image,
        "dataset/train/annotations-a.json": first,
        "dataset/train/annotations-b.json": second,
    }
    scanner, _store = _scanner(tmp_path, payloads)

    with pytest.raises(Exception, match="multiple COCO annotation documents"):
        scanner.scan("coco", prefix="dataset", recursive=True)


def test_coco_scan_rejects_duplicate_image_object_inside_one_document(tmp_path):
    import pytest

    image = _jpg()
    coco = json.dumps({
        "images": [
            {"id": 1, "file_name": "a.jpg", "width": 100, "height": 80},
            {"id": 2, "file_name": "a.jpg", "width": 100, "height": 80},
        ],
        "annotations": [],
        "categories": [{"id": 7, "name": "smoke"}],
    }).encode()
    scanner, _store = _scanner(tmp_path, {
        "dataset/train/a.jpg": image,
        "dataset/train/_annotations.coco.json": coco,
    })

    with pytest.raises(Exception, match="referenced more than once"):
        scanner.scan("coco", prefix="dataset", recursive=True)


def test_voc_scan_hashes_real_xml_bytes_and_rejects_ambiguous_image_sources(tmp_path):
    import hashlib
    import pytest

    image = _jpg()
    xml = b"""<annotation><filename>a.jpg</filename><object><name>fire</name><bndbox><xmin>5</xmin><ymin>6</ymin><xmax>55</xmax><ymax>46</ymax></bndbox></object></annotation>"""
    payloads = {
        "dataset/train/JPEGImages/a.jpg": image,
        "dataset/train/Annotations/a.xml": xml,
    }
    scanner, store = _scanner(tmp_path / "identity", payloads)
    scanner.scan("voc", prefix="dataset", recursive=True)
    identity = store.inventory_for_keys(
        ["dataset/train/Annotations/a.xml"]
    )["dataset/train/Annotations/a.xml"]
    assert identity["sha256"] == hashlib.sha256(xml).hexdigest()
    assert identity["size_bytes"] == len(xml)
    assert identity["etag"]

    duplicate = dict(payloads)
    duplicate["dataset/train/Annotations/duplicate.xml"] = xml
    ambiguous, _store = _scanner(tmp_path / "ambiguous", duplicate)
    with pytest.raises(Exception, match="multiple Pascal VOC XML documents"):
        ambiguous.scan("voc", prefix="dataset", recursive=True)
