from platform_core.material_ingestion_service import MaterialIngestionService
import io
import json
import time
import zipfile

import app as app_module
from PIL import Image
from platform_core.negative_pool import NegativePool


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


def _negative_upload_kind(client, project_id):
    """A classless ZIP still requires an explicit pool category before import."""
    created = client.post(
        f"/api/v61/projects/{project_id}/negative-pool/categories",
        json={"name": "空背景素材"},
    )
    assert created.status_code == 200, created.text
    return {"sample_type": "negative", "negative_category_ids": [created.json()["id"]]}


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
            "sample_type": "positive", "intended_label_codes": ["helmet"],
        },
    )
    assert started.status_code == 200, started.text
    final = _wait_job(client, project["id"], job["id"])
    assert final["status"] == "done", json.dumps(final, ensure_ascii=False)
    assert final["report"]["upload_classification_status"] == "applied"
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
    assert all(app_module.material_store(project['id']).get(image_id)['upload_intended_label_codes'] == ['helmet']
               for image_id in review['image_ids'])
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
        json={"label_mapping": {"0": "helmet"}, "sample_type": "positive", "intended_label_codes": ["helmet"]},
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
            "sample_type": "positive", "intended_label_codes": ["helmet_new"],
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
        json={"label_mapping": {"0": "smoke", "1": "fire"}, "sample_type": "positive", "intended_label_codes": ["smoke", "fire"]},
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
        "annotated", "unannotated"
    }
    for annotation in annotations:
        assert "helmet" not in annotation["annotation_scope"]

    positive = next(row for row in annotations if row["annotation_state"] == "annotated")
    assert {box["label"] for box in positive["boxes"]} == {"smoke"}
    assert positive["annotation_scope"] == ["fire", "smoke"]
    empty = next(row for row in annotations if row["annotation_state"] == "unannotated")
    assert empty["boxes"] == []
    assert empty["annotation_scope"] == []


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

    selection = _negative_upload_kind(client, project['id'])
    started = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json=selection,
    )
    assert started.status_code == 200, started.text
    final = _wait_job(client, project["id"], job["id"])
    assert final["status"] == "done", json.dumps(final, ensure_ascii=False)
    assert final["report"]["upload_classification_status"] == "applied"
    assert NegativePool(app_module.material_store(project['id'])).query(
        category_ids=selection['negative_category_ids'])['total'] == 1

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


def _empty_yolo_with_schema_zip():
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("data.yaml", "names:\n  0: fire\n  1: smoke\n")
        archive.writestr("images/train/a.jpg", _jpg_bytes())
        archive.writestr("images/train/b.jpg", _jpg_bytes())
        archive.writestr("labels/train/a.txt", "")
        archive.writestr("labels/train/b.txt", "\n  \n")
    return payload.getvalue()


