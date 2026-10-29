"""Task-specific training/annotation compatibility without a second truth owner."""
from __future__ import annotations

import json
import hashlib
import math
from collections import Counter
from dataclasses import dataclass, replace
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
from .training_splits import (
    SplitMode, SplitRequest, analyze_training_duplicates,
    exclude_reserved_test_components, training_annotation_digest,
)
from .training_tasks import resolve_training_selection, _selected_project_images


@dataclass(frozen=True)
class TrainingCompatibilityResult:
    label_contract: dict[str, Any]
    issues: tuple[dict[str, Any], ...]
    material_revision: int
    annotation_revision: int
    selection_truth: dict[str, Any]
    duplicate_review: dict[str, Any] | None = None

    def summary(self) -> dict[str, Any]:
        counts = Counter(str(item.get("issue_type") or "unknown") for item in self.issues)
        return {
            "compatible": not self.issues,
            "issue_count": len(self.issues),
            "affected_image_count": len({item["image_id"] for item in self.issues}),
            "duplicate_conflict_image_count": len({item["image_id"] for item in self.issues
                if item.get("issue_type") == "duplicate_annotation_conflict"}),
            "duplicate_conflict_group_count": len({item.get("content_sha256") for item in self.issues
                if item.get("issue_type") == "duplicate_annotation_conflict"}),
            "issue_counts": dict(sorted(counts.items())),
            "effective_label_codes": list(
                self.label_contract.get("effective_label_codes") or []
            ),
            "material_revision": self.material_revision,
            "annotation_revision": self.annotation_revision,
            "selection_truth": {key: value for key, value in self.selection_truth.items() if key.endswith("_count")},
            "selection_truth_ids_omitted": True,
            "duplicate_group_count": len({str(item.get("content_sha256")) for item in self.issues
                if item.get("issue_type") in {"duplicate_annotation_conflict", "content_hash_leakage"}}),
            "duplicate_review": ({"validated": True,
                "excluded_count": len(self.duplicate_review.get("excluded_image_ids") or [])}
                if self.duplicate_review else None),
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
            from .training_label_tasks import training_material_role
            issue = training_material_role(row, contract)["scope_issue"]
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
    review = validate_duplicate_review(project_path, payload, split)
    duplicates = diagnose_training_duplicates(project_path, payload)
    if duplicates.issues:
        return replace(duplicates, duplicate_review=review,
            label_contract={"effective_label_codes": list(payload.get("train_labels") or [])})
    # Selection intent needs the target labels, not a checkpoint byte digest.
    # The final verified contract below still hashes the selected best.pt once.
    intent_contract = resolve_training_label_contract(
        data_dir, project_path, payload, algorithm,
        require_positive_evidence=False, include_base_weight_digest=False,
    )
    selection = resolve_training_selection(project_path, split, label_contract=intent_contract)
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
    return replace(evaluate_selection_compatibility(project_path, selection, contract), duplicate_review=review)


def validate_duplicate_review(project: Path, payload: Mapping[str, Any], split: SplitRequest):
    """Validate an explicit adjustment of new input; never change canonical GT/history."""
    material_revision = MaterialRepository(project).current_revision()
    annotation_revision = AnnotationRepository(project).current_revision()
    expected_material = payload.get("expected_material_revision")
    expected_annotation = payload.get("expected_annotation_revision")
    if expected_material is not None or expected_annotation is not None:
        if (expected_material is None or expected_annotation is None
                or expected_material != material_revision or expected_annotation != annotation_revision):
            raise ValueError("TRAINING_REVIEW_STALE: material/annotation revision changed; repeat preflight")
    raw = payload.get("duplicate_review")
    if raw is None:
        return None
    if not isinstance(raw, Mapping):
        raise ValueError("duplicate review must be an object")
    if raw.get("material_revision") != material_revision or raw.get("annotation_revision") != annotation_revision:
        raise ValueError("TRAINING_REVIEW_STALE: duplicate review revision changed; repeat preflight")
    normalized_ids = {}
    for field in ("original_train_image_ids", "original_test_image_ids", "excluded_image_ids"):
        values = raw.get(field, [])
        if (not isinstance(values, list)
                or any(not isinstance(value, str) or not value.strip() or value != value.strip() for value in values)
                or len(set(values)) != len(values)):
            raise ValueError(f"duplicate review {field} must be an array of unique non-empty image ID strings")
        normalized_ids[field] = tuple(values)
    original_train = normalized_ids["original_train_image_ids"]
    original_test = normalized_ids["original_test_image_ids"]
    excluded = normalized_ids["excluded_image_ids"]
    if not original_train or set(original_train) & set(original_test):
        raise ValueError("duplicate review original selection has invalid roles")
    rows = _selected_project_images(MaterialRepository(project), project, (*original_train, *original_test))
    review_kind = raw.get("review_kind")
    if review_kind not in (None, "EXPLICIT_SELECTION_ADJUSTMENT"):
        raise ValueError("duplicate review kind is unsupported")
    if review_kind == "EXPLICIT_SELECTION_ADJUSTMENT":
        eligible = set(original_train) | set(original_test)
    else:
        groups = analyze_training_duplicates(rows, original_train, original_test)
        if any(group["issue_type"] == "content_hash_leakage" for group in groups):
            raise ValueError("content hash leakage: original review crosses train/test; exclusions cannot conceal leakage")
        eligible = {image_id for group in groups if group["issue_type"] == "duplicate_annotation_conflict"
                    for image_id in group["image_ids"]}
    if not excluded or not set(excluded) <= eligible:
        raise ValueError("duplicate review exclusion must identify eligible original selection members")
    if (tuple(value for value in original_train if value not in set(excluded)) != split.train_image_ids
            or tuple(value for value in original_test if value not in set(excluded)) != split.test_image_ids):
        raise ValueError("duplicate review exclusion does not match the final selection")
    return {"original_train_image_ids": list(original_train), "original_test_image_ids": list(original_test),
            "excluded_image_ids": list(excluded), "material_revision": material_revision,
            "annotation_revision": annotation_revision, "ground_truth_source": "original_annotation",
            **({"review_kind": review_kind} if review_kind else {})}


def normalize_benchmark_duplicate_review(
    project: Path, payload: Mapping[str, Any], resolved_split: SplitRequest,
):
    """Bind a client review to a Benchmark split resolved by a trusted caller.

    Only the API/Worker Benchmark resolvers call this helper, after verifying
    the frozen Benchmark. A payload field never grants that authority. Keep
    the client revisions and validate its original roles before introducing
    server-private Test identities into the internal freeze contract.
    """
    requested = _split_request(payload)
    review = validate_duplicate_review(project, payload, requested)
    if review is None:
        return None
    if requested.test_image_ids or review["original_test_image_ids"]:
        raise ValueError("duplicate review cannot supply Test roles when reusing a fixed Benchmark")
    original_train = tuple(review["original_train_image_ids"])
    rows = _selected_project_images(MaterialRepository(project), project,
        (*original_train, *resolved_split.test_image_ids))
    original_train, reserved = exclude_reserved_test_components(
        rows, original_train, resolved_split.test_image_ids,
    )
    if set(review["excluded_image_ids"]) & set(reserved):
        raise ValueError("duplicate review cannot exclude fixed Benchmark reserved material")
    normalized = {
        **review,
        "original_train_image_ids": list(original_train),
        "original_test_image_ids": list(resolved_split.test_image_ids),
    }
    return validate_duplicate_review(project, {**payload, "duplicate_review": normalized}, resolved_split)


def diagnose_training_duplicates(project: Path, payload: Mapping[str, Any], *, current_only=False) -> TrainingCompatibilityResult:
    """Read current original GT even when an old task has no usable label contract."""
    request = dict(payload)
    stored_split = payload.get("requested_split") or payload.get("split")
    if isinstance(stored_split, Mapping):
        request.update(stored_split)
        request["split_mode"] = stored_split.get("mode") or stored_split.get("split_mode") or request.get("split_mode")
    split = _split_request(request)
    materials = MaterialRepository(project)
    ids = (*split.train_image_ids, *split.test_image_ids)
    missing_count = 0
    if current_only:
        # History remains immutable. Its current-data view may omit indices
        # actually removed by governance; training admission stays strict.
        current_ids = {str(row['id']) for offset in range(0,len(ids),500)
            for row in materials.get_many(ids[offset:offset+500])}
        missing_count = len(set(ids)-current_ids)
        ids = tuple(image_id for image_id in ids if image_id in current_ids)
    rows = _selected_project_images(materials, project, ids) if ids else []
    issues = _duplicate_issues(rows, split.train_image_ids, split.test_image_ids, _dataset_names(project))
    return TrainingCompatibilityResult({}, tuple(issues), MaterialRepository(project).current_revision(),
        AnnotationRepository(project).current_revision(), {"selected_train_count": len(split.train_image_ids),
            "test_count": len(split.test_image_ids), "missing_current_image_count": missing_count})


_COMPATIBILITY_PAGE_FIELDS = frozenset({
    "selection_action",
    "selection",
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

    duplicate_issues = _duplicate_issues(
        list(by_id.values()), selection.selected_train_image_ids, effective.test_image_ids, names,
    )
    issues = tuple(duplicate_issues) + tuple(
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


def _duplicate_issues(rows, train_ids, test_ids, dataset_names):
    by_id = {str(row.get("id") or ""): row for row in rows}
    test = set(test_ids)
    issues = []
    for group in analyze_training_duplicates(rows, train_ids, test_ids):
        if group["issue_type"] == "duplicate_identical":
            continue
        for image_id in group["image_ids"]:
            row = by_id[image_id]
            labels = sorted({str(box.get("label") or box.get("code") or "")
                             for box in row.get("boxes") or []})
            dataset_id = str(row.get("dataset_id") or "")
            issues.append({
                "image_id": image_id, "filename": str(row.get("filename") or image_id),
                "dataset_id": dataset_id, "dataset_name": dataset_names.get(dataset_id, dataset_id),
                "issue_type": group["issue_type"], "content_sha256": group["content_sha256"],
                "duplicate_group_id": group["content_sha256"], "duplicate_group_size": len(group["image_ids"]),
                "conflict_types": group["conflict_types"], "ground_truth_conflict": group["ground_truth_conflict"],
                "annotation_state": str(row.get("annotation_state") or "unannotated"),
                "annotation_scope": list(row.get("annotation_scope") or [])[:100],
                "labels": labels[:100], "labels_count": len(labels),
                "box_count": len(row.get("boxes") or []),
                "annotation_digest": training_annotation_digest(row),
                "annotation_version": int(row.get("annotation_version") or row.get("version") or 0),
                "role": "test" if image_id in test else "train",
                "ground_truth_source": "original_annotation",
            })
    return issues


def annotation_import_batches(row):
    return sorted({str(value) for value in (
        row.get('import_batch_id'), row.get('batch_id'),
        *(box.get('import_batch_id') or box.get('source_task_id') for box in row.get('boxes') or []),
    ) if value})


def diagnose_annotation_conflict(rows, label_ids=None, import_confirmations=None):
    """Disposable evidence projection, never a vote on which GT is correct.

    Compare each member with a deterministic reference (not a recommended GT).
    Greedy IoU pairs are candidates only, not proof of object identity/missed GT.
    """
    from .annotation_quality import _finite_box, _iou

    rows = sorted(({**row, 'id': str(row.get('id') or row.get('image_id') or '')} for row in rows), key=lambda row: row['id'])
    if len({str(row.get('content_sha256') or '').lower() for row in rows}) > 1:
        raise ValueError('GT comparison requires the same content SHA256')
    duplicate = analyze_training_duplicates(rows, [row['id'] for row in rows])
    dimensions = set(duplicate[0]['conflict_types']) if duplicate else set()
    cohort = ('LABEL_SCOPE_COUNT_COMPOUND' if {'labels', 'annotation_scope', 'box_count'} <= dimensions else
              'COORDINATE_ONLY' if 'coordinates' in dimensions and not dimensions & {'labels', 'annotation_scope', 'box_count'} else
              'SCOPE_AND_GEOMETRY' if {'annotation_scope', 'coordinates'} <= dimensions else 'OTHER')
    observations, mappings, pairs = set(), [], []
    labels, scopes, counts, origins, roles = set(), set(), set(), set(), set()
    import_targets = {}
    verified_sources = []
    for row in rows:
        boxes = row.get('boxes') or []
        scope = set(map(str, row.get('annotation_scope') or []))
        names = {str(box.get('label') or box.get('code') or '') for box in boxes}
        labels.add(tuple(sorted(names)))
        scopes.add(tuple(sorted(scope)))
        counts.add(len(boxes))
        origins.update(annotation_import_batches(row) or [''])
        roles.add(str(row.get('split') or row.get('role') or 'unassigned').lower())
        if scope and names - scope:
            observations.add('SCOPE_BOX_MISMATCH')
        per_class = Counter(str(box.get('label') or box.get('code') or '') for box in boxes)
        row_counts = tuple(sorted(per_class.items()))
        # Numeric source ZIP IDs are not project IDs. Only an explicitly
        # canonical identity can prove a contradiction with the formal schema.
        verified_boxes = 0
        for index, box in enumerate(boxes):
            name = str(box.get('canonical_label_id') or box.get('label') or box.get('code') or '')
            canonical = box.get('canonical_project_class_id')
            if label_ids is not None and canonical is not None and name in label_ids and canonical != label_ids[name]:
                mappings.append({'image_id': str(row.get('id') or row.get('image_id') or ''),
                    'box_index': index, 'label': name, 'recorded_class_id': canonical,
                    'expected_class_id': label_ids[name], 'basis': 'EXPLICIT_CANONICAL_ID_VS_ACTIVE_SCHEMA'})
            task_id = str(box.get('import_batch_id') or box.get('source_task_id') or '')
            confirmation = (import_confirmations or {}).get(task_id) or {}
            taxonomy = confirmation.get('external_classes') or []
            coordinates = _finite_box(box)
            if (not confirmation.get('verified_task_owner') or not taxonomy or coordinates is None
                    or not all(math.isfinite(value) for value in coordinates)
                    or any(not str(item.get('name') or '').strip() for item in taxonomy)):
                continue
            source = str(box.get('source_class_id', ''))
            imported = (confirmation.get('members') or {}).get(str(row.get('id') or row.get('image_id') or ''), [])
            if not any(str(source_id) == source and all(abs(x-y) <= 1e-6 for x,y in zip(coordinates, original))
                       for source_id, original in imported):
                continue
            target = (confirmation.get('label_mapping') or {}).get(source)
            label = str(box.get('label') or box.get('code') or '')
            if target != label:
                observations.add('CURRENT_GT_DIFFERS_FROM_IMPORT_CONFIRMATION')
                continue
            verified_boxes += 1
            schema = tuple(sorted((str(item.get('class_id')), str(item['name'])) for item in taxonomy))
            key = (schema, source, tuple(round(value, 6) for value in coordinates))
            import_targets.setdefault(key, set()).add((task_id, label))
        batches = annotation_import_batches(row)
        if len(batches) == 1 and boxes and verified_boxes == len(boxes):
            source_record = (import_confirmations or {}).get(batches[0]) or {}
            original = (source_record.get('members') or {}).get(str(row.get('id') or row.get('image_id') or ''), [])
            actual_boxes = Counter((str(box.get('source_class_id', '')), tuple(round(v, 6) for v in _finite_box(box))) for box in boxes)
            source_boxes = Counter((str(source), tuple(round(v, 6) for v in coords)) for source, coords in original)
            if actual_boxes == source_boxes and scope == set((source_record.get('label_mapping') or {}).values()):
                verified_sources.append(str(row.get('id') or row.get('image_id') or ''))
        if row is rows[0]:
            first_counts = row_counts
        elif row_counts != first_counts:
            observations.add('PER_CLASS_BOX_COUNT_DIFFERENCE')
    if len(labels) > 1:
        observations.add('LABEL_SET_DIFFERENCE')
    if len(scopes) > 1:
        observations.add('SCOPE_DIFFERENCE')
    if len(counts) > 1:
        observations.add('BOX_COUNT_DIFFERENCE')
    if len(origins - {''}) > 1:
        observations.add('DIFFERENT_IMPORT_BATCHES')
    if len(roles - {'unassigned', ''}) > 1:
        observations.add('CROSS_SPLIT_IDENTITY')
    if mappings:
        observations.add('CANONICAL_ID_MISMATCH')
    mapping_differences = sum(len({label for _task, label in values}) > 1
        and len({task for task, _label in values}) > 1 for values in import_targets.values())
    if mapping_differences:
        observations.add('VERIFIED_IMPORT_MAPPING_DIFFERENCE')
    comparison_budget = 100000
    for row in rows[1:]:
        base = rows[0]
        left, right = base.get('boxes') or [], row.get('boxes') or []
        a, b = [_finite_box(box) for box in left], [_finite_box(box) for box in right]
        valid = all(box is not None and box[2] > box[0] and box[3] > box[1] for box in (*a, *b))
        pair = {'reference_image_id': str(base.get('id') or base.get('image_id') or ''),
                'image_id': str(row.get('id') or row.get('image_id') or ''), 'matches': [],
                'geometry_status': 'VERIFIED' if valid else 'UNVERIFIABLE',
                'matching_method': 'GREEDY_IOU_CANDIDATES_NOT_OBJECT_IDENTITY'}
        comparison_budget -= len(left) * len(right)
        if comparison_budget < 0:
            pair['geometry_status'] = 'DETAIL_REQUIRED_BUDGET_LIMIT'
        if pair['geometry_status'] == 'VERIFIED':
            candidates = sorted(((_iou(x, y), i, j) for i, x in enumerate(a) for j, y in enumerate(b)), reverse=True)
            used_a, used_b = set(), set()
            for iou, i, j in candidates:
                if iou <= 0 or i in used_a or j in used_b:
                    continue
                used_a.add(i)
                used_b.add(j)
                pair['matches'].append({'reference_box': i, 'box': j, 'iou': iou,
                    'same_label': str(left[i].get('label') or left[i].get('code') or '') == str(right[j].get('label') or right[j].get('code') or ''),
                    'max_pixel_delta': max(abs(x - y) for x, y in zip(a[i], b[j])),
                    'reference_coordinates': a[i], 'coordinates': b[j]})
            pair['unmatched_reference_boxes'] = len(left) - len(used_a)
            pair['unmatched_boxes'] = len(right) - len(used_b)
            if any(match['max_pixel_delta'] > 0 for match in pair['matches']):
                observations.add('COORDINATE_DIFFERENCE')
            if pair['unmatched_reference_boxes'] or pair['unmatched_boxes']:
                observations.add('UNMATCHED_BOXES_REVIEW_REQUIRED')
        pairs.append(pair)
    matches = [match for pair in pairs for match in pair['matches']]
    scores = [match['iou'] for match in matches]
    iou_summary = {'matched_count': len(matches), 'min': min(scores) if scores else None,
        'max': max(scores) if scores else None, 'mean': sum(scores) / len(scores) if scores else None,
        'max_pixel_delta': max((match['max_pixel_delta'] for match in matches), default=None),
        'unmatched_count': sum(pair.get('unmatched_boxes', 0) + pair.get('unmatched_reference_boxes', 0) for pair in pairs),
        'unverifiable_pairs': sum(pair['geometry_status'] != 'VERIFIED' for pair in pairs),
        'histogram': {name: sum(low <= score < high for score in scores) for name, low, high in
            [('lt_0_5', 0, 0.5), ('0_5_to_0_75', 0.5, 0.75), ('0_75_to_0_9', 0.75, 0.9), ('gte_0_9', 0.9, 1.0000001)]}}
    return {'observations': sorted(observations), 'cohort': cohort, 'mapping_evidence': mappings, 'iou_summary': iou_summary,
        'proven_mapping_error_count': len(mappings), 'pairs': pairs,
        'verified_import_mapping_difference_count': mapping_differences,
        'verified_source_image_ids': verified_sources,
        'root_cause_status': ('CANONICAL_ID_MISMATCH_PROVEN' if mappings else
                              'IMPORT_CONFIRMATIONS_DIFFER' if mapping_differences else 'UNDETERMINED'),
        'provenance_status': 'RECORDED' if origins and '' not in origins else 'INCOMPLETE',
        'requires_human_review': True, 'automatic_gt_write_allowed': False}


def resolve_training_compatibility_selection(result: TrainingCompatibilityResult, payload) -> dict[str, Any]:
    """Resolve exact issue identities for draft exclusion or a deletion preview.

    This is a read projection of the same canonical compatibility result, never
    an audit job or an authorization to remove current Ground Truth.
    """
    if (payload.get('expected_material_revision') != result.material_revision
            or payload.get('expected_annotation_revision') != result.annotation_revision):
        raise ValueError('TRAINING_SELECTION_STALE: 素材或GT已变化，请重新检查')
    selection = payload.get('selection') or {}
    if not isinstance(selection, Mapping):
        raise ValueError('TRAINING_SELECTION_INVALID: selection必须是对象')
    selected, excluded = selection.get('image_ids') or [], selection.get('excluded_image_ids') or []
    for values in (selected, excluded):
        if (not isinstance(values, list) or len(values) > 100000
                or any(not isinstance(value, str) or not value.strip() for value in values)):
            raise ValueError('TRAINING_SELECTION_INVALID: 素材身份列表无效')
    query = str(selection.get('query') or '').strip().casefold()
    issue_type = str(selection.get('issue_type') or '').strip()
    if len(query) > 256:
        raise ValueError('TRAINING_SELECTION_INVALID: 筛选文本过长')
    all_ids = {str(item['image_id']) for item in result.issues}
    filtered = {str(item['image_id']) for item in result.issues
        if (not issue_type or item.get('issue_type') == issue_type)
        and (not query or any(query in str(item.get(key) or '').casefold()
            for key in ('image_id','filename','content_sha256','duplicate_group_id')))}
    candidates = all_ids if selection.get('all_issues') is True else filtered
    if not set(selected).issubset(candidates) or not set(excluded).issubset(candidates):
        raise ValueError('TRAINING_SELECTION_CHANGED: 所选素材不属于本次真实问题范围')
    chosen = candidates if selection.get('all_issues') is True or selection.get('all_filtered') is True else set(selected)
    chosen = chosen - set(excluded)
    return {'matching_image_ids':sorted(chosen),'selected_count':len(chosen),
        'filtered_count':len(candidates),'excluded_count':len(set(excluded)),
        'summary':result.summary(),'material_revision':result.material_revision,
        'annotation_revision':result.annotation_revision,'selection_action':'RESOLVE_SELECTION'}


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
            or normalized_query in str(item.get("content_sha256") or "").casefold()
            or normalized_query in str(item.get("duplicate_group_id") or "").casefold()
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
        "governance_eligible_count": len({str(item['image_id']) for item in filtered}),
        "filtered_affected_image_count": len({str(item['image_id']) for item in filtered}),
        "filtered_issue_count": total,
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
