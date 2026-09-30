import io
import json
import time
import zipfile

import app as app_module
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
    assert [(row["class_id"], row["name"]) for row in remembered_job["external_classes"]] == [
        ("0", "toukui1"), ("1", "toukui2"),
    ]
    assert all("target_label_code" not in row for row in remembered_job["external_classes"])

    review = client.get(f"/api/v52/projects/{project['id']}/import/jobs/{job['id']}/review").json()
    assert len(review["image_ids"]) == 2
    for image_id in review["image_ids"]:
        boxes = client.get(f"/api/projects/{project['id']}/annotations/{image_id}").json()["boxes"]
        assert len(boxes) == 1
        assert boxes[0]["label"] == "helmet"
        assert boxes[0]["class_id"] == 0
        assert boxes[0]["source"] == "imported"
        assert boxes[0]["import_batch_id"] == job["id"]
        assert boxes[0]["source_format"] == "yolo"
        assert boxes[0]["source_task_id"] == job["id"]
        assert boxes[0]["source_class_id"] in {"0", "1"}
        assert boxes[0]["source_label_name"] in {"toukui1", "toukui2"}
        assert boxes[0]["canonical_label_id"] == "helmet"
        assert boxes[0]["canonical_project_class_id"] == 0
        assert boxes[0]["mapping_method"] == "manual"
        assert boxes[0]["confirmed_at"]


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

def test_v19_confirmation_cannot_implicitly_create_platform_label(client):
    project = client.post("/api/projects", json={
        "name": "zip-canonical-label-only",
        "labels": [{"code": "helmet", "display_name": "安全头盔"}],
    }).json()
    created = client.post(
        f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
        files={"file": ("labels.zip", _yolo_zip(), "application/zip")},
    )
    assert created.status_code == 200, created.text
    job = created.json()

    blocked = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json={
            "label_mapping": {"0": "helmet_new", "1": "helmet"},
            "create_labels": ["helmet_new"],
        },
    )
    assert blocked.status_code == 409
    assert "不能根据外部标签名隐式创建平台标签" in blocked.text

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    assert [row["code"] for row in labels] == ["helmet"]


def test_v19_explicit_canonical_label_creation_then_mapping_is_supported(client):
    project = client.post("/api/projects", json={
        "name": "zip-explicit-new-canonical-label",
        "labels": [{"code": "person", "display_name": "人员"}],
    }).json()
    created = client.post(
        f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
        files={"file": ("labels.zip", _yolo_zip(), "application/zip")},
    )
    assert created.status_code == 200, created.text
    job = created.json()

    label_created = client.post(
        f"/api/projects/{project['id']}/labels",
        json={
            "label": "helmet_new",
            "display_name": "安全头盔",
            "color": "#ef4444",
        },
    )
    assert label_created.status_code == 200, label_created.text

    started = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json={
            "label_mapping": {"0": "helmet_new", "1": "helmet_new"},
            "create_labels": [],
        },
    )
    assert started.status_code == 200, started.text
    final = _wait_job(client, project["id"], job["id"])
    assert final["status"] == "done", json.dumps(final, ensure_ascii=False)
    assert final["report"]["label_mapping"] == {"0": "helmet_new", "1": "helmet_new"}
    assert final["report"]["label_box_counts"] == {"helmet_new": 2}

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    by_code = {row["code"]: row for row in labels}
    assert set(by_code) == {"person", "helmet_new"}
    assert by_code["helmet_new"]["display_name"] == "安全头盔"
    assert by_code["helmet_new"]["aliases"] == ["toukui1", "toukui2"]




def _scoped_yolo_zip():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.yaml", "names:\n  0: external_smoke\n  1: external_fire\n")
        archive.writestr("images/train/positive.jpg", _jpg_bytes())
        archive.writestr("images/train/empty.jpg", _jpg_bytes())
        archive.writestr("labels/train/positive.txt", "0 0.5 0.5 0.4 0.4\n")
        archive.writestr("labels/train/empty.txt", "")
    return payload.getvalue()


def _plain_image_zip():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("images/train/plain.jpg", _jpg_bytes())
    return payload.getvalue()


def test_v19_structured_import_uses_only_confirmed_mapping_scope(client):
    project = client.post("/api/projects", json={
        "name": "zip-bounded-annotation-scope",
        "labels": [
            {"code": "smoke", "display_name": "烟雾"},
            {"code": "fire", "display_name": "明火"},
            {"code": "helmet", "display_name": "安全头盔"},
        ],
    }).json()
    created = client.post(
        f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
        files={"file": ("bounded-scope.zip", _scoped_yolo_zip(), "application/zip")},
    )
    assert created.status_code == 200, created.text
    job = created.json()
    assert job["label_confirmation_required"] is True

    started = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json={"label_mapping": {"0": "smoke", "1": "fire"}},
    )
    assert started.status_code == 200, started.text
    final = _wait_job(client, project["id"], job["id"])
    assert final["status"] == "done", json.dumps(final, ensure_ascii=False)

    review = client.get(
        f"/api/v52/projects/{project['id']}/import/jobs/{job['id']}/review"
    ).json()
    assert len(review["image_ids"]) == 2
    annotations = [
        client.get(f"/api/projects/{project['id']}/annotations/{image_id}").json()
        for image_id in review["image_ids"]
    ]
    assert {row["annotation_state"] for row in annotations} == {
        "annotated", "confirmed_empty"
    }
    for annotation in annotations:
        assert annotation["annotation_scope"] == ["fire", "smoke"]
        assert "helmet" not in annotation["annotation_scope"]

    positive = next(row for row in annotations if row["annotation_state"] == "annotated")
    assert {box["label"] for box in positive["boxes"]} == {"smoke"}
    empty = next(row for row in annotations if row["annotation_state"] == "confirmed_empty")
    assert empty["boxes"] == []


