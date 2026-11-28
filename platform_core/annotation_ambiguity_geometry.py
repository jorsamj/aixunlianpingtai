"""Server counterpart to static/modules/annotation-ambiguity.js.

The AI candidate contract supplies JSON pixel coordinates. Keep the pair
iteration, inclusive threshold, confidence ordering and final strict 0.5
check in sync with the browser's existing review policy.
"""
import math


def _number(value):
    if value is None or isinstance(value, str) and not value.strip():
        return 0.0
    try:
        if isinstance(value, str) and value.strip().lower().startswith(("0x", "0b", "0o")):
            return float(int(value, 0))
        return float(value)
    except (ValueError, TypeError, OverflowError):
        return math.nan


def _iou(left, right):
    coordinates = ("x1", "y1", "x2", "y2")
    a, b = ([(_number(box[key]) if key in box else math.nan) for key in coordinates] for box in (left, right))
    if not all(math.isfinite(value) for value in (*a, *b)):
        return 0
    area_a, area_b = (a[2] - a[0]) * (a[3] - a[1]), (b[2] - b[0]) * (b[3] - b[1])
    if area_a <= 0 or area_b <= 0:
        return 0
    overlap = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return overlap / (area_a + area_b - overlap) if overlap > 0 else 0


def _groups(boxes, threshold, inclusive):
    if not isinstance(boxes, list) or len(boxes) > 300:
        return []
    parent = list(range(len(boxes)))
    touched = {}

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for i, left in enumerate(boxes):
        for j in range(i + 1, len(boxes)):
            right = boxes[j]
            if not left or not right or str(left.get("label") or "") == str(right.get("label") or ""):
                continue
            overlap = _iou(left, right)
            below_threshold = overlap < threshold if inclusive else overlap <= threshold
            if below_threshold:
                continue
            parent[root(j)] = root(i)
            touched[i] = touched[j] = None
    groups = {}
    for index in touched:
        groups.setdefault(root(index), []).append(index)
    return list(groups.values())


def plan_ambiguity(item, mode, label, threshold):
    if (not item or item.get("status") != "success"
            or item.get("review_state") not in (None, "", "active") or not item.get("manual_review_required")):
        return {"reason": "不是可编辑的歧义候选"}
    if item.get("accepted") is True:
        return {"reason": "此图已采用，请先单图核对"}
    boxes = item.get("boxes") or []
    groups = _groups(boxes, threshold, True)
    if not groups:
        return {"reason": "没有达到所填 IoU 阈值的冲突框"}
    removed, chosen, fallback = set(), [], 0

    def confidence(index):
        value = boxes[index].get("confidence")
        number = _number(value)
        return number if value is not None and value != "" and 0 <= number <= 1 else -1

    for indices in groups:
        if any(_iou(boxes[index], boxes[other]) < threshold
               for position, index in enumerate(indices) for other in indices[position + 1:]):
            return {"reason": "链式重叠不是同一位置，请逐图人工审核"}
        if mode == "manual":
            winners = [index for index in indices if str(boxes[index].get("label")) == label]
            if len(winners) != 1:
                return {"reason": "冲突组中没有唯一的指定标签，请逐图人工审核"}
            keep = winners[0]
        else:
            keep = min(indices, key=lambda index: (-confidence(index), index))
            fallback += int(confidence(keep) == -1)
        chosen.append(str(boxes[keep].get("label") or ""))
        removed.update(index for index in indices if index != keep)
    next_boxes = [box for index, box in enumerate(boxes) if index not in removed]
    if not removed or _groups(next_boxes, 0.5, False):
        return {"reason": "仍有低于所填阈值的跨标签冲突，请调低阈值或单图处理"}
    return {"boxes": next_boxes, "removed": len(removed), "chosen": chosen, "fallbackGroups": fallback}
