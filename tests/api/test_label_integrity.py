import io
import json
import sqlite3
from contextlib import closing

import app as app_module
from PIL import Image

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_batches import MaterialBatchHandler
from platform_core.material_batches import BatchSelection
from platform_core.task_runtime import ArtifactStore, Scheduler, TaskKind, TaskRepository


def _isolated_runtime(tmp_path, monkeypatch):
    repository = TaskRepository(tmp_path / "tasks.sqlite3")
    artifacts = ArtifactStore(tmp_path / "artifacts")
    monkeypatch.setattr(app_module, "_SHARED_TASK_REPOSITORY", repository)
    monkeypatch.setattr(app_module, "_SHARED_TASK_ARTIFACTS", artifacts)
    scheduler = Scheduler(
        repository,
        artifacts,
        "label-integrity-worker",
        {TaskKind.MATERIAL_BATCH: MaterialBatchHandler(app_module.DATA_DIR)},
        {"materials.batch"},
        lease_seconds=10,
    )
    return repository, artifacts, scheduler


def test_full_audit_uses_annotation_truth_without_fake_material_selection(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    annotations.upsert(
        image["id"],
        [{"label": "head", "class_id": 12}],
        annotation_state="annotated",
        annotation_scope=["head"],
        project_material=False,
    )
    repository, artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)

    created = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    )

    assert created.status_code == 202, created.text
    task_id = created.json()["task_id"]
    assert created.json()["operation"] == "AUDIT_LABEL_INTEGRITY"
    assert not artifacts.artifact_path(task_id, "selection.sqlite3").exists()

    assert scheduler.run_once() is True
    final = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{task_id}"
    )
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "SUCCEEDED"
    assert final.json()["selection_frozen"] is False
    assert not artifacts.artifact_path(task_id, "selection.sqlite3").exists()

    issues = client.get(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{task_id}/issues",
        params={"limit": 100},
    )
    assert issues.status_code == 200, issues.text
    body = issues.json()
    assert body["metadata"]["truth_owner"] == "AnnotationRepository"
    assert body["metadata"]["annotation_fingerprint"]
    assert body["metadata"]["governance_fingerprint"]
    assert body["metadata"]["material_revision"] >= 1
    kinds = {(row["issue_type"], row["label_code"]) for row in body["items"]}
    assert ("ORPHAN_LABEL", "head") in kinds
    assert ("PROJECTION_DRIFT", "head") in kinds
    assert body["summary"]["affected_images"] == 1
    assert any(
        row["issue_type"] == "ORPHAN_LABEL"
        and row["label_code"] == "head"
        and row["image_count"] == 1
        for row in body["groups"]
    )

    audit_path = artifacts.artifact_path(task_id, "label-integrity.sqlite3")
    with sqlite3.connect(audit_path) as database:
        tables = {
            row[0]
            for row in database.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        reference = database.execute(
            "SELECT image_id,label_code,box_count,scope_ref,class_ids_json,annotation_digest "
            "FROM annotation_references WHERE image_id=? AND label_code='head'",
            (image["id"],),
        ).fetchone()
    assert {
        "audit_metadata",
        "audit_summary",
        "issue_groups",
        "issues",
        "annotation_references",
    } <= tables
    assert reference[:4] == (image["id"], "head", 1, 1)
    assert json.loads(reference[4]) == [12]
    assert reference[5] == annotations.get(image["id"])["content_digest"]


def test_full_audit_cannot_be_created_with_a_fake_generic_selection(
    client, seeded_project
):
    project_id, _image = seeded_project
    response = client.post(
        f"/api/v62/projects/{project_id}/material-batches",
        json={
            "operation": "AUDIT_LABEL_INTEGRITY",
            "selection_spec": {"scope": "FILTERED", "filters": {}},
        },
    )

    assert response.status_code == 422
    assert "LABEL_INTEGRITY_DEDICATED_PREPARE_REQUIRED" in response.text


def test_audit_samples_use_current_annotation_truth_and_only_source_boxes(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, first = seeded_project
    materials = app_module.material_store(project_id)
    second_image = io.BytesIO()
    Image.new("RGB", (128, 128), "navy").save(second_image, format="JPEG")
    second = {"id": "label-integrity-second-sample"}
    (app_module.project_dir(project_id) / "uploads" / "second-sample.jpg").write_bytes(
        second_image.getvalue()
    )
    materials.upsert(
        {
            "id": second["id"],
            "filename": "second-sample.jpg",
            "stored_name": "second-sample.jpg",
            "object_key": "uploads/second-sample.jpg",
            "dataset_id": "sample-preview",
            "width": 128,
            "height": 128,
            "processing_status": "processed",
        }
    )
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    for image_id in (first["id"], second["id"]):
        annotations.upsert(
            image_id,
            [
                {
                    "label": "head",
                    "class_id": 1,
                    "x1": 10,
                    "y1": 11,
                    "x2": 60,
                    "y2": 70,
                },
                {
                    "label": "fire",
                    "class_id": 0,
                    "x1": 70,
                    "y1": 71,
                    "x2": 110,
                    "y2": 120,
                },
            ],
            annotation_state="annotated",
            annotation_scope=["head", "fire"],
            project_material=False,
        )
    repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)
    audit = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    ).json()
    assert scheduler.run_once() is True
    for image_id in (first["id"], second["id"]):
        annotations.upsert(
            image_id,
            [
                {
                    "label": "head",
                    "class_id": 1,
                    "x1": 20,
                    "y1": 21,
                    "x2": 61,
                    "y2": 71,
                },
                {
                    "label": "fire",
                    "class_id": 0,
                    "x1": 70,
                    "y1": 71,
                    "x2": 110,
                    "y2": 120,
                },
            ],
            annotation_state="annotated",
            annotation_scope=["head", "fire"],
            project_material=False,
        )
    annotation_revision = annotations.current_revision()
    material_revision = materials.current_revision()

    first_page = client.get(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{audit['task_id']}/samples",
        params={"source_label": "head", "limit": 1},
    )

    assert first_page.status_code == 200, first_page.text
    body = first_page.json()
    assert body["read_only"] is True
    assert body["source_label"] == "head"
    assert body["candidate_count"] == 2
    assert body["next_cursor"]
    assert len(body["items"]) == 1
    sample = body["items"][0]
    assert sample["image_id"] in {first["id"], second["id"]}
    assert sample["filename"]
    assert sample["historical_class_ids"] == [1]
    assert sample["current_schema_identity"] == [
        {"class_id": 1, "label_code": "smoke", "status": "active"}
    ]
    assert sample["thumbnail_url"].endswith("/thumbnail?size=320")
    assert sample["content_url"].endswith(f"/materials/{sample['image_id']}/content")
    assert sample["provenance"]["storage_source_id"] == "default_local"
    assert sample["provenance"]["object_key"]
    assert len(sample["boxes"]) == 1
    assert sample["boxes"][0]["label"] == "head"
    assert sample["boxes"][0]["class_id"] == 1
    assert sample["boxes"][0]["x1"] == 20
    assert "target_label" not in sample
    assert "recommended_target" not in sample

    second_page = client.get(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{audit['task_id']}/samples",
        params={
            "source_label": "head",
            "limit": 1,
            "cursor": body["next_cursor"],
        },
    )
    assert second_page.status_code == 200, second_page.text
    second_body = second_page.json()
    assert len(second_body["items"]) == 1
    assert second_body["items"][0]["image_id"] != sample["image_id"]
    assert second_body["next_cursor"] is None
    assert annotations.current_revision() == annotation_revision
    assert materials.current_revision() == material_revision


