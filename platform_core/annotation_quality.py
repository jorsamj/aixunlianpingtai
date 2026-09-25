"""Read-only annotation quality audit for frozen CLEAN selections.

This module never mutates AnnotationRepository ground truth. Local and remote
CLEAN executions call the same control-plane audit after image-quality results
have been committed into the frozen selection database.
"""
from __future__ import annotations

import json
import math
import statistics
from pathlib import Path
from typing import Any, Mapping

from .annotation_repository import AnnotationRepository
from .annotations import annotation_summary
from .material_repository import MaterialRepository


AUDIT_META_KEY = "annotation_audit_summary"
AUDIT_PAGE_LIMIT = 200
AUDIT_MAX_IOU_BOXES = 300
_TINY_AREA_RATIO = 0.0001
_LARGE_AREA_RATIO = 0.90
_DUPLICATE_IOU = 0.95


def _label_catalog(project_path: Path) -> tuple[set[str], set[str]]:
    path = project_path / "meta.json"
    if not path.is_file():
        return set(), set()
    try:
        meta = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError):
        return set(), set()
    labels = list(meta.get("labels") or [])
    label_meta = list(meta.get("label_meta") or [])
    known, disabled = set(), set()
    for index, raw in enumerate(labels):
        code = str(raw or "").strip()
        if not code:
            continue
        known.add(code)
        info = label_meta[index] if index < len(label_meta) and isinstance(label_meta[index], dict) else {}
        if str(info.get("status") or "active").strip().lower() in {"disabled", "inactive"}:
            disabled.add(code)
    return known, disabled


def _finite_box(box: Mapping[str, Any]) -> tuple[float, float, float, float] | None:
    try:
        values = tuple(float(box[key]) for key in ("x1", "y1", "x2", "y2"))
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) for value in values):
        return None
    return values  # type: ignore[return-value]


def _iou(first: tuple[float, float, float, float], second: tuple[float, float, float, float]) -> float:
    ax1, ay1, ax2, ay2 = first
    bx1, by1, bx2, by2 = second
    iw = max(0.0, min(ax2, bx2) - max(ax1, bx1))
    ih = max(0.0, min(ay2, by2) - max(ay1, by1))
    intersection = iw * ih
    if intersection <= 0:
        return 0.0
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    area_b = max(0.0, bx2 - bx1) * max(0.0, by2 - by1)
    union = area_a + area_b - intersection
    return intersection / union if union > 0 else 0.0


def _issue_collector():
    issues: dict[str, dict[str, Any]] = {}

    def add(code: str, name: str, detail: str) -> None:
        current = issues.get(code)
        if current is None:
            issues[code] = {
                "code": code,
                "name": name,
                "detail": detail,
                "severity": "warning",
                "count": 1,
            }
        else:
            current["count"] = int(current.get("count") or 1) + 1

    return issues, add


