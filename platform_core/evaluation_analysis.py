"""Read-only, bounded explanations of frozen evaluation evidence.

No image reads, GT writes, rescoring, synthetic quality score or task owner.
Missing historical evidence is deliberately not a passing check.
"""
from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Mapping

from .training_evaluation import build_evaluation_benchmark_scope, compare_evaluations


def _digest(value):
    return isinstance(value, str) and re.fullmatch(r"[a-f0-9]{64}", value) is not None


def evaluation_samples(evaluation: Mapping, *, offset=0, limit=24, issue="", class_id=None, sort="severity"):
    """Paginate persisted formal outcomes; absent legacy samples stay unknown."""
    complete = isinstance(evaluation.get('sample_outcomes'), list)
    outcomes = evaluation.get('sample_outcomes') if complete else evaluation.get('error_samples', [])
    evidence = evaluation.get('sample_evidence') if complete else evaluation.get('error_samples', [])
    indexed = {(row.get('image_id'), row.get('image_content_sha256')): row for row in evidence or []}
    rows = []
    for outcome in outcomes:
        sample = dict(outcome)
        detail = indexed.get((sample.get('image_id'), sample.get('image_content_sha256')))
        if detail:
            sample.update(detail)
        sample['box_evidence_available'] = bool(detail and isinstance(detail.get('gt_boxes'), list)
                                                 and isinstance(detail.get('pred_boxes'), list))
        kinds = set(sample.get('diagnostic_tags') or [])
        for box in sample.get('pred_boxes', []):
            kinds.update(box.get('diagnostic_tags') or [])
            confidence = box.get('confidence')
            if isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and 0 <= confidence < .5:
                kinds.add('low_confidence')
        kinds.update(key for key in ('fp', 'fn', 'tp') if sample.get(f'{key}_count', 0) > 0)
        if issue and issue not in kinds:
            continue
        if class_id is not None and not any(box.get('class_id') == class_id for box in
                list(sample.get('gt_boxes', [])) + list(sample.get('pred_boxes', []))):
            continue
        rows.append(sample)
    if sort == 'high_confidence_fp':
        rows.sort(key=lambda row: (-max((box.get('confidence', 0) for box in row.get('pred_boxes', [])
                                         if box.get('matched') is False), default=-1), row.get('image', '')))
    else:
        rows.sort(key=lambda row: (-row.get('fn_count', 0), -row.get('fp_count', 0), row.get('image', '')))
    box_filter = class_id is not None or issue in {'wrong_class', 'localization', 'low_confidence', 'duplicate'}
    return {'items': rows[offset:offset + limit], 'total': len(rows), 'offset': offset, 'limit': limit,
            'cohort_complete': complete and len(outcomes) == evaluation.get('image_count'),
            'image_count': evaluation.get('image_count'), 'evaluation_id': evaluation.get('evaluation_id'),
            'diagnostic_low_confidence_threshold': .5,
            'filter_scope': 'retained_box_evidence_only' if box_filter else 'persisted_sample_outcomes',
            'filter_evidence_complete': not box_filter or complete and all(row.get('evidence_complete') is True for row in outcomes)}


