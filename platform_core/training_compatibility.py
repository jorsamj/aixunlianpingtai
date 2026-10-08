"""Task-specific training/annotation compatibility without a second truth owner."""
from __future__ import annotations

import json
import hashlib
import math
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

from .annotation_repository import AnnotationRepository
from .material_repository import (
    DATASET_DELETE_CLAIM_FIELD,
    MATERIAL_BATCH_DELETE_CLAIM_FIELD,
    MaterialRepository,
)
from .training_label_tasks import (
    resolve_training_label_contract,
    training_material_scope_issue,
)
from .training_splits import SplitMode, SplitRequest
from .training_tasks import resolve_training_selection


@dataclass(frozen=True)
class TrainingCompatibilityResult:
    label_contract: dict[str, Any]
    issues: tuple[dict[str, Any], ...]
    material_revision: int
    annotation_revision: int
    selection_truth: dict[str, Any]

    def summary(self) -> dict[str, Any]:
        counts = Counter(str(item.get("issue_type") or "unknown") for item in self.issues)
        return {
            "compatible": not self.issues,
            "issue_count": len(self.issues),
            "issue_counts": dict(sorted(counts.items())),
            "effective_label_codes": list(
                self.label_contract.get("effective_label_codes") or []
            ),
            "material_revision": self.material_revision,
            "annotation_revision": self.annotation_revision,
            "selection_truth": dict(self.selection_truth),
        }


def _split_request(payload: Mapping[str, Any]) -> SplitRequest:
    train_ids = payload.get("train_image_ids")
    if train_ids is None:
        train_ids = payload.get("image_ids") or []
    mode = SplitMode(str(
        payload.get("split_mode") or SplitMode.RANDOM_TEST_FROM_TRAINING_POOL.value
    ))
    return SplitRequest(
        mode=mode,
        train_image_ids=tuple(str(value) for value in train_ids if str(value)),
        test_image_ids=tuple(
            str(value) for value in (payload.get("test_image_ids") or []) if str(value)
        ),
        experiment_percent=(
            None
            if mode is SplitMode.INDEPENDENT_TEST_SET
            else payload.get("experiment_percent", 20)
        ),
        validation_percent=float(payload.get("validation_percent") or 20),
    )


def _dataset_names(project: Path) -> dict[str, str]:
    path = project / "datasets.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else []
    except (OSError, ValueError):
        value = []
    rows = value.get("items") if isinstance(value, Mapping) else value
    return {
        str(row.get("id") or ""): str(row.get("name") or row.get("id") or "")
        for row in (rows or []) if isinstance(row, Mapping) and row.get("id")
    }


def _issue_for_row(
    row: Mapping[str, Any],
    contract: Mapping[str, Any],
    dataset_names: Mapping[str, str],
) -> dict[str, Any] | None:
    image_id = str(row.get("id") or row.get("image_id") or "")
    required = list(contract.get("effective_label_codes") or [])
    if (
        row.get(DATASET_DELETE_CLAIM_FIELD)
        or row.get(MATERIAL_BATCH_DELETE_CLAIM_FIELD)
    ):
        issue = {
            "image_id": image_id,
            "issue_type": "material_unavailable",
            "annotation_state": str(row.get("annotation_state") or "unannotated"),
            "annotation_scope": list(row.get("annotation_scope") or []),
            "required_label_codes": required,
            "missing_label_codes": required,
        }
    elif row.get("source_available") is False:
        issue = {
            "image_id": image_id,
            "issue_type": "material_unavailable",
            "annotation_state": str(row.get("annotation_state") or "unannotated"),
            "annotation_scope": list(row.get("annotation_scope") or []),
            "required_label_codes": required,
            "missing_label_codes": required,
        }
    elif row.get("annotation_needs_review") or row.get("needs_review"):
        issue = {
            "image_id": image_id,
            "issue_type": "stale_ground_truth",
            "annotation_state": str(row.get("annotation_state") or "unannotated"),
            "annotation_scope": list(row.get("annotation_scope") or []),
            "required_label_codes": required,
            "missing_label_codes": required,
        }
    else:
        source_sha = str(row.get("annotation_source_content_sha256") or "").lower()
        current_sha = str(row.get("content_sha256") or "").lower()
        if source_sha and current_sha and source_sha != current_sha:
            issue = {
                "image_id": image_id,
                "issue_type": "stale_ground_truth",
                "annotation_state": str(row.get("annotation_state") or "unannotated"),
                "annotation_scope": list(row.get("annotation_scope") or []),
                "required_label_codes": required,
                "missing_label_codes": required,
            }
        else:
            issue = training_material_scope_issue(row, contract)
    if issue is None:
        return None
    dataset_id = str(row.get("dataset_id") or "")
    return {
        **issue,
        "filename": str(row.get("filename") or image_id),
        "dataset_id": dataset_id,
        "dataset_name": str(dataset_names.get(dataset_id) or dataset_id),
        "annotation_version": int(row.get("annotation_version") or row.get("version") or 0),
        "annotation_hash": str(
            row.get("annotation_hash") or row.get("content_digest") or ""
        ),
        "content_sha256": str(row.get("content_sha256") or ""),
        "annotation_review_reason": str(row.get("annotation_review_reason") or ""),
    }


