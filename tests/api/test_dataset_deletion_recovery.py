import io
import json
import threading
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
        json={"name": f"deletion-{uuid.uuid4().hex[:8]}", "labels": []},
    ).json()
    dataset = client.post(
        f"/api/projects/{project['id']}/datasets",
        json={"name": "target", "description": ""},
    ).json()
    return project["id"], dataset["id"]


def upload_response(client, project_id: str, dataset_id: str, filename: str):
    return client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (filename, png_bytes(), "image/png"))],
        data={"dataset_id": dataset_id},
    )


def upload_png(client, project_id: str, dataset_id: str, filename: str) -> dict:
    response = upload_response(client, project_id, dataset_id, filename)
    response.raise_for_status()
    return response.json()["uploaded"][0]


def journal_paths(app_module, project_id: str):
    return sorted(
        (
            app_module.project_dir(project_id)
            / "imports"
            / "dataset_deletions"
        ).glob("*.json")
    )


def dataset_exists(app_module, project_id: str, dataset_id: str) -> bool:
    return any(
        str(item.get("id")) == dataset_id
        for item in app_module.read_json(app_module.datasets_file(project_id), [])
    )


def assert_token_inactive(app_module, token: str):
    guard = app_module._V50_ACTIVE_DATASET_DELETIONS_GUARD
    with guard:
        assert token not in app_module._V50_ACTIVE_DATASET_DELETION_TOKENS


def test_active_deletion_rejects_target_writes_but_allows_other_dataset(
    client, monkeypatch
):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    target = upload_png(client, project_id, dataset_id, "target.png")
    reassign = upload_png(client, project_id, "default", "reassign.png")
    reached = threading.Event()
    resume = threading.Event()
    original_stage = app_module._v50_stage_material_file

    def paused_stage(source, destination):
        if threading.current_thread().name == "durable-delete" and not reached.is_set():
            reached.set()
            assert resume.wait(5), "dataset deletion did not resume"
        return original_stage(source, destination)

    monkeypatch.setattr(app_module, "_v50_stage_material_file", paused_stage)
    outcome = {}

    def run_delete():
        try:
            outcome["value"] = app_module.delete_dataset(project_id, dataset_id)
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=run_delete, name="durable-delete")
    thread.start()
    try:
        assert reached.wait(5), "deletion did not reach staging"
        blocked_upload = upload_response(
            client, project_id, dataset_id, "blocked.png"
        )
        blocked_patch = client.patch(
            f"/api/v12/projects/{project_id}/images/{reassign['id']}",
            json={"dataset_id": dataset_id},
        )
        unrelated = upload_png(
            client, project_id, "default", "unrelated.png"
        )
    finally:
        resume.set()
        thread.join(5)

    assert not thread.is_alive(), "dataset deletion thread did not terminate"
    assert outcome == {"value": {"ok": True}}
    assert blocked_upload.status_code == 200
    assert blocked_upload.json()["uploaded_count"] == 0
    assert blocked_upload.json()["failed_count"] == 1
    assert blocked_patch.status_code == 409
    rows = app_module.material_store(project_id).read().rows
    assert all(row.get("dataset_id", "default") != dataset_id for row in rows)
    row_ids = {str(row.get("id")) for row in rows}
    rows_by_id = {str(row.get("id")): row for row in rows}
    assert target["id"] not in row_ids
    assert reassign["id"] in row_ids
    assert rows_by_id[reassign["id"]].get("dataset_id", "default") == "default"
    assert unrelated["id"] in row_ids
    uploads = app_module.project_dir(project_id) / "uploads"
    assert {path.name for path in uploads.iterdir()} == {
        reassign["stored_name"],
        unrelated["stored_name"],
    }
    assert not journal_paths(app_module, project_id)


class FailAfterSecondMutation:
    def __init__(self, delegate, state):
        self._delegate = delegate
        self._state = state

    def mutate(self, fn):
        self._state["mutations"] += 1
        result = self._delegate.mutate(fn)
        if self._state["mutations"] == 2:
            raise RuntimeError("simulated finalize interruption")
        return result

    def __getattr__(self, name):
        return getattr(self._delegate, name)


def test_recovery_restores_rows_and_files_after_finalize_interruption(
    client, monkeypatch
):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    target = upload_png(client, project_id, dataset_id, "interrupted.png")
    project_path = app_module.project_dir(project_id)
    upload_path = project_path / "uploads" / target["stored_name"]
    annotation_path = project_path / "annotations" / f"{target['id']}.json"
    real_material_store = app_module.material_store
    state = {"mutations": 0}

    def failing_material_store(pid):
        delegate = real_material_store(pid)
        if pid == project_id:
            return FailAfterSecondMutation(delegate, state)
        return delegate

    monkeypatch.setattr(app_module, "material_store", failing_material_store)
    with pytest.raises(RuntimeError, match="simulated finalize interruption"):
        app_module.delete_dataset(project_id, dataset_id)
    monkeypatch.setattr(app_module, "material_store", real_material_store)

    journals = journal_paths(app_module, project_id)
    assert len(journals) == 1
    journal = json.loads(journals[0].read_text(encoding="utf-8"))
    assert_token_inactive(app_module, journal["token"])
    assert dataset_exists(app_module, project_id, dataset_id)
    assert target["id"] not in {
        str(row.get("id")) for row in real_material_store(project_id).read().rows
    }
    assert not upload_path.exists()
    assert not annotation_path.exists()

    app_module._v50_recover_dataset_deletions(project_id, dataset_id)

    rows = {str(row.get("id")): row for row in real_material_store(project_id).read().rows}
    assert rows[target["id"]]["stored_name"] == target["stored_name"]
    assert app_module._V50_DATASET_DELETE_CLAIM_FIELD not in rows[target["id"]]
    assert upload_path.exists()
    assert annotation_path.exists()
    assert not journal_paths(app_module, project_id)
    assert not Path(journal["staging_dir"]).exists()


def test_recovery_finishes_deletion_when_dataset_metadata_is_already_absent(
    client, monkeypatch
):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    target = upload_png(client, project_id, dataset_id, "finish.png")
    original_cleanup = app_module._v50_cleanup_dataset_delete_artifacts

    def interrupted_cleanup(_journal):
        raise RuntimeError("simulated cleanup interruption")

    monkeypatch.setattr(
        app_module, "_v50_cleanup_dataset_delete_artifacts", interrupted_cleanup
    )
    with pytest.raises(RuntimeError, match="simulated cleanup interruption"):
        app_module.delete_dataset(project_id, dataset_id)
    monkeypatch.setattr(
        app_module, "_v50_cleanup_dataset_delete_artifacts", original_cleanup
    )

    journals = journal_paths(app_module, project_id)
    assert len(journals) == 1
    journal = json.loads(journals[0].read_text(encoding="utf-8"))
    assert journal["status"] == "metadata_removed"
    assert_token_inactive(app_module, journal["token"])
    assert not dataset_exists(app_module, project_id, dataset_id)
    assert target["id"] not in {
        str(row.get("id"))
        for row in app_module.material_store(project_id).read().rows
    }
    assert Path(journal["staging_dir"]).exists()
    claimed_again = dict(target)
    claimed_again[app_module._V50_DATASET_DELETE_CLAIM_FIELD] = journal["token"]
    app_module.material_store(project_id).upsert(claimed_again)

    app_module._v50_recover_dataset_deletions(project_id, dataset_id)

    assert not journal_paths(app_module, project_id)
    assert not Path(journal["staging_dir"]).exists()
    assert target["id"] not in {
        str(row.get("id"))
        for row in app_module.material_store(project_id).read().rows
    }
