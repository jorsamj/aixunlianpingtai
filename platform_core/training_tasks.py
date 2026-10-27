from __future__ import annotations

from platform_core.task_runtime.process_start_gate import execution_environment

import errno
import hashlib
import json
import math
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping, Sequence

import psutil
import yaml
from PIL import Image, ImageDraw, ImageFile, ImageOps, ImageStat, UnidentifiedImageError

from .annotations import atomic_write_json
from .errors import PlatformError
from .annotation_repository import AnnotationRepository
from .algorithms import (
    attach_version,
    attach_version_if_current,
    choose_algorithm_iteration_base,
    list_algorithms,
    resolve_current_version_id,
)
from .material_repository import MaterialRepository
from .secrets import KeyringSecretStore, SecretCredentialStore
from .snapshots import (
    build_snapshot,
    dataset_revision_document,
    ensure_dataset_revision,
    is_training_ground_truth,
    persist_dataset_revision,
)
from .storage import StorageManager
from .task_runtime import ProcessController, TaskKind, TaskStatus, launch_process
from .training_splits import SplitMode, SplitRequest, build_split_manifest, assert_training_duplicate_safety, training_annotation_digest
from .training_devices import normalize_training_device, training_python, validate_training_device
from .training_metrics import read_metrics
from .training_bundle_cache import TrainingBundleCache
from .training_lineage import build_training_lineage
from .training_evaluation import build_evaluation_truth, build_iteration_decision, build_training_metric_credibility, build_evaluation_benchmark_scope


TRAINING_BUNDLE_SAFETY_RESERVE_BYTES = 512 * 1024 * 1024
TRAINING_BUNDLE_SAFETY_RESERVE_ENV = "TRAINING_BUNDLE_SAFETY_RESERVE_BYTES"
TRAINING_BUNDLE_COPY_ORPHAN_AGE_SECONDS = 24 * 60 * 60
TRAINING_PROJECTION_POLICY_V1 = "redact_excluded_objects_v1"
TRAINING_PROJECTION_POLICY = "redact_excluded_objects_v2_preserve_selected"
TRAINING_PROJECTION_POLICY_V3 = "reviewed_negative_original_v3_preserve_selected"
_TRAINING_BUNDLE_COPY_PREFIX = ".training-bundle-copy."
TRAINING_COMPLETION_GRACE_SECONDS = 5.0
TRAINING_INPUT_POLICY = "ultralytics_jpeg_repair_v1"
_JPEG_SUFFIXES = {".jpg", ".jpeg", ".jpe", ".jfif"}
_JPEG_NORMALIZATION_LOCK = threading.Lock()
_SUCCESSFUL_TRAINING_OUTCOMES = {
    "completed",
    "target_reached",
    "early_stopping",
    # Existing quality-gate semantics: the run completed and produced a
    # verified checkpoint, but the result recommends another iteration.
    "needs_optimization",
}


def _request_external_publish_after_training(**kwargs) -> bool:
    """Wake the existing external publisher without widening training-core imports."""
    from .external_publish_request import request_external_auto_publish_if_enabled

    return request_external_auto_publish_if_enabled(**kwargs)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _copy2_with_sha256(source: Path, destination: Path) -> tuple[int, str]:
    """Copy one artifact while hashing the exact bytes written to its destination."""
    digest = hashlib.sha256()
    size_bytes = 0

    class CountingHashingReader(_HashingReader):
        def read(self, size: int = -1):
            nonlocal size_bytes
            chunk = super().read(size)
            if chunk:
                size_bytes += len(chunk)
            return chunk

    with source.open("rb") as input_stream, destination.open("wb") as output_stream:
        shutil.copyfileobj(
            CountingHashingReader(input_stream, digest),
            output_stream,
            length=1024 * 1024,
        )
    shutil.copystat(source, destination)
    return size_bytes, digest.hexdigest()


def _portable_relative(reference: str) -> Path:
    raw = str(reference or "")
    value = Path(raw)
    windows = PureWindowsPath(raw)
    if (
        not raw
        or "\\" in raw
        or value.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or windows.root
        or ".." in value.parts
        or ".." in windows.parts
    ):
        raise ValueError("relative portable dataset reference required")
    return value


def _resolve_relative(root: Path, reference: str) -> Path:
    value = _portable_relative(reference)
    base = root.resolve()
    resolved = (base / value).resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError("relative portable dataset reference required")
    return resolved


def _atomic_text(path: Path, text: str, *, durable: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
            if durable:
                os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _path_info(path: Path) -> os.stat_result | None:
    try:
        return path.lstat()
    except FileNotFoundError:
        return None


def _is_link_like(path: Path) -> bool:
    info = _path_info(path)
    if info is None:
        return False
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0)
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & reparse_flag)


def _same_physical_file(left: Path, right: Path) -> bool:
    try:
        return os.path.samefile(left, right)
    except (NotImplementedError, OSError):
        # Unknown identity is never sufficient proof that reuse is safe.
        return True


class _HashingReader:
    """Read-through wrapper so the copied bytes are hashed in the copy pass."""

    def __init__(self, stream, digest):
        self.stream = stream
        self.digest = digest

    def read(self, size: int = -1):
        chunk = self.stream.read(size)
        if chunk:
            self.digest.update(chunk)
        return chunk


def _prepare_bundle_root(task_root: str | Path) -> tuple[Path, Path]:
    work_input = Path(task_root)
    if _is_link_like(work_input):
        raise ValueError("training work path must be a real directory, not a link")
    work = work_input.resolve()
    work.mkdir(parents=True, exist_ok=True)
    root = work / "bundle"
    info = _path_info(root)
    if info is not None:
        if _is_link_like(root):
            raise ValueError("training bundle path must be a real bundle directory, not a link")
        if not stat.S_ISDIR(info.st_mode):
            raise ValueError("training bundle path must be a directory")
    else:
        root.mkdir()
    return work, root


def _bundle_output_path(root: Path, reference: str) -> Path:
    relative = _portable_relative(reference)
    current = root
    for part in relative.parts[:-1]:
        current = current / part
        info = _path_info(current)
        if info is None:
            current.mkdir()
        elif _is_link_like(current):
            raise ValueError("training bundle output parent must not be a link or reparse point")
        elif not stat.S_ISDIR(info.st_mode):
            raise ValueError("training bundle output parent must be a directory")
    return root / relative


def _copy_verified_isolated(
    source: Path,
    destination: Path,
    expected_hash: str,
    *,
    bundle_root: Path | None = None,
    durable: bool = True,
) -> None:
    source_info = source.stat() if source.is_file() else None
    if source_info is None or source_info.st_size <= 0:
        raise FileNotFoundError(f"training image does not exist: {source.name}")
    source_size = source_info.st_size
    if bundle_root is None:
        destination.parent.mkdir(parents=True, exist_ok=True)
    else:
        try:
            relative = destination.relative_to(bundle_root).as_posix()
        except ValueError as error:
            raise ValueError("portable destination must stay inside the bundle") from error
        if _bundle_output_path(bundle_root, relative) != destination:
            raise ValueError("portable destination must stay inside the bundle")
    if source == destination:
        raise ValueError("training image source and portable destination must be different paths")
    destination_link = _is_link_like(destination)
    if destination_link or destination.exists():
        if destination_link:
            pass
        elif not destination.is_file():
            raise ValueError(f"existing portable image is not a file: {destination.name}")
        elif _sha256(destination) == expected_hash and not _same_physical_file(source, destination):
            return

    descriptor, name = tempfile.mkstemp(
        dir=destination.parent,
        prefix=f"{_TRAINING_BUNDLE_COPY_PREFIX}{os.getpid()}.",
        suffix=".copy",
    )
    temporary = Path(name)
    digest = hashlib.sha256()
    try:
        with source.open("rb") as input_stream:
            hashing_stream = _HashingReader(input_stream, digest)
            with os.fdopen(descriptor, "wb") as output_stream:
                descriptor = -1
                shutil.copyfileobj(hashing_stream, output_stream, length=1024 * 1024)
                output_stream.flush()
                if durable:
                    os.fsync(output_stream.fileno())
        copied_size = temporary.stat().st_size
        if copied_size != source_size:
            raise OSError(
                f"portable image size verification failed: {destination.name}; "
                f"expected={source_size}, actual={copied_size}"
            )
        if copied_size <= 0:
            raise OSError(f"portable image verification failed: {destination.name}")
        if digest.hexdigest() != expected_hash:
            raise ValueError(f"source image SHA256 changed: {source.name}")
        os.replace(temporary, destination)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


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

def _process_is_running(process_id: int) -> bool:
    if process_id <= 0:
        return False
    # POSIX commonly uses os.kill(pid, 0) as a non-signalling existence probe,
    # but that contract is unsafe on Windows: signal value 0 is CTRL_C_EVENT
    # there. Use psutil's cross-platform, non-signalling PID probe instead. A
    # reused PID intentionally counts as live so orphan cleanup remains
    # conservative and never deletes a temporary copy owned by another process.
    return bool(psutil.pid_exists(int(process_id)))


def _cleanup_orphan_bundle_copies(
    root: Path,
    *,
    expected_work: Path,
    now: float | None = None,
) -> None:
    """Remove only aged, owned temp copies without traversing link-like paths."""
    work_info = _path_info(expected_work)
    if (
        work_info is None
        or _is_link_like(expected_work)
        or not stat.S_ISDIR(work_info.st_mode)
        or root.parent != expected_work
        or root.name != "bundle"
    ):
        raise ValueError("cleanup root is outside the validated training work boundary")
    info = _path_info(root)
    if info is None or _is_link_like(root) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("cleanup requires a validated real bundle directory")
    current_time = time.time() if now is None else now
    pending = [root]
    while pending:
        directory = pending.pop()
        for candidate in directory.iterdir():
            candidate_info = _path_info(candidate)
            if candidate_info is None or _is_link_like(candidate):
                continue
            if stat.S_ISDIR(candidate_info.st_mode):
                pending.append(candidate)
                continue
            if not stat.S_ISREG(candidate_info.st_mode):
                continue
            name = candidate.name
            if not name.startswith(_TRAINING_BUNDLE_COPY_PREFIX) or not name.endswith(".copy"):
                continue
            owner_and_token = name[len(_TRAINING_BUNDLE_COPY_PREFIX) : -len(".copy")]
            owner, separator, token = owner_and_token.partition(".")
            if not separator or not token or not owner.isdecimal():
                continue
            if current_time - candidate_info.st_mtime < TRAINING_BUNDLE_COPY_ORPHAN_AGE_SECONDS:
                continue
            if _process_is_running(int(owner)):
                continue
            candidate.unlink(missing_ok=True)


def _safety_reserve_bytes(configured: int | None) -> int:
    raw: int | str = configured if configured is not None else os.environ.get(
        TRAINING_BUNDLE_SAFETY_RESERVE_ENV,
        TRAINING_BUNDLE_SAFETY_RESERVE_BYTES,
    )
    try:
        reserve = int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{TRAINING_BUNDLE_SAFETY_RESERVE_ENV} must be a non-negative integer") from error
    if reserve < 0:
        raise ValueError(f"{TRAINING_BUNDLE_SAFETY_RESERVE_ENV} must be a non-negative integer")
    return reserve


def _nearest_existing(path: Path) -> Path:
    candidate = path
    while not candidate.exists():
        if candidate.parent == candidate:
            break
        candidate = candidate.parent
    return candidate


def _check_bundle_disk_space(root: Path, remaining_bytes: int, atomic_copy_bytes: int, reserve_bytes: int) -> None:
    required = max(0, remaining_bytes) + max(0, atomic_copy_bytes) + reserve_bytes
    free = shutil.disk_usage(_nearest_existing(root)).free
    if free < required:
        raise OSError(
            errno.ENOSPC,
            "Insufficient disk space for training bundle: "
            f"free={free} bytes, required={required} bytes, "
            f"remaining={remaining_bytes} bytes, atomic_copy_peak={atomic_copy_bytes} bytes, "
            f"safety_reserve={reserve_bytes} bytes",
        )


def _yolo_line(box: Mapping[str, Any], width: float, height: float, class_id: int) -> str:
    if width <= 0 or height <= 0:
        raise ValueError("image width and height must be positive")
    if all(key in box for key in ("x1", "y1", "x2", "y2")):
        x1, y1 = float(box["x1"]), float(box["y1"])
        x2, y2 = float(box["x2"]), float(box["y2"])
        cx, cy = (x1 + x2) / 2 / width, (y1 + y2) / 2 / height
        bw, bh = (x2 - x1) / width, (y2 - y1) / height
    else:
        cx, cy = float(box.get("cx", 0)), float(box.get("cy", 0))
        bw, bh = float(box.get("w", 0)), float(box.get("h", 0))
        if max(abs(cx), abs(cy), abs(bw), abs(bh)) > 1:
            cx, cy, bw, bh = cx / width, cy / height, bw / width, bh / height
    values = [cx, cy, bw, bh]
    if bw <= 0 or bh <= 0 or any(value < 0 or value > 1 for value in values):
        raise ValueError("annotation box is outside image bounds")
    return f"{class_id} " + " ".join(f"{value:.8f}" for value in values)


def _apply_training_projection(
    destination: Path,
    row: Mapping[str, Any],
    role: str,
    image_identity: Mapping[str, Any],
) -> dict[str, Any]:
    """Redact task-excluded objects while preserving selected positive pixels."""
    identity = dict(image_identity)
    excluded = [
        dict(box) for box in (row.get("training_excluded_boxes") or [])
        if isinstance(box, Mapping)
    ]
    policy = str(row.get("training_projection_policy") or "")
    if role == "test" or (not excluded and policy != TRAINING_PROJECTION_POLICY_V3):
        return identity
    policy = str(row.get("training_projection_policy") or "")
    if policy not in {TRAINING_PROJECTION_POLICY_V1, TRAINING_PROJECTION_POLICY, TRAINING_PROJECTION_POLICY_V3}:
        raise ValueError("excluded training objects require a supported redaction policy")
    projection_digest = str(row.get("training_projection_digest") or "").strip().lower()
    if len(projection_digest) != 64:
        raise ValueError("training projection digest is missing or invalid")

    if policy == TRAINING_PROJECTION_POLICY_V3 and not row.get("boxes"):
        if row.get("annotation_state") != "confirmed_empty" or not row.get("annotation_scope"):
            raise ValueError("reviewed negative projection requires scoped formal empty truth")
        identity.update(training_projection_policy=policy,
                        training_projection_digest=projection_digest, redacted_object_count=0)
        return identity

    if not excluded:
        identity.update(training_projection_policy=policy,
                        training_projection_digest=projection_digest, redacted_object_count=0)
        return identity

    def pixel_bounds(
        box: Mapping[str, Any], width: int, height: int,
    ) -> tuple[int, int, int, int]:
        if all(key in box for key in ("x1", "y1", "x2", "y2")):
            x1, y1 = float(box["x1"]), float(box["y1"])
            x2, y2 = float(box["x2"]), float(box["y2"])
        else:
            cx, cy = float(box.get("cx", 0)), float(box.get("cy", 0))
            bw, bh = float(box.get("w", 0)), float(box.get("h", 0))
            if max(abs(cx), abs(cy), abs(bw), abs(bh)) <= 1:
                cx, cy, bw, bh = cx * width, cy * height, bw * width, bh * height
            x1, y1 = cx - bw / 2, cy - bh / 2
            x2, y2 = cx + bw / 2, cy + bh / 2
        left = max(0, min(width, int(x1)))
        top = max(0, min(height, int(y1)))
        right = max(0, min(width, int(x2 + 0.999999)))
        bottom = max(0, min(height, int(y2 + 0.999999)))
        if right <= left or bottom <= top:
            raise ValueError(
                f"training projection box is outside image bounds: {row.get('id')}"
            )
        return left, top, right, bottom

    temporary = destination.with_name(
        f".{destination.name}.{uuid.uuid4().hex}.projection.tmp"
    )
    try:
        with Image.open(destination) as source:
            image_format = str(source.format or "").upper()
            canvas = source.convert("RGB")
            width, height = canvas.size
            if width <= 0 or height <= 0:
                raise ValueError(
                    f"TRAINING_IMAGE_INVALID: filename={destination.name}; reason=empty_dimensions"
                )
            original = canvas.copy() if policy in {TRAINING_PROJECTION_POLICY, TRAINING_PROJECTION_POLICY_V3} else None
            median = tuple(int(value) for value in ImageStat.Stat(canvas).median[:3])
            draw = ImageDraw.Draw(canvas)
            redacted = 0
            for box in excluded:
                left, top, right, bottom = pixel_bounds(box, width, height)
                draw.rectangle((left, top, right - 1, bottom - 1), fill=median)
                redacted += 1
            if redacted != len(excluded):
                raise ValueError("not all excluded training objects were redacted")

            # v2 restores each selected positive rectangle after excluded-object
            # redaction. Without this, a large unselected box can erase the
            # pixels of a nested selected target while its positive YOLO label
            # remains, creating contradictory training truth.
            if original is not None:
                for box in (row.get("boxes") or []):
                    if not isinstance(box, Mapping):
                        continue
                    left, top, right, bottom = pixel_bounds(box, width, height)
                    canvas.paste(
                        original.crop((left, top, right, bottom)),
                        (left, top),
                    )

            save_format = image_format or (
                "JPEG" if destination.suffix.lower() in _JPEG_SUFFIXES else "PNG"
            )
            save_options = (
                {"quality": 100, "subsampling": 0}
                if save_format in {"JPEG", "JPG"} else {}
            )
            canvas.save(temporary, format=save_format, **save_options)
        if not temporary.is_file() or temporary.stat().st_size <= 0:
            raise ValueError("training projection produced an empty image")
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)

    previous_reason = str(identity.get("normalization_reason") or "").strip()
    identity.update(
        training_content_sha256=_sha256(destination),
        training_size_bytes=destination.stat().st_size,
        normalized=True,
        normalization_reason=(
            f"{previous_reason}+excluded_object_redaction"
            if previous_reason else "excluded_object_redaction"
        ),
        training_projection_policy=policy,
        training_projection_digest=projection_digest,
        redacted_object_count=len(excluded),
    )
    return identity

