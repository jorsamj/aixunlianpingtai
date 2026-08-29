import io
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from PIL import Image, ImageDraw


def image_bytes(kind: str) -> bytes:
    image = Image.new("RGB", (400, 300), "gray")
    if kind == "checker":
        draw = ImageDraw.Draw(image)
        for x in range(0, 400, 20):
            for y in range(0, 300, 20):
                fill = "white" if (x // 20 + y // 20) % 2 == 0 else "black"
                draw.rectangle((x, y, x + 19, y + 19), fill=fill)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def wait_for_clean_result(client, pid: str, task_id: str, timeout: float = 15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v47/projects/{pid}/clean-tasks/{task_id}/result")
        response.raise_for_status()
        body = response.json()
        status = body["task"].get("status")
        if status == "awaiting_confirmation":
            return body
        if status == "failed":
            raise AssertionError(body["task"])
        time.sleep(0.05)
    raise AssertionError(f"clean task {task_id} timed out")


def upload_png(client, project_id: str, filename: str) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/images",
        files=[("files", (filename, image_bytes("checker"), "image/png"))],
        data={"dataset_id": "default"},
    )
    response.raise_for_status()
    return response.json()["uploaded"][0]


def upload_many_png(client, project_id: str, names: list[str]) -> dict:
    response = client.post(
        f"/api/projects/{project_id}/images",
        files=[
            ("files", (name, image_bytes("checker"), "image/png"))
            for name in names
        ],
        data={"dataset_id": "default"},
    )
    response.raise_for_status()
    return response.json()


def seed_published_clean_intent(app_module, pid, batch_id, image_id, task_id):
    store = app_module.upload_batch_store(pid)
    with store.locked(batch_id):
        batch = store._read_unlocked(batch_id)
        batch["items"][0]["decision"] = "clean"
        batch["clean_task_id"] = task_id
        batch["clean_task_image_ids"] = [image_id]
        store._write_unlocked(batch_id, batch)
    app_module.material_store(pid).patch(
        {
            image_id: {
                "processing_status": "cleaning",
                "clean_skipped": False,
                "clean_decision": "clean",
                "clean_decision_at": "2026-08-29 10:00:00",
                "updated_at": "2026-08-29 10:00:00",
            }
        }
    )


def test_upload_batch_survives_reload_and_tracks_mixed_decisions(client):
    pid = client.post(
        "/api/projects",
        json={"name": "mixed-batch", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(
        client,
        pid,
        ["clean.png", "ready.png", "later.png"],
    )
    batch_id = uploaded["batch_id"]

    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions",
        json={
            "clean_image_ids": [uploaded["uploaded"][0]["id"]],
            "ready_image_ids": [uploaded["uploaded"][1]["id"]],
        },
    )
    response.raise_for_status()
    clean_task_id = response.json()["clean_task_id"]
    assert clean_task_id

    repeated = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions",
        json={
            "clean_image_ids": [uploaded["uploaded"][0]["id"]],
            "ready_image_ids": [uploaded["uploaded"][1]["id"]],
        },
    )
    repeated.raise_for_status()
    assert repeated.json()["clean_task_id"] == clean_task_id

    batch = client.get(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}"
    ).json()
    assert [item["decision"] for item in batch["items"]] == [
        "clean",
        "ready",
        "pending",
    ]
    rows = {
        row["id"]: row
        for row in client.get(f"/api/projects/{pid}/images").json()
    }
    assert rows[uploaded["uploaded"][0]["id"]]["processing_status"] == "cleaning"
    assert rows[uploaded["uploaded"][1]["id"]]["processing_status"] == "processed"
    assert rows[uploaded["uploaded"][1]["id"]]["clean_decision"] == "skipped"
    assert rows[uploaded["uploaded"][2]["id"]]["processing_status"] == "pending_decision"

    tasks = client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]
    assert [task["id"] for task in tasks].count(clean_task_id) == 1

    import app as app_module
    from fastapi.testclient import TestClient

    batch_path = app_module.project_dir(pid) / "upload_batches" / f"{batch_id}.json"
    assert batch_path.exists()
    with TestClient(app_module.app) as reloaded_client:
        reloaded = reloaded_client.get(
            f"/api/v55/projects/{pid}/upload-batches/{batch_id}"
        )
        reloaded.raise_for_status()
    assert [item["decision"] for item in reloaded.json()["items"]] == [
        "clean",
        "ready",
        "pending",
    ]


