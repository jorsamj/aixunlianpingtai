import io
import json
import time
import zipfile

from PIL import Image


def _jpg_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (80, 60), "white").save(stream, format="JPEG")
    return stream.getvalue()


def _yolo_zip():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.yaml", "names:\n  0: toukui1\n  1: toukui2\n")
        archive.writestr("images/train/a.jpg", _jpg_bytes())
        archive.writestr("images/train/b.jpg", _jpg_bytes())
        archive.writestr("annotations/train/a.txt", "0 0.5 0.5 0.4 0.4\n")
        archive.writestr("annotations/train/b.txt", "1 0.5 0.5 0.4 0.4\n")
    return payload.getvalue()


def _wait_job(client, project_id, job_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v19/projects/{project_id}/import/jobs/{job_id}").json()
        if body.get("status") in {"done", "failed"}:
            return body
        time.sleep(0.05)
    raise AssertionError("ZIP import did not finish")


def test_v19_yolo_requires_explicit_label_mapping_before_formal_import(client):
    project = client.post("/api/projects", json={
        "name": "zip-label-normalization",
        "labels": [{"code": "helmet", "display_name": "安全头盔"}],
    }).json()
    created = client.post(
        f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
        files={"file": ("labels.zip", _yolo_zip(), "application/zip")},
    )
    assert created.status_code == 200, created.text
    job = created.json()
    assert job["status"] == "selecting"
    assert job["detected_format"] == "YOLO"
    assert job["label_confirmation_required"] is True
    assert [(row["class_id"], row["name"]) for row in job["external_classes"]] == [
        ("0", "toukui1"), ("1", "toukui2"),
    ]
    assert [row["box_count"] for row in job["external_classes"]] == [1, 1]

    blocked = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json={"selected_paths": []},
    )
    assert blocked.status_code == 409

    started = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json={
            "selected_paths": [],
            "label_mapping": {"0": "helmet", "1": "helmet"},
            "create_labels": [],
        },
    )
    assert started.status_code == 200, started.text
    final = _wait_job(client, project["id"], job["id"])
    assert final["status"] == "done", json.dumps(final, ensure_ascii=False)
    assert final["report"]["label_mapping"] == {"0": "helmet", "1": "helmet"}
    assert final["report"]["label_box_counts"] == {"helmet": 2}
    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    assert [row["code"] for row in labels] == ["helmet"]
    assert labels[0]["aliases"] == ["toukui1", "toukui2"]

    remembered = client.post(
        f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
        files={"file": ("labels-again.zip", _yolo_zip(), "application/zip")},
    )
    assert remembered.status_code == 200, remembered.text
    remembered_job = remembered.json()
    assert remembered_job["label_confirmation_required"] is True
    assert [row["target_label_code"] for row in remembered_job["external_classes"]] == [
        "helmet", "helmet",
    ]

    review = client.get(f"/api/v52/projects/{project['id']}/import/jobs/{job['id']}/review").json()
    assert len(review["image_ids"]) == 2
    for image_id in review["image_ids"]:
        boxes = client.get(f"/api/projects/{project['id']}/annotations/{image_id}").json()["boxes"]
        assert len(boxes) == 1
        assert boxes[0]["label"] == "helmet"
        assert boxes[0]["class_id"] == 0


def _broken_yolo_zip():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.yaml", "names:\n  0: toukui1\n")
        archive.writestr("images/train/broken.jpg", b"not-a-real-image")
        archive.writestr("annotations/train/broken.txt", "0 0.5 0.5 0.4 0.4\n")
    return payload.getvalue()


def test_v19_failed_retry_cannot_change_frozen_label_mapping(client):
    project = client.post("/api/projects", json={
        "name": "zip-label-freeze",
        "labels": [
            {"code": "helmet", "display_name": "安全头盔"},
            {"code": "person", "display_name": "人员"},
        ],
    }).json()
    created = client.post(
        f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
        files={"file": ("broken.zip", _broken_yolo_zip(), "application/zip")},
    )
    assert created.status_code == 200, created.text
    job = created.json()
    assert job["label_confirmation_required"] is True

    started = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json={"label_mapping": {"0": "helmet"}},
    )
    assert started.status_code == 200, started.text
    failed = _wait_job(client, project["id"], job["id"])
    assert failed["status"] == "failed"

    changed = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json={"label_mapping": {"0": "person"}},
    )
    assert changed.status_code == 409
    assert "已经确认冻结" in changed.text
