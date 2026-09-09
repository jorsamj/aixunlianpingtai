"""Read-only YOLO detection discovery with disk-backed manifests and quality rules."""
from __future__ import annotations

import math
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Mapping

from .errors import StorageError
from .models import ObjectMetadata, StorageType

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
BATCH_SIZE = 500
MAX_TEXT_LINE = 1024 * 1024


@dataclass(frozen=True)
class YoloDatasetLayout:
    yaml_key: str
    split_image_roots: dict[str, tuple[str, ...]]
    names: dict[int, str]


@dataclass(frozen=True)
class ParsedYoloBox:
    external_class_id: int
    class_name: str
    cx: float
    cy: float
    width: float
    height: float
    action: str
    line_number: int


@dataclass(frozen=True)
class ParseResult:
    boxes: tuple[ParsedYoloBox, ...]
    issues: tuple[dict[str, object], ...]


class YoloImportError(StorageError):
    def __init__(self, code: str, message: str):
        super().__init__(code=code, message=message, detail=message)


class YoloScanCancelled(Exception):
    pass


def resolve_reference(provider, reference: str, base: str = "") -> str:
    """Normalize YAML/list references to a source-relative key, checking symlinks."""
    if not isinstance(reference, str) or not reference.strip() or "\x00" in reference or len(reference) > 4096:
        raise YoloImportError("YOLO_INVALID_PATH", "Dataset reference must be a nonempty path")
    raw = reference.strip().replace("\\", "/")
    windows = PureWindowsPath(raw)
    absolute = PurePosixPath(raw).is_absolute() or windows.is_absolute() or bool(windows.drive)
    is_local = provider.storage_type in (StorageType.LOCAL, "local")
    if "://" in raw:
        raise YoloImportError("YOLO_INVALID_PATH", "Dataset references must stay within the storage source")
    if absolute:
        if not is_local:
            raise YoloImportError("YOLO_ABSOLUTE_PATH", "Host absolute paths are not supported by this storage source")
        root = Path(provider.root).resolve()
        path = Path(raw)
        if not path.is_absolute():
            raise YoloImportError("YOLO_INVALID_PATH", "Absolute path is incompatible with this host")
        try:
            return path.resolve().relative_to(root).as_posix().removeprefix("./")
        except ValueError as error:
            raise YoloImportError("YOLO_PATH_OUTSIDE_SOURCE", "Dataset reference escapes its storage source") from error
    parts = []
    for part in (PurePosixPath(base) / raw).parts:
        if part == "..":
            if not parts:
                raise YoloImportError("YOLO_PATH_OUTSIDE_SOURCE", "Dataset reference escapes its storage source")
            parts.pop()
        elif part != ".":
            if ":" in part:
                raise YoloImportError("YOLO_INVALID_PATH", "Dataset path contains an unsupported path component")
            parts.append(part)
    key = "/".join(parts)
    if is_local:
        root = Path(provider.root).resolve()
        try:
            (root / key).resolve().relative_to(root)
        except ValueError as error:
            raise YoloImportError("YOLO_PATH_OUTSIDE_SOURCE", "Dataset reference escapes its storage source") from error
    return key


def parse_detection_line(line: str, class_ids: set[int]) -> tuple[dict | None, list[str]]:
    """Return a normalized clipped box plus stable diagnostic codes.

    Severe overflow means more than half the original width or height is lost.
    Every positive intersection is retained, independently of that warning.
    """
    fields = line.split()
    if len(fields) != 5:
        return None, ["INVALID_DETECTION_FORMAT"]
    try:
        values = [float(value) for value in fields]
    except ValueError:
        return None, ["INVALID_DETECTION_FORMAT"]
    if not all(math.isfinite(value) for value in values):
        return None, ["NONFINITE_BOX"]
    class_value, cx, cy, width, height = values
    if not class_value.is_integer() or class_value < 0:
        return None, ["INVALID_CLASS_ID"]
    class_id = int(class_value)
    if class_id not in class_ids:
        return None, ["UNKNOWN_CLASS_ID"]
    if width <= 0 or height <= 0:
        return None, ["ZERO_SIZE_BOX" if width == 0 or height == 0 else "INVALID_BOX_SIZE"]
    left, right = cx - width / 2, cx + width / 2
    top, bottom = cy - height / 2, cy + height / 2
    if right <= 0 or bottom <= 0 or left >= 1 or top >= 1:
        return None, ["FULLY_OUTSIDE_BOX"]
    x1, y1, x2, y2 = max(0.0, left), max(0.0, top), min(1.0, right), min(1.0, bottom)
    clipped_w, clipped_h = x2 - x1, y2 - y1
    if clipped_w <= 0 or clipped_h <= 0:
        return None, ["CLIP_TO_ZERO_BOX"]
    clipped = left < 0 or top < 0 or right > 1 or bottom > 1
    codes = []
    if clipped:
        codes.append("BOX_CLIPPED")
        if clipped_w / width < 0.5 or clipped_h / height < 0.5:
            codes.append("SEVERE_BOX_OVERFLOW")
    return {"class_id": class_id, "cx": (x1 + x2) / 2, "cy": (y1 + y2) / 2,
            "w": clipped_w, "h": clipped_h, "clipped": clipped}, codes