def test_retry_after_prepared_task_before_batch_publication_completes_once(client):
    import app as app_module

    pid = client.post(
        "/api/projects",
        json={"name": "prepared-before-publish", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    task_id = app_module._v55_upload_clean_task_id(
        pid,
        uploaded["batch_id"],
        [image_id],
    )
    task, created = app_module._v47_prepare_clean_task_record(
        pid,
        app_module.V47CleanReq(
            image_ids=[image_id],
            task_name=f"上传批次 {uploaded['batch_id']} 清洗",
        ),
        task_id=task_id,
    )
    assert created is True
    assert task["status"] == "prepared"

    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    response.raise_for_status()

    assert response.json()["clean_task_id"] == task_id
    tasks = client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]
    assert [item["id"] for item in tasks].count(task_id) == 1


def test_retry_recreates_missing_task_from_published_batch_association(client):
    import app as app_module

    pid = client.post(
        "/api/projects",
        json={"name": "repair-missing-task", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    task_id = "a1b2c3d4e5f6"
    seed_published_clean_intent(
        app_module,
        pid,
        uploaded["batch_id"],
        image_id,
        task_id,
    )
    assert client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"] == []

    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    response.raise_for_status()

    assert response.json()["clean_task_id"] == task_id
    tasks = client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]
    assert [item["id"] for item in tasks] == [task_id]
    assert tasks[0]["status"] != "prepared"


def test_retry_starts_existing_prepared_task_exactly_once(client, monkeypatch):
    import app as app_module

    pid = client.post(
        "/api/projects",
        json={"name": "start-prepared-on-retry", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    task_id = "b1c2d3e4f5a6"
    payload = app_module.V47CleanReq(
        image_ids=[image_id],
        task_name=f"上传批次 {uploaded['batch_id']} 清洗",
    )
    app_module._v47_prepare_clean_task_record(pid, payload, task_id=task_id)
    seed_published_clean_intent(
        app_module,
        pid,
        uploaded["batch_id"],
        image_id,
        task_id,
    )
    started = threading.Event()
    release = threading.Event()
    calls = []

    def blocking_worker(project_id, started_task_id, data):
        calls.append((project_id, started_task_id))
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(app_module, "_v47_run_clean_task", blocking_worker)
    try:
        first = client.post(
            f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
            json={"clean_image_ids": [image_id], "ready_image_ids": []},
        )
        first.raise_for_status()
        assert started.wait(5)
        second = client.post(
            f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
            json={"clean_image_ids": [image_id], "ready_image_ids": []},
        )
        second.raise_for_status()
        assert first.json()["clean_task_id"] == second.json()["clean_task_id"] == task_id
        assert calls == [(pid, task_id)]
    finally:
        release.set()


def test_concurrent_identical_decisions_spawn_one_task_worker(client, monkeypatch):
    import app as app_module

    pid = client.post(
        "/api/projects",
        json={"name": "concurrent-clean-retry", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    started = threading.Event()
    release = threading.Event()
    calls = []

    def blocking_worker(project_id, task_id, data):
        calls.append((project_id, task_id))
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(app_module, "_v47_run_clean_task", blocking_worker)
    url = f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions"
    body = {"clean_image_ids": [image_id], "ready_image_ids": []}
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses = list(executor.map(lambda _: client.post(url, json=body), range(2)))
        for response in responses:
            response.raise_for_status()
        assert started.wait(5)
        assert len({response.json()["clean_task_id"] for response in responses}) == 1
        assert len(calls) == 1
        assert len(client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]) == 1
    finally:
        release.set()


def test_upload_batch_rejects_overlap_without_changing_state(client):
    pid = client.post(
        "/api/projects",
        json={"name": "overlap-batch", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["only.png"])
    image_id = uploaded["uploaded"][0]["id"]
    batch_id = uploaded["batch_id"]

    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": [image_id]},
    )

    assert response.status_code == 400
    batch = client.get(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}"
    ).json()
    assert batch["items"][0]["decision"] == "pending"
    rows = client.get(f"/api/projects/{pid}/images").json()
    assert rows[0]["processing_status"] == "pending_decision"
    assert client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"] == []


def test_upload_batch_rejects_image_from_another_batch(client):
    pid = client.post(
        "/api/projects",
        json={"name": "foreign-image-batch", "labels": []},
    ).json()["id"]
    first = upload_many_png(client, pid, ["first.png"])
    second = upload_many_png(client, pid, ["second.png"])
    foreign_id = second["uploaded"][0]["id"]

    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{first['batch_id']}/decisions",
        json={"clean_image_ids": [], "ready_image_ids": [foreign_id]},
    )

    assert response.status_code == 400
    rows = {
        row["id"]: row
        for row in client.get(f"/api/projects/{pid}/images").json()
    }
    assert rows[foreign_id]["processing_status"] == "pending_decision"


def _set_clean_task_status(app_module, project_id: str, task_id: str, status: str):
    task_path = app_module._v33_tasks_file(project_id, "clean_tasks")
    tasks = app_module.read_json(task_path, [])
    for task in tasks:
        if str(task.get("id")) == str(task_id):
            task.update({"status": status, "status_text": status})
            app_module.write_json(task_path, tasks)
            return
    raise AssertionError(f"task {task_id} not found")


def test_replaying_clean_after_terminal_task_preserves_material_state(client):
    import app as app_module

    pid = client.post(
        "/api/projects", json={"name": "terminal-replay", "labels": []}
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png", "ready.png"])
    image_id = uploaded["uploaded"][0]["id"]
    batch_id = uploaded["batch_id"]
    task_id = app_module._v55_upload_clean_task_id(pid, batch_id, [image_id])
    app_module._v47_prepare_clean_task_record(
        pid,
        app_module.V47CleanReq(
            image_ids=[image_id], task_name=f"上传批次 {batch_id} 清洗"
        ),
        task_id=task_id,
    )
    seed_published_clean_intent(app_module, pid, batch_id, image_id, task_id)
    app_module.material_store(pid).patch(
        {
            image_id: {
                "processing_status": "processed",
                "cleaned_at": "sentinel-cleaned",
                "updated_at": "sentinel-updated",
            }
        }
    )
    _set_clean_task_status(app_module, pid, task_id, "done")

    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    response.raise_for_status()
    row = {item["id"]: item for item in client.get(f"/api/projects/{pid}/images").json()}[
        image_id
    ]
    assert row["processing_status"] == "processed"
    assert row["cleaned_at"] == "sentinel-cleaned"
    assert row["updated_at"] == "sentinel-updated"
    assert len(client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]) == 1


def test_failed_clean_task_can_be_retried_with_same_task_id(client, monkeypatch):
    import app as app_module

    pid = client.post(
        "/api/projects", json={"name": "failed-retry", "labels": []}
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    batch_id = uploaded["batch_id"]
    task_id = app_module._v55_upload_clean_task_id(pid, batch_id, [image_id])
    app_module._v47_prepare_clean_task_record(
        pid,
        app_module.V47CleanReq(
            image_ids=[image_id], task_name=f"上传批次 {batch_id} 清洗"
        ),
        task_id=task_id,
    )
    seed_published_clean_intent(app_module, pid, batch_id, image_id, task_id)
    _set_clean_task_status(app_module, pid, task_id, "failed")
    started = threading.Event()
    release = threading.Event()

    def blocking_worker(project_id, started_task_id, data):
        assert started_task_id == task_id
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(app_module, "_v47_run_clean_task", blocking_worker)
    try:
        response = client.post(
            f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions",
            json={"clean_image_ids": [image_id], "ready_image_ids": []},
        )
        response.raise_for_status()
        assert started.wait(5)
        tasks = client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]
        assert [item["id"] for item in tasks].count(task_id) == 1
    finally:
        release.set()


def test_running_clean_task_is_recovered_when_worker_registry_is_empty(client, monkeypatch):
    import app as app_module

    pid = client.post(
        "/api/projects", json={"name": "running-recovery", "labels": []}
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    task_id = "c1d2e3f4a5b6"
    payload = app_module.V47CleanReq(image_ids=[image_id], task_name="恢复清洗")
    app_module._v47_prepare_clean_task_record(pid, payload, task_id=task_id)
    _set_clean_task_status(app_module, pid, task_id, "running")
    app_module._V47_ACTIVE_CLEAN_WORKERS.clear()
    started = threading.Event()
    release = threading.Event()

    def blocking_worker(project_id, started_task_id, data):
        assert started_task_id == task_id
        started.set()
        assert release.wait(5)

    monkeypatch.setattr(app_module, "_v47_run_clean_task", blocking_worker)
    try:
        app_module._v47_recover_clean_tasks(pid)
        assert started.wait(5)
        assert (pid, task_id) in app_module._V47_ACTIVE_CLEAN_WORKERS
    finally:
        release.set()


def test_clean_decision_rollback_preserves_concurrent_updated_at(client, monkeypatch):
    import app as app_module

    pid = client.post(
        "/api/projects", json={"name": "decision-rollback", "labels": []}
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]
    batch_id = uploaded["batch_id"]

    def fail_start(project_id, task_id):
        app_module.material_store(project_id).patch(
            {
                image_id: {
                    "filename": "concurrent-name.png",
                    "updated_at": "concurrent-updated",
                }
            }
        )
        raise RuntimeError("simulated worker start failure")

    monkeypatch.setattr(app_module, "_v47_start_clean_task_record", fail_start)
    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )
    assert response.status_code == 500
    batch = client.get(f"/api/v55/projects/{pid}/upload-batches/{batch_id}").json()
    assert batch["items"][0]["decision"] == "pending"
    row = {item["id"]: item for item in client.get(f"/api/projects/{pid}/images").json()}[
        image_id
    ]
    assert row["processing_status"] == "pending_decision"
    assert row["filename"] == "concurrent-name.png"
    assert row["updated_at"] == "concurrent-updated"


def test_upload_batch_normalizes_non_string_ids_before_validation(client):
    pid = client.post(
        "/api/projects",
        json={"name": "normalize-batch-ids", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["only.png"])

    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [], "ready_image_ids": [123]},
    )

    assert response.status_code == 400
    assert "123" in response.json()["detail"]


def test_upload_batch_invalid_id_is_404_and_deleted_image_is_explicit(client):
    pid = client.post(
        "/api/projects",
        json={"name": "missing-batch-image", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["deleted.png"])
    batch_id = uploaded["batch_id"]
    image_id = uploaded["uploaded"][0]["id"]

    assert client.get(
        f"/api/v55/projects/{pid}/upload-batches/.hidden"
    ).status_code == 404
    assert client.post(
        f"/api/v55/projects/{pid}/upload-batches/.hidden/decisions",
        json={"clean_image_ids": [], "ready_image_ids": []},
    ).status_code == 404

    deleted = client.delete(f"/api/projects/{pid}/images/{image_id}")
    deleted.raise_for_status()
    batch = client.get(
        f"/api/v55/projects/{pid}/upload-batches/{batch_id}"
    )
    batch.raise_for_status()
    assert batch.json()["items"][0]["image"] is None
    assert batch.json()["items"][0]["missing"] is True


def test_partial_ready_decision_keeps_unannotated_remainder_pending(client):
    pid = client.post(
        "/api/projects",
        json={"name": "partial-ready", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["ready.png", "later.png"])
    ready_id, later_id = [item["id"] for item in uploaded["uploaded"]]

    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [], "ready_image_ids": [ready_id]},
    )
    response.raise_for_status()

    assert [item["decision"] for item in response.json()["items"]] == [
        "ready",
        "pending",
    ]
    annotation = client.get(f"/api/projects/{pid}/annotations/{ready_id}").json()
    assert annotation["boxes"] == []
    rows = {
        row["id"]: row
        for row in client.get(f"/api/projects/{pid}/images").json()
    }
    assert rows[ready_id]["processing_status"] == "processed"
    assert rows[later_id]["processing_status"] == "pending_decision"


def test_ready_only_decisions_preserve_unspecified_clean_material_state(client):
    import app as app_module

    pid = client.post(
        "/api/projects",
        json={"name": "preserve-unspecified-clean", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(
        client,
        pid,
        ["clean.png", "ready.png", "later.png"],
    )
    clean_id, ready_id, later_id = [item["id"] for item in uploaded["uploaded"]]
    decision_url = (
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions"
    )
    clean_response = client.post(
        decision_url,
        json={"clean_image_ids": [clean_id], "ready_image_ids": []},
    )
    clean_response.raise_for_status()
    task_id = clean_response.json()["clean_task_id"]
    wait_for_clean_result(client, pid, task_id)

    app_module.material_store(pid).patch(
        {
            clean_id: {
                "processing_status": "cleaning",
                "clean_decision": "clean",
                "clean_decision_at": "awaiting-decision-stable",
                "updated_at": "awaiting-updated-stable",
                "clean_task_id": task_id,
            }
        }
    )
    before_awaiting = {
        row["id"]: row
        for row in client.get(f"/api/projects/{pid}/images").json()
    }[clean_id]
    ready_response = client.post(
        decision_url,
        json={"clean_image_ids": [], "ready_image_ids": [ready_id]},
    )
    ready_response.raise_for_status()
    after_awaiting = {
        row["id"]: row
        for row in client.get(f"/api/projects/{pid}/images").json()
    }[clean_id]
    for field in (
        "processing_status",
        "clean_decision",
        "clean_decision_at",
        "updated_at",
        "clean_task_id",
    ):
        assert after_awaiting.get(field) == before_awaiting.get(field)

    confirmed = client.post(
        f"/api/v47/projects/{pid}/clean-tasks/{task_id}/confirm",
        json={"delete_ids": []},
    )
    confirmed.raise_for_status()
    app_module.material_store(pid).patch(
        {
            clean_id: {
                "clean_decision_at": "confirmed-decision-stable",
                "updated_at": "confirmed-updated-stable",
            }
        }
    )
    before_confirmed = {
        row["id"]: row
        for row in client.get(f"/api/projects/{pid}/images").json()
    }[clean_id]
    later_response = client.post(
        decision_url,
        json={"clean_image_ids": [], "ready_image_ids": [later_id]},
    )
    later_response.raise_for_status()
    after_confirmed = {
        row["id"]: row
        for row in client.get(f"/api/projects/{pid}/images").json()
    }[clean_id]
    for field in (
        "processing_status",
        "clean_decision",
        "clean_decision_at",
        "updated_at",
        "clean_task_id",
        "cleaned_at",
    ):
        assert after_confirmed.get(field) == before_confirmed.get(field)


def test_upload_batch_rejects_additional_clean_ids_after_task_start(client):
    pid = client.post(
        "/api/projects",
        json={"name": "single-clean-task-per-batch", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["first.png", "later.png"])
    first_id, later_id = [item["id"] for item in uploaded["uploaded"]]
    first = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [first_id], "ready_image_ids": []},
    )
    first.raise_for_status()

    second = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [later_id], "ready_image_ids": []},
    )

    assert second.status_code == 400
    batch = client.get(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}"
    ).json()
    assert [item["decision"] for item in batch["items"]] == ["clean", "pending"]
    tasks = client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"]
    assert len(tasks) == 1
    assert tasks[0]["request_payload"]["image_ids"] == [first_id]


