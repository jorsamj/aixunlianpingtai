from __future__ import annotations

import json
import math
import time

import pytest

import platform_core.training_compatibility as compatibility_module
from platform_core.training_compatibility import (
    TrainingCompatibilityResult,
    compatibility_page,
    evaluate_training_compatibility_projection,
    resolve_training_compatibility_selection,
)


@pytest.mark.parametrize("selection_size", (1_000, 10_000, 20_000, 21_163))
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
    last_page_number = max(1, math.ceil(selection_size / 50))
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
    assert len(last_page["items"]) == selection_size - 50 * (last_page_number - 1)
    assert first_page["total"] == selection_size
    assert last_page["total_pages"] == last_page_number
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


def test_missing_label_filter_pages_and_freezes_exact_cross_page_selection():
    """Per-label bulk review must never sweep other labels or duplicate conflicts."""
    issues = (
        {"image_id": "a", "issue_type": "partial_review_scope", "missing_label_codes": ["fire"]},
        {"image_id": "b", "issue_type": "partial_review_scope", "missing_label_codes": ["smoke"]},
        {"image_id": "c", "issue_type": "partial_review_scope", "missing_label_codes": ["fire", "smoke"]},
        {"image_id": "d", "issue_type": "duplicate_annotation_conflict", "missing_label_codes": []},
    )
    truth = TrainingCompatibilityResult(
        label_contract={"effective_label_codes": ["fire", "smoke"]},
        issues=issues, material_revision=5, annotation_revision=8,
        selection_truth={"selected_count": 4},
    )

    first = compatibility_page(truth, missing_label_code="fire", page=1, page_size=1)
    second = compatibility_page(truth, missing_label_code="fire", page=2, page_size=1)
    assert [row["image_id"] for row in first["items"]] == ["a"]
    assert [row["image_id"] for row in second["items"]] == ["c"]
    assert first["filtered_affected_image_count"] == 2
    payload = {
        "expected_material_revision": 5, "expected_annotation_revision": 8,
        "selection": {
            "all_filtered": True, "missing_label_code": "fire", "excluded_image_ids": ["a"],
        },
    }
    chosen = resolve_training_compatibility_selection(truth, payload)
    assert chosen["matching_image_ids"] == ["c"]
    assert chosen["selected_count"] == 1
    assert compatibility_page(truth, missing_label_code="Fire", page=1)["filtered_count"] == 0
    all_issues = resolve_training_compatibility_selection(truth, {
        **payload, "selection": {"all_issues": True, "missing_label_code": "fire"},
    })
    assert all_issues["matching_image_ids"] == ["a", "b", "c", "d"]
    with pytest.raises(ValueError, match="TRAINING_SELECTION_CHANGED"):
        resolve_training_compatibility_selection(truth, {
            **payload,
            "selection": {"image_ids": ["b"], "missing_label_code": "fire"},
        })
    with pytest.raises(ValueError, match="TRAINING_SELECTION_STALE"):
        resolve_training_compatibility_selection(truth, {
            **payload, "expected_annotation_revision": 7,
        })


def test_21163_missing_scope_filter_returns_only_ids_of_selected_label():
    size = 21_163
    truth = TrainingCompatibilityResult(
        label_contract={"effective_label_codes": ["fire", "smoke"]},
        issues=tuple({
            "image_id": f"synthetic-{index:05d}",
            "issue_type": "partial_review_scope",
            "missing_label_codes": ["fire"] if index % 2 else ["smoke"],
        } for index in range(size)),
        material_revision=7, annotation_revision=10,
        selection_truth={"selected_count": size},
    )
    page = compatibility_page(truth, missing_label_code="fire", page=1, page_size=50)
    assert page["filtered_affected_image_count"] == size // 2
    assert len(page["items"]) == 50
    selection = resolve_training_compatibility_selection(truth, {
        "expected_material_revision": 7, "expected_annotation_revision": 10,
        "selection": {"all_filtered": True, "missing_label_code": "fire"},
    })
    assert selection["selected_count"] == size // 2
    assert all(int(image_id.rsplit("-", 1)[-1]) % 2 for image_id in selection["matching_image_ids"])
