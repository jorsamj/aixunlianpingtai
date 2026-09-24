from __future__ import annotations

import hashlib
import json
import stat
import zipfile
from pathlib import Path

import yaml

from platform_core.remote_training_transport import (
    TRAINING_BUNDLE_DOWNLOAD_TTL_SECONDS,
    RemoteTrainingTransportError,
    create_training_bundle_archive,
    extract_training_bundle_archive,
    resolve_training_bundle_download,
    stage_training_bundle_object,
)
from platform_core.storage.models import ObjectMetadata


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def make_bundle(root: Path, *, snapshot_id: str = "snapshot-abc") -> Path:
    (root / "dataset" / "images" / "train").mkdir(parents=True)
    (root / "dataset" / "labels" / "train").mkdir(parents=True)
    image = root / "dataset" / "images" / "train" / "image-1.jpg"
    label = root / "dataset" / "labels" / "train" / "image-1.txt"
    image.write_bytes(b"portable-training-image")
    label.write_text("0 0.5 0.5 0.25 0.25", encoding="utf-8")
    data_yaml = root / "dataset" / "data.yaml"
    data_yaml.write_text(
        yaml.safe_dump(
            {
                "path": ".",
                "train": "images/train",
                "val": "images/validation",
                "names": {0: "fire"},
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    snapshot = root / "snapshot.json"
    snapshot.write_text(
        json.dumps({"snapshot_id": snapshot_id}, sort_keys=True),
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 3,
        "snapshot_id": snapshot_id,
        "training_input_policy": "ultralytics_jpeg_repair_v1",
        "snapshot_ref": "snapshot.json",
        "snapshot_sha256": sha256(snapshot),
        "data_yaml_ref": "dataset/data.yaml",
        "total_size_bytes": image.stat().st_size,
        "splits": {
            "train": [{
                "image_id": "image-1",
                "image_ref": "dataset/images/train/image-1.jpg",
                "label_ref": "dataset/labels/train/image-1.txt",
                "source_content_sha256": sha256(image),
                "source_size_bytes": image.stat().st_size,
                "content_sha256": sha256(image),
                "size_bytes": image.stat().st_size,
                "training_input_policy": "ultralytics_jpeg_repair_v1",
                "normalized": False,
                "normalization_reason": "",
                "label_sha256": sha256(label),
            }],
            "validation": [],
            "test": [],
        },
    }
    (root / "manifest.json").write_text(
        json.dumps(manifest, sort_keys=True),
        encoding="utf-8",
    )
    return root


class FakeProvider:
    def __init__(self):
        self.objects = {}
        self.uploads = []
        self.signatures = []

    def exists(self, key):
        return str(key) in self.objects

    def upload(self, key, source, *, content_type="application/octet-stream", metadata=None):
        data = Path(source).read_bytes()
        self.objects[str(key)] = {
            "data": data,
            "content_type": content_type,
            "sha256": str((metadata or {}).get("sha256") or ""),
        }
        self.uploads.append((str(key), dict(metadata or {})))
        return self.stat(key)

    def stat(self, key):
        item = self.objects[str(key)]
        return ObjectMetadata(
            key=str(key),
            size_bytes=len(item["data"]),
            content_type=item["content_type"],
            sha256=item["sha256"],
        )

    def generate_preview_url(self, key, *, expires_seconds=900):
        self.signatures.append((str(key), int(expires_seconds)))
        return f"https://objects.example.test/{key}?signed=1"


def test_training_bundle_archive_round_trip_preserves_verified_snapshot(tmp_path):
    bundle = make_bundle(tmp_path / "bundle")
    archive = create_training_bundle_archive(bundle, tmp_path / "bundle.zip")

    assert archive.snapshot_id == "snapshot-abc"
    assert archive.size_bytes > 0
    assert archive.uncompressed_size_bytes > 0
    assert archive.member_count == 5
    assert len(archive.sha256) == 64

    extracted = extract_training_bundle_archive(
        archive.path,
        tmp_path / "extracted",
        {
            "sha256": archive.sha256,
            "size_bytes": archive.size_bytes,
            "uncompressed_size_bytes": archive.uncompressed_size_bytes,
            "member_count": archive.member_count,
            "snapshot_id": archive.snapshot_id,
        },
    )

    assert extracted.snapshot_id == "snapshot-abc"
    assert extracted.verified_files == 1
    assert extracted.data_yaml.is_file()
    assert (extracted.root / "dataset/images/train/image-1.jpg").read_bytes() == b"portable-training-image"


def test_training_bundle_archive_rejects_path_traversal_even_with_valid_outer_hash(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("../escape.txt", b"escape")
    contract = {
        "sha256": sha256(archive),
        "size_bytes": archive.stat().st_size,
        "uncompressed_size_bytes": len(b"escape"),
        "member_count": 1,
        "snapshot_id": "snapshot-abc",
    }

    try:
        extract_training_bundle_archive(archive, tmp_path / "out", contract)
    except RemoteTrainingTransportError as error:
        assert error.code == "TRAINING_BUNDLE_ARCHIVE_UNSAFE"
    else:
        raise AssertionError("unsafe ZIP member was accepted")
    assert not (tmp_path / "escape.txt").exists()


def test_training_bundle_archive_rejects_zip_symlinks(tmp_path):
    archive = tmp_path / "link.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        info = zipfile.ZipInfo("dataset/link")
        info.create_system = 3
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        writer.writestr(info, "target")
    contract = {
        "sha256": sha256(archive),
        "size_bytes": archive.stat().st_size,
        "uncompressed_size_bytes": len(b"target"),
        "member_count": 1,
        "snapshot_id": "snapshot-abc",
    }

    try:
        extract_training_bundle_archive(archive, tmp_path / "out", contract)
    except RemoteTrainingTransportError as error:
        assert error.code == "TRAINING_BUNDLE_LINK_FORBIDDEN"
    else:
        raise AssertionError("ZIP symlink was accepted")


def test_training_bundle_archive_rejects_duplicate_member_names(tmp_path):
    archive = tmp_path / "duplicate.zip"
    with zipfile.ZipFile(archive, "w") as writer:
        writer.writestr("same.txt", b"a")
        writer.writestr("same.txt", b"b")
    contract = {
        "sha256": sha256(archive),
        "size_bytes": archive.stat().st_size,
        "uncompressed_size_bytes": 2,
        "member_count": 2,
        "snapshot_id": "snapshot-abc",
    }

    try:
        extract_training_bundle_archive(archive, tmp_path / "out", contract)
    except RemoteTrainingTransportError as error:
        assert error.code == "TRAINING_BUNDLE_DUPLICATE_MEMBER"
    else:
        raise AssertionError("duplicate ZIP member was accepted")


def test_staged_training_bundle_object_requires_server_visible_sha256_metadata(tmp_path):
    archive = create_training_bundle_archive(
        make_bundle(tmp_path / "bundle"),
        tmp_path / "bundle.zip",
    )
    provider = FakeProvider()
    ref = stage_training_bundle_object(
        project_id="project-one",
        archive=archive,
        source_id="s3-training",
        provider=provider,
    )

    assert ref["snapshot_id"] == "snapshot-abc"
    assert ref["sha256"] == archive.sha256
    assert ref["size_bytes"] == archive.size_bytes
    assert ref["object_key"].startswith("training-bundles/project-one/snapshot-abc/")
    assert provider.uploads[0][1]["sha256"] == archive.sha256
    assert provider.uploads[0][1]["purpose"] == "remote-training-bundle"

    provider.objects[ref["object_key"]]["sha256"] = ""
    try:
        stage_training_bundle_object(
            project_id="project-one",
            archive=archive,
            source_id="s3-training",
            provider=provider,
        )
    except RemoteTrainingTransportError as error:
        assert error.code == "TRAINING_BUNDLE_OBJECT_VERIFICATION_FAILED"
    else:
        raise AssertionError("unverifiable existing training bundle object was accepted")


def test_training_bundle_download_contract_revalidates_object_before_signing(tmp_path):
    archive = create_training_bundle_archive(
        make_bundle(tmp_path / "bundle"),
        tmp_path / "bundle.zip",
    )
    provider = FakeProvider()
    ref = stage_training_bundle_object(
        project_id="project-one",
        archive=archive,
        source_id="s3-training",
        provider=provider,
    )

    resolved = resolve_training_bundle_download(
        project_id="project-one",
        bundle_ref=ref,
        provider=provider,
    )

    assert resolved["method"] == "GET"
    assert resolved["sha256"] == archive.sha256
    assert resolved["snapshot_id"] == "snapshot-abc"
    assert provider.signatures == [
        (ref["object_key"], TRAINING_BUNDLE_DOWNLOAD_TTL_SECONDS)
    ]

    provider.objects[ref["object_key"]]["data"] += b"changed"
    try:
        resolve_training_bundle_download(
            project_id="project-one",
            bundle_ref=ref,
            provider=provider,
        )
    except RemoteTrainingTransportError as error:
        assert error.code == "TRAINING_BUNDLE_OBJECT_CHANGED"
    else:
        raise AssertionError("changed training bundle object was signed")
