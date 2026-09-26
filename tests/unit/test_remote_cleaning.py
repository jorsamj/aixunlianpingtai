from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from platform_core.material_batches import BatchSelection
from platform_core.material_repository import MaterialRepository
from platform_core.remote_cleaning import RemoteCleaningError, commit_remote_cleaning_review
from platform_core.task_runtime import ArtifactStore


def _material(project, image_id, object_key, content_sha, size_bytes):
    return MaterialRepository(project).upsert({
        "id": image_id,
        "filename": object_key.rsplit("/", 1)[-1],
        "storage_source_id": "s3-clean",
        "storage_type": "s3",
        "object_key": object_key,
        "content_sha256": content_sha,
        "size_bytes": size_bytes,
        "etag": f"etag-{image_id}",
    })


def _freeze(artifacts, task_id, image_ids):
    manifest = BatchSelection(artifacts.artifact_path(task_id, "selection.sqlite3"))
    try:
        manifest.database.executemany(
            "INSERT INTO selection(image_id,state) VALUES (?,?)",
            ((image_id, "pending") for image_id in image_ids),
        )
        manifest.database.execute(
            "INSERT INTO meta(key,value) VALUES ('frozen','2026-09-18T00:00:00+00:00')"
        )
    finally:
        manifest.close()


def _write_review(path, task, generation, rows):
    body = [{
        "schema_version": 1,
        "task_id": task.task_id,
        "project_id": task.project_id,
        "execution_generation": generation,
        "operation": "CLEAN",
        "total": len(rows),
    }, *rows]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in body),
        encoding="utf-8",
    )
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return digest, path.stat().st_size


def _metric(sha, *, dhash=0x1010101010101010, blur=100.0):
    return {
        "width": 640,
        "height": 480,
        "sha256": sha,
        "dhash": dhash,
        "blur_score": blur,
        "brightness": 120.0,
        "entropy": 6.5,
        "analysis_downsampled": False,
    }


def test_remote_cleaning_commit_recomputes_duplicate_rules_and_existing_truth(tmp_path):
    artifacts = ArtifactStore(tmp_path / "task-runtime" / "artifacts")
    project = tmp_path / "projects" / "p-clean"
    task = SimpleNamespace(task_id="clean-remote-1", project_id="p-clean")
    generation = 1
    payload = {
        "operation": "CLEAN",
        "options": {
            "exact_duplicate": True,
            "near_duplicate": True,
            "blur_check": True,
        },
    }
    source_bytes = b"same-image-content"
    source_sha = hashlib.sha256(source_bytes).hexdigest()
    _material(project, "img-a", "dataset/a.jpg", source_sha, len(source_bytes))
    _material(project, "img-b", "dataset/b.jpg", source_sha, len(source_bytes))
    _freeze(artifacts, task.task_id, ["img-a", "img-b"])

    review = tmp_path / "review.jsonl"
    digest, size = _write_review(review, task, generation, [
        {
            "image_id": "img-a",
            "source_sha256": source_sha,
            "source_size_bytes": len(source_bytes),
            "status": "analyzed",
            "metrics": _metric(source_sha),
            "error": "",
        },
        {
            "image_id": "img-b",
            "source_sha256": source_sha,
            "source_size_bytes": len(source_bytes),
            "status": "analyzed",
            "metrics": _metric(source_sha),
            "error": "",
        },
    ])

    result = commit_remote_cleaning_review(
        artifacts=artifacts,
        task=task,
        project_path=project,
        payload=payload,
        review_path=review,
        execution_generation=generation,
        expected_sha256=digest,
        expected_size_bytes=size,
    )

    assert result["total"] == 2
    assert result["processed"] == 2
    assert result["succeeded"] == 2
    assert result["failed"] == 0
    assert result["flagged"] == 1
    assert result["remote_cleaning_verified"] is True

    manifest = BatchSelection(artifacts.artifact_path(task.task_id, "selection.sqlite3"))
    try:
        states = dict(manifest.database.execute(
            "SELECT image_id,state FROM selection ORDER BY image_id"
        ))
        clean_rows = {
            row[0]: json.loads(row[1])
            for row in manifest.database.execute(
                "SELECT image_id,result_json FROM clean_results ORDER BY image_id"
            )
        }
    finally:
        manifest.close()
    assert states == {"img-a": "succeeded", "img-b": "succeeded"}
    assert clean_rows["img-a"]["issues"] == []
    assert clean_rows["img-b"]["issues"] == [{
        "code": "exact_duplicate",
        "name": "重复图",
        "detail": "与另一张图片完全相同",
        "related_image_id": "img-a",
    }]

    materials = MaterialRepository(project)
    assert materials.get("img-a")["clean_status"] == "passed"
    assert materials.get("img-b")["clean_status"] == "needs_review"
    assert materials.get("img-b")["clean_issues"][0]["code"] == "exact_duplicate"


def test_remote_cleaning_commit_rejects_source_evidence_change(tmp_path):
    artifacts = ArtifactStore(tmp_path / "task-runtime" / "artifacts")
    project = tmp_path / "projects" / "p-clean-change"
    task = SimpleNamespace(task_id="clean-remote-change", project_id="p-clean-change")
    actual = b"actual"
    actual_sha = hashlib.sha256(actual).hexdigest()
    _material(project, "img-a", "dataset/a.jpg", actual_sha, len(actual))
    _freeze(artifacts, task.task_id, ["img-a"])

    review = tmp_path / "changed.jsonl"
    digest, size = _write_review(review, task, 2, [{
        "image_id": "img-a",
        "source_sha256": "f" * 64,
        "source_size_bytes": len(actual),
        "status": "analyzed",
        "metrics": _metric("f" * 64),
        "error": "",
    }])

    with pytest.raises(RemoteCleaningError) as denied:
        commit_remote_cleaning_review(
            artifacts=artifacts,
            task=task,
            project_path=project,
            payload={"operation": "CLEAN", "options": {"blur_check": True}},
            review_path=review,
            execution_generation=2,
            expected_sha256=digest,
            expected_size_bytes=size,
        )
    assert denied.value.code == "REMOTE_CLEANING_SOURCE_CHANGED"


def test_remote_cleaning_commit_maps_corrupt_to_existing_cleaning_semantics(tmp_path):
    artifacts = ArtifactStore(tmp_path / "task-runtime" / "artifacts")
    project = tmp_path / "projects" / "p-clean-corrupt"
    task = SimpleNamespace(task_id="clean-remote-corrupt", project_id="p-clean-corrupt")
    raw = b"not-an-image"
    digest_source = hashlib.sha256(raw).hexdigest()
    _material(project, "img-corrupt", "dataset/bad.jpg", digest_source, len(raw))
    _freeze(artifacts, task.task_id, ["img-corrupt"])

    review = tmp_path / "corrupt.jsonl"
    digest, size = _write_review(review, task, 3, [{
        "image_id": "img-corrupt",
        "source_sha256": digest_source,
        "source_size_bytes": len(raw),
        "status": "corrupt",
        "metrics": None,
        "error": "cannot identify image file",
    }])
    result = commit_remote_cleaning_review(
        artifacts=artifacts,
        task=task,
        project_path=project,
        payload={"operation": "CLEAN", "options": {"corrupt_check": True}},
        review_path=review,
        execution_generation=3,
        expected_sha256=digest,
        expected_size_bytes=size,
    )
    assert result["succeeded"] == 1
    assert result["flagged"] == 1
    material = MaterialRepository(project).get("img-corrupt")
    assert material["clean_status"] == "needs_review"
    assert material["clean_issues"][0]["code"] == "corrupt"
