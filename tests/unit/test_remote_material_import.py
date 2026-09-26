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
    build_detection_material_review_archive,
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


@pytest.mark.parametrize("import_format", ["coco", "voc"])
def test_detection_zip_review_round_trip_commits_embedded_annotation_truth(tmp_path, import_format):
    source = tmp_path / import_format
    if import_format == "coco":
        image = _image(source / "train" / "a.jpg")
        annotation = {
            "images": [{"id": 1, "file_name": "a.jpg", "width": 48, "height": 32}],
            "annotations": [{"id": 1, "image_id": 1, "category_id": 7, "bbox": [4, 6, 20, 12]}],
            "categories": [{"id": 7, "name": "smoke"}],
        }
        (source / "train" / "_annotations.coco.json").write_text(
            json.dumps(annotation), encoding="utf-8",
        )
        expected_key = "incoming/coco/train/a.jpg"
        expected_class = {"class_id": 7, "name": "smoke"}
    else:
        image = _image(source / "val" / "JPEGImages" / "a.jpg")
        annotation_path = source / "val" / "Annotations" / "a.xml"
        annotation_path.parent.mkdir(parents=True, exist_ok=True)
        annotation_path.write_text(
            "<annotation><filename>a.jpg</filename><object><name>fire</name>"
            "<bndbox><xmin>2</xmin><ymin>3</ymin><xmax>22</xmax><ymax>18</ymax>"
            "</bndbox></object></annotation>",
            encoding="utf-8",
        )
        expected_key = "incoming/voc/val/JPEGImages/a.jpg"
        expected_class = {"class_id": 0, "name": "fire"}

    archive = tmp_path / f"{import_format}-review.zip"
    built = build_detection_material_review_archive(
        source,
        archive,
        task_id=f"{import_format}-zip",
        project_id="project-detection",
        execution_generation=1,
        storage_source_id="s3-target",
        storage_type="s3",
        target_prefix=f"incoming/{import_format}",
        import_format=import_format,
    )

    assert built["candidate_count"] == 1
    assert built["counts"] == {"IMPORTABLE": 1}
    assert expected_class in built["classes"]
    with zipfile.ZipFile(archive, "r") as review:
        meta = json.loads(review.read("meta.json"))
        rows = [
            json.loads(line)
            for line in review.read("review.jsonl").decode("utf-8").splitlines()
        ]
        assert meta["mode"] == "zip_scan"
        assert meta["payload_mode"] == "embedded"
        assert meta["import_format"] == import_format
        assert meta["annotation_member"] == REVIEW_DETECTION_ANNOTATIONS_MEMBER
        assert rows[0]["object_key"] == expected_key
        assert rows[0]["payload_member"].startswith("files/")
        assert review.read(rows[0]["payload_member"]) == image.read_bytes()
        assert REVIEW_DETECTION_ANNOTATIONS_MEMBER in review.namelist()

    artifacts = ArtifactStore(tmp_path / f"{import_format}-artifacts")
    committed = commit_material_review_archive(
        artifacts=artifacts,
        task_id=f"{import_format}-zip",
        project_id="project-detection",
        execution_generation=1,
        archive_path=archive,
        archive_sha256=built["sha256"],
        archive_size_bytes=built["size_bytes"],
        expected_source_id="s3-target",
        expected_storage_type="s3",
        expected_prefix=f"incoming/{import_format}",
        expected_mode="zip_scan",
        expected_import_format=import_format,
        platform_labels=[],
    )
    assert committed["material_review_committed"] is True
    store = ImportCandidateStore(
        artifacts.artifact_path(f"{import_format}-zip", MANIFEST_REF)
    )
    annotations = store.annotations_for_keys([expected_key])
    assert annotations[expected_key]["annotation_status"] == "annotated"
    assert len(annotations[expected_key]["boxes"]) == 1
    staging = RemoteMaterialStagingStore(
        artifacts.artifact_path(
            f"{import_format}-zip", REMOTE_MATERIAL_STAGING_REF,
        )
    )
    staged = staging.get_many([expected_key])
    assert staged[expected_key]["payload_member"].startswith("files/")


