from __future__ import annotations

from io import BytesIO

import app as app_module
from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.storage.models import StorageType
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository


class _PreviewProvider:
    storage_type = StorageType.S3

    def generate_preview_url(self, object_key, *, expires_seconds=900):
        assert expires_seconds == 300
        return "https://preview.example.invalid/" + object_key

    def open_reader(self, object_key):
        return BytesIO(("sample:" + object_key).encode())


class _LocalProvider(_PreviewProvider):
    storage_type = StorageType.LOCAL

    def generate_preview_url(self, object_key, *, expires_seconds=900):
        return None


class _Manager:
    def __init__(self, provider):
        self.provider = provider

    def provider_for(self, source_id):
        assert source_id == "source-a"
        return self.provider


def _seed_review(tmp_path, monkeypatch, project_id, *, provider):
    root = tmp_path / "runtime"
    repository = TaskRepository(root / "tasks.sqlite3")
    artifacts = ArtifactStore(root / "artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)
    monkeypatch.setattr(app_module, "storage_manager", lambda _project_id: _Manager(provider))

    task_id = "sample-review"
    artifacts.atomic_write_json(task_id, "request.json", {
        "mode": "storage_scan",
        "storage_source_id": "source-a",
        "import_format": "yolo",
    })
    repository.create(TaskRecord.new(
        task_id,
        project_id,
        TaskKind.MATERIAL_IMPORT,
        "request.json",
        "storage:source-a",
    ))
    store = ImportCandidateStore(
        artifacts.artifact_path(task_id, "scan/candidates.sqlite3")
    )
    store.upsert_many([
        {
            "object_key": "images/a.jpg",
            "filename": "a.jpg",
            "storage_source_id": "source-a",
            "storage_type": "s3",
            "width": 100,
            "height": 80,
            "status": "IMPORTABLE",
        },
        {
            "object_key": "images/b.jpg",
            "filename": "b.jpg",
            "storage_source_id": "source-a",
            "storage_type": "s3",
            "width": 120,
            "height": 90,
            "status": "IMPORTABLE",
        },
    ])
    store.manifest_many([
        {"object_key": "images/a.jpg", "split": "train", "yaml_key": "data.yaml"},
        {"object_key": "images/b.jpg", "split": "train", "yaml_key": "data.yaml"},
    ])
    store.set_label_mapping({3: "external-smoke"})
    store.annotation_batch(
        [
            {
                "object_key": "images/a.jpg",
                "label_key": "labels/a.txt",
                "annotation_status": "annotated",
                "box_count": 1,
            },
            {
                "object_key": "images/b.jpg",
                "label_key": "labels/b.txt",
                "annotation_status": "annotated",
                "box_count": 1,
            },
        ],
        [
            {
                "object_key": "images/a.jpg",
                "line_number": 1,
                "class_id": 3,
                "cx": 0.5,
                "cy": 0.5,
                "w": 0.4,
                "h": 0.2,
            },
            {
                "object_key": "images/b.jpg",
                "line_number": 1,
                "class_id": 3,
                "cx": 0.25,
                "cy": 0.25,
                "w": 0.2,
                "h": 0.2,
            },
        ],
        [],
    )
    return task_id


def test_label_review_samples_use_short_lived_provider_preview(client, seeded_project, tmp_path, monkeypatch):
    project_id, _image = seeded_project
    task_id = _seed_review(
        tmp_path, monkeypatch, project_id, provider=_PreviewProvider()
    )

    response = client.get(
        f"/api/v61/projects/{project_id}/label-review/{task_id}/classes/3/samples",
        params={"limit": 8},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 2
    assert [row["object_key"] for row in body["samples"]] == [
        "images/a.jpg", "images/b.jpg",
    ]
    assert body["samples"][0]["preview_url"].startswith(
        "https://preview.example.invalid/"
    )
    assert body["samples"][0]["bbox"] == {
        "cx": 0.5,
        "cy": 0.5,
        "w": 0.4,
        "h": 0.2,
        "clipped": False,
    }


def test_label_review_local_sample_proxy_is_class_fenced(client, seeded_project, tmp_path, monkeypatch):
    project_id, _image = seeded_project
    task_id = _seed_review(
        tmp_path, monkeypatch, project_id, provider=_LocalProvider()
    )

    listing = client.get(
        f"/api/v61/projects/{project_id}/label-review/{task_id}/classes/3/samples"
    ).json()
    content_url = listing["samples"][0]["content_url"]
    response = client.get(content_url)
    assert response.status_code == 200
    assert response.content == b"sample:images/a.jpg"

    denied = client.get(
        f"/api/v61/projects/{project_id}/label-review/{task_id}/classes/3/sample-content",
        params={"object_key": "images/not-in-class.jpg"},
    )
    assert denied.status_code == 404
