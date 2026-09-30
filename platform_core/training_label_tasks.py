from __future__ import annotations

import hashlib
import json
import re
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import training_tasks as base
from .algorithms import (
    choose_algorithm_iteration_base,
    list_algorithms,
    update_algorithm_version,
)
from .annotation_repository import AnnotationRepository
from .task_runtime import ArtifactStore, TaskKind, TaskStatus


_LABEL_CONTRACT: ContextVar[dict[str, Any] | None] = ContextVar(
    "training_label_contract",
    default=None,
)
_ORIGINAL_LABEL_SCHEMA = base._label_schema
_ORIGINAL_SELECTED_PROJECT_IMAGES = base._selected_project_images


def _unique_codes(values: Sequence[Any] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values or ():
        code = str(value or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        result.append(code)
    return result


def _project_label_governance(
    project: Path,
) -> tuple[list[str], dict[str, dict[str, Any]]]:
    """Return the durable project label identities, including merged/inactive rows."""

    meta = base._json(project / "meta.json", {})
    labels = list(meta.get("labels") or [])
    metadata = list(meta.get("label_meta") or [])
    ordered: list[str] = []
    governance: dict[str, dict[str, Any]] = {}
    total = max(len(labels), len(metadata))
    for index in range(total):
        raw_label = labels[index] if index < len(labels) else ""
        raw_meta = metadata[index] if index < len(metadata) else {}
        item = dict(raw_meta) if isinstance(raw_meta, Mapping) else {}
        if isinstance(raw_label, Mapping):
            item = {**dict(raw_label), **item}
            fallback_code = str(raw_label.get("code") or raw_label.get("name") or "")
        else:
            fallback_code = str(raw_label or "")
        code = str(item.get("code") or fallback_code).strip()
        if not code or code in governance:
            continue
        status = str(
            item.get("status")
            or ("inactive" if item.get("active") is False else "active")
        ).strip().lower()
        if item.get("active") is False and status == "active":
            status = "inactive"
        item["code"] = code
        item["status"] = status
        item["merged_into"] = str(item.get("merged_into") or "").strip()
        item["project_class_id"] = int(item.get("class_id", index))
        ordered.append(code)
        governance[code] = item
    return ordered, governance


def _project_label_catalog(project: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    ordered, governance = _project_label_governance(project)
    active_order: list[str] = []
    catalog: dict[str, dict[str, Any]] = {}
    for code in ordered:
        item = governance[code]
        if item.get("active") is False or str(item.get("status") or "active") != "active":
            continue
        active_order.append(code)
        catalog[code] = dict(item)
    return active_order, catalog


def _resolve_inherited_label_governance(
    project: Path,
    inherited: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, str], list[str]]:
    """Project immutable historical outputs into the current canonical label graph.

    Historical algorithm versions are never mutated. A user-confirmed project
    merge is authoritative for NEW training tasks, so inherited merged labels
    follow merged_into (including merge chains) and deduplicate at the active
    target. Plain inactive/missing labels fail closed because there is no
    user-approved target to infer.
    """

    _ordered, governance = _project_label_governance(project)
    _active_order, active_catalog = _project_label_catalog(project)
    retained: list[dict[str, Any]] = []
    retained_by_code: dict[str, dict[str, Any]] = {}
    merged: dict[str, str] = {}
    dropped: list[str] = []

    for historical in inherited:
        source_code = str(historical.get("code") or "").strip()
        current_code = source_code
        visited: list[str] = []
        while True:
            if current_code in visited:
                raise ValueError(
                    "项目标签合并关系存在循环，无法安全创建迭代训练: "
                    + " -> ".join([*visited, current_code])
                )
            visited.append(current_code)
            row = governance.get(current_code)
            if row is None:
                raise ValueError(
                    f"上一算法版本标签 {source_code} 已不在当前项目标签治理中；"
                    "请先恢复该标签或在标签管理中明确统一到现有标签"
                )
            status = str(row.get("status") or "active").strip().lower()
            if status == "active" and row.get("active") is not False:
                target_code = current_code
                break
            if status == "merged":
                target = str(row.get("merged_into") or "").strip()
                if not target:
                    raise ValueError(
                        f"上一算法版本标签 {source_code} 已标记 merged 但缺少 merged_into；"
                        "请先修复标签治理关系"
                    )
                current_code = target
                continue
            raise ValueError(
                f"上一算法版本标签 {source_code} 已停用且没有明确 merged_into；"
                "系统不会自动猜测替代标签，请先在标签管理中完成统一"
            )

        active = active_catalog.get(target_code)
        if active is None:
            raise ValueError(
                f"上一算法版本标签 {source_code} 的合并目标 {target_code} 当前不可用；"
                "请先修复标签治理关系"
            )
        if source_code != target_code:
            merged[source_code] = target_code
            dropped.append(source_code)

        if target_code in retained_by_code:
            sources = retained_by_code[target_code].setdefault("inherited_from_codes", [])
            if source_code not in sources:
                sources.append(source_code)
            continue

        normalized = dict(active)
        canonical_project_class_id = int(
            normalized.pop(
                "project_class_id",
                normalized.get("class_id", len(retained)),
            )
        )
        normalized["code"] = target_code
        normalized["canonical_project_class_id"] = canonical_project_class_id
        normalized["class_id"] = len(retained)
        normalized["source"] = (
            "previous_version_merged"
            if source_code != target_code
            else "previous_version"
        )
        normalized["inherited_from_codes"] = [source_code]
        retained.append(normalized)
        retained_by_code[target_code] = normalized

    return retained, merged, dropped


def _temporary_or_unmapped_label(code: str) -> bool:
    value = str(code or "").strip().lower()
    if not value:
        return True
    if value in {"unknown", "unmapped", "temporary", "temp", "class"}:
        return True
    return bool(
        re.fullmatch(r"(?:class|cls)[_-]?\d+", value)
        or value.startswith("unknown_")
        or value.startswith("unmapped_")
        or value.startswith("temp_")
    )


def selected_material_label_codes(
    project: Path,
    payload: Mapping[str, Any],
    *,
    allowed_nonactive_codes: Sequence[str] = (),
    positive_only: bool = False,
) -> list[str]:
    """Return only labels evidenced by the exact materials selected for this task.

    Positive annotations contribute their box labels. Explicit confirmed-empty
    samples contribute their scoped labels for preflight validation, but callers
    may request positive-only evidence when deciding which NEW classes can enter
    a task schema. Historical '*' negatives do not
    manufacture project-wide choices because the original concrete scope is no
    longer knowable.
    """

    selected_ids = _unique_codes(
        [
            *(payload.get("train_image_ids") or []),
            *(payload.get("val_image_ids") or []),
            *(payload.get("selected_image_ids") or []),
        ]
    )
    if not selected_ids:
        return []
    annotations = AnnotationRepository(project)
    encountered: list[str] = []
    positive_encountered: list[str] = []
    seen: set[str] = set()
    positive_seen: set[str] = set()
    for offset in range(0, len(selected_ids), 500):
        chunk = selected_ids[offset:offset + 500]
        batch = annotations.get_many(chunk)
        for image_id in chunk:
            annotation = batch[image_id]
            for box in annotation.get("boxes") or []:
                code = str(box.get("label") or box.get("code") or "").strip()
                if not code:
                    raise ValueError(
                        f"训练素材 {image_id} 存在没有 canonical label 的标注框；请先完成标签统一"
                    )
                if code not in seen:
                    seen.add(code)
                    encountered.append(code)
                if code not in positive_seen:
                    positive_seen.add(code)
                    positive_encountered.append(code)
            for value in annotation.get("annotation_scope") or []:
                code = str(value or "").strip()
                if code and code != "*" and code not in seen:
                    seen.add(code)
                    encountered.append(code)

    project_order, catalog = _project_label_catalog(project)
    inherited_allowlist = {
        str(code).strip() for code in allowed_nonactive_codes if str(code).strip()
    }
    invalid = [
        code for code in encountered
        if code not in catalog and code not in inherited_allowlist
    ]
    if invalid:
        raise ValueError(
            "训练素材包含未映射、已删除或已停用的标签: "
            + ", ".join(invalid[:10])
            + "；请先前往 标签管理 → 标签完整性 完成审计与人工映射后再训练"
        )
    temporary = [code for code in encountered if _temporary_or_unmapped_label(code)]
    if temporary:
        raise ValueError(
            "训练素材包含临时/未知标签: "
            + ", ".join(temporary[:10])
            + "；class_x / unknown / temp_* 不能进入正式训练"
        )
    rank = {code: index for index, code in enumerate(project_order)}
    evidence = positive_encountered if positive_only else encountered
    return sorted(evidence, key=lambda code: (rank.get(code, 10**9), evidence.index(code), code))


def _normalized_version_schema(values: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    schema = [dict(item) for item in values or () if str(item.get("code") or "").strip()]
    schema.sort(key=lambda item: (int(item.get("class_id", 10**9)), str(item.get("code"))))
    codes = [str(item.get("code") or "").strip() for item in schema]
    if len(codes) != len(set(codes)):
        raise ValueError("上一算法版本的 label_schema 存在重复标签，无法安全迭代")
    class_ids = [int(item.get("class_id", index)) for index, item in enumerate(schema)]
    if class_ids != list(range(len(schema))):
        raise ValueError("上一算法版本的 class_id 不是连续 0..N-1，无法安全保持类别映射")
    for index, item in enumerate(schema):
        item["code"] = codes[index]
        item["class_id"] = index
        item["source"] = "previous_version"
    return schema


def _legacy_snapshot_schema(data_dir: Path, version: Mapping[str, Any]) -> list[dict[str, Any]]:
    task_id = str(version.get("task_id") or version.get("job_id") or "").strip()
    if not task_id:
        return []
    artifacts = ArtifactStore(data_dir / "task_runtime" / "artifacts")
    snapshot = artifacts.read_json(task_id, "snapshot.json", default={})
    if not isinstance(snapshot, dict):
        return []
    return _normalized_version_schema(snapshot.get("label_schema") or [])


def inherited_training_label_preview(
    data_dir: Path,
    project: Path,
    algorithm: Mapping[str, Any],
    base_version_id: str = "",
) -> dict[str, Any]:
    """Return only canonical labels inherited by a new training task.

    This is a read-only UI projection. It intentionally omits historical source
    labels and merge audit details. Final task creation still recomputes and
    freezes resolve_training_label_contract(), which remains the sole training
    truth owner.
    """

    versions = list(algorithm.get("versions") or [])
    requested_version_id = str(
        base_version_id or algorithm.get("current_version_id") or ""
    ).strip()
    if not versions or not requested_version_id:
        return {
            "has_previous_version": False,
            "base_version_id": "",
            "base_version_name": "",
            "labels": [],
        }

    previous = next(
        (
            row for row in versions
            if str(row.get("id") or row.get("version_id") or "").strip()
            == requested_version_id
        ),
        None,
    )
    if previous is None:
        raise ValueError("上一算法版本已变化，请刷新算法列表后重试")

    inherited = _normalized_version_schema(previous.get("label_schema") or [])
    if not inherited:
        inherited = _legacy_snapshot_schema(data_dir, previous)
    if not inherited:
        raise ValueError(
            "上一算法版本缺少可验证的标签快照，无法展示继承标签"
        )

    retained, _merged, _dropped = _resolve_inherited_label_governance(
        project,
        inherited,
    )
    labels = []
    for item in retained:
        code = str(item.get("code") or "").strip()
        if not code:
            continue
        display_name = str(
            item.get("display_name")
            or item.get("display_name_zh")
            or item.get("name")
            or code
        )
        labels.append({"code": code, "display_name": display_name})

    return {
        "has_previous_version": True,
        "base_version_id": requested_version_id,
        "base_version_name": str(previous.get("version_name") or requested_version_id),
        "labels": labels,
    }


def _iteration_base(
    algorithm: Mapping[str, Any],
    mother_model: str,
    framework: str,
) -> tuple[Mapping[str, Any] | None, dict[str, Any]]:
    framework_value = str(framework or "ultralytics").strip().lower()
    versions = list(algorithm.get("versions") or [])
    selection = choose_algorithm_iteration_base(
        algorithm,
        mother_model,
        framework_value,
        strict_latest=bool(versions),
        artifact_validator=lambda path: path.is_file() and path.stat().st_size > 0,
    )
    version_id = str(selection.get("base_version_id") or "")
    previous = (
        next((row for row in versions if str(row.get("id") or "") == version_id), None)
        if version_id else None
    )
    return previous, dict(selection)


def _iteration_version(
    algorithm: Mapping[str, Any],
    mother_model: str,
    framework: str,
) -> Mapping[str, Any] | None:
    previous, _selection = _iteration_base(algorithm, mother_model, framework)
    return previous


def _frozen_base_contract(
    previous: Mapping[str, Any] | None,
    selection: Mapping[str, Any],
    mother_model: str,
    framework: str,
) -> dict[str, Any]:
    framework_value = str(framework or "ultralytics").strip().lower()
    reference = str(selection.get("base_model_path") or mother_model or "").strip()
    result = {
        "base_model_contract_schema_version": 1,
        "framework": framework_value,
        "base_version_id": (
            str(selection.get("base_version_id") or "") if previous is not None else ""
        ),
        "base_version_name": (
            str(selection.get("base_version_name") or "") if previous is not None else ""
        ),
        "base_model_kind": str(
            selection.get("base_model_kind")
            or ("train_checkpoint" if previous is not None else "mother_model")
        ),
        "base_model_reference": reference,
        "base_model_sha256": "",
        "base_model_size_bytes": 0,
        "base_selection_reason": str(
            selection.get("base_selection_reason")
            or ("current_verified_version" if previous is not None else "mother_model")
        ),
    }
    if not reference:
        return result

    candidate = Path(reference).expanduser()
    if not candidate.is_file():
        # Official/model-registry references are frozen by exact name. They are
        # resolved by the execution environment later, but a newly-created
        # algorithm version may not change this first-training choice.
        return result

    resolved = candidate.resolve()
    result.update(
        base_model_reference=str(resolved),
        base_model_sha256=base._sha256(resolved),
        base_model_size_bytes=int(resolved.stat().st_size),
    )
    return result


def resolve_training_label_contract(
    data_dir: str | Path,
    project: str | Path,
    payload: Mapping[str, Any],
    algorithm: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve the only label schema that may reach YOLO for this task.

    First training: user-selected labels from selected materials only.
    Iteration: the historical previous-version schema remains immutable, while
    NEW task labels are resolved through current canonical governance. Explicit
    merged_into decisions collapse inherited labels; plain inactive/missing
    labels fail closed. Mother-model classes never enter the contract.
    """

    data_root = Path(data_dir).resolve()
    project_path = Path(project).resolve()
    project_order, catalog = _project_label_catalog(project_path)
    project_rank = {code: index for index, code in enumerate(project_order)}
    requested = _unique_codes(payload.get("train_labels") or [])
    invalid_catalog_requested = [code for code in requested if code not in catalog]
    if invalid_catalog_requested:
        raise ValueError(
            "本次选择包含非当前有效 canonical 标签: "
            + ", ".join(invalid_catalog_requested[:10])
        )
    temporary_requested = [code for code in requested if _temporary_or_unmapped_label(code)]
    if temporary_requested:
        raise ValueError(
            "本次选择包含临时/未知标签: " + ", ".join(temporary_requested[:10])
        )
    mother = str(payload.get("model") or "").strip()
    framework_value = str(payload.get("framework") or "ultralytics").strip().lower()
    previous, base_selection = _iteration_base(
        algorithm,
        mother,
        framework_value,
    )
    base_contract = _frozen_base_contract(
        previous,
        base_selection,
        mother,
        framework_value,
    )

    inherited: list[dict[str, Any]] = []
    if previous is not None:
        inherited = _normalized_version_schema(previous.get("label_schema") or [])
        if not inherited:
            inherited = _legacy_snapshot_schema(data_root, previous)
        if not inherited:
            raise ValueError(
                "上一算法版本没有可恢复的标签合同；为避免类别错位，不能从项目全部标签或母模型自动猜测。"
                "请恢复上一版本 snapshot.json，或重新建立首个正确标签版本。"
            )

    inherited_codes = [str(item["code"]) for item in inherited]
    retained_inherited, merged_inherited, dropped_inherited = (
        _resolve_inherited_label_governance(project_path, inherited)
        if inherited
        else ([], {}, [])
    )
    retained_inherited_codes = [str(item["code"]) for item in retained_inherited]
    retained_inherited_set = set(retained_inherited_codes)
    available = selected_material_label_codes(
        project_path,
        payload,
        positive_only=True,
    )
    available_set = set(available)

    invalid_requested = [
        code for code in requested
        if code not in available_set and code not in retained_inherited_set
    ]
    if invalid_requested:
        raise ValueError(
            "本次选择的标签不在已选素材中: " + ", ".join(invalid_requested[:10])
        )
    if previous is None and not requested:
        raise ValueError(
            "首次训练必须从已选素材实际携带的标签中至少选择一个；母算法自带类别不会自动继承。"
        )

    requested_new = [code for code in requested if code not in retained_inherited_set]
    schema_change_reasons = []
    if merged_inherited:
        schema_change_reasons.append("merged_labels")
    if requested_new:
        schema_change_reasons.append("added_labels")
    label_schema_changed = bool(schema_change_reasons)

    # Training always starts from model weights, never optimizer/trainer state.
    # Inherited class identity is retained; newly selected classes append to the
    # task schema. Training class_id is reindexed contiguously while canonical
    # project class identity remains separately auditable.
    effective = [dict(item) for item in retained_inherited]
    for code in requested_new:
        source = dict(catalog[code])
        canonical_project_class_id = int(
            source.pop("project_class_id", source.get("class_id", len(effective)))
        )
        source["code"] = code
        source["canonical_project_class_id"] = canonical_project_class_id
        source["class_id"] = len(effective)
        source["source"] = "selected_material"
        effective.append(source)

    if not effective:
        raise ValueError("本次训练没有任何有效标签")
    if [int(item.get("class_id", -1)) for item in effective] != list(range(len(effective))):
        raise ValueError("训练标签 class_id 必须连续为 0..N-1")

    return {
        "schema_version": 1,
        "algorithm_id": str(algorithm.get("id") or ""),
        "available_material_label_codes": available,
        "requested_label_codes": requested,
        "requested_new_label_codes": requested_new,
        "inherited_label_codes": inherited_codes,
        "retained_inherited_label_codes": retained_inherited_codes,
        "merged_inherited_label_codes": merged_inherited,
        "dropped_inherited_label_codes": dropped_inherited,
        "effective_label_codes": [str(item["code"]) for item in effective],
        "effective_label_schema": effective,
        "label_schema_changed": label_schema_changed,
        "label_schema_change_reasons": schema_change_reasons,
        **base_contract,
        "base_training_mode": "previous_weights_init" if previous is not None else "mother_model_init",
        "strict_resume": False,
        "optimizer_state_resumed": False,
        "mother_model_labels_inherited": False,
        "project_label_count": len(project_rank),
    }


def _contract_for_project(project: Path) -> dict[str, Any] | None:
    contract = _LABEL_CONTRACT.get()
    if not contract:
        return None
    if Path(str(contract.get("project_path") or "")).resolve() != Path(project).resolve():
        return None
    return contract


def _scoped_label_schema(project: Path) -> list[dict[str, Any]]:
    contract = _contract_for_project(project)
    if contract is None:
        return _ORIGINAL_LABEL_SCHEMA(project)
    return [dict(item) for item in contract["effective_label_schema"]]


def _projection_digest(
    *,
    state: str,
    allowed: Sequence[str],
    selected_boxes: Sequence[Mapping[str, Any]],
    excluded_boxes: Sequence[Mapping[str, Any]],
) -> str:
    payload = {
        "policy": base.TRAINING_PROJECTION_POLICY,
        "source_annotation_state": str(state),
        "effective_label_codes": list(allowed),
        "selected_boxes": [dict(box) for box in selected_boxes],
        "excluded_boxes": [dict(box) for box in excluded_boxes],
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()


def project_training_rows(
    rows: Sequence[Mapping[str, Any]],
    contract: Mapping[str, Any],
) -> list[dict[str, Any]]:
    """Project formal GT to one task schema while preserving excluded-object truth."""
    allowed_order = _unique_codes(contract.get("effective_label_codes") or [])
    allowed = set(allowed_order)
    projected: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        state = str(row.get("annotation_state") or "unannotated")
        raw_scope = [str(value) for value in row.get("annotation_scope") or []]
        boxes = [dict(box) for box in (row.get("boxes") or [])]
        selected_boxes = [
            box for box in boxes
            if str(box.get("label") or box.get("code") or "").strip() in allowed
        ]
        excluded_boxes = [
            box for box in boxes
            if str(box.get("label") or box.get("code") or "").strip() not in allowed
        ]
        present = sorted({
            str(box.get("label") or box.get("code") or "").strip()
            for box in boxes
            if str(box.get("label") or box.get("code") or "").strip()
        })
        row["source_annotation_state"] = state
        source_annotation_hash = str(row.get("annotation_hash") or row.get("content_digest") or "").strip().lower()
        if source_annotation_hash:
            row["source_annotation_hash"] = source_annotation_hash
        row["source_labels"] = present

        if excluded_boxes:
            row["training_excluded_boxes"] = excluded_boxes
            row["training_projection_policy"] = base.TRAINING_PROJECTION_POLICY
            row["training_projection_digest"] = _projection_digest(
                state=state,
                allowed=allowed_order,
                selected_boxes=selected_boxes,
                excluded_boxes=excluded_boxes,
            )

        if state == "annotated":
            if selected_boxes:
                row["annotation_state"] = "annotated"
                row["annotated"] = True
                row["boxes"] = selected_boxes
                explicit = {value for value in raw_scope if value and value != "*"}
                row["annotation_scope"] = sorted((explicit & allowed) | {
                    str(box.get("label") or box.get("code") or "").strip()
                    for box in selected_boxes
                })
            elif excluded_boxes:
                # The materializer must redact every excluded region before this
                # task-local negative is allowed to reach train/validation loss.
                row["annotation_state"] = "confirmed_empty"
                row["annotated"] = True
                row["boxes"] = []
                row["annotation_scope"] = sorted(allowed)
                row["negative_origin"] = "redacted_unselected_labels"
            else:
                row["boxes"] = []
        else:
            row["annotation_state"] = state
            row["annotated"] = state in {"annotated", "confirmed_empty"}
            row["boxes"] = []
            row["annotation_scope"] = raw_scope
            if state == "confirmed_empty":
                row["negative_origin"] = str(
                    row.get("negative_origin") or "explicit_confirmed_empty"
                )

        # Persisted annotation_hash describes full project GT. The task snapshot
        # hashes projected truth plus training_projection_digest instead.
        row.pop("annotation_hash", None)
        projected.append(row)
    return projected


def _scoped_selected_project_images(materials, project: Path, image_ids: Sequence[str]):
    rows = _ORIGINAL_SELECTED_PROJECT_IMAGES(materials, project, image_ids)
    contract = _contract_for_project(project)
    if contract is None:
        return rows
    return project_training_rows(rows, contract)


def _install_scoped_training_hooks() -> None:
    if getattr(base, "_training_label_contract_installed", False):
        return
    base._label_schema = _scoped_label_schema
    base._selected_project_images = _scoped_selected_project_images
    base._training_label_contract_installed = True


def _algorithm_for_payload(project: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    algorithm_id = str(payload.get("algorithm_asset_id") or "").strip()
    algorithms = list_algorithms(project / "algorithms.json")
    algorithm = next((row for row in algorithms if str(row.get("id") or "") == algorithm_id), None)
    if algorithm is None:
        raise ValueError("training algorithm no longer exists")
    return algorithm


def _persist_version_contract(project: Path, task_id: str, contract: Mapping[str, Any]) -> None:
    """Patch only the completed version; never replace the whole algorithm graph."""
    path = project / "algorithms.json"
    algorithm_id = str(contract.get("algorithm_id") or "").strip()
    if not algorithm_id:
        return
    algorithm = next(
        (
            row
            for row in list_algorithms(path)
            if str(row.get("id") or "") == algorithm_id
        ),
        None,
    )
    if algorithm is None:
        return
    version = next(
        (
            row
            for row in (algorithm.get("versions") or [])
            if str(row.get("task_id") or row.get("job_id") or "") == str(task_id)
        ),
        None,
    )
    if version is None:
        return
    version_id = str(version.get("id") or "").strip()
    if not version_id:
        return

    persisted_contract = {
        key: value
        for key, value in contract.items()
        if key != "project_path"
    }
    previous_contract = (
        dict(version.get("label_contract") or {})
        if isinstance(version.get("label_contract"), Mapping)
        else {}
    )
    update_algorithm_version(
        path,
        algorithm_id,
        version_id,
        {
            "label_schema": [
                dict(item)
                for item in contract.get("effective_label_schema") or []
            ],
            "label_codes": list(contract.get("effective_label_codes") or []),
            "label_contract": {
                **previous_contract,
                **persisted_contract,
                "strict_resume": False,
                "optimizer_state_resumed": False,
                "mother_model_labels_inherited": False,
            },
        },
        now=datetime.now(timezone.utc).isoformat(),
    )


class LabelContractTrainingHandler(base.TrainingHandler):
    def _contract(self, context, payload: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
        project = self.data_dir / "projects" / context.task.project_id
        freeze_ref = str(payload.get("input_freeze_ref") or "").strip()
        if freeze_ref:
            frozen = context.artifacts.read_json(context.task.task_id, freeze_ref, default={})
            frozen_contract = (
                dict(frozen.get("label_contract") or {})
                if isinstance(frozen, Mapping)
                else {}
            )
            if frozen_contract:
                frozen_contract["project_path"] = str(project.resolve())
                return project, frozen_contract
        # Compatibility only for tasks created before submit-time label freezing.
        algorithm = _algorithm_for_payload(project, payload)
        contract = resolve_training_label_contract(self.data_dir, project, payload, algorithm)
        contract["project_path"] = str(project.resolve())
        return project, contract

    def _persist_result_contract(self, context, project: Path, contract: Mapping[str, Any]) -> None:
        result = context.artifacts.read_json(context.task.task_id, "result.json", default={})
        if isinstance(result, dict) and result:
            result["label_schema"] = [dict(item) for item in contract.get("effective_label_schema") or []]
            result["label_codes"] = list(contract.get("effective_label_codes") or [])
            result["label_contract"] = {
                key: value for key, value in contract.items() if key != "project_path"
            }
            context.artifacts.atomic_write_json(context.task.task_id, "result.json", result)
        _persist_version_contract(project, context.task.task_id, contract)
        job_path = project / "jobs" / context.task.task_id / "job.json"
        job = base._json(job_path, {})
        if isinstance(job, dict) and job:
            job["label_schema"] = [dict(item) for item in contract.get("effective_label_schema") or []]
            job["label_codes"] = list(contract.get("effective_label_codes") or [])
            job["label_contract"] = {
                key: value for key, value in contract.items() if key != "project_path"
            }
            base.atomic_write_json(job_path, job)

    def run(self, context):
        payload = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
        if not isinstance(payload, dict):
            raise ValueError("training payload is invalid")
        project, contract = self._contract(context, payload)
        context.artifacts.atomic_write_json(
            context.task.task_id,
            "label-contract.json",
            {key: value for key, value in contract.items() if key != "project_path"},
        )
        token = _LABEL_CONTRACT.set(contract)
        try:
            outcome = super().run(context)
        finally:
            _LABEL_CONTRACT.reset(token)
        self._persist_result_contract(context, project, contract)
        return outcome

    def recover(self, context):
        committed = self._committed(context)
        if committed:
            result = context.artifacts.read_json(context.task.task_id, committed, default={})
            snapshot = context.artifacts.read_json(context.task.task_id, "snapshot.json", default={})
            schema = list((result or {}).get("label_schema") or (snapshot or {}).get("label_schema") or [])
            if schema:
                project = self.data_dir / "projects" / context.task.project_id
                contract = dict((result or {}).get("label_contract") or {})
                contract.update(
                    algorithm_id=str((result or {}).get("label_contract", {}).get("algorithm_id") or context.task.project_id),
                    effective_label_schema=schema,
                    effective_label_codes=[str(item.get("code")) for item in schema if item.get("code")],
                )
                # Prefer the actual algorithm id from the persisted task payload.
                payload = context.artifacts.read_json(context.task.task_id, context.task.payload_ref, default={})
                if isinstance(payload, dict):
                    contract["algorithm_id"] = str(payload.get("algorithm_asset_id") or contract.get("algorithm_id") or "")
                self._persist_result_contract(context, project, contract)
            partial = ((result.get("training_report") or {}).get("test_result") or {}).get("status") == "failed"
            return (TaskStatus.PARTIAL_SUCCESS if partial else TaskStatus.SUCCEEDED), committed
        return self.run(context)


def worker_registration(data_dir: Path):
    _install_scoped_training_hooks()
    return {
        "handlers": {TaskKind.TRAINING: LabelContractTrainingHandler(data_dir)},
        "capabilities": {"training.ultralytics"},
    }
