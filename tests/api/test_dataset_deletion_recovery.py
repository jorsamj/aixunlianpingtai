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


def create_dataset(client, project_id: str, name: str) -> str:
    response = client.post(
        f"/api/projects/{project_id}/datasets",
        json={"name": name, "description": ""},
    )
    response.raise_for_status()
    return response.json()["id"]


def write_recovery_journal(app_module, project_id: str, dataset_id: str, row: dict):
    token = uuid.uuid4().hex
    staging_dir = app_module._v50_dataset_delete_staging_dir(project_id, token)
    image_id = str(row["id"])
    row_dir = staging_dir / app_module.safe_filename(image_id)
    stored_name = str(row.get("stored_name") or "")
    entries = []
    if stored_name:
        entries.append(
            {
                "image_id": image_id,
                "kind": "image",
                "source": str(
                    app_module.project_dir(project_id) / "uploads" / stored_name
                ),
                "staged": str(row_dir / f"image{Path(stored_name).suffix}"),
                "existed": True,
            }
        )
    entries.append(
        {
            "image_id": image_id,
            "kind": "annotation",
            "source": str(
                app_module.project_dir(project_id)
                / "annotations"
                / f"{image_id}.json"
            ),
            "staged": str(row_dir / "annotation.json"),
            "existed": True,
        }
    )
    journal = {
        "token": token,
        "project_id": project_id,
        "dataset_id": dataset_id,
        "created_at": app_module.now_iso(),
        "updated_at": app_module.now_iso(),
        "status": "claimed",
        "staging_dir": str(staging_dir),
        "claimed_rows": [dict(row)],
        "claimed_positions": {image_id: 0},
        "files": entries,
    }
    app_module.atomic_write_json(
        app_module._v50_dataset_delete_journal_path(project_id, token), journal
    )
    return journal


def test_other_dataset_add_does_not_wait_for_project_import_lock(
    client, tmp_path
):
    import app as app_module

    project_id, _ = create_project_with_dataset(client)
    other_dataset_id = create_dataset(client, project_id, "other")
    source = tmp_path / "other.png"
    Image.new("RGB", (64, 64), "blue").save(source, format="PNG")
    held = threading.Event()
    release = threading.Event()
    completed = threading.Event()
    outcome = {}

    def hold_import_lock():
        with app_module._v50_project_import_lock(project_id):
            held.set()
            assert release.wait(5), "project import lock was not released"

    def add_other_dataset_image():
        try:
            outcome["record"] = app_module.add_image_record(
                project_id, source, "other.png", "raw", other_dataset_id
            )
        except BaseException as error:
            outcome["error"] = error
        finally:
            completed.set()

    holder = threading.Thread(target=hold_import_lock, name="long-v19-import")
    worker = threading.Thread(target=add_other_dataset_image, name="other-upload")
    holder.start()
    assert held.wait(5)
    worker.start()
    try:
        completed_while_held = completed.wait(2)
    finally:
        release.set()
        holder.join(5)
        worker.join(5)

    assert completed_while_held, "unrelated dataset add waited for v19 project lock"
    assert not holder.is_alive()
    assert not worker.is_alive()
    assert "error" not in outcome
    assert outcome["record"]["dataset_id"] == other_dataset_id


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


def test_active_source_dataset_deletion_rejects_reassignment_out(
    client, monkeypatch
):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    other_dataset_id = create_dataset(client, project_id, "other")
    target = upload_png(client, project_id, dataset_id, "source.png")
    reached = threading.Event()
    resume = threading.Event()
    original_stage = app_module._v50_stage_material_file

    def paused_stage(source, destination):
        if threading.current_thread().name == "source-delete" and not reached.is_set():
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

    thread = threading.Thread(target=run_delete, name="source-delete")
    thread.start()
    try:
        assert reached.wait(5), "deletion did not reach staging"
        response = client.patch(
            f"/api/v12/projects/{project_id}/images/{target['id']}",
            json={"dataset_id": other_dataset_id},
        )
    finally:
        resume.set()
        thread.join(5)

    assert not thread.is_alive()
    assert response.status_code == 409
    assert outcome == {"value": {"ok": True}}
    assert target["id"] not in {
        str(row.get("id"))
        for row in app_module.material_store(project_id).read().rows
    }


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


def test_recovery_rejects_traversal_image_id_without_touching_evidence(client):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    target = upload_png(client, project_id, dataset_id, "safe.png")
    malicious = dict(target)
    malicious["id"] = "../outside"
    journal = write_recovery_journal(
        app_module, project_id, dataset_id, malicious
    )
    staging_annotation = Path(journal["files"][-1]["staged"])
    staging_annotation.parent.mkdir(parents=True, exist_ok=True)
    staging_annotation.write_text("staged annotation", encoding="utf-8")
    outside_sentinel = app_module.project_dir(project_id) / "outside.json"
    outside_sentinel.write_text("outside sentinel", encoding="utf-8")

    with pytest.raises(app_module.HTTPException) as raised:
        app_module._v50_recover_dataset_deletions(project_id, dataset_id)

    assert raised.value.status_code == 409
    assert outside_sentinel.read_text(encoding="utf-8") == "outside sentinel"
    assert staging_annotation.read_text(encoding="utf-8") == "staged annotation"
    assert app_module._v50_dataset_delete_journal_path(
        project_id, journal["token"]
    ).exists()
    assert all(
        str(row.get("id")) != "../outside"
        for row in app_module.material_store(project_id).read().rows
    )


def test_malformed_dataset_metadata_preserves_claimed_row_and_staging(client):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    target = upload_png(client, project_id, dataset_id, "malformed.png")
    original = dict(target)
    journal = write_recovery_journal(
        app_module, project_id, dataset_id, original
    )
    token = journal["token"]
    claim_field = app_module._V50_DATASET_DELETE_CLAIM_FIELD
    app_module.material_store(project_id).patch(
        {target["id"]: {claim_field: token}}
    )
    for item in journal["files"]:
        source = Path(item["source"])
        staged = Path(item["staged"])
        if source.exists():
            app_module._v50_stage_material_file(source, staged)
    app_module.datasets_file(project_id).write_text("{malformed", encoding="utf-8")

    with pytest.raises(app_module.HTTPException) as raised:
        app_module._v50_recover_dataset_deletions(project_id, dataset_id)

    assert raised.value.status_code == 409
    rows = {
        str(row.get("id")): row
        for row in app_module.material_store(project_id).read().rows
    }
    assert rows[target["id"]][claim_field] == token
    assert all(Path(item["staged"]).exists() for item in journal["files"])
    assert app_module._v50_dataset_delete_journal_path(project_id, token).exists()
