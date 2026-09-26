import json
import math
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence


PREVIEW_LIMIT = 32
PREVIEW_FIELDS = ("class_id", "label", "x1", "y1", "x2", "y2", "source", "source_task_id", "confidence")
PROVENANCE_FIELDS = ("source", "source_task_id", "candidate_id", "confidence", "model_config_id", "prompt_template_id", "prompt_template_version_id")


def atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    temp.replace(path)


def normalize_boxes(
    boxes: Sequence[Mapping[str, Any]],
    width: int,
    height: int,
    label_ids: Mapping[str, int],
) -> list[dict]:
    if width <= 0 or height <= 0:
        raise ValueError("图片尺寸无效")
    labels_by_id = {int(class_id): str(code) for code, class_id in label_ids.items()}
    normalized = []
    for index, box in enumerate(boxes):
        label = str(box.get("label") or box.get("code") or "").strip()
        if not label and box.get("class_id") is not None:
            try:
                label = labels_by_id[int(box["class_id"])]
            except (KeyError, TypeError, ValueError):
                label = ""
        if label not in label_ids:
            raise KeyError(label or f"box[{index}]")
        try:
            x1 = float(box["x1"])
            y1 = float(box["y1"])
            x2 = float(box["x2"])
            y2 = float(box["y2"])
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"第 {index + 1} 个标注框坐标格式不正确") from error
        coordinates = (x1, y1, x2, y2)
        if not all(math.isfinite(value) for value in coordinates):
            raise ValueError(f"第 {index + 1} 个标注框坐标不是有限数值")
        if x1 < 0 or y1 < 0 or x2 > width or y2 > height or x2 <= x1 or y2 <= y1:
            raise ValueError(f"第 {index + 1} 个标注框坐标超出图片范围或方向错误")
        normalized.append(
            {
                "id": str(box.get("id") or uuid.uuid4().hex[:10]),
                "class_id": int(label_ids[label]),
                "label": label,
                "x1": round(x1, 2),
                "y1": round(y1, 2),
                "x2": round(x2, 2),
                "y2": round(y2, 2),
            }
        )
    return normalized


def restore_box_provenance(
    normalized_boxes: Sequence[Mapping[str, Any]],
    existing_boxes: Sequence[Mapping[str, Any]],
    *,
    existing_source_fallback: str = "manual",
    new_source: str = "manual",
) -> list[dict]:
    """Preserve server-owned provenance while accepting geometry/label edits.

    The browser may edit coordinates and canonical labels, but it must not be
    able to turn a newly drawn manual box into an AI/import box by posting
    forged provenance fields. Existing box provenance is recovered by stable
    box id; new boxes always receive ``new_source``.
    """
    existing_by_id = {
        str(box.get("id")): box
        for box in existing_boxes
        if str(box.get("id") or "").strip()
    }
    restored = []
    for box in normalized_boxes:
        row = dict(box)
        previous = existing_by_id.get(str(row.get("id") or ""))
        if previous is None:
            if new_source:
                row["source"] = str(new_source)
        else:
            for field in PROVENANCE_FIELDS:
                value = previous.get(field)
                if value is not None and value != "":
                    row[field] = value
            if not str(row.get("source") or "").strip() and existing_source_fallback:
                row["source"] = str(existing_source_fallback)
        restored.append(row)
    return restored

def annotation_summary(boxes: Sequence[Mapping[str, Any]], annotation_state: str | None = None) -> dict:
    state = annotation_state or ("annotated" if boxes else "unannotated")
    label_counts: dict[str, int] = {}
    source_values = []
    for box in boxes:
        label = str(box.get("label") or "").strip()
        if label:
            label_counts[label] = label_counts.get(label, 0) + 1
        source_values.append(str(box.get("source") or "").strip().lower())
    labels = sorted(label_counts)
    is_ai_source = lambda source: source.startswith("ai_") or source in {"auto", "semi-auto"}
    has_ai = any(is_ai_source(source) for source in source_values)
    has_non_ai = any(not is_ai_source(source) for source in source_values)
    has_import = any("import" in source for source in source_values if source)
    if state == "unannotated":
        origin = "unannotated"
    elif state == "confirmed_empty":
        origin = "confirmed_empty"
    elif has_ai and has_non_ai:
        origin = "mixed"
    elif has_ai:
        origin = "ai_confirmed"
    elif has_import:
        origin = "imported"
    else:
        origin = "manual"
    preview = [
        {field: box.get(field) for field in PREVIEW_FIELDS}
        for box in boxes[:PREVIEW_LIMIT]
    ]
    return {
        "labels": labels,
        "label_counts": label_counts,
        "box_count": len(boxes),
        "annotated": state in {"annotated", "confirmed_empty"},
        "annotation_state": state,
        "annotation_status": state,
        "annotation_origin": origin,
        "annotation_preview": preview,
    }