def test_storage_rescan_root_review_is_explicit_and_preserves_same_hash_object_identity(tmp_path):
    image_buffer = io.BytesIO()
    Image.new("RGB", (24, 18), "purple").save(image_buffer, format="JPEG")
    image = image_buffer.getvalue()
    digest = hashlib.sha256(image).hexdigest()
    provider = _StorageScanReviewProvider(
        [
            ObjectMetadata(
                key="a.jpg", size_bytes=len(image), etag='"etag-a"',
                sha256=digest, content_type="image/jpeg",
            ),
            ObjectMetadata(
                key="nested/b.jpg", size_bytes=len(image), etag='"etag-b"',
                sha256=digest, content_type="image/jpeg",
            ),
        ],
        {"a.jpg": image, "nested/b.jpg": image},
    )
    with pytest.raises(RemoteMaterialImportError) as blocked:
        build_storage_scan_material_review_archive(
            provider,
            tmp_path / "blocked.zip",
            task_id="rescan-root",
            project_id="project-rescan",
            execution_generation=1,
            storage_source_id="s3-source",
            storage_type="s3",
            prefix="",
            recursive=True,
            import_format="images",
        )
    assert blocked.value.code == "REMOTE_MATERIAL_PREFIX_REQUIRED"

    archive = tmp_path / "rescan.zip"
    built = build_storage_scan_material_review_archive(
        provider,
        archive,
        task_id="rescan-root",
        project_id="project-rescan",
        execution_generation=2,
        storage_source_id="s3-source",
        storage_type="s3",
        prefix="",
        recursive=True,
        import_format="images",
        intent="storage_rescan",
    )
    assert built["counts"]["IMPORTABLE"] == 2
    assert built["counts"].get("DUPLICATE", 0) == 0
    with zipfile.ZipFile(archive, "r") as review:
        meta = json.loads(review.read("meta.json"))
        rows = [
            json.loads(line)
            for line in review.read("review.jsonl").decode("utf-8").splitlines()
        ]
    assert meta["intent"] == "storage_rescan"
    assert meta["target_prefix"] == ""
    assert {row["object_key"] for row in rows} == {"a.jpg", "nested/b.jpg"}
    assert {row["content_sha256"] for row in rows} == {digest}


def test_storage_rescan_root_yolo_review_keeps_annotation_evidence_and_object_identity(tmp_path):
    image_buffer = io.BytesIO()
    Image.new("RGB", (100, 80), "orange").save(image_buffer, format="JPEG")
    image = image_buffer.getvalue()
    yaml_bytes = b"path: .\ntrain: images/train\nnames:\n  0: smoke\n"
    label_bytes = b"0 0.5 0.5 0.2 0.25\n"
    payloads = {
        "data.yaml": yaml_bytes,
        "images/train/a.jpg": image,
        "labels/train/a.txt": label_bytes,
    }
    rows = [
        ObjectMetadata(
            key=key,
            size_bytes=len(value),
            etag=f'"etag-{index}"',
            sha256=hashlib.sha256(value).hexdigest(),
            content_type="image/jpeg" if key.endswith(".jpg") else "text/plain",
        )
        for index, (key, value) in enumerate(payloads.items(), 1)
    ]
    provider = _StorageScanReviewProvider(rows, payloads)
    archive = tmp_path / "yolo-rescan.zip"
    built = build_storage_scan_material_review_archive(
        provider,
        archive,
        task_id="rescan-yolo",
        project_id="project-yolo",
        execution_generation=2,
        storage_source_id="s3-source",
        storage_type="s3",
        prefix="",
        recursive=True,
        import_format="yolo",
        dataset_yaml="data.yaml",
        intent="storage_rescan",
    )
    assert built["counts"]["IMPORTABLE"] == 1
    with zipfile.ZipFile(archive, "r") as review:
        meta = json.loads(review.read("meta.json"))
        annotation = json.loads(
            review.read("yolo/annotations.jsonl").decode("utf-8").strip()
        )
    assert meta["intent"] == "storage_rescan"
    assert meta["target_prefix"] == ""
    assert meta["dataset_yaml"] == "data.yaml"
    assert annotation["object_key"] == "images/train/a.jpg"
    assert annotation["annotation_status"] == "annotated"
    assert annotation["boxes"][0]["class_id"] == 0
    assert annotation["label_object"]["sha256"] == hashlib.sha256(label_bytes).hexdigest()
    assert annotation["dataset_object"]["sha256"] == hashlib.sha256(yaml_bytes).hexdigest()

    artifacts = ArtifactStore(tmp_path / "yolo-rescan-artifacts")
    committed = commit_material_review_archive(
        artifacts=artifacts,
        task_id="rescan-yolo",
        project_id="project-yolo",
        execution_generation=2,
        archive_path=built["path"],
        archive_sha256=built["sha256"],
        archive_size_bytes=built["size_bytes"],
        expected_source_id="s3-source",
        expected_storage_type="s3",
        expected_prefix="",
        expected_mode="storage_scan",
        expected_import_format="yolo",
        expected_dataset_yaml="data.yaml",
        expected_intent="storage_rescan",
        platform_labels=[],
    )
    assert committed["material_review_committed"] is True
    committed_store = ImportCandidateStore(
        artifacts.artifact_path("rescan-yolo", MANIFEST_REF)
    )
    refs = committed_store.inventory_for_keys(
        ["data.yaml", "labels/train/a.txt"]
    )
    assert refs["data.yaml"]["sha256"] == hashlib.sha256(yaml_bytes).hexdigest()
    assert refs["labels/train/a.txt"]["sha256"] == hashlib.sha256(label_bytes).hexdigest()


