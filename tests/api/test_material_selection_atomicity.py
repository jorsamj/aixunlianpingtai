import io
import json
import threading
import uuid

import pytest
from PIL import Image


def png_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (64, 64), "white").save(output, format="PNG")
    return output.getvalue()


def create_project_with_dataset(client):
    project = client.post(
        "/api/projects",
        json={"name": f"atomic-{uuid.uuid4().hex[:8]}", "labels": []},
    ).json()
    dataset = client.post(
        f"/api/projects/{project['id']}/datasets",
        json={"name": "target", "description": ""},
    ).json()
    return project["id"], dataset["id"]


def upload_png(client, project_id: str, dataset_id: str, filename: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (filename, png_bytes(), "image/png"))],
        data={"dataset_id": dataset_id},
    )
    response.raise_for_status()
    return response.json()["uploaded"][0]


class PausedCommitStore:
    def __init__(self, delegate, reached: threading.Event, resume: threading.Event):
        self._delegate = delegate
        self._reached = reached
        self._resume = resume

    def _pause(self):
        self._reached.set()
        assert self._resume.wait(5), "material mutation did not resume"

    def mutate(self, fn):
        self._pause()
        return self._delegate.mutate(fn)

    def patch(self, patches):
        self._pause()
        return self._delegate.patch(patches)

    def remove(self, image_ids):
        self._pause()
        return self._delegate.remove(image_ids)

    def __getattr__(self, name):
        return getattr(self._delegate, name)


def run_with_paused_commit(monkeypatch, app_module, project_id: str, invoke, change):
    real_material_store = app_module.material_store
    reached = threading.Event()
    resume = threading.Event()
    worker_name = f"material-selection-{uuid.uuid4().hex}"

    def wrapped_material_store(pid):
        delegate = real_material_store(pid)
        if pid == project_id and threading.current_thread().name == worker_name:
            return PausedCommitStore(delegate, reached, resume)
        return delegate

    monkeypatch.setattr(app_module, "material_store", wrapped_material_store)
    outcome = {}

    def target():
        try:
            outcome["value"] = invoke()
        except BaseException as error:  # make endpoint-thread failures observable
            outcome["error"] = error

    thread = threading.Thread(target=target, name=worker_name)
    thread.start()
    try:
        assert reached.wait(5), "endpoint did not reach its material commit"
        change(real_material_store(project_id))
    finally:
        resume.set()
        thread.join(5)

    assert not thread.is_alive(), "endpoint thread did not terminate"
    if "error" in outcome:
        raise outcome["error"]
    return outcome["value"], real_material_store(project_id)


def test_delete_dataset_selects_latest_rows_inside_atomic_mutation(client, monkeypatch):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    first = upload_png(client, project_id, dataset_id, "first.png")
    reassigned = upload_png(client, project_id, "default", "reassigned.png")

    result, store = run_with_paused_commit(
        monkeypatch,
        app_module,
        project_id,
        lambda: app_module.delete_dataset(project_id, dataset_id),
        lambda real_store: real_store.patch(
            {reassigned["id"]: {"dataset_id": dataset_id}}
        ),
    )

    assert result == {"ok": True}
    assert {row["id"] for row in store.read().rows}.isdisjoint(
        {first["id"], reassigned["id"]}
    )
    uploads = app_module.project_dir(project_id) / "uploads"
    assert not (uploads / first["stored_name"]).exists()
    assert not (uploads / reassigned["stored_name"]).exists()