def compare_sample_outcomes(source: Mapping, current: Mapping, *, offset=0, limit=24, category=""):
    """Explain original comparison using persisted counts; never rematch boxes."""
    comparison = compare_evaluations(source, current)
    comparison.update(samples=[], sample_counts={}, sample_cohort_complete=False)
    if not comparison['comparable']:
        return comparison
    counts = {}
    for side, value in (('before', source), ('after', current)):
        classes = value.get('per_class') or []
        totals = {key: sum(row[key] for row in classes) for key in ('true_positive', 'false_positive', 'false_negative')
                  if classes and all(isinstance(row.get(key), int) and row[key] >= 0 for row in classes)}
        if len(totals) == 3:
            denominator = 2 * totals['true_positive'] + totals['false_positive'] + totals['false_negative']
            totals['micro_f1'] = 2 * totals['true_positive'] / denominator if denominator and totals['true_positive'] + totals['false_negative'] > 0 else None
        counts[side] = totals
    comparison['detection_counts'] = counts
    def index(value):
        rows = value.get('sample_outcomes')
        if not isinstance(rows, list):
            return {}, False
        result = {}
        for row in rows:
            key = row.get('image_id')
            if not key or key in result:
                return {}, False
            result[key] = row
        return result, len(rows) == value.get('image_count')
    before, before_complete = index(source)
    after, after_complete = index(current)
    counts = {key: 0 for key in ('improved', 'regressed', 'persistent_error', 'persistent_correct', 'unknown')}
    rows = []
    def details(value, row):
        detail = next((item for item in value.get('sample_evidence', []) if
                       item.get('image_id') == row.get('image_id') and
                       item.get('image_content_sha256') == row.get('image_content_sha256') and
                       item.get('ground_truth_digest') == row.get('ground_truth_digest')), None)
        return {**row, **(detail or {}), 'box_evidence_available': detail is not None}
    for key in sorted(set(before) | set(after)):
        a, b = before.get(key), after.get(key)
        kind, reason = 'unknown', 'sample_evidence_missing'
        if a and b:
            matching = all(a.get(field) == b.get(field) and a.get(field) is not None for field in (
                'image_content_sha256', 'ground_truth_digest', 'image_width', 'image_height'))
            valid_counts = all(isinstance(row.get(field), int) and not isinstance(row.get(field), bool)
                               and row[field] >= 0 for row in (a, b) for field in ('tp_count', 'fp_count', 'fn_count'))
            if matching and _digest(a.get('image_content_sha256')) and _digest(a.get('ground_truth_digest')) and valid_counts:
                old_error, new_error = a['fp_count'] + a['fn_count'] > 0, b['fp_count'] + b['fn_count'] > 0
                kind = ('persistent_error' if new_error else 'improved') if old_error else ('regressed' if new_error else 'persistent_correct')
                reason = 'same_frozen_ground_truth_formal_counts'
            else:
                reason = 'sample_identity_or_ground_truth_mismatch'
        counts[kind] += 1
        if not category or kind == category:
            rows.append({'image_id': key, 'category': kind, 'reason': reason,
                         'before': a, 'after': b})
    page = [{**row, 'before': details(source, row['before']) if row['before'] else None,
             'after': details(current, row['after']) if row['after'] else None} for row in rows[offset:offset + limit]]
    comparison.update(samples=page, total=len(rows), offset=offset, limit=limit,
                      sample_counts=counts, sample_cohort_complete=before_complete and after_complete and set(before) == set(after),
                      sample_scope='formal_counts_on_identical_frozen_images_and_ground_truth')
    return comparison