def test_v19_plain_image_zip_stays_unannotated_and_does_not_create_label(client):
    project = client.post("/api/projects", json={
        "name": "zip-plain-images",
        "labels": [],
    }).json()
    created = client.post(
        f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
        files={"file": ("plain-images.zip", _plain_image_zip(), "application/zip")},
    )
    assert created.status_code == 200, created.text
    job = created.json()
    assert job["label_confirmation_required"] is False
    assert job["external_classes"] == []

    started = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json={},
    )
    assert started.status_code == 200, started.text
    final = _wait_job(client, project["id"], job["id"])
    assert final["status"] == "done", json.dumps(final, ensure_ascii=False)

    review = client.get(
        f"/api/v52/projects/{project['id']}/import/jobs/{job['id']}/review"
    ).json()
    assert len(review["image_ids"]) == 1
    annotation = client.get(
        f"/api/projects/{project['id']}/annotations/{review['image_ids'][0]}"
    ).json()
    assert annotation["annotation_state"] == "unannotated"
    assert annotation["annotation_scope"] == []
    assert annotation["boxes"] == []

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    assert labels == []



def _empty_yolo_without_schema_zip():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("images/train/empty.jpg", _jpg_bytes())
        archive.writestr("labels/train/empty.txt", "")
    return payload.getvalue()


def _empty_voc_without_schema_zip():
    payload = io.BytesIO()
    xml = """<annotation>
  <filename>empty.jpg</filename>
  <size><width>80</width><height>60</height><depth>3</depth></size>
</annotation>
"""
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("JPEGImages/empty.jpg", _jpg_bytes())
        archive.writestr("Annotations/empty.xml", xml)
    return payload.getvalue()


def _empty_coco_without_schema_zip():
    payload = io.BytesIO()
    annotation = {
        "images": [{"id": 1, "file_name": "images/empty.jpg", "width": 80, "height": 60}],
        "annotations": [],
        "categories": [],
    }
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("images/empty.jpg", _jpg_bytes())
        archive.writestr("annotations/instances.json", json.dumps(annotation))
    return payload.getvalue()


def test_v19_empty_structured_sidecar_without_confirmed_schema_stays_unannotated(client):
    cases = [
        ("empty-yolo.zip", _empty_yolo_without_schema_zip()),
        ("empty-voc.zip", _empty_voc_without_schema_zip()),
        ("empty-coco.zip", _empty_coco_without_schema_zip()),
    ]
    for zip_name, payload in cases:
        project = client.post("/api/projects", json={
            "name": f"no-scope-{zip_name}",
            "labels": [],
        }).json()
        created = client.post(
            f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
            files={"file": (zip_name, payload, "application/zip")},
        )
        assert created.status_code == 200, created.text
        job = created.json()
        assert job["label_confirmation_required"] is False
        assert job["external_classes"] == []

        started = client.post(
            f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
            json={},
        )
        assert started.status_code == 200, started.text
        final = _wait_job(client, project["id"], job["id"])
        assert final["status"] == "done", json.dumps(final, ensure_ascii=False)

        review = client.get(
            f"/api/v52/projects/{project['id']}/import/jobs/{job['id']}/review"
        ).json()
        assert len(review["image_ids"]) == 1
        annotation = client.get(
            f"/api/projects/{project['id']}/annotations/{review['image_ids'][0]}"
        ).json()
        assert annotation["annotation_state"] == "unannotated"
        assert annotation["annotation_scope"] == []
        assert annotation["boxes"] == []

        labels = client.get(
            f"/api/v12/projects/{project['id']}/labels"
        ).json()["items"]
        assert labels == []



def test_v19_worker_revalidates_frozen_mapping_before_final_commit_and_rolls_back(
    client, monkeypatch
):
    project = client.post("/api/projects", json={
        "name": "zip-label-final-fence",
        "labels": [{"code": "helmet", "display_name": "安全头盔"}],
    }).json()
    created = client.post(
        f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
        files={"file": ("labels-final-fence.zip", _yolo_zip(), "application/zip")},
    )
    assert created.status_code == 200, created.text
    job = created.json()

    original = app_module._v19_assert_frozen_mapping_targets_active
    calls = {"count": 0}

    def change_label_before_final_check(project_id, mapping):
        calls["count"] += 1
        if calls["count"] == 2:
            current = app_module.get_project(project_id)
            current["label_meta"][0]["status"] = "inactive"
            current["label_meta"][0]["active"] = False
            app_module.save_project(current)
        return original(project_id, mapping)

    monkeypatch.setattr(
        app_module,
        "_v19_assert_frozen_mapping_targets_active",
        change_label_before_final_check,
    )
    started = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json={"label_mapping": {"0": "helmet", "1": "helmet"}},
    )
    assert started.status_code == 200, started.text
    final = _wait_job(client, project["id"], job["id"])
    assert final["status"] == "failed"
    assert calls["count"] >= 2
    assert "标签映射目标已失效" in str(final.get("error") or final.get("message") or "")

    imported_ids = list((final.get("report") or {}).get("imported_image_ids") or [])
    assert imported_ids
    assert app_module.material_store(project["id"]).get_many(imported_ids) == []
    assert app_module.AnnotationRepository(
        app_module.project_dir(project["id"])
    ).get_many(imported_ids) == {}
