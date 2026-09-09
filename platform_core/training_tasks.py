from __future__ import annotations

import errno
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping, Sequence

import yaml

from .annotations import atomic_write_json
from .annotation_repository import AnnotationRepository
from .algorithms import attach_version, choose_iteration_base, list_algorithms
from .material_repository import MaterialRepository
from .secrets import KeyringSecretStore, SecretCredentialStore
from .snapshots import build_snapshot
from .storage import StorageManager
from .task_runtime import ProcessController, TaskKind, TaskStatus, launch_process
from .training_splits import SplitMode, SplitRequest, build_split_manifest


TRAINING_BUNDLE_SAFETY_RESERVE_BYTES = 512 * 1024 * 1024
TRAINING_BUNDLE_SAFETY_RESERVE_ENV = "TRAINING_BUNDLE_SAFETY_RESERVE_BYTES"
TRAINING_BUNDLE_COPY_ORPHAN_AGE_SECONDS = 24 * 60 * 60
_TRAINING_BUNDLE_COPY_PREFIX = ".training-bundle-copy."


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


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


def _atomic_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            stream.write(text)
            stream.flush()
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
) -> None:
    source_info = source.stat() if source.is_file() else None
    if source_info is None or source_info.st_size <= 0:
        raise FileNotFoundError(f"training image does not exist: {source.name}")
    source_size = source_info.st_size
    actual = _sha256(source)
    if actual != expected_hash:
        raise ValueError(f"source image SHA256 changed: {source.name}")
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
    try:
        with source.open("rb") as input_stream:
            with os.fdopen(descriptor, "wb") as output_stream:
                descriptor = -1
                shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
                output_stream.flush()
                os.fsync(output_stream.fileno())
        copied_size = temporary.stat().st_size
        if copied_size != source_size:
            raise OSError(
                f"portable image size verification failed: {destination.name}; "
                f"expected={source_size}, actual={copied_size}"
            )
        if copied_size <= 0 or _sha256(temporary) != expected_hash:
            raise OSError(f"portable image verification failed: {destination.name}")
        os.replace(temporary, destination)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _process_is_running(process_id: int) -> bool:
    if process_id <= 0:
        return False
    try:
        os.kill(process_id, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True


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


def materialize_portable_dataset(
    task_root: str | Path,
    snapshot: Mapping[str, Any],
    source_images: Sequence[Mapping[str, Any]],
    materialize: Callable[[Mapping[str, Any]], str | Path],
    *,
    safety_reserve_bytes: int | None = None,
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
            source_path = Path(materialize(row)).resolve()
            if not source_path.is_file() or source_path.stat().st_size <= 0:
                raise FileNotFoundError(f"training image does not exist: {source_path.name}")
            planned.append(
                {
                    "role": role,
                    "image_id": str(image_id),
                    "row": row,
                    "stored_name": stored_name,
                    "expected_hash": expected_hash,
                    "source_path": source_path,
                    "size_bytes": source_path.stat().st_size,
                }
            )

    total_size_bytes = sum(int(item["size_bytes"]) for item in planned)
    peak_copy_bytes = max((int(item["size_bytes"]) for item in planned), default=0)
    reserve_bytes = _safety_reserve_bytes(safety_reserve_bytes)
    _check_bundle_disk_space(root, total_size_bytes, peak_copy_bytes, reserve_bytes)

    splits: dict[str, list[dict[str, Any]]] = {"train": [], "validation": [], "test": []}
    remaining_bytes = total_size_bytes
    for item in planned:
        role = str(item["role"])
        image_id = str(item["image_id"])
        row = item["row"]
        stored_name = str(item["stored_name"])
        expected_hash = str(item["expected_hash"])
        source_path = Path(item["source_path"])
        size_bytes = int(item["size_bytes"])
        image_ref = f"dataset/images/{role}/{stored_name}"
        label_ref = f"dataset/labels/{role}/{Path(stored_name).stem}.txt"
        destination = _bundle_output_path(root, image_ref)
        _check_bundle_disk_space(root, remaining_bytes, size_bytes, reserve_bytes)
        _copy_verified_isolated(source_path, destination, expected_hash, bundle_root=root)
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
        _atomic_text(label_path, "\n".join(lines))
        splits[role].append(
            {
                "image_id": image_id,
                "image_ref": image_ref,
                "label_ref": label_ref,
                "content_sha256": expected_hash,
                "size_bytes": size_bytes,
                "label_sha256": _sha256(label_path),
            }
        )
    data_yaml = {
        "path": ".",
        "train": "images/train",
        "val": "images/validation",
        "test": "images/test",
        "names": names,
    }
    _atomic_text(
        _bundle_output_path(root, "dataset/data.yaml"),
        yaml.safe_dump(data_yaml, allow_unicode=True, sort_keys=False),
    )
    snapshot_path = root / "snapshot.json"
    atomic_write_json(snapshot_path, dict(snapshot))
    manifest = {
        "schema_version": 2,
        "snapshot_id": str(snapshot.get("snapshot_id") or ""),
        "snapshot_ref": "snapshot.json",
        "snapshot_sha256": _sha256(snapshot_path),
        "data_yaml_ref": "dataset/data.yaml",
        "total_size_bytes": total_size_bytes,
        "splits": splits,
    }
    atomic_write_json(manifest_path, manifest)
    verify_portable_dataset(manifest_path)
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


def verify_portable_dataset(manifest_path: str | Path) -> dict[str, Any]:
    path = Path(manifest_path).resolve()
    manifest = json.loads(path.read_text(encoding="utf-8"))
    resolve_dataset_yaml(path)
    verified = 0
    for role in ("train", "validation", "test"):
        for member in (manifest.get("splits") or {}).get(role, []):
            image_path = _resolve_relative(path.parent, str(member.get("image_ref") or ""))
            label_path = _resolve_relative(path.parent, str(member.get("label_ref") or ""))
            if not image_path.is_file() or _sha256(image_path) != str(member.get("content_sha256") or ""):
                raise ValueError(f"portable image SHA256 mismatch: {member.get('image_id')}")
            if not label_path.is_file() or _sha256(label_path) != str(member.get("label_sha256") or ""):
                raise ValueError(f"portable label SHA256 mismatch: {member.get('image_id')}")
            verified += 1
    return {"snapshot_id": manifest.get("snapshot_id"), "verified_files": verified}


@dataclass(frozen=True)
class RemoteTrainingBundle:
    root: Path
    manifest: Path
    data_yaml: Path
    snapshot: Path
    snapshot_id: str
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
    return RemoteTrainingBundle(
        root=path.parent,
        manifest=path,
        data_yaml=resolve_dataset_yaml(path),
        snapshot=snapshot,
        snapshot_id=snapshot_id,
        verified_files=int(verification["verified_files"]),
    )


def _json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _selected_project_images(
    materials: MaterialRepository,
    project: Path,
    image_ids: Sequence[str],
) -> list[dict[str, Any]]:
    wanted = tuple(dict.fromkeys(str(value).strip() for value in image_ids if str(value).strip()))
    if not wanted:
        raise ValueError("train_image_ids 不能为空")
    rows = materials.get_many(wanted)
    found = {str(row.get("id")) for row in rows}
    missing = [image_id for image_id in wanted if image_id not in found]
    if missing:
        raise ValueError(f"所选素材不存在: {', '.join(missing[:5])}")
    by_id = {str(row.get("id")): row for row in rows}
    result = []
    annotations = AnnotationRepository(project)
    for image_id in wanted:
        row = dict(by_id[image_id])
        image_id = str(row.get("id") or "")
        annotation = annotations.get(image_id)
        row['annotation_state'] = annotation['annotation_state']
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
        item["class_id"] = int(item.get("class_id", index))
        if item.get("code"):
            items.append(item)
    return items


def _training_python(data_dir: Path) -> str:
    configured = _json(data_dir / "ultralytics_env.json", {})
    candidate = Path(str(configured.get("python_path") or "")) if isinstance(configured, dict) else Path()
    if str(candidate) and candidate.is_file():
        return str(candidate)
    return sys.executable


def _bool(value: Any) -> str:
    return "true" if bool(value) else "false"


def _training_argv(data_dir: Path, project: Path, task_id: str, payload: Mapping[str, Any], data_yaml: Path, model: str) -> list[str]:
    root = Path(__file__).resolve().parent.parent
    argv = [
        _training_python(data_dir),
        str(root / "train_worker.py"),
        "--project-dir", str(project),
        "--data", str(data_yaml),
        "--model", str(model),
        "--epochs", str(int(payload.get("epochs") or 50)),
        "--imgsz", str(int(payload.get("imgsz") or 640)),
        "--batch", str(int(payload.get("batch") or 8)),
        "--device", str(payload.get("device") or "cpu"),
        "--job-id", task_id,
        "--run-name", f"train_{task_id}",
    ]
    value_options = {
        "patience": 100, "workers": 0, "optimizer": "auto", "lr0": 0.01,
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
        argv.extend([f"--{key.replace('_', '-')}", str(payload.get(key, default))])
    for key, default in {
        "single_cls": False, "pretrained": True, "rect": False, "amp": True,
        "cos_lr": False, "deterministic": True, "auto_supplement": False,
        "ai_intervention": False,
    }.items():
        payload_key = "ai_intervention_enabled" if key == "ai_intervention" else key
        argv.extend([f"--{key.replace('_', '-')}", _bool(payload.get(payload_key, default))])
    argv.extend(["--supplement-count", str(int(payload.get("supplement_count") or 0))])
    return argv


def _run_training_process(context, argv: Sequence[str], job_file: Path) -> dict[str, Any]:
    artifact_log = context.artifacts.artifact_path(context.task.task_id, context.task.log_ref)
    artifact_log.parent.mkdir(parents=True, exist_ok=True)
    log_path = job_file.parent / "train.log"
    root = Path(__file__).resolve().parent.parent
    try:
        with log_path.open("a", encoding="utf-8", newline="") as log:
            launched = launch_process(
                argv,
                cwd=root,
                env={**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"},
                stdout=log,
                stderr=subprocess.STDOUT,
                text=True,
            )
            context.repository.bind_process(context.task.task_id, context.lease.lease_token, launched.identity)
            controller = ProcessController()
            while launched.process.poll() is None:
                if context.cancel_requested():
                    controller.terminate_tree(launched.identity)
                    raise InterruptedError("training cancelled")
                current_task = context.repository.get(context.task.task_id)
                if current_task is not None and current_task.stage == "paused":
                    context.repository.heartbeat(
                        context.task.task_id,
                        context.lease.lease_token,
                        stage="paused",
                    )
                    time.sleep(0.25)
                    continue
                job = _json(job_file, {})
                progress = float(job.get("progress_percent") or 20)
                current = str(job.get("current_epoch") or "") or None
                context.repository.heartbeat(
                    context.task.task_id,
                    context.lease.lease_token,
                    progress=max(20, min(95, progress)),
                    stage="training",
                    current_item=current,
                )
                time.sleep(0.25)
    finally:
        if log_path.is_file():
            shutil.copy2(log_path, artifact_log)
    job = _json(job_file, {})
    if launched.process.returncode != 0:
        raise RuntimeError(str(job.get("message") or f"training process exited {launched.process.returncode}"))
    return job


class TrainingHandler:
    def __init__(
        self,
        data_dir: str | Path,
        process_runner: Callable[[Any, Sequence[str], Path], dict[str, Any]] | None = None,
    ):
        self.data_dir = Path(data_dir).resolve()
        self.process_runner = process_runner or _run_training_process

    def _committed(self, context) -> str | None:
        result = context.artifacts.read_json(context.task.task_id, "result.json", default=None)
        if not isinstance(result, dict):
            return None
        for model in result.get("verified_models") or []:
            path = context.artifacts.artifact_path(context.task.task_id, str(model.get("ref") or ""))
            if not path.is_file() or path.stat().st_size <= 0 or _sha256(path) != model.get("sha256"):
                return None
        return "result.json"

    def run(self, context):
        payload = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
        if not isinstance(payload, dict):
            raise ValueError("training payload is invalid")
        if str(payload.get("target") or "local").lower() != "local":
            raise EnvironmentError("remote training requires a configured NVIDIA training worker")
        if str(payload.get("framework") or "ultralytics").lower() != "ultralytics":
            raise EnvironmentError("Paddle training worker is not configured in this environment")
        project = self.data_dir / "projects" / context.task.project_id
        if not (project / "meta.json").is_file():
            raise FileNotFoundError("training project does not exist")
        context.repository.heartbeat(context.task.task_id, context.lease.lease_token, 2, "hashing")
        train_image_ids = tuple(payload.get("train_image_ids") or ())
        test_image_ids = tuple(payload.get("test_image_ids") or ())
        if payload.get("train_dataset_ids") or payload.get("test_dataset_ids"):
            raise ValueError("训练任务只接受 train_image_ids/test_image_ids，禁止数据集分组回退")
        materials = MaterialRepository(project)
        images = _selected_project_images(materials, project, (*train_image_ids, *test_image_ids))
        credentials = SecretCredentialStore(KeyringSecretStore())
        storage = StorageManager(
            data_dir=self.data_dir,
            project_id=context.task.project_id,
            materials=materials,
            credentials=credentials,
        )
        for row in images:
            resolved = storage.materialize(row)
            row["content_sha256"] = resolved.content_sha256
            row["size_bytes"] = resolved.size_bytes
        split_request = SplitRequest(
            mode=SplitMode(str(payload.get("split_mode"))),
            train_image_ids=train_image_ids,
            test_image_ids=test_image_ids,
            experiment_percent=payload.get("experiment_percent"),
            validation_percent=float(payload.get("validation_percent") or 20),
        )
        manifest = build_split_manifest(images, split_request, seed=int(payload.get("seed") or 0))
        snapshot = build_snapshot(images, manifest, _label_schema(project))
        context.artifacts.atomic_write_json(context.task.task_id, "snapshot.json", snapshot)
        context.save_checkpoint({"stage": "snapshot_ready", "snapshot_id": snapshot["snapshot_id"]})
        context.repository.heartbeat(context.task.task_id, context.lease.lease_token, 10, "materializing")
        bundle = materialize_portable_dataset(
            context.artifacts.artifact_path(context.task.task_id, "work"),
            snapshot,
            images,
            lambda row: storage.materialize(row).path,
        )
        verification = verify_portable_dataset(bundle / "manifest.json")

        algorithms_path = project / "algorithms.json"
        algorithms = list_algorithms(algorithms_path)
        algorithm = next(
            (row for row in algorithms if str(row.get("id")) == str(payload.get("algorithm_asset_id") or "")),
            None,
        )
        if algorithm is None:
            raise ValueError("training algorithm no longer exists")
        mother = str(payload.get("model") or "").strip()
        base = choose_iteration_base(
            algorithm.get("versions") or [],
            mother,
            "ultralytics",
            strict_latest=bool(algorithm.get("versions")),
            artifact_validator=lambda path: path.is_file() and path.stat().st_size > 0,
        )
        model = str(base.get("base_model_path") or mother)
        job_dir = project / "jobs" / context.task.task_id
        job_dir.mkdir(parents=True, exist_ok=True)
        job_file = job_dir / "job.json"
        job = {
            "id": context.task.task_id,
            "task_id": context.task.task_id,
            "status": "queued",
            "framework": "ultralytics",
            "asset_algorithm_id": algorithm.get("id"),
            "algorithm_name": algorithm.get("name"),
            "model": model,
            "base_version_id": base.get("base_version_id"),
            "base_version_name": base.get("base_version_name"),
            "base_selection_reason": base.get("base_selection_reason"),
            "snapshot_id": snapshot["snapshot_id"],
            "dataset_counts": manifest.counts,
            "epochs": int(payload.get("epochs") or 50),
            "imgsz": int(payload.get("imgsz") or 640),
            "batch": int(payload.get("batch") or 8),
            "device": str(payload.get("device") or "cpu"),
            "created_at": context.task.created_at,
            "artifact_verified": False,
        }
        atomic_write_json(job_file, job)
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
        )
        context.repository.heartbeat(context.task.task_id, context.lease.lease_token, 20, "starting_trainer")
        job = self.process_runner(context, argv, job_file)
        if not job.get("artifact_verified"):
            raise RuntimeError(str(job.get("message") or "training produced no verified model"))
        verified_models = []
        for index, source_value in enumerate(job.get("verified_models") or []):
            source = Path(str(source_value)).resolve()
            if not source.is_file() or source.stat().st_size <= 0:
                raise RuntimeError(f"verified training model is missing: {source.name}")
            ref = f"outputs/{index:02d}_{source.name}"
            destination = context.artifacts.artifact_path(context.task.task_id, ref)
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source != destination.resolve():
                shutil.copy2(source, destination)
            digest = _sha256(destination)
            verified_models.append({"ref": ref, "sha256": digest, "size_bytes": destination.stat().st_size})
        if not verified_models:
            raise RuntimeError("training reported success without a verified model")
        training_report = job.get("training_report") or {}
        partial = (training_report.get("test_result") or {}).get("status") == "failed"
        final_status = TaskStatus.PARTIAL_SUCCESS if partial else TaskStatus.SUCCEEDED
        result = {
            "schema_version": 1,
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_ref": "snapshot.json",
            "dataset_manifest_ref": "work/bundle/manifest.json",
            "counts": manifest.counts,
            "actual_ratios": manifest.actual_ratios,
            "test_source": manifest.requested["test_source"],
            "test_seed": manifest.test_seed,
            "validation_seed": manifest.validation_seed,
            "base_version_id": base.get("base_version_id"),
            "base_version_name": base.get("base_version_name"),
            "base_selection_reason": base.get("base_selection_reason"),
            "verified_models": verified_models,
            "training_report": training_report,
            "dataset_verification": verification,
        }
        context.artifacts.atomic_write_json(context.task.task_id, "result.json", result)
        existing = next(
            (version for version in algorithm.get("versions") or [] if version.get("task_id") == context.task.task_id),
            None,
        )
        if existing is None:
            primary = context.artifacts.artifact_path(context.task.task_id, verified_models[0]["ref"])
            attach_version(
                algorithms_path,
                str(algorithm.get("id")),
                {
                    "id": uuid.uuid4().hex[:12],
                    "version_name": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
                    "stored_path": str(primary),
                    "model_name": primary.name,
                    "training_status": final_status.value,
                    "artifact_verified": True,
                    "trainable": True,
                    "framework": "ultralytics",
                    "snapshot_id": snapshot["snapshot_id"],
                    "result_ref": "result.json",
                    "task_id": context.task.task_id,
                    "job_id": context.task.task_id,
                    "created_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        context.save_checkpoint({"stage": "committed", "snapshot_id": snapshot["snapshot_id"], "result_ref": "result.json"})
        return final_status, "result.json"

    def recover(self, context):
        committed = self._committed(context)
        if committed:
            result = context.artifacts.read_json(context.task.task_id, committed, default={})
            partial = ((result.get("training_report") or {}).get("test_result") or {}).get("status") == "failed"
            return (TaskStatus.PARTIAL_SUCCESS if partial else TaskStatus.SUCCEEDED), committed
        return self.run(context)


def worker_registration(data_dir: Path):
    return {
        "handlers": {TaskKind.TRAINING: TrainingHandler(data_dir)},
        "capabilities": {"training.ultralytics"},
    }
