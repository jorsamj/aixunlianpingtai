import io
import time
import uuid

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

    def fail_task_creation(*args, **kwargs):
        app_module.material_store(pid).patch(
            {image_id: {"concurrent_review_note": "preserve-me"}}
        )
        raise RuntimeError("injected clean task failure")

    monkeypatch.setattr(app_module, "_v47_create_clean_task_record", fail_task_creation)
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
