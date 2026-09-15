from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping

from filelock import FileLock


CACHE_SCHEMA_VERSION = 2
_CACHE_ROOT_NAME = "training-bundles"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_component(value: str, *, label: str) -> str:
    text = str(value or "")
    windows = PureWindowsPath(text)
    if (
        not text
        or text in {".", ".."}
        or "/" in text
        or "\\" in text
        or windows.drive
        or windows.root
    ):
        raise ValueError(f"{label} must be one safe path component")
    return text


def _snapshot_id(value: str) -> str:
    text = str(value or "").strip().lower()
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise ValueError("snapshot_id must be a lowercase SHA256 hex digest")
    return text


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
    return stat.S_ISLNK(info.st_mode) or bool(
        getattr(info, "st_file_attributes", 0) & reparse_flag
    )


def _has_link_component(root: Path, path: Path) -> bool:
    base = root.resolve()
    try:
        relative = path.resolve().relative_to(base)
    except ValueError:
        return True
    current = base
    for part in relative.parts:
        current = current / part
        if _is_link_like(current):
            return True
    return False


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
        raise ValueError("relative portable bundle reference required")
    return value


def _resolve_relative(root: Path, reference: str) -> Path:
    relative = _portable_relative(reference)
    base = root.resolve()
    # Inspect the lexical path before Path.resolve() can hide an in-bundle
    # symlink/reparse component that happens to target another in-bundle file.
    current = base
    for part in relative.parts:
        current = current / part
        if _is_link_like(current):
            raise ValueError("portable bundle reference must not traverse a link or reparse point")
    resolved = (base / relative).resolve()
    if resolved != base and base not in resolved.parents:
        raise ValueError("relative portable bundle reference required")
    return resolved


def _real_directory(path: Path, *, label: str) -> Path:
    resolved = path.resolve()
    info = _path_info(resolved)
    if info is None or _is_link_like(resolved) or not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"{label} must be a real directory")
    return resolved


def _safe_rmtree(path: Path, *, parent: Path) -> None:
    if not path.exists():
        return
    resolved_parent = parent.resolve()
    resolved = path.resolve()
    if resolved.parent != resolved_parent:
        raise ValueError("cache cleanup escaped its parent")
    info = _path_info(path)
    if info is None:
        return
    if _is_link_like(path) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("cache cleanup target must be a real directory")
    shutil.rmtree(path)


@dataclass(frozen=True)
class TrainingBundleCacheEntry:
    root: Path
    bundle: Path
    snapshot_id: str
    verified_files: int
    manifest_sha256: str


