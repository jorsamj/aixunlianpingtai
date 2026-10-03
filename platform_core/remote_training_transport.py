"""Portable archive transport for remote training input bundles.

This module contains no task database access. It converts the already-verified
training bundle format into one immutable object-store artifact and provides a
safe cross-platform extraction path for an Agent.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import stat
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping

from .training_tasks import RemoteTrainingBundle, resolve_remote_training_bundle


TRAINING_BUNDLE_TRANSPORT_VERSION = 1
TRAINING_BUNDLE_OBJECT_PREFIX = "training-bundles"
TRAINING_BUNDLE_DOWNLOAD_TTL_SECONDS = 1800
_MAX_MEMBER_COUNT = 250_000


class RemoteTrainingTransportError(RuntimeError):
    def __init__(self, code: str, message: str, status_code: int = 409):
        self.code = str(code)
        self.status_code = int(status_code)
        super().__init__(str(message))


@dataclass(frozen=True)
class TrainingBundleArchive:
    path: Path
    snapshot_id: str
    sha256: str
    size_bytes: int
    uncompressed_size_bytes: int
    member_count: int
    verified_files: int


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalized_member_name(value: object) -> str:
    raw = str(value or "")
    if not raw or "\\" in raw or "\x00" in raw:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_ARCHIVE_UNSAFE",
            "training bundle archive contains an unsafe member name",
            422,
        )
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or "." in path.parts:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_ARCHIVE_UNSAFE",
            "training bundle archive member escapes the bundle root",
            422,
        )
    normalized = path.as_posix().strip("/")
    if not normalized:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_ARCHIVE_UNSAFE",
            "training bundle archive contains an empty member name",
            422,
        )
    return normalized


def _is_zip_symlink(info: zipfile.ZipInfo) -> bool:
    mode = (int(info.external_attr) >> 16) & 0xFFFF
    return stat.S_ISLNK(mode)


def create_training_bundle_archive(
    bundle_root: str | Path,
    destination: str | Path,
) -> TrainingBundleArchive:
    root = Path(bundle_root).expanduser().resolve()
    verified = resolve_remote_training_bundle(root / "manifest.json")
    if verified.root != root:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_ROOT_MISMATCH",
            "verified training bundle root does not match requested archive root",
            409,
        )

    members: list[tuple[str, Path]] = []
    uncompressed = 0
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise RemoteTrainingTransportError(
                "TRAINING_BUNDLE_LINK_FORBIDDEN",
                "training bundle must not contain symbolic links",
                409,
            )
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        name = _normalized_member_name(relative)
        size = int(path.stat().st_size)
        if size < 0:
            raise RemoteTrainingTransportError(
                "TRAINING_BUNDLE_FILE_INVALID",
                "training bundle contains an invalid file",
                409,
            )
        uncompressed += size
        members.append((name, path))
    if not members or len(members) > _MAX_MEMBER_COUNT:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_MEMBER_COUNT_INVALID",
            "training bundle archive member count is invalid",
            409,
        )

    target = Path(destination).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        dir=target.parent,
        prefix=f".{target.name}.",
        suffix=".tmp",
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with zipfile.ZipFile(
            temporary,
            "w",
            compression=zipfile.ZIP_STORED,
            allowZip64=True,
        ) as archive:
            for name, path in members:
                archive.write(path, arcname=name)
        if temporary.stat().st_size <= 0:
            raise RemoteTrainingTransportError(
                "TRAINING_BUNDLE_ARCHIVE_EMPTY",
                "training bundle archive is empty",
                409,
            )
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)

    return TrainingBundleArchive(
        path=target,
        snapshot_id=verified.snapshot_id,
        sha256=_sha256(target),
        size_bytes=int(target.stat().st_size),
        uncompressed_size_bytes=uncompressed,
        member_count=len(members),
        verified_files=verified.verified_files,
    )


def _validate_archive_contract(
    archive_path: Path,
    contract: Mapping[str, Any],
) -> tuple[str, int, int, int]:
    expected_sha = str(contract.get("sha256") or "").strip().lower()
    try:
        expected_size = int(contract.get("size_bytes") or 0)
        expected_uncompressed = int(contract.get("uncompressed_size_bytes") or 0)
        expected_members = int(contract.get("member_count") or 0)
    except (TypeError, ValueError) as error:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_CONTRACT_INVALID",
            "training bundle archive evidence is invalid",
            422,
        ) from error
    if (
        len(expected_sha) != 64
        or any(char not in "0123456789abcdef" for char in expected_sha)
        or expected_size <= 0
        or expected_uncompressed <= 0
        or expected_members <= 0
        or expected_members > _MAX_MEMBER_COUNT
    ):
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_CONTRACT_INVALID",
            "training bundle archive evidence is incomplete",
            422,
        )
    if not archive_path.is_file() or archive_path.stat().st_size != expected_size:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_ARCHIVE_SIZE_MISMATCH",
            "training bundle archive size does not match durable evidence",
            409,
        )
    if _sha256(archive_path) != expected_sha:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_ARCHIVE_HASH_MISMATCH",
            "training bundle archive SHA256 does not match durable evidence",
            409,
        )
    return expected_sha, expected_size, expected_uncompressed, expected_members


def extract_training_bundle_archive(
    archive: str | Path,
    destination: str | Path,
    contract: Mapping[str, Any],
) -> RemoteTrainingBundle:
    source = Path(archive).expanduser().resolve()
    _, _, expected_uncompressed, expected_members = _validate_archive_contract(source, contract)
    target = Path(destination).expanduser().resolve()
    if target.exists() or target.is_symlink():
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_DESTINATION_EXISTS",
            "training bundle extraction destination must not already exist",
            409,
        )
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(
        tempfile.mkdtemp(
            dir=target.parent,
            prefix=f".{target.name}.extract.",
        )
    ).resolve()
    try:
        seen: set[str] = set()
        declared_total = 0
        files = 0
        with zipfile.ZipFile(source, "r") as archive_file:
            infos = archive_file.infolist()
            if len(infos) > _MAX_MEMBER_COUNT:
                raise RemoteTrainingTransportError(
                    "TRAINING_BUNDLE_MEMBER_COUNT_INVALID",
                    "training bundle archive contains too many members",
                    422,
                )
            for info in infos:
                name = _normalized_member_name(info.filename)
                if name in seen:
                    raise RemoteTrainingTransportError(
                        "TRAINING_BUNDLE_DUPLICATE_MEMBER",
                        "training bundle archive contains duplicate members",
                        422,
                    )
                seen.add(name)
                if _is_zip_symlink(info):
                    raise RemoteTrainingTransportError(
                        "TRAINING_BUNDLE_LINK_FORBIDDEN",
                        "training bundle archive contains a symbolic link",
                        422,
                    )
                if info.is_dir():
                    continue
                files += 1
                declared_total += int(info.file_size)
                if declared_total > expected_uncompressed:
                    raise RemoteTrainingTransportError(
                        "TRAINING_BUNDLE_EXPANSION_MISMATCH",
                        "training bundle archive expands beyond durable evidence",
                        409,
                    )
                output = (temporary / Path(*PurePosixPath(name).parts)).resolve()
                if temporary not in output.parents:
                    raise RemoteTrainingTransportError(
                        "TRAINING_BUNDLE_ARCHIVE_UNSAFE",
                        "training bundle archive member escaped extraction root",
                        422,
                    )
                output.parent.mkdir(parents=True, exist_ok=True)
                written = 0
                with archive_file.open(info, "r") as input_stream, output.open("xb") as output_stream:
                    for chunk in iter(lambda: input_stream.read(1024 * 1024), b""):
                        written += len(chunk)
                        if declared_total - int(info.file_size) + written > expected_uncompressed:
                            raise RemoteTrainingTransportError(
                                "TRAINING_BUNDLE_EXPANSION_MISMATCH",
                                "training bundle archive expanded beyond durable evidence",
                                409,
                            )
                        output_stream.write(chunk)
                if written != int(info.file_size):
                    raise RemoteTrainingTransportError(
                        "TRAINING_BUNDLE_MEMBER_SIZE_MISMATCH",
                        "training bundle member size does not match ZIP metadata",
                        409,
                    )
        if files != expected_members or declared_total != expected_uncompressed:
            raise RemoteTrainingTransportError(
                "TRAINING_BUNDLE_EXPANSION_MISMATCH",
                "training bundle extracted size/member count does not match durable evidence",
                409,
            )
        os.replace(temporary, target)
        temporary = None  # type: ignore[assignment]
        verified = resolve_remote_training_bundle(target / "manifest.json")
        expected_snapshot = str(contract.get("snapshot_id") or "").strip()
        if not expected_snapshot or verified.snapshot_id != expected_snapshot:
            raise RemoteTrainingTransportError(
                "TRAINING_BUNDLE_SNAPSHOT_MISMATCH",
                "extracted training bundle snapshot does not match durable evidence",
                409,
            )
        return verified
    except zipfile.BadZipFile as error:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_ARCHIVE_INVALID",
            "training bundle archive is not a valid ZIP",
            422,
        ) from error
    finally:
        if temporary is not None:
            shutil.rmtree(temporary, ignore_errors=True)


def stage_training_bundle_object(
    *,
    project_id: str,
    archive: TrainingBundleArchive,
    source_id: str,
    provider,
) -> dict[str, Any]:
    safe_project = "".join(
        char if char.isalnum() or char in "._-" else "-"
        for char in str(project_id or "")
    ).strip("-._") or "project"
    safe_snapshot = "".join(
        char if char.isalnum() or char in "._-" else "-"
        for char in archive.snapshot_id
    ).strip("-._") or "snapshot"
    object_key = (
        f"{TRAINING_BUNDLE_OBJECT_PREFIX}/{safe_project}/{safe_snapshot}/"
        f"{archive.sha256[:16]}-bundle.zip"
    )
    metadata = {
        "sha256": archive.sha256,
        "snapshot_id": archive.snapshot_id,
        "purpose": "remote-training-bundle",
    }
    if provider.exists(object_key):
        stored = provider.stat(object_key)
    else:
        stored = provider.upload(
            object_key,
            archive.path,
            content_type="application/zip",
            metadata=metadata,
        )
    if (
        int(stored.size_bytes) != archive.size_bytes
        or str(stored.sha256 or "").strip().lower() != archive.sha256
    ):
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_OBJECT_VERIFICATION_FAILED",
            "uploaded training bundle object does not match archive evidence",
            502,
        )
    return {
        "transport_version": TRAINING_BUNDLE_TRANSPORT_VERSION,
        "storage_source_id": str(source_id),
        "object_key": object_key,
        "file_name": "training-bundle.zip",
        "content_type": "application/zip",
        "sha256": archive.sha256,
        "size_bytes": archive.size_bytes,
        "uncompressed_size_bytes": archive.uncompressed_size_bytes,
        "member_count": archive.member_count,
        "snapshot_id": archive.snapshot_id,
        "verified_files": archive.verified_files,
    }


def resolve_training_bundle_download(
    *,
    project_id: str,
    bundle_ref: Mapping[str, Any],
    provider,
) -> dict[str, Any]:
    object_key = str(bundle_ref.get("object_key") or "").strip()
    expected_sha = str(bundle_ref.get("sha256") or "").strip().lower()
    try:
        expected_size = int(bundle_ref.get("size_bytes") or 0)
    except (TypeError, ValueError) as error:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_CONTRACT_INVALID",
            "training bundle object evidence is invalid",
            422,
        ) from error
    if not object_key or expected_size <= 0 or len(expected_sha) != 64:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_CONTRACT_INVALID",
            "training bundle object evidence is incomplete",
            422,
        )
    stored = provider.stat(object_key)
    if int(stored.size_bytes) != expected_size or str(stored.sha256 or "").lower() != expected_sha:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_OBJECT_CHANGED",
            "training bundle object no longer matches durable evidence",
            409,
        )
    url = provider.generate_preview_url(
        object_key,
        expires_seconds=TRAINING_BUNDLE_DOWNLOAD_TTL_SECONDS,
    )
    if not url:
        raise RemoteTrainingTransportError(
            "TRAINING_BUNDLE_DOWNLOAD_UNAVAILABLE",
            "storage provider cannot mint a training bundle download URL",
            409,
        )
    return {
        "method": "GET",
        "url": str(url),
        "headers": {},
        "expires_seconds": TRAINING_BUNDLE_DOWNLOAD_TTL_SECONDS,
        "file_name": str(bundle_ref.get("file_name") or "training-bundle.zip"),
        "content_type": "application/zip",
        "sha256": expected_sha,
        "size_bytes": expected_size,
        "uncompressed_size_bytes": int(bundle_ref.get("uncompressed_size_bytes") or 0),
        "member_count": int(bundle_ref.get("member_count") or 0),
        "snapshot_id": str(bundle_ref.get("snapshot_id") or ""),
    }


__all__ = [
    "RemoteTrainingTransportError",
    "TRAINING_BUNDLE_DOWNLOAD_TTL_SECONDS",
    "TRAINING_BUNDLE_OBJECT_PREFIX",
    "TRAINING_BUNDLE_TRANSPORT_VERSION",
    "TrainingBundleArchive",
    "create_training_bundle_archive",
    "extract_training_bundle_archive",
    "resolve_training_bundle_download",
    "stage_training_bundle_object",
]
