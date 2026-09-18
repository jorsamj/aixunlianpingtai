from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
from PIL import Image

from platform_core.remote_material_import import (
    REMOTE_MATERIAL_STAGING_REF,
    REVIEW_DETECTION_ANNOTATIONS_MEMBER,
    RemoteMaterialImportError,
    RemoteMaterialStagingStore,
    build_material_review_archive,
    build_storage_scan_material_review_archive,
    commit_material_review_archive,
)
from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.storage.import_tasks import MANIFEST_REF, SCAN_RESULT_REF
from platform_core.storage.models import ObjectMetadata
from platform_core.task_runtime import ArtifactStore


def _image(path: Path, color=(20, 30, 40)):
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (48, 32), color).save(path, format="JPEG")
    return path


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_review_bundle_build_and_server_commit_round_trip(tmp_path):
    source = tmp_path / "source"
    first = _image(source / "a" / "one.jpg")
    duplicate = source / "a" / "copy.jpg"
    duplicate.write_bytes(first.read_bytes())
    (source / "bad.jpg").write_bytes(b"not-an-image")
    (source / "notes.txt").write_text("hello", encoding="utf-8")

    archive = tmp_path / "review.zip"
    built = build_material_review_archive(
        source,
        archive,
        task_id="material-task",
        project_id="project-one",
        execution_generation=1,
        storage_source_id="s3-target",
        storage_type="s3",
        target_prefix="incoming/2026",
    )

    assert built["candidate_count"] == 4
    assert built["counts"] == {
        "DUPLICATE": 1,
        "IMPORTABLE": 1,
        "INVALID": 1,
        "SKIPPED": 1,
    }
    assert built["sha256"] == _sha(archive)

    artifacts = ArtifactStore(tmp_path / "artifacts")
    committed = commit_material_review_archive(
        artifacts=artifacts,
        task_id="material-task",
        project_id="project-one",
        execution_generation=1,
        archive_path=archive,
        archive_sha256=built["sha256"],
        archive_size_bytes=built["size_bytes"],
        expected_source_id="s3-target",
        expected_storage_type="s3",
        expected_prefix="incoming/2026",
    )

    assert committed["material_review_committed"] is True
    assert committed["material_candidates"] == 4
    assert committed["material_importable"] == 1
    store = ImportCandidateStore(
        artifacts.artifact_path("material-task", MANIFEST_REF)
    )
    assert store.counts() == {
        "DUPLICATE": 1,
        "IMPORTABLE": 1,
        "INVALID": 1,
        "SKIPPED": 1,
    }
    importable = list(store.iter_status("IMPORTABLE"))
    assert len(importable) == 1
    assert importable[0]["object_key"].startswith("incoming/2026/")
    assert importable[0]["content_sha256"] == _sha(first)

    staging = RemoteMaterialStagingStore(
        artifacts.artifact_path("material-task", REMOTE_MATERIAL_STAGING_REF)
    )
    mapping = staging.get_many([importable[0]["object_key"]])
    assert mapping[importable[0]["object_key"]]["payload_member"].startswith("files/")
    result = artifacts.read_json("material-task", SCAN_RESULT_REF)
    assert result["stage"] == "awaiting_confirmation"
    assert result["importable_images"] == 1
    assert result["remote_review_archive_ref"].endswith("review.zip")


def test_review_commit_rejects_candidate_target_prefix_tampering(tmp_path):
    source = tmp_path / "source"
    _image(source / "one.jpg")
    archive = tmp_path / "review.zip"
    built = build_material_review_archive(
        source,
        archive,
        task_id="material-task",
        project_id="project-one",
        execution_generation=1,
        storage_source_id="s3-target",
        storage_type="s3",
        target_prefix="incoming",
    )

    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive, "r") as original, zipfile.ZipFile(
        tampered, "w", compression=zipfile.ZIP_STORED
    ) as output:
        for info in original.infolist():
            data = original.read(info.filename)
            if info.filename == "review.jsonl":
                row = json.loads(data.decode("utf-8").strip())
                row["object_key"] = "outside/one.jpg"
                data = (
                    json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    + "\n"
                ).encode("utf-8")
            output.writestr(info, data)

    artifacts = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(RemoteMaterialImportError) as unsafe:
        commit_material_review_archive(
            artifacts=artifacts,
            task_id="material-task",
            project_id="project-one",
            execution_generation=1,
            archive_path=tampered,
            archive_sha256=_sha(tampered),
            archive_size_bytes=tampered.stat().st_size,
            expected_source_id="s3-target",
            expected_storage_type="s3",
            expected_prefix="incoming",
        )
    assert unsafe.value.code == "REMOTE_MATERIAL_TARGET_MISMATCH"


