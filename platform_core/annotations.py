import json
import math
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence


PREVIEW_LIMIT = 32
PREVIEW_FIELDS = ("label_id", "class_id", "label", "x1", "y1", "x2", "y2")


def normalize_annotation_scope(values: Sequence[object] | None) -> list[str]:
    """Return a stable-label scope without inferring unchecked classes."""
    if isinstance(values, (str, bytes)):
        values = [values]
    return sorted({str(value).strip() for value in (values or []) if str(value).strip()})


def normalize_annotation_contract(
    boxes: Sequence[Mapping[str, Any]],
    annotation_state: str | None = None,
    annotation_scope: Sequence[object] | None = None,
    confirmed_empty_scope: Sequence[object] | None = None,
) -> tuple[str, list[str]]:
    """Normalize state/scope while reading the legacy confirmed-empty field safely."""
    state = str(annotation_state or ("annotated" if boxes else "unannotated"))
    if state not in {"unannotated", "annotated", "confirmed_empty"}:
        raise ValueError("invalid annotation state")
    if bool(boxes) != (state == "annotated"):
        raise ValueError("annotation state does not agree with boxes")
    supplied = annotation_scope
    if supplied is None and state == "confirmed_empty":
        supplied = confirmed_empty_scope
    scope = normalize_annotation_scope(supplied)
    if state == "annotated":
        scope = normalize_annotation_scope([
            *scope,
            *(box.get("label_id") for box in boxes if box.get("label_id")),
        ])
    elif state == "unannotated":
        scope = []
    return state, scope


def annotation_scope_covers(
    annotation_scope: Sequence[object] | None,
    selected_label_ids: Sequence[object] | None,
) -> bool:
    selected = set(normalize_annotation_scope(selected_label_ids))
    return bool(selected) and selected.issubset(set(normalize_annotation_scope(annotation_scope)))


def legal_negative_for_labels(
    boxes: Sequence[Mapping[str, Any]],
    annotation_state: str | None,
    annotation_scope: Sequence[object] | None,
    selected_label_ids: Sequence[object] | None,
) -> bool:
    """A filtered empty image is negative only when every selected class was checked."""
    selected = set(normalize_annotation_scope(selected_label_ids))
    if not selected or annotation_state not in {"annotated", "confirmed_empty"}:
        return False
    if any(str(box.get("label_id") or "") in selected for box in boxes):
        return False
    return selected.issubset(set(normalize_annotation_scope(annotation_scope)))


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


def annotation_summary(
    boxes: Sequence[Mapping[str, Any]],
    annotation_state: str | None = None,
    annotation_scope: Sequence[object] | None = None,
    confirmed_empty_scope: Sequence[object] | None = None,
) -> dict:
    state, scope = normalize_annotation_contract(
        boxes, annotation_state, annotation_scope, confirmed_empty_scope,
    )
    label_counts: dict[str, int] = {}
    stable_label_ids: set[str] = set()
    for box in boxes:
        label = str(box.get("label") or "").strip()
        if label:
            label_counts[label] = label_counts.get(label, 0) + 1
        label_id = str(box.get("label_id") or "").strip()
        if label_id:
            stable_label_ids.add(label_id)
    labels = sorted(
        label_counts
    )
    preview = [
        {field: box.get(field) for field in PREVIEW_FIELDS}
        for box in boxes[:PREVIEW_LIMIT]
    ]
    return {
        "labels": labels,
        "label_ids": sorted(stable_label_ids),
        "label_counts": label_counts,
        "box_count": len(boxes),
        "annotated": state in {"annotated", "confirmed_empty"},
        "annotation_state": state,
        "annotation_status": state,
        "annotation_scope": scope,
        "confirmed_empty_scope": scope if state == "confirmed_empty" else [],
        "ground_truth_complete": state in {"annotated", "confirmed_empty"} and bool(scope),
        "annotation_preview": preview,
    }