def _read_yaml_document(provider, yaml_key: str) -> dict:
    import yaml
    try:
        with closing(provider.open_reader(yaml_key)) as stream:
            raw = stream.read(MAX_TEXT_LINE + 1)
        if len(raw) > MAX_TEXT_LINE:
            raise YoloImportError("YOLO_YAML_TOO_LARGE", "Dataset YAML exceeds the size limit")
        document = yaml.safe_load(raw)
    except (yaml.YAMLError, UnicodeError, RecursionError) as error:
        raise YoloImportError("YOLO_INVALID_YAML", "Dataset YAML is invalid") from error
    except YoloImportError:
        raise
    except (OSError, StorageError, KeyError) as error:
        raise YoloImportError("YOLO_YAML_READ_FAILED", "Dataset YAML could not be read") from error
    if not isinstance(document, dict):
        raise YoloImportError("YOLO_INVALID_YAML", "Dataset YAML must contain a mapping")
    return document


def _parse_names(document: Mapping) -> dict[int, str]:
    names = document.get("names")
    if isinstance(names, list):
        names = dict(enumerate(names))
    if not isinstance(names, dict) or not names or len(names) > 10000:
        raise YoloImportError("YOLO_INVALID_CLASSES", "Dataset YAML requires a bounded names list or mapping")
    parsed = {}
    for key, name in names.items():
        try:
            class_id = int(key)
        except (ValueError, TypeError, OverflowError) as error:
            raise YoloImportError("YOLO_INVALID_CLASSES", "Class IDs must be nonnegative integers") from error
        if (isinstance(key, bool) or str(class_id) != str(key) or class_id < 0 or class_id > 2**63 - 1
                or not isinstance(name, str) or not name.strip() or len(name) > 1000):
            raise YoloImportError("YOLO_INVALID_CLASSES", "Class IDs and names are invalid")
        parsed[class_id] = name
    return parsed


def discover_yolo_layout(provider, prefix: str, dataset_yaml: str = "") -> YoloDatasetLayout:
    """Discover a dataset YAML at the exact prefix root and resolve its split roots."""
    prefix = resolve_reference(provider, prefix) if prefix else ""
    if dataset_yaml:
        yaml_key = resolve_reference(provider, dataset_yaml)
    else:
        root = prefix.rstrip("/")
        candidates = [f"{root}/{name}" if root else name for name in ("data.yaml", "dataset.yaml")]
        found = [key for key in candidates if provider.exists(key)]
        if len(found) > 1:
            raise YoloImportError("YOLO_YAML_AMBIGUOUS", "Multiple dataset YAML files found; choose dataset_yaml explicitly")
        if not found:
            raise YoloImportError("YOLO_YAML_REQUIRED", "YOLO import requires a dataset YAML file")
        yaml_key = found[0]
    document = _read_yaml_document(provider, yaml_key)
    names = _parse_names(document)
    base = str(PurePosixPath(yaml_key).parent)
    if document.get("path") is not None:
        base = resolve_reference(provider, document["path"], base)
    splits: dict[str, tuple[str, ...]] = {}
    values = [(key, document[key]) for key in ("train", "val", "test", "valid", "validation")
              if document.get(key) is not None]
    if isinstance(document.get("splits"), dict):
        values.extend(document["splits"].items())
    if not values:
        raise YoloImportError("YOLO_SPLITS_REQUIRED", "Dataset YAML must declare image splits")
    for split, references in values:
        if not isinstance(split, str) or len(split) > 100:
            raise YoloImportError("YOLO_INVALID_SPLIT", "Dataset split name is invalid")
        references = references if isinstance(references, list) else [references]
        splits[split] = tuple(resolve_reference(provider, reference, base) for reference in references)
    return YoloDatasetLayout(yaml_key=yaml_key, split_image_roots=splits, names=names)