def test_delete_dataset_file_lock_failure_keeps_dataset_and_material(
    client, monkeypatch
):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    locked = upload_png(client, project_id, dataset_id, "locked.png")
    unrelated = upload_png(client, project_id, "default", "unrelated.png")
    store = app_module.material_store(project_id)
    unrelated_before = next(
        dict(row) for row in store.read().rows if row["id"] == unrelated["id"]
    )
    original_stage = getattr(
        app_module,
        "_v50_stage_material_file",
        lambda source, destination: source.replace(destination),
    )

    def fail_locked_file(source, destination):
        if source.name == f"{locked['id']}.json":
            raise PermissionError("simulated Windows file lock")
        return original_stage(source, destination)

    monkeypatch.setattr(
        app_module, "_v50_stage_material_file", fail_locked_file, raising=False
    )
    response = client.delete(f"/api/projects/{project_id}/datasets/{dataset_id}")

    assert response.status_code == 409
    detail = json.loads(response.json()["detail"])
    assert detail["failed_items"][0]["id"] == locked["id"]
    assert any(
        dataset["id"] == dataset_id
        for dataset in app_module.read_json(app_module.datasets_file(project_id), [])
    )
    rows = {row["id"]: row for row in store.read().rows}
    assert rows[locked["id"]]["filename"] == locked["filename"]
    assert rows[unrelated["id"]] == unrelated_before
    claim_field = getattr(
        app_module, "_V50_DATASET_DELETE_CLAIM_FIELD", "_dataset_delete_claim"
    )
    assert all(claim_field not in row for row in rows.values())
    assert (
        app_module.project_dir(project_id) / "uploads" / locked["stored_name"]
    ).exists()
    assert (
        app_module.project_dir(project_id) / "annotations" / f"{locked['id']}.json"
    ).exists()
    assert not list(
        (app_module.project_dir(project_id) / "imports").glob("dataset_delete_*")
    )
    assert not list(
        (
            app_module.project_dir(project_id)
            / "imports"
            / "dataset_deletions"
        ).glob("*.json")
    )


@pytest.mark.parametrize(
    ("scope", "filter_name"),
    [
        ("dataset", "all"),
        ("filtered", "unassigned"),
        ("filtered", "unmarked"),
    ],
)
def test_batch_split_rechecks_latest_dataset_membership(
    client, monkeypatch, scope, filter_name
):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    first = upload_png(client, project_id, dataset_id, "first.png")
    reassigned = upload_png(client, project_id, "default", "reassigned.png")
    payload = app_module.BatchImageSplitReq(
        image_ids=[],
        split="train",
        dataset_id=dataset_id,
        filter=filter_name,
        scope=scope,
    )

    result, store = run_with_paused_commit(
        monkeypatch,
        app_module,
        project_id,
        lambda: app_module.v20_batch_image_split(project_id, payload),
        lambda real_store: real_store.patch(
            {reassigned["id"]: {"dataset_id": dataset_id}}
        ),
    )

    rows = {row["id"]: row for row in store.read().rows}
    assert result == {"ok": True, "changed": 2, "split": "train"}
    assert rows[first["id"]]["split"] == "train"
    assert rows[reassigned["id"]]["split"] == "train"


@pytest.mark.parametrize("include_unannotated", [True, False])
def test_auto_split_rechecks_latest_membership_and_sorts_by_id(
    client, monkeypatch, include_unannotated
):
    import app as app_module

    project_id, dataset_id = create_project_with_dataset(client)
    first = upload_png(client, project_id, dataset_id, "first.png")
    reassigned = upload_png(client, project_id, "default", "reassigned.png")
    if not include_unannotated:
        box = {"class_id": 0, "label": "target", "x1": 1, "y1": 1, "x2": 20, "y2": 20}
        app_module.write_annotation(project_id, first["id"], [box])
        app_module.write_annotation(project_id, reassigned["id"], [box])
    payload = app_module.BatchSplitReq(
        train=0.5,
        val=0,
        test=0.5,
        include_unannotated=include_unannotated,
    )

    result, store = run_with_paused_commit(
        monkeypatch,
        app_module,
        project_id,
        lambda: app_module.v12_auto_split(project_id, dataset_id, payload),
        lambda real_store: real_store.patch(
            {reassigned["id"]: {"dataset_id": dataset_id}}
        ),
    )

    rows = {row["id"]: row for row in store.read().rows}
    ordered_ids = sorted([first["id"], reassigned["id"]])
    assert result == {"ok": True, "counts": {"train": 1, "val": 0, "test": 1}}
    assert rows[ordered_ids[0]]["split"] == "train"
    assert rows[ordered_ids[1]]["split"] == "test"