def test_upload_batch_contains_only_successes_when_some_files_fail(client):
    pid = client.post(
        "/api/projects",
        json={"name": "partial-upload", "labels": []},
    ).json()["id"]
    response = client.post(
        f"/api/projects/{pid}/images",
        files=[
            ("files", ("good.png", image_bytes("checker"), "image/png")),
            ("files", ("bad.txt", b"not-an-image", "text/plain")),
        ],
        data={"dataset_id": "default"},
    )
    response.raise_for_status()
    body = response.json()

    assert body["uploaded_count"] == 1
    assert body["failed_count"] == 1
    batch = client.get(
        f"/api/v55/projects/{pid}/upload-batches/{body['batch_id']}"
    ).json()
    assert [item["image_id"] for item in batch["items"]] == body["uploaded_image_ids"]


def test_upload_with_no_successes_persists_empty_batch(client):
    pid = client.post(
        "/api/projects",
        json={"name": "empty-upload", "labels": []},
    ).json()["id"]
    response = client.post(
        f"/api/projects/{pid}/images",
        files=[("files", ("bad.txt", b"not-an-image", "text/plain"))],
        data={"dataset_id": "default"},
    )
    response.raise_for_status()
    body = response.json()

    assert body["uploaded_count"] == 0
    batch = client.get(
        f"/api/v55/projects/{pid}/upload-batches/{body['batch_id']}"
    )
    batch.raise_for_status()
    assert batch.json()["items"] == []