def materialize_portable_dataset(
    task_root: str | Path,
    snapshot: Mapping[str, Any],
    source_images: Sequence[Mapping[str, Any]],
    materialize: Callable[[Mapping[str, Any]], str | Path],
    *,
    safety_reserve_bytes: int | None = None,
    defer_source_reads: bool = False,
    progress: Callable[[int, int, Mapping[str, Any]], None] | None = None,
) -> Path:
    work, root = _prepare_bundle_root(task_root)
    _cleanup_orphan_bundle_copies(root, expected_work=work)
    manifest_path = root / "manifest.json"
    if _is_link_like(manifest_path):
        raise ValueError("training bundle manifest must not be a link or reparse point")
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if str(existing.get("snapshot_id") or "") != str(snapshot.get("snapshot_id") or ""):
            raise ValueError("portable bundle already belongs to a different snapshot")

    by_id = {str(row.get("id")): row for row in source_images}
    schema = sorted(
        (dict(item) for item in (snapshot.get("label_schema") or []) if item.get("code")),
        key=lambda item: (int(item.get("class_id", 10**9)), str(item.get("code"))),
    )
    class_ids = {str(item["code"]): int(item.get("class_id", index)) for index, item in enumerate(schema)}
    names = {class_id: code for code, class_id in class_ids.items()}
    snapshot_records = {str(row.get("image_id")): row for row in snapshot.get("images") or []}
    planned: list[dict[str, Any]] = []
    for role in ("train", "validation", "test"):
        for image_id in (snapshot.get("ids") or {}).get(role, []):
            row = by_id.get(str(image_id))
            locked = snapshot_records.get(str(image_id))
            if row is None or locked is None:
                raise ValueError(f"snapshot image is unavailable: {image_id}")
            original_name = str(row.get("filename") or row.get("stored_name") or row.get("object_key") or "")
            suffix = Path(original_name).suffix.lower() or ".jpg"
            stored_name = f"{image_id}{suffix}"
            expected_hash = str(locked.get("content_sha256") or "")
            if not expected_hash:
                raise ValueError(f"snapshot image has no content SHA256: {image_id}")
            if defer_source_reads:
                source_path = None
                size_bytes = int(row.get("size_bytes") or 0)
                if size_bytes <= 0:
                    raise ValueError(f"frozen image size is unavailable: {image_id}")
            else:
                source_path = Path(materialize(row)).resolve()
                if not source_path.is_file() or source_path.stat().st_size <= 0:
                    raise FileNotFoundError(f"training image does not exist: {source_path.name}")
                size_bytes = source_path.stat().st_size
            planned.append(
                {
                    "role": role,
                    "image_id": str(image_id),
                    "row": row,
                    "stored_name": stored_name,
                    "expected_hash": expected_hash,
                    "source_path": source_path,
                    "size_bytes": size_bytes,
                }
            )

    total_size_bytes = sum(int(item["size_bytes"]) for item in planned)
    peak_copy_bytes = max((int(item["size_bytes"]) for item in planned), default=0)
    reserve_bytes = _safety_reserve_bytes(safety_reserve_bytes)
    _check_bundle_disk_space(root, total_size_bytes, peak_copy_bytes, reserve_bytes)

    splits: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "test": []}
    remaining_bytes = total_size_bytes
    training_total_size_bytes = 0
    total_items = len(planned)
    for completed, item in enumerate(planned, start=1):
        role = str(item["role"])
        image_id = str(item["image_id"])
        row = item["row"]
        stored_name = str(item["stored_name"])
        expected_hash = str(item["expected_hash"])
        size_bytes = int(item["size_bytes"])
        source_path = (Path(materialize(row)).resolve() if defer_source_reads else Path(item["source_path"]))
        if defer_source_reads and (not source_path.is_file() or source_path.stat().st_size != size_bytes):
            raise ValueError(f"frozen image size changed: {image_id}")
        image_ref = f"dataset/images/{role}/{stored_name}"
        label_ref = (
            f"evaluation/ground_truth/test/{Path(stored_name).stem}.txt"
            if role == "test"
            else f"dataset/labels/{role}/{Path(stored_name).stem}.txt"
        )
        destination = _bundle_output_path(root, image_ref)
        _check_bundle_disk_space(root, remaining_bytes, size_bytes, reserve_bytes)
        # The task bundle is derived/rebuildable. Avoid a per-image fsync storm;
        # manifest/job durability remains authoritative and recovery revalidates reused files.
        _copy_verified_isolated(
            source_path, destination, expected_hash, bundle_root=root, durable=False
        )
        image_identity = _normalize_training_image(
            destination, expected_hash, size_bytes
        )
        image_identity = _apply_training_projection(
            destination, row, role, image_identity
        )
        training_hash = str(image_identity["training_content_sha256"])
        training_size_bytes = int(image_identity["training_size_bytes"])
        training_total_size_bytes += training_size_bytes
        remaining_bytes -= size_bytes
        lines = []
        for box in row.get("boxes") or []:
            label = str(box.get("label") or "").strip()
            if label not in class_ids:
                raise ValueError(f"annotation label is not in locked schema: {label}")
            lines.append(
                _yolo_line(box, float(row.get("width") or 0), float(row.get("height") or 0), class_ids[label])
            )
        label_path = _bundle_output_path(root, label_ref)
        _atomic_text(label_path, "\n".join(lines), durable=False)
        splits[role].append(
            {
                "image_id": image_id,
                "image_ref": image_ref,
                "label_ref": label_ref,
                "source_content_sha256": expected_hash,
                "source_size_bytes": size_bytes,
                "content_sha256": training_hash,
                "size_bytes": training_size_bytes,
                "training_input_policy": TRAINING_INPUT_POLICY,
                "normalized": bool(image_identity["normalized"]),
                "normalization_reason": image_identity["normalization_reason"],
                "training_projection_policy": image_identity.get("training_projection_policy"),
                "training_projection_digest": image_identity.get("training_projection_digest"),
                "redacted_object_count": int(image_identity.get("redacted_object_count") or 0),
                "label_sha256": _sha256(label_path),
            }
        )
        if progress is not None:
            progress(completed, total_items, item)
    # Independent test images stay portable, but their hidden answers are deliberately
    # absent from the Ultralytics training YAML. Final evaluation is image-only inference
    # followed by a separate scorer that opens evaluation/ground_truth/test afterwards.
    data_yaml = {
        "path": ".",
        "train": "images/train",
        "val": "images/validation",
        "names": names,
    }
    _atomic_text(
        _bundle_output_path(root, "dataset/data.yaml"),
        yaml.safe_dump(data_yaml, allow_unicode=True, sort_keys=False),
        durable=False,
    )
    portable_snapshot = ensure_dataset_revision(snapshot)
    snapshot_path = root / "snapshot.json"
    atomic_write_json(snapshot_path, portable_snapshot)
    revision_path = root / "dataset-revision.json"
    atomic_write_json(revision_path, dataset_revision_document(portable_snapshot))
    manifest = {
        "schema_version": 3,
        "snapshot_id": str(portable_snapshot.get("snapshot_id") or ""),
        "dataset_revision_schema_version": int(
            portable_snapshot.get("dataset_revision_schema_version") or 0
        ),
        "canonical_annotation_schema_version": int(
            portable_snapshot.get("canonical_annotation_schema_version") or 0
        ),
        "dataset_revision_id": str(portable_snapshot.get("dataset_revision_id") or ""),
        "training_input_policy": TRAINING_INPUT_POLICY,
        "snapshot_ref": "snapshot.json",
        "snapshot_sha256": _sha256(snapshot_path),
        "dataset_revision_ref": "dataset-revision.json",
        "dataset_revision_sha256": _sha256(revision_path),
        "data_yaml_ref": "dataset/data.yaml",
        "total_size_bytes": training_total_size_bytes,
        "splits": splits,
        "construction_verification": {
            "image_integrity": "source_sha256_verified_then_training_input_normalized",
            "training_input_policy": TRAINING_INPUT_POLICY,
            "post_write_check": "path_size_label_sha256_and_snapshot_sha256",
        },
    }
    atomic_write_json(manifest_path, manifest)
    _verify_materialized_dataset_evidence(manifest_path)
    return root


def resolve_dataset_yaml(manifest_path: str | Path) -> Path:
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    resolved = _resolve_relative(path.parent, str(manifest.get("data_yaml_ref") or ""))
    if not resolved.is_file():
        raise FileNotFoundError("portable dataset YAML does not exist")
    return resolved


def materialize_runtime_yaml(manifest_path: str | Path, destination: str | Path) -> Path:
    """Create an execution-only YAML for runtimes that resolve '.' globally.

    The portable manifest and its data.yaml remain relative and relocatable.
    This derived file is never recorded in task payload/result contracts.
    """
    portable = resolve_dataset_yaml(manifest_path)
    data = yaml.safe_load(portable.read_text(encoding="utf-8")) or {}
    data["path"] = portable.parent.resolve().as_posix()
    output = Path(destination).resolve()
    _atomic_text(output, yaml.safe_dump(data, allow_unicode=True, sort_keys=False))
    return output


def _verify_portable_training_yaml(path: Path, manifest: Mapping[str, Any], snapshot: Mapping[str, Any]) -> None:
    """Check the existing v3 training layout against its frozen class catalog."""
    if str(snapshot.get("snapshot_id") or "") != str(manifest.get("snapshot_id") or ""):
        raise ValueError("portable training snapshot identity mismatch")
    # Old snapshots have no complete class contract. Do not upgrade or
    # reinterpret their training layout during historical recovery.
    if int(manifest.get("schema_version") or 0) < 3 or int(snapshot.get("schema_version") or 0) < 3:
        return
    data_path = resolve_dataset_yaml(path)
    data = yaml.safe_load(data_path.read_text(encoding="utf-8"))
    if not isinstance(data, Mapping):
        raise ValueError("portable training YAML must be a mapping")
    schema = snapshot.get("label_schema") or []
    names = {int(row["class_id"]): str(row["code"]) for row in schema}
    if not names or len(names) != len(schema) or data.get("names") != names:
        raise ValueError("portable training YAML names differ from frozen snapshot")
    if any(data.get(key) != value for key, value in (
        ("path", "."), ("train", "images/train"), ("val", "images/validation"),
    )) or "test" in data:
        raise ValueError("portable training YAML split paths violate frozen isolation")
    if "nc" in data and data["nc"] != len(names):
        raise ValueError("portable training YAML class count differs from frozen snapshot")


def _verify_materialized_dataset_evidence(manifest_path: str | Path) -> dict[str, Any]:
    # Fresh copies SHA256 the exact source bytes while streaming them into their
    # isolated temporary destination; reused destinations are SHA256 checked
    # before reuse. Remote/received bundles and post-training finalization still
    # use verify_portable_dataset for full image SHA256 verification.
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    resolve_dataset_yaml(path)
    snapshot = _resolve_relative(path.parent, str(manifest.get("snapshot_ref") or ""))
    expected_snapshot = str(manifest.get("snapshot_sha256") or "")
    if not snapshot.is_file() or not expected_snapshot or _sha256(snapshot) != expected_snapshot:
        raise ValueError("portable training snapshot SHA256 mismatch")
    snapshot_value = json.loads(snapshot.read_text(encoding="utf-8"))
    _verify_portable_training_yaml(path, manifest, snapshot_value)
    revision = _resolve_relative(
        path.parent,
        str(manifest.get("dataset_revision_ref") or ""),
    )
    expected_revision_sha = str(manifest.get("dataset_revision_sha256") or "")
    if not revision.is_file() or not expected_revision_sha or _sha256(revision) != expected_revision_sha:
        raise ValueError("portable dataset revision SHA256 mismatch")
    revision_value = json.loads(revision.read_text(encoding="utf-8"))
    revision_id = str(manifest.get("dataset_revision_id") or "")
    if (
        not revision_id
        or str(snapshot_value.get("dataset_revision_id") or "") != revision_id
        or str(revision_value.get("dataset_revision_id") or "") != revision_id
    ):
        raise ValueError("portable dataset revision identity mismatch")
    verified = 0
    for role in ("train", "validation", "test"):
        for member in (manifest.get("splits") or {}).get(role, []):
            image_path = _resolve_relative(path.parent, str(member.get("image_ref") or ""))
            label_path = _resolve_relative(path.parent, str(member.get("label_ref") or ""))
            if _is_link_like(image_path) or not image_path.is_file():
                raise ValueError(f"portable image is missing or link-like: {member.get('image_id')}")
            expected_size = int(member.get("size_bytes") or 0)
            if expected_size <= 0 or image_path.stat().st_size != expected_size:
                raise ValueError(f"portable image size mismatch: {member.get('image_id')}")
            if _is_link_like(label_path) or not label_path.is_file():
                raise ValueError(f"portable label is missing or link-like: {member.get('image_id')}")
            if _sha256(label_path) != str(member.get("label_sha256") or ""):
                raise ValueError(f"portable label SHA256 mismatch: {member.get('image_id')}")
            verified += 1
    return {
        "snapshot_id": manifest.get("snapshot_id"),
        "dataset_revision_id": manifest.get("dataset_revision_id"),
        "verified_files": verified,
        "verification_mode": "materialization_evidence",
    }