def test_review_commit_rejects_payload_content_tampering_even_when_outer_hash_matches(tmp_path):
    source = tmp_path / "source"
    _image(source / "one.jpg")
    archive = tmp_path / "review.zip"
    build_material_review_archive(
        source,
        archive,
        task_id="material-task",
        project_id="project-one",
        execution_generation=2,
        storage_source_id="s3-target",
        storage_type="s3",
        target_prefix="incoming",
    )

    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive, "r") as original, zipfile.ZipFile(
        tampered, "w", compression=zipfile.ZIP_STORED
    ) as output:
        for info in original.infolist():
            data = original.read(info.filename)
            if info.filename.startswith("files/"):
                data = data + b"tamper"
            output.writestr(info, data)

    artifacts = ArtifactStore(tmp_path / "artifacts")
    with pytest.raises(RemoteMaterialImportError) as changed:
        commit_material_review_archive(
            artifacts=artifacts,
            task_id="material-task",
            project_id="project-one",
            execution_generation=2,
            archive_path=tampered,
            archive_sha256=_sha(tampered),
            archive_size_bytes=tampered.stat().st_size,
            expected_source_id="s3-target",
            expected_storage_type="s3",
            expected_prefix="incoming",
        )
    assert changed.value.code in {
        "REMOTE_MATERIAL_PAYLOAD_CHANGED",
        "REMOTE_MATERIAL_PAYLOAD_INVALID",
    }



class _StorageScanReviewProvider:
    storage_type = "s3"

    def __init__(self, rows, payloads):
        self.rows = list(rows)
        self.payloads = dict(payloads)

    def iter_objects(self, prefix="", *, recursive=True):
        for row in self.rows:
            if not prefix or row.key == prefix or row.key.startswith(prefix.rstrip("/") + "/"):
                yield row

    def open_reader(self, key):
        return io.BytesIO(self.payloads[key])

    def exists(self, key):
        return key in self.payloads


def test_storage_scan_review_is_metadata_only_and_server_verified(tmp_path):
    image_buffer = io.BytesIO()
    Image.new("RGB", (24, 18), "purple").save(image_buffer, format="JPEG")
    image = image_buffer.getvalue()
    digest = hashlib.sha256(image).hexdigest()
    provider = _StorageScanReviewProvider(
        [ObjectMetadata(
            key="incoming/2026/a.jpg",
            size_bytes=len(image),
            etag='"etag-a"',
            content_type="image/jpeg",
            sha256=digest,
        )],
        {"incoming/2026/a.jpg": image},
    )
    archive = tmp_path / "storage-scan-review.zip"
    built = build_storage_scan_material_review_archive(
        provider,
        archive,
        task_id="storage-scan-review",
        project_id="project-storage-scan",
        execution_generation=1,
        storage_source_id="s3-source",
        storage_type="s3",
        prefix="incoming/2026",
        recursive=True,
        import_format="images",
    )

    with zipfile.ZipFile(archive, "r") as review:
        names = set(review.namelist())
        meta = json.loads(review.read("meta.json"))
        row = json.loads(review.read("review.jsonl").decode("utf-8").strip())
        assert meta["mode"] == "storage_scan"
        assert meta["payload_mode"] == "source_reference"
        assert row["object_key"] == "incoming/2026/a.jpg"
        assert row["content_sha256"] == digest
        assert row["etag"] == '"etag-a"'
        assert row["payload_member"] == ""
        assert not any(name.startswith("files/") for name in names)

    artifacts = ArtifactStore(tmp_path / "artifacts")
    committed = commit_material_review_archive(
        artifacts=artifacts,
        task_id="storage-scan-review",
        project_id="project-storage-scan",
        execution_generation=1,
        archive_path=built["path"],
        archive_sha256=built["sha256"],
        archive_size_bytes=built["size_bytes"],
        expected_source_id="s3-source",
        expected_storage_type="s3",
        expected_prefix="incoming/2026",
        expected_mode="storage_scan",
        expected_import_format="images",
    )
    assert committed["material_review_committed"] is True
    result = artifacts.read_json("storage-scan-review", "scan/result.json")
    assert result["mode"] == "agent_storage_scan"
    assert result["importable_images"] == 1



