import io
import time
import zipfile

from PIL import Image


def _jpg_bytes():
    stream = io.BytesIO()
    Image.new("RGB", (80, 60), "white").save(stream, format="JPEG")
    return stream.getvalue()


def _project(client, name):
    response = client.post("/api/projects", json={
        "name": name,
        "labels": [{"code": "helmet", "display_name": "安全头盔"}],
    })
    assert response.status_code == 200, response.text
    return response.json()


def _wait_source_job(client, project_id, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(
            f"/api/v36/projects/{project_id}/datasets/default/source-import/jobs"
        ).json()
        items = body.get("items") or []
        if items and items[0].get("status") in {"done", "failed"}:
            return items[0]
        time.sleep(0.05)
    raise AssertionError("v36 source import did not finish")


def _label_codes(client, project_id):
    body = client.get(f"/api/v12/projects/{project_id}/labels").json()
    return [row["code"] for row in body["items"]]


def test_v36_annotated_directory_is_blocked_before_job_creation(client, tmp_path):
    project = _project(client, "v36-annotated-directory")
    root = tmp_path / "annotated"
    (root / "images" / "train").mkdir(parents=True)
    (root / "labels" / "train").mkdir(parents=True)
    (root / "images" / "train" / "a.jpg").write_bytes(_jpg_bytes())
    (root / "data.yaml").write_text("names:\n  0: toukui1\n", encoding="utf-8")
    (root / "labels" / "train" / "a.txt").write_text(
        "0 0.5 0.5 0.4 0.4\n", encoding="utf-8"
    )

    scan = client.post(
        f"/api/v36/projects/{project['id']}/datasets/default/source-import/scan",
        json={"source": str(root)},
    )
    assert scan.status_code == 200, scan.text
    body = scan.json()
    assert body["legacy_annotated_import_blocked"] is True
    assert body["label_confirmation_required"] is True
    assert "YOLO" in body["detected_annotation_formats"]

    blocked = client.post(
        f"/api/v36/projects/{project['id']}/datasets/default/source-import/jobs",
        json={"source": str(root)},
    )
    assert blocked.status_code == 409
    assert "上传并检查标注" in blocked.text

    jobs = client.get(
        f"/api/v36/projects/{project['id']}/datasets/default/source-import/jobs"
    ).json()["items"]
    assert jobs == []
    assert _label_codes(client, project["id"]) == ["helmet"]


def test_v36_annotated_zip_is_blocked_before_job_creation(client, tmp_path):
    project = _project(client, "v36-annotated-zip")
    archive_path = tmp_path / "annotated.zip"
    with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.yaml", "names:\n  0: toukui1\n")
        archive.writestr("images/train/a.jpg", _jpg_bytes())
        archive.writestr("labels/train/a.txt", "0 0.5 0.5 0.4 0.4\n")

    blocked = client.post(
        f"/api/v36/projects/{project['id']}/datasets/default/source-import/jobs",
        json={"source": str(archive_path)},
    )
    assert blocked.status_code == 409
    assert "YOLO" in blocked.text
    assert _label_codes(client, project["id"]) == ["helmet"]


def test_v36_plain_image_directory_remains_supported_without_creating_labels(client, tmp_path):
    project = _project(client, "v36-plain-images")
    root = tmp_path / "plain"
    root.mkdir()
    (root / "a.jpg").write_bytes(_jpg_bytes())

    started = client.post(
        f"/api/v36/projects/{project['id']}/datasets/default/source-import/jobs",
        json={"source": str(root), "dataset_kind": "images"},
    )
    assert started.status_code == 200, started.text

    final = _wait_source_job(client, project["id"])
    assert final["status"] == "done", final
    assert final["report"]["imported_images"] == 1
    assert final["report"]["boxes"] == 0
    assert _label_codes(client, project["id"]) == ["helmet"]
