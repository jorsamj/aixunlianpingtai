"""Read-only COCO / Pascal VOC detection discovery for material-import review.

This module is deliberately project-database agnostic. It reads one bounded
StorageProvider view, writes only task-owned ImportCandidateStore evidence and
never creates platform labels or Material/AnnotationRepository records.
"""
from __future__ import annotations

import hashlib
import json
import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable, Iterable, Mapping

from .errors import StorageError
from .import_candidates import ImportCandidateStore
from .models import ObjectMetadata
from .yolo_import import IMAGE_EXTENSIONS, resolve_reference

BATCH_SIZE = 500
MAX_COCO_JSON_BYTES = 64 * 1024 * 1024
MAX_VOC_XML_BYTES = 2 * 1024 * 1024
MAX_ANNOTATION_FILES = 250_000
MAX_ANNOTATION_BOXES = 5_000_000


class DetectionImportError(StorageError):
    def __init__(self, code: str, message: str):
        super().__init__(code=code, message=message, detail=message)


class DetectionScanCancelled(Exception):
    pass


@dataclass(frozen=True)
class DetectionScanResult:
    import_format: str
    annotation_files: int
    missing_images: int
    quality: dict
    classes: tuple[tuple[int, str], ...]


def _cancelled(callback: Callable[[], bool]) -> None:
    if callback():
        raise DetectionScanCancelled()


def _read_bounded(provider, key: str, maximum: int) -> bytes:
    with provider.open_reader(key) as stream:
        raw = stream.read(maximum + 1)
    if len(raw) > maximum:
        raise DetectionImportError(
            "DETECTION_ANNOTATION_TOO_LARGE",
            f"annotation file exceeds {maximum} bytes",
        )
    return raw


def _split_from_key(key: str) -> str:
    path = PurePosixPath(str(key or "").replace("\\", "/"))
    parts = [part.lower() for part in path.parts]
    for value in parts:
        if value in {"val", "valid", "validation"}:
            return "val"
        if value == "test":
            return "test"
        if value == "train":
            return "train"
    stem = path.stem.lower()
    if "validation" in stem or "valid" in stem or "val" in stem:
        return "val"
    if "test" in stem:
        return "test"
    return "train"


