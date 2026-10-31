from __future__ import annotations

import json
import time

import pytest

import platform_core.training_compatibility as compatibility_module
from platform_core.training_compatibility import (
    TrainingCompatibilityResult,
    compatibility_page,
    evaluate_training_compatibility_projection,
)


@pytest.mark.parametrize("selection_size", (1_000, 10_000, 20_000))
def test_compatibility_page_switch_reuses_evaluation_and_bounds_response(
    tmp_path,
    monkeypatch,
    record_property,
    selection_size,
):
    """Lightweight scale check: page switches never repeat canonical IO work."""
    project = tmp_path / "project"
    project.mkdir()
    calls = 0
    issues = tuple(
        {
            "image_id": f"material-{index:05d}",
            "filename": f"material-{index:05d}.jpg",
            "issue_type": "missing_annotation_scope",
            "missing_label_codes": ["person"],
        }
        for index in range(selection_size)
    )

    def fake_evaluate(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return TrainingCompatibilityResult(
            label_contract={"effective_label_codes": ["person"]},
            issues=issues,
            material_revision=7,
            annotation_revision=11,
            selection_truth={"selected_count": selection_size},
        )

    monkeypatch.setattr(
        compatibility_module,
        "evaluate_training_compatibility",
        fake_evaluate,
    )
    monkeypatch.setattr(
        compatibility_module.MaterialRepository,
        "current_revision",
        lambda _self: 7,
    )
    monkeypatch.setattr(
        compatibility_module.AnnotationRepository,
        "current_revision",
        lambda _self: 11,
    )
    compatibility_module._evaluate_training_compatibility_projection_cached.cache_clear()
    payload = {
        "algorithm_asset_id": "algorithm-1",
        "image_ids": [f"material-{index:05d}" for index in range(selection_size)],
        "train_labels": ["person"],
    }

    started = time.perf_counter()
    first_result = evaluate_training_compatibility_projection(
        tmp_path,
        project,
        {**payload, "page": 1, "page_size": 50},
        {"id": "algorithm-1", "framework": "ultralytics"},
    )
    first_page = compatibility_page(first_result, page=1, page_size=50)
    last_page_number = max(1, selection_size // 50)
    second_result = evaluate_training_compatibility_projection(
        tmp_path,
        project,
        {**payload, "page": last_page_number, "page_size": 50},
        {"id": "algorithm-1", "framework": "ultralytics"},
    )
    last_page = compatibility_page(
        second_result,
        page=last_page_number,
        page_size=50,
    )
    elapsed = time.perf_counter() - started

    assert calls == 1
    assert first_result is second_result
    assert len(first_page["items"]) == 50
    assert len(last_page["items"]) == 50
    assert first_page["total"] == selection_size
    assert last_page["total_pages"] == selection_size // 50
    assert len(json.dumps(last_page, ensure_ascii=False)) < 20_000
    record_property(
        f"compatibility_{selection_size}_two_page_seconds",
        round(elapsed, 6),
    )


def test_task_negative_receipt_invalidates_cached_compatibility(tmp_path, monkeypatch):
    """Final preflight after task evidence must not reuse pre-confirmation issues."""
    project = tmp_path / "project"
    project.mkdir()
    calls = 0
    receipt_revision = 0

    def fake_evaluate(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return TrainingCompatibilityResult(
            label_contract={"effective_label_codes": ["person"]},
            issues=({"image_id": "image-1", "issue_type": "partial_review_scope"},)
            if receipt_revision == 0 else (),
            material_revision=7,
            annotation_revision=11,
            selection_truth={"selected_count": 2},
        )

    monkeypatch.setattr(compatibility_module, "evaluate_training_compatibility", fake_evaluate)
    monkeypatch.setattr(compatibility_module.MaterialRepository, "current_revision", lambda _self: 7)
    monkeypatch.setattr(compatibility_module.AnnotationRepository, "current_revision", lambda _self: 11)
    monkeypatch.setattr(compatibility_module.AnnotationRepository,
                        "task_negative_confirmation_revision", lambda _self: receipt_revision)
    compatibility_module._evaluate_training_compatibility_projection_cached.cache_clear()
    payload = {"algorithm_asset_id": "algorithm-1", "image_ids": ["image-1", "image-2"],
               "train_labels": ["person"]}
    algorithm = {"id": "algorithm-1", "framework": "ultralytics"}

    before = evaluate_training_compatibility_projection(tmp_path, project, payload, algorithm)
    receipt_revision = 1
    after = evaluate_training_compatibility_projection(tmp_path, project, payload, algorithm)
    repeated = evaluate_training_compatibility_projection(tmp_path, project, payload, algorithm)

    assert len(before.issues) == 1
    assert after.issues == ()
    assert after is repeated
    assert before is not after
    assert calls == 2
