import hashlib
import json
import math
import re
from typing import Any, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, ValidationError


MARKDOWN_FENCE = re.compile(r"^```(?:json)?\s*\n?(.*?)\n?```$", re.IGNORECASE | re.DOTALL)

CANDIDATE_OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "boxes": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "label": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "x1": {"type": "number"},
                    "y1": {"type": "number"},
                    "x2": {"type": "number"},
                    "y2": {"type": "number"},
                },
                "required": ["label", "confidence", "x1", "y1", "x2", "y2"],
            },
        }
    },
    "required": ["boxes"],
}


def provider_factory(provider_config: Mapping[str, Any]):
    from .providers.openai_vision import OpenAICompatibleVisionProvider
    from .providers.ollama_vision import OllamaVisionProvider

    config = dict(provider_config or {})
    provider = str(config.get("provider_adapter") or config.get("provider_type") or "local_openai")
    if provider in {"cloud", "local"}:
        provider = "local_openai"
    if provider == "ollama":
        return OllamaVisionProvider(
            base_url=str(config.get("base_url") or config.get("detect_url") or "http://127.0.0.1:11434"),
            model=str(config.get("model_name") or ""),
        )
    if provider not in {"volcengine_ark", "aliyun_qwen", "local_openai"}:
        raise ValueError(f"不支持的视觉模型适配器：{provider}")
    return OpenAICompatibleVisionProvider(
        provider=provider,
        base_url=str(config.get("base_url") or config.get("detect_url") or ""),
        api_key=str(config.get("_api_key") or ""),
        model=str(config.get("model_name") or ""),
        headers=config.get("headers_json") or {},
        api_protocol=str(config.get("api_protocol") or "auto"),
        structured_output=str(config.get("structured_output") or "auto"),
    )


class CandidateAnnotation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    confidence: float
    x1: float
    y1: float
    x2: float
    y2: float


class CandidateResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    boxes: list[CandidateAnnotation]


