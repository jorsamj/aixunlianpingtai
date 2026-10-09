import io
import json
import sqlite3
import threading
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


def test_repair_admission_holds_one_project_lock_through_freeze_and_create(
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
    _repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)
    audit = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    ).json()
    assert scheduler.run_once() is True

    original_get_many = AnnotationRepository.get_many
    first_inside_freeze = threading.Event()
    release_first = threading.Event()
    second_finished = threading.Event()
    call_lock = threading.Lock()
    call_count = 0

    def blocking_get_many(self, image_ids):
        nonlocal call_count
        with call_lock:
            call_count += 1
            ordinal = call_count
        if ordinal == 1:
            first_inside_freeze.set()
            assert release_first.wait(3)
        return original_get_many(self, image_ids)

    monkeypatch.setattr(AnnotationRepository, "get_many", blocking_get_many)
    responses = []

    def submit(mark_done=None):
        responses.append(client.post(
            f"/api/v54/projects/{project_id}/labels/integrity/audits/{audit['task_id']}/repairs",
            json={"source_label": "head", "target_label": "smoke"},
        ))
        if mark_done is not None:
            mark_done.set()

    first = threading.Thread(target=submit)
    first.start()
    assert first_inside_freeze.wait(3)
    second = threading.Thread(target=submit, args=(second_finished,))
    second.start()

    assert second_finished.wait(0.2) is False
    with call_lock:
        assert call_count == 1

    release_first.set()
    first.join(3)
    second.join(3)
    assert not first.is_alive()
    assert not second.is_alive()
    assert sorted(response.status_code for response in responses) == [202, 409]


def test_repair_worker_treats_externally_resolved_stale_record_as_noop(
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
    _repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)
    audit = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    ).json()
    assert scheduler.run_once() is True
    created = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{audit['task_id']}/repairs",
        json={"source_label": "head", "target_label": "smoke"},
    )
    assert created.status_code == 202, created.text

    resolved = annotations.upsert(
        image["id"],
        [{"label": "fire", "class_id": 0}],
        annotation_state="annotated",
        annotation_scope=["fire"],
        project_material=True,
    )

    assert scheduler.run_once() is True
    final = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{created.json()['task_id']}"
    ).json()
    assert final["status"] == "SUCCEEDED"
    assert final["failed"] == 0
    assert final["changed_images"] == 0
    assert final["noop_resolved"] == 1
    assert final["already_resolved"] == 1
    current = annotations.get(image["id"])
    assert current["version"] == resolved["version"]
    assert current["boxes"] == resolved["boxes"]


