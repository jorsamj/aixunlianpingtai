"""Stable, public-safe training provenance persisted on algorithm versions."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Iterable, Mapping

TRAINING_LINEAGE_SCHEMA_VERSION = 1
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_PARAM_KEYS = {
    "epochs", "imgsz", "batch", "device", "patience", "workers", "optimizer",
    "resource_strategy", "resource_profile", "gpu_policy", "precision", "time",
    "lr0", "lrf", "weight_decay", "close_mosaic", "mosaic", "cache",
    "single_cls", "pretrained", "rect", "amp", "cos_lr", "freeze",
    "momentum", "warmup_epochs", "save_period", "seed", "deterministic",
    "multi_scale", "hsv_h", "hsv_s", "hsv_v", "degrees", "translate",
    "scale", "shear", "perspective", "flipud", "fliplr", "mixup",
}
_EXECUTION_KEYS = {
    "mode", "worker_id", "node_id", "execution_generation", "requested_device",
    "assigned_device", "actual_device", "resource_id", "resource_name",
    "gpu_id", "gpu_uuid", "gpu_name", "gpu_index",
}
_ARTIFACT_KEYS = {
    "role", "artifact_id", "file_name", "model_name", "sha256", "size_bytes",
    "storage_source_id", "object_key", "verified",
}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _sha256(value: Any, field: str) -> str:
    normalized = _text(value).lower()
    if normalized and not _SHA256.fullmatch(normalized):
        raise ValueError(f"{field} must be a SHA256 hex digest")
    return normalized


def _primitive_mapping(value: Mapping[str, Any] | None, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in sorted(allowed):
        item = value.get(key)
        if item is None or item == "":
            continue
        if isinstance(item, (str, int, float, bool)):
            result[key] = item
    return result


def _safe_model_name(value: Any) -> str:
    text = _text(value).replace("\\", "/")
    return Path(text).name if text else ""


def _iteration_action(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    source = value.get("source")
    source = source if isinstance(source, Mapping) else value
    result: dict[str, Any] = {}
    if action := _text(value.get("action")):
        result["action"] = action
    if action_id := _sha256(value.get("action_id"), "iteration_action.action_id"):
        result["action_id"] = action_id
    for key in ("decision_id", "evaluation_id", "dataset_revision_id"):
        if digest := _sha256(source.get(key), f"iteration_action.{key}"):
            result[key] = digest
    for key in ("version_id", "snapshot_id"):
        if item := _text(source.get(key)):
            result[key] = item
    return result


def _supplement_provenance(value: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result = {
        "schema_version": int(value.get("schema_version") or 0),
        "candidate_set_id": _sha256(value.get("candidate_set_id"), "supplement.candidate_set_id"),
        "adoption_id": _sha256(value.get("adoption_id"), "supplement.adoption_id"),
        "action_id": _sha256(value.get("action_id"), "supplement.action_id"),
        "algorithm_id": _text(value.get("algorithm_id")),
        "version_id": _text(value.get("version_id")),
        "source_candidate_count": max(0, int(value.get("source_candidate_count") or 0)),
        "adopted_candidate_count": max(0, int(value.get("adopted_candidate_count") or 0)),
        "adopted_material_count": max(0, int(value.get("adopted_material_count") or 0)),
        "adopted_feedback_ids": [_text(item) for item in list(value.get("adopted_feedback_ids") or [])[:500] if _text(item)],
        "adopted_material_ids": [_text(item) for item in list(value.get("adopted_material_ids") or [])[:500] if _text(item)],
        "automatic_execution": False,
    }
    candidates = []
    for raw in list(value.get("adopted_candidates") or [])[:500]:
        if not isinstance(raw, Mapping):
            continue
        candidates.append({
            "feedback_id": _text(raw.get("feedback_id")),
            "feedback_type": _text(raw.get("feedback_type")),
            "material_id": _text(raw.get("material_id")),
            "candidate_digest": _sha256(raw.get("candidate_digest"), "supplement.candidate_digest"),
            "annotation_hash": _sha256(raw.get("annotation_hash"), "supplement.annotation_hash"),
            "annotation_state": _text(raw.get("annotation_state")),
            "model_sha256": _sha256(raw.get("model_sha256"), "supplement.model_sha256"),
            "input_sha256": _sha256(raw.get("input_sha256"), "supplement.input_sha256"),
        })
    if result["schema_version"] != 1 or not candidates:
        raise ValueError("supplement provenance is incomplete")
    result["adopted_candidates"] = candidates
    return result


def _artifact_rows(values: Iterable[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    rows = []
    for raw in values or []:
        if not isinstance(raw, Mapping):
            continue
        row = _primitive_mapping(raw, _ARTIFACT_KEYS)
        if row.get("sha256"):
            row["sha256"] = _sha256(row["sha256"], "artifact.sha256")
        if row.get("size_bytes") is not None:
            size = int(row["size_bytes"])
            if size < 0:
                raise ValueError("artifact.size_bytes must be nonnegative")
            row["size_bytes"] = size
        if row:
            rows.append(row)
    return rows[:32]


def build_training_lineage(
    *,
    task_id: Any,
    snapshot_id: Any = "",
    dataset_revision_id: Any = "",
    framework: Any = "",
    base_version_id: Any = "",
    base_version_name: Any = "",
    base_model: Any = "",
    base_selection_reason: Any = "",
    execution: Mapping[str, Any] | None = None,
    requested_params: Mapping[str, Any] | None = None,
    actual_params: Mapping[str, Any] | None = None,
    iteration_action: Mapping[str, Any] | None = None,
    supplement_provenance: Mapping[str, Any] | None = None,
    artifacts: Iterable[Mapping[str, Any]] | None = None,
    training_status: Any = "",
    training_outcome: Any = "",
    completion_reason: Any = "",
    finished_at: Any = "",
) -> dict[str, Any]:
    task = _text(task_id)
    if not task:
        raise ValueError("training lineage requires task_id")
    revision = _sha256(dataset_revision_id, "dataset_revision_id")
    lineage: dict[str, Any] = {"schema_version": TRAINING_LINEAGE_SCHEMA_VERSION, "task_id": task}
    if snapshot := _text(snapshot_id):
        lineage["snapshot_id"] = snapshot
    if revision:
        lineage["dataset_revision_id"] = revision
    if framework_name := _text(framework):
        lineage["framework"] = framework_name.lower()

    base = {}
    if value := _text(base_version_id):
        base["version_id"] = value
    if value := _text(base_version_name):
        base["version_name"] = value
    if value := _safe_model_name(base_model):
        base["model"] = value
    if value := _text(base_selection_reason):
        base["selection_reason"] = value
    if base:
        lineage["base"] = base

    execution_value = _primitive_mapping(execution, _EXECUTION_KEYS)
    worker_id = _text(execution_value.get("worker_id"))
    if worker_id.startswith("agent:") and not execution_value.get("node_id"):
        execution_value["node_id"] = worker_id.split(":", 1)[1]
    if execution_value:
        lineage["execution"] = execution_value

    parameters = {}
    requested = _primitive_mapping(requested_params, _PARAM_KEYS)
    actual = _primitive_mapping(actual_params, _PARAM_KEYS)
    if requested:
        parameters["requested"] = requested
    if actual:
        parameters["actual"] = actual
    if parameters:
        lineage["parameters"] = parameters

    action = _iteration_action(iteration_action)
    if action:
        lineage["iteration_action"] = action

    supplement = _supplement_provenance(supplement_provenance)
    if supplement:
        lineage["supplement_provenance"] = supplement

    artifact_rows = _artifact_rows(artifacts)
    if artifact_rows:
        lineage["artifacts"] = artifact_rows

    outcome = {}
    if value := _text(training_status):
        outcome["status"] = value
    if value := _text(training_outcome):
        outcome["training_outcome"] = value
    if value := _text(completion_reason):
        outcome["completion_reason"] = value
    if value := _text(finished_at):
        outcome["finished_at"] = value
    if outcome:
        lineage["outcome"] = outcome
    return lineage