def test_storage_rescan_root_coco_carries_verified_json_source_evidence(tmp_path):
    image_buffer = io.BytesIO()
    Image.new("RGB", (100, 80), "orange").save(image_buffer, format="JPEG")
    image = image_buffer.getvalue()
    coco = json.dumps({
        "images": [{"id": 1, "file_name": "a.jpg", "width": 100, "height": 80}],
        "annotations": [{"id": 1, "image_id": 1, "category_id": 7, "bbox": [10, 20, 30, 40]}],
        "categories": [{"id": 7, "name": "smoke"}],
    }, separators=(",", ":")).encode()
    json_key = "train/_annotations.coco.json"
    payloads = {"train/a.jpg": image, json_key: coco}
    provider = _StorageScanReviewProvider(
        [
            ObjectMetadata(
                key=key,
                size_bytes=len(value),
                etag=f'"etag-{index}"',
                content_type="image/jpeg" if key.endswith(".jpg") else "application/json",
                sha256="" if key.endswith(".json") else hashlib.sha256(value).hexdigest(),
            )
            for index, (key, value) in enumerate(payloads.items(), 1)
        ],
        payloads,
    )
    archive = tmp_path / "coco-rescan.zip"
    built = build_storage_scan_material_review_archive(
        provider,
        archive,
        task_id="rescan-coco",
        project_id="project-coco-rescan",
        execution_generation=3,
        storage_source_id="s3-source",
        storage_type="s3",
        prefix="",
        recursive=True,
        import_format="coco",
        intent="storage_rescan",
    )
    expected_sha = hashlib.sha256(coco).hexdigest()
    with zipfile.ZipFile(archive, "r") as review:
        meta = json.loads(review.read("meta.json"))
        annotation = json.loads(
            review.read(REVIEW_DETECTION_ANNOTATIONS_MEMBER).decode("utf-8").strip()
        )
    assert meta["intent"] == "storage_rescan"
    assert meta["target_prefix"] == ""
    assert annotation["label_key"] == json_key
    assert annotation["dataset_key"] == json_key
    assert annotation["label_object"]["sha256"] == expected_sha
    assert annotation["dataset_object"]["sha256"] == expected_sha

    artifacts = ArtifactStore(tmp_path / "coco-rescan-artifacts")
    committed = commit_material_review_archive(
        artifacts=artifacts,
        task_id="rescan-coco",
        project_id="project-coco-rescan",
        execution_generation=3,
        archive_path=built["path"],
        archive_sha256=built["sha256"],
        archive_size_bytes=built["size_bytes"],
        expected_source_id="s3-source",
        expected_storage_type="s3",
        expected_prefix="",
        expected_mode="storage_scan",
        expected_import_format="coco",
        expected_intent="storage_rescan",
        platform_labels=[],
    )
    assert committed["material_review_committed"] is True
    store = ImportCandidateStore(
        artifacts.artifact_path("rescan-coco", MANIFEST_REF)
    )
    identity = store.inventory_for_keys([json_key])[json_key]
    assert identity["sha256"] == expected_sha
    annotation_truth = store.annotations_for_keys(["train/a.jpg"])["train/a.jpg"]
    assert annotation_truth["label_key"] == json_key
    assert annotation_truth["yaml_key"] == json_key