def raw_response_hash(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()


def _json_text(text: str) -> str:
    clean = str(text or "").strip()
    fenced = MARKDOWN_FENCE.fullmatch(clean)
    return fenced.group(1).strip() if fenced else clean


def coordinate_contract(config, *, legacy=False):
    """An explicit contract; names and coordinate magnitudes never select a new protocol."""
    if legacy and "coordinate_space" not in config:
        return {"coordinate_space": "legacy_auto", "coordinate_order": "xyxy", "output_protocol": "json_boxes", "coordinate_contract_version": 0}
    result = {"coordinate_space": config.get("coordinate_space", "pixel"),
              "coordinate_order": config.get("coordinate_order", "xyxy"),
              "output_protocol": config.get("output_protocol", "json_boxes"),
              "coordinate_contract_version": 1,
              "coordinate_origin": config.get("coordinate_origin", "top_left"),
              "coordinate_image_space": config.get("coordinate_image_space", "original_input")}
    if result["coordinate_space"] not in {"pixel", "normalized_01", "normalized_1000"} or result["coordinate_order"] not in {"xyxy", "yxyx"} or result["output_protocol"] != "json_boxes":
        raise ValueError("UNVERIFIED_CONTRACT: unsupported coordinate contract")
    if result["coordinate_origin"] not in {"top_left", "bottom_left"} or result["coordinate_image_space"] not in {"original_input", "processed_image"}:
        raise ValueError("UNVERIFIED_CONTRACT: unknown origin or image space")
    return result


def adapt_coordinates(coordinates, *, width, height, coordinate_space, coordinate_order, coordinate_origin="top_left", geometry=None):
    original_width, original_height = width, height
    if geometry is not None:
        required = ("width", "height", "scale_x", "scale_y", "pad_x", "pad_y", "crop_x", "crop_y")
        if any(key not in geometry or not isinstance(geometry[key], (int, float)) or not math.isfinite(geometry[key]) for key in required):
            raise ValueError("UNVERIFIED_CONTRACT: incomplete preprocessing geometry")
        if any(geometry[k] <= 0 for k in ("width", "height", "scale_x", "scale_y")):
            raise ValueError("UNVERIFIED_CONTRACT: invalid preprocessing geometry")
        width, height = geometry["width"], geometry["height"]
    if coordinate_origin not in {"top_left", "bottom_left"}:
        raise ValueError("UNVERIFIED_CONTRACT: unsupported coordinate origin")
    if coordinate_order not in {"xyxy", "yxyx"}:
        raise ValueError("UNVERIFIED_CONTRACT: unsupported coordinate order")
    x1, y1, x2, y2 = map(float, coordinates)
    if coordinate_order == "yxyx":
        x1, y1, x2, y2 = y1, x1, y2, x2
    values = (x1, y1, x2, y2)
    if not all(math.isfinite(v) for v in values):
        raise ValueError("COORDINATE_CONVERSION_ERROR: non-finite coordinate")
    if coordinate_space == "legacy_auto":
        coordinate_space = ("normalized_01" if all(0 <= v <= 1 for v in values) else
                            "normalized_1000" if (x2 > width or y2 > height) and all(0 <= v <= 1000 for v in values) else "pixel")
    divisor = {"pixel": None, "normalized_01": 1, "normalized_1000": 1000}.get(coordinate_space, -1)
    if divisor == -1:
        raise ValueError("UNVERIFIED_CONTRACT: unsupported coordinate space")
    if divisor is not None:
        if not all(0 <= v <= divisor for v in values):
            raise ValueError("COORDINATE_CONVERSION_ERROR: coordinate outside declared range")
        x1, x2 = x1 * width / divisor, x2 * width / divisor
        y1, y2 = y1 * height / divisor, y2 * height / divisor
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("COORDINATE_CONVERSION_ERROR: reversed or out-of-bounds box")
    if coordinate_origin == "bottom_left":
        y1, y2 = height - y2, height - y1
    if geometry is not None:
        x1, x2 = ((v - geometry["pad_x"]) / geometry["scale_x"] + geometry["crop_x"] for v in (x1,x2))
        y1, y2 = ((v - geometry["pad_y"]) / geometry["scale_y"] + geometry["crop_y"] for v in (y1,y2))
        if not (0 <= x1 < x2 <= original_width and 0 <= y1 < y2 <= original_height):
            raise ValueError("COORDINATE_CONVERSION_ERROR: inverse mapping outside original pixels")
    return x1, y1, x2, y2


def parse_candidate_response(
    text: str,
    *,
    width: int,
    height: int,
    label_ids: Mapping[str, int],
    label_aliases: Mapping[str, Sequence[str]] | None = None,
    coordinate_space: str = "legacy_auto",
    coordinate_order: str = "xyxy",
    diagnostics: dict | None = None,
    coordinate_origin: str = "top_left",
    geometry: dict | None = None,
) -> list[dict[str, Any]]:
    if width <= 0 or height <= 0:
        raise ValueError("图片尺寸无效")
    try:
        payload = json.loads(_json_text(text))
    except json.JSONDecodeError as error:
        raise ValueError(f"模型返回的不是合法 JSON：{error.msg}") from error
    if not isinstance(payload, dict):
        raise ValueError("模型返回必须是一个包含 boxes 的 JSON object")
    try:
        parsed = CandidateResponse.model_validate(payload)
    except ValidationError as error:
        raise ValueError(f"候选标注字段不符合协议：{error.errors(include_url=False, include_input=False)}") from None

    # Alias metadata is intentionally ignored here. The model must return one
    # of the exact canonical codes explicitly allowed by this task.
    del label_aliases
    if diagnostics is not None:
        diagnostics["raw_candidate_count"] = len(parsed.boxes)
        diagnostics["raw_candidates"] = [
            {"confidence": b.confidence, "x1": b.x1, "y1": b.y1, "x2": b.x2, "y2": b.y2,
             "label": b.label if b.label in label_ids else "[unknown label]"}
            for b in parsed.boxes[:100]
            if all(math.isfinite(v) for v in (b.confidence, b.x1, b.y1, b.x2, b.y2))
        ]
        diagnostics["raw_candidates_truncated"] = len(parsed.boxes) > 100
    result: list[dict[str, Any]] = []
    for index, box in enumerate(parsed.boxes):
        label = box.label.strip()
        values = (box.confidence, box.x1, box.y1, box.x2, box.y2)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"第 {index + 1} 个框包含非有限数字")
        if label not in label_ids:
            raise ValueError(f"第 {index + 1} 个框使用了标签库之外的标签")
        if not 0 <= box.confidence <= 1:
            raise ValueError(f"第 {index + 1} 个框置信度必须在 0 到 1 之间")
        x1, y1, x2, y2 = adapt_coordinates(
            (box.x1, box.y1, box.x2, box.y2), width=width, height=height,
            coordinate_space=coordinate_space, coordinate_order=coordinate_order, coordinate_origin=coordinate_origin, geometry=geometry,
        )
        result.append({
            "class_id": int(label_ids[label]),
            "label": label,
            "confidence": float(box.confidence),
            "x1": x1,
            "y1": y1,
            "x2": x2,
            "y2": y2,
        })
    return result


def _iou(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    x1 = max(float(left["x1"]), float(right["x1"]))
    y1 = max(float(left["y1"]), float(right["y1"]))
    x2 = min(float(left["x2"]), float(right["x2"]))
    y2 = min(float(left["y2"]), float(right["y2"]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    left_area = (float(left["x2"]) - float(left["x1"])) * (float(left["y2"]) - float(left["y1"]))
    right_area = (float(right["x2"]) - float(right["x1"])) * (float(right["y2"]) - float(right["y1"]))
    union = left_area + right_area - intersection
    return intersection / union if union > 0 else 0.0


def nms_candidates(boxes: Sequence[Mapping[str, Any]], *, iou_threshold: float = 0.5) -> list[dict[str, Any]]:
    if not 0 <= iou_threshold <= 1:
        raise ValueError("NMS 阈值必须在 0 到 1 之间")
    ordered = sorted(
        (dict(box) for box in boxes),
        key=lambda box: (
            -float(box.get("confidence", 0)),
            str(box.get("label", "")),
            float(box.get("x1", 0)),
            float(box.get("y1", 0)),
            float(box.get("x2", 0)),
            float(box.get("y2", 0)),
        ),
    )
    kept: list[dict[str, Any]] = []
    for box in ordered:
        duplicate = any(
            str(old.get("label")) == str(box.get("label")) and _iou(old, box) > iou_threshold
            for old in kept
        )
        if not duplicate:
            kept.append(box)
    return kept
