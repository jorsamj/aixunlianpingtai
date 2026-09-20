from types import SimpleNamespace

import app as app_module
from platform_core.task_runtime import ArtifactStore, TaskKind, TaskStatus

def test_label_aliases_are_editable_and_canonical_conflicts_fail_closed(client):
    project = client.post("/api/projects", json={
        "name": "label-alias-api",
        "labels": [
            {"code": "helmet", "display_name": "安全头盔"},
            {"code": "person", "display_name": "人员"},
        ],
    }).json()

    updated = client.put(
        f"/api/v12/projects/{project['id']}/labels/0",
        json={
            "code": "helmet",
            "display_name": "安全头盔",
            "aliases": ["toukui1", "toukui2", "toukui1"],
        },
    )
    assert updated.status_code == 200, updated.text
    helmet = updated.json()["items"][0]
    assert helmet["aliases"] == ["toukui1", "toukui2"]

    conflict = client.put(
        f"/api/v12/projects/{project['id']}/labels/0",
        json={
            "code": "helmet",
            "display_name": "安全头盔",
            "aliases": ["person"],
        },
    )
    assert conflict.status_code == 409
    assert "正式标签身份冲突" in conflict.text

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    assert labels[0]["aliases"] == ["toukui1", "toukui2"]
    assert labels[1]["aliases"] == []


def test_confirmed_alias_learning_skips_only_canonical_conflicts(client):
    project = client.post("/api/projects", json={
        "name": "label-alias-mixed-confirmation",
        "labels": [
            {"code": "helmet", "display_name": "安全头盔"},
            {"code": "person", "display_name": "人员"},
        ],
    }).json()

    remembered = app_module.remember_project_label_aliases(
        project["id"],
        [
            {"class_id": "0", "name": "toukui1"},
            {"class_id": "1", "name": "person"},
            {"class_id": "2", "name": "toukui2"},
        ],
        {"0": "helmet", "1": "helmet", "2": "helmet"},
    )
    assert remembered["helmet"] == ["toukui1", "toukui2"]

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    helmet = next(row for row in labels if row["code"] == "helmet")
    assert helmet["aliases"] == ["toukui1", "toukui2"]
    assert "person" not in helmet["aliases"]


def test_new_canonical_label_retires_matching_alias_from_other_label(client):
    project = client.post("/api/projects", json={
        "name": "label-alias-canonical-promotion",
        "labels": [{"code": "helmet", "display_name": "安全头盔"}],
    }).json()

    seeded = client.put(
        f"/api/v12/projects/{project['id']}/labels/0",
        json={
            "code": "helmet",
            "display_name": "安全头盔",
            "aliases": ["toukui1"],
        },
    )
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["items"][0]["aliases"] == ["toukui1"]

    promoted = client.post(
        f"/api/projects/{project['id']}/labels",
        json={"label": "toukui1", "display_name": "头盔旧类"},
    )
    assert promoted.status_code == 200, promoted.text

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    helmet = next(row for row in labels if row["code"] == "helmet")
    canonical = next(row for row in labels if row["code"] == "toukui1")
    assert helmet["aliases"] == []
    assert canonical["code"] == "toukui1"


def test_project_initialization_preserves_aliases_and_prunes_canonical_conflicts(client):
    project = client.post("/api/projects", json={
        "name": "label-alias-project-init",
        "labels": [
            {
                "code": "helmet",
                "display_name": "安全头盔",
                "aliases": ["toukui1", "person"],
            },
            {
                "code": "person",
                "display_name": "人员",
                "aliases": [],
            },
        ],
    }).json()

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    helmet = next(row for row in labels if row["code"] == "helmet")
    assert helmet["aliases"] == ["toukui1"]


def test_storage_rescan_review_uses_confirmed_alias_suggestions(
    client, tmp_path, monkeypatch
):
    project = client.post("/api/projects", json={
        "name": "label-alias-storage-rescan",
        "labels": [{
            "code": "helmet",
            "display_name": "安全头盔",
            "aliases": ["toukui1"],
        }],
    }).json()

    artifacts = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)
    task_id = "rescan-alias-review"
    artifacts.atomic_write_json(task_id, "request.json", {
        "mode": "storage_rescan",
        "import_format": "yolo",
        "execution_mode": "local",
    })
    artifacts.atomic_write_json(task_id, "result.json", {
        "mode": "storage_rescan",
        "stage": "awaiting_confirmation",
        "import_format": "yolo",
        "counts": {"NEW": 1},
        "quality": {
            "images": 1,
            "boxes": 2,
            "classes": 1,
            "annotation_status": {},
            "issues": {},
            "examples": [],
        },
        "external_classes": [{
            "class_id": "0",
            "name": "toukui1",
            "image_count": 1,
            "box_count": 2,
        }],
    })
    task = SimpleNamespace(
        task_id=task_id,
        project_id=project["id"],
        status=TaskStatus.AWAITING_CONFIRMATION,
        stage="awaiting_confirmation",
        accepted=False,
        worker_id=None,
        resource_wait_reason="",
        current_item="",
        result_ref="result.json",
        payload_ref="request.json",
    )

    public = app_module._public_storage_rescan(task)
    assert public["status"] == "AWAITING_CONFIRMATION"
    assert public["accepted"] is False
    assert public["external_classes"][0]["name"] == "toukui1"
    assert public["external_classes"][0]["target_label_code"] == "helmet"