def analyze_evaluation_trust(evaluation: Mapping, snapshot: Mapping, version: Mapping,
                             *, verified_model: Mapping | None = None,
                             detail_offset: int = 0, detail_limit: int = 20) -> dict[str, Any]:
    """Check immutable records, never substitute present-day GT for frozen GT."""
    checks = []
    offset, limit = max(0, detail_offset), min(50, max(1, detail_limit))

    def add(code, title, status, details=(), explanation=""):
        checks.append(dict(code=code, title=title, status=status, count=len(details),
                           details=list(details[offset:offset + limit]),
                           explanation=explanation, offset=offset, limit=limit))

    records = [row for row in snapshot.get("images", []) if isinstance(row, Mapping)]
    declared = snapshot.get("ids") or {}
    memberships = defaultdict(set)
    for role, key in (("train", "train_image_ids"), ("validation", "val_image_ids"), ("test", "test_image_ids")):
        for image_id in declared.get(role, snapshot.get(key, [])):
            memberships[str(image_id)].add(role)
    for row in records:
        if row.get("role") in {"train", "validation", "test"}:
            memberships[str(row.get("image_id"))].add(row["role"])
    ids = [str(row.get("image_id") or "") for row in records]
    malformed = not records or len(set(ids)) != len(ids) or "" in ids
    incomplete = malformed or any(not memberships[image_id] for image_id in ids) or set(memberships) != set(ids)

    def public(row):
        return {"image_id": str(row.get("image_id") or ""),
                "roles": sorted(memberships[str(row.get("image_id"))]),
                "content_sha256": row.get("content_sha256", ""),
                "annotation_hash": row.get("annotation_hash", "")}

    identity_reasons = []
    try:
        scope = build_evaluation_benchmark_scope(snapshot)
    except (TypeError, ValueError, OverflowError):
        scope = {}
    frozen = evaluation.get("benchmark_scope") or {}
    if not scope or evaluation.get('image_count') != scope.get('test_image_count') or any(scope.get(key) != frozen.get(key) for key in (
            "content_digest", "ground_truth_digest", "label_schema_digest", "test_image_count")):
        identity_reasons.append({"reason": "benchmark_snapshot_identity_missing_or_mismatched"})
    if frozen.get("binding_level") != "bundle_verified" or any(not _digest(frozen.get(key)) for key in (
            "scope_id", "evaluation_input_digest", "content_digest", "ground_truth_digest", "label_schema_digest")):
        identity_reasons.append({"reason": "executed_input_binding_missing"})
    task_ids = {str(version.get(key)) for key in ("task_id", "job_id", "training_job_id") if version.get(key)}
    if len(task_ids) != 1 or evaluation.get("task_id") not in task_ids:
        identity_reasons.append({"reason": "training_task_binding_missing_or_mismatched"})
    if not verified_model or evaluation.get("model_sha256") != verified_model.get("model_sha256"):
        identity_reasons.append({"reason": "verified_model_binding_missing_or_mismatched"})
    snapshot_id = snapshot.get("snapshot_id")
    if not _digest(snapshot_id) or evaluation.get("snapshot_id") != snapshot_id:
        identity_reasons.append({"reason": "snapshot_binding_missing_or_mismatched"})
    if (not _digest(evaluation.get("evaluation_id")) or not _digest(evaluation.get("model_sha256"))
            or not _digest(evaluation.get("evaluation_protocol_id"))
            or not evaluation.get("finished_at") or not evaluation.get("protocol")
            or evaluation.get("status") != "succeeded"
            or not _digest(evaluation.get("dataset_revision_id"))
            or evaluation.get("dataset_revision_id") != snapshot.get("dataset_revision_id")):
        identity_reasons.append({"reason": "evaluation_evidence_incomplete"})
    if incomplete:
        identity_reasons.append({"reason": "snapshot_membership_incomplete"})
    add("identity", "评测与冻结身份", "insufficient_evidence" if identity_reasons else "passed", identity_reasons,
        "只核验持久证据关联，不代表生产原图、模型字节或GT当前版本已重新核验。")

    sha_groups = defaultdict(list)
    for row in records:
        if _digest(row.get("content_sha256")):
            sha_groups[row["content_sha256"]].append(row)
    sha_complete = not incomplete and all(_digest(row.get("content_sha256")) for row in records)
    cross, within, conflicts = [], [], []
    for sha, rows in sha_groups.items():
        roles = set().union(*(memberships[str(row.get("image_id"))] for row in rows))
        detail = {"content_sha256": sha, "members": [public(row) for row in rows[:50]],
                  "member_count": len(rows), "roles": sorted(roles)}
        if len(roles) > 1:
            cross.append(detail)
        if any(sum(role in memberships[str(row.get("image_id"))] for row in rows) > 1 for role in roles):
            within.append(detail)
        hashes = {row.get("annotation_hash") for row in rows if _digest(row.get("annotation_hash"))}
        if len(hashes) > 1:
            conflicts.append(detail)
    def status(details, complete=True):
        return "risk" if details else "passed" if complete else "insufficient_evidence"
    add("cross_split_sha256", "Train / Val / Test 同图泄漏", status(cross, sha_complete), cross)
    add("within_split_sha256", "划分内部重复", status(within, sha_complete), within)
    add("same_sha_different_gt", "同图不同 GT", status(conflicts, sha_complete and all(
        _digest(row.get("annotation_hash")) for row in records)), conflicts)

    source_groups = defaultdict(list)
    for row in records:
        for key in ("group_id", "source_ref"):
            if row.get(key):
                source_groups[(key, str(row[key]))].append(row)
    sources = [{"relation": key[0], "members": [public(row) for row in rows[:50]], "member_count": len(rows)}
               for key, rows in source_groups.items()
               if len(set().union(*(memberships[str(row.get("image_id"))] for row in rows))) > 1]
    add("source_isolation", "同来源或事件跨划分", "risk" if sources else "insufficient_evidence", sources,
        "已有group/source关系只作风险线索；未记录摄像头、事件和时间不等于独立。")
    add("near_duplicate", "不同 SHA 的视觉近重复", "not_checked", explanation=
        "已有清洗dHash可复用，但历史Snapshot未冻结感知哈希；本请求不下载整集或借用当前哈希冒充历史检查。")
    add("video_time", "视频连续帧及时间窗口", "insufficient_evidence", explanation=
        "历史Snapshot缺少可信采集时间和摄像头窗口，无法确认。source/group交叉风险另列。")

    gt_issues = [public(row) | {"reason": "unreviewed_or_missing_ground_truth"} for row in records
                 if "test" in memberships[str(row.get("image_id"))]
                 and (row.get("annotation_state") not in {"annotated", "confirmed_empty"}
                      or not _digest(row.get("annotation_hash")))]
    tests = [row for row in records if "test" in memberships[str(row.get("image_id"))]]
    add("ground_truth", "冻结 Test 正式 GT", status(gt_issues, bool(tests) and not incomplete), gt_issues,
        "confirmed_empty仅接受冻结的显式状态；空标注不自动视为负样本。")
    add("review_version", "GT 版本与人工审核", "insufficient_evidence", explanation=
        "annotation_hash可校验冻结内容；历史Snapshot未保存逐图annotation_version和完整人工审核回执，不能补造。")
    coverage = []
    for label in snapshot.get("label_schema", []):
        if not isinstance(label, Mapping):
            continue
        code = str(label.get("code") or "")
        count = sum(code in (row.get("labels") or []) for row in tests)
        coverage.append({"class_id": label.get("class_id"), "label": code, "image_count": count,
                         "status": "covered" if count else "not_covered"})
    return {"schema_version": 1, "evaluation_id": evaluation.get("evaluation_id", ""),
            "snapshot_id": snapshot_id or "", "checks": checks, "coverage": coverage,
            "read_only": True, "production_verification": "NOT VERIFIED"}