def _valid_class_id(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("boolean class id")
    class_id = int(value)
    if class_id < 0 or class_id > 2**63 - 1:
        raise ValueError("class id out of range")
    return class_id


def _class_name(value: object) -> str:
    name = str(value or "").strip()
    if not name or len(name) > 1000:
        raise ValueError("invalid class name")
    return name


def _normalized_box(
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    width: int,
    height: int,
) -> tuple[dict[str, float | bool] | None, str | None]:
    values = (x1, y1, x2, y2)
    if width <= 0 or height <= 0 or not all(math.isfinite(value) for value in values):
        return None, "DETECTION_BOX_INVALID"
    clipped_x1 = max(0.0, min(float(width), x1))
    clipped_y1 = max(0.0, min(float(height), y1))
    clipped_x2 = max(0.0, min(float(width), x2))
    clipped_y2 = max(0.0, min(float(height), y2))
    if clipped_x2 - clipped_x1 < 2.0 or clipped_y2 - clipped_y1 < 2.0:
        return None, "DETECTION_BOX_INVALID"
    clipped = any(
        abs(left - right) > 1e-9
        for left, right in zip(values, (clipped_x1, clipped_y1, clipped_x2, clipped_y2))
    )
    box_width = clipped_x2 - clipped_x1
    box_height = clipped_y2 - clipped_y1
    return {
        "cx": ((clipped_x1 + clipped_x2) / 2.0) / float(width),
        "cy": ((clipped_y1 + clipped_y2) / 2.0) / float(height),
        "w": box_width / float(width),
        "h": box_height / float(height),
        "clipped": clipped,
    }, ("DETECTION_BOX_CLIPPED" if clipped else None)


class DetectionDatasetScanner:
    def __init__(
        self,
        provider,
        store: ImportCandidateStore,
        iter_objects,
        inspect_image,
        *,
        storage_source_id: str,
        storage_type: str,
        cancelled: Callable[[], bool] = lambda: False,
        progress: Callable[[str], object] = lambda _key: None,
    ) -> None:
        self.provider = provider
        self.store = store
        self.iter_objects = iter_objects
        self.inspect_image = inspect_image
        self.storage_source_id = str(storage_source_id)
        self.storage_type = str(storage_type)
        self.cancelled = cancelled
        self.progress = progress
        self._metadata: dict[str, ObjectMetadata] = {}
        self._basename: dict[str, str | None] = {}
        self._stem: dict[str, str | None] = {}
        self._json_keys: list[str] = []
        self._xml_keys: list[str] = []

    @staticmethod
    def _index_unique(index: dict[str, str | None], value: str, key: str) -> None:
        current = index.get(value)
        if current is None and value not in index:
            index[value] = key
        elif current != key:
            index[value] = None

    def _inventory(self, prefix: str, recursive: bool) -> None:
        batch = []
        total = 0
        for item in self.iter_objects(self.provider, prefix, recursive):
            _cancelled(self.cancelled)
            key = resolve_reference(self.provider, str(item.key))
            total += 1
            if total > 250_000:
                raise DetectionImportError(
                    "DETECTION_OBJECT_LIMIT",
                    "dataset contains more than 250000 objects",
                )
            batch.append({
                "object_key": key,
                "size_bytes": max(0, int(item.size_bytes or 0)),
                "etag": str(item.etag or ""),
                "sha256": str(item.sha256 or ""),
            })
            suffix = PurePosixPath(key).suffix.lower()
            if suffix in IMAGE_EXTENSIONS:
                metadata = ObjectMetadata(
                    key=key,
                    size_bytes=max(0, int(item.size_bytes or 0)),
                    etag=str(item.etag or ""),
                    content_type=str(getattr(item, "content_type", "") or "application/octet-stream"),
                    sha256=str(item.sha256 or ""),
                    last_modified=str(getattr(item, "last_modified", "") or ""),
                )
                self._metadata[key] = metadata
                self._index_unique(self._basename, PurePosixPath(key).name.lower(), key)
                self._index_unique(self._stem, PurePosixPath(key).stem.lower(), key)
            elif suffix == ".json":
                self._json_keys.append(key)
            elif suffix == ".xml":
                self._xml_keys.append(key)
            if len(batch) >= BATCH_SIZE:
                self.store.inventory_many(batch)
                batch.clear()
                self.progress(key)
        if batch:
            self.store.inventory_many(batch)

    def _read_annotation_source(self, key: str, maximum: int) -> bytes:
        """Read bounded annotation bytes and freeze their verified source identity."""
        raw = _read_bounded(self.provider, key, maximum)
        current = self.store.inventory_for_keys([key]).get(key)
        if current is None:
            raise DetectionImportError(
                "DETECTION_SOURCE_CHANGED",
                "annotation source disappeared during scan",
            )
        actual_size = len(raw)
        listed_size = int(current.get("size_bytes") or 0)
        if listed_size and listed_size != actual_size:
            raise DetectionImportError(
                "DETECTION_SOURCE_CHANGED",
                "annotation source size changed while being read",
            )
        actual_sha = hashlib.sha256(raw).hexdigest()
        listed_sha = str(current.get("sha256") or "").strip().lower()
        if listed_sha and listed_sha != actual_sha:
            raise DetectionImportError(
                "DETECTION_SOURCE_CHANGED",
                "annotation source hash changed while being read",
            )
        self.store.inventory_many([{
            "object_key": key,
            "size_bytes": actual_size,
            "etag": str(current.get("etag") or ""),
            "sha256": actual_sha,
        }])
        return raw

    def _resolve_image(self, file_name: str, *, annotation_key: str, prefix: str) -> str | None:
        raw = str(file_name or "").strip().replace("\\", "/")
        if not raw:
            return None
        candidates: list[str] = []
        for base in ("", prefix, str(PurePosixPath(annotation_key).parent)):
            try:
                candidate = resolve_reference(self.provider, raw, base)
            except StorageError:
                continue
            if candidate not in candidates:
                candidates.append(candidate)
        for candidate in candidates:
            if candidate in self._metadata:
                return candidate
        basename = PurePosixPath(raw).name.lower()
        unique = self._basename.get(basename)
        if unique:
            return unique
        stem = PurePosixPath(raw).stem.lower()
        unique = self._stem.get(stem)
        return unique or None

    def _inspect(self, key: str, seen_hashes: set[str]) -> dict:
        metadata = self._metadata.get(key)
        if metadata is None:
            raise DetectionImportError(
                "DETECTION_IMAGE_MISSING",
                "annotation references an image outside the inventoried dataset",
            )
        return self.inspect_image(
            self.provider,
            metadata,
            storage_source_id=self.storage_source_id,
            storage_type=self.storage_type,
            seen_hashes=seen_hashes,
        )

    def scan(
        self,
        import_format: str,
        *,
        prefix: str = "",
        recursive: bool = True,
    ) -> DetectionScanResult:
        normalized = str(import_format or "").strip().lower()
        if normalized not in {"coco", "voc"}:
            raise DetectionImportError(
                "DETECTION_FORMAT_UNSUPPORTED",
                "detection scanner accepts coco or voc",
            )
        prefix = resolve_reference(self.provider, prefix) if prefix else ""
        self._inventory(prefix, recursive)
        if normalized == "coco":
            return self._scan_coco(prefix)
        return self._scan_voc(prefix)

    def _scan_coco(self, prefix: str) -> DetectionScanResult:
        documents: list[tuple[str, dict]] = []
        for key in sorted(self._json_keys):
            _cancelled(self.cancelled)
            try:
                raw = self._read_annotation_source(key, MAX_COCO_JSON_BYTES)
                payload = json.loads(raw.decode("utf-8-sig"))
            except DetectionImportError:
                raise
            except (UnicodeError, json.JSONDecodeError):
                continue
            if (
                isinstance(payload, dict)
                and isinstance(payload.get("images"), list)
                and isinstance(payload.get("annotations"), list)
                and isinstance(payload.get("categories"), list)
            ):
                documents.append((key, payload))
        if not documents:
            raise DetectionImportError(
                "COCO_ANNOTATION_REQUIRED",
                "no COCO annotation JSON was found inside the selected prefix",
            )

        names: dict[int, str] = {}
        seen_splits: dict[str, str] = {}
        seen_hashes: set[str] = set()
        missing_images = 0
        total_boxes = 0
        candidate_batch: list[dict] = []

        for annotation_key, payload in documents:
            categories: dict[int, str] = {}
            if len(payload["categories"]) > 10_000:
                raise DetectionImportError("COCO_CLASSES_INVALID", "COCO contains too many classes")
            for item in payload["categories"]:
                if not isinstance(item, Mapping):
                    raise DetectionImportError("COCO_CLASSES_INVALID", "COCO category must be an object")
                try:
                    class_id = _valid_class_id(item.get("id"))
                    name = _class_name(item.get("name"))
                except (TypeError, ValueError, OverflowError) as error:
                    raise DetectionImportError("COCO_CLASSES_INVALID", "COCO category id/name is invalid") from error
                if class_id in names and names[class_id] != name:
                    raise DetectionImportError("COCO_CLASSES_CONFLICT", "COCO category id maps to conflicting names")
                names[class_id] = name
                categories[class_id] = name
            if not categories:
                raise DetectionImportError("COCO_CLASSES_INVALID", "COCO categories are empty")

            annotations_by_image: dict[str, list[Mapping]] = {}
            for item in payload["annotations"]:
                if not isinstance(item, Mapping):
                    continue
                image_id = str(item.get("image_id"))
                annotations_by_image.setdefault(image_id, []).append(item)
                total_boxes += 1
                if total_boxes > MAX_ANNOTATION_BOXES:
                    raise DetectionImportError("DETECTION_BOX_LIMIT", "dataset contains too many annotation boxes")

            for image_index, image in enumerate(payload["images"], start=1):
                _cancelled(self.cancelled)
                if not isinstance(image, Mapping):
                    continue
                file_name = str(image.get("file_name") or "").strip()
                key = self._resolve_image(file_name, annotation_key=annotation_key, prefix=prefix)
                if not key:
                    missing_images += 1
                    continue
                split = _split_from_key(annotation_key)
                previous = seen_splits.get(key)
                if previous and previous != split:
                    raise DetectionImportError(
                        "DETECTION_SPLIT_AMBIGUOUS",
                        "one image is referenced by multiple dataset splits",
                    )
                seen_splits[key] = split
                candidate = self._inspect(key, seen_hashes)
                candidate_batch.append(candidate)
                if len(candidate_batch) >= BATCH_SIZE:
                    self.store.upsert_many(candidate_batch)
                    candidate_batch.clear()

                width = int(candidate.get("width") or 0)
                height = int(candidate.get("height") or 0)
                raw_annotations = annotations_by_image.get(str(image.get("id")), [])
                boxes = []
                issues = []
                for line_number, annotation in enumerate(raw_annotations, start=1):
                    try:
                        category_id = _valid_class_id(annotation.get("category_id"))
                    except (TypeError, ValueError, OverflowError):
                        issues.append({"object_key": key, "line_number": line_number, "code": "COCO_CATEGORY_INVALID", "severity": "error"})
                        continue
                    if category_id not in categories:
                        issues.append({"object_key": key, "line_number": line_number, "code": "COCO_CATEGORY_UNKNOWN", "severity": "error"})
                        continue
                    bbox = annotation.get("bbox")
                    if not isinstance(bbox, list) or len(bbox) < 4:
                        issues.append({"object_key": key, "line_number": line_number, "code": "COCO_BBOX_INVALID", "severity": "error"})
                        continue
                    try:
                        x, y, box_width, box_height = [float(value) for value in bbox[:4]]
                    except (TypeError, ValueError, OverflowError):
                        issues.append({"object_key": key, "line_number": line_number, "code": "COCO_BBOX_INVALID", "severity": "error"})
                        continue
                    normalized, warning = _normalized_box(
                        x, y, x + box_width, y + box_height, width, height
                    )
                    if normalized is None:
                        issues.append({"object_key": key, "line_number": line_number, "code": "COCO_BBOX_INVALID", "severity": "error"})
                        continue
                    boxes.append({
                        "object_key": key,
                        "line_number": line_number,
                        "class_id": category_id,
                        **normalized,
                    })
                    if warning:
                        issues.append({"object_key": key, "line_number": line_number, "code": warning, "severity": "warning"})

                status = (
                    "annotated" if boxes
                    else "confirmed_empty" if not raw_annotations
                    else "invalid"
                )
                self.store.manifest_many([{
                    "object_key": key,
                    "split": split,
                    "yaml_key": annotation_key,
                }])
                self.store.annotation_batch(
                    [{
                        "object_key": key,
                        "label_key": annotation_key,
                        "annotation_status": status,
                        "box_count": len(boxes),
                    }],
                    boxes,
                    issues,
                )
                if image_index == 1 or image_index % 100 == 0:
                    self.progress(key)

        if candidate_batch:
            self.store.upsert_many(candidate_batch)
        self.store.set_label_mapping(names)
        quality = self.store.quality_summary()
        if missing_images:
            quality.setdefault("issues", {})["COCO_IMAGE_MISSING"] = missing_images
        return DetectionScanResult(
            import_format="coco",
            annotation_files=len(documents),
            missing_images=missing_images,
            quality=quality,
            classes=tuple(sorted(names.items())),
        )

    def _scan_voc(self, prefix: str) -> DetectionScanResult:
        xml_keys = sorted(self._xml_keys)
        if not xml_keys:
            raise DetectionImportError(
                "VOC_ANNOTATION_REQUIRED",
                "no Pascal VOC XML was found inside the selected prefix",
            )
        if len(xml_keys) > MAX_ANNOTATION_FILES:
            raise DetectionImportError("VOC_ANNOTATION_LIMIT", "too many Pascal VOC XML files")

        names: dict[int, str] = {}
        name_to_id: dict[str, int] = {}
        seen_hashes: set[str] = set()
        missing_images = 0
        total_boxes = 0
        candidate_batch: list[dict] = []

        for annotation_index, annotation_key in enumerate(xml_keys, start=1):
            _cancelled(self.cancelled)
            raw = self._read_annotation_source(annotation_key, MAX_VOC_XML_BYTES)
            lowered = raw.lower()
            if b"<!doctype" in lowered or b"<!entity" in lowered:
                raise DetectionImportError("VOC_XML_UNSAFE", "Pascal VOC XML contains forbidden declarations")
            try:
                root = ET.fromstring(raw)
            except ET.ParseError:
                continue
            filename = str(root.findtext("filename") or "").strip()
            key = self._resolve_image(
                filename or (PurePosixPath(annotation_key).stem + ".jpg"),
                annotation_key=annotation_key,
                prefix=prefix,
            )
            if not key and not filename:
                unique = self._stem.get(PurePosixPath(annotation_key).stem.lower())
                key = unique or None
            if not key:
                missing_images += 1
                continue
            candidate = self._inspect(key, seen_hashes)
            candidate_batch.append(candidate)
            if len(candidate_batch) >= BATCH_SIZE:
                self.store.upsert_many(candidate_batch)
                candidate_batch.clear()
            width = int(candidate.get("width") or 0)
            height = int(candidate.get("height") or 0)
            boxes = []
            issues = []
            objects = list(root.findall("object"))
            for line_number, obj in enumerate(objects, start=1):
                label = str(obj.findtext("name") or "").strip()
                if not label or len(label) > 1000:
                    issues.append({"object_key": key, "line_number": line_number, "code": "VOC_LABEL_INVALID", "severity": "error"})
                    continue
                class_id = name_to_id.get(label)
                if class_id is None:
                    class_id = len(name_to_id)
                    name_to_id[label] = class_id
                    names[class_id] = label
                box = obj.find("bndbox")
                if box is None:
                    issues.append({"object_key": key, "line_number": line_number, "code": "VOC_BBOX_MISSING", "severity": "error"})
                    continue
                try:
                    x1 = float(box.findtext("xmin"))
                    y1 = float(box.findtext("ymin"))
                    x2 = float(box.findtext("xmax"))
                    y2 = float(box.findtext("ymax"))
                except (TypeError, ValueError, OverflowError):
                    issues.append({"object_key": key, "line_number": line_number, "code": "VOC_BBOX_INVALID", "severity": "error"})
                    continue
                normalized, warning = _normalized_box(x1, y1, x2, y2, width, height)
                if normalized is None:
                    issues.append({"object_key": key, "line_number": line_number, "code": "VOC_BBOX_INVALID", "severity": "error"})
                    continue
                total_boxes += 1
                if total_boxes > MAX_ANNOTATION_BOXES:
                    raise DetectionImportError("DETECTION_BOX_LIMIT", "dataset contains too many annotation boxes")
                boxes.append({
                    "object_key": key,
                    "line_number": line_number,
                    "class_id": class_id,
                    **normalized,
                })
                if warning:
                    issues.append({"object_key": key, "line_number": line_number, "code": warning, "severity": "warning"})
            status = "annotated" if boxes else "confirmed_empty" if not objects else "invalid"
            self.store.manifest_many([{
                "object_key": key,
                "split": _split_from_key(annotation_key),
                "yaml_key": annotation_key,
            }])
            self.store.annotation_batch(
                [{
                    "object_key": key,
                    "label_key": annotation_key,
                    "annotation_status": status,
                    "box_count": len(boxes),
                }],
                boxes,
                issues,
            )
            if annotation_index == 1 or annotation_index % 100 == 0:
                self.progress(key)

        if candidate_batch:
            self.store.upsert_many(candidate_batch)
        if not names:
            raise DetectionImportError("VOC_CLASSES_INVALID", "Pascal VOC dataset contains no valid classes")
        self.store.set_label_mapping(names)
        quality = self.store.quality_summary()
        if missing_images:
            quality.setdefault("issues", {})["VOC_IMAGE_MISSING"] = missing_images
        return DetectionScanResult(
            import_format="voc",
            annotation_files=len(xml_keys),
            missing_images=missing_images,
            quality=quality,
            classes=tuple(sorted(names.items())),
        )


__all__ = [
    "DetectionDatasetScanner",
    "DetectionImportError",
    "DetectionScanCancelled",
    "DetectionScanResult",
]
