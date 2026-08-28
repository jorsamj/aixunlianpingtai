from collections import Counter
from typing import Any, Mapping, Sequence


WEIGHTS = {
    "annotation_completeness": 0.20,
    "box_validity": 0.20,
    "label_balance": 0.20,
    "duplicate_control": 0.15,
    "resolution_quality": 0.15,
    "split_coverage": 0.10,
}


def compute_quality(
    rows: Sequence[Mapping[str, Any]],
    min_width: int = 640,
    min_height: int = 480,
) -> dict:
    image_count = len(rows)
    label_counts: Counter[str] = Counter()
    annotated_images = 0
    valid_boxes = 0
    invalid_boxes = 0
    low_resolution = 0
    hashes: Counter[str] = Counter()
    splits: Counter[str] = Counter()
    for row in rows:
        boxes = list(row.get("boxes") or [])
        if boxes:
            annotated_images += 1
        for box in boxes:
            label = str(box.get("label") or "").strip()
            if label:
                label_counts[label] += 1
        valid_boxes += int(row.get("valid_box_count", len(boxes)) or 0)
        invalid_boxes += int(row.get("invalid_box_count", 0) or 0)
        if int(row.get("width") or 0) < min_width or int(row.get("height") or 0) < min_height:
            low_resolution += 1
        if row.get("content_hash"):
            hashes[str(row["content_hash"])] += 1
        split = str(row.get("split") or "unassigned").lower()
        splits[split] += 1
    duplicates = sum(max(0, count - 1) for count in hashes.values())
    used_counts = list(label_counts.values())
    scores = {
        "annotation_completeness": annotated_images / max(1, image_count) * 100,
        "box_validity": valid_boxes / max(1, valid_boxes + invalid_boxes) * 100 if valid_boxes + invalid_boxes else 0,
        "label_balance": min(used_counts) / max(used_counts) * 100 if used_counts else 0,
        "duplicate_control": max(0.0, 100 - duplicates / max(1, image_count) * 100),
        "resolution_quality": max(0.0, 100 - low_resolution / max(1, image_count) * 100),
        "split_coverage": sum(1 for split in ("train", "val", "test") if splits.get(split)) / 3 * 100,
    }
    scores = {key: round(value, 1) for key, value in scores.items()}
    explanations = {
        "annotation_completeness": f"{annotated_images}/{image_count} 张素材包含有效标注",
        "box_validity": f"有效框 {valid_boxes} 个，无效框 {invalid_boxes} 个",
        "label_balance": "各标签框数量的最小值与最大值之比",
        "duplicate_control": f"发现 {duplicates} 张重复素材",
        "resolution_quality": f"{low_resolution} 张低于 {min_width}×{min_height}",
        "split_coverage": f"训练/试验/评测三类用途覆盖 {sum(1 for split in ('train', 'val', 'test') if splits.get(split))} 类",
    }
    radar = [
        {"key": key, "score": scores[key], "explanation": explanations[key]}
        for key in WEIGHTS
    ]
    suggestions = []
    if used_counts:
        maximum = max(used_counts)
        for label, count in sorted(label_counts.items()):
            if count < maximum:
                suggestions.append(f"标签 {label} 只有 {count} 个框，建议补充到接近 {maximum} 个框。")
    if low_resolution:
        suggestions.append(f"有 {low_resolution} 张低分辨率素材，建议替换或确认小目标是否仍清晰。")
    if not splits.get("val"):
        suggestions.append("缺少试验集素材，无法独立验证训练效果。")
    if not splits.get("test"):
        suggestions.append("缺少评测集素材，无法进行最终泛化评测。")
    overall = round(sum(scores[key] * weight for key, weight in WEIGHTS.items()), 1)
    return {
        "overall_score": overall,
        "weights": dict(WEIGHTS),
        "scores": scores,
        "radar": radar,
        "suggestions": suggestions,
        "images": image_count,
        "annotated_images": annotated_images,
        "box_count": sum(label_counts.values()),
        "invalid_boxes": invalid_boxes,
        "label_counts": dict(sorted(label_counts.items())),
        "label_boxes": dict(sorted(label_counts.items())),
        "label_count": len(label_counts),
        "low_resolution": low_resolution,
        "duplicate_images": duplicates,
        "split_counts": dict(splits),
    }
