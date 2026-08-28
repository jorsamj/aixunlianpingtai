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


def parse_candidate_response(
    text: str,
    *,
    width: int,
    height: int,
    label_ids: Mapping[str, int],
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
        raise ValueError(f"候选标注字段不符合协议：{error.errors(include_url=False)}") from error

    result: list[dict[str, Any]] = []
    for index, box in enumerate(parsed.boxes):
        label = box.label.strip()
        values = (box.confidence, box.x1, box.y1, box.x2, box.y2)
        if not all(math.isfinite(value) for value in values):
            raise ValueError(f"第 {index + 1} 个框包含非有限数字")
        if label not in label_ids:
            raise ValueError(f"第 {index + 1} 个框使用了标签库之外的标签：{label}")
        if not 0 <= box.confidence <= 1:
            raise ValueError(f"第 {index + 1} 个框置信度必须在 0 到 1 之间")
        if not (0 <= box.x1 < box.x2 <= width and 0 <= box.y1 < box.y2 <= height):
            raise ValueError(f"第 {index + 1} 个框坐标越界或宽高无效")
        result.append({
            "class_id": int(label_ids[label]),
            "label": label,
            "confidence": float(box.confidence),
            "x1": float(box.x1),
            "y1": float(box.y1),
            "x2": float(box.x2),
            "y2": float(box.y2),
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