def evaluate_training_compatibility(
    data_dir: str | Path,
    project: str | Path,
    payload: Mapping[str, Any],
    algorithm: Mapping[str, Any],
) -> TrainingCompatibilityResult:
    project_path = Path(project).resolve()
    split = _split_request(payload)
    selection = resolve_training_selection(project_path, split)
    effective = selection.effective_split
    contract_payload = {
        **dict(payload),
        "train_image_ids": list(effective.train_image_ids),
        "test_image_ids": list(effective.test_image_ids),
        "selected_image_ids": list(effective.train_image_ids),
    }
    contract = resolve_training_label_contract(
        data_dir, project_path, contract_payload, algorithm,
    )
    return evaluate_selection_compatibility(project_path, selection, contract)


_COMPATIBILITY_PAGE_FIELDS = frozenset({
    "cursor",
    "issue_type",
    "limit",
    "page",
    "page_size",
    "query",
})


def _canonical_json(value: Mapping[str, Any]) -> str:
    return json.dumps(
        dict(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _file_digest(path: Path) -> str:
    try:
        content = path.read_bytes()
    except FileNotFoundError:
        content = b""
    return hashlib.sha256(content).hexdigest()


@lru_cache(maxsize=8)
def _evaluate_training_compatibility_projection_cached(
    data_dir: str,
    project: str,
    request_json: str,
    algorithm_json: str,
    material_revision: int,
    annotation_revision: int,
    label_schema_digest: str,
    dataset_digest: str,
) -> TrainingCompatibilityResult:
    """Memoize only a revision-complete, disposable read projection.

    Revision and file digests are intentionally part of the key even though
    the evaluator reads the repositories itself.  They make cached values
    impossible to reuse after canonical Material, Annotation, label-schema or
    dataset display metadata changes.  Final training admission never calls
    this helper.
    """
    del material_revision, annotation_revision, label_schema_digest, dataset_digest
    return evaluate_training_compatibility(
        Path(data_dir),
        Path(project),
        json.loads(request_json),
        json.loads(algorithm_json),
    )


def evaluate_training_compatibility_projection(
    data_dir: str | Path,
    project: str | Path,
    payload: Mapping[str, Any],
    algorithm: Mapping[str, Any],
) -> TrainingCompatibilityResult:
    """Return a bounded cached UI projection keyed by every canonical revision."""
    project_path = Path(project).resolve()
    request = {
        str(key): value
        for key, value in dict(payload).items()
        if str(key) not in _COMPATIBILITY_PAGE_FIELDS
    }
    materials = MaterialRepository(project_path)
    annotations = AnnotationRepository(project_path)
    return _evaluate_training_compatibility_projection_cached(
        str(Path(data_dir).resolve()),
        str(project_path),
        _canonical_json(request),
        _canonical_json(algorithm),
        int(materials.current_revision()),
        int(annotations.current_revision()),
        _file_digest(project_path / "meta.json"),
        _file_digest(project_path / "datasets.json"),
    )


def evaluate_selection_compatibility(
    project: str | Path,
    selection,
    contract: Mapping[str, Any],
) -> TrainingCompatibilityResult:
    """Evaluate an already-resolved selection/label contract without re-resolving owners."""
    project_path = Path(project).resolve()
    effective = selection.effective_split
    names = _dataset_names(project_path)
    by_id = {
        str(row.get("id") or ""): dict(row)
        for row in selection.effective_images
    }
    pending_ids = list(selection.pending_annotation_image_ids)
    materials = MaterialRepository(project_path)
    annotations = AnnotationRepository(project_path)
    for offset in range(0, len(pending_ids), 500):
        chunk = pending_ids[offset:offset + 500]
        material_rows = {
            str(row.get("id") or ""): dict(row)
            for row in materials.get_many(chunk)
        }
        annotation_rows = annotations.get_many(chunk)
        for image_id in chunk:
            row = material_rows.get(image_id, {"id": image_id})
            annotation = annotation_rows.get(image_id) or {}
            row.update({
                "annotation_state": annotation.get("annotation_state") or "unannotated",
                "annotation_scope": list(annotation.get("annotation_scope") or []),
                "annotation_version": int(annotation.get("version") or 0),
                "annotation_hash": str(annotation.get("content_digest") or ""),
                "boxes": list(annotation.get("boxes") or []),
            })
            by_id[image_id] = row

    issues = tuple(
        issue
        for image_id in (*selection.selected_train_image_ids, *effective.test_image_ids)
        if (issue := _issue_for_row(by_id[image_id], contract, names)) is not None
    )
    return TrainingCompatibilityResult(
        label_contract=dict(contract),
        issues=issues,
        material_revision=materials.current_revision(),
        annotation_revision=annotations.current_revision(),
        selection_truth=selection.truth(),
    )


def compatibility_page(
    result: TrainingCompatibilityResult,
    *,
    query: str = "",
    issue_type: str = "",
    cursor: str = "",
    limit: int = 50,
    page: int | None = None,
    page_size: int | None = None,
) -> dict[str, Any]:
    normalized_query = str(query or "").strip().casefold()
    normalized_type = str(issue_type or "").strip()
    filtered = [
        item for item in result.issues
        if (not normalized_type or item["issue_type"] == normalized_type)
        and (
            not normalized_query
            or normalized_query in str(item.get("image_id") or "").casefold()
            or normalized_query in str(item.get("filename") or "").casefold()
        )
    ]
    bounded = int(page_size if page_size is not None else limit)
    if not 1 <= bounded <= 100:
        raise ValueError("page_size must be between 1 and 100")
    total = len(filtered)
    total_pages = max(1, math.ceil(total / bounded))
    if page is not None:
        try:
            page_number = int(page)
        except (TypeError, ValueError) as error:
            raise ValueError("page must be a positive integer") from error
        if page_number < 1:
            raise ValueError("page must be a positive integer")
        if page_number > total_pages:
            raise ValueError(
                f"page {page_number} exceeds total_pages {total_pages}"
            )
        offset = (page_number - 1) * bounded
    else:
        try:
            offset = int(cursor or 0)
        except (TypeError, ValueError) as error:
            raise ValueError("cursor must be a non-negative integer offset") from error
        if offset < 0:
            raise ValueError("cursor must be a non-negative integer offset")
        page_number = offset // bounded + 1
    items = filtered[offset:offset + bounded]
    next_cursor = str(offset + len(items)) if offset + len(items) < total else None
    return {
        "items": [dict(item) for item in items],
        "filtered_count": total,
        "total": total,
        "page": page_number,
        "page_size": bounded,
        "total_pages": total_pages,
        "has_previous": offset > 0,
        "has_next": next_cursor is not None,
        "next_cursor": next_cursor,
    }


def persist_compatibility_issues(
    artifacts,
    task_id: str,
    result: TrainingCompatibilityResult,
    *,
    page_size: int = 100,
) -> dict[str, Any]:
    bounded_page_size = max(1, min(100, int(page_size)))
    pages = []
    for offset in range(0, len(result.issues), bounded_page_size):
        page_number = offset // bounded_page_size + 1
        ref = f"input-compatibility/pages/{page_number:06d}.json"
        artifacts.atomic_write_json(
            task_id,
            ref,
            list(result.issues[offset:offset + bounded_page_size]),
        )
        pages.append({"page": page_number, "ref": ref})
    manifest = {
        "schema_version": 1,
        "issue_count": len(result.issues),
        "issue_counts": result.summary()["issue_counts"],
        "required_label_codes": list(
            result.label_contract.get("effective_label_codes") or []
        ),
        "material_revision": result.material_revision,
        "annotation_revision": result.annotation_revision,
        "page_size": bounded_page_size,
        "pages": pages,
    }
    artifacts.atomic_write_json(
        task_id,
        "input-compatibility/manifest.json",
        manifest,
    )
    return manifest


__all__ = [
    "TrainingCompatibilityResult",
    "compatibility_page",
    "evaluate_selection_compatibility",
    "evaluate_training_compatibility",
    "evaluate_training_compatibility_projection",
    "persist_compatibility_issues",
]