def test_storage_scan_coco_review_commits_generic_detection_truth(tmp_path):
    image_buffer = io.BytesIO()
    Image.new("RGB", (100, 80), "orange").save(image_buffer, format="JPEG")
    image = image_buffer.getvalue()
    coco = json.dumps({
        "images": [{"id": 1, "file_name": "a.jpg", "width": 100, "height": 80}],
        "annotations": [{"id": 10, "image_id": 1, "category_id": 7, "bbox": [10, 20, 30, 40]}],
        "categories": [{"id": 7, "name": "smoke"}],
    }).encode()
    provider = _StorageScanReviewProvider(
        [
            ObjectMetadata(
                key="incoming/2026/train/a.jpg",
                size_bytes=len(image),
                etag='"etag-a"',
                content_type="image/jpeg",
                sha256=hashlib.sha256(image).hexdigest(),
            ),
            ObjectMetadata(
                key="incoming/2026/train/_annotations.coco.json",
                size_bytes=len(coco),
                etag='"etag-coco"',
                content_type="application/json",
                sha256=hashlib.sha256(coco).hexdigest(),
            ),
        ],
        {
            "incoming/2026/train/a.jpg": image,
            "incoming/2026/train/_annotations.coco.json": coco,
        },
    )
    archive = tmp_path / "coco-review.zip"
    built = build_storage_scan_material_review_archive(
        provider,
        archive,
        task_id="coco-storage-scan",
        project_id="project-coco",
        execution_generation=1,
        storage_source_id="s3-source",
        storage_type="s3",
        prefix="incoming/2026",
        recursive=True,
        import_format="coco",
    )
    with zipfile.ZipFile(archive, "r") as review:
        meta = json.loads(review.read("meta.json"))
        assert meta["import_format"] == "coco"
        assert meta["annotation_member"] == REVIEW_DETECTION_ANNOTATIONS_MEMBER
        assert meta["classes"] == [{"class_id": 7, "name": "smoke"}]
        assert REVIEW_DETECTION_ANNOTATIONS_MEMBER in review.namelist()
        assert not any(name.startswith("files/") for name in review.namelist())

    artifacts = ArtifactStore(tmp_path / "coco-artifacts")
    committed = commit_material_review_archive(
        artifacts=artifacts,
        task_id="coco-storage-scan",
        project_id="project-coco",
        execution_generation=1,
        archive_path=built["path"],
        archive_sha256=built["sha256"],
        archive_size_bytes=built["size_bytes"],
        expected_source_id="s3-source",
        expected_storage_type="s3",
        expected_prefix="incoming/2026",
        expected_mode="storage_scan",
        expected_import_format="coco",
        platform_labels=[],
    )
    assert committed["material_review_committed"] is True
    result = artifacts.read_json("coco-storage-scan", SCAN_RESULT_REF)
    assert result["import_format"] == "coco"
    assert result["quality"]["boxes"] == 1
    assert result["external_classes"][0]["class_id"] == 7
    assert result["external_classes"][0]["name"] == "smoke"
    store = ImportCandidateStore(
        artifacts.artifact_path("coco-storage-scan", MANIFEST_REF)
    )
    candidate = list(store.iter_candidates())[0]
    annotation = store.annotations_for_keys([candidate["object_key"]])[candidate["object_key"]]
    assert annotation["annotation_status"] == "annotated"
    assert annotation["boxes"][0]["class_id"] == 7