def test_clean_task_creation_failure_rolls_back_batch_and_material(client, monkeypatch):
    import app as app_module

    pid = client.post(
        "/api/projects",
        json={"name": "clean-task-rollback", "labels": []},
    ).json()["id"]
    uploaded = upload_many_png(client, pid, ["clean.png"])
    image_id = uploaded["uploaded"][0]["id"]

    original_material_store = app_module.material_store
    persisted_store = original_material_store(pid)

    class FailingMaterialStore:
        failed = False

        def __getattr__(self, name):
            return getattr(persisted_store, name)

        def mutate(self, fn):
            if not self.failed:
                self.failed = True
                persisted_store.mutate(fn)
                persisted_store.patch(
                    {image_id: {"concurrent_review_note": "preserve-me"}}
                )
                raise RuntimeError("injected material publication failure")
            return persisted_store.mutate(fn)

    failing_store = FailingMaterialStore()
    monkeypatch.setattr(
        app_module,
        "material_store",
        lambda project_id: (
            failing_store if project_id == pid else original_material_store(project_id)
        ),
    )
    response = client.post(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}/decisions",
        json={"clean_image_ids": [image_id], "ready_image_ids": []},
    )

    assert response.status_code == 500
    batch = client.get(
        f"/api/v55/projects/{pid}/upload-batches/{uploaded['batch_id']}"
    ).json()
    assert batch["items"][0]["decision"] == "pending"
    rows = client.get(f"/api/projects/{pid}/images").json()
    assert rows[0]["processing_status"] == "pending_decision"
    assert rows[0]["concurrent_review_note"] == "preserve-me"
    assert client.get(f"/api/v47/projects/{pid}/clean-tasks").json()["items"] == []


