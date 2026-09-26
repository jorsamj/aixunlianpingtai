from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from typing import Any, Callable, Mapping, Sequence

from filelock import FileLock, Timeout


CACHE_SCHEMA_VERSION = 3
_CACHE_ROOT_NAME = "training-bundles"
_CACHE_ACCESS_NAME = "access.json"
_CACHE_PROJECT_LOCK_NAME = ".project.lock"
CACHE_MAX_BYTES_ENV = "TRAINING_BUNDLE_CACHE_MAX_BYTES"
CACHE_TTL_SECONDS_ENV = "TRAINING_BUNDLE_CACHE_TTL_SECONDS"
DEFAULT_CACHE_MAX_BYTES = 64 * 1024 * 1024 * 1024
DEFAULT_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60
CACHE_RECENT_ACCESS_GRACE_SECONDS = 5 * 60


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


def _configured_non_negative_int(name: str, default: int, override: int | None) -> int:
    raw: int | str = override if override is not None else os.environ.get(name, default)
    try:
        value = int(raw)
    except (TypeError, ValueError) as error:
        raise ValueError(f"{name} must be a non-negative integer") from error
    if value < 0:
        raise ValueError(f"{name} must be a non-negative integer")
    return value


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
    if _is_link_like(path):
        raise ValueError(f"{label} must be a real directory")
    resolved = path.resolve()
    info = _path_info(resolved)
    if info is None or _is_link_like(resolved) or not stat.S_ISDIR(info.st_mode):
        raise ValueError(f"{label} must be a real directory")
    return resolved


def _safe_rmtree(path: Path, *, parent: Path) -> None:
    info = _path_info(path)
    if info is None:
        return
    if _is_link_like(path) or not stat.S_ISDIR(info.st_mode):
        raise ValueError("cache cleanup target must be a real directory")
    resolved_parent = parent.resolve()
    resolved = path.resolve()
    if resolved.parent != resolved_parent:
        raise ValueError("cache cleanup escaped its parent")
    shutil.rmtree(path)


def _bundle_logical_bytes(root: Path) -> int:
    info = _path_info(root)
    if info is None or _is_link_like(root) or not stat.S_ISDIR(info.st_mode):
        return 0
    total = 0
    pending = [root]
    while pending:
        directory = pending.pop()
        for candidate in directory.iterdir():
            candidate_info = _path_info(candidate)
            if candidate_info is None or _is_link_like(candidate):
                continue
            if stat.S_ISDIR(candidate_info.st_mode):
                pending.append(candidate)
            elif stat.S_ISREG(candidate_info.st_mode):
                total += int(candidate_info.st_size)
    return total


def _published_ns(marker: Mapping[str, Any], fallback: Path) -> int:
    raw = str(marker.get("published_at") or "").strip()
    if raw:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return int(parsed.timestamp() * 1_000_000_000)
        except (TypeError, ValueError, OverflowError):
            pass
    try:
        return int(fallback.stat().st_mtime_ns)
    except OSError:
        return 0


@dataclass(frozen=True)
class TrainingBundleCacheEntry:
    root: Path
    bundle: Path
    snapshot_id: str
    verified_files: int
    manifest_sha256: str
    bundle_bytes: int = 0
    last_access_ns: int = 0


@dataclass(frozen=True)
class _MaintenanceCandidate:
    snapshot_id: str
    root: Path
    bundle_bytes: int
    last_access_ns: int
    invalid: bool = False


