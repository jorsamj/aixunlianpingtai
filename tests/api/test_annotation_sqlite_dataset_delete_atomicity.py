import io
import uuid
from pathlib import Path

import pytest
from PIL import Image


def png_bytes(color: str = "white") -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 64), color).save(output, format="PNG")
    return output.getvalue()


def create_project_with_dataset(client):
    project = client.post(
        "/api/projects",
        json={"name": f"annotation-delete-{uuid.uuid4().hex[:8]}", "labels": ["target"]},
    ).json()
    dataset = client.post(
        f"/api/projects/{project['id']}/datasets",
        json={"name": "target", "description": ""},
    ).json()
    return project["id"], dataset["id"]


def upload_png(client, project_id: str, dataset_id: str, filename: str, color: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (filename, png_bytes(color), "image/png"))],
        data={"dataset_id": dataset_id},
    )
    response.raise_for_status()
    return response.json()["uploaded"][0]


def annotate(app_module, project_id: str, image_id: str):
    app_module.write_annotation(
        project_id,
        image_id,
        [{
            "class_id": 0,
            "label": "target",
            "x1": 2,
            "y1": 2,
            "x2": 30,
            "y2": 30,
        }],
    )


def test_dataset_delete_removes_only_target_sqlite_annotations(client):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    target = upload_png(client, project_id, dataset_id, "target.png", "red")
    unrelated = upload_png(client, project_id, "default", "unrelated.png", "blue")
    annotate(app_module, project_id, target["id"])
    annotate(app_module, project_id, unrelated["id"])

    repository = app_module.AnnotationRepository(app_module.project_dir(project_id))
    assert len(repository.snapshot_rows([target["id"], unrelated["id"]])) == 2

    response = client.delete(f"/api/projects/{project_id}/datasets/{dataset_id}")
    assert response.status_code == 200, response.text

    assert repository.snapshot_rows([target["id"]]) == []
    unrelated_rows = repository.snapshot_rows([unrelated["id"]])
    assert len(unrelated_rows) == 1
    assert unrelated_rows[0]["annotation_state"] == "annotated"
    assert all(
        str(row.get("id")) != target["id"]
        for row in app_module.material_store(project_id).read().rows
    )


def test_dataset_delete_journal_snapshots_sqlite_annotation_truth(client, monkeypatch):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    target = upload_png(client, project_id, dataset_id, "journal.png", "green")
    annotate(app_module, project_id, target["id"])
    before = app_module.AnnotationRepository(app_module.project_dir(project_id)).get(target["id"])

    original_stage = app_module._v50_stage_material_file
    observed = {}

    def inspect_first_stage(source, destination):
        if not observed:
            journals = list(
                (app_module.project_dir(project_id) / "imports" / "dataset_deletions").glob("*.json")
            )
            assert len(journals) == 1
            journal = app_module.read_json(journals[0], {})
            rows = journal.get("annotation_rows") or []
            observed["rows"] = rows
        return original_stage(source, destination)

    monkeypatch.setattr(app_module, "_v50_stage_material_file", inspect_first_stage)
    response = client.delete(f"/api/projects/{project_id}/datasets/{dataset_id}")
    assert response.status_code == 200, response.text

    assert len(observed.get("rows") or []) == 1
    snapshot = observed["rows"][0]
    assert snapshot["image_id"] == target["id"]
    assert snapshot["annotation_state"] == "annotated"
    assert snapshot["content_digest"] == before["content_digest"]


def test_dataset_delete_recovery_restores_sqlite_annotation_after_metadata_failure(
    client, monkeypatch
):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    target = upload_png(client, project_id, dataset_id, "recover.png", "purple")
    annotate(app_module, project_id, target["id"])
    repository = app_module.AnnotationRepository(app_module.project_dir(project_id))
    before = repository.get(target["id"])

    original_atomic_write = app_module.atomic_write_json
    metadata_path = app_module.datasets_file(project_id).resolve()
    failed = {"value": False}

    def fail_metadata_once(path, value):
        if Path(path).resolve() == metadata_path and not failed["value"]:
            current = app_module.read_json(app_module.datasets_file(project_id), [])
            current_ids = {str(item.get("id")) for item in current if isinstance(item, dict)}
            next_ids = {str(item.get("id")) for item in value if isinstance(item, dict)} if isinstance(value, list) else current_ids
            if dataset_id in current_ids and dataset_id not in next_ids:
                failed["value"] = True
                raise OSError("simulated dataset metadata write failure")
        return original_atomic_write(path, value)

    monkeypatch.setattr(app_module, "atomic_write_json", fail_metadata_once)
    with pytest.raises(OSError, match="simulated dataset metadata write failure"):
        app_module.delete_dataset(project_id, dataset_id)
    monkeypatch.setattr(app_module, "atomic_write_json", original_atomic_write)

    assert failed["value"] is True
    journals = list(
        (app_module.project_dir(project_id) / "imports" / "dataset_deletions").glob("*.json")
    )
    assert len(journals) == 1

    recovered = app_module._v50_recover_dataset_deletions(project_id, dataset_id)
    assert recovered

    rows = {str(row.get("id")): row for row in app_module.material_store(project_id).read().rows}
    assert target["id"] in rows
    after = repository.get(target["id"])
    assert after["annotation_state"] == before["annotation_state"]
    assert after["content_digest"] == before["content_digest"]
    assert after["boxes"] == before["boxes"]
    assert not list(
        (app_module.project_dir(project_id) / "imports" / "dataset_deletions").glob("*.json")
    )