def _audit_boxes(
    boxes: list[Mapping[str, Any]],
    *,
    width: int,
    height: int,
    known_labels: set[str],
    disabled_labels: set[str],
) -> tuple[list[dict[str, Any]], float, dict[str, int], list[int]]:
    issues, add = _issue_collector()
    image_area = float(width * height) if width > 0 and height > 0 else 0.0
    density_area = 0.0
    class_counts: dict[str, int] = {}
    heatmap = [0] * 25
    exact_seen: dict[tuple[Any, ...], int] = {}
    comparable: dict[str, list[tuple[int, tuple[float, float, float, float]]]] = {}

    for index, raw in enumerate(boxes):
        box = dict(raw)
        label = str(box.get("label") or box.get("code") or "").strip()
        if not label:
            add("label_missing", "标签缺失", f"第 {index + 1} 个框没有正式标签")
        else:
            class_counts[label] = class_counts.get(label, 0) + 1
            if known_labels and label not in known_labels:
                add("label_unknown", "标签不存在", f"标签 {label} 已不在当前标签目录")
            elif label in disabled_labels:
                add("label_disabled", "标签已停用", f"标签 {label} 当前已停用")

        coords = _finite_box(box)
        if coords is None:
            add("box_invalid", "框坐标无效", f"第 {index + 1} 个框坐标无法解析")
            continue
        x1, y1, x2, y2 = coords
        box_width, box_height = x2 - x1, y2 - y1
        if box_width <= 0 or box_height <= 0:
            add("box_invalid", "框宽高无效", f"第 {index + 1} 个框宽高必须大于 0")
            continue
        if width > 0 and height > 0:
            if x1 < 0 or y1 < 0 or x2 > width or y2 > height:
                add("box_out_of_bounds", "标注框越界", f"第 {index + 1} 个框超出图片边界")
            clipped_w = max(0.0, min(x2, width) - max(x1, 0.0))
            clipped_h = max(0.0, min(y2, height) - max(y1, 0.0))
            area_ratio = (clipped_w * clipped_h) / image_area if image_area > 0 else 0.0
            density_area += clipped_w * clipped_h
            if min(box_width, box_height) < 2.0 or area_ratio < _TINY_AREA_RATIO:
                add("box_tiny", "疑似极小框", f"第 {index + 1} 个框面积占比 {area_ratio:.5f}")
            if area_ratio > _LARGE_AREA_RATIO:
                add("box_large", "疑似极大框", f"第 {index + 1} 个框面积占比 {area_ratio:.3f}")
            center_x = min(max((x1 + x2) / 2.0, 0.0), max(0.0, float(width) - 1e-9))
            center_y = min(max((y1 + y2) / 2.0, 0.0), max(0.0, float(height) - 1e-9))
            gx = min(4, int(center_x / max(1.0, width) * 5))
            gy = min(4, int(center_y / max(1.0, height) * 5))
            heatmap[gy * 5 + gx] += 1

        exact_key = (label, round(x1, 2), round(y1, 2), round(x2, 2), round(y2, 2))
        if exact_key in exact_seen:
            add(
                "box_duplicate_exact",
                "完全重复框",
                f"第 {exact_seen[exact_key] + 1} 与第 {index + 1} 个框完全重复",
            )
        else:
            exact_seen[exact_key] = index
        comparable.setdefault(label, []).append((index, coords))

    if len(boxes) > AUDIT_MAX_IOU_BOXES:
        add(
            "target_count_high",
            "单图目标数量很高",
            f"单图共有 {len(boxes)} 个目标，跳过高成本两两 IoU 全比较",
        )
    else:
        for label, candidates in comparable.items():
            for left in range(len(candidates)):
                left_index, left_box = candidates[left]
                for right in range(left + 1, len(candidates)):
                    right_index, right_box = candidates[right]
                    if tuple(round(v, 2) for v in left_box) == tuple(round(v, 2) for v in right_box):
                        continue
                    overlap = _iou(left_box, right_box)
                    if overlap >= _DUPLICATE_IOU:
                        add(
                            "box_duplicate_iou",
                            "高 IoU 同类疑似重复框",
                            f"{label or '未命名标签'} 第 {left_index + 1}/{right_index + 1} 个框 IoU={overlap:.3f}",
                        )

    density = density_area / image_area if image_area > 0 else 0.0
    return list(issues.values()), density, class_counts, heatmap


def _robust_upper(values: list[float], *, floor: float, minimum_gap: float) -> float | None:
    if len(values) < 10:
        return None
    median = float(statistics.median(values))
    deviations = [abs(float(value) - median) for value in values]
    mad = float(statistics.median(deviations))
    return max(float(floor), median + max(float(minimum_gap), 6.0 * mad))


