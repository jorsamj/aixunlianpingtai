from __future__ import annotations

import json
import re
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Mapping, Sequence

from . import training_tasks as base
from .algorithms import choose_algorithm_iteration_base, list_algorithms, save_algorithms
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


def _project_label_catalog(project: Path) -> tuple[list[str], dict[str, dict[str, Any]]]:
    meta = base._json(project / "meta.json", {})
    ordered: list[str] = []
    catalog: dict[str, dict[str, Any]] = {}
    for index, value in enumerate(meta.get("label_meta") or meta.get("labels") or []):
        item = dict(value) if isinstance(value, dict) else {"code": str(value)}
        code = str(item.get("code") or "").strip()
        if not code or item.get("active") is False or item.get("status", "active") != "active":
            continue
        if code in catalog:
            continue
        item["code"] = code
        item["project_class_id"] = int(item.get("class_id", index))
        ordered.append(code)
        catalog[code] = item
    return ordered, catalog


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


def selected_material_label_codes(project: Path, payload: Mapping[str, Any]) -> list[str]:
    """Return only labels evidenced by the exact materials selected for this task.

    Positive annotations contribute their box labels. Explicit confirmed-empty
    samples contribute their scoped labels. Historical '*' negatives do not
    manufacture project-wide choices because the original concrete scope is no
    longer knowable.
    """

    selected_ids = _unique_codes(
        [
            *(payload.get("train_image_ids") or []),
            *(payload.get("val_image_ids") or []),
            *(payload.get("test_image_ids") or []),
            *(payload.get("selected_image_ids") or []),
        ]
    )
    if not selected_ids:
        return []
    annotations = AnnotationRepository(project)
    encountered: list[str] = []
    seen: set[str] = set()
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
            for value in annotation.get("annotation_scope") or []:
                code = str(value or "").strip()
                if code and code != "*" and code not in seen:
                    seen.add(code)
                    encountered.append(code)

    project_order, catalog = _project_label_catalog(project)
    invalid = [code for code in encountered if code not in catalog]
    if invalid:
        raise ValueError(
            "训练素材包含未映射、已删除或已停用的标签: "
            + ", ".join(invalid[:10])
            + "；请先在标签管理中统一后再训练"
        )
    temporary = [code for code in encountered if _temporary_or_unmapped_label(code)]
    if temporary:
        raise ValueError(
            "训练素材包含临时/未知标签: "
            + ", ".join(temporary[:10])
            + "；class_x / unknown / temp_* 不能进入正式训练"
        )
    rank = {code: index for index, code in enumerate(project_order)}
    return sorted(encountered, key=lambda code: (rank.get(code, 10**9), encountered.index(code), code))


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


def _iteration_version(
    algorithm: Mapping[str, Any],
    mother_model: str,
) -> Mapping[str, Any] | None:
    versions = list(algorithm.get("versions") or [])
    if not versions:
        return None
    selection = choose_algorithm_iteration_base(
        algorithm,
        mother_model,
        "ultralytics",
        strict_latest=True,
        artifact_validator=lambda path: path.is_file() and path.stat().st_size > 0,
    )
    version_id = str(selection.get("base_version_id") or "")
    return next((row for row in versions if str(row.get("id") or "") == version_id), None)


def resolve_training_label_contract(
    data_dir: str | Path,
    project: str | Path,
    payload: Mapping[str, Any],
    algorithm: Mapping[str, Any],
) -> dict[str, Any]:
    """Resolve the only label schema that may reach YOLO for this task.

    First training: user-selected labels from selected materials only.
    Iteration: previous version schema is immutable and inherited; user-selected
    material labels may append new classes. Mother-model classes never enter the
    contract.
    """

    data_root = Path(data_dir).resolve()
    project_path = Path(project).resolve()
    project_order, catalog = _project_label_catalog(project_path)
    project_rank = {code: index for index, code in enumerate(project_order)}
    available = selected_material_label_codes(project_path, payload)
    available_set = set(available)
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
    previous = _iteration_version(algorithm, mother)

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
    dropped_inherited = [code for code in inherited_codes if code not in catalog]
    retained_inherited: list[dict[str, Any]] = []
    for item in inherited:
        code = str(item["code"])
        if code not in catalog:
            continue
        normalized = dict(item)
        normalized["class_id"] = len(retained_inherited)
        normalized["source"] = "previous_version"
        retained_inherited.append(normalized)
    retained_inherited_codes = [str(item["code"]) for item in retained_inherited]
    retained_inherited_set = set(retained_inherited_codes)

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
    if dropped_inherited:
        schema_change_reasons.append("removed_or_inactive_labels")
    if requested_new:
        schema_change_reasons.append("added_labels")
    label_schema_changed = bool(schema_change_reasons)

    # Training always starts from model weights, never optimizer/trainer state.
    # If schema changed, stale previous classes are dropped and current classes
    # are reindexed contiguously before Ultralytics receives the dataset.
    effective = [dict(item) for item in retained_inherited]
    for code in requested_new:
        source = dict(catalog[code])
        source.pop("project_class_id", None)
        source["code"] = code
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
        "inherited_label_codes": inherited_codes,
        "retained_inherited_label_codes": retained_inherited_codes,
        "dropped_inherited_label_codes": dropped_inherited,
        "effective_label_codes": [str(item["code"]) for item in effective],
        "effective_label_schema": effective,
        "label_schema_changed": label_schema_changed,
        "label_schema_change_reasons": schema_change_reasons,
        "base_version_id": None if previous is None else str(previous.get("id") or ""),
        "base_version_name": "" if previous is None else str(previous.get("version_name") or ""),
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