def test_storage_rescan_coco_keeps_unreferenced_source_image_in_image_truth(tmp_path):
    image_buffer = io.BytesIO()
    Image.new("RGB", (100, 80), "orange").save(image_buffer, format="JPEG")
    image = image_buffer.getvalue()
    extra_buffer = io.BytesIO()
    Image.new("RGB", (120, 90), "blue").save(extra_buffer, format="JPEG")
    extra = extra_buffer.getvalue()
    coco = json.dumps({
        "images": [{"id": 1, "file_name": "a.jpg", "width": 100, "height": 80}],
        "annotations": [],
        "categories": [{"id": 7, "name": "smoke"}],
    }).encode()
    payloads = {
        "train/a.jpg": image,
        "extra.jpg": extra,
        "train/_annotations.coco.json": coco,
    }
    provider = _StorageScanReviewProvider(
        [
            ObjectMetadata(
                key=key, size_bytes=len(value), etag=f'"etag-{index}"',
                sha256=hashlib.sha256(value).hexdigest(),
                content_type="image/jpeg" if key.endswith(".jpg") else "application/json",
            )
            for index, (key, value) in enumerate(payloads.items(), 1)
        ],
        payloads,
    )
    archive = tmp_path / "coco-full-source-rescan.zip"
    build_storage_scan_material_review_archive(
        provider, archive,
        task_id="coco-full-source", project_id="p-coco-full",
        execution_generation=1, storage_source_id="s3-source", storage_type="s3",
        prefix="", recursive=True, import_format="coco", intent="storage_rescan",
    )
    with zipfile.ZipFile(archive, "r") as review:
        rows = [
            json.loads(line)
            for line in review.read("review.jsonl").decode("utf-8").splitlines()
        ]
        annotations = [
            json.loads(line)
            for line in review.read(REVIEW_DETECTION_ANNOTATIONS_MEMBER).decode("utf-8").splitlines()
        ]
    assert {row["object_key"] for row in rows} == {"train/a.jpg", "extra.jpg"}
    assert {row["object_key"] for row in annotations} == {"train/a.jpg"}


def test_storage_rescan_root_voc_carries_verified_xml_source_evidence(tmp_path):
    image_buffer = io.BytesIO()
    Image.new("RGB", (100, 80), "orange").save(image_buffer, format="JPEG")
    image = image_buffer.getvalue()
    xml_key = "train/Annotations/a.xml"
    xml = b"""<annotation><filename>a.jpg</filename><object><name>fire</name><bndbox><xmin>10</xmin><ymin>20</ymin><xmax>40</xmax><ymax>60</ymax></bndbox></object></annotation>"""
    payloads = {
        "train/JPEGImages/a.jpg": image,
        xml_key: xml,
    }
    provider = _StorageScanReviewProvider(
        [
            ObjectMetadata(
                key=key,
                size_bytes=len(value),
                etag=f'"etag-{index}"',
                sha256=hashlib.sha256(value).hexdigest(),
                content_type="image/jpeg" if key.endswith(".jpg") else "application/xml",
            )
            for index, (key, value) in enumerate(payloads.items(), 1)
        ],
        payloads,
    )
    archive = tmp_path / "voc-rescan.zip"
    built = build_storage_scan_material_review_archive(
        provider,
        archive,
        task_id="rescan-voc",
        project_id="project-voc-rescan",
        execution_generation=4,
        storage_source_id="s3-source",
        storage_type="s3",
        prefix="",
        recursive=True,
        import_format="voc",
        intent="storage_rescan",
    )
    expected_sha = hashlib.sha256(xml).hexdigest()
    with zipfile.ZipFile(archive, "r") as review:
        meta = json.loads(review.read("meta.json"))
        annotation = json.loads(
            review.read(REVIEW_DETECTION_ANNOTATIONS_MEMBER).decode("utf-8").strip()
        )
    assert meta["intent"] == "storage_rescan"
    assert meta["import_format"] == "voc"
    assert annotation["label_key"] == xml_key
    assert annotation["dataset_key"] == xml_key
    assert annotation["label_object"]["sha256"] == expected_sha
    assert annotation["dataset_object"]["sha256"] == expected_sha

    artifacts = ArtifactStore(tmp_path / "voc-rescan-artifacts")
    committed = commit_material_review_archive(
        artifacts=artifacts,
        task_id="rescan-voc",
        project_id="project-voc-rescan",
        execution_generation=4,
        archive_path=built["path"],
        archive_sha256=built["sha256"],
        archive_size_bytes=built["size_bytes"],
        expected_source_id="s3-source",
        expected_storage_type="s3",
        expected_prefix="",
        expected_mode="storage_scan",
        expected_import_format="voc",
        expected_intent="storage_rescan",
        platform_labels=[],
    )
    assert committed["material_review_committed"] is True
    store = ImportCandidateStore(
        artifacts.artifact_path("rescan-voc", MANIFEST_REF)
    )
    identity = store.inventory_for_keys([xml_key])[xml_key]
    assert identity["sha256"] == expected_sha
    truth = store.annotations_for_keys(["train/JPEGImages/a.jpg"])[
        "train/JPEGImages/a.jpg"
    ]
    assert truth["label_key"] == xml_key
    assert truth["yaml_key"] == xml_key


