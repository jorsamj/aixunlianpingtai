"""Confirmed product actions derived from version-owned iteration decisions."""
from __future__ import annotations
import hashlib, json
from typing import Any, Mapping

ACTION_SCHEMA_VERSION = 1
ACTION_BY_DECISION = {
    "needs_data": "supplement_data",
    "continue_training": "continue_training",
    "ready_for_business_validation": "business_validation",
    "review_required": "manual_review",
}

def _text(value: object, limit: int = 1000) -> str:
    return str(value or "").strip()[:limit]

def _sha(value: object, field: str, *, optional: bool = False) -> str:
    value = _text(value, 128).lower()
    if optional and not value:
        return ""
    if len(value) != 64 or any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{field} must be a SHA256 identity")
    return value

def build_confirmed_iteration_action(*, algorithm_id: str, version: Mapping[str, Any],
                                     requested_action: str, decision_id: str,
                                     confirmed_at: str) -> dict[str, Any]:
    decision = version.get("iteration_decision")
    evaluation = version.get("evaluation")
    if not isinstance(decision, Mapping) or not isinstance(evaluation, Mapping):
        raise ValueError("algorithm version has no persisted iteration decision/evaluation truth")
    persisted_decision_id = _sha(decision.get("decision_id"), "decision_id")
    if _sha(decision_id, "decision_id") != persisted_decision_id:
        raise ValueError("iteration decision changed; refresh before confirming an action")
    expected_action = ACTION_BY_DECISION.get(_text(decision.get("decision"), 100))
    action = _text(requested_action, 100)
    if action != expected_action:
        raise ValueError("confirmed action does not match the persisted iteration decision")
    if decision.get("requires_confirmation") is not True or decision.get("automatic_execution") is not False:
        raise ValueError("iteration decision confirmation contract is invalid")
    evaluation_id = _sha(evaluation.get("evaluation_id"), "evaluation_id")
    if _sha(decision.get("evaluation_id"), "decision.evaluation_id") != evaluation_id:
        raise ValueError("iteration decision/evaluation identity mismatch")

    dataset_revision_id = _sha(
        evaluation.get("dataset_revision_id") or version.get("dataset_revision_id"),
        "dataset_revision_id", optional=True,
    )
    source = {
        "decision_id": persisted_decision_id,
        "evaluation_id": evaluation_id,
        "algorithm_id": _text(algorithm_id, 200),
        "version_id": _text(version.get("id") or version.get("version_id"), 200),
        "dataset_revision_id": dataset_revision_id,
        "snapshot_id": _text(evaluation.get("snapshot_id") or version.get("snapshot_id"), 256),
    }
    weak_labels = list(dict.fromkeys(
        _text(v, 1000) for v in list(decision.get("weak_labels") or []) if _text(v, 1000)
    ))
    identity = {
        "schema_version": ACTION_SCHEMA_VERSION,
        "action": action,
        "status": "confirmed",
        "source": source,
        "weak_labels": weak_labels,
    }
    action_id = hashlib.sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode()).hexdigest()
    result = {
        **identity,
        "action_id": action_id,
        "confirmed_at": _text(confirmed_at, 100),
        "automatic_execution": False,
        "requires_user_submit": action == "continue_training",
    }
    if action == "supplement_data":
        result["data_draft"] = {
            "weak_labels": weak_labels,
            "problem_samples": [
                {
                    "image": _text(row.get("image"), 1000),
                    "fp_count": max(0, int(row.get("fp_count") or 0)),
                    "fn_count": max(0, int(row.get("fn_count") or 0)),
                    "fp_labels": [_text(v, 1000) for v in list(row.get("fp_labels") or [])[:100] if _text(v, 1000)],
                    "fn_labels": [_text(v, 1000) for v in list(row.get("fn_labels") or [])[:100] if _text(v, 1000)],
                }
                for row in list(evaluation.get("error_samples") or [])[:200]
                if isinstance(row, Mapping)
            ],
            "dataset_revision_id": dataset_revision_id,
            "snapshot_id": source["snapshot_id"],
        }
    elif action == "continue_training":
        result["training_draft"] = {
            "algorithm_id": source["algorithm_id"],
            "base_version_id": source["version_id"],
            "focus_labels": weak_labels,
            "dataset_revision_id": dataset_revision_id,
            "snapshot_id": source["snapshot_id"],
        }
    elif action == "business_validation":
        result["validation_entry"] = {
            "algorithm_id": source["algorithm_id"],
            "version_id": source["version_id"],
            "model_sha256": _sha(evaluation.get("model_sha256"), "model_sha256", optional=True),
        }
    return result

def training_action_context(action: Mapping[str, Any]) -> dict[str, str]:
    if not isinstance(action, Mapping) or action.get("action") != "continue_training":
        raise ValueError("confirmed action is not a continue-training action")
    source = action.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("confirmed action source lineage is missing")
    return {
        "action_id": _sha(action.get("action_id"), "action_id"),
        "decision_id": _sha(source.get("decision_id"), "decision_id"),
        "evaluation_id": _sha(source.get("evaluation_id"), "evaluation_id"),
        "version_id": _text(source.get("version_id"), 200),
        "dataset_revision_id": _sha(source.get("dataset_revision_id"), "dataset_revision_id", optional=True),
        "snapshot_id": _text(source.get("snapshot_id"), 256),
    }