def test_orphan_repair_revalidates_current_gt_and_freezes_only_still_affected(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, first = seeded_project
    materials = app_module.material_store(project_id)
    second_id = "orphan-second"
    materials.upsert(
        {
            "id": second_id,
            "filename": "orphan-second.jpg",
            "stored_name": "orphan-second.jpg",
            "object_key": "uploads/orphan-second.jpg",
            "processing_status": "processed",
        }
    )
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    for image_id in (first["id"], second_id):
        annotations.upsert(
            image_id,
            [{"label": "head", "class_id": 12}],
            annotation_state="annotated",
            annotation_scope=["head"],
            project_material=False,
        )
    repository, artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)
    audit = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    ).json()
    assert scheduler.run_once() is True

    # One audit candidate is corrected by a human before repair creation.
    annotations.upsert(
        second_id,
        [
            {
                "label": "smoke",
                "class_id": 1,
                "canonical_label_id": "smoke",
                "canonical_project_class_id": 1,
            }
        ],
        annotation_state="annotated",
        annotation_scope=["smoke"],
    )

    repaired = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{audit['task_id']}/repairs",
        json={"source_label": "head", "target_label": "smoke"},
    )
    assert repaired.status_code == 202, repaired.text
    body = repaired.json()
    assert body["candidate"] == 2
    assert body["still_requires_repair"] == 1
    assert body["already_resolved"] == 1
    assert body["source_labels"] == ["head"]
    assert body["target_label"] == "smoke"

    selection_path = artifacts.artifact_path(body["task_id"], "selection.sqlite3")
    with closing(BatchSelection(selection_path)) as manifest:
        rows = manifest.database.execute(
            "SELECT image_id,tombstone_json FROM selection ORDER BY image_id"
        ).fetchall()
    assert [row["image_id"] for row in rows] == [first["id"]]
    frozen = json.loads(rows[0]["tombstone_json"])
    current = annotations.get(first["id"])
    assert frozen["source_digest"] == annotations.record_digest(current)
    assert frozen["target_label"] == "smoke"
    assert frozen["target_class_id"] == 1
    assert frozen["repair_mode"] is True

    assert scheduler.run_once() is True
    final = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{body['task_id']}"
    ).json()
    assert final["status"] == "SUCCEEDED"
    assert final["changed_images"] == 1
    first_box = annotations.get(first["id"])["boxes"][0]
    assert first_box["label"] == "smoke"
    assert first_box["class_id"] == 1
    assert first_box["canonical_label_id"] == "smoke"
    assert first_box["canonical_project_class_id"] == 1
    assert annotations.get(second_id)["boxes"][0]["label"] == "smoke"


