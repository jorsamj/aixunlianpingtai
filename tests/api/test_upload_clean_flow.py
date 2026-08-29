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