def test_background_annotation_index_cannot_remove_a_new_upload(client, monkeypatch):
    import threading

    import app as app_module
    from platform_core.material_store import MaterialStore

    project = client.post(
        "/api/projects",
        json={"name": "index-race", "labels": []},
    ).json()
    project_id = project["id"]
    first = upload_png(client, project_id, "before.png")

    # New uploads already have an empty summary; remove it to model a legacy
    # row that the background annotation index must backfill.
    store = MaterialStore(app_module.project_dir(project_id) / "images.json")
    store.mutate(
        lambda rows: next(
            row for row in rows if str(row.get("id")) == first["id"]
        ).pop("annotation_summary_at", None)
    )
    indexed = threading.Event()
    resume = threading.Event()
    original = app_module.read_annotation

    def paused_read(pid, image_id):
        value = original(pid, image_id)
        if image_id == first["id"]:
            indexed.set()
            assert resume.wait(5), "annotation index worker did not resume"
        return value

    monkeypatch.setattr(app_module, "read_annotation", paused_read)
    thread = threading.Thread(
        target=app_module._v52_annotation_index_worker,
        args=(project_id,),
    )
    thread.start()
    try:
        assert indexed.wait(5), "annotation index worker did not reach the pause"
        second = upload_png(client, project_id, "during.png")
    finally:
        resume.set()
        thread.join(5)

    assert not thread.is_alive(), "annotation index worker did not terminate"
    assert "error" not in app_module._ANNOTATION_INDEX_STATUS[project_id]
    rows = client.get(f"/api/projects/{project_id}/images").json()
    assert {row["id"] for row in rows} >= {first["id"], second["id"]}