def test_full_audit_includes_legacy_fallback_and_annotated_scope_only(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    project_path = app_module.project_dir(project_id)
    annotations = AnnotationRepository(project_path)
    annotations.upsert(
        image["id"],
        [
            {
                "label": "fire",
                "class_id": 0,
                "canonical_label_id": "fire",
                "canonical_project_class_id": 0,
            }
        ],
        annotation_state="annotated",
        annotation_scope=["fire", "scope_orphan"],
        project_material=False,
    )
    legacy_dir = project_path / "annotations"
    legacy_dir.mkdir(exist_ok=True)
    (legacy_dir / "legacy-orphan.json").write_text(
        json.dumps(
            {
                "image_id": "legacy-orphan",
                "annotation_state": "annotated",
                "boxes": [{"label": "legacy_head", "class_id": 12}],
                "annotation_scope": ["legacy_head"],
            }
        ),
        encoding="utf-8",
    )
    _repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)
    audit = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    ).json()
    assert scheduler.run_once() is True

    issues = client.get(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{audit['task_id']}/issues",
        params={"limit": 100},
    ).json()
    orphan_rows = {
        (row["image_id"], row["label_code"]): row
        for row in issues["items"]
        if row["issue_type"] == "ORPHAN_LABEL"
    }
    assert orphan_rows[(image["id"], "scope_orphan")]["box_count"] == 0
    assert orphan_rows[(image["id"], "scope_orphan")]["scope_ref"] == 1
    assert orphan_rows[("legacy-orphan", "legacy_head")]["box_count"] == 1


def test_orphan_repair_rejects_target_that_is_no_longer_active(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    AnnotationRepository(app_module.project_dir(project_id)).upsert(
        image["id"],
        [{"label": "head", "class_id": 12}],
        annotation_state="annotated",
        project_material=False,
    )
    _repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)
    audit = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    ).json()
    assert scheduler.run_once() is True

    project = app_module.get_project(project_id)
    project["label_meta"][1]["status"] = "inactive"
    app_module.save_project(project)
    response = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{audit['task_id']}/repairs",
        json={"source_label": "head", "target_label": "smoke"},
    )

    assert response.status_code == 409
    assert "LABEL_INTEGRITY_TARGET_UNAVAILABLE" in response.text


def test_batch_repair_aggregates_mappings_per_image_and_writes_once(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, first = seeded_project
    materials = app_module.material_store(project_id)
    second_id = "batch-scope-only"
    materials.upsert(
        {
            "id": second_id,
            "filename": "batch-scope-only.jpg",
            "stored_name": "batch-scope-only.jpg",
            "object_key": "uploads/batch-scope-only.jpg",
            "processing_status": "processed",
        }
    )
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    annotations.upsert(
        first["id"],
        [
            {"label": "head", "code": "head", "class_id": 12},
            {"label": "Helmet", "code": "Helmet", "class_id": 13},
        ],
        annotation_state="annotated",
        annotation_scope=["head", "Helmet", "No_Helmet"],
        project_material=False,
    )
    annotations.upsert(
        second_id,
        [],
        annotation_state="confirmed_empty",
        annotation_scope=["Persona", "No_Helmet"],
        project_material=False,
    )
    first_version = annotations.get(first["id"])["version"]
    repository, artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)
    audit = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    ).json()
    assert scheduler.run_once() is True
    mappings = [
        {"source_label": "head", "target_label": "smoke"},
        {"source_label": "Helmet", "target_label": "smoke"},
        {"source_label": "No_Helmet", "target_label": "fire"},
        {"source_label": "Persona", "target_label": "fire"},
    ]

    created = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{audit['task_id']}/repairs",
        json={"mappings": mappings},
    )

    assert created.status_code == 202, created.text
    body = created.json()
    assert body["mapping_count"] == 4
    assert body["candidate_images"] == 2
    assert body["still_requires_repair"] == 2
    selection_path = artifacts.artifact_path(body["task_id"], "selection.sqlite3")
    with closing(BatchSelection(selection_path)) as manifest:
        rows = manifest.database.execute(
            "SELECT image_id,tombstone_json FROM selection ORDER BY image_id"
        ).fetchall()
    assert len(rows) == 2
    plans = {row["image_id"]: json.loads(row["tombstone_json"]) for row in rows}
    assert len(plans[first["id"]]["mappings"]) == 3
    assert len(plans[second_id]["mappings"]) == 2
    assert plans[first["id"]]["expected_digest"]
    assert plans[first["id"]]["result_digest"]

    duplicate = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{audit['task_id']}/repairs",
        json={"mappings": [mappings[0]]},
    )
    assert duplicate.status_code == 409
    assert "LABEL_INTEGRITY_REPAIR_ACTIVE" in duplicate.text

    assert scheduler.run_once() is True
    final = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{body['task_id']}"
    ).json()
    assert final["status"] == "SUCCEEDED"
    assert final["mapping_count"] == 4
    assert final["candidate_images"] == 2
    assert final["succeeded"] == 2
    assert final["failed"] == 0
    assert final["changed_images"] == 2
    assert final["changed_boxes"] == 2
    assert final["result"]["changed_scope_images"] == 2
    assert final["result"]["candidate_images"] == 2
    assert final["result"]["mapping_count"] == 4
    assert final["result"]["failure_reasons"] == {}
    first_after = annotations.get(first["id"])
    assert first_after["version"] == first_version + 1
    assert [box["label"] for box in first_after["boxes"]] == ["smoke", "smoke"]
    assert all(box["class_id"] == 1 for box in first_after["boxes"])
    assert all(box["canonical_label_id"] == "smoke" for box in first_after["boxes"])
    assert first_after["annotation_scope"] == ["fire", "smoke"]
    assert annotations.get(second_id)["annotation_scope"] == ["fire"]
    assert annotations.label_reference_preview(
        ["head", "Helmet", "No_Helmet", "Persona"]
    )["affected_images"] == 0


