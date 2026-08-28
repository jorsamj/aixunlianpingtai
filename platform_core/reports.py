from typing import Any, Mapping, Sequence


def _metrics(record: Mapping[str, Any]) -> dict:
    direct = record.get("metrics")
    if isinstance(direct, Mapping):
        return dict(direct)
    for container_key in ("training_report", "report"):
        container = record.get(container_key)
        if isinstance(container, Mapping) and isinstance(container.get("metrics"), Mapping):
            return dict(container["metrics"])
    return {}


def _map50(record: Mapping[str, Any]) -> float | None:
    metrics = _metrics(record)
    for key in ("map50", "mAP50", "metrics/mAP50(B)"):
        if metrics.get(key) is not None:
            try:
                return float(metrics[key])
            except (TypeError, ValueError):
                pass
    return None


def build_version_report(record: Mapping[str, Any]) -> dict:
    training_report = record.get("training_report") if isinstance(record.get("training_report"), Mapping) else {}
    return {
        "report_type": "version",
        "job_id": record.get("id") or record.get("job_id"),
        "version_id": record.get("version_id") or record.get("auto_version_id"),
        "version_name": record.get("version_name") or record.get("auto_version_name") or "",
        "snapshot_id": record.get("snapshot_id") or "",
        "base_version_id": record.get("base_version_id"),
        "base_version_name": record.get("base_version_name") or "",
        "base_model_path": record.get("base_model_path") or record.get("model") or "",
        "base_selection_reason": record.get("base_selection_reason") or "",
        "metrics": _metrics(record),
        "requested_train_params": dict(record.get("requested_train_params") or {}),
        "actual_train_params": dict(record.get("actual_train_params") or {}),
        "gate_events": list(training_report.get("gate_events") or record.get("gate_events") or []),
        "error_samples": list(training_report.get("error_samples") or []),
        "artifacts": list(record.get("verified_models") or record.get("models") or []),
        "artifact_verified": bool(record.get("artifact_verified")),
        "status": record.get("status") or "",
        "created_at": record.get("created_at") or "",
        "finished_at": record.get("finished_at") or "",
    }


def build_algorithm_report(versions: Sequence[Mapping[str, Any]]) -> dict:
    ordered = sorted(
        [dict(version) for version in versions],
        key=lambda version: str(version.get("finished_at") or version.get("created_at") or version.get("version_name") or ""),
    )
    trend = [
        {
            "version_id": version.get("id"),
            "version_name": version.get("version_name") or "",
            "finished_at": version.get("finished_at") or version.get("created_at") or "",
            "map50": _map50(version),
        }
        for version in ordered
    ]
    with_metrics = [item for item in trend if item["map50"] is not None]
    latest_vs_previous = {"latest_version": "", "previous_version": "", "map50_delta": None}
    if len(with_metrics) >= 2:
        previous, latest = with_metrics[-2], with_metrics[-1]
        latest_vs_previous = {
            "latest_version": latest["version_name"],
            "previous_version": previous["version_name"],
            "map50_delta": round(float(latest["map50"]) - float(previous["map50"]), 4),
        }
    best = max(with_metrics, key=lambda item: float(item["map50"])) if with_metrics else None
    return {
        "report_type": "algorithm",
        "version_count": len(ordered),
        "trend": trend,
        "latest_vs_previous": latest_vs_previous,
        "best_version": best["version_name"] if best else "",
        "best_map50": best["map50"] if best else None,
    }