def parse_yolo_text(text: str, names: Mapping[int, str], object_key: str) -> ParseResult:
    """Parse a YOLO label document through the scanner's stable box rules."""
    boxes = []
    issues = []
    class_ids = set(names)
    for line_number, line in enumerate(text.splitlines(), 1):
        if not line.strip():
            continue
        box, codes = parse_detection_line(line, class_ids)
        if box:
            boxes.append(ParsedYoloBox(
                external_class_id=box["class_id"], class_name=names[box["class_id"]],
                cx=box["cx"], cy=box["cy"], width=box["w"], height=box["h"],
                action="clipped" if box["clipped"] else "accepted", line_number=line_number,
            ))
        issues.extend({"object_key": object_key, "line_number": line_number, "code": code,
                       "severity": "warning" if box else "error"} for code in codes)
    return ParseResult(tuple(boxes), tuple(issues))


class YoloImportScanner:
    def __init__(self, provider, store, iter_objects, *, cancelled=lambda: False, progress=lambda key: None):
        self.provider = provider
        self.store = store
        self.iter_objects = iter_objects
        self.cancelled = cancelled
        self.progress = progress
        self.yaml_key = ""
        self.names: dict[int, str] = {}

    def _tick(self, key=""):
        if self.cancelled():
            raise YoloScanCancelled()
        self.progress(key)

    def _inventory(self, prefix: str, recursive: bool):
        batch = []
        for item in self.iter_objects(self.provider, prefix, recursive):
            if self.cancelled():
                raise YoloScanCancelled()
            key = resolve_reference(self.provider, item.key)
            batch.append({"object_key": key, "size_bytes": item.size_bytes,
                          "etag": item.etag or "", "sha256": item.sha256 or ""})
            if len(batch) == BATCH_SIZE:
                self.store.inventory_many(batch)
                batch.clear()
                self._tick(key)
        if batch:
            self.store.inventory_many(batch)

    def _lines(self, key):
        with closing(self.provider.open_reader(key)) as stream:
            while True:
                if self.cancelled():
                    raise YoloScanCancelled()
                line = stream.readline(MAX_TEXT_LINE + 1)
                if not line:
                    return
                if len(line) > MAX_TEXT_LINE:
                    raise YoloImportError("YOLO_TEXT_LINE_TOO_LONG", "Dataset text line exceeds the size limit")
                try:
                    yield line.decode("utf-8-sig").strip() if isinstance(line, bytes) else line.strip()
                except UnicodeError as error:
                    raise YoloImportError("YOLO_INVALID_TEXT", "Dataset text must use UTF-8 encoding") from error

    def prepare(self, import_format="auto", *, prefix="", recursive=True, dataset_yaml=None):
        if import_format not in {"auto", "images", "yolo"}:
            raise YoloImportError("INVALID_IMPORT_FORMAT", "import_format must be auto, images or yolo")
        if import_format == "images":
            return "images"
        # A restart rebuilds discovery and annotations; legacy candidates and lifecycle remain intact.
        with self.store._transaction() as connection:
            for table in ("candidate_annotations", "annotation_issues", "dataset_manifest", "dataset_objects", "label_mapping"):
                connection.execute(f"DELETE FROM {table}")
        prefix = resolve_reference(self.provider, prefix) if prefix else ""
        self._inventory(prefix, recursive)
        if dataset_yaml:
            self.yaml_key = resolve_reference(self.provider, dataset_yaml)
        else:
            root = prefix.rstrip("/")
            candidates = [f"{root}/{name}" if root else name for name in ("data.yaml", "dataset.yaml")]
            with closing(self.store._connect()) as connection:
                found = connection.execute(
                    "SELECT object_key FROM dataset_objects WHERE lower(object_key) IN (?, ?) "
                    "ORDER BY object_key LIMIT 2", tuple(key.lower() for key in candidates)).fetchall()
            if len(found) > 1:
                raise YoloImportError("YOLO_YAML_AMBIGUOUS", "Multiple dataset YAML files found; choose dataset_yaml explicitly")
            if not found:
                if import_format == "auto":
                    return "images"
                raise YoloImportError("YOLO_YAML_REQUIRED", "YOLO import requires a dataset YAML file")
            self.yaml_key = found[0][0]
        import yaml
        try:
            with closing(self.provider.open_reader(self.yaml_key)) as stream:
                raw = stream.read(MAX_TEXT_LINE + 1)
            if len(raw) > MAX_TEXT_LINE:
                raise YoloImportError("YOLO_YAML_TOO_LARGE", "Dataset YAML exceeds the size limit")
            document = yaml.safe_load(raw)
        except (yaml.YAMLError, UnicodeError, RecursionError) as error:
            raise YoloImportError("YOLO_INVALID_YAML", "Dataset YAML is invalid") from error
        except YoloImportError:
            raise
        except (OSError, StorageError) as error:
            raise YoloImportError("YOLO_YAML_READ_FAILED", "Dataset YAML could not be read") from error
        if not isinstance(document, dict):
            raise YoloImportError("YOLO_INVALID_YAML", "Dataset YAML must contain a mapping")
        names = document.get("names")
        if isinstance(names, list):
            names = dict(enumerate(names))
        if not isinstance(names, dict) or not names or len(names) > 10000:
            raise YoloImportError("YOLO_INVALID_CLASSES", "Dataset YAML requires a bounded names list or mapping")
        for key, name in names.items():
            try:
                class_id = int(key)
            except (ValueError, TypeError, OverflowError) as error:
                raise YoloImportError("YOLO_INVALID_CLASSES", "Class IDs must be nonnegative integers") from error
            if (isinstance(key, bool) or str(class_id) != str(key) or class_id < 0 or class_id > 2**63 - 1
                    or not isinstance(name, str) or not name.strip() or len(name) > 1000):
                raise YoloImportError("YOLO_INVALID_CLASSES", "Class IDs and names are invalid")
            self.names[class_id] = name
        self.store.set_label_mapping(self.names)
        base = str(PurePosixPath(self.yaml_key).parent)
        if document.get("path") is not None:
            base = resolve_reference(self.provider, document["path"], base)
        # YAML may refer to siblings of the selected prefix. One source inventory
        # avoids an exists/stat round trip for each image and each possible TXT.
        if prefix or not recursive:
            self._inventory("", True)
        splits = [(key, document[key]) for key in ("train", "val", "test", "valid", "validation") if document.get(key) is not None]
        if isinstance(document.get("splits"), dict):
            splits.extend(document["splits"].items())
        if not splits:
            raise YoloImportError("YOLO_SPLITS_REQUIRED", "Dataset YAML must declare image splits")
        for split, references in splits:
            if not isinstance(split, str) or len(split) > 100:
                raise YoloImportError("YOLO_INVALID_SPLIT", "Dataset split name is invalid")
            references = references if isinstance(references, list) else [references]
            for reference in references:
                key = resolve_reference(self.provider, reference, base)
                if PurePosixPath(key).suffix.lower() == ".txt":
                    entries = []
                    for line in self._lines(key):
                        if not line:
                            continue
                        # Relative list entries are resolved against the list's directory.
                        entries.append(resolve_reference(self.provider, line, str(PurePosixPath(key).parent)))
                        if len(entries) == BATCH_SIZE:
                            self._add_list_entries(entries, split)
                            entries.clear()
                    if entries:
                        self._add_list_entries(entries, split)
                else:
                    self._add_reference(key, split)
        return "yolo"

    def _add_list_entries(self, keys, split):
        placeholders = ",".join("?" for _ in keys)
        with closing(self.store._connect()) as connection:
            found = {row[0] for row in connection.execute(
                f"SELECT object_key FROM dataset_objects WHERE object_key IN ({placeholders})", keys)}
            conflict = connection.execute(
                f"SELECT 1 FROM dataset_manifest WHERE object_key IN ({placeholders}) AND split<>? LIMIT 1",
                (*keys, split)).fetchone()
        if conflict:
            raise YoloImportError("YOLO_SPLIT_AMBIGUOUS", "An image is referenced by multiple splits")
        if any(key not in found or PurePosixPath(key).suffix.lower() not in IMAGE_EXTENSIONS for key in keys):
            raise YoloImportError("YOLO_IMAGES_NOT_FOUND", "An image list contains an absent or unsupported image")
        self.store.manifest_many({"object_key": key, "split": split, "yaml_key": self.yaml_key} for key in keys)
        self._tick(keys[-1])

    def _add_reference(self, key, split):
        prefix = key.rstrip("/") + "/" if key else ""
        after = ""
        found = False
        while True:
            with closing(self.store._connect()) as connection:
                rows = connection.execute(
                    "SELECT object_key FROM dataset_objects WHERE object_key>? AND "
                    "(object_key=? OR (object_key>=? AND object_key<?)) ORDER BY object_key LIMIT ?",
                    (after, key, prefix, prefix + chr(0x10ffff), BATCH_SIZE)).fetchall()
                images = [row[0] for row in rows if PurePosixPath(row[0]).suffix.lower() in IMAGE_EXTENSIONS]
                if images:
                    placeholders = ",".join("?" for _ in images)
                    conflict = connection.execute(
                        f"SELECT 1 FROM dataset_manifest WHERE object_key IN ({placeholders}) AND split<>? LIMIT 1",
                        (*images, split)).fetchone()
                    if conflict:
                        raise YoloImportError("YOLO_SPLIT_AMBIGUOUS", "An image is referenced by multiple splits")
            if not rows:
                break
            found |= bool(images)
            self.store.manifest_many({"object_key": image, "split": split, "yaml_key": self.yaml_key} for image in images)
            after = rows[-1][0]
            self._tick(after)
        if not found:
            raise YoloImportError("YOLO_IMAGES_NOT_FOUND", "A dataset image reference contains no supported images")

    def iter_images(self):
        yield from self.iter_inventory(dataset_only=True)

    def iter_inventory(self, *, dataset_only=False):
        after = ""
        while True:
            with closing(self.store._connect()) as connection:
                join = " JOIN dataset_manifest m USING(object_key)" if dataset_only else ""
                rows = connection.execute(
                    "SELECT o.* FROM dataset_objects o" + join + " "
                    "WHERE o.object_key>? ORDER BY o.object_key LIMIT ?", (after, BATCH_SIZE)).fetchall()
            if not rows:
                return
            after = rows[-1]["object_key"]
            for row in rows:
                yield ObjectMetadata(key=row["object_key"], size_bytes=row["size_bytes"], etag=row["etag"], sha256=row["sha256"])

    @staticmethod
    def _label_options(key):
        path = PurePosixPath(key)
        options = {str(path.with_suffix(".txt"))}
        for index, part in enumerate(path.parts[:-1]):
            if part == "images":
                parts = list(path.parts)
                parts[index] = "labels"
                options.add(str(PurePosixPath(*parts).with_suffix(".txt")))
        return options

    def scan_annotations(self):
        after = ""
        classes = set(self.names)
        while True:
            with closing(self.store._connect()) as connection:
                images = connection.execute(
                    "SELECT object_key FROM dataset_manifest WHERE object_key>? ORDER BY object_key LIMIT ?",
                    (after, 100)).fetchall()
                if not images:
                    return self.store.quality_summary()
                options = {key for image in images for key in self._label_options(image[0])}
                available = set()
                keys = sorted(options)
                for offset in range(0, len(keys), BATCH_SIZE):
                    chunk = keys[offset:offset + BATCH_SIZE]
                    placeholders = ",".join("?" for _ in chunk)
                    available.update(row[0] for row in connection.execute(
                        f"SELECT object_key FROM dataset_objects WHERE object_key IN ({placeholders})", chunk))
            states, boxes, issues = [], [], []

            def flush():
                self.store.annotation_batch(states, boxes, issues)
                states.clear()
                boxes.clear()
                issues.clear()

            for image in images:
                key = image[0]
                self._tick(key)
                labels = self._label_options(key) & available
                state = {"object_key": key, "label_key": None, "annotation_status": "unannotated", "box_count": 0}
                if len(labels) > 1:
                    state["annotation_status"] = "invalid"
                    issues.append({"object_key": key, "line_number": 0, "code": "YOLO_LABEL_AMBIGUOUS", "severity": "error"})
                elif labels:
                    label_key = resolve_reference(self.provider, next(iter(labels)))
                    state["label_key"] = label_key
                    nonempty = False
                    try:
                        for number, line in enumerate(self._lines(label_key), 1):
                            if not line:
                                continue
                            nonempty = True
                            box, codes = parse_detection_line(line, classes)
                            if box:
                                boxes.append({"object_key": key, "line_number": number, **box})
                                state["box_count"] += 1
                            issues.extend({"object_key": key, "line_number": number, "code": code,
                                           "severity": "warning" if box else "error"} for code in codes)
                            if len(boxes) + len(issues) >= BATCH_SIZE:
                                flush()
                                self._tick(key)
                        state["annotation_status"] = "annotated" if state["box_count"] else ("invalid" if nonempty else "confirmed_empty")
                    except (OSError, StorageError) as error:
                        state["annotation_status"] = "invalid"
                        issues.append({"object_key": key, "line_number": 0,
                                       "code": error.code if isinstance(error, YoloImportError) else "YOLO_LABEL_READ_FAILED", "severity": "error"})
                states.append(state)
            flush()
            after = images[-1][0]