def test_audit_exposes_final_active_merge_target_but_never_defaults_orphan(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    project = app_module.get_project(project_id)
    project["labels"].extend(["Helmet", "helmet_alias"])
    project["label_meta"].extend(
        [
            {"status": "merged", "merged_into": "helmet_alias"},
            {"status": "merged", "merged_into": "smoke"},
        ]
    )
    app_module.save_project(project)
    AnnotationRepository(app_module.project_dir(project_id)).upsert(
        image["id"],
        [
            {"label": "Helmet", "class_id": 2},
            {"label": "head", "class_id": 12},
        ],
        annotation_state="annotated",
        annotation_scope=["Helmet", "head"],
        project_material=False,
    )
    _repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)
    audit = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    ).json()
    assert scheduler.run_once() is True

    issues = client.get(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{audit['task_id']}/issues",
        params={"limit": 100},
    ).json()

    assert issues["repair_defaults"]["Helmet"] == {
        "target_label": "smoke",
        "merge_chain": ["Helmet", "helmet_alias", "smoke"],
    }
    assert "head" not in issues["repair_defaults"]


def test_batch_repair_submits_only_configured_sources_and_keeps_external_cas(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, image = seeded_project
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    annotations.upsert(
        image["id"],
        [
            {"label": "head", "class_id": 12},
            {"label": "unconfigured", "class_id": 13},
        ],
        annotation_state="annotated",
        annotation_scope=["head", "unconfigured"],
        project_material=False,
    )
    _repository, artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)
    audit = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    ).json()
    assert scheduler.run_once() is True
    created = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{audit['task_id']}/repairs",
        json={"mappings": [{"source_label": "head", "target_label": "smoke"}]},
    )
    assert created.status_code == 202, created.text
    selection_path = artifacts.artifact_path(
        created.json()["task_id"], "selection.sqlite3"
    )
    with closing(BatchSelection(selection_path)) as manifest:
        frozen = json.loads(
            manifest.database.execute(
                "SELECT tombstone_json FROM selection"
            ).fetchone()[0]
        )
    assert [item["source_label"] for item in frozen["mappings"]] == ["head"]
    annotations.upsert(
        image["id"],
        [
            {"label": "head", "class_id": 12, "x1": 1},
            {"label": "unconfigured", "class_id": 13},
        ],
        annotation_state="annotated",
        annotation_scope=["head", "unconfigured"],
        project_material=False,
    )

    assert scheduler.run_once() is True
    final = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{created.json()['task_id']}"
    ).json()
    assert final["status"] == "FAILED"
    assert final["failed"] == 1
    assert any(
        item["error"] == "ANNOTATION_CHANGED_DURING_REMAP"
        for item in final["error_examples"]
    )
    assert final["result"]["failure_reasons"] == {
        "ANNOTATION_CHANGED_DURING_REMAP": 1
    }
    current = annotations.get(image["id"])
    assert [box["label"] for box in current["boxes"]] == ["head", "unconfigured"]