def test_large_storage_scan_review_streams_verified_rows(tmp_path, monkeypatch):
    total = 10_001
    rows_file = tmp_path / "large-review.jsonl"
    with rows_file.open("w", encoding="utf-8", newline="\n") as stream:
        for index in range(total):
            stream.write(json.dumps({
                "object_key": f"incoming/image-{index:05d}.jpg",
                "filename": f"image-{index:05d}.jpg",
                "storage_source_id": "s3-source",
                "storage_type": "s3",
                "content_sha256": f"{index % 16:x}" * 64,
                "size_bytes": 128,
                "etag": f'"etag-{index}"',
                "width": 64,
                "height": 48,
                "status": "IMPORTABLE",
                "error": "",
                "duplicate": False,
            }, sort_keys=True, separators=(",", ":")) + "\n")

    archive = tmp_path / "large-review.zip"
    meta = {
        "schema_version": 1,
        "task_id": "large-stream-review",
        "project_id": "project-large",
        "execution_generation": 1,
        "mode": "storage_scan",
        "payload_mode": "source_reference",
        "import_format": "images",
        "storage_source_id": "s3-source",
        "storage_type": "s3",
        "target_prefix": "incoming",
        "intent": "",
        "candidate_count": total,
        "counts": {"IMPORTABLE": total},
    }
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as review:
        review.write(rows_file, arcname="review.jsonl")
        review.writestr(
            "meta.json",
            json.dumps(meta, sort_keys=True, separators=(",", ":")),
        )

    original_upsert = ImportCandidateStore.upsert_many
    original_stage = RemoteMaterialStagingStore.replace_many
    candidate_inputs = []
    staging_inputs = []

    def guarded_upsert(self, rows):
        assert not isinstance(rows, (list, tuple))
        candidate_inputs.append(type(rows).__name__)
        return original_upsert(self, rows)

    def guarded_stage(self, rows):
        assert not isinstance(rows, (list, tuple))
        staging_inputs.append(type(rows).__name__)
        return original_stage(self, rows)

    monkeypatch.setattr(ImportCandidateStore, "upsert_many", guarded_upsert)
    monkeypatch.setattr(RemoteMaterialStagingStore, "replace_many", guarded_stage)

    artifacts = ArtifactStore(tmp_path / "large-artifacts")
    committed = commit_material_review_archive(
        artifacts=artifacts,
        task_id="large-stream-review",
        project_id="project-large",
        execution_generation=1,
        archive_path=archive,
        archive_sha256=_sha(archive),
        archive_size_bytes=archive.stat().st_size,
        expected_source_id="s3-source",
        expected_storage_type="s3",
        expected_prefix="incoming",
        expected_mode="storage_scan",
        expected_import_format="images",
    )

    assert committed["material_candidates"] == total
    assert committed["material_importable"] == total
    assert candidate_inputs == ["generator"]
    assert staging_inputs == ["generator"]
    store = ImportCandidateStore(
        artifacts.artifact_path("large-stream-review", MANIFEST_REF)
    )
    assert store.counts() == {"IMPORTABLE": total}


def test_remote_material_staging_stream_rolls_back_late_invalid_row(tmp_path):
    store = RemoteMaterialStagingStore(tmp_path / "staged.sqlite3")
    digest = "a" * 64
    store.replace_many([{
        "object_key": "old.jpg",
        "payload_member": "files/old.jpg",
        "content_sha256": digest,
        "size_bytes": 10,
    }])

    def replacement_rows():
        yield {
            "object_key": "new.jpg",
            "payload_member": "files/new.jpg",
            "content_sha256": digest,
            "size_bytes": 20,
        }
        yield {
            "object_key": "broken.jpg",
            "payload_member": "",
            "content_sha256": digest,
            "size_bytes": 20,
        }

    with pytest.raises(RemoteMaterialImportError) as error:
        store.replace_many(replacement_rows())
    assert error.value.code == "REMOTE_MATERIAL_STAGING_INVALID"
    assert "old.jpg" in store.get_many(["old.jpg"])
    assert store.get_many(["new.jpg"]) == {}