def test_v19_all_empty_yolo_with_schema_defaults_to_raw_no_gt(client):
    project = client.post("/api/projects", json={"name": "zip-raw-schema", "labels": []}).json()
    created = client.post(
        f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
        files={"file": ("empty-with-names.zip", _empty_yolo_with_schema_zip(), "application/zip")},
    )
    assert created.status_code == 200, created.text
    job = created.json()
    assert job["scan_kind"] == "RAW_UNANNOTATED"
    assert job["label_confirmation_required"] is False
    assert job["external_classes"] == []
    assert {row["name"] for row in job["external_class_hints"]} == {"fire", "smoke"}

    # No positive label or negative category is necessary to store raw images.
    started = client.post(f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start", json={})
    assert started.status_code == 200, started.text
    final = _wait_job(client, project["id"], job["id"])
    assert final["status"] == "done", json.dumps(final, ensure_ascii=False)
    assert final["report"]["imported_images"] == 2
    assert final["report"]["boxes"] == 0
    assert final["report"].get("upload_classification_status") != "applied"
    # Browser progress omits large image-id arrays; the paged review owner is
    # the stable contract for post-import image lookup.
    review = client.get(f"/api/v52/projects/{project['id']}/import/jobs/{job['id']}/review")
    assert review.status_code == 200, review.text
    image_ids = review.json()["image_ids"]
    for image_id in image_ids:
        annotation = client.get(f"/api/projects/{project['id']}/annotations/{image_id}").json()
        assert annotation["annotation_state"] == "unannotated"
        assert annotation["annotation_scope"] == []
    assert client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"] == []


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


def test_v19_partial_coco_manifest_keeps_unreferenced_raw_image(client):
    project = client.post("/api/projects", json={
        "name": "zip-coco-with-raw", "labels": [{"code": "fire", "display_name": "明火"}],
    }).json()
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("images/labeled.jpg", _jpg_bytes())
        archive.writestr("images/raw.jpg", _jpg_bytes())
        archive.writestr("annotations/instances.json", json.dumps({
            "images": [{"id": 1, "file_name": "images/labeled.jpg", "width": 80, "height": 60}],
            "categories": [{"id": 1, "name": "external_fire"}],
            "annotations": [{"id": 1, "image_id": 1, "category_id": 1, "bbox": [10, 10, 20, 20]}],
        }))
    created = client.post(
        f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
        files={"file": ("coco-mixed.zip", payload.getvalue(), "application/zip")},
    )
    assert created.status_code == 200, created.text
    job = created.json()
    assert job["label_confirmation_required"] is True
    started = client.post(f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start", json={
        "label_mapping": {"1": "fire"}, "sample_type": "positive", "intended_label_codes": ["fire"],
    })
    assert started.status_code == 200, started.text
    done = _wait_job(client, project["id"], job["id"])
    assert done["status"] == "done", json.dumps(done, ensure_ascii=False)
    assert done["report"]["imported_images"] == 2
    assert done["report"]["boxes"] == 1
    review = client.get(f"/api/v52/projects/{project['id']}/import/jobs/{job['id']}/review")
    assert review.status_code == 200, review.text
    states = {
        client.get(f"/api/projects/{project['id']}/annotations/{image_id}").json()["annotation_state"]
        for image_id in review.json()["image_ids"]
    }
    assert states == {"annotated", "unannotated"}


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
            json=_negative_upload_kind(client, project['id']),
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

    original = app_module._material_ingestion_service()._v19_assert_frozen_mapping_targets_active
    calls = {"count": 0}
    captured_image_ids = []

    def change_label_before_final_check(project_id, mapping):
        calls["count"] += 1
        if calls["count"] == 2:
            batch = app_module._v50_active_image_batch(project_id)
            captured_image_ids.extend(
                sorted(str(image_id) for image_id in (batch or {}).get("records", {}))
            )
            current = app_module.get_project(project_id)
            current["label_meta"][0]["status"] = "inactive"
            current["label_meta"][0]["active"] = False
            app_module.save_project(current)
        return original(project_id, mapping)

    monkeypatch.setattr(
        MaterialIngestionService,
        "_v19_assert_frozen_mapping_targets_active",
        staticmethod(change_label_before_final_check),
    )
    started = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json={"label_mapping": {"0": "helmet", "1": "helmet"}, "sample_type": "positive", "intended_label_codes": ["helmet"]},
    )
    assert started.status_code == 200, started.text
    final = _wait_job(client, project["id"], job["id"])
    assert final["status"] == "failed"
    assert calls["count"] >= 2
    assert "标签映射目标已失效" in str(final.get("error") or final.get("message") or "")

    assert captured_image_ids
    assert app_module.material_store(project["id"]).get_many(captured_image_ids) == []
    annotations = app_module.AnnotationRepository(app_module.project_dir(project["id"]))
    assert all(not annotations.exists(image_id) for image_id in captured_image_ids)



def test_v19_mapping_rejects_legacy_active_false_target(client):
    project = client.post("/api/projects", json={
        "name": "zip-active-false-target",
        "labels": [{"code": "helmet", "display_name": "安全头盔"}],
    }).json()
    current = app_module.get_project(project["id"])
    current["label_meta"][0]["status"] = "active"
    current["label_meta"][0]["active"] = False
    app_module.save_project(current)

    created = client.post(
        f"/api/v19/projects/{project['id']}/datasets/default/import/jobs",
        files={"file": ("active-false.zip", _yolo_zip(), "application/zip")},
    )
    assert created.status_code == 200, created.text
    job = created.json()
    rejected = client.post(
        f"/api/v19/projects/{project['id']}/import/jobs/{job['id']}/start",
        json={"label_mapping": {"0": "helmet", "1": "helmet"}},
    )
    assert rejected.status_code == 409
    assert "当前有效标签" in rejected.text


