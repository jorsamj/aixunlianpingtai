import io
import json
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


def test_retired_dataset_delete_preserves_target_and_unrelated_sqlite_annotations(client):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    target = upload_png(client, project_id, dataset_id, "target.png", "red")
    unrelated = upload_png(client, project_id, "default", "unrelated.png", "blue")
    annotate(app_module, project_id, target["id"])
    annotate(app_module, project_id, unrelated["id"])

    repository = app_module.AnnotationRepository(app_module.project_dir(project_id))
    assert repository.exists(target["id"])
    assert repository.exists(unrelated["id"])

    response = client.delete(f"/api/projects/{project_id}/datasets/{dataset_id}")
    assert response.status_code == 409, response.text
    assert json.loads(response.json()["detail"])["code"] == "MATERIAL_DELETE_PREVIEW_REQUIRED"

    assert repository.exists(target["id"])
    assert repository.exists(unrelated["id"])
    assert repository.get(unrelated["id"])["annotation_state"] == "annotated"
    assert all(
        str(row.get("id")) in {target["id"], unrelated["id"]}
        for row in app_module.material_store(project_id).read().rows
    )


def test_dataset_delete_journal_has_durable_sqlite_annotation_backup(client, monkeypatch):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    target = upload_png(client, project_id, dataset_id, "journal.png", "green")
    annotate(app_module, project_id, target["id"])
    repository = app_module.AnnotationRepository(app_module.project_dir(project_id))

    before = repository.get(target['id'])
    journal = historical_journal(app_module, project_id, dataset_id, target)
    token = journal['token']
    assert repository.delete_backup_count(token) == 1
    repository.finalize_delete(token)
    assert not repository.exists(target['id'])
    with pytest.raises(app_module.HTTPException, match='STAGED_BYTES_RETAINED'):
        app_module._v50_cleanup_dataset_delete_artifacts(journal)
    assert repository.delete_backup_count(token) == 1
    app_module._v50_recover_dataset_deletions(project_id, dataset_id)
    assert repository.get(target['id'])['content_digest'] == before['content_digest']
    assert repository.delete_backup_count(token) == 0


def test_dataset_delete_recovery_restores_sqlite_annotation_after_metadata_failure(
    client, monkeypatch
):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    target = upload_png(client, project_id, dataset_id, "recover.png", "purple")
    annotate(app_module, project_id, target["id"])
    repository = app_module.AnnotationRepository(app_module.project_dir(project_id))
    before = repository.get(target["id"])

    journal = historical_journal(app_module, project_id, dataset_id, target)
    token = journal['token']
    repository.finalize_delete(token)
    app_module.material_store(project_id).remove([target['id']])
    assert repository.delete_backup_count(token) == 1
    assert not repository.exists(target['id'])

    recovered = app_module._v50_recover_dataset_deletions(project_id, dataset_id)
    assert recovered

    rows = {str(row.get("id")): row for row in app_module.material_store(project_id).read().rows}
    assert target["id"] in rows
    after = repository.get(target["id"])
    assert after["annotation_state"] == before["annotation_state"]
    assert after["content_digest"] == before["content_digest"]
    assert after["boxes"] == before["boxes"]
    assert repository.delete_backup_count(token) == 0
    assert not list(
        (app_module.project_dir(project_id) / "imports" / "dataset_deletions").glob("*.json")
    )


def historical_journal(app_module, pid, did, target):
    token = uuid.uuid4().hex
    journal = {'token': token, 'project_id': pid, 'dataset_id': did,
        'created_at': app_module.now_iso(), 'updated_at': app_module.now_iso(), 'status': 'staged',
        'staging_dir': str(app_module._v50_dataset_delete_staging_dir(pid, token)),
        'claimed_rows': [dict(target)], 'claimed_positions': {target['id']: 0}}
    journal['files'] = app_module._v50_dataset_delete_file_entries(pid, journal)
    repository = app_module.AnnotationRepository(app_module.project_dir(pid))
    repository.prepare_delete(token, [target['id']])
    app_module.material_store(pid).patch({target['id']: {app_module._V50_DATASET_DELETE_CLAIM_FIELD: token}})
    for item in journal['files']:
        if item.get('existed'):
            app_module._v50_stage_material_file(Path(item['source']), Path(item['staged']))
    app_module._v50_write_dataset_delete_journal(journal)
    return journal