def _ensure_schema(database) -> None:
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS annotation_audit_results (
            image_id TEXT PRIMARY KEY,
            result_json TEXT NOT NULL,
            target_count INTEGER NOT NULL,
            density REAL NOT NULL,
            flagged INTEGER NOT NULL DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS ix_annotation_audit_flagged
            ON annotation_audit_results(flagged,image_id);
        """
    )


def audit_cleaning_annotations(
    project_path: str | Path,
    database,
    materials: MaterialRepository | None = None,
    *,
    enabled: bool = True,
) -> dict[str, Any]:
    """Audit formal GT for exactly the frozen CLEAN selection; never mutate GT."""
    project = Path(project_path)
    _ensure_schema(database)
    database.execute("DELETE FROM annotation_audit_results")
    database.execute("DELETE FROM meta WHERE key=?", (AUDIT_META_KEY,))
    state_counts = {"annotated": 0, "unannotated": 0, "confirmed_empty": 0}
    if not enabled:
        summary = {
            "enabled": False, "audited_images": 0, "review_images": 0,
            "warning_count": 0, "state_counts": state_counts,
            "class_balance": [], "heatmap": {"grid": 5, "cells": [0] * 25},
            "provenance_counts": {}, "issue_counts": {},
        }
        database.execute(
            "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
            (AUDIT_META_KEY, json.dumps(summary, ensure_ascii=False, separators=(",", ":"))),
        )
        return summary

    annotations = AnnotationRepository(project)
    material_repository = materials or MaterialRepository(project)
    known_labels, disabled_labels = _label_catalog(project)
    class_totals: dict[str, int] = {}
    provenance_counts: dict[str, int] = {}
    issue_counts: dict[str, int] = {}
    heatmap = [0] * 25
    audited = 0
    cursor = ""

    while True:
        rows = database.execute(
            "SELECT s.image_id,r.result_json FROM selection s "
            "LEFT JOIN clean_results r ON r.image_id=s.image_id "
            "WHERE s.image_id>? ORDER BY s.image_id LIMIT 500",
            (cursor,),
        ).fetchall()
        if not rows:
            break
        ids = [str(row[0]) for row in rows]
        annotation_rows = annotations.get_many(ids)
        material_rows = {str(row.get("id")): row for row in material_repository.get_many(ids)}
        for row in rows:
            image_id = str(row[0])
            record = annotation_rows.get(image_id) or {}
            state = str(record.get("annotation_state") or "unannotated").strip().lower()
            if state not in state_counts:
                state = "unannotated"
            state_counts[state] += 1
            if state != "annotated":
                continue

            boxes = [dict(box) for box in (record.get("boxes") or []) if isinstance(box, Mapping)]
            material = material_rows.get(image_id) or {}
            try:
                clean_result = json.loads(row[1] or "{}") if row[1] else {}
            except (TypeError, ValueError):
                clean_result = {}
            metrics = clean_result.get("metrics") if isinstance(clean_result, dict) else {}
            metrics = metrics if isinstance(metrics, Mapping) else {}
            try:
                width = int(metrics.get("width") or material.get("width") or 0)
                height = int(metrics.get("height") or material.get("height") or 0)
            except (TypeError, ValueError):
                width = height = 0

            issues, density, per_class, per_heatmap = _audit_boxes(
                boxes, width=width, height=height,
                known_labels=known_labels, disabled_labels=disabled_labels,
            )
            for label, count in per_class.items():
                class_totals[label] = class_totals.get(label, 0) + int(count)
            for index, count in enumerate(per_heatmap):
                heatmap[index] += int(count)
            for issue in issues:
                code = str(issue.get("code") or "unknown")
                issue_counts[code] = issue_counts.get(code, 0) + int(issue.get("count") or 1)

            provenance = str(material.get("annotation_origin") or "").strip().lower()
            if not provenance:
                provenance = str(annotation_summary(boxes, state).get("annotation_origin") or "manual")
            provenance_counts[provenance] = provenance_counts.get(provenance, 0) + 1
            digest = str(record.get("content_digest") or annotations.record_digest(record))
            result = {
                "image_id": image_id,
                "filename": str(material.get("filename") or ""),
                "annotation_state": "annotated",
                "annotation_provenance": provenance,
                "annotation_digest": digest,
                "annotation_version": int(record.get("version") or 0),
                "box_count": len(boxes),
                "density": round(float(density), 6),
                "issues": issues,
                "labels": sorted(per_class),
            }
            database.execute(
                "INSERT OR REPLACE INTO annotation_audit_results"
                "(image_id,result_json,target_count,density,flagged) VALUES (?,?,?,?,?)",
                (image_id, json.dumps(result, ensure_ascii=False, separators=(",", ":")),
                 len(boxes), float(density), int(bool(issues))),
            )
            audited += 1
        cursor = ids[-1]

    counts = [float(row[0]) for row in database.execute(
        "SELECT target_count FROM annotation_audit_results ORDER BY image_id"
    )]
    densities = [float(row[0]) for row in database.execute(
        "SELECT density FROM annotation_audit_results ORDER BY image_id"
    )]
    count_limit = _robust_upper(counts, floor=20.0, minimum_gap=10.0)
    density_limit = _robust_upper(densities, floor=1.5, minimum_gap=0.5)
    if count_limit is not None or density_limit is not None:
        rows = database.execute(
            "SELECT image_id,result_json,target_count,density FROM annotation_audit_results ORDER BY image_id"
        ).fetchall()
        for row in rows:
            result = json.loads(row[1])
            added = False
            if count_limit is not None and int(row[2]) > count_limit:
                result["issues"].append({
                    "code": "target_count_abnormal", "name": "单图目标数量异常",
                    "detail": f"当前 {int(row[2])} 个，高于本批稳健阈值 {count_limit:.1f}",
                    "severity": "warning", "count": 1,
                })
                issue_counts["target_count_abnormal"] = issue_counts.get("target_count_abnormal", 0) + 1
                added = True
            if density_limit is not None and float(row[3]) > density_limit:
                result["issues"].append({
                    "code": "annotation_density_abnormal", "name": "标注密度异常",
                    "detail": f"当前密度 {float(row[3]):.3f}，高于本批稳健阈值 {density_limit:.3f}",
                    "severity": "warning", "count": 1,
                })
                issue_counts["annotation_density_abnormal"] = issue_counts.get("annotation_density_abnormal", 0) + 1
                added = True
            if added:
                database.execute(
                    "UPDATE annotation_audit_results SET result_json=?,flagged=1 WHERE image_id=?",
                    (json.dumps(result, ensure_ascii=False, separators=(",", ":")), str(row[0])),
                )

    review_images = int(database.execute(
        "SELECT COUNT(*) FROM annotation_audit_results WHERE flagged=1"
    ).fetchone()[0])
    warning_count = sum(int(value) for value in issue_counts.values())
    total_boxes = sum(class_totals.values())
    class_balance = [{
        "label": label, "count": int(count),
        "share": round((count / total_boxes) if total_boxes else 0.0, 6),
    } for label, count in sorted(class_totals.items(), key=lambda item: (-item[1], item[0]))]
    summary = {
        "enabled": True, "audited_images": audited, "review_images": review_images,
        "warning_count": warning_count, "state_counts": state_counts,
        "class_balance": class_balance, "heatmap": {"grid": 5, "cells": heatmap},
        "provenance_counts": dict(sorted(provenance_counts.items())),
        "issue_counts": dict(sorted(issue_counts.items())),
        "target_count_upper": round(count_limit, 3) if count_limit is not None else None,
        "density_upper": round(density_limit, 6) if density_limit is not None else None,
    }
    database.execute(
        "INSERT OR REPLACE INTO meta(key,value) VALUES (?,?)",
        (AUDIT_META_KEY, json.dumps(summary, ensure_ascii=False, separators=(",", ":"))),
    )
    return summary


def read_annotation_audit(database, *, cursor: str = "", limit: int = AUDIT_PAGE_LIMIT) -> dict[str, Any]:
    table = database.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='annotation_audit_results'"
    ).fetchone()
    meta = database.execute("SELECT value FROM meta WHERE key=?", (AUDIT_META_KEY,)).fetchone()
    if table is None or meta is None:
        return {
            "enabled": False, "audited_images": 0, "review_images": 0,
            "warning_count": 0, "items": [], "next_cursor": None,
        }
    try:
        summary = json.loads(meta[0])
    except (TypeError, ValueError):
        summary = {"enabled": False}
    bounded = max(1, min(AUDIT_PAGE_LIMIT, int(limit or AUDIT_PAGE_LIMIT)))
    after = str(cursor or "")
    rows = database.execute(
        "SELECT image_id,result_json FROM annotation_audit_results "
        "WHERE flagged=1 AND image_id>? ORDER BY image_id LIMIT ?",
        (after, bounded + 1),
    ).fetchall()
    has_more = len(rows) > bounded
    page = rows[:bounded]
    items = [json.loads(row[1]) for row in page]
    return {**summary, "items": items,
            "next_cursor": str(page[-1][0]) if has_more and page else None}


__all__ = ["AUDIT_META_KEY", "AUDIT_PAGE_LIMIT",
           "audit_cleaning_annotations", "read_annotation_audit"]