def test_v19_confirmed_folders_bind_real_sources_and_recover_only_pool_association(client, monkeypatch):
    from hashlib import sha256
    from platform_core.storage.zip_folders import folder_rows

    suggestions = {row['folder_key']: row for row in folder_rows({'path': f'{name}/a.jpg'} for name in (
        'Training', 'valid', 'TESTING', '训练集', '验证集', '测试集', '试验集', '评测集', 'contest_images', 'train/test'
    ))}
    assert [suggestions[key]['suggested_usage'] for key in ('Training','valid','TESTING','训练集','验证集','测试集')] == ['train','val','test'] * 2
    assert all(suggestions[key]['suggested_usage'] == 'unassigned' for key in ('试验集','评测集','contest_images','train/test'))
    assert suggestions['train/test']['suggestion_reason'] == '用途目录冲突'
    project = client.post('/api/projects', json={'name':'zip folders', 'labels':['person','vehicle']}).json()['id']
    created_category = client.post(f'/api/v61/projects/{project}/negative-pool/categories', json={'name':'反光'})
    category = created_category.json()['id']
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w', zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('data.yaml', 'names: [object]\n')
        for path in ('images/train/001.jpg','images/验证集/001.jpg','images/背景/001.jpg','raw/001.jpg'):
            archive.writestr(path, _jpg_bytes())
        for path in ('train','验证集','背景'):
            archive.writestr(f'labels/{path}/001.txt', '0 0.5 0.5 0.4 0.4\n')
        archive.writestr('images/背景/broken.jpg', b'invalid image')
    source = payload.getvalue()
    response = client.post(f'/api/v19/projects/{project}/datasets/default/import/jobs',
                           data={'folder_confirmation':'true'}, files={'file':('folders.zip',source,'application/zip')})
    assert response.status_code == 200, response.text
    job = response.json()
    assert job['folder_confirmation_required'] is True and 'images' not in job
    assert job['source_zip_sha256'] == sha256(source).hexdigest()
    endpoint = f"/api/v19/projects/{project}/import/jobs/{job['id']}"
    first = client.get(endpoint+'/folders?limit=2').json()
    second = client.get(endpoint+'/folders?limit=2&offset=2').json()
    assert first['total'] == 4 and first['next_offset'] == 2 and second['next_offset'] is None
    folders = {row['folder_key']: row for row in first['items'] + second['items']}
    assert folders['images/验证集']['suggested_usage'] == 'val'
    assert folders['images/背景']['annotated_count'] == 1 and folders['images/背景']['image_count'] == 2
    assert folders['raw']['annotated_count'] == 0 and folders['raw']['suggested_usage'] == 'unassigned'
    rules = [
        dict(folder_key='images/train',usage_intent='train',sample_type='positive',intended_label_codes=['person','vehicle']),
        dict(folder_key='images/验证集',usage_intent='val',sample_type='positive',intended_label_codes=['person']),
        dict(folder_key='images/背景',usage_intent='unassigned',sample_type='negative',negative_category_ids=[category]),
        dict(folder_key='raw',usage_intent='unassigned',sample_type='unclassified'),
    ]
    confirmation = dict(source_scan_digest=first['source_scan_digest'], folder_rules=rules, label_mapping={'0':'person'})
    start = endpoint+'/start'
    assert client.post(start,json={}).status_code == 409
    assert client.post(start,json={**confirmation,'source_scan_digest':'bad'}).status_code == 409
    assert client.post(start,json={**confirmation,'folder_rules':rules[:3]}).status_code == 422
    assert client.post(start,json={**confirmation,'folder_rules':[*rules[:3],dict(rules[3],folder_key='fake')]}).status_code == 422
    assert client.post(start,json={**confirmation,'folder_rules':[dict(rules[0],intended_label_codes=['bad']),*rules[1:]]}).status_code == 422
    assert client.post(start,json={**confirmation,'folder_rules':[*rules[:2],dict(rules[2],negative_category_ids=['other-project']),rules[3]]}).status_code == 422
    assert client.post(start,json={**confirmation,'label_mapping':{}}).status_code == 409
    original = NegativePool.members

    def fail_once(self, ids, **kwargs):
        if kwargs.get('zip_folder'):
            raise ValueError('isolated pool write failure')
        return original(self, ids, **kwargs)

    monkeypatch.setattr(NegativePool,'members',fail_once)
    response = client.post(start,json=confirmation)
    assert response.status_code == 200, response.text
    final = _wait_job(client, project, job['id'])
    assert final['status'] == 'done', final
    assert final['report']['imported_images'] == 4
    assert final['report']['folder_classification']['pending'] == 1
    review = client.get(f"/api/v52/projects/{project}/import/jobs/{job['id']}/review").json()
    store = app_module.material_store(project)
    materials = {row['zip_folder_source']['source_path']:row for row in store.get_many(review['image_ids'])}
    assert len(materials) == len({row['id'] for row in materials.values()}) == 4
    assert {row['zip_folder_source']['rule_digest'] for row in materials.values()} == {final['folder_confirmation_digest']}
    assert materials['raw/001.jpg']['zip_folder_source']['usage_intent'] == 'unassigned'
    assert materials['images/验证集/001.jpg']['zip_folder_source']['usage_intent'] == 'val'
    assert materials['images/train/001.jpg']['upload_intended_label_codes'] == ['person','vehicle']
    assert materials['images/train/001.jpg']['split'] == 'unassigned'
    negative_id = materials['images/背景/001.jpg']['id']
    annotation = f'/api/projects/{project}/annotations/{negative_id}'
    boxes = client.get(annotation).json()['boxes']
    assert [box['label'] for box in boxes] == ['person']
    assert client.get(f"/api/projects/{project}/annotations/{materials['raw/001.jpg']['id']}").json()['boxes'] == []
    assert client.post(start,json=confirmation).json()['folder_confirmation_digest'] == final['folder_confirmation_digest']
    assert client.post(start,json={**confirmation,'folder_rules':[dict(rules[0],usage_intent='test'),*rules[1:]]}).status_code == 409
    monkeypatch.setattr(NegativePool,'members',original)
    pool = NegativePool(store)
    retry = endpoint+'/retry-folder-classification'
    assert client.post(retry).json()['report']['folder_classification']['pending'] == 0
    assert pool.candidate_ids(category_ids=[category]) == [negative_id]
    assert not pool.member_snapshot(negative_id)['algorithms']
    pool_revision = pool.revision()
    assert client.post(retry).json()['report']['folder_classification']['applied'] == 4
    assert pool.revision() == pool_revision
    assert client.get(annotation).json()['boxes'] == boxes
    assert client.get(f"/api/v52/projects/{project}/import/jobs/{job['id']}/review").json()['image_ids'] == review['image_ids']


