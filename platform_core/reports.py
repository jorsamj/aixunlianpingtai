from typing import Any, Mapping, Sequence
import math


def diagnose_training_history(history: Sequence[Mapping[str, Any]]) -> dict:
    """Explain observed trends; hypotheses are never asserted as root causes."""
    rows = [row for row in history if isinstance(row, Mapping)][-1000:]
    def number(row, key):
        value = row.get(key)
        if value is None:
            value = (row.get('losses') or {}).get(key)
        try:
            result = float(value)
            return result if math.isfinite(result) else None
        except (TypeError, ValueError):
            return None
    paired = [(number(row, 'box_loss'), number(row, 'val_box_loss')) for row in rows]
    paired = [(train, val) for train, val in paired if train is not None and val is not None]
    findings = []
    if len(paired) >= 10:
        window = max(3, len(paired) // 4)
        first_train = sum(train for train, _ in paired[:window]) / window
        last_train = sum(train for train, _ in paired[-window:]) / window
        first_val = sum(val for _, val in paired[:window]) / window
        last_val = sum(val for _, val in paired[-window:]) / window
        if first_train > 0 and first_val > 0 and last_train < first_train * .85 and last_val > first_val * 1.15:
            findings.append({
                'code': 'GENERALIZATION_GAP', 'severity': 'warning', 'confidence': 'trend_signal',
                'phenomenon': '训练损失下降而验证损失上升',
                'evidence': {'paired_epochs': len(paired), 'window': window,
                             'train_before': first_train, 'train_after': last_train,
                             'val_before': first_val, 'val_after': last_val},
                'possible_causes': ['可能过拟合', '训练与验证分布可能不同', '标注或场景覆盖需要复核'],
                'action': '先检查验证样本和数据隔离，再决定是否调整训练参数。',
            })
    metrics = []
    for row in rows:
        value = row.get('map50', (row.get('metrics') or {}).get('metrics/mAP50(B)'))
        try:
            if value is not None and math.isfinite(float(value)):
                metrics.append((row.get('epoch'), float(value)))
        except (TypeError, ValueError):
            pass
    best = max(metrics, key=lambda item: item[1]) if metrics else None
    if len(metrics) >= 10:
        recent = [value for _, value in metrics[-10:]]
        spread = max(recent) - min(recent)
        average = sum(recent) / len(recent)
        deviation = math.sqrt(sum((value-average)**2 for value in recent) / len(recent))
        improvement = sum(recent[-3:])/3 - sum(recent[:3])/3
        signal = None
        if spread <= .005:
            signal = ('METRIC_PLATEAU', '最近10条 mAP50 记录改善有限',
                      '可能已收敛，也可能需要检查数据、参数或评测集覆盖。',
                      '先复核错误类别；不要仅因平台期增加轮次。')
        elif deviation >= .1 and spread >= .2:
            signal = ('METRIC_INSTABILITY', '最近10条 mAP50 记录明显波动',
                      '可能存在评测抽样变化、样本差异或训练不稳定。',
                      '核查每轮评测范围、学习率与异常日志。')
        elif improvement >= .02:
            signal = ('LATE_IMPROVEMENT', '已记录末段 mAP50 仍在改善',
                      '可能仍有改善空间，但不能仅凭趋势认定训练不足。',
                      '结合停止原因、资源成本与独立 Test 再决定是否继续。')
        if signal:
            code, phenomenon, cause, action = signal
            findings.append({'code':code, 'severity':'info', 'confidence':'trend_signal',
                             'phenomenon':phenomenon, 'evidence':{
                                 'metric_records':10,'range':spread,'standard_deviation':deviation,
                                 'last_three_vs_first_three':improvement},
                             'evidence_summary':f'最近10条记录：范围 {spread:.4f}，标准差 {deviation:.4f}，末3条较首3条均值变化 {improvement:+.4f}。',
                             'possible_causes':[cause], 'action':action})
    return {'evidence_epochs': len(rows), 'paired_loss_epochs': len(paired),
            'best_observed_epoch': best[0] if best else None,
            'best_observed_map50': best[1] if best else None,
            'findings': findings,
            'status': 'analyzed' if len(paired) >= 10 or len(metrics) >= 10 else 'insufficient_evidence',
            'note': '基于已记录曲线的趋势信号，不能证明根因或业务验收通过。'}


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
        "evaluation": dict(
            record.get("evaluation")
            if isinstance(record.get("evaluation"), Mapping)
            else training_report.get("test_result")
            if isinstance(training_report.get("test_result"), Mapping)
            else {}
        ),
        # Do not compute or infer credibility here. Only finalized durable
        # training truth may assert the high-mAP advisory; old reports stay
        # explicitly unavailable instead of laundering current library data.
        "metric_credibility": dict(record["metric_credibility"])
        if isinstance(record.get("metric_credibility"), Mapping) else None,
        "error_samples": list(training_report.get("error_samples") or []),
        "artifacts": list(record.get("verified_models") or record.get("models") or []),
        "artifact_verified": bool(record.get("artifact_verified")),
        "status": record.get("status") or "",
        "created_at": record.get("created_at") or "",
        "finished_at": record.get("finished_at") or "",
        'dataset_revision_id': record.get('dataset_revision_id') or '',
        'completion_reason': record.get('completion_reason') or '',
        'training_outcome': record.get('training_outcome') or '',
        'completed_epochs': record.get('current_epoch'),
        'dataset_counts': dict(record.get('dataset_counts') or {}),
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