def test_merged_scope_fixture_repairs_once_and_stays_clean_across_full_audits(
    client, seeded_project, tmp_path, monkeypatch
):
    project_id, _image = seeded_project
    project = app_module.get_project(project_id)
    project["labels"] = [
        "safetyhelmet", "NOT_safetyhelmet", "people",
        "Helmet", "No_Helmet", "No_helmet_detected", "Persona",
        "Safety_helmet_detected", "helmet", "safetyhelmet2",
    ]
    project["label_meta"] = [
        {"status": "active"},
        {"status": "active"},
        {"status": "active"},
        {"status": "merged", "merged_into": "safetyhelmet"},
        {"status": "merged", "merged_into": "NOT_safetyhelmet"},
        {"status": "merged", "merged_into": "NOT_safetyhelmet"},
        {"status": "merged", "merged_into": "people"},
        {"status": "merged", "merged_into": "safetyhelmet"},
        {"status": "merged", "merged_into": "Helmet"},
        {"status": "merged", "merged_into": "safetyhelmet"},
    ]
    app_module.save_project(project)
    materials = app_module.material_store(project_id)
    for image_id in ("empty-scope-history", "persisted-merged-scope"):
        materials.upsert({
            "id": image_id,
            "filename": f"{image_id}.jpg",
            "stored_name": f"{image_id}.jpg",
            "object_key": f"uploads/{image_id}.jpg",
            "processing_status": "processed",
        })
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    active_scope = ["safetyhelmet", "NOT_safetyhelmet", "people"]
    annotations.upsert(
        "empty-scope-history",
        [],
        annotation_state="confirmed_empty",
        annotation_scope=active_scope,
        project_material=True,
    )
    empty_payload = annotations._content_payload([], "confirmed_empty", [])
    with closing(annotations._connect()) as database, database:
        database.execute(
            "UPDATE annotations SET scope_json='[]',content_digest=? WHERE image_id=?",
            (empty_payload["content_digest"], "empty-scope-history"),
        )
    merged_sources = [
        "Helmet", "No_Helmet", "No_helmet_detected", "Persona",
        "Safety_helmet_detected", "helmet", "safetyhelmet2",
    ]
    annotations.upsert(
        "persisted-merged-scope",
        [],
        annotation_state="confirmed_empty",
        annotation_scope=merged_sources,
        project_material=True,
    )
    assert annotations.get("empty-scope-history")["annotation_scope"] == sorted(active_scope)

    _repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)

    def full_audit():
        created = client.post(
            f"/api/v54/projects/{project_id}/labels/integrity/audits"
        )
        assert created.status_code == 202, created.text
        assert scheduler.run_once() is True
        issues = client.get(
            f"/api/v54/projects/{project_id}/labels/integrity/audits/{created.json()['task_id']}/issues",
            params={"limit": 500},
        )
        assert issues.status_code == 200, issues.text
        return created.json(), issues.json()

    first_audit, first_issues = full_audit()
    incomplete = {
        (item["image_id"], item["label_code"])
        for item in first_issues["items"]
        if item["issue_type"] == "INCOMPLETE_MERGE"
    }
    assert not any(image_id == "empty-scope-history" for image_id, _ in incomplete)
    assert {
        label for image_id, label in incomplete
        if image_id == "persisted-merged-scope"
    } == set(merged_sources)

    mappings = [
        {"source_label": "Helmet", "target_label": "safetyhelmet"},
        {"source_label": "No_Helmet", "target_label": "NOT_safetyhelmet"},
        {"source_label": "No_helmet_detected", "target_label": "NOT_safetyhelmet"},
        {"source_label": "Persona", "target_label": "people"},
        {"source_label": "Safety_helmet_detected", "target_label": "safetyhelmet"},
        {"source_label": "helmet", "target_label": "safetyhelmet"},
        {"source_label": "safetyhelmet2", "target_label": "safetyhelmet"},
    ]
    repair = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/{first_audit['task_id']}/repairs",
        json={"mappings": mappings},
    )
    assert repair.status_code == 202, repair.text
    assert repair.json()["still_requires_repair"] == 1
    assert scheduler.run_once() is True
    repaired = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{repair.json()['task_id']}"
    ).json()
    assert repaired["status"] == "SUCCEEDED"
    assert annotations.get("persisted-merged-scope")["annotation_scope"] == sorted(active_scope)

    for _ in range(2):
        _audit, issues = full_audit()
        assert issues["summary"]["issue_count"] == 0
        assert issues["groups"] == []
        assert annotations.get("empty-scope-history")["annotation_scope"] == sorted(active_scope)
        assert annotations.get("persisted-merged-scope")["annotation_scope"] == sorted(active_scope)