def test_v19_folder_scan_rejects_conflicting_external_class_ids(client):
    project = client.post('/api/projects', json={'name':'zip conflict', 'labels':['person']}).json()['id']
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('train/data.yaml', 'names: [person]\n')
        archive.writestr('val/data.yaml', 'names: [vehicle]\n')
        for folder in ('train','val'):
            archive.writestr(f'{folder}/images/001.jpg', _jpg_bytes())
            archive.writestr(f'{folder}/labels/001.txt', '0 0.5 0.5 0.4 0.4\n')
    uploaded = client.post(f'/api/v19/projects/{project}/datasets/default/import/jobs', data={'folder_confirmation':'true'},
                           files={'file':('conflict.zip',payload.getvalue(),'application/zip')})
    assert uploaded.status_code == 200, uploaded.text
    job = uploaded.json()
    assert job['folder_mapping_conflict'] is True
    rules = [dict(folder_key=f'{folder}/images',usage_intent=folder,sample_type='positive',intended_label_codes=['person'])
             for folder in ('train','val')]
    assert client.post(f"/api/v19/projects/{project}/import/jobs/{job['id']}/start", json={
        'source_scan_digest':job['source_scan_digest'], 'folder_rules':rules, 'label_mapping':{'0':'person'},
    }).status_code == 409
    assert app_module.v19_read_job(project,job['id'])['status'] == 'selecting'


def test_v19_coco_folder_evidence_includes_unreferenced_same_name_image(client):
    project = client.post('/api/projects', json={'name':'structured folders', 'labels':['person']}).json()['id']
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, 'w') as archive:
        archive.writestr('train/001.jpg', _jpg_bytes())
        archive.writestr('raw/001.jpg', _jpg_bytes())
        archive.writestr('coco.json', json.dumps({
            'images':[{'id':1,'file_name':'train/001.jpg','height':60,'width':80}],
            'categories':[{'id':1,'name':'person'}],
            'annotations':[{'id':1,'image_id':1,'category_id':1,'bbox':[3,4,20,20]}],
        }))
    uploaded = client.post(f'/api/v19/projects/{project}/datasets/default/import/jobs', data={'folder_confirmation':'true'},
                           files={'file':('structured.zip',payload.getvalue(),'application/zip')})
    assert uploaded.status_code == 200, uploaded.text
    job = uploaded.json()
    rules = [dict(folder_key='train',usage_intent='train',sample_type='positive',intended_label_codes=['person']),
             dict(folder_key='raw',usage_intent='unassigned',sample_type='unclassified')]
    started = client.post(f"/api/v19/projects/{project}/import/jobs/{job['id']}/start", json={
        'source_scan_digest':job['source_scan_digest'], 'folder_rules':rules, 'label_mapping':{'1':'person'},
    })
    assert started.status_code == 200, started.text
    final = _wait_job(client,project,job['id'])
    assert final['status'] == 'done', final
    assert final['report']['unreferenced_raw_images'] == 1
    samples = {row['source_path']:row['material_id'] for row in final['report']['folder_classification']['examples']}
    assert samples['train/001.jpg'] != samples['raw/001.jpg']
    assert [row['label'] for row in client.get(f"/api/projects/{project}/annotations/{samples['train/001.jpg']}").json()['boxes']] == ['person']
    assert client.get(f"/api/projects/{project}/annotations/{samples['raw/001.jpg']}").json()['boxes'] == []