def test_upload_batch_and_confirmed_cleaning_only_delete_selected_items(client):
    project = client.post(
        "/api/projects",
        json={
            "name": f"clean-{uuid.uuid4().hex[:8]}",
            "labels": [{"code": "fire", "display_name": "明火"}],
        },
    ).json()
    pid = project["id"]
    checker = image_bytes("checker")
    upload = client.post(
        f"/api/projects/{pid}/images",
        files=[
            ("files", ("normal.png", checker, "image/png")),
            ("files", ("duplicate.png", checker, "image/png")),
            ("files", ("blurry.png", image_bytes("solid"), "image/png")),
        ],
        data={"dataset_id": "default"},
    )
    upload.raise_for_status()
    uploaded = upload.json()
    assert uploaded["batch_id"]
    assert uploaded["uploaded_image_ids"] == [item["id"] for item in uploaded["uploaded"]]
    by_name = {item["filename"]: item for item in uploaded["uploaded"]}

    duplicate = by_name["duplicate.png"]
    saved = client.post(
        f"/api/projects/{pid}/annotations/{duplicate['id']}",
        json={"boxes": [{"label": "fire", "x1": 10, "y1": 10, "x2": 80, "y2": 90}]},
    )
    saved.raise_for_status()

    task = client.post(
        f"/api/v47/projects/{pid}/clean-tasks",
        json={
            "image_ids": uploaded["uploaded_image_ids"],
            "exact_duplicate": True,
            "near_duplicate": False,
            "min_width": 1,
            "min_height": 1,
            "blur_check": True,
            "blur_min_laplacian": 5,
            "brightness_check": False,
            "task_name": "confirmed-clean-test",
        },
    ).json()
    result = wait_for_clean_result(client, pid, task["id"])
    flagged = {item["filename"]: item for item in result["result"]["items"]}
    assert {"duplicate.png", "blurry.png"}.issubset(flagged)

    confirmed = client.post(
        f"/api/v47/projects/{pid}/clean-tasks/{task['id']}/confirm",
        json={"delete_ids": [duplicate["id"]]},
    )
    confirmed.raise_for_status()
    body = confirmed.json()
    assert [item["id"] for item in body["deleted_images"]] == [duplicate["id"]]
    assert body["failed_items"] == []

    remaining = client.get(f"/api/projects/{pid}/images").json()
    assert {item["filename"] for item in remaining} == {"normal.png", "blurry.png"}
    assert client.get(f"/api/projects/{pid}/annotations/{duplicate['id']}").status_code == 404
    assert client.get(
        f"/api/projects/{pid}/annotations/{by_name['blurry.png']['id']}"
    ).status_code == 200

    ready = client.post(
        f"/api/v52/projects/{pid}/images/mark-ready",
        json={"image_ids": [by_name["blurry.png"]["id"]]},
    )
    ready.raise_for_status()
    assert ready.json()["images"][0]["clean_skipped"] is True