def test_v60_ai_task_accepts_learned_alias_in_label_input(client, seeded_project):
    project_id, image = seeded_project
    updated = client.put(
        f"/api/v12/projects/{project_id}/labels/0",
        json={
            "code": "fire",
            "display_name": "明火",
            "aliases": ["huomiao1"],
        },
    )
    assert updated.status_code == 200, updated.text

    created = client.post(
        f"/api/v60/projects/{project_id}/annotation-tasks",
        json={
            "image_ids": [image["id"]],
            "labels_text": "huomiao1",
            "provider_id": "alias-test-provider",
            "task_name": "alias input test",
        },
    )
    assert created.status_code == 202, created.text
    task_id = created.json()["id"]
    request = app_module.shared_task_artifacts().read_json(
        task_id, "request.json", default={}
    )
    assert request["labels"] == ["fire"]
    assert request["labels_text"] == "huomiao1"


def test_pending_storage_import_refreshes_alias_suggestions(
    client, tmp_path, monkeypatch
):
    project = client.post("/api/projects", json={
        "name": "label-alias-storage-import",
        "labels": [{
            "code": "helmet",
            "display_name": "安全头盔",
            "aliases": ["toukui1"],
        }],
    }).json()

    artifacts = ArtifactStore(tmp_path / "import-artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)
    task_id = "storage-import-alias-review"
    artifacts.atomic_write_json(task_id, "request.json", {
        "mode": "storage_scan",
        "execution_mode": "local",
        "import_format": "yolo",
        "storage_source_id": "source-1",
    })
    artifacts.atomic_write_json(task_id, "scan/result.json", {
        "stage": "awaiting_confirmation",
        "import_format": "yolo",
        "external_classes": [{
            "class_id": "0",
            "name": "toukui1",
            "target_label_code": None,
        }],
    })
    task = SimpleNamespace(
        task_id=task_id,
        project_id=project["id"],
        kind=TaskKind.MATERIAL_IMPORT,
        status=TaskStatus.AWAITING_CONFIRMATION,
        accepted=False,
        progress=50,
        stage="awaiting_confirmation",
        current_item="",
        error="",
        created_at="2026-09-20T00:00:00+00:00",
        updated_at="2026-09-20T00:00:00+00:00",
        finished_at=None,
        result_ref="scan/result.json",
        payload_ref="request.json",
    )

    public = app_module._public_storage_import_task(task)
    assert public["status"] == "AWAITING_CONFIRMATION"
    assert public["result"]["external_classes"][0]["target_label_code"] == "helmet"

    task.accepted = True
    frozen = app_module._public_storage_import_task(task)
    assert frozen["result"]["external_classes"][0]["target_label_code"] is None


def test_project_creation_rejects_overlong_alias_with_400(client):
    response = client.post("/api/projects", json={
        "name": "invalid-label-alias",
        "labels": [{
            "code": "helmet",
            "display_name": "安全头盔",
            "aliases": ["x" * 129],
        }],
    })
    assert response.status_code == 400
    assert "标签别名无效" in response.text


def test_legacy_batch_remap_cannot_create_implicit_target_label(client):
    project = client.post("/api/projects", json={
        "name": "legacy-remap-canonical-only",
        "labels": [{"code": "helmet", "display_name": "安全头盔"}],
    }).json()

    response = client.post(
        f"/api/v52/projects/{project['id']}/labels/remap",
        json={
            "image_ids": ["not-needed-for-target-validation"],
            "source_label": "toukui1",
            "target_label": "toukui_new",
        },
    )
    assert response.status_code == 409
    assert "目标标签必须来自当前有效标签库" in response.text

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    assert [row["code"] for row in labels] == ["helmet"]


def test_ensure_label_retires_alias_for_any_canonical_creation_path(client):
    project = client.post("/api/projects", json={
        "name": "ensure-label-alias-retirement",
        "labels": [{"code": "helmet", "display_name": "安全头盔"}],
    }).json()

    seeded = client.put(
        f"/api/v12/projects/{project['id']}/labels/0",
        json={
            "code": "helmet",
            "display_name": "安全头盔",
            "aliases": ["blueprint_hat"],
        },
    )
    assert seeded.status_code == 200, seeded.text
    assert seeded.json()["items"][0]["aliases"] == ["blueprint_hat"]

    mutable_project = app_module.get_project(project["id"])
    class_id = app_module.ensure_label(mutable_project, "blueprint_hat")
    assert class_id == 1

    labels = client.get(f"/api/v12/projects/{project['id']}/labels").json()["items"]
    helmet = next(row for row in labels if row["code"] == "helmet")
    promoted = next(row for row in labels if row["code"] == "blueprint_hat")
    assert helmet["aliases"] == []
    assert promoted["class_id"] == 1
    assert promoted["aliases"] == []
