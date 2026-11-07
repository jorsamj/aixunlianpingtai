"""Bounded read-only visual evidence for ZIP external-label confirmation.

Not an AnnotationRepository, ImportCandidateStore, or label-mapping owner.
Only scanned ZIP members are eligible; no labels are decided automatically.
"""
from __future__ import annotations

import json
from pathlib import PurePosixPath
import xml.etree.ElementTree as ET

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
_MAX_LABEL_BYTES = 32 * 1024 * 1024


def _read_member(zf, name: str) -> bytes:
    info = zf.getinfo(name)
    if info.file_size < 0 or info.file_size > _MAX_LABEL_BYTES:
        return b""
    with zf.open(info) as source:
        return source.read(_MAX_LABEL_BYTES + 1)[:_MAX_LABEL_BYTES]


def _index_images(images: list[str]) -> tuple[dict[str, str], dict[str, str]]:
    """Index path suffixes once: 20k images must not require 20k scans per label."""
    by_suffix: dict[str, str] = {}
    by_stem: dict[str, str] = {}
    for image in images:
        positions = [0] + [i + 1 for i, char in enumerate(image) if char == "/"]
        for position in positions:
            suffix = image[position:]
            previous = by_suffix.get(suffix)
            if previous is None:
                by_suffix[suffix] = image
            elif previous != image:
                by_suffix[suffix] = ""
        stem = PurePosixPath(image).stem
        previous = by_stem.get(stem)
        if previous is None:
            by_stem[stem] = image
        elif previous != image:
            by_stem[stem] = ""
    return by_suffix, by_stem


def _pair_image(reference: str, lookup: tuple[dict[str, str], dict[str, str]]) -> str:
    """Fail closed when an original label could reference multiple ZIP images."""
    by_suffix, by_stem = lookup
    normalized = str(reference or "").replace("\\", "/").lstrip("/")
    if not normalized:
        return ""
    exact = by_suffix.get(normalized, "")
    if exact:
        return exact
    ref = PurePosixPath(normalized)
    prefixes = str(ref.parent).replace("/labels", "/images").replace("labels/", "images/")
    if prefixes == "labels":
        prefixes = "images"
    possible = {
        by_suffix.get(f"{prefixes}/{ref.stem}{suffix}".strip("./"), "")
        for suffix in _IMAGE_EXTENSIONS
    } - {""}
    if len(possible) == 1:
        return next(iter(possible))
    if len(possible) > 1:
        return ""
    return by_stem.get(ref.stem, "")


def build_zip_class_samples(
    zf, images: list[dict], classes: list[dict], fmt: str, *,
    limit: int = 8, normalize_name=None,
) -> dict[str, list[dict]]:
    """Inspect source annotations once during scan and save <=8 refs per class.

    Returns normalized YOLO-like bounding boxes and internal ZIP image member
    names only. Full images are streamed later behind a same-project endpoint.
    """
    cap = max(1, min(12, int(limit)))
    keys = {str(row.get("class_id")) for row in classes}
    samples: dict[str, list[dict]] = {key: [] for key in keys}
    grouped: dict[str, dict[str, dict]] = {key: {} for key in keys}
    image_paths = [
        str(row.get("path") or "") for row in images
        if PurePosixPath(str(row.get("path") or "")).suffix.lower() in _IMAGE_EXTENSIONS
    ]

    lookup = _index_images(image_paths)

    def add(key, path, bbox):
        key = str(key)
        if key not in samples or not path:
            return
        values = [float(bbox.get(k, 0)) for k in ("cx", "cy", "w", "h")]
        if not all(0 <= n <= 1 for n in values) or values[2] <= 0 or values[3] <= 0:
            return
        normalized_box = dict(zip(("cx", "cy", "w", "h"), values))
        existing = grouped[key].get(path)
        if existing is not None:
            if len(existing["bboxes"]) < 256:
                existing["bboxes"].append(normalized_box)
            return
        if len(samples[key]) >= cap:
            return
        row = {
            "image_path": path, "filename": PurePosixPath(path).name,
            "bbox": normalized_box, "bboxes": [normalized_box],
        }
        grouped[key][path] = row
        samples[key].append(row)

    if str(fmt).upper() == "YOLO":
        for name in zf.namelist():
            ref = PurePosixPath(name)
            if ref.suffix.lower() != ".txt" or ref.name.lower() in {
                "classes.txt", "obj.names", "_darknet.labels", "train.txt", "val.txt", "test.txt"
            }:
                continue
            path = _pair_image(name, lookup)
            if not path:
                continue
            try:
                data = _read_member(zf, name).decode("utf-8", "replace")
            except (OSError, KeyError, RuntimeError, ValueError):
                continue
            for line in data.splitlines():
                parts = line.split()
                if len(parts) < 5:
                    continue
                try:
                    key = str(int(float(parts[0])))
                    bbox = dict(zip(("cx", "cy", "w", "h"), map(float, parts[1:5])))
                    add(key, path, bbox)
                except (TypeError, ValueError, OverflowError):
                    continue
    elif str(fmt).upper() == "COCO":
        for name in zf.namelist():
            if PurePosixPath(name).suffix.lower() != ".json":
                continue
            try:
                data = json.loads(_read_member(zf, name).decode("utf-8"))
            except (OSError, KeyError, RuntimeError, ValueError):
                continue
            if not isinstance(data, dict) or not isinstance(data.get("annotations"), list):
                continue
            records = {
                str(row.get("id")): row for row in data.get("images", [])
                if isinstance(row, dict)
            }
            for annotation in data.get("annotations", []):
                if not isinstance(annotation, dict):
                    continue
                original = records.get(str(annotation.get("image_id"))) or {}
                path = _pair_image(str(original.get("file_name") or ""), lookup)
                box = annotation.get("bbox") or []
                try:
                    width, height = float(original.get("width") or 0), float(original.get("height") or 0)
                    if not path or width <= 0 or height <= 0 or len(box) < 4:
                        continue
                    x, y, w, h = [float(v) for v in box[:4]]
                    add(annotation.get("category_id"), path, {
                        "cx": (x + w / 2) / width, "cy": (y + h / 2) / height,
                        "w": w / width, "h": h / height,
                    })
                except (TypeError, ValueError, ZeroDivisionError):
                    continue
            break
    elif str(fmt).lower() == "pascal voc":
        for name in zf.namelist():
            if PurePosixPath(name).suffix.lower() != ".xml":
                continue
            try:
                root = ET.fromstring(_read_member(zf, name))
                path = _pair_image(root.findtext("filename") or name, lookup)
                width = float(root.findtext("size/width") or 0)
                height = float(root.findtext("size/height") or 0)
                if not path or width <= 0 or height <= 0:
                    continue
                for obj in root.findall("object"):
                    original_name = str(obj.findtext("name") or "").strip()
                    key = normalize_name(original_name) if normalize_name else original_name
                    rect = obj.find("bndbox")
                    if rect is None:
                        continue
                    x1, y1, x2, y2 = [
                        float(rect.findtext(tag) or 0)
                        for tag in ("xmin", "ymin", "xmax", "ymax")
                    ]
                    add(key, path, {
                        "cx": (x1 + x2) / (2 * width), "cy": (y1 + y2) / (2 * height),
                        "w": (x2 - x1) / width, "h": (y2 - y1) / height,
                    })
            except (ET.ParseError, KeyError, ValueError, TypeError, OSError, RuntimeError):
                continue
    return {key: rows for key, rows in samples.items() if rows}
