"""Focused evidence for the remaining O(N) material call chains.

These tests are small deterministic fixtures, not production benchmarks.  They
prove three things for every path they cover:

1. the implemented path returns exactly the historical result (the previous
   algorithm is executed side by side on a byte-identical project copy);
2. where the contract is a catalog-free read (v12/v20/video), the canonical
   full-catalog ``MaterialRepository.read()`` is never called and formal GT is
   read through bounded ``get_many`` batches only (v44 still needs its existing
   full catalog snapshot, but no longer opens the GT owner once per image);
3. the revision / formal-GT owners still own their state (revision +1 only when
   a row actually changed, annotation versions and payload digests untouched).
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from types import SimpleNamespace

import pytest

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_governance_contracts import (
    BatchImageSplitReq,
    BatchSplitReq,
)
from platform_core.material_governance_service import (
    MaterialGovernanceDependencies,
    MaterialGovernanceService,
)
from platform_core.material_repository import MaterialRepository
from platform_core.video_tasks import VideoFrameHandler

NOW = "2026-11-26T00:00:00+00:00"
CREATED_AT = "2026-01-01T00:00:00+00:00"
BOX = {"class_id": 0, "label": "fire", "x1": 1, "y1": 1, "x2": 10, "y2": 10}


def _box(label: str = "fire") -> dict:
    return {**BOX, "label": label}


def _forbidden(name: str):
    def fail(*_args, **_kwargs):
        raise AssertionError(f"hot path must not call {name}")
    return fail


def _material(image_id: str, dataset: object = "dsA", split: str = "unassigned") -> dict:
    row = {
        "id": image_id,
        "filename": f"{image_id}.jpg",
        "object_key": f"uploads/{image_id}.jpg",
        "created_at": CREATED_AT,
        "split": split,
    }
    if dataset is not ...:
        row["dataset_id"] = dataset
    return row


def _seed(root: Path, rows: list[dict], annotations: dict[str, list[dict]] | None = None) -> Path:
    repository = MaterialRepository(root)
    repository.upsert_many(rows)
    annotations = annotations or {}
    if annotations:
        AnnotationRepository(root).upsert_many(
            [
                {"image_id": image_id, "boxes": boxes}
                for image_id, boxes in annotations.items()
            ],
            project_material=False,
        )
    for name in ("materials.sqlite3", "annotations.sqlite3"):
        database = root / name
        if database.is_file():
            with sqlite3.connect(str(database)) as connection:
                connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    return root


def _clone(template: Path, *targets: Path) -> list[Path]:
    copies = []
    for target in targets:
        shutil.copytree(
            template, target,
            ignore=shutil.ignore_patterns("*-wal", "*-shm"),
        )
        copies.append(target)
    return copies


def _payloads(repository: MaterialRepository) -> dict[str, str]:
    with sqlite3.connect(str(repository.path)) as database:
        return {
            str(row[0]): str(row[1])
            for row in database.execute("SELECT id, payload_json FROM materials")
        }


def _annotations_state(project_path: Path, image_ids: list[str]) -> dict[str, tuple[int, str]]:
    repository = AnnotationRepository(project_path)
    state = {}
    for offset in range(0, len(image_ids), 500):
        for image_id, record in repository.get_many(image_ids[offset:offset + 500]).items():
            state[image_id] = (int(record.get("version") or 0), str(record.get("content_digest") or ""))
    return state


def _service(
    repository: MaterialRepository,
    project_path: Path,
    *,
    load_images=None,
    read_annotation=None,
    read_annotations_many=None,
    read_json=None,
    write_job_json=None,
) -> MaterialGovernanceService:
    return MaterialGovernanceService(MaterialGovernanceDependencies(
        _V50DatasetSourceChanged=RuntimeError,
        _require_material_delete_preview=lambda *args, **kwargs: None,
        _v50_assert_dataset_writable_locked=lambda *args, **kwargs: None,
        _v50_dataset_locks=lambda *args, **kwargs: [],
        get_project=lambda project_id: {"id": project_id, "labels": []},
        load_images=load_images or (lambda *args, **kwargs: _forbidden("load_images")()),
        material_store=lambda project_id: repository,
        now_iso=lambda: NOW,
        project_dir=lambda project_id: project_path,
        read_annotation=read_annotation or (lambda *args, **kwargs: _forbidden("read_annotation")()),
    ))


def _legacy_v12(
    repository: MaterialRepository,
    project_path: Path,
    dataset_id: str,
    payload: BatchSplitReq,
):
    """The exact pre-remediation algorithm, kept as the equivalence oracle."""
    annotation_presence: dict[str, bool] = {}
    if not payload.include_unannotated:
        annotations = AnnotationRepository(project_path)
        for image in repository.read().rows:
            image_id = str(image.get("id"))
            annotation_presence[image_id] = bool(annotations.get(image_id).get("boxes"))

    def apply_auto_split(rows):
        images = [
            image
            for image in rows
            if image.get("dataset_id", "default") == dataset_id
            and (
                payload.include_unannotated
                or annotation_presence.get(str(image.get("id")), False)
            )
        ]
        if not images:
            raise ValueError("no images")
        images.sort(key=lambda image: str(image.get("id", "")))
        total = len(images)
        train_n = max(1, int(total * payload.train))
        val_n = max(0, int(total * payload.val))
        if train_n + val_n > total:
            val_n = max(0, total - train_n)
        counts = {"train": 0, "val": 0, "test": 0}
        for index, image in enumerate(images):
            if index < train_n:
                split = "train"
            elif index < train_n + val_n:
                split = "val"
            else:
                split = "test"
            image["split"] = split
            counts[split] += 1
        return counts

    return repository.mutate(apply_auto_split)


def _legacy_v20_filtered(
    repository: MaterialRepository,
    project_path: Path,
    payload: BatchImageSplitReq,
):
    dataset_id = payload.dataset_id or None
    filt = (payload.filter or "all").lower()
    split = (payload.split or "unassigned").lower()
    box_counts: dict[str, int] = {}
    if filt in {"marked", "unmarked"}:
        images = repository.read().rows
        image_ids = [str(image.get("id") or "") for image in images if str(image.get("id") or "")]
        annotations = AnnotationRepository(project_path)
        for offset in range(0, len(image_ids), 500):
            batch = image_ids[offset:offset + 500]
            for image_id, annotation in annotations.get_many(batch).items():
                box_counts[str(image_id)] = len(annotation.get("boxes", []))

    def match_latest(image):
        from platform_core.material_repository import material_dataset_matches
        if not material_dataset_matches(image, dataset_id):
            return False
        image_id = str(image.get("id"))
        current_split = (image.get("split") or "unassigned").lower()
        if filt == "marked":
            count = box_counts.get(image_id)
            return count is not None and count > 0
        if filt == "unmarked":
            count = box_counts.get(image_id)
            return count is not None and count == 0
        if filt in {"train", "val", "test", "unassigned"}:
            return current_split == filt
        return True

    def apply_split(rows):
        changed = 0
        for image in rows:
            if not match_latest(image):
                continue
            image["split"] = split
            image["updated_at"] = NOW
            changed += 1
        if not changed:
            raise ValueError("no matching material")
        return changed

    return repository.mutate(apply_split)


# ---------------------------------------------------------------------------
# v12_auto_split
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("include_unannotated", [True, False])
def test_v12_auto_split_matches_legacy_selection_without_catalog_read(
    tmp_path, monkeypatch, include_unannotated
):
    rows = [_material(f"a-{index:04d}", "dsA") for index in range(1201)]
    rows += [
        _material("d-missing", ...),
        _material("d-null", None),
        _material("d-empty", ""),
        _material("d-zero", 0),
        _material("d-false", False),
        _material("d-string-zero", "0"),
        _material("d-real", "default"),
        _material("b-1", "dsB"),
    ]
    annotated = {
        image["id"]: [_box()]
        for index, image in enumerate(rows[:1201])
        if index % 3 == 0
    }
    template = _seed(tmp_path / "template", rows, annotated)
    legacy_root, hot_root = _clone(template, tmp_path / "legacy", tmp_path / "hot")
    legacy_repository = MaterialRepository(legacy_root)
    hot_repository = MaterialRepository(hot_root)
    payload = BatchSplitReq(train=0.5, val=0.25, test=0.25, include_unannotated=include_unannotated)
    expected = _legacy_v12(legacy_repository, legacy_root, "dsA", payload)
    legacy_payloads = _payloads(legacy_repository)
    legacy_revision = legacy_repository.current_revision()
    annotation_ids = list(annotated)
    legacy_annotations = _annotations_state(hot_root, annotation_ids)

    batches: list[int] = []
    real_get_many = AnnotationRepository.get_many

    def spy_get_many(self, image_ids):
        ids = list(image_ids)
        batches.append(len(ids))
        assert len(ids) <= 500
        return real_get_many(self, ids)

    monkeypatch.setattr(AnnotationRepository, "get_many", spy_get_many)
    monkeypatch.setattr(AnnotationRepository, "get", _forbidden("AnnotationRepository.get"))
    monkeypatch.setattr(MaterialRepository, "read", _forbidden("MaterialRepository.read"))

    service = _service(hot_repository, hot_root)
    result = service.v12_auto_split("project-1", "dsA", payload)

    assert result == {"ok": True, "counts": expected}
    assert _payloads(hot_repository) == legacy_payloads
    assert hot_repository.current_revision() == legacy_revision == 1 + 1
    # Formal GT is read through bounded batches only; no per-image repository
    # open is allowed and the batch size never exceeds the canonical 500 limit.
    if include_unannotated:
        assert batches == []
    else:
        assert batches == [500, 500, 209]
    assert _annotations_state(hot_root, annotation_ids) == legacy_annotations
    # Legacy default identities are still outside the exact "default" dataset,
    # matching the historical predicate rather than the wider canonical view.
    state = {row["id"]: row for row in hot_repository.get_many(["d-missing", "d-null", "d-empty", "d-zero", "d-false", "d-real"])}
    for image_id in ("d-null", "d-empty", "d-zero", "d-false"):
        assert state[image_id]["split"] == "unassigned"
        assert state[image_id]["updated_at"] == ""


def test_v12_auto_split_default_dataset_keeps_historical_strict_membership(tmp_path, monkeypatch):
    rows = [
        _material("d-missing", ...),
        _material("d-null", None),
        _material("d-empty", ""),
        _material("d-zero", 0),
        _material("d-string-zero", "0"),
        _material("d-real", "default"),
        _material("b-1", "dsB"),
    ]
    template = _seed(tmp_path / "template", rows)
    legacy_root, hot_root = _clone(template, tmp_path / "legacy", tmp_path / "hot")
    legacy_repository = MaterialRepository(legacy_root)
    hot_repository = MaterialRepository(hot_root)
    payload = BatchSplitReq(train=0.5, val=0.0, test=0.5, include_unannotated=True)
    expected = _legacy_v12(legacy_repository, legacy_root, "default", payload)
    legacy_payloads = _payloads(legacy_repository)

    monkeypatch.setattr(MaterialRepository, "read", _forbidden("MaterialRepository.read"))
    service = _service(hot_repository, hot_root)
    result = service.v12_auto_split("project-1", "default", payload)

    assert result == {"ok": True, "counts": expected}
    assert expected == {"train": 1, "val": 0, "test": 1}
    assert _payloads(hot_repository) == legacy_payloads

    from fastapi import HTTPException
    with pytest.raises(HTTPException) as missing:
        service.v12_auto_split("project-1", "missing-dataset", payload)
    assert missing.value.status_code == 400
    assert _payloads(hot_repository) == legacy_payloads


# ---------------------------------------------------------------------------
# v20_batch_image_split filtered scope
# ---------------------------------------------------------------------------


def test_v20_filtered_marked_split_is_dataset_scoped_and_result_equivalent(tmp_path, monkeypatch):
    rows = [_material(f"a-{index:03d}", "dsA") for index in range(20)]
    rows += [_material("b-1", "dsB"), _material("d-missing", ...)]
    annotations = {
        "a-000": [_box()],
        "a-001": [_box("smoke")],
        "a-003": [_box()],
        "b-1": [_box()],
    }
    template = _seed(tmp_path / "template", rows, annotations)
    legacy_root, hot_root = _clone(template, tmp_path / "legacy", tmp_path / "hot")
    legacy_repository = MaterialRepository(legacy_root)
    hot_repository = MaterialRepository(hot_root)
    payload = BatchImageSplitReq(
        split="train", dataset_id="dsA", filter="marked", scope="filtered",
    )
    expected = _legacy_v20_filtered(legacy_repository, legacy_root, payload)
    legacy_payloads = _payloads(legacy_repository)
    legacy_revision = legacy_repository.current_revision()

    batches: list[int] = []
    real_get_many = AnnotationRepository.get_many

    def spy_get_many(self, image_ids):
        ids = list(image_ids)
        batches.append(len(ids))
        assert len(ids) <= 500
        return real_get_many(self, ids)

    monkeypatch.setattr(AnnotationRepository, "get_many", spy_get_many)
    monkeypatch.setattr(MaterialRepository, "read", _forbidden("MaterialRepository.read"))
    monkeypatch.setattr(MaterialRepository, "mutate", _forbidden("MaterialRepository.mutate"))
    service = _service(hot_repository, hot_root)
    result = service.v20_batch_image_split("project-1", payload)

    assert result == {"ok": True, "changed": expected, "split": "train"}
    assert expected == 3
    assert _payloads(hot_repository) == legacy_payloads
    assert hot_repository.current_revision() == legacy_revision == 2
    assert batches == [len(rows)]
    state = {row["id"]: row for row in hot_repository.get_many(["a-000", "a-001", "a-003", "b-1"])}
    assert state["a-000"]["split"] == "train"
    assert state["a-003"]["split"] == "train"
    assert state["a-001"]["split"] == "train"
    assert state["b-1"]["split"] == "unassigned"


def test_v20_filtered_scope_without_dataset_keeps_atomic_full_transaction(tmp_path, monkeypatch):
    rows = [_material(f"a-{index:03d}", "dsA") for index in range(6)] + [
        _material("b-1", "dsB"),
    ]
    template = _seed(tmp_path / "template", rows)
    legacy_root, hot_root = _clone(template, tmp_path / "legacy", tmp_path / "hot")
    legacy_repository = MaterialRepository(legacy_root)
    hot_repository = MaterialRepository(hot_root)
    payload = BatchImageSplitReq(split="val", dataset_id=None, filter="unassigned", scope="filtered")
    expected = _legacy_v20_filtered(legacy_repository, legacy_root, payload)
    legacy_payloads = _payloads(legacy_repository)

    monkeypatch.setattr(MaterialRepository, "read", _forbidden("MaterialRepository.read"))
    service = _service(hot_repository, hot_root)
    result = service.v20_batch_image_split("project-1", payload)

    assert result == {"ok": True, "changed": expected, "split": "val"}
    assert _payloads(hot_repository) == legacy_payloads


# ---------------------------------------------------------------------------
# v44_supplement_training_data
# ---------------------------------------------------------------------------


def test_v44_supplement_reads_formal_gt_in_bounded_batches(tmp_path, monkeypatch):
    from platform_core.quality_analysis_service import (
        QualityAnalysisDependencies,
        QualityAnalysisService,
    )

    rows = [_material(f"u-{index:03d}", "default") for index in range(30)]
    rows += [_material("t-001", "default", split="train")]
    annotations = {
        "u-000": [_box("fire")],
        "u-002": [_box("fire")],
        "u-004": [_box("smoke")],
        "u-006": [_box("fire")],
        "u-008": [_box("fire")],
        "t-001": [_box("fire")],
    }
    template = _seed(tmp_path / "template", rows, annotations)
    legacy_root, hot_root = _clone(template, tmp_path / "legacy", tmp_path / "hot")
    legacy_repository = MaterialRepository(legacy_root)
    hot_repository = MaterialRepository(hot_root)
    weak = {"fire"}
    limit = 3

    legacy_annotations = AnnotationRepository(legacy_root)
    eligible = []
    for image in legacy_repository.read().rows:
        if (image.get("split") or "unassigned") != "unassigned":
            continue
        boxes = legacy_annotations.get(image["id"]).get("boxes", [])
        labels = {str(box.get("label") or "").strip() for box in boxes if str(box.get("label") or "").strip()}
        if labels & weak:
            eligible.append(str(image["id"]))
    eligible_set = set(eligible)
    legacy_changed: list[str] = []

    def apply_supplement(rows_in_transaction):
        for image in rows_in_transaction:
            if len(legacy_changed) >= limit:
                break
            if str(image.get("id")) not in eligible_set:
                continue
            if (image.get("split") or "unassigned") != "unassigned":
                continue
            image["split"] = "train"
            image["updated_at"] = NOW
            legacy_changed.append(str(image.get("id")))
        return legacy_changed

    expected = legacy_repository.mutate(apply_supplement)
    legacy_payloads = _payloads(legacy_repository)

    job_path = hot_root / "jobs" / "job-1" / "job.json"
    job_path.parent.mkdir(parents=True)
    job_path.write_text(json.dumps({
        "id": "job-1",
        "training_report": {"weak_labels": ["fire"]},
        "quality_gate": {"supplement_count": limit},
    }), encoding="utf-8")

    batches: list[int] = []
    real_get_many = AnnotationRepository.get_many

    def bounded_read(project_id, image_ids):
        ids = list(image_ids)
        assert len(ids) <= 500
        batches.append(len(ids))
        return real_get_many(AnnotationRepository(hot_root), ids)

    service = QualityAnalysisService(QualityAnalysisDependencies(
        MODEL_CONFIGS_FILE=lambda: Path(hot_root / "model_configs.json"),
        _training_success_rate_stats=lambda jobs: {"ended_count": 0, "success_rate": None, "success_count": 0, "failure_count": 0},
        _v35_call_model=_forbidden("_v35_call_model"),
        _v35_is_vision_provider=lambda config: False,
        _v35_items=lambda items: list(items),
        _v44_labels_in_ann=lambda ann: {
            str(box.get("label") or "").strip()
            for box in ann.get("boxes", [])
            if str(box.get("label") or "").strip()
        },
        _write_job_json=lambda path, value: Path(path).write_text(json.dumps(value), encoding="utf-8"),
        get_project=lambda project_id: {"id": project_id, "labels": []},
        list_algorithms_internal=lambda project_id: [],
        list_jobs=lambda project_id: [],
        load_images=lambda project_id: hot_repository.read().rows,
        material_store=lambda project_id: hot_repository,
        normalize_box_for_project=lambda *args, **kwargs: None,
        normalize_label=lambda value: str(value),
        now_iso=lambda: NOW,
        project_dir=lambda project_id: hot_root,
        read_annotation=_forbidden("read_annotation"),
        read_annotations_many=bounded_read,
        read_json=lambda path, default: json.loads(Path(path).read_text(encoding="utf-8")) if Path(path).is_file() else default,
        resolve_material_path=lambda *args, **kwargs: None,
        sync_jobs_index=lambda project_id: None,
        v35_test_model_config=_forbidden("v35_test_model_config"),
        v35_test_saved_model_annotation=_forbidden("v35_test_saved_model_annotation"),
    ))
    result = service.v44_supplement_training_data("project-1", "job-1")

    assert result["changed"] == len(expected) == limit
    assert _payloads(hot_repository) == legacy_payloads
    written_job = json.loads(job_path.read_text(encoding="utf-8"))
    assert written_job["supplemented_image_ids"] == expected
    # All 30 unassigned rows were inspected with one bounded batch, and the one
    # formal GT read never fell back to a per-image repository call.
    assert batches == [30]


# ---------------------------------------------------------------------------
# video_tasks.VideoFrameHandler._already_committed
# ---------------------------------------------------------------------------


def test_video_already_committed_reads_only_result_materials(tmp_path, monkeypatch):
    data_dir = (tmp_path / "data").resolve()
    project_dir = data_dir / "projects" / "project-1"
    uploads = project_dir / "uploads"
    uploads.mkdir(parents=True)
    bodies = {"m0": b"frame-zero", "m1": b"frame-one"}
    rows = []
    for image_id, body in bodies.items():
        (uploads / f"{image_id}.jpg").write_bytes(body)
        rows.append({
            "id": image_id,
            "filename": f"{image_id}.jpg",
            "object_key": f"uploads/{image_id}.jpg",
            "storage_source_id": "default_local",
            "storage_type": "local",
            "content_sha256": hashlib.sha256(body).hexdigest(),
            "size_bytes": len(body),
            "created_at": CREATED_AT,
            "dataset_id": "default",
            "split": "unassigned",
        })
    repository = MaterialRepository(project_dir)
    repository.upsert_many(rows)
    revision = repository.current_revision()
    result = {
        "materials": [
            {"image_id": image_id, "sha256": hashlib.sha256(body).hexdigest()}
            for image_id, body in bodies.items()
        ],
    }

    class Artifacts:
        def read_json(self, task_id, ref, default=None):
            return result if ref == "result.json" else default

    context = SimpleNamespace(
        task=SimpleNamespace(task_id="video-1", project_id="project-1"),
        artifacts=Artifacts(),
    )
    handler = VideoFrameHandler(data_dir)
    calls: list[list[str]] = []
    real_get_many = MaterialRepository.get_many

    def spy_get_many(self, image_ids):
        ids = list(image_ids)
        calls.append(ids)
        return real_get_many(self, ids)

    monkeypatch.setattr(MaterialRepository, "get_many", spy_get_many)
    monkeypatch.setattr(MaterialRepository, "read", _forbidden("MaterialRepository.read"))

    assert handler._already_committed(context) == "result.json"
    assert calls == [["m0", "m1"]]
    assert MaterialRepository(project_dir).current_revision() == revision

    # A missing result identity still fails closed without catalog hydration.
    result["materials"] = [{"image_id": "m-missing", "sha256": "0" * 64}]
    assert handler._already_committed(context) is None
    # A tampered frame digest still fails closed.
    result["materials"] = [{"image_id": "m0", "sha256": "0" * 64}]
    assert handler._already_committed(context) is None
    assert calls == [["m0", "m1"], ["m-missing"], ["m0"]]