def test_preview_only_drift_full_audit_and_durable_repair_preserve_formal_gt(
    client, seeded_project, tmp_path, monkeypatch,
):
    project_id, image = seeded_project
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    materials = app_module.material_store(project_id)
    before = annotations.upsert(
        image["id"],
        [{
            "label": "fire", "class_id": 0,
            "canonical_label_id": "fire", "canonical_project_class_id": 0,
            "x1": 5, "y1": 8, "x2": 32, "y2": 47,
        }],
        annotation_state="annotated",
        annotation_scope=["fire"],
    )
    correct = materials.get(image["id"])
    assert correct["annotation_preview"][0]["label"] == "fire"
    materials.patch({
        image["id"]: {
            "annotation_preview": [{
                **correct["annotation_preview"][0], "label": "fire_old",
            }],
        },
    })
    assert materials.get(image["id"])["labels"] == ["fire"]
    assert materials.get(image["id"])["annotation_hash"] == before["content_digest"]

    _repository, artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)
    audit = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    )
    assert audit.status_code == 202, audit.text
    premature = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/"
        f"{audit.json()['task_id']}/projection-repairs"
    )
    assert premature.status_code == 409
    assert scheduler.run_once() is True
    issues = client.get(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/"
        f"{audit.json()['task_id']}/issues"
    )
    assert issues.status_code == 200, issues.text
    kinds = {row["issue_type"] for row in issues.json()["items"]}
    assert "PROJECTION_PREVIEW_DRIFT" in kinds
    assert "PROJECTION_DRIFT" not in kinds
    preview = next(
        row for row in issues.json()["items"]
        if row["issue_type"] == "PROJECTION_PREVIEW_DRIFT"
    )
    assert preview["details"]["expected_labels"] == ["fire"]
    assert preview["details"]["projected_labels"] == ["fire_old"]
    assert any(
        group["issue_type"] == "PROJECTION_PREVIEW_DRIFT"
        and group["image_count"] == 1
        for group in issues.json()["groups"]
    )

    task = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/"
        f"{audit.json()['task_id']}/projection-repairs"
    )
    assert task.status_code == 202, task.text
    assert task.json()["still_requires_repair"] == 1
    assert task.json()["operation"] == "REPAIR_ANNOTATION_PROJECTIONS"
    with closing(BatchSelection(
        artifacts.artifact_path(task.json()["task_id"], "selection.sqlite3")
    )) as manifest:
        rows = manifest.database.execute(
            "SELECT image_id,tombstone_json FROM selection"
        ).fetchall()
        assert len(rows) == 1
        assert rows[0]["image_id"] == image["id"]
        assert json.loads(rows[0]["tombstone_json"])["expected_digest"] == before["content_digest"]
    assert scheduler.run_once() is True
    final = client.get(
        f"/api/v62/projects/{project_id}/material-batches/{task.json()['task_id']}"
    )
    assert final.status_code == 200, final.text
    assert final.json()["status"] == "SUCCEEDED"
    assert final.json()["changed_images"] == 1
    assert final.json()["failed"] == 0
    assert materials.get(image["id"])["annotation_preview"] == correct["annotation_preview"]
    after = annotations.get(image["id"])
    assert after["version"] == before["version"]
    assert after["content_digest"] == before["content_digest"]
    assert after["boxes"] == before["boxes"]

    follow_up = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    ).json()
    assert scheduler.run_once() is True
    clean = client.get(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/"
        f"{follow_up['task_id']}/issues"
    ).json()
    assert not any(
        item["issue_type"] == "PROJECTION_PREVIEW_DRIFT"
        for item in clean["items"]
    )
    replay = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/"
        f"{audit.json()['task_id']}/projection-repairs"
    )
    assert replay.status_code == 202, replay.text
    assert replay.json()["still_requires_repair"] == 0
    assert replay.json()["already_resolved"] == 1
    assert scheduler.run_once() is True


def test_preview_repair_fails_closed_if_formal_gt_changes_after_freeze(
    client, seeded_project, tmp_path, monkeypatch,
):
    project_id, image = seeded_project
    annotations = AnnotationRepository(app_module.project_dir(project_id))
    materials = app_module.material_store(project_id)
    annotations.upsert(
        image["id"],
        [{"label": "fire", "class_id": 0}],
        annotation_state="annotated", annotation_scope=["fire"],
    )
    original_preview = materials.get(image["id"])["annotation_preview"]
    materials.patch({
        image["id"]: {
            "annotation_preview": [{**original_preview[0], "label": "old_fire"}],
        },
    })
    _repository, _artifacts, scheduler = _isolated_runtime(tmp_path, monkeypatch)
    audit = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits"
    ).json()
    assert scheduler.run_once() is True
    queued = client.post(
        f"/api/v54/projects/{project_id}/labels/integrity/audits/"
        f"{audit['task_id']}/projection-repairs"
    )
    assert queued.status_code == 202, queued.text

    new_truth = annotations.upsert(
        image["id"],
        [{"label": "smoke", "class_id": 1}],
        annotation_state="annotated", annotation_scope=["smoke"],
    )
    assert scheduler.run_once() is True
    outcome = client.get(
        f"/api/v62/projects/{project_id}/material-batches/"
        f"{queued.json()['task_id']}"
    ).json()
    assert outcome["status"] == "FAILED"
    assert outcome["failed"] == 1
    assert "ANNOTATION_CHANGED_DURING_PROJECTION_REPAIR" in str(outcome)
    assert annotations.get(image["id"])["version"] == new_truth["version"]
    assert materials.get(image["id"])["annotation_preview"][0]["label"] == "smoke"


def test_projection_repair_rejects_generic_batch_creation(
    client, seeded_project,
):
    project_id, _image = seeded_project
    response = client.post(
        f"/api/v62/projects/{project_id}/material-batches",
        json={
            "operation": "REPAIR_ANNOTATION_PROJECTIONS",
            "selection_spec": {"scope": "FILTERED", "filters": {}},
        },
    )
    assert response.status_code == 422
    assert "LABEL_PREVIEW_REPAIR_DEDICATED_PREPARE_REQUIRED" in response.text