def verify_portable_dataset(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    resolve_dataset_yaml(path)
    snapshot_path = _resolve_relative(path.parent, str(manifest.get("snapshot_ref") or ""))
    if not snapshot_path.is_file():
        raise FileNotFoundError("portable training snapshot does not exist")
    expected_snapshot = str(manifest.get("snapshot_sha256") or "")
    if (expected_snapshot or int(manifest.get("schema_version") or 0) >= 3) and (
        not expected_snapshot or _sha256(snapshot_path) != expected_snapshot
    ):
        raise ValueError("portable training snapshot SHA256 mismatch")
    snapshot_value = json.loads(snapshot_path.read_text(encoding="utf-8"))
    _verify_portable_training_yaml(path, manifest, snapshot_value)
    revision_id = str(manifest.get("dataset_revision_id") or "").strip()
    if revision_id:
        revision_path = _resolve_relative(
            path.parent,
            str(manifest.get("dataset_revision_ref") or ""),
        )
        if not revision_path.is_file():
            raise FileNotFoundError("portable dataset revision evidence is missing")
        revision_value = json.loads(revision_path.read_text(encoding="utf-8"))
        if (
            str(snapshot_value.get("dataset_revision_id") or "") != revision_id
            or str(revision_value.get("dataset_revision_id") or "") != revision_id
            or str(manifest.get("dataset_revision_sha256") or "") != _sha256(revision_path)
        ):
            raise ValueError("portable dataset revision identity mismatch")
    verified = 0
    for role in ("train", "validation", "test"):
        for member in (manifest.get("splits") or {}).get(role, []):
            image_path = _resolve_relative(path.parent, str(member.get("image_ref") or ""))
            label_path = _resolve_relative(path.parent, str(member.get("label_ref") or ""))
            expected_training_sha = str(member.get("content_sha256") or "")
            actual_training_sha = _sha256(image_path) if image_path.is_file() else ""
            if not image_path.is_file() or actual_training_sha != expected_training_sha:
                raise ValueError(
                    "TRAINING_BUNDLE_IMAGE_MUTATED: portable image SHA256 mismatch; "
                    f"image_id={member.get('image_id')}; "
                    f"expected_training_sha256={expected_training_sha or '<missing>'}; "
                    f"actual_sha256={actual_training_sha or '<missing>'}; "
                    f"source_sha256={member.get('source_content_sha256') or expected_training_sha or '<missing>'}; "
                    f"normalization_policy={member.get('training_input_policy') or manifest.get('training_input_policy') or '<missing>'}"
                )
            if not label_path.is_file() or _sha256(label_path) != str(member.get("label_sha256") or ""):
                raise ValueError(f"portable label SHA256 mismatch: {member.get('image_id')}")
            verified += 1
    return {
        "snapshot_id": manifest.get("snapshot_id"),
        "dataset_revision_id": revision_id,
        "verified_files": verified,
    }


@dataclass(frozen=True)
class RemoteTrainingBundle:
    root: Path
    manifest: Path
    data_yaml: Path
    snapshot: Path
    dataset_revision: Path | None
    snapshot_id: str
    dataset_revision_id: str
    verified_files: int


def resolve_remote_training_bundle(manifest_path: str | Path) -> RemoteTrainingBundle:
    """Resolve and verify a received portable training bundle.

    The sender may choose any archive name, but every reference inside the
    manifest must stay relative to the extracted bundle root. No client-side
    absolute path is accepted by the remote worker.
    """

    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    verification = verify_portable_dataset(path)
    snapshot = _resolve_relative(path.parent, str(manifest.get("snapshot_ref") or ""))
    if not snapshot.is_file():
        raise FileNotFoundError("portable training snapshot does not exist")
    expected = str(manifest.get("snapshot_sha256") or "")
    if not expected or _sha256(snapshot) != expected:
        raise ValueError("portable training snapshot SHA256 mismatch")
    snapshot_value = json.loads(snapshot.read_text(encoding="utf-8"))
    snapshot_id = str(manifest.get("snapshot_id") or "")
    if not snapshot_id or str(snapshot_value.get("snapshot_id") or "") != snapshot_id:
        raise ValueError("portable training snapshot identity mismatch")
    dataset_revision_id = str(verification.get("dataset_revision_id") or "")
    dataset_revision = (
        _resolve_relative(path.parent, str(manifest.get("dataset_revision_ref") or ""))
        if dataset_revision_id
        else None
    )
    return RemoteTrainingBundle(
        root=path.parent,
        manifest=path,
        data_yaml=resolve_dataset_yaml(path),
        snapshot=snapshot,
        dataset_revision=dataset_revision,
        snapshot_id=snapshot_id,
        dataset_revision_id=dataset_revision_id,
        verified_files=int(verification["verified_files"]),
    )


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _indexed_content_identity_ready(images: Sequence[Mapping[str, Any]]) -> bool:
    """Return true only when the durable material index can reproduce the Snapshot ID without source reads."""
    if not images:
        return False
    for row in images:
        digest = str(row.get("content_sha256") or "").strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            return False
        try:
            size_bytes = int(row.get("size_bytes") or 0)
        except (TypeError, ValueError):
            return False
        if size_bytes <= 0:
            return False
    return True


def revalidate_queued_training_selection(materials: MaterialRepository, split: SplitRequest):
    """Reduce a queued exact request to live identities, never refill from a filter.

    Called under the existing lifecycle fence, before formal GT/split admission.
    It is not allowed to rewrite an already-bound input freeze.
    """
    requested = tuple(dict.fromkeys((*split.train_image_ids, *split.test_image_ids)))
    found = set()
    for offset in range(0, len(requested), 500):
        found.update(str(row['id']) for row in materials.get_many(requested[offset:offset + 500]))
    train = tuple(key for key in split.train_image_ids if key in found)
    test = tuple(key for key in split.test_image_ids if key in found)
    if len(train) < 2:
        raise ValueError('TRAINING_SELECTION_INSUFFICIENT: 原请求范围内有效训练素材不足2张，请重新选择素材')
    if split.mode is SplitMode.INDEPENDENT_TEST_SET and not test:
        raise ValueError('TRAINING_TEST_SELECTION_INSUFFICIENT: 原请求独立Test素材已不可用，不能自动补选')
    report = {
        'requested_train_count': len(split.train_image_ids),
        'requested_test_count': len(split.test_image_ids),
        'remaining_train_count': len(train), 'remaining_test_count': len(test),
        'removed_image_ids': [key for key in requested if key not in found],
    }
    return replace(split, train_image_ids=train, test_image_ids=test), report


def _selected_project_images(
    materials: MaterialRepository,
    project: Path,
    image_ids: Sequence[str],
) -> list[dict[str, Any]]:
    wanted = tuple(dict.fromkeys(str(value).strip() for value in image_ids if str(value).strip()))
    if not wanted:
        raise ValueError("train_image_ids 不能为空")
    rows: list[dict[str, Any]] = []
    for offset in range(0, len(wanted), 500):
        rows.extend(materials.get_many(wanted[offset:offset + 500]))
    found = {str(row.get("id")) for row in rows}
    missing = [image_id for image_id in wanted if image_id not in found]
    if missing:
        raise ValueError(f"所选素材不存在: {', '.join(missing[:5])}")
    by_id = {str(row.get("id")): row for row in rows}
    result = []
    annotations = AnnotationRepository(project)
    annotation_by_id: dict[str, dict[str, Any]] = {}
    for offset in range(0, len(wanted), 500):
        annotation_by_id.update(annotations.get_many(wanted[offset:offset + 500]))
    for image_id in wanted:
        row = dict(by_id[image_id])
        image_id = str(row.get("id") or "")
        annotation = annotation_by_id[image_id]
        row['annotation_state'] = annotation['annotation_state']
        row['annotation_scope'] = list(annotation.get('annotation_scope') or [])
        row['annotation_version'] = int(annotation.get('version') or 0)
        row['annotation_hash'] = str(
            annotation.get('content_digest')
            or row.get('annotation_hash')
            or ''
        )
        row['annotated'] = annotation['annotation_state'] in {'annotated', 'confirmed_empty'}
        row["boxes"] = list(annotation.get("boxes") or [])
        result.append(row)
    return result


def _label_schema(project: Path) -> list[dict[str, Any]]:
    meta = _json(project / "meta.json", {})
    items = []
    for index, value in enumerate(meta.get("label_meta") or meta.get("labels") or []):
        item = dict(value) if isinstance(value, dict) else {"code": str(value)}
        if item.get("active") is False or item.get('status', 'active') != 'active':
            continue
        if not item.get("code"):
            continue
        # Project/canonical class ids are durable governance identity and may
        # contain gaps after soft-delete/unify. Training ids are a separate,
        # frozen 0..N-1 namespace required by YOLO.
        item["canonical_project_class_id"] = int(item.get("class_id", index))
        item["class_id"] = len(items)
        items.append(item)
    return items


@dataclass(frozen=True)
class TrainingSelectionResolution:
    requested_split: SplitRequest
    effective_split: SplitRequest
    effective_images: tuple[dict[str, Any], ...]
    selected_train_image_ids: tuple[str, ...]
    pending_annotation_image_ids: tuple[str, ...]
    material_revision: int | None = None
    annotation_revision: int | None = None

    def truth(self) -> dict[str, Any]:
        return {
            "selected_train_image_ids": list(self.selected_train_image_ids),
            "effective_train_image_ids": list(self.effective_split.train_image_ids),
            "pending_annotation_image_ids": list(self.pending_annotation_image_ids),
            "test_image_ids": list(self.effective_split.test_image_ids),
            "selected_train_count": len(self.selected_train_image_ids),
            "effective_train_count": len(self.effective_split.train_image_ids),
            "pending_annotation_count": len(self.pending_annotation_image_ids),
            "test_count": len(self.effective_split.test_image_ids),
        }


def _processed_training_candidate(row: Mapping[str, Any]) -> bool:
    return (
        str(row.get("processing_status") or "").strip().lower() == "processed"
        or bool(row.get("cleaned_at"))
        or bool(row.get("clean_skipped"))
    )


def resolve_training_selection(
    project: Path,
    split_request: SplitRequest,
) -> TrainingSelectionResolution:
    """Separate user-selectable cleaned material from formal supervised truth.

    Cleaned/unannotated training material is valid task intent, but it is never
    converted into an empty YOLO label. Independent test material remains
    Ground-Truth-only because evaluation without labels is meaningless.
    """
    materials = MaterialRepository(project)
    annotations = AnnotationRepository(project)
    material_revision = materials.current_revision()
    annotation_revision = annotations.current_revision()
    image_ids = (*split_request.train_image_ids, *split_request.test_image_ids)
    images = _selected_project_images(materials, project, image_ids)
    by_id = {str(row.get("id") or ""): row for row in images}

    effective_train: list[str] = []
    pending_annotation: list[str] = []
    invalid_train: list[str] = []
    for image_id in split_request.train_image_ids:
        row = by_id[str(image_id)]
        boxes = list(row.get("boxes") or [])
        state = str(row.get("annotation_state") or "unannotated")
        if is_training_ground_truth(state, boxes):
            effective_train.append(str(image_id))
        elif state == "unannotated" and not boxes and _processed_training_candidate(row):
            pending_annotation.append(str(image_id))
        else:
            invalid_train.append(str(image_id))

    if invalid_train:
        raise ValueError(
            "训练候选包含尚未清洗完成或标注状态不一致的素材: "
            + ", ".join(invalid_train[:5])
        )

    invalid_test: list[str] = []
    for image_id in split_request.test_image_ids:
        row = by_id[str(image_id)]
        if not is_training_ground_truth(
            row.get("annotation_state"),
            list(row.get("boxes") or []),
        ):
            invalid_test.append(str(image_id))
    if invalid_test:
        raise ValueError(
            "独立试验素材必须具备正式 Ground Truth，以下素材仍待标注: "
            + ", ".join(invalid_test[:5])
        )

    if not effective_train:
        raise ValueError(
            "已清洗未标注素材可以选入训练任务，但本轮没有任何正式标注素材可用于监督训练；"
            "请先完成至少一部分人工标注或 AI 标注审核确认"
        )

    effective_split = SplitRequest(
        mode=split_request.mode,
        train_image_ids=tuple(effective_train),
        test_image_ids=tuple(split_request.test_image_ids),
        experiment_percent=split_request.experiment_percent,
        validation_percent=split_request.validation_percent,
    )
    effective_ids = set((*effective_split.train_image_ids, *effective_split.test_image_ids))
    effective_images = tuple(
        row for row in images if str(row.get("id") or "") in effective_ids
    )
    if materials.current_revision() != material_revision or annotations.current_revision() != annotation_revision:
        raise ValueError("training selection changed during canonical truth read; repeat preflight")
    return TrainingSelectionResolution(
        requested_split=split_request,
        effective_split=effective_split,
        effective_images=effective_images,
        selected_train_image_ids=tuple(split_request.train_image_ids),
        pending_annotation_image_ids=tuple(pending_annotation),
        material_revision=material_revision,
        annotation_revision=annotation_revision,
    )


_TRAINING_INPUT_FREEZE_SCHEMA_VERSION = 1
_TRAINING_INPUT_FREEZE_FIELDS = (
    "id",
    "dataset_id",
    "filename",
    "stored_name",
    "stored_path",
    "path",
    "source_type",
    "source_ref",
    "video_task_id",
    "group_id",
    "source_group_id",
    "near_duplicate_group_id",
    "sequence_group_id",
    "camera_session_id",
    "capture_session_id",
    "camera_id",
    "session_id",
    "content_sha256",
    "size_bytes",
    "width",
    "height",
    "storage_source_id",
    "storage_type",
    "object_key",
    "etag",
    "source_available",
    "annotation_needs_review",
    "annotation_review_reason",
    "annotation_source_content_sha256",
    "negative_origin",
    "source_annotation_state",
    "source_annotation_hash",
    "source_labels",
    "training_excluded_boxes",
    "training_projection_policy",
    "training_projection_digest",
    "external_annotation",
    "external_annotation_needs_review",
    "external_annotation_review_reason",
    "annotation_state",
    "annotation_version",
    "annotation_scope",
    "annotation_hash",
    "annotated",
    "boxes",
)


def _training_input_freeze_digest(value: Mapping[str, Any]) -> str:
    payload = {
        key: item
        for key, item in value.items()
        if key not in {"created_at", "input_freeze_id"}
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _frozen_training_row(row: Mapping[str, Any]) -> dict[str, Any]:
    frozen = {
        key: row.get(key)
        for key in _TRAINING_INPUT_FREEZE_FIELDS
        if key in row
    }
    frozen["id"] = str(row.get("id") or "")
    frozen["content_sha256"] = str(row.get("content_sha256") or "").strip().lower()
    frozen["annotation_state"] = str(row.get("annotation_state") or "unannotated")
    frozen["annotation_scope"] = list(row.get("annotation_scope") or [])
    frozen["annotation_hash"] = str(row.get("annotation_hash") or "")
    frozen["boxes"] = [dict(box) for box in (row.get("boxes") or [])]
    return frozen


def _requested_new_training_labels(
    label_contract: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    return tuple(dict.fromkeys(
        str(code).strip()
        for code in (
            (label_contract or {}).get("requested_new_label_codes") or []
        )
        if str(code).strip()
    ))


def _training_split_quality(
    images: Sequence[Mapping[str, Any]],
    manifest: Any,
    label_schema: Sequence[Mapping[str, Any]],
    label_contract: Mapping[str, Any] | None = None,
    *,
    include_class_coverage: bool = False,
) -> dict[str, Any]:
    by_id = {str(row.get("id") or ""): row for row in images}
    role_box_counts: dict[str, int] = {}
    role_label_counts: dict[str, dict[str, int]] = {}
    for role in ("train", "validation", "test"):
        counts: dict[str, int] = {}
        box_total = 0
        for image_id in manifest.ids[role]:
            row = by_id.get(str(image_id)) or {}
            for box in row.get("boxes") or []:
                label = str(box.get("label") or box.get("code") or "").strip()
                if not label:
                    continue
                counts[label] = counts.get(label, 0) + 1
                box_total += 1
        role_box_counts[role] = box_total
        role_label_counts[role] = dict(sorted(counts.items()))
    if role_box_counts["train"] <= 0:
        raise ValueError("训练集没有任何正样本标注框；confirmed_empty 可作为负样本，但不能单独训练检测模型")
    if role_box_counts["validation"] <= 0:
        raise ValueError("验证集没有任何正样本标注框，无法得到有意义的检测指标；请增加正样本或调整划分")
    active_codes = [
        str(item.get("code") or "").strip()
        for item in label_schema
        if str(item.get("code") or "").strip()
    ]
    missing_train = [
        code for code in active_codes
        if role_label_counts["train"].get(code, 0) <= 0
    ]
    requested_new = _requested_new_training_labels(label_contract)
    unknown_requested_new = [
        code for code in requested_new if code not in set(active_codes)
    ]
    if unknown_requested_new:
        raise ValueError(
            "训练标签合同包含不在有效 schema 中的新增标签: "
            + ", ".join(unknown_requested_new[:20])
        )
    missing_requested_new = [
        code for code in requested_new
        if role_label_counts["train"].get(code, 0) <= 0
    ]
    if missing_requested_new:
        raise ValueError(
            "本次新增训练标签在训练集没有正样本: "
            + ", ".join(missing_requested_new[:20])
            + "；请增加对应正样本或调整训练/验证/试验划分后重试"
        )
    train_labels = {
        code for code, count in role_label_counts["train"].items()
        if count > 0
    }
    missing_validation = [
        code for code in sorted(train_labels)
        if role_label_counts["validation"].get(code, 0) <= 0
    ]
    warnings = []
    if missing_train:
        warnings.append(
            "启用标签在训练集缺少正样本: " + ", ".join(missing_train[:20])
        )
    if missing_validation:
        warnings.append(
            "训练标签在验证集缺少正样本，相关类别指标不可评估: "
            + ", ".join(missing_validation[:20])
        )
    quality = {
        "role_box_counts": role_box_counts,
        "role_label_counts": role_label_counts,
        "active_labels_without_train_positive": missing_train,
        "train_labels_without_validation_positive": missing_validation,
        "warnings": warnings,
    }
    if not include_class_coverage:
        # Frozen input contracts created before TQ-01 must replay exactly.
        # Never change their digest or historical quality evidence.
        return quality

    roles = ("train", "validation", "test")
    role_label_images: dict[str, dict[str, int]] = {}
    role_label_components: dict[str, dict[str, int]] = {}
    role_known_source_images: dict[str, int] = {}
    role_unknown_source_images: dict[str, int] = {}
    role_confirmed_negative_images: dict[str, int] = {}
    # Relationship identifiers such as group_id / near_duplicate_group_id
    # enforce leakage isolation but do NOT by themselves prove real
    # provenance (camera, collection session, original video).
    known_source_fields = (
        "source_group_id", "video_task_id", "camera_session_id",
        "capture_session_id",
    )
    for role in roles:
        positive_images: dict[str, int] = {}
        label_components: dict[str, set[str]] = {}
        known = unknown = negative = 0
        for image_id in manifest.ids[role]:
            row = by_id.get(str(image_id)) or {}
            code_set = {
                str(box.get("label") or box.get("code") or "").strip()
                for box in (row.get("boxes") or [])
                if isinstance(box, Mapping)
                and str(box.get("label") or box.get("code") or "").strip()
            }
            if not code_set and str(row.get("annotation_state") or "") == "confirmed_empty":
                negative += 1
            reliable_source = (
                any(str(row.get(key) or "").strip() for key in known_source_fields)
                or (
                    bool(str(row.get("camera_id") or "").strip())
                    and bool(str(row.get("session_id") or "").strip())
                )
            )
            if reliable_source:
                known += 1
            else:
                unknown += 1
            # Component keys are generated by the same leakage guard as the
            # split manifest. No component identity is inferred from names.
            component_key = str((getattr(manifest, "groups", None) or {}).get(str(image_id)) or str(image_id))
            for code in code_set:
                positive_images[code] = positive_images.get(code, 0) + 1
                label_components.setdefault(code, set()).add(component_key)
        role_label_images[role] = dict(sorted(positive_images.items()))
        role_label_components[role] = {
            code: len(components) for code, components in sorted(label_components.items())
        }
        role_known_source_images[role] = known
        role_unknown_source_images[role] = unknown
        role_confirmed_negative_images[role] = negative

    measured_labels = sorted(set(active_codes) | set().union(
        *(set(codes) for codes in role_label_images.values())
    ))
    missing_test = [
        code for code in sorted(train_labels)
        if role_label_images["test"].get(code, 0) == 0
    ]
    if missing_test:
        quality["warnings"].append(
            "训练标签在独立试验集缺少正样本，相关类别不能获得独立测试 AP: "
            + ", ".join(missing_test[:20])
        )
    quality["class_coverage"] = {
        "schema_version": 1,
        "label_image_counts": role_label_images,
        "label_independent_component_counts": role_label_components,
        "label_box_counts": role_label_counts,
        "role_confirmed_negative_image_counts": role_confirmed_negative_images,
        "role_known_source_image_counts": role_known_source_images,
        "role_unknown_source_image_counts": role_unknown_source_images,
        "active_label_codes": measured_labels,
        "train_labels_without_validation_positive": missing_validation,
        "train_labels_without_test_positive": missing_test,
        "provenance_status": (
            "partial_unknown"
            if any(role_unknown_source_images.values()) else "declared_source_fields_present"
        ),
    }
    if (getattr(manifest, "requested", None) or {}).get("split_strategy") == "multilabel_grouped_v2":
        diagnostics: dict[str, Any] = {}
        for code in measured_labels:
            component_supply = sum(
                role_label_components[role].get(code, 0) for role in roles
            )
            present = [
                role for role in roles if role_label_components[role].get(code, 0)
            ]
            missing = [role for role in roles if role not in present]
            if not missing:
                reason = "all_roles_covered"
            elif component_supply == 0:
                reason = "no_positive_examples"
            elif (manifest.mode == SplitMode.INDEPENDENT_TEST_SET and "test" in missing):
                reason = "fixed_independent_test_has_no_positive"
            elif component_supply < 3:
                reason = "insufficient_independent_components"
            else:
                reason = "coupled_groups_or_holdout_quota"
            diagnostics[code] = {
                "independent_component_count": component_supply,
                "positive_roles": present,
                "missing_roles": missing,
                "reason": reason,
            }
        quality["class_coverage"]["partition_diagnostics"] = diagnostics
        quality["class_coverage"]["partition_strategy"] = "multilabel_grouped_v2"
    return quality



def _training_annotation_admission(
    images: Sequence[Mapping[str, Any]],
    label_schema: Sequence[Mapping[str, Any]],
    *,
    strict_catalog: bool = False,
) -> dict[str, Any]:
    """Bounded, read-only quality admission of this exact projected GT selection.

    Existing CLEAN audits are historical artifacts, not proof that the current
    train/validation/test input passes. Do not mutate the source annotation.
    """
    from .annotation_quality import _audit_boxes

    allowed = {
        str(item.get("code") or "").strip()
        for item in label_schema if str(item.get("code") or "").strip()
    }
    counts: dict[str, int] = {}
    severities = {"blocking": 0, "manual_review": 0, "warning": 0}
    samples: dict[str, list[str]] = {key: [] for key in severities}
    missing_dimensions = 0
    blocker_codes = {
        "label_missing", "label_unknown", "label_disabled",
        "box_invalid", "box_out_of_bounds", "annotation_state_inconsistent",
    }
    review_codes = {
        "box_tiny", "box_large", "box_duplicate_exact",
        "box_duplicate_iou", "box_pairwise_unchecked",
        "dimensions_unknown", "annotation_needs_review",
    }

    def record(code: str, image_id: str, multiplicity: int = 1) -> None:
        severity = (
            "blocking" if code in blocker_codes else
            "manual_review" if code in review_codes else "warning"
        )
        count = max(1, int(multiplicity))
        counts[code] = counts.get(code, 0) + count
        severities[severity] += count
        if len(samples[severity]) < 10 and image_id not in samples[severity]:
            samples[severity].append(image_id)

    for row in images:
        image_id = str(row.get("id") or "")
        raw_boxes = list(row.get("boxes") or [])
        state = str(row.get("annotation_state") or ("annotated" if raw_boxes else "unannotated")).strip().lower()
        if (state == "annotated" and not raw_boxes or
                state == "confirmed_empty" and raw_boxes or
                state not in {"annotated", "confirmed_empty"}):
            record("annotation_state_inconsistent", image_id)
        if row.get("annotation_needs_review") or row.get("external_annotation_needs_review"):
            record("annotation_needs_review", image_id)
        if not raw_boxes:
            continue
        if strict_catalog and not allowed:
            # A declared project catalog with zero ACTIVE labels must never
            # silently treat all excluded GT labels as acceptable.
            for candidate in raw_boxes:
                if isinstance(candidate, Mapping):
                    record("label_unknown", image_id)
        try:
            width = int(row.get("width") or 0)
            height = int(row.get("height") or 0)
        except (TypeError, ValueError, OverflowError):
            width = height = 0
        if width <= 0 or height <= 0:
            missing_dimensions += 1
            record("dimensions_unknown", image_id)
        translated: list[dict[str, Any]] = []
        for box in raw_boxes:
            if not isinstance(box, Mapping):
                translated.append({})
                continue
            candidate = dict(box)
            if not all(key in candidate for key in ("x1", "y1", "x2", "y2")):
                if all(key in candidate for key in ("cx", "cy", "w", "h")):
                    try:
                        cx, cy, bw, bh = (
                            float(candidate[key]) for key in ("cx", "cy", "w", "h")
                        )
                        if all(math.isfinite(value) for value in (cx, cy, bw, bh)):
                            # Match _yolo_line's normalized-vs-pixel semantics.
                            if max(abs(cx), abs(cy), abs(bw), abs(bh)) <= 1:
                                cx, cy = cx * max(1, width), cy * max(1, height)
                                bw, bh = bw * max(1, width), bh * max(1, height)
                            candidate.update(
                                x1=cx - bw / 2, y1=cy - bh / 2,
                                x2=cx + bw / 2, y2=cy + bh / 2,
                            )
                    except (TypeError, ValueError, OverflowError):
                        pass
            translated.append(candidate)
        issues, _density, _per_class, _heatmap = _audit_boxes(
            translated,
            width=width, height=height,
            known_labels=allowed, disabled_labels=set(),
            pairwise_box_limit=32,
        )
        for issue in issues:
            record(
                str(issue.get("code") or "unknown"),
                image_id,
                int(issue.get("count") or 1),
            )

    result = {
        "schema_version": 1,
        "scope": "projected_frozen_training_selection",
        "audited_images": len(images),
        "issue_counts": dict(sorted(counts.items())),
        "severity_counts": severities,
        "sample_image_ids_by_severity": samples,
        "images_with_unverified_dimensions": missing_dimensions,
        "gt_mutated": False,
    }
    if severities["blocking"]:
        reason_codes = sorted(code for code in counts if code in blocker_codes)
        raise ValueError(
            "TRAINING_ANNOTATION_ADMISSION_BLOCKED: 当前训练选择包含无效正式标注 "
            + ", ".join(reason_codes[:8])
            + "；素材示例 " + ", ".join(samples["blocking"][:5])
            + "；请人工修正正式 GT 后重新创建任务"
        )
    return result



def _training_source_projection_admission(
    project: Path,
    original: Sequence[Mapping[str, Any]],
    projected: Sequence[Mapping[str, Any]],
    label_schema: Sequence[Mapping[str, Any]],
    label_contract: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Check original GT *before* label filtering and verify task projection.

    A projected-only box audit can miss an invalid excluded object that will be
    redacted when building the training image. Never read mutable live GT here:
    both sequences are from the same fenced training selection.
    """
    from .training_label_tasks import project_training_rows

    meta = _json(project / "meta.json", {})
    labels = list(meta.get("labels") or []) if isinstance(meta, Mapping) else []
    label_meta = list(meta.get("label_meta") or []) if isinstance(meta, Mapping) else []
    active_codes: list[str] = []
    for index in range(max(len(labels), len(label_meta))):
        item = label_meta[index] if index < len(label_meta) else {}
        entry = dict(item) if isinstance(item, Mapping) else {}
        raw = labels[index] if index < len(labels) else ""
        code = str(entry.get("code") or (
            (raw.get("code") or raw.get("name")) if isinstance(raw, Mapping) else raw
        ) or "").strip()
        if not code or entry.get("active") is False:
            continue
        if str(entry.get("status") or "active").strip().lower() != "active":
            continue
        active_codes.append(code)
    # Existing test fixtures and legacy import projects can have no label
    # catalog. Do not manufacture a false missing-label blocker in that case;
    # their task-local effective schema remains the only asserted catalog.
    declared_catalog = bool(labels or label_meta)
    source_schema = (
        [{"code": code} for code in dict.fromkeys(active_codes)]
        if declared_catalog else [
            {"code": code} for code in dict.fromkeys([
                *(str(item.get("code") or "").strip() for item in label_schema),
                *(
                    str(box.get("label") or box.get("code") or "").strip()
                    for row in original for box in (row.get("boxes") or [])
                    if isinstance(box, Mapping)
                ),
            ]) if code
        ]
    )
    source_audit = _training_annotation_admission(
        original, source_schema, strict_catalog=declared_catalog,
    )
    effective_codes = (label_contract or {}).get("effective_label_codes") or ()
    if effective_codes:
        expected = project_training_rows(original, label_contract or {})
    else:
        expected = original
    if len(expected) != len(projected):
        raise ValueError(
            "TRAINING_PROJECTION_MISMATCH: 原始 GT 与本次投影素材数量不一致"
        )

    # These fields are the actual label/pixel-redaction contract. Ignore
    # unrelated UI annotations; never compare to live repository revisions.
    protected = (
        "id", "content_sha256", "size_bytes", "width", "height",
        "annotation_state", "annotation_scope", "boxes", "annotated",
        "negative_origin", "source_annotation_state", "source_annotation_hash",
        "source_labels", "training_excluded_boxes",
        "training_projection_policy", "training_projection_digest",
    )
    projected_negatives = reviewed_original_negatives = excluded_objects = 0
    for expected_row, actual_row in zip(expected, projected):
        image_id = str(expected_row.get("id") or "")
        for key in protected:
            if expected_row.get(key) != actual_row.get(key):
                raise ValueError(
                    f"TRAINING_PROJECTION_MISMATCH: 素材 {image_id} 的 {key} "
                    "与正式 GT 和训练标签投影合同不一致；请重新创建训练任务"
                )
        excluded_objects += len(actual_row.get("training_excluded_boxes") or [])
        if str(actual_row.get("negative_origin") or "") == "redacted_unselected_labels":
            projected_negatives += 1
        elif str(actual_row.get("negative_origin") or "") == "reviewed_task_negative":
            reviewed_original_negatives += 1

    return {
        "schema_version": 1,
        "source_ground_truth_admission": source_audit,
        "projection_consistency": {
            "schema_version": 1,
            "verified_images": len(projected),
            "excluded_source_object_count": excluded_objects,
            "redacted_task_negative_image_count": projected_negatives,
            "reviewed_original_negative_image_count": reviewed_original_negatives,
            "status": "verified_against_fenced_original_gt",
            "original_source_retained_in_freeze": False,
        },
    }


def freeze_training_inputs(
    project: Path,
    split_request: SplitRequest,
    *,
    seed: int,
    supplement_candidate_set: Mapping[str, Any] | None = None,
    selection_resolution: TrainingSelectionResolution | None = None,
    effective_images: Sequence[Mapping[str, Any]] | None = None,
    label_schema_override: Sequence[Mapping[str, Any]] | None = None,
    label_contract: Mapping[str, Any] | None = None,
    duplicate_review: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze formal DB truth at submit time without reading/copying source bytes."""
    if selection_resolution is None:
        original_images = _selected_project_images(MaterialRepository(project), project,
            (*split_request.train_image_ids, *split_request.test_image_ids))
        assert_training_duplicate_safety(original_images,
            split_request.train_image_ids, split_request.test_image_ids)
    resolution = selection_resolution or resolve_training_selection(project, split_request)
    if resolution.requested_split != split_request:
        raise ValueError("training selection resolution does not match the requested split")
    if ((resolution.material_revision is not None and
            MaterialRepository(project).current_revision() != resolution.material_revision)
            or (resolution.annotation_revision is not None and
            AnnotationRepository(project).current_revision() != resolution.annotation_revision)):
        raise ValueError("training selection changed before input freeze; repeat preflight")
    if duplicate_review:
        from .training_compatibility import validate_duplicate_review
        validate_duplicate_review(project, {"duplicate_review": duplicate_review}, split_request)
    effective_split = resolution.effective_split
    source_images = [dict(row) for row in resolution.effective_images]
    # Original formal GT must be checked before task-label projection can hide
    # an out-of-scope category, empty-state, or coordinate disagreement.
    assert_training_duplicate_safety(
        source_images, effective_split.train_image_ids, effective_split.test_image_ids,
    )
    images = (
        [dict(row) for row in effective_images]
        if effective_images is not None
        else source_images
    )
    source_ids = [str(row.get("id") or "") for row in source_images]
    projected_ids = [str(row.get("id") or "") for row in images]
    if projected_ids != source_ids:
        raise ValueError("projected training images must preserve frozen selection identity/order")
    if not _indexed_content_identity_ready(images):
        invalid = [
            str(row.get("id") or "")
            for row in images
            if not _indexed_content_identity_ready([row])
        ]
        raise ValueError(
            "训练素材缺少可冻结的 SHA256/size 身份: "
            + ", ".join(invalid[:5])
            + "；请先重新扫描/导入建立内容身份后再训练"
        )
    label_schema = (
        [dict(item) for item in label_schema_override]
        if label_schema_override is not None
        else _label_schema(project)
    )
    if not label_schema:
        raise ValueError("training label schema is empty")
    # Source audit must precede projected GT audit. Legitimate dropped labels
    # are validated against the project catalog, not the task's reduced schema.
    source_projection = _training_source_projection_admission(
        project, source_images, images, label_schema, label_contract,
    )
    annotation_admission = _training_annotation_admission(images, label_schema)
    manifest = build_split_manifest(
        images,
        effective_split,
        seed=int(seed),
        required_train_labels=_requested_new_training_labels(label_contract),
        split_strategy="multilabel_grouped_v2",
    )
    input_quality = _training_split_quality(
        images, manifest, label_schema, label_contract=label_contract,
        include_class_coverage=True,
    )
    input_quality["annotation_admission"] = annotation_admission
    input_quality["source_ground_truth_admission"] = source_projection["source_ground_truth_admission"]
    input_quality["projection_consistency"] = source_projection["projection_consistency"]
    snapshot = build_snapshot(
        images,
        manifest,
        label_schema,
        supplement_candidate_set=supplement_candidate_set,
    )
    split_truth = {
        "mode": effective_split.mode.value,
        "train_image_ids": list(effective_split.train_image_ids),
        "test_image_ids": list(effective_split.test_image_ids),
        "experiment_percent": effective_split.experiment_percent,
        "validation_percent": effective_split.validation_percent,
        "seed": int(seed),
    }
    value = {
        "schema_version": _TRAINING_INPUT_FREEZE_SCHEMA_VERSION,
        "split_strategy": "multilabel_grouped_v2",
        "split": split_truth,
        "images": [_frozen_training_row(row) for row in images],
        "label_schema": [dict(item) for item in label_schema],
        "snapshot_id": str(snapshot["snapshot_id"]),
        "dataset_revision_id": str(snapshot["dataset_revision_id"]),
        "input_quality": input_quality,
        "selection": resolution.truth(),
        "material_revision": resolution.material_revision,
        "annotation_revision": resolution.annotation_revision,
        "original_ground_truth": [{"image_id": str(row.get("id") or ""),
            "annotation_state": str(row.get("annotation_state") or "unannotated"),
            "annotation_scope": list(row.get("annotation_scope") or []),
            "box_count": len(row.get("boxes") or []),
            "annotation_digest": training_annotation_digest(row),
            "content_sha256": str(row.get("content_sha256") or ""),
        } for row in source_images],
        **({"duplicate_review": dict(duplicate_review)} if duplicate_review else {}),
        **(
            {"label_contract": {
                key: item for key, item in dict(label_contract).items()
                if key != "project_path"
            }}
            if label_contract is not None else {}
        ),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    value["input_freeze_id"] = _training_input_freeze_digest(value)
    # Material index writers can advance a revision during split/snapshot work.
    # Validate the same original selection again at the freeze publication point.
    if ((resolution.material_revision is not None and
            MaterialRepository(project).current_revision() != resolution.material_revision)
            or (resolution.annotation_revision is not None and
            AnnotationRepository(project).current_revision() != resolution.annotation_revision)):
        raise ValueError("training selection changed while building input freeze; repeat preflight")
    return value


def resolve_training_input_freeze(
    value: Mapping[str, Any],
    split_request: SplitRequest,
    *,
    seed: int,
    supplement_candidate_set: Mapping[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Any, dict[str, Any]]:
    """Validate frozen submit truth and reproduce its split/snapshot deterministically."""
    if int(value.get("schema_version") or 0) != _TRAINING_INPUT_FREEZE_SCHEMA_VERSION:
        raise ValueError("training input freeze schema version is unsupported")
    actual_freeze_id = str(value.get("input_freeze_id") or "").strip().lower()
    expected_freeze_id = _training_input_freeze_digest(value)
    if not actual_freeze_id or actual_freeze_id != expected_freeze_id:
        raise ValueError("training input freeze digest mismatch")
    expected_split = {
        "mode": split_request.mode.value,
        "train_image_ids": list(split_request.train_image_ids),
        "test_image_ids": list(split_request.test_image_ids),
        "experiment_percent": split_request.experiment_percent,
        "validation_percent": split_request.validation_percent,
        "seed": int(seed),
    }
    if dict(value.get("split") or {}) != expected_split:
        raise ValueError("training payload no longer matches its frozen input selection")
    images = [dict(row) for row in (value.get("images") or []) if isinstance(row, Mapping)]
    expected_ids = tuple(dict.fromkeys(
        str(item).strip()
        for item in (*split_request.train_image_ids, *split_request.test_image_ids)
        if str(item).strip()
    ))
    actual_ids = tuple(str(row.get("id") or "") for row in images)
    if actual_ids != expected_ids:
        raise ValueError("training input freeze image identity/order mismatch")
    if not _indexed_content_identity_ready(images):
        raise ValueError("training input freeze contains invalid content identity")
    label_schema = [
        dict(item)
        for item in (value.get("label_schema") or [])
        if isinstance(item, Mapping)
    ]
    frozen_contract = value.get("label_contract")
    if isinstance(frozen_contract, Mapping) and frozen_contract:
        contract_schema = [
            dict(item)
            for item in (frozen_contract.get("effective_label_schema") or [])
            if isinstance(item, Mapping)
        ]
        if contract_schema != label_schema:
            raise ValueError("training input freeze label contract/schema mismatch")
    manifest = build_split_manifest(
        images,
        split_request,
        seed=int(seed),
        required_train_labels=_requested_new_training_labels(
            frozen_contract if isinstance(frozen_contract, Mapping) else None
        ),
        # Pre-v2 freezes carry no marker: replay the historical split exactly.
        split_strategy=str(value.get("split_strategy") or "legacy_v1"),
    )
    frozen_quality = value.get("input_quality") if isinstance(value.get("input_quality"), Mapping) else {}
    input_quality = _training_split_quality(
        images,
        manifest,
        label_schema,
        label_contract=(
            frozen_contract if isinstance(frozen_contract, Mapping) else None
        ),
        include_class_coverage="class_coverage" in frozen_quality,
    )
    if "annotation_admission" in frozen_quality:
        # Only new freezes carry this key; keep legacy input_quality byte-for-byte.
        input_quality["annotation_admission"] = _training_annotation_admission(
            images, label_schema,
        )
    # The unfiltered original GT is intentionally not duplicated into the
    # frozen worker payload. It cannot be re-audited from today's mutable DB.
    # Instead, the source attestation is protected by input_freeze_id and
    # anchored to original_ground_truth digests in this frozen contract.
    if "source_ground_truth_admission" in frozen_quality:
        original_evidence = value.get("original_ground_truth")
        source_audit = frozen_quality["source_ground_truth_admission"]
        projection_proof = frozen_quality.get("projection_consistency")
        if (not isinstance(source_audit, Mapping)
                or not isinstance(projection_proof, Mapping)
                or not isinstance(original_evidence, list)
                or len(original_evidence) != len(images)
                or int(source_audit.get("audited_images") or -1) != len(images)
                or int(projection_proof.get("verified_images") or -1) != len(images)
                or str(projection_proof.get("status") or "") != "verified_against_fenced_original_gt"):
            raise ValueError("training frozen source GT attestation is incomplete")
        input_quality["source_ground_truth_admission"] = dict(source_audit)
        input_quality["projection_consistency"] = dict(projection_proof)
    if dict(value.get("input_quality") or {}) != input_quality:
        raise ValueError("training input freeze quality evidence mismatch")
    snapshot = build_snapshot(
        images,
        manifest,
        label_schema,
        supplement_candidate_set=supplement_candidate_set,
    )
    if str(snapshot.get("snapshot_id") or "") != str(value.get("snapshot_id") or ""):
        raise ValueError("training input freeze snapshot identity mismatch")
    if str(snapshot.get("dataset_revision_id") or "") != str(
        value.get("dataset_revision_id") or ""
    ):
        raise ValueError("training input freeze dataset revision mismatch")
    return images, label_schema, manifest, snapshot


def _training_python(data_dir: Path) -> str:
    return training_python(data_dir)


def _resolve_resource_contract_subprocess(
    python_executable: str,
    request: Mapping[str, Any],
    resource_context: Mapping[str, Any],
    model_argument: str,
) -> dict[str, Any]:
    """Run the one canonical resolver in the selected Ultralytics runtime."""
    root = Path(__file__).resolve().parent.parent
    env = {
        **os.environ,
        "PYTHONUTF8": "1",
        "PYTHONIOENCODING": "utf-8",
    }
    existing_pythonpath = str(env.get("PYTHONPATH") or "").strip()
    env["PYTHONPATH"] = (
        str(root) + (os.pathsep + existing_pythonpath if existing_pythonpath else "")
    )
    with tempfile.TemporaryDirectory(prefix="training-resource-resolve-") as temporary:
        private_root = Path(temporary)
        request_path = private_root / "resource-request.json"
        context_path = private_root / "resource-context.json"
        private_output = private_root / "resolved-resources.json"
        request_path.write_text(
            json.dumps(dict(request), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        context_path.write_text(
            json.dumps(dict(resource_context), ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        try:
            completed = subprocess.run(
                [
                    str(python_executable),
                    "-m",
                    "platform_core.training_metrics",
                    "--request", str(request_path),
                    "--context", str(context_path),
                    "--model", str(model_argument),
                    "--output", str(private_output),
                ],
                cwd=root,
                env=env,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=300,
                check=False,
            )
        except (OSError, subprocess.SubprocessError) as error:
            raise RuntimeError(
                f"RESOURCE_PREPARE_FAILED: {type(error).__name__}: {error}"
            ) from error
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "resource resolver failed").strip()
            canonical = re.findall(r"\b([A-Z][A-Z0-9_]{2,}):\s*([^\r\n]+)", detail)
            if canonical:
                code, message = canonical[-1]
                raise RuntimeError(f"{code}: {message.strip()}")
            raise RuntimeError("RESOURCE_PREPARE_FAILED: " + detail[-4000:])
        resolved = json.loads(private_output.read_text(encoding="utf-8"))
    if not (
        isinstance(resolved, dict)
        and int(resolved.get("resolved_batch") or 0) > 0
        and int(
            resolved.get("resolved_workers")
            if resolved.get("resolved_workers") is not None else -1
        ) >= 0
        and str(resolved.get("resource_strategy") or "")
        == str(request.get("resource_strategy") or "auto")
    ):
        raise RuntimeError("RESOURCE_PREPARE_REQUIRED: resolved resource contract is missing or invalid")
    return dict(resolved)


def _freeze_deferred_resource_contract(
    context,
    *,
    python_executable: str,
    payload: Mapping[str, Any],
    resource_context: Mapping[str, Any],
    model_argument: str,
    bundle: Path,
    assigned_device: str,
) -> dict[str, Any]:
    """Resolve once against the owned assignment, then fenced-publish truth."""
    context.heartbeat(
        progress=19,
        stage="resolving_resources",
        current_item="按已分配 GPU 冻结 Batch / Workers / Precision / Cache",
    )
    request = {
        **payload,
        "data": str(Path(bundle) / "manifest.json"),
        "device": assigned_device,
        "assigned_device": assigned_device,
    }
    resolved = _resolve_resource_contract_subprocess(
        python_executable,
        request,
        resource_context,
        model_argument,
    )
    context.artifacts.atomic_write_json(
        context.task.task_id,
        "resolved-resources.json",
        resolved,
    )
    return resolved


def _bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def _training_argv(data_dir: Path, project: Path, task_id: str, payload: Mapping[str, Any], data_yaml: Path, model: str,
                   *, python_executable: str | None = None) -> list[str]:
    root = Path(__file__).resolve().parent.parent
    device = normalize_training_device(payload.get("assigned_device"))
    if device == "auto":
        raise ValueError("GPU_ASSIGNMENT_REQUIRED: training argv requires an assigned concrete device")
    argv = [
        python_executable or _training_python(data_dir),
        str(root / "train_worker.py"),
        "--project-dir", str(project),
        "--data", str(data_yaml),
        "--model", str(model),
        "--epochs", str(int(payload.get("epochs") or 50)),
        "--imgsz", str(int(payload.get("imgsz") or 640)),
        "--batch", str(int(payload.get("resolved_batch", payload.get("batch", 8)))),
        "--device", device.removeprefix("cuda:"),
        "--assigned-device", device,
        "--requested-device", normalize_training_device(payload.get("requested_device", payload.get("device"))),
        "--job-id", task_id,
        "--run-name", f"train_{task_id}",
        "--resource-strategy", str(payload.get("resource_strategy") or "auto"),
        "--resource-profile", str(payload.get("resource_profile") or "performance"),
        "--gpu-policy", str(payload.get("gpu_policy") or "exclusive"),
        "--precision", str(payload.get("resolved_precision") or payload.get("precision") or "auto"),
    ]
    value_options = {
        "patience": 40, "workers": 0, "optimizer": "auto", "lr0": 0.01,
        "lrf": 0.01, "weight_decay": 0.0005, "close_mosaic": 10,
        "mosaic": 1.0, "cache": "False", "freeze": 0, "momentum": 0.937,
        "warmup_epochs": 3.0, "save_period": -1, "seed": 0,
        "multi_scale": 0.0, "hsv_h": 0.015, "hsv_s": 0.7, "hsv_v": 0.4,
        "degrees": 0.0, "translate": 0.1, "scale": 0.5, "shear": 0.0,
        "perspective": 0.0, "flipud": 0.0, "fliplr": 0.5, "mixup": 0.0,
        "val_max_samples": 0, "eval_interval": 0, "eval_metric": "map50",
        "continue_threshold": 0.0, "stop_threshold": 0.0,
    }
    for key, default in value_options.items():
        value = payload.get(f"resolved_{key}", payload.get(key, default)) if key in {"workers", "cache"} else payload.get(key, default)
        argv.extend([f"--{key.replace('_', '-')}", str(value)])
    if payload.get("time") is not None:
        argv.extend(["--time", str(float(payload.get("time")))])
    for key, default in {
        "single_cls": False, "pretrained": True, "rect": False, "amp": True,
        "cos_lr": False, "deterministic": True, "early_stopping_enabled": False, "auto_supplement": False,
        "ai_intervention": False,
    }.items():
        payload_key = "ai_intervention_enabled" if key == "ai_intervention" else key
        argv.extend([f"--{key.replace('_', '-')}", _bool(payload.get(payload_key, default))])
    argv.extend(["--supplement-count", str(int(payload.get("supplement_count") or 0))])
    for option in ("resource_context", "resource_resolution", "metrics_db"):
        if payload.get(option):
            argv.extend(["--" + option.replace("_", "-"), str(payload[option])])
    argv.extend(["--runtime-stop-policy", "target_only"])
    return argv


def _verified_job_model_paths(job: Mapping[str, Any]) -> list[Path]:
    paths = []
    for value in job.get("verified_models") or []:
        if isinstance(value, Mapping):
            value = value.get("path") or value.get("stored_path") or value.get("source")
        raw = str(value or "").strip()
        if raw:
            paths.append(Path(raw))
    return paths


def _training_completion_error(
    job: Mapping[str, Any],
    *,
    expected_task_id: str | None = None,
    expected_snapshot_id: str | None = None,
    expected_models_root: Path | None = None,
) -> str | None:
    if expected_task_id:
        job_task_id = str(job.get("task_id") or job.get("id") or "").strip()
        if job_task_id != str(expected_task_id):
            return "training job identity does not match the durable task"
    if expected_snapshot_id:
        if str(job.get("snapshot_id") or "").strip() != str(expected_snapshot_id):
            return "training snapshot identity does not match the durable task"
    if str(job.get("status") or "").strip().lower() != "done":
        return "job status is not done"
    if job.get("artifact_verified") is not True:
        return "model artifact verification is incomplete"
    if not str(job.get("finished_at") or "").strip():
        return "training finished_at is missing"
    outcome = str(job.get("training_outcome") or "").strip().lower()
    if outcome not in _SUCCESSFUL_TRAINING_OUTCOMES:
        return f"training outcome is not terminal success: {outcome or '<missing>'}"
    paths = _verified_job_model_paths(job)
    if not paths:
        return "verified model list is empty"
    if expected_models_root is not None:
        models_root = expected_models_root.resolve()
        for path in paths:
            try:
                path.resolve().relative_to(models_root)
            except ValueError:
                return "verified model is outside the project model directory"
    best_or_last = {
        str(Path(str(job.get(key))).resolve())
        for key in ("best_path", "last_path")
        if str(job.get(key) or "").strip()
    }
    if not best_or_last:
        return "verified best/last model is missing"
    verified_existing = {
        str(path.resolve())
        for path in paths
        if path.is_file() and path.stat().st_size > 0
    }
    if not verified_existing.intersection(best_or_last):
        return "verified best/last model file is missing or empty"
    return None


def _run_training_process(context, argv: Sequence[str], job_file: Path) -> dict[str, Any]:
    artifact_log = context.artifacts.artifact_path(context.task.task_id, context.task.log_ref)
    artifact_log.parent.mkdir(parents=True, exist_ok=True)
    log_path = job_file.parent / "train.log"
    root = Path(__file__).resolve().parent.parent
    snapshot = context.artifacts.read_json(context.task.task_id, "snapshot.json", default={})
    expected_snapshot_id = (
        str(snapshot.get("snapshot_id") or "").strip()
        if isinstance(snapshot, Mapping)
        else ""
    )
    expected_models_root = (job_file.parent.parent.parent / "models").resolve()
    try:
        with log_path.open("a", encoding="utf-8", newline="") as log:
            launched = launch_process(
                argv,
                cwd=root,
                env={**os.environ, **execution_environment(context), "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            context.bind_process(launched.identity)
            controller = ProcessController()
            next_metrics = 0.0
            completion_seen_at = None
            while launched.process.poll() is None:
                if context.cancel_requested():
                    try:
                        controller.terminate_tree(launched.identity)
                    except PermissionError as error:
                        # Do not release the task/GPU lease while the exact
                        # process tree cannot be proven stopped. Keep managing
                        # the cancellation and retry instead of publishing a
                        # false CANCELLED terminal state.
                        context.heartbeat(
                            stage="cancelling",
                            current_item=f"waiting for verified process cleanup: {error}",
                        )
                        time.sleep(0.25)
                        continue
                    raise InterruptedError("training cancelled")
                job = _json(job_file, {})
                if _training_completion_error(
                    job,
                    expected_task_id=context.task.task_id,
                    expected_snapshot_id=expected_snapshot_id or None,
                    expected_models_root=expected_models_root,
                ) is None:
                    completion_seen_at = completion_seen_at or time.monotonic()
                    context.heartbeat(
                        progress=95,
                        stage="finalizing",
                        current_item="verified training complete; finalizing",
                    )
                    if time.monotonic() - completion_seen_at >= TRAINING_COMPLETION_GRACE_SECONDS:
                        # Business completion is already durable and the model files
                        # are verified. End only this exact bound process tree so
                        # lingering DataLoader/telemetry threads cannot block commit.
                        try:
                            controller.terminate_tree(launched.identity)
                        except PermissionError as error:
                            # A verified model is not permission to release a
                            # GPU that an unverified process may still use.
                            context.heartbeat(
                                progress=95,
                                stage="finalizing",
                                current_item=f"waiting for verified process cleanup: {error}",
                            )
                            time.sleep(0.25)
                            continue
                        break
                    time.sleep(0.1)
                    continue
                completion_seen_at = None
                current_task = context.assert_current_execution()
                if current_task is not None and current_task.stage == "paused":
                    context.heartbeat(
                        stage="paused",
                    )
                    time.sleep(0.25)
                    continue
                if time.monotonic() >= next_metrics:
                    metrics = read_metrics(context.artifacts.artifact_path(context.task.task_id, "training-metrics.sqlite3"))
                    # Feed scheduler evidence with ownership fencing; never infer unknown CPU/IO pressure.
                    from .gpu_resources import update_reservation_evidence
                    context.run_owned(lambda: update_reservation_evidence(context.repository, context.lease, metrics))
                    next_metrics = time.monotonic() + 5
                progress = float(job.get("progress_percent") or 20)
                current = str(job.get("current_item") or job.get("message") or job.get("current_epoch") or "") or None
                training_started = bool(
                    job.get("training_started") or job.get("current_epoch") or job.get("training_progress")
                )
                context.heartbeat(
                    progress=max(20, min(95, progress)),
                    stage="training" if training_started else "trainer_startup",
                    current_item=current,
                )
                time.sleep(0.25)
    finally:
        if log_path.is_file():
            shutil.copy2(log_path, artifact_log)
    job = _json(job_file, {})
    if context.cancel_requested():
        raise InterruptedError("training cancelled")
    completion_error = _training_completion_error(
        job,
        expected_task_id=context.task.task_id,
        expected_snapshot_id=expected_snapshot_id or None,
        expected_models_root=expected_models_root,
    )
    if completion_error is None:
        return job
    if launched.process.returncode != 0:
        raise RuntimeError(str(job.get("message") or f"training process exited {launched.process.returncode}"))
    raise RuntimeError(f"training process exited without a trusted completion handshake: {completion_error}")


def _completion_int(*values: Any) -> int:
    for value in values:
        try:
            number = int(float(value))
        except (TypeError, ValueError):
            continue
        if number >= 0:
            return number
    return 0


def _training_completion_metadata(job: Mapping[str, Any], payload: Mapping[str, Any]) -> dict[str, Any]:
    progress = job.get("training_progress") if isinstance(job.get("training_progress"), dict) else {}
    completed_epochs = _completion_int(job.get("completed_epochs"), progress.get("epoch"), job.get("current_epoch"))
    requested_epochs = _completion_int(
        job.get("requested_epochs"), progress.get("total_epochs"), job.get("total_epochs"), job.get("epochs"), payload.get("epochs")
    )
    outcome = str(job.get("training_outcome") or "completed").strip() or "completed"
    report = job.get("training_report") if isinstance(job.get("training_report"), dict) else {}
    quality_gate_reason = str(job.get("quality_gate_reason") or report.get("quality_gate_reason") or "").strip()
    explicit_reason = str(job.get("completion_reason") or "").strip()
    if explicit_reason:
        completion_reason = explicit_reason
    elif outcome == "target_reached":
        completion_reason = "quality_target_reached"
    elif outcome == "needs_optimization":
        completion_reason = "quality_gate_below_continue_threshold"
    elif completed_epochs > 0 and requested_epochs > 0 and completed_epochs < requested_epochs:
        completion_reason = "early_stopping"
    elif completed_epochs > 0 and requested_epochs > 0:
        completion_reason = "requested_epochs_completed"
    else:
        completion_reason = "completed"
    return {
        "completed_epochs": completed_epochs,
        "requested_epochs": requested_epochs,
        "training_outcome": outcome,
        "completion_reason": completion_reason,
        "quality_gate_reason": quality_gate_reason or None,
        "early_stopping_reason": job.get("early_stopping_reason"),
        "early_stopping_patience": job.get("early_stopping_patience"),
        "best_epoch": job.get("best_epoch"),
        "completion_message": job.get("message"),
        "training_finished_at": job.get("finished_at"),
        "training_message": job.get("message"),
    }


def resolve_frozen_training_base(
    payload: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Resolve and verify the submit-time base-model contract.

    New durable tasks freeze the exact iteration checkpoint before queueing.
    Historical tasks without this contract retain the compatibility reselect
    path in TrainingHandler.
    """
    contract = payload.get("label_contract")
    if not isinstance(contract, Mapping):
        return None
    if int(contract.get("base_model_contract_schema_version") or 0) != 1:
        return None

    framework = str(payload.get("framework") or "ultralytics").strip().lower()
    contract_framework = str(contract.get("framework") or framework).strip().lower()
    if contract_framework != framework:
        raise ValueError(
            "frozen training base framework does not match task framework"
        )

    mode = str(contract.get("base_training_mode") or "").strip()
    version_id = str(contract.get("base_version_id") or "").strip()
    version_name = str(contract.get("base_version_name") or "")
    reference = str(contract.get("base_model_reference") or "").strip()
    expected_sha = str(contract.get("base_model_sha256") or "").strip().lower()
    try:
        expected_size = int(contract.get("base_model_size_bytes") or 0)
    except (TypeError, ValueError) as error:
        raise ValueError("frozen training base size is invalid") from error

    if mode == "previous_weights_init":
        if not version_id or not reference or len(expected_sha) != 64 or expected_size <= 0:
            raise ValueError("frozen iteration base model evidence is incomplete")
    elif mode == "mother_model_init":
        if version_id:
            raise ValueError("mother-model training cannot freeze a previous version id")
        if not reference:
            raise ValueError("frozen mother model reference is empty")
    else:
        raise ValueError("frozen training base mode is invalid")

    resolved_reference = reference
    if expected_sha or expected_size:
        candidate = Path(reference).expanduser().resolve()
        if not candidate.is_file():
            raise ValueError("frozen training base model file no longer exists")
        actual_size = int(candidate.stat().st_size)
        if expected_size <= 0 or actual_size != expected_size:
            raise ValueError("frozen training base model size changed after task creation")
        actual_sha = _sha256(candidate)
        if len(expected_sha) != 64 or actual_sha != expected_sha:
            raise ValueError("frozen training base model SHA256 changed after task creation")
        allowed_suffixes = (
            {".pt"}
            if framework == "ultralytics"
            else {".pdparams", ".pdmodel", ".pdiparams"}
        )
        if candidate.suffix.lower() not in allowed_suffixes:
            raise ValueError("frozen training base model format does not match task framework")
        resolved_reference = str(candidate)

    return {
        "base_version_id": version_id or None,
        "base_version_name": version_name,
        "base_model_path": resolved_reference,
        "base_model_kind": str(contract.get("base_model_kind") or "mother_model"),
        "base_selection_reason": str(
            contract.get("base_selection_reason")
            or ("current_verified_version" if version_id else "mother_model")
        ),
        "base_model_sha256": expected_sha,
        "base_model_size_bytes": expected_size,
        "base_training_mode": mode,
        "framework": framework,
    }


def _training_finalization_existing_version(
    algorithm: Mapping[str, Any],
    *,
    task_id: str,
    expected_base_version_id: str | None,
    framework: str,
) -> Mapping[str, Any] | None:
    """Fence stale local iteration commits and make post-attach recovery idempotent."""
    task_value = str(task_id or "").strip()
    existing = next(
        (
            version
            for version in (algorithm.get("versions") or [])
            if str(version.get("task_id") or version.get("job_id") or "") == task_value
        ),
        None,
    )
    if existing is not None:
        return existing

    expected = str(expected_base_version_id or "").strip()
    current = str(
        resolve_current_version_id(
            algorithm,
            framework=str(framework or "ultralytics").strip().lower(),
        )
        or ""
    )
    if expected:
        if current != expected:
            raise RuntimeError(
                "TRAINING_BASE_VERSION_STALE: "
                f"task was frozen on base {expected}, current version is {current or '<none>'}"
            )
    elif current:
        raise RuntimeError(
            "TRAINING_BASE_VERSION_STALE: "
            f"first-run task was frozen without a base, but current version is now {current}"
        )
    return None


class TrainingHandler:
    def __init__(
        self,
        data_dir: str | Path,
        process_runner: Callable[[Any, Sequence[str], Path], dict[str, Any]] | None = None,
    ):
        self.data_dir = Path(data_dir).resolve()
        self.process_runner = process_runner or _run_training_process

    def _committed(self, context) -> str | None:
        checkpoint = context.load_checkpoint()
        if (
            not isinstance(checkpoint, dict)
            or checkpoint.get("stage") != "committed"
            or checkpoint.get("result_ref") != "result.json"
        ):
            # result.json is written before the algorithm version. It is not a
            # complete transaction until the post-version checkpoint exists.
            return None
        result = context.artifacts.read_json(context.task.task_id, "result.json", default=None)
        if not isinstance(result, dict):
            return None
        for model in result.get("verified_models") or []:
            path = context.artifacts.artifact_path(context.task.task_id, str(model.get("ref") or ""))
            if not path.is_file() or path.stat().st_size <= 0 or _sha256(path) != model.get("sha256"):
                return None
        return "result.json"

    def _finalize_completed_job(
        self,
        context,
        payload: Mapping[str, Any],
        project: Path,
        job: Mapping[str, Any],
        *,
        recovered: bool = False,
    ):
        snapshot = context.artifacts.read_json(context.task.task_id, "snapshot.json", default={})
        if not isinstance(snapshot, dict) or not str(snapshot.get("snapshot_id") or ""):
            raise RuntimeError("completed training is missing its durable dataset snapshot")
        snapshot_id = str(snapshot["snapshot_id"])
        dataset_revision_id = str(snapshot.get("dataset_revision_id") or "")
        if not dataset_revision_id:
            raise RuntimeError("completed training is missing its durable dataset revision")
        completion_error = _training_completion_error(
            job,
            expected_task_id=context.task.task_id,
            expected_snapshot_id=snapshot_id,
            expected_models_root=project / "models",
        )
        if completion_error is not None:
            raise RuntimeError(f"training completion handshake is not trustworthy: {completion_error}")
        manifest_ref = "work/bundle/manifest.json"
        manifest_path = context.artifacts.artifact_path(context.task.task_id, manifest_ref)
        verification = verify_portable_dataset(manifest_path)
        if str(verification.get("snapshot_id") or "") != snapshot_id:
            raise RuntimeError("completed training dataset manifest does not match durable task snapshot")
        if str(verification.get("dataset_revision_id") or "") != dataset_revision_id:
            raise RuntimeError("completed training dataset manifest does not match durable dataset revision")
        # The *verified* materialized Test bundle (exact pixels, YOLO labels,
        # policy and original snapshot) is the sole source for a strict
        # independent evaluation binding. Do not infer it from current materials.
        benchmark_scope = build_evaluation_benchmark_scope(
            snapshot, _json(manifest_path, {}),
        )

        cache_runtime = context.artifacts.read_json(
            context.task.task_id,
            "bundle-cache.json",
            default={},
        )
        bundle_cache_evidence = {
            **(cache_runtime if isinstance(cache_runtime, dict) else {}),
            "publish": {
                "status": "pending_commit",
                "snapshot_id": snapshot_id,
            },
        }

        algorithms_path = project / "algorithms.json"
        algorithms = list_algorithms(algorithms_path)
        algorithm_id = str(job.get("asset_algorithm_id") or payload.get("algorithm_asset_id") or "")
        algorithm = next((row for row in algorithms if str(row.get("id")) == algorithm_id), None)
        if algorithm is None:
            raise RuntimeError("completed training algorithm no longer exists")
        framework = str(payload.get("framework") or "ultralytics").strip().lower()
        expected_base_version_id = str(
            job.get("base_version_id") or payload.get("base_version_id") or ""
        ).strip()
        existing_task_version = _training_finalization_existing_version(
            algorithm,
            task_id=context.task.task_id,
            expected_base_version_id=expected_base_version_id,
            framework=framework,
        )
        if existing_task_version is not None:
            existing_snapshot_id = str(existing_task_version.get("snapshot_id") or "").strip()
            existing_revision_id = str(
                existing_task_version.get("dataset_revision_id") or ""
            ).strip()
            if existing_snapshot_id and existing_snapshot_id != snapshot_id:
                raise RuntimeError(
                    "TRAINING_VERSION_RECOVERY_MISMATCH: existing task version has another snapshot"
                )
            if existing_revision_id and existing_revision_id != dataset_revision_id:
                raise RuntimeError(
                    "TRAINING_VERSION_RECOVERY_MISMATCH: existing task version has another dataset revision"
                )

        source_values = list(job.get("verified_models") or [])
        if not source_values:
            raise RuntimeError("training reported done without verified model paths")
        models_root = (project / "models").resolve()
        resolved_sources = []
        for source_value in source_values:
            if isinstance(source_value, Mapping):
                source_value = (
                    source_value.get("path")
                    or source_value.get("stored_path")
                    or source_value.get("source")
                )
            source = Path(str(source_value or "")).resolve()
            try:
                source.relative_to(models_root)
            except ValueError as error:
                raise RuntimeError("completed training model is outside the project model directory") from error
            if not source.is_file() or source.stat().st_size <= 0:
                raise RuntimeError(f"verified training model is missing: {source.name}")
            resolved_sources.append(source)
        # Atomically settle the stop/completion race before writing any official
        # task result or algorithm version. A cancellation already persisted
        # wins; after this transition the verified completion owns the commit.
        context.begin_finalization()
        verified_models = []
        output_by_source = {}
        for index, source in enumerate(resolved_sources):
            ref = f"outputs/{index:02d}_{source.name}"
            destination = context.artifacts.artifact_path(context.task.task_id, ref)
            destination.parent.mkdir(parents=True, exist_ok=True)
            size_bytes, digest = _copy2_with_sha256(source, destination)
            artifact = {
                "ref": ref,
                "sha256": digest,
                "size_bytes": size_bytes,
            }
            verified_models.append(artifact)
            output_by_source[str(source)] = destination.resolve()
        if not verified_models:
            raise RuntimeError("training recovery found no deliverable model")

        training_report = job.get("training_report") if isinstance(job.get("training_report"), dict) else {}
        partial = (training_report.get("test_result") or {}).get("status") == "failed"
        final_status = TaskStatus.PARTIAL_SUCCESS if partial else TaskStatus.SUCCEEDED
        requested = snapshot.get("requested") if isinstance(snapshot.get("requested"), dict) else {}
        frozen_label_schema = [
            dict(item)
            for item in (snapshot.get("label_schema") or [])
            if isinstance(item, Mapping) and str(item.get("code") or "").strip()
        ]
        frozen_label_codes = [
            str(item.get("code") or "").strip()
            for item in frozen_label_schema
        ]
        freeze_ref = str(payload.get("input_freeze_ref") or "").strip()
        frozen_input = (
            context.artifacts.read_json(
                context.task.task_id,
                freeze_ref,
                default={},
            )
            if freeze_ref else {}
        )
        frozen_label_contract = (
            dict(frozen_input.get("label_contract") or {})
            if isinstance(frozen_input, Mapping)
            else {}
        )
        if not frozen_label_contract and isinstance(payload.get("label_contract"), Mapping):
            # Compatibility only for early durable tasks that persisted the
            # contract on the request before input-freeze became authoritative.
            frozen_label_contract = dict(payload.get("label_contract") or {})
        frozen_label_contract.pop("project_path", None)
        quality_gate = job.get("quality_gate") if isinstance(job.get("quality_gate"), dict) else {
            "runtime_stop_policy": "target_only",
            "eval_interval": int(payload.get("eval_interval") or 0),
            "metric": str(payload.get("eval_metric") or "map50"),
            "continue_threshold": float(payload.get("continue_threshold") or 0),
            "stop_threshold": float(payload.get("stop_threshold") or 0),
            "stage_eval_samples": int(payload.get("val_max_samples") or 0),
            "experiment_percent": float(payload.get("experiment_percent") or 0),
            "split_seed": int(payload.get("seed") or 0),
        }
        result = {
            "schema_version": 1,
            "requested_device": job.get("requested_device") or payload.get("requested_device") or payload.get("device"),
            "assigned_device": job.get("assigned_device"),
            "actual_device": job.get("actual_device"),
            "device_evidence": job.get("device_evidence"),
            "device_validation": job.get("device_evidence") or job.get("device_validation") or {},
            "actual_train_params": job.get("actual_train_params"),
            "amp_preflight": job.get("amp_preflight"),
            "amp_check_method": job.get("amp_check_method"),
            "amp_check_result": job.get("amp_check_result"),
            "precision_fallback_reason": job.get("precision_fallback_reason"),
            "resolved_precision": job.get("resolved_precision"),
            "runtime_precision": job.get("runtime_precision"),
            "requested_precision": job.get("requested_precision"),
            **_training_completion_metadata(job, payload),
            "snapshot_id": snapshot_id,
            "dataset_revision_id": dataset_revision_id,
            "snapshot_ref": "snapshot.json",
            "dataset_revision_ref": "dataset-revision.json",
            "dataset_manifest_ref": manifest_ref,
            "counts": snapshot.get("counts") or {},
            "actual_ratios": snapshot.get("actual_ratios") or {},
            "test_source": requested.get("test_source"),
            "test_seed": snapshot.get("test_seed"),
            "validation_seed": snapshot.get("validation_seed"),
            "label_schema": frozen_label_schema,
            "label_codes": frozen_label_codes,
            "label_contract": frozen_label_contract,
            "base_version_id": job.get("base_version_id"),
            "base_version_name": job.get("base_version_name"),
            "base_selection_reason": job.get("base_selection_reason"),
            "verified_models": verified_models,
            "training_report": training_report,
            "quality_gate": quality_gate,
            "dataset_verification": verification,
            "bundle_cache": bundle_cache_evidence,
            "resolved_resources": context.artifacts.read_json(context.task.task_id, "resolved-resources.json", default={}),
            "training_metrics": read_metrics(context.artifacts.artifact_path(context.task.task_id, "training-metrics.sqlite3")),
            "recovered_from_completed_job": bool(recovered),
        }
        best_output = output_by_source.get(str(Path(str(job.get("best_path") or "")).resolve())) if job.get("best_path") else None
        last_output = output_by_source.get(str(Path(str(job.get("last_path") or "")).resolve())) if job.get("last_path") else None
        result["best_model_ref"] = next(
            (model["ref"] for model in verified_models if best_output == context.artifacts.artifact_path(context.task.task_id, model["ref"]).resolve()),
            None,
        )
        result["last_model_ref"] = next(
            (model["ref"] for model in verified_models if last_output == context.artifacts.artifact_path(context.task.task_id, model["ref"]).resolve()),
            None,
        )
        primary_ref = (
            result["best_model_ref"]
            or result["last_model_ref"]
            or verified_models[0]["ref"]
        )
        primary = context.artifacts.artifact_path(
            context.task.task_id, primary_ref
        ).resolve()
        primary_evidence = next(
            model for model in verified_models
            if str(model.get("ref") or "") == str(primary_ref)
        )
        finished_at = str(job.get("finished_at") or datetime.now(timezone.utc).isoformat())
        model_sha256 = str(primary_evidence["sha256"])
        model_size_bytes = int(primary_evidence["size_bytes"])
        completion = _training_completion_metadata(job, payload)
        training_lineage = build_training_lineage(
            task_id=context.task.task_id,
            snapshot_id=snapshot_id,
            dataset_revision_id=dataset_revision_id,
            framework=str(payload.get("framework") or "ultralytics"),
            base_version_id=job.get("base_version_id"),
            base_version_name=job.get("base_version_name"),
            base_model=job.get("model") or payload.get("model"),
            base_selection_reason=job.get("base_selection_reason"),
            execution={
                "mode": str(payload.get("target") or "local"),
                "worker_id": context.lease.worker_id,
                "requested_device": job.get("requested_device") or payload.get("requested_device") or payload.get("device"),
                "assigned_device": job.get("assigned_device"),
                "actual_device": job.get("actual_device"),
            },
            requested_params=payload,
            actual_params=job.get("actual_train_params"),
            iteration_action=job.get("confirmed_iteration_action") or payload.get("iteration_action"),
            supplement_provenance=job.get("supplement_provenance"),
            artifacts=[{
                "role": "primary",
                "file_name": primary.name,
                "sha256": model_sha256,
                "size_bytes": model_size_bytes,
                "verified": True,
            }],
            training_status=final_status.value,
            training_outcome=completion.get("training_outcome"),
            completion_reason=completion.get("completion_reason"),
            finished_at=finished_at,
        )
        evaluation = build_evaluation_truth(
            training_report.get("test_result"),
            task_id=context.task.task_id,
            snapshot_id=snapshot_id,
            dataset_revision_id=dataset_revision_id,
            model_sha256=model_sha256,
            finished_at=finished_at,
            benchmark_scope=benchmark_scope,
        )
        metric_credibility = build_training_metric_credibility(
            training_report,
            evaluation,
            input_quality=(
                frozen_input.get("input_quality")
                if isinstance(frozen_input, Mapping) else None
            ),
        )
        iteration_decision = build_iteration_decision(
            evaluation,
            quality_gate=quality_gate,
            metric_credibility=metric_credibility,
        )
        result.update({
            "training_lineage": training_lineage,
            "evaluation": evaluation,
            "metric_credibility": metric_credibility,
            "iteration_decision": iteration_decision,
        })
        context.artifacts.atomic_write_json(context.task.task_id, "result.json", result)
        version_name = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        committed_version_id = (
            str(existing_task_version.get("id") or "")
            if isinstance(existing_task_version, Mapping)
            else ""
        )
        if existing_task_version is None:
            committed_version_id = uuid.uuid4().hex[:12]
            try:
                attach_version_if_current(
                    algorithms_path,
                    str(algorithm.get("id")),
                    {
                        "id": committed_version_id,
                        "version_name": version_name,
                        "version_no": version_name,
                        "stored_path": str(primary),
                        "best_path": str(best_output) if best_output else "",
                        "last_path": str(last_output) if last_output else "",
                        "model_name": primary.name,
                        "verified_models": verified_models,
                        "training_status": final_status.value,
                        "training_outcome": job.get("training_outcome"),
                        "completion_reason": job.get("completion_reason"),
                        "base_version_id": job.get("base_version_id"),
                        "base_version_name": job.get("base_version_name"),
                        "base_selection_reason": job.get("base_selection_reason"),
                        "metrics": training_report.get("metrics") or {},
                        "artifact_verified": True,
                        "trainable": True,
                        "framework": "ultralytics",
                        "label_schema": frozen_label_schema,
                        "label_codes": frozen_label_codes,
                        "label_contract": frozen_label_contract,
                        "external_analysis_id": str(
                            payload.get("external_analysis_id") or ""
                        ).strip(),
                        "snapshot_id": snapshot_id,
                        "dataset_revision_id": dataset_revision_id,
                        "training_lineage": training_lineage,
                        "evaluation": evaluation,
                        "metric_credibility": metric_credibility,
                        "iteration_decision": iteration_decision,
                        "result_ref": "result.json",
                        "task_id": context.task.task_id,
                        "job_id": context.task.task_id,
                        "created_at": finished_at,
                        "finished_at": finished_at,
                    },
                    expected_current_version_id=(
                        expected_base_version_id or None
                    ),
                )
            except PlatformError as error:
                if error.code == "ALGORITHM_VERSION_CONFLICT":
                    raise RuntimeError(
                        "TRAINING_BASE_VERSION_STALE: " + error.detail
                    ) from error
                raise

        external_publish_requested = _request_external_publish_after_training(
            data_dir=self.data_dir,
            algorithms_path=algorithms_path,
            algorithm_id=str(algorithm.get("id") or ""),
            version_id=committed_version_id,
            now=datetime.now(timezone.utc).isoformat(),
        )
        result["external_publish_requested"] = bool(external_publish_requested)

        # Seed the shared cache only after the official algorithm version has
        # been attached successfully. A task that fails before this point must
        # not become the source of a future fast-path training bundle.
        try:
            cache_entry, cache_stats = TrainingBundleCache(
                self.data_dir,
                context.task.project_id,
            ).publish_verified(
                manifest_path.parent,
                snapshot_id,
                verified_files=int(verification.get("verified_files") or 0),
            )
            cache_publish = {
                "status": "ready",
                "snapshot_id": cache_entry.snapshot_id,
                "manifest_sha256": cache_entry.manifest_sha256,
                **cache_stats,
            }
        except Exception as error:
            # Cache publication is only a performance optimization; failure here
            # cannot invalidate a model/version that already passed final truth.
            cache_publish = {
                "status": "publish_failed",
                "snapshot_id": snapshot_id,
                "error": str(error),
            }
        bundle_cache_evidence = {
            **(cache_runtime if isinstance(cache_runtime, dict) else {}),
            "publish": cache_publish,
        }
        result["bundle_cache"] = bundle_cache_evidence
        context.artifacts.atomic_write_json(context.task.task_id, "result.json", result)
        context.save_checkpoint({
            "stage": "committed",
            "snapshot_id": snapshot_id,
            "dataset_revision_id": dataset_revision_id,
            "result_ref": "result.json",
        })
        return final_status, "result.json"

    def run(self, context):
        payload = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
        if not isinstance(payload, dict):
            raise ValueError("training payload is invalid")
        if str(payload.get("training_input_state") or "").upper() != "READY":
            raise ValueError("TRAINING_PREPARE_REQUIRED: training input is not ready")
        deferred_resource_resolution = payload.get("resource_resolution_deferred") is True
        prepared_resources = context.artifacts.read_json(
            context.task.task_id,
            "resolved-resources.json",
            default={},
        )
        if not deferred_resource_resolution:
            if not (
                isinstance(prepared_resources, Mapping)
                and int(prepared_resources.get("resolved_batch") or 0) > 0
                and int(
                    prepared_resources.get("resolved_workers")
                    if prepared_resources.get("resolved_workers") is not None else -1
                ) >= 0
                and str(prepared_resources.get("resource_strategy") or "")
                == str(payload.get("resource_strategy") or "auto")
            ):
                raise ValueError(
                    "RESOURCE_PREPARE_REQUIRED: resolved resource contract is missing or invalid"
                )
            payload = {
                **payload,
                "resolved_batch": int(prepared_resources["resolved_batch"]),
                "resolved_workers": int(prepared_resources["resolved_workers"]),
                "resolved_cache": prepared_resources.get("resolved_cache", False),
                "resolved_precision": str(
                    prepared_resources.get("resolved_precision")
                    or prepared_resources.get("precision")
                    or payload.get("precision")
                    or "auto"
                ),
            }
        else:
            if (
                str(payload.get("resource_strategy") or "auto").strip().lower() != "auto"
                or normalize_training_device(
                    payload.get("requested_device", payload.get("device"))
                ) != "auto"
            ):
                raise ValueError(
                    "RESOURCE_DEFERRED_STRATEGY_INVALID: only local AUTO device/AUTO resources may defer resolution"
                )
            prepared_resources = {}
        if str(payload.get("target") or "local").lower() != "local":
            raise EnvironmentError("remote training requires a configured NVIDIA training worker")
        if str(payload.get("framework") or "ultralytics").lower() != "ultralytics":
            raise EnvironmentError("Paddle training worker is not configured in this environment")
        requested_device = normalize_training_device(payload.get("requested_device", payload.get("device")))
        assignment = context.artifacts.read_json(context.task.task_id, "assignment.json", default={})
        assigned_device = assignment.get("assigned_device") if isinstance(assignment, dict) else None
        if not assigned_device:
            raise EnvironmentError("GPU_ASSIGNMENT_REQUIRED: training requires a concrete scheduler assignment")
        if assignment.get("lease_token") != context.lease.lease_token or assignment.get("worker_id") != context.lease.worker_id:
            raise EnvironmentError("GPU_ASSIGNMENT_STALE: assignment does not belong to the current worker lease")
        assigned_device = normalize_training_device(assigned_device)
        if assigned_device == "auto" or (requested_device != "auto" and assigned_device != requested_device):
            raise EnvironmentError(
                f"TRAINING_DEVICE_ASSIGNMENT_MISMATCH: requested={requested_device}; assigned={assigned_device}"
            )
        python_executable = _training_python(self.data_dir)
        context.heartbeat(
            progress=1,
            stage="device_admission",
            current_item="验证训练设备分配",
        )
        device_evidence = validate_training_device(python_executable, assigned_device)
        if assigned_device.startswith("cuda:"):
            with context.repository._connect() as database:
                reservation = database.execute(
                    "SELECT gpu_uuid FROM gpu_reservations WHERE task_id=? AND lease_token=? AND expires_at>?",
                    (context.task.task_id, context.lease.lease_token, datetime.now(timezone.utc).isoformat()),
                ).fetchone()
            if reservation is None or reservation["gpu_uuid"] != assignment.get("gpu_uuid"):
                raise EnvironmentError("GPU_RESERVATION_REQUIRED: training does not own a current reservation")
            gpu = next((item for item in device_evidence.get("gpus", [])
                        if item.get("index") == int(assigned_device[5:])), {})
            if gpu.get("uuid") and str(gpu["uuid"]).lower().removeprefix("gpu-") != str(assignment["gpu_uuid"]).lower().removeprefix("gpu-"):
                raise EnvironmentError("GPU_IDENTITY_MISMATCH: trainer CUDA index differs from reserved physical GPU")
        context.artifacts.atomic_write_json(context.task.task_id, "device-validation.json", device_evidence)
        payload = {**payload, "requested_device": requested_device, "assigned_device": assigned_device,
                   "device": assigned_device}
        project = self.data_dir / "projects" / context.task.project_id
        if not (project / "meta.json").is_file():
            raise FileNotFoundError("training project does not exist")
        context.heartbeat(
            progress=2,
            stage="preparing_materials",
            current_item="读取本次训练素材",
        )
        train_image_ids = tuple(payload.get("train_image_ids") or ())
        test_image_ids = tuple(payload.get("test_image_ids") or ())
        if payload.get("train_dataset_ids") or payload.get("test_dataset_ids"):
            raise ValueError("训练任务只接受 train_image_ids/test_image_ids，禁止数据集分组回退")
        materials = MaterialRepository(project)
        split_request = SplitRequest(
            mode=SplitMode(str(payload.get("split_mode"))),
            train_image_ids=train_image_ids,
            test_image_ids=test_image_ids,
            experiment_percent=payload.get("experiment_percent"),
            validation_percent=float(payload.get("validation_percent") or 20),
        )
        seed = int(payload.get("seed") or 0)
        freeze_ref = str(payload.get("input_freeze_ref") or "").strip()
        if freeze_ref:
            frozen = context.artifacts.read_json(
                context.task.task_id,
                freeze_ref,
                default={},
            )
            if not isinstance(frozen, Mapping):
                raise ValueError("training input freeze is invalid")
            images, label_schema, manifest, snapshot = resolve_training_input_freeze(
                frozen,
                split_request,
                seed=seed,
                supplement_candidate_set=payload.get("supplement_candidate_set"),
            )
            if str(frozen.get("input_freeze_id") or "") != str(
                payload.get("input_freeze_id") or ""
            ):
                raise ValueError("training payload freeze identity mismatch")
        else:
            # Compatibility only for tasks created before submit-time freezing.
            images = _selected_project_images(
                materials,
                project,
                (*train_image_ids, *test_image_ids),
            )
            label_schema = _label_schema(project)
            manifest = build_split_manifest(images, split_request, seed=seed)
            snapshot = build_snapshot(
                images,
                manifest,
                label_schema,
                supplement_candidate_set=payload.get("supplement_candidate_set"),
            )
        prepared_bundle = None
        prepared_ref = str(payload.get("prepared_input_ref") or "").strip()
        if str(payload.get("training_input_state") or "").upper() == "READY" and prepared_ref:
            prepared = context.artifacts.read_json(
                context.task.task_id,
                prepared_ref,
                default={},
            )
            candidate = Path(str((prepared or {}).get("bundle_path") or "")).resolve()
            expected_work = context.artifacts.artifact_path(
                context.task.task_id, "work",
            ).resolve()
            if (
                isinstance(prepared, Mapping)
                and str(prepared.get("snapshot_id") or "") == str(snapshot.get("snapshot_id") or "")
                and (candidate == expected_work or expected_work in candidate.parents)
                and (candidate / "manifest.json").is_file()
            ):
                prepared_bundle = candidate
        bundle_cache = TrainingBundleCache(self.data_dir, context.task.project_id)
        cache_entry = (
            bundle_cache.resolve(str(snapshot["snapshot_id"]))
            if prepared_bundle is None and _indexed_content_identity_ready(images)
            else None
        )

        # A completed cache entry is itself the verified materialization of the
        # indexed Snapshot. On a hit, do not re-read 10k source objects merely
        # to rediscover the same content hashes.

        materialized_paths: dict[str, Path] = {}
        if cache_entry is None and prepared_bundle is None:
            credentials = SecretCredentialStore(KeyringSecretStore())
            storage = StorageManager(
                data_dir=self.data_dir,
                project_id=context.task.project_id,
                materials=materials,
                credentials=credentials,
            )
            total_materials = len(images)
            material_progress_step = max(1, total_materials // 100) if total_materials else 1
            for index, row in enumerate(images, start=1):
                if context.cancel_requested():
                    raise InterruptedError("training cancelled during material preparation")
                frozen_sha256 = str(row.get("content_sha256") or "").strip().lower()
                resolved = storage.materialize(row)
                if str(resolved.content_sha256 or "").strip().lower() != frozen_sha256:
                    raise ValueError(
                        f"training source content changed after submit: {row.get('id')}"
                    )
                row["size_bytes"] = resolved.size_bytes
                materialized_paths[str(row.get("id"))] = Path(resolved.path).resolve()
                if index == 1 or index == total_materials or index % material_progress_step == 0:
                    progress = 2 + (6 * index / max(1, total_materials))
                    context.heartbeat(
                        progress=progress,
                        stage="preparing_materials",
                        current_item=f"校验训练素材 {index}/{total_materials}",
                    )

        if manifest is None or snapshot is None:
            raise RuntimeError("training snapshot preparation did not produce a manifest")

        revision = dataset_revision_document(snapshot)
        persist_dataset_revision(project / "dataset_revisions", snapshot)
        context.artifacts.atomic_write_json(context.task.task_id, "snapshot.json", snapshot)
        context.artifacts.atomic_write_json(
            context.task.task_id,
            "dataset-revision.json",
            revision,
        )
        context.save_checkpoint({
            "stage": "snapshot_ready",
            "snapshot_id": snapshot["snapshot_id"],
            "dataset_revision_id": snapshot["dataset_revision_id"],
        })
        if context.cancel_requested():
            raise InterruptedError("training cancelled before dataset materialization")

        if prepared_bundle is None:
            # The assigned TRAINING execution owns these new derived files.
            # Old prebuilt/historical bundles are never silently adopted for GC.
            from .training_workspace_lifecycle import mark_training_workspace
            mark_training_workspace(
                context.artifacts, context.task, snapshot, payload.get("input_freeze_id"),
            )

        bundle_progress_step = max(1, len(images) // 100) if images else 1

        if prepared_bundle is not None:
            bundle = prepared_bundle
            context.artifacts.atomic_write_json(
                context.task.task_id,
                "bundle-cache.json",
                {
                    "cache_hit": False,
                    "prepared_input_reused": True,
                    "snapshot_id": snapshot["snapshot_id"],
                    "source_validation": "training_prepare_verified",
                },
            )
        elif cache_entry is not None:
            context.heartbeat(
                progress=10,
                stage="materializing",
                current_item=f"复用已验证训练数据 0/{len(images)}",
            )

            def cache_progress(completed: int, total: int, _item: Mapping[str, Any]) -> None:
                if completed != 1 and completed != total and completed % bundle_progress_step != 0:
                    return
                context.heartbeat(
                    progress=10 + (8 * completed / max(1, total)),
                    stage="materializing",
                    current_item=f"复用已验证训练数据 {completed}/{total}",
                )

            bundle, cache_stats = bundle_cache.restore(
                cache_entry,
                context.artifacts.artifact_path(context.task.task_id, "work"),
                progress=cache_progress,
            )
            context.artifacts.atomic_write_json(
                context.task.task_id,
                "bundle-cache.json",
                {
                    "cache_hit": True,
                    "snapshot_id": snapshot["snapshot_id"],
                    "source_validation": "verified_snapshot_cache",
                    **cache_stats,
                },
            )
        else:
            context.heartbeat(
                progress=10,
                stage="materializing",
                current_item=f"准备训练数据 0/{len(images)}",
            )

            def bundle_progress(completed: int, total: int, _item: Mapping[str, Any]) -> None:
                if completed != 1 and completed != total and completed % bundle_progress_step != 0:
                    return
                context.heartbeat(
                    progress=10 + (8 * completed / max(1, total)),
                    stage="materializing",
                    current_item=f"准备训练数据 {completed}/{total}",
                )

            bundle = materialize_portable_dataset(
                context.artifacts.artifact_path(context.task.task_id, "work"),
                snapshot,
                images,
                lambda row: materialized_paths[str(row.get("id"))],
                progress=bundle_progress,
            )
            context.artifacts.atomic_write_json(
                context.task.task_id,
                "bundle-cache.json",
                {
                    "cache_hit": False,
                    "snapshot_id": snapshot["snapshot_id"],
                    "source_validation": "materialized_from_source",
                },
            )

        if context.cancel_requested():
            raise InterruptedError("training cancelled after dataset materialization")

        algorithms_path = project / "algorithms.json"
        algorithms = list_algorithms(algorithms_path)
        algorithm = next(
            (row for row in algorithms if str(row.get("id")) == str(payload.get("algorithm_asset_id") or "")),
            None,
        )
        if algorithm is None:
            raise ValueError("training algorithm no longer exists")
        mother = str(payload.get("model") or "").strip()
        framework = str(payload.get("framework") or "ultralytics").strip().lower()
        base = resolve_frozen_training_base(payload)
        if base is None:
            # Compatibility for tasks created before submit-time base freezing.
            base = choose_algorithm_iteration_base(
                algorithm,
                mother,
                framework,
                strict_latest=bool(algorithm.get("versions")),
                artifact_validator=lambda path: path.is_file() and path.stat().st_size > 0,
            )
        model = str(base.get("base_model_path") or mother)
        assignment_node = str(assignment.get("node_id") or "").strip()
        active_at = datetime.now(timezone.utc).isoformat()
        with context.repository._connect() as database:
            if assignment_node:
                reservations = database.execute(
                    "SELECT * FROM gpu_reservations WHERE node_id=? AND expires_at>?",
                    (assignment_node, active_at),
                ).fetchall()
            else:
                # Compatibility for pre-node-scoped local runtimes.
                reservations = database.execute(
                    "SELECT * FROM gpu_reservations WHERE expires_at>?",
                    (active_at,),
                ).fetchall()
        resource_context = {
            "gpu_uuid": assignment.get("gpu_uuid"),
            "reserved_bytes": assignment.get("reserved_bytes"),
            "concurrent_reservations": max(1, len(reservations)),
            "other_reserved_bytes": sum(row["reserved_bytes"] for row in reservations
                if row["task_id"] != context.task.task_id and row["gpu_uuid"] == assignment.get("gpu_uuid")),
            "dataset_bytes": sum(int(row.get("size_bytes") or 0) for row in images),
            "train_image_count": manifest.counts.get("train", 0),
            "decoded_dataset_bytes": (sum(max(int(row["width"]) * int(row["height"]), int(payload.get("imgsz") or 640) ** 2) * 3 for row in images)
                if all(row.get("width") and row.get("height") for row in images) else None),
            "remote_cache_ready": True,  # All selected objects have been verified in the local portable bundle.
        }
        context.artifacts.atomic_write_json(context.task.task_id, "resource-context.json", resource_context)
        resolution_path = context.artifacts.artifact_path(
            context.task.task_id, "resolved-resources.json",
        )
        if deferred_resource_resolution:
            prepared_resources = _freeze_deferred_resource_contract(
                context,
                python_executable=python_executable,
                payload=payload,
                resource_context=resource_context,
                model_argument=model,
                bundle=bundle,
                assigned_device=assigned_device,
            )
            payload = {
                **payload,
                "resolved_batch": int(prepared_resources["resolved_batch"]),
                "resolved_workers": int(prepared_resources["resolved_workers"]),
                "resolved_cache": prepared_resources.get("resolved_cache", False),
                "resolved_precision": str(
                    prepared_resources.get("resolved_precision")
                    or prepared_resources.get("precision")
                    or payload.get("precision")
                    or "auto"
                ),
            }
        payload.update(
            resource_context=str(context.artifacts.artifact_path(
                context.task.task_id, "resource-context.json",
            )),
            resource_resolution=str(resolution_path),
            metrics_db=str(context.artifacts.artifact_path(
                context.task.task_id, "training-metrics.sqlite3",
            )),
        )
        job_dir = project / "jobs" / context.task.task_id
        job_dir.mkdir(parents=True, exist_ok=True)
        job_file = job_dir / "job.json"
        job = {
            "id": context.task.task_id,
            "task_id": context.task.task_id,
            "status": "queued",
            "framework": framework,
            "asset_algorithm_id": algorithm.get("id"),
            "algorithm_asset_id": algorithm.get("id"),
            "asset_algorithm_name": str(
                payload.get("asset_algorithm_name") or algorithm.get("name") or "已删除算法"
            ),
            "algorithm_name": algorithm.get("name"),
            "model": model,
            "base_version_id": base.get("base_version_id"),
            "base_version_name": base.get("base_version_name"),
            "base_selection_reason": base.get("base_selection_reason"),
            "base_model_sha256": base.get("base_model_sha256") or "",
            "base_model_size_bytes": int(base.get("base_model_size_bytes") or 0),
            "base_training_mode": base.get("base_training_mode") or (
                "previous_weights_init" if base.get("base_version_id") else "mother_model_init"
            ),
            "snapshot_id": snapshot["snapshot_id"],
            "dataset_revision_id": snapshot["dataset_revision_id"],
            "supplement_provenance": snapshot.get("supplement_provenance"),
            "dataset_counts": manifest.counts,
            "epochs": int(payload.get("epochs") or 150),
            "imgsz": int(payload.get("imgsz") or 640),
            "batch": int(payload.get("batch") or 8),
            "device": assigned_device,
            "requested_device": requested_device,
            "assigned_device": assigned_device,
            "actual_device": None,
            "device_validation": device_evidence,
            "current_item": "启动训练进程",
            "created_at": context.task.created_at,
            "artifact_verified": False,
            "resource_strategy": payload.get("resource_strategy", "auto"),
            "resource_profile": payload.get("resource_profile", "performance"),
            "precision": payload.get("precision", "auto"),
            "resolved_precision": payload.get("resolved_precision", payload.get("precision", "auto")),
            "requested_resources": payload.get("requested_resources") or {},
            "resolved_resources": dict(prepared_resources),
            "max_train_hours": payload.get("time"),
            "quality_gate": {
                "runtime_stop_policy": "target_only",
                "eval_interval": int(payload.get("eval_interval") or 0),
                "metric": str(payload.get("eval_metric") or "map50"),
                "continue_threshold": float(payload.get("continue_threshold") or 0),
                "stop_threshold": float(payload.get("stop_threshold") or 0),
                "stage_eval_samples": int(payload.get("val_max_samples") or 0),
                "experiment_percent": float(payload.get("experiment_percent") or 0),
                "split_seed": int(seed),
            },
        }
        from .training_timing import begin_attempt
        previous_job = _json(job_file, {})
        for timing_key in ("first_started_at", "training_attempts"):
            if timing_key in previous_job:
                job[timing_key] = previous_job[timing_key]
        begin_attempt(job, context.task.attempt, context.lease.worker_id, context.task.updated_at)
        atomic_write_json(job_file, job)
        if context.cancel_requested():
            raise InterruptedError("training cancelled before trainer launch")
        argv = _training_argv(
            self.data_dir,
            project,
            context.task.task_id,
            payload,
            materialize_runtime_yaml(
                bundle / "manifest.json",
                context.artifacts.artifact_path(context.task.task_id, "work/runtime-data.yaml"),
            ),
            model,
            python_executable=python_executable,
        )
        context.heartbeat(
            progress=20,
            stage="starting_trainer",
            current_item="启动训练进程",
        )
        job = self.process_runner(context, argv, job_file)
        return self._finalize_completed_job(context, payload, project, job)

    def recover(self, context):
        committed = self._committed(context)
        if committed:
            result = context.artifacts.read_json(context.task.task_id, committed, default={})
            partial = ((result.get("training_report") or {}).get("test_result") or {}).get("status") == "failed"
            return (TaskStatus.PARTIAL_SUCCESS if partial else TaskStatus.SUCCEEDED), committed
        project = self.data_dir / "projects" / context.task.project_id
        job = _json(project / "jobs" / context.task.task_id / "job.json", {})
        if isinstance(job, dict) and str(job.get("status") or "").lower() == "done":
            payload = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
            if not isinstance(payload, dict):
                raise RuntimeError("completed training task payload is invalid")
            return self._finalize_completed_job(context, payload, project, job, recovered=True)
        return self.run(context)


def worker_registration(data_dir: Path):
    return {
        "handlers": {TaskKind.TRAINING: TrainingHandler(data_dir)},
        "capabilities": {"training.ultralytics"},
    }