class TrainingBundleCache:
    """Project-scoped cache for fully verified portable training bundles.

    Bundle payloads remain immutable. Mutable access metadata lives in a separate
    sidecar and is used only for TTL/LRU lifecycle decisions.
    """

    def __init__(
        self,
        data_dir: str | Path,
        project_id: str,
        *,
        max_bytes: int | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        self.data_dir = Path(data_dir).resolve()
        self.project_id = _safe_component(project_id, label="project_id")
        self.root = self.data_dir / "cache" / _CACHE_ROOT_NAME / self.project_id
        self.max_bytes = _configured_non_negative_int(
            CACHE_MAX_BYTES_ENV,
            DEFAULT_CACHE_MAX_BYTES,
            max_bytes,
        )
        self.ttl_seconds = _configured_non_negative_int(
            CACHE_TTL_SECONDS_ENV,
            DEFAULT_CACHE_TTL_SECONDS,
            ttl_seconds,
        )

    def _entry_root(self, snapshot_id: str) -> Path:
        return self.root / _snapshot_id(snapshot_id)

    def _lock(self, snapshot_id: str, *, timeout: float = 300) -> FileLock:
        self.root.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self.root / f".{_snapshot_id(snapshot_id)}.lock"), timeout=timeout)

    def _project_lock(self) -> FileLock:
        self.root.mkdir(parents=True, exist_ok=True)
        return FileLock(str(self.root / _CACHE_PROJECT_LOCK_NAME), timeout=300)

    @staticmethod
    def _access_path(entry_root: Path) -> Path:
        return entry_root / _CACHE_ACCESS_NAME

    def _read_access_ns(self, entry_root: Path, marker: Mapping[str, Any]) -> int:
        access_path = self._access_path(entry_root)
        if not _is_link_like(access_path):
            try:
                access = json.loads(access_path.read_text(encoding="utf-8"))
                value = int(access.get("last_access_ns") or 0)
                if value > 0:
                    return value
            except (OSError, json.JSONDecodeError, TypeError, ValueError):
                pass
        return _published_ns(marker, entry_root)

    def _write_access_unlocked(self, entry_root: Path, *, now_ns: int | None = None) -> int:
        timestamp_ns = int(time.time_ns() if now_ns is None else now_ns)
        if timestamp_ns <= 0:
            timestamp_ns = 1
        access_path = self._access_path(entry_root)
        if _is_link_like(access_path):
            return timestamp_ns
        temporary = entry_root / f".{_CACHE_ACCESS_NAME}.{uuid.uuid4().hex}.tmp"
        payload = {
            "last_access_ns": timestamp_ns,
            "last_accessed_at": datetime.fromtimestamp(
                timestamp_ns / 1_000_000_000,
                tz=timezone.utc,
            ).isoformat(),
        }
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                encoding="utf-8",
            )
            os.replace(temporary, access_path)
        finally:
            temporary.unlink(missing_ok=True)
        return timestamp_ns

    def _expired(self, last_access_ns: int, *, now_ns: int | None = None) -> bool:
        if self.ttl_seconds <= 0 or last_access_ns <= 0:
            return False
        current_ns = int(time.time_ns() if now_ns is None else now_ns)
        return current_ns - last_access_ns > self.ttl_seconds * 1_000_000_000

    def _resolve_unlocked(
        self,
        snapshot_id: str,
        *,
        allow_expired: bool = False,
    ) -> TrainingBundleCacheEntry | None:
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
        last_access_ns = self._read_access_ns(entry_root, marker)
        if not allow_expired and self._expired(last_access_ns):
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
            revision_id = str(manifest.get("dataset_revision_id") or "").strip()
            revision_path = (
                _resolve_relative(
                    bundle,
                    str(manifest.get("dataset_revision_ref") or ""),
                )
                if revision_id
                else None
            )
        except ValueError:
            return None
        expected_snapshot_sha = str(manifest.get("snapshot_sha256") or "")
        expected_data_yaml = str(marker.get("data_yaml_sha256") or "")
        expected_revision_sha = str(manifest.get("dataset_revision_sha256") or "")
        if (
            _has_link_component(bundle, snapshot_path)
            or not snapshot_path.is_file()
            or not expected_snapshot_sha
            or _sha256(snapshot_path) != expected_snapshot_sha
            or _has_link_component(bundle, data_yaml)
            or not data_yaml.is_file()
            or not expected_data_yaml
            or _sha256(data_yaml) != expected_data_yaml
            or (
                revision_path is not None
                and (
                    _has_link_component(bundle, revision_path)
                    or not revision_path.is_file()
                    or not expected_revision_sha
                    or _sha256(revision_path) != expected_revision_sha
                )
            )
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
        try:
            bundle_bytes = max(0, int(marker.get("bundle_bytes") or 0))
        except (TypeError, ValueError):
            bundle_bytes = 0
        return TrainingBundleCacheEntry(
            root=entry_root,
            bundle=bundle,
            snapshot_id=sid,
            verified_files=verified_files,
            manifest_sha256=expected_manifest_sha,
            bundle_bytes=bundle_bytes,
            last_access_ns=last_access_ns,
        )

    def resolve(self, snapshot_id: str) -> TrainingBundleCacheEntry | None:
        with self._lock(snapshot_id):
            entry = self._resolve_unlocked(snapshot_id)
            if entry is None:
                return None
            accessed_ns = self._write_access_unlocked(entry.root)
            return TrainingBundleCacheEntry(
                root=entry.root,
                bundle=entry.bundle,
                snapshot_id=entry.snapshot_id,
                verified_files=entry.verified_files,
                manifest_sha256=entry.manifest_sha256,
                bundle_bytes=entry.bundle_bytes,
                last_access_ns=accessed_ns,
            )

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
        hardlinked_image_bytes = 0
        copied_images = 0
        copied_image_bytes = 0
        label_files = 0
        label_bytes = 0
        metadata_bytes = 0
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
            # Trainer work is writable. Never share a cache inode with a task.
            # A future reflink/CoW optimization is safe only if writes remain isolated.
            shutil.copy2(source_image, destination_image)
            copied_images += 1
            copied_image_bytes += expected_size
            shutil.copy2(source_label, destination_label)
            label_files += 1
            label_bytes += int(source_label.stat().st_size)
            if progress is not None:
                progress(index, len(members), member)

        reference_keys = ["snapshot_ref", "data_yaml_ref"]
        if str(manifest.get("dataset_revision_id") or "").strip():
            reference_keys.append("dataset_revision_ref")
        for reference_key in reference_keys:
            reference = str(manifest.get(reference_key) or "")
            source_path = _resolve_relative(source, reference)
            destination_path = _resolve_relative(destination_bundle, reference)
            if _has_link_component(source, source_path) or not source_path.is_file():
                raise ValueError(f"cache source {reference_key} is invalid")
            destination_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, destination_path)
            metadata_bytes += int(source_path.stat().st_size)
        shutil.copy2(manifest_path, destination_bundle / "manifest.json")
        metadata_bytes += int(manifest_path.stat().st_size)
        return {
            "verified_files": len(members),
            "hardlinked_images": hardlinked_images,
            "hardlinked_image_bytes": hardlinked_image_bytes,
            "copied_images": copied_images,
            "copied_image_bytes": copied_image_bytes,
            "label_files": label_files,
            "label_bytes": label_bytes,
            "metadata_bytes": metadata_bytes,
            "bundle_bytes": hardlinked_image_bytes
            + copied_image_bytes
            + label_bytes
            + metadata_bytes,
        }

    def restore(
        self,
        entry: TrainingBundleCacheEntry,
        task_work_root: str | Path,
        *,
        progress: Callable[[int, int, Mapping[str, Any]], None] | None = None,
    ) -> tuple[Path, dict[str, int]]:
        work_input = Path(task_work_root)
        if _is_link_like(work_input):
            raise ValueError("training work path must not be link-like")
        work = work_input.resolve()
        work.mkdir(parents=True, exist_ok=True)
        with self._lock(entry.snapshot_id):
            # A cache entry already admitted by resolve() is allowed to cross a
            # TTL boundary while the same task is restoring it. Integrity must
            # still match exactly.
            current = self._resolve_unlocked(entry.snapshot_id, allow_expired=True)
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
                access_ns = self._write_access_unlocked(current.root)
                stats["cache_bundle_bytes"] = int(
                    current.bundle_bytes or stats.get("bundle_bytes") or 0
                )
                stats["cache_last_access_ns"] = access_ns
                return target, stats
            finally:
                if temporary.exists():
                    _safe_rmtree(temporary, parent=work)

    def _maintenance_candidates_unlocked(
        self,
    ) -> tuple[list[_MaintenanceCandidate], int]:
        info = _path_info(self.root)
        if info is None:
            return [], 0
        if _is_link_like(self.root) or not stat.S_ISDIR(info.st_mode):
            raise ValueError("training bundle cache root must be a real directory")
        candidates: list[_MaintenanceCandidate] = []
        unsafe_entries = 0
        for entry_root in self.root.iterdir():
            if entry_root.name.startswith("."):
                continue
            entry_info = _path_info(entry_root)
            if entry_info is None:
                continue
            if _is_link_like(entry_root) or not stat.S_ISDIR(entry_info.st_mode):
                unsafe_entries += 1
                continue
            try:
                sid = _snapshot_id(entry_root.name)
            except ValueError:
                continue
            marker_path = entry_root / "cache.json"
            bundle = entry_root / "bundle"
            marker: Mapping[str, Any] = {}
            invalid = False
            if _is_link_like(marker_path) or _is_link_like(bundle):
                invalid = True
            else:
                try:
                    loaded = json.loads(marker_path.read_text(encoding="utf-8"))
                    marker = loaded if isinstance(loaded, dict) else {}
                except (OSError, json.JSONDecodeError):
                    invalid = True
            if (
                not invalid
                and (
                    int(marker.get("schema_version") or 0) != CACHE_SCHEMA_VERSION
                    or str(marker.get("snapshot_id") or "") != sid
                )
            ):
                invalid = True
            try:
                bundle_bytes = max(0, int(marker.get("bundle_bytes") or 0))
            except (TypeError, ValueError):
                bundle_bytes = 0
            if bundle_bytes <= 0:
                bundle_bytes = _bundle_logical_bytes(bundle)
            last_access_ns = self._read_access_ns(entry_root, marker)
            candidates.append(
                _MaintenanceCandidate(
                    snapshot_id=sid,
                    root=entry_root,
                    bundle_bytes=bundle_bytes,
                    last_access_ns=last_access_ns,
                    invalid=invalid,
                )
            )
        return candidates, unsafe_entries

    def maintain(
        self,
        *,
        protect_snapshot_ids: Sequence[str] = (),
    ) -> dict[str, Any]:
        protected = {_snapshot_id(value) for value in protect_snapshot_ids}
        self.root.mkdir(parents=True, exist_ok=True)
        now_ns = time.time_ns()
        with self._project_lock():
            candidates, unsafe_entries = self._maintenance_candidates_unlocked()
            before_bytes = sum(candidate.bundle_bytes for candidate in candidates)
            retained_bytes = before_bytes
            evicted_entries = 0
            evicted_bytes = 0
            ttl_evictions = 0
            quota_evictions = 0
            invalid_evictions = 0
            skipped_locked = 0
            skipped_protected = 0
            skipped_recent = 0
            eviction_failures = 0
            evicted_snapshot_ids: list[str] = []
            removed: set[str] = set()

            def evict(candidate: _MaintenanceCandidate, *, reason: str) -> bool:
                nonlocal retained_bytes
                nonlocal evicted_entries
                nonlocal evicted_bytes
                nonlocal ttl_evictions
                nonlocal quota_evictions
                nonlocal invalid_evictions
                nonlocal skipped_locked
                nonlocal skipped_protected
                nonlocal skipped_recent
                nonlocal eviction_failures

                if candidate.snapshot_id in protected:
                    skipped_protected += 1
                    return False
                age_ns = max(0, now_ns - candidate.last_access_ns)
                if (
                    reason != "invalid"
                    and candidate.last_access_ns > 0
                    and age_ns < CACHE_RECENT_ACCESS_GRACE_SECONDS * 1_000_000_000
                ):
                    skipped_recent += 1
                    return False
                try:
                    with self._lock(candidate.snapshot_id, timeout=0):
                        current_info = _path_info(candidate.root)
                        if current_info is None:
                            removed.add(candidate.snapshot_id)
                            return False
                        if _is_link_like(candidate.root) or not stat.S_ISDIR(current_info.st_mode):
                            eviction_failures += 1
                            return False
                        _safe_rmtree(candidate.root, parent=self.root)
                except Timeout:
                    skipped_locked += 1
                    return False
                except (OSError, ValueError):
                    eviction_failures += 1
                    return False
                removed.add(candidate.snapshot_id)
                evicted_entries += 1
                evicted_bytes += candidate.bundle_bytes
                retained_bytes = max(0, retained_bytes - candidate.bundle_bytes)
                evicted_snapshot_ids.append(candidate.snapshot_id)
                if reason == "ttl":
                    ttl_evictions += 1
                elif reason == "quota":
                    quota_evictions += 1
                elif reason == "invalid":
                    invalid_evictions += 1
                return True

            for candidate in sorted(
                (item for item in candidates if item.invalid),
                key=lambda item: (item.last_access_ns, item.snapshot_id),
            ):
                evict(candidate, reason="invalid")

            if self.ttl_seconds > 0:
                for candidate in sorted(
                    (
                        item
                        for item in candidates
                        if not item.invalid
                        and item.snapshot_id not in removed
                        and self._expired(item.last_access_ns, now_ns=now_ns)
                    ),
                    key=lambda item: (item.last_access_ns, item.snapshot_id),
                ):
                    evict(candidate, reason="ttl")

            if self.max_bytes > 0 and retained_bytes > self.max_bytes:
                for candidate in sorted(
                    (
                        item
                        for item in candidates
                        if not item.invalid and item.snapshot_id not in removed
                    ),
                    key=lambda item: (item.last_access_ns, item.snapshot_id),
                ):
                    if retained_bytes <= self.max_bytes:
                        break
                    evict(candidate, reason="quota")

            return {
                "max_bytes": self.max_bytes,
                "ttl_seconds": self.ttl_seconds,
                "scanned_entries": len(candidates),
                "unsafe_entries": unsafe_entries,
                "before_bytes": before_bytes,
                "after_bytes": retained_bytes,
                "evicted_entries": evicted_entries,
                "evicted_bytes": evicted_bytes,
                "ttl_evictions": ttl_evictions,
                "quota_evictions": quota_evictions,
                "invalid_evictions": invalid_evictions,
                "skipped_locked": skipped_locked,
                "skipped_protected": skipped_protected,
                "skipped_recent": skipped_recent,
                "eviction_failures": eviction_failures,
                "over_budget_bytes": (
                    max(0, retained_bytes - self.max_bytes)
                    if self.max_bytes > 0
                    else 0
                ),
                "evicted_snapshot_ids": evicted_snapshot_ids,
            }

    def publish_verified(
        self,
        source_bundle: str | Path,
        snapshot_id: str,
        *,
        verified_files: int,
    ) -> tuple[TrainingBundleCacheEntry, dict[str, Any]]:
        sid = _snapshot_id(snapshot_id)
        source = _real_directory(Path(source_bundle), label="source bundle")
        published = False
        stats: dict[str, Any]
        with self._lock(sid):
            existing = self._resolve_unlocked(sid, allow_expired=True)
            if existing is not None:
                resolved = existing
                stats = {
                    "published": False,
                    "verified_files": existing.verified_files,
                    "hardlinked_images": 0,
                    "hardlinked_image_bytes": 0,
                    "copied_images": 0,
                    "copied_image_bytes": 0,
                    "label_files": 0,
                    "label_bytes": 0,
                    "metadata_bytes": 0,
                    "bundle_bytes": existing.bundle_bytes,
                }
                self._write_access_unlocked(existing.root)
            else:
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
                    now_ns = time.time_ns()
                    marker = {
                        "schema_version": CACHE_SCHEMA_VERSION,
                        "snapshot_id": sid,
                        "manifest_sha256": _sha256(manifest_path),
                        "data_yaml_sha256": _sha256(data_yaml_path),
                        "verified_files": int(verified_files),
                        "bundle_bytes": int(stats["bundle_bytes"]),
                        "published_at": datetime.fromtimestamp(
                            now_ns / 1_000_000_000,
                            tz=timezone.utc,
                        ).isoformat(),
                    }
                    (temporary_root / "cache.json").write_text(
                        json.dumps(marker, ensure_ascii=False, sort_keys=True),
                        encoding="utf-8",
                    )
                    self._write_access_unlocked(temporary_root, now_ns=now_ns)
                    os.replace(temporary_root, entry_root)
                    published = True
                finally:
                    if temporary_root.exists():
                        _safe_rmtree(temporary_root, parent=self.root)
                resolved = self._resolve_unlocked(sid, allow_expired=True)
                if resolved is None:
                    if entry_root.exists():
                        _safe_rmtree(entry_root, parent=self.root)
                    raise ValueError("published training bundle cache failed validation")
                stats = {"published": True, **stats}

        maintenance = self.maintain(protect_snapshot_ids=(sid,))
        return resolved, {
            **stats,
            "published": published,
            "maintenance": maintenance,
        }