def _scoped_selected_project_images(materials, project: Path, image_ids: Sequence[str]):
    rows = _ORIGINAL_SELECTED_PROJECT_IMAGES(materials, project, image_ids)
    contract = _contract_for_project(project)
    if contract is None:
        return rows
    allowed = set(contract["effective_label_codes"])
    annotations = AnnotationRepository(project)
    projected: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        image_id = str(row.get("id") or "")
        annotation = annotations.get(image_id)
        state = str(annotation.get("annotation_state") or "unannotated")
        raw_scope = [str(value) for value in annotation.get("annotation_scope") or []]
        boxes = list(annotation.get("boxes") or [])
        selected_boxes = [
            dict(box) for box in boxes
            if str(box.get("label") or box.get("code") or "").strip() in allowed
        ]
        present = sorted({
            str(box.get("label") or box.get("code") or "").strip()
            for box in boxes
            if str(box.get("label") or box.get("code") or "").strip()
        })
        task_filtered_negative = state == "annotated" and not selected_boxes
        row["source_annotation_state"] = state
        row["source_labels"] = present
        if task_filtered_negative:
            # Material selection decides whether the image participates in this task;
            # the task label contract decides which classes are positive. If all
            # source boxes belong to unselected classes, keep the image and project
            # it to an intentional task-local background sample. Source Ground Truth
            # in AnnotationRepository is never mutated.
            row["annotation_state"] = "confirmed_empty"
            row["annotated"] = True
            row["boxes"] = []
            row["annotation_scope"] = sorted(allowed)
            row["negative_origin"] = "filtered_by_training_labels"
        else:
            row["annotation_state"] = state
            row["annotated"] = state in {"annotated", "confirmed_empty"}
            row["boxes"] = selected_boxes if state == "annotated" else []
            if state == "annotated":
                explicit = {value for value in raw_scope if value and value != "*"}
                row["annotation_scope"] = sorted((explicit & allowed) | {
                    str(box.get("label") or box.get("code") or "").strip()
                    for box in selected_boxes
                })
            else:
                row["annotation_scope"] = raw_scope
                if state == "confirmed_empty":
                    row["negative_origin"] = str(row.get("negative_origin") or "explicit_confirmed_empty")
        # The persisted annotation hash describes the full Ground Truth. Once
        # boxes are projected to this task schema, Snapshot must hash the task
        # projection instead of reusing the full-project digest.
        row.pop("annotation_hash", None)
        projected.append(row)
    return projected


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
    path = project / "algorithms.json"
    algorithms = list_algorithms(path)
    changed = False
    for algorithm in algorithms:
        if str(algorithm.get("id") or "") != str(contract.get("algorithm_id") or ""):
            continue
        for version in algorithm.get("versions") or []:
            if str(version.get("task_id") or version.get("job_id") or "") != str(task_id):
                continue
            version["label_schema"] = [dict(item) for item in contract.get("effective_label_schema") or []]
            version["label_codes"] = list(contract.get("effective_label_codes") or [])
            version["label_contract"] = {
                "schema_version": int(contract.get("schema_version") or 1),
                "requested_label_codes": list(contract.get("requested_label_codes") or []),
                "inherited_label_codes": list(contract.get("inherited_label_codes") or []),
                "retained_inherited_label_codes": list(contract.get("retained_inherited_label_codes") or []),
                "dropped_inherited_label_codes": list(contract.get("dropped_inherited_label_codes") or []),
                "label_schema_changed": bool(contract.get("label_schema_changed")),
                "label_schema_change_reasons": list(contract.get("label_schema_change_reasons") or []),
                "base_training_mode": contract.get("base_training_mode"),
                "strict_resume": False,
                "optimizer_state_resumed": False,
                "base_version_id": contract.get("base_version_id"),
                "mother_model_labels_inherited": False,
            }
            changed = True
            break
    if changed:
        save_algorithms(path, algorithms)


class LabelContractTrainingHandler(base.TrainingHandler):
    def _contract(self, context, payload: Mapping[str, Any]) -> tuple[Path, dict[str, Any]]:
        project = self.data_dir / "projects" / context.task.project_id
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