class TrainingBundleCache:
    """Project-scoped immutable cache for fully verified portable training bundles."""

    def __init__(self, data_dir: str | Path, project_id: str) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.project_id = _safe_component(project_id, label="project_id")
        self.root = self.data_dir / "cache" / _CACHE_ROOT_NAME / self.project_id

    def _entry_root(self, snapshot_id: str) -> Path:
        return self.root / _snapshot_id(snapshot_id)

    def _lock(self, snapshot_id: str) -> FileLock:
        self.root.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self.root / f".{_snapshot_id(snapshot_id)}.lock"), timeout=300)

    def _resolve_unlocked(self, snapshot_id: str) -> TrainingBundleCacheEntry | None:
        sid = _snapshot_id(snapshot_id)
        entry_root = self._entry_root(sid)
        info = _path_info(entry_root)
        if info is None or _is_link_like(entry_root) or not stat.S_ISDIR(info.st_mode):
            return None
        marker_path = entry_root / "cache.json"
        bundle = entry_root / "bundle"
        manifest_path = bundle / "manifest.json"
        for candidate in (marker_path, bundle, manifest_path):
            if _is_link_like(candidate):
                return None
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if (
            int(marker.get("schema_version") or 0) != CACHE_SCHEMA_VERSION
            or str(marker.get("snapshot_id") or "") != sid
            or str(manifest.get("snapshot_id") or "") != sid
        ):
            return None
        expected_manifest_sha = str(marker.get("manifest_sha256") or "")
        if not expected_manifest_sha or _sha256(manifest_path) != expected_manifest_sha:
            return None

        try:
            snapshot_path = _resolve_relative(
                bundle, str(manifest.get("snapshot_ref") or "")
            )
            data_yaml = _resolve_relative(
                bundle, str(manifest.get("data_yaml_ref") or "")
            )
        except ValueError:
            return None
        expected_snapshot_sha = str(manifest.get("snapshot_sha256") or "")
        expected_data_yaml = str(marker.get("data_yaml_sha256") or "")
        if (
            _has_link_component(bundle, snapshot_path)
            or not snapshot_path.is_file()
            or not expected_snapshot_sha
            or _sha256(snapshot_path) != expected_snapshot_sha
            or _has_link_component(bundle, data_yaml)
            or not data_yaml.is_file()
            or not expected_data_yaml
            or _sha256(data_yaml) != expected_data_yaml
        ):
            return None

        verified_files = 0
        try:
            for role in ("train", "validation", "test"):
                for member in (manifest.get("splits") or {}).get(role, []):
                    image_path = _resolve_relative(
                        bundle, str(member.get("image_ref") or "")
                    )
                    label_path = _resolve_relative(
                        bundle, str(member.get("label_ref") or "")
                    )
                    expected_size = int(member.get("size_bytes") or 0)
                    expected_label_sha = str(member.get("label_sha256") or "")
                    if (
                        _has_link_component(bundle, image_path)
                        or not image_path.is_file()
                        or expected_size <= 0
                        or image_path.stat().st_size != expected_size
                        or _has_link_component(bundle, label_path)
                        or not label_path.is_file()
                        or not expected_label_sha
                        or _sha256(label_path) != expected_label_sha
                    ):
                        return None
                    verified_files += 1
        except (OSError, TypeError, ValueError):
            return None
        if verified_files != int(marker.get("verified_files") or -1):
            return None
        return TrainingBundleCacheEntry(
            root=entry_root,
            bundle=bundle,
            snapshot_id=sid,
            verified_files=verified_files,
            manifest_sha256=expected_manifest_sha,
        )

    def resolve(self, snapshot_id: str) -> TrainingBundleCacheEntry | None:
        with self._lock(snapshot_id):
            return self._resolve_unlocked(snapshot_id)

    @staticmethod
    def _clone_bundle(
        source_bundle: Path,
        destination_bundle: Path,
        *,
        progress: Callable[[int, int, Mapping[str, Any]], None] | None = None,
    ) -> dict[str, int]:
        source = _real_directory(source_bundle, label="source bundle")
        destination_bundle.mkdir(parents=True, exist_ok=False)
        manifest_path = source / "manifest.json"
        if _is_link_like(manifest_path) or not manifest_path.is_file():
            raise ValueError("source bundle manifest is missing")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        members: list[Mapping[str, Any]] = []
        for role in ("train", "validation", "test"):
            members.extend((manifest.get("splits") or {}).get(role, []))

        hardlinked_images = 0
        copied_images = 0
        label_files = 0
        for index, member in enumerate(members, start=1):
            image_ref = str(member.get("image_ref") or "")
            label_ref = str(member.get("label_ref") or "")
            source_image = _resolve_relative(source, image_ref)
            source_label = _resolve_relative(source, label_ref)
            expected_size = int(member.get("size_bytes") or 0)
            if (
                _has_link_component(source, source_image)
                or not source_image.is_file()
                or expected_size <= 0
                or source_image.stat().st_size != expected_size
                or _has_link_component(source, source_label)
                or not source_label.is_file()
            ):
                raise ValueError(f"cache source member is invalid: {member.get('image_id')}")
            destination_image = _resolve_relative(destination_bundle, image_ref)
            destination_label = _resolve_relative(destination_bundle, label_ref)
            destination_image.parent.mkdir(parents=True, exist_ok=True)
            destination_label.parent.mkdir(parents=True, exist_ok=True)
            try:
                os.link(source_image, destination_image)
                hardlinked_images += 1
            except OSError:
                shutil.copy2(source_image, destination_image)
                copied_images += 1
            shutil.copy2(source_label, destination_label)
            label_files += 1
            if progress is not None:
                progress(index, len(members), member)

        for reference_key in ("snapshot_ref", "data_yaml_ref"):
            reference = str(manifest.get(reference_key) or "")
            source_path = _resolve_relative(source, reference)
            destination_path = _resolve_relative(destination_bundle, reference)
            if _has_link_component(source, source_path) or not source_path.is_file():
                raise ValueError(f"cache source {reference_key} is invalid")
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)
        shutil.copy2(manifest_path, destination_bundle / "manifest.json")
        return {
            "verified_files": len(members),
            "hardlinked_images": hardlinked_images,
            "copied_images": copied_images,
            "label_files": label_files,
        }

    def restore(
        self,
        entry: TrainingBundleCacheEntry,
        task_work_root: str | Path,
        *,
        progress: Callable[[int, int, Mapping[str, Any]], None] | None = None,
    ) -> tuple[Path, dict[str, int]]:
        work = Path(task_work_root).resolve()
        if _is_link_like(work):
            raise ValueError("training work path must not be link-like")
        work.mkdir(parents=True, exist_ok=True)
        with self._lock(entry.snapshot_id):
            current = self._resolve_unlocked(entry.snapshot_id)
            if current is None or current.manifest_sha256 != entry.manifest_sha256:
                raise ValueError("training bundle cache entry is no longer valid")
            temporary = work / f".bundle-cache-{uuid.uuid4().hex}.tmp"
            target = work / "bundle"
            try:
                stats = self._clone_bundle(
                    current.bundle,
                    temporary,
                    progress=progress,
                )
                if target.exists():
                    _safe_rmtree(target, parent=work)
                os.replace(temporary, target)
                return target, stats
            finally:
                if temporary.exists():
                    _safe_rmtree(temporary, parent=work)

    def publish_verified(
        self,
        source_bundle: str | Path,
        snapshot_id: str,
        *,
        verified_files: int,
    ) -> tuple[TrainingBundleCacheEntry, dict[str, int | bool]]:
        sid = _snapshot_id(snapshot_id)
        source = _real_directory(Path(source_bundle), label="source bundle")
        with self._lock(sid):
            existing = self._resolve_unlocked(sid)
            if existing is not None:
                return existing, {
                    "published": False,
                    "verified_files": existing.verified_files,
                    "hardlinked_images": 0,
                    "copied_images": 0,
                    "label_files": 0,
                }

            entry_root = self._entry_root(sid)
            if entry_root.exists():
                _safe_rmtree(entry_root, parent=self.root)
            temporary_root = self.root / f".{sid}.{uuid.uuid4().hex}.tmp"
            bundle = temporary_root / "bundle"
            try:
                temporary_root.mkdir(parents=True, exist_ok=False)
                stats = self._clone_bundle(source, bundle)
                if int(stats["verified_files"]) != int(verified_files):
                    raise ValueError(
                        "verified bundle file count does not match final validation evidence"
                    )
                manifest_path = bundle / "manifest.json"
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if str(manifest.get("snapshot_id") or "") != sid:
                    raise ValueError("verified bundle snapshot identity mismatch")
                data_yaml_path = _resolve_relative(
                    bundle, str(manifest.get("data_yaml_ref") or "")
                )
                if not data_yaml_path.is_file():
                    raise ValueError("verified bundle data YAML is missing")
                marker = {
                    "schema_version": CACHE_SCHEMA_VERSION,
                    "snapshot_id": sid,
                    "manifest_sha256": _sha256(manifest_path),
                    "data_yaml_sha256": _sha256(data_yaml_path),
                    "verified_files": int(verified_files),
                    "published_at": datetime.now(timezone.utc).isoformat(),
                }
                (temporary_root / "cache.json").write_text(
                    json.dumps(marker, ensure_ascii=False, sort_keys=True),
                    encoding="utf-8",
                )
                os.replace(temporary_root, entry_root)
            finally:
                if temporary_root.exists():
                    _safe_rmtree(temporary_root, parent=self.root)
            resolved = self._resolve_unlocked(sid)
            if resolved is None:
                if entry_root.exists():
                    _safe_rmtree(entry_root, parent=self.root)
                raise ValueError("published training bundle cache failed validation")
            return resolved, {"published": True, **stats}
