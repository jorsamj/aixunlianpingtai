"""Optional WeVisOne native vision API integration.

This provider owns its wire format.  All boxes returned to the platform are
canonical original-image pixels; generic OpenAI providers are untouched.
"""

import base64
import binascii
import io
import json
import math
import re
import time
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit, urlunsplit

import requests
from PIL import Image

from .base import ProviderRequestError, response_metadata, http_error


_REF_BOX = re.compile(r"<ref>([^<>]+)</ref>\s*<box>(.*?)</box>", re.I | re.S)
_COORD = re.compile(r"<(\d{1,4})>")
_EMPTY = {"none", "null", "no objects", "no object", "no targets", "无目标", "未检测到目标"}
_IMAGE_FIELDS = {"mask": "mask_image_base64", "alpha": "alpha_matte_base64", "foreground": "foreground_base64"}
_MAX_IMAGE_BYTES = 10_000_000
_MAX_IMAGE_PIXELS = 25_000_000
_MAX_DETECTIONS = 300
_MAX_PREVIEW_INSTANCES = 32
_PNG_FIELDS = {"mask": "mask_png", "foreground": "cutout_png"}
_MIME_FORMATS = {"JPEG": "image/jpeg", "PNG": "image/png", "WEBP": "image/webp"}
_MAX_QUERY_LENGTH = 300
_LABEL_TRAILING_PUNCTUATION = ".,;:!?。！？；：，"


def _label_key(value: str) -> str:
    """Only presentation-equivalent label changes; never guess semantics."""
    return str(value).strip().rstrip(_LABEL_TRAILING_PUNCTUATION).strip().casefold()


def _public_label(value: Any) -> str:
    """Short diagnostic label, never a full free-form model response or secret."""
    text = re.sub(r"[\x00-\x1f\x7f]+", " ", str(value or "")).strip()
    if re.search(r"(?i)data:image/|base64,|bearer\s|sk-[a-z0-9_-]{12,}|api[_-]?key\s*[:=]", text):
        return "[REDACTED]"
    return text[:160]


def _response_summary(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Protocol shape only; never persist raw model prose, images or bodies."""
    raw = payload.get("response")
    boxes = payload.get("boxes")
    return {"parser_source": "structured_boxes" if isinstance(boxes, list) else "native_ref_box",
            "structured_box_count": len(boxes) if isinstance(boxes, list) else None,
            "raw_length": min(len(raw), 1_000_000) if isinstance(raw, str) else None,
            "raw_ref_count": min(len(_REF_BOX.findall(raw)), 301) if isinstance(raw, str) else None,
            "raw_empty_markers": min(sum(m.group(2).strip().lower() in _EMPTY for m in _REF_BOX.finditer(raw)), 301) if isinstance(raw, str) else None,
            "coordinate_system": _public_label(payload.get("coordinate_system")),
            "width": payload.get("width") if type(payload.get("width")) is int else None,
            "height": payload.get("height") if type(payload.get("height")) is int else None}


def _protocol_conflict(message: str) -> ProviderRequestError:
    error = ProviderRequestError(message, code="MODEL_OUTPUT_PARSE_ERROR")
    error.diagnostics = {"label_match_status": "protocol_conflict", "parser_source": "structured_and_native"}
    return error


def _label_failure(raw_label: str, *, allowed: Mapping[str, str], source: str,
                   zero_box: bool | None = None) -> ProviderRequestError:
    error = ProviderRequestError("WeVisOne 返回了本次任务范围外的标签", code="MODEL_LABEL_NOT_ALLOWED",
                                 solution="模型实际标签未匹配冻结标签或已配置别名；请查看返回标签及查询映射。")
    error.diagnostics = {"returned_label": _public_label(raw_label), "label_match_status": "not_allowed",
                         "parser_source": source, "allowed_labels": list(dict.fromkeys(allowed.values()))[:100],
                         "zero_box": zero_box}
    return error


def normalize_label_queries(value: Mapping[str, str] | None) -> dict[str, str]:
    """Keep native referring descriptions separate from durable class codes."""
    if value is None:
        return {}
    if not isinstance(value, Mapping) or len(value) > 100:
        raise ValueError("WeVisOne 标签描述必须是至多 100 项的键值对象")
    cleaned: dict[str, str] = {}
    descriptions: set[str] = set()
    for code, description in value.items():
        if not isinstance(code, str) or not isinstance(description, str):
            raise ValueError("WeVisOne 标签和定位描述必须是字符串")
        code, description = code.strip(), description.strip()
        if not code or len(code) > 80 or any(char.isspace() for char in code):
            raise ValueError("WeVisOne 标签 code 不能为空、含空格或超过 80 字符")
        if (not description or len(description) > _MAX_QUERY_LENGTH or
                any(char in description for char in "\r\n\x00") or
                re.search(r"<\|[^>]*\|>|</?c>|</?(?:ref|box)>", description, re.I)):
            raise ValueError("WeVisOne 定位描述不能为空、超过 300 字符或包含协议控制字符")
        normalized_description = _label_key(description)
        if not normalized_description or normalized_description in descriptions or normalized_description in {_label_key(code) for code in cleaned}:
            raise ValueError("WeVisOne 不同标签的定位描述不能重复或与其他标签 code 相同")
        cleaned[code] = description
        descriptions.add(normalized_description)
    if any(_label_key(code) in descriptions for code in cleaned):
        raise ValueError("WeVisOne 定位描述不能与其他标签 code 相同")
    return cleaned


def effective_detection_config(config: Mapping[str, Any], labels: Sequence[str]) -> dict[str, Any]:
    """Public, credential-free view of the actual frozen native request contract."""
    codes = list(dict.fromkeys(str(code) for code in labels))
    queries = normalize_label_queries(config.get("wevisone_label_queries"))
    selected = {code: queries.get(code, code) for code in codes}
    if len({_label_key(value) for value in selected.values()}) != len(selected):
        raise ValueError("WeVisOne 冻结标签查询存在歧义")
    per_label = len(codes) > 1 and any(_label_key(selected[code]) != _label_key(code) for code in codes)
    return {
        "model": str(config.get("model_name") or ""), "adapter": "wevisone_vl",
        "task": "detection", "request_mode": "per_label" if per_label else "category_list",
        "endpoint": "/v1/vision/detect", "image": "data:image/<type>;base64,[omitted]",
        "query_type": "list[str]", "label_queries": selected,
        "coordinate_space": str(config.get("coordinate_space") or "pixel"),
        "coordinate_order": str(config.get("coordinate_order") or "xyxy"),
        "coordinate_origin": str(config.get("coordinate_origin") or "top_left"),
        "coordinate_image_space": str(config.get("coordinate_image_space") or "original_input"),
        "generic_prompt_applied": False,
    }


def _endpoint(base_url: str, operation: str) -> str:
    parts = urlsplit(str(base_url or "").strip())
    if (parts.scheme not in {"http", "https"} or not parts.hostname or
            parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError("WeVisOne 服务地址须为不含账号、查询参数的 HTTP(S) 地址")
    path = parts.path.rstrip("/")
    if "%" in path or "//" in path or any(part in {".", ".."} for part in path.split("/")):
        raise ValueError("WeVisOne 地址路径含歧义编码或目录跳转")
    path = re.sub(r"/vision/(detect|segment|matting)$", "", path)
    path = re.sub(r"/models$", "", path)
    if path.endswith("/v1"):
        root = path
    elif not path or path == "/":
        root = "/v1"
    else:
        raise ValueError("WeVisOne 地址应为服务根地址或 /v1，不接受自定义聊天接口路径")
    return urlunsplit(parts._replace(path=root + ("/models" if operation == "models" else "/vision/" + operation)))


def _native_boxes(raw: str, *, allowed_labels: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    value = str(raw or "").strip().split("<|im_end|>", 1)[0].strip()
    if value.lower() in _EMPTY:
        return []
    matches = list(_REF_BOX.finditer(value))
    if not matches:
        raise ProviderRequestError("WeVisOne 原生响应无法识别为检测结果", code="MODEL_OUTPUT_PARSE_ERROR", solution="请检查专用检测接口返回的 ref/box 协议。")
    remaining = _REF_BOX.sub("", value).strip(" \r\n\t,;。")
    if remaining:
        raise ProviderRequestError("WeVisOne 检测响应包含无法解析的内容", code="MODEL_OUTPUT_PARSE_ERROR")
    boxes = []
    empty_labels: set[str] = set()
    detected_labels: set[str] = set()
    for match in matches:
        label = match.group(1).strip()
        body = match.group(2).strip()
        if not label:
            raise ProviderRequestError("WeVisOne 原生目标框缺少标签", code="MODEL_OUTPUT_PARSE_ERROR")
        # The live 4070 FastAPI returns boxes=[] with the raw model text
        # <ref>fire</ref><box>none</box> on an empty 128x128 sample.  This is
        # an explicit absence marker, not a four-coordinate detection.
        if body.lower() in _EMPTY:
            # An absent target has no class assignment. Its descriptive ref
            # cannot invalidate an otherwise well-formed no-target response.
            empty_labels.add(_label_key(label))
            continue
        groups = [part.strip() for part in body.split(",")]
        for part in groups:
            coords = _COORD.findall(part)
            if len(coords) != 4 or _COORD.sub("", part).strip():
                raise ProviderRequestError("WeVisOne 原生目标框格式错误", code="MODEL_OUTPUT_PARSE_ERROR")
            if allowed_labels is not None and _label_key(label) not in allowed_labels:
                raise _label_failure(label, allowed=allowed_labels, source="native_ref_box", zero_box=False)
            boxes.append({"label": label, "coordinates": [int(c) for c in coords], "space": "normalized_1000"})
            detected_labels.add(_label_key(label))
    if empty_labels & detected_labels:
        raise ProviderRequestError("WeVisOne 同一标签同时声明有目标和无目标", code="MODEL_OUTPUT_PARSE_ERROR")
    return boxes


def _validate_image(image_bytes: bytes) -> tuple[int, int, str]:
    if not image_bytes or len(image_bytes) > _MAX_IMAGE_BYTES:
        raise ProviderRequestError("WeVisOne 输入图片不能为空或超过 10MB", code="MODEL_IMAGE_TOO_LARGE")
    try:
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
            mime = _MIME_FORMATS.get(image.format)
    except (OSError, ValueError, Image.DecompressionBombError):
        raise ProviderRequestError("WeVisOne 输入图片无法解码", code="MODEL_IMAGE_INVALID") from None
    if width <= 0 or height <= 0 or width * height > _MAX_IMAGE_PIXELS:
        raise ProviderRequestError("WeVisOne 输入图片超过 2500 万像素", code="MODEL_IMAGE_TOO_LARGE")
    if not mime:
        raise ProviderRequestError("WeVisOne 支持 JPEG、PNG、WebP 图片", code="MODEL_IMAGE_FORMAT_UNSUPPORTED")
    return width, height, mime


def _label_mapping(labels: Sequence[str], aliases: Mapping[str, Sequence[str]] | None) -> dict[str, str]:
    allowed: dict[str, str] = {}
    def register(name: str, code: str) -> None:
        key = _label_key(name)
        if not key or (key in allowed and allowed[key] != code):
            raise ProviderRequestError("WeVisOne 标签别名存在冲突或为空", code="MODEL_LABEL_AMBIGUOUS")
        allowed[key] = code
    for label in labels:
        register(label, label)
    # Only the task's frozen aliases may map server labels to canonical codes.
    # Ambiguous aliases are rejected, not assigned to whichever label came first.
    for code, names in (aliases or {}).items():
        if _label_key(code) not in allowed:
            continue
        for alias in names:
            if not str(alias).strip():
                continue
            register(str(alias), code)
    return allowed


def normalize_detection(payload: Any, *, width: int, height: int, labels: list[str],
                        label_aliases: Mapping[str, Sequence[str]] | None = None,
                        expected_contract: Mapping[str, str] | None = None) -> list[dict[str, Any]]:
    """Reject unknown wire contracts; never infer coordinate units from magnitude."""
    if not isinstance(payload, dict):
        raise ProviderRequestError("WeVisOne 检测响应不是 JSON 对象", code="MODEL_OUTPUT_PARSE_ERROR")
    if payload.get("error") or payload.get("detail") or payload.get("status") in {"failed", "refused", "error"}:
        raise ProviderRequestError("WeVisOne 检测失败或拒识", code="MODEL_OUTPUT_FAILED")
    response_text = payload.get("response")
    if response_text is not None and not isinstance(response_text, str):
        raise ProviderRequestError("WeVisOne 原始响应类型错误", code="MODEL_OUTPUT_PARSE_ERROR")
    if isinstance(response_text, str) and re.search(r"\b(cannot|unable|refus(?:e|ed)|sorry|error)\b|无法识别|拒绝", response_text, re.I):
        raise ProviderRequestError("WeVisOne 模型拒识或返回错误说明", code="MODEL_OUTPUT_FAILED")
    allowed = _label_mapping(labels, label_aliases)
    if "boxes" in payload:
        if not isinstance(payload["boxes"], list):
            raise ProviderRequestError("WeVisOne boxes 不是列表", code="MODEL_OUTPUT_PARSE_ERROR")
        rows = payload["boxes"]
        if rows and isinstance(response_text, str):
            raw = response_text.strip()
            if raw.lower() in _EMPTY:
                raise _protocol_conflict("WeVisOne 原始空目标响应与目标框矛盾")
            # Only inspect an explicitly empty native declaration here.  For
            # positive structured boxes, bbox_xyxy stays authoritative even
            # when a model's free-form raw text is not parseable.
            matches = list(_REF_BOX.finditer(raw))
            # A parseable native ref cannot contradict the frozen label
            # whitelist just because the service also supplied pixel boxes.
            # In particular, a joined two-query ref is NOT one valid class.
            if matches and not _REF_BOX.sub("", raw).strip(" \r\n\t,;。"):
                _native_boxes(raw, allowed_labels=allowed)
            if matches and not _REF_BOX.sub("", raw).strip(" \r\n\t,;。") and all(
                match.group(2).strip().lower() in _EMPTY for match in matches
            ):
                raise _protocol_conflict("WeVisOne 原始空目标响应与目标框矛盾")
        if not rows and response_text and response_text.strip().lower() not in _EMPTY:
            # Empty structured boxes must not hide raw detections or a parse failure.
            if _native_boxes(response_text):
                raise _protocol_conflict("WeVisOne 原始响应与空框列表矛盾")
    elif "detections" in payload and isinstance(payload["detections"], list):
        rows = payload["detections"]
    elif isinstance(response_text, str):
        rows = _native_boxes(response_text, allowed_labels=allowed)
    elif isinstance(payload.get("text"), str):
        rows = _native_boxes(payload["text"], allowed_labels=allowed)
    elif payload.get("no_target") is True:
        rows = []
    else:
        raise ProviderRequestError("WeVisOne 没有返回可识别的检测结果", code="MODEL_OUTPUT_PARSE_ERROR")
    if len(rows) > _MAX_DETECTIONS:
        raise ProviderRequestError("WeVisOne 单图目标数量超过 300", code="MODEL_OUTPUT_TOO_MANY_BOXES")
    # The service's width/height describe the *submitted* image coordinate
    # basis. A rescaled/cropped model image cannot be inverted without an
    # explicit preprocessing transform. Never silently treat its pixels as
    # original-image pixels.
    for dimension, expected_size in (("width", width), ("height", height)):
        if dimension in payload and (type(payload[dimension]) is not int or payload[dimension] != expected_size):
            raise ProviderRequestError("WeVisOne 响应尺寸与提交原图不一致，缺少可验证的缩放/补边还原信息",
                                       code="MODEL_COORDINATE_GEOMETRY_UNVERIFIED")
    converted = []
    for row in rows:
        if not isinstance(row, dict):
            raise ProviderRequestError("WeVisOne 目标框必须为对象", code="MODEL_OUTPUT_PARSE_ERROR")
        label = str(row.get("label") or row.get("category") or row.get("name") or "").strip()
        if _label_key(label) not in allowed:
            raise _label_failure(label, allowed=allowed, source="structured_boxes" if "boxes" in payload else "native_ref_box")
        label = allowed[_label_key(label)]
        coordinate_system = payload.get("coordinate_system")
        declared = {
            "xyxy_pixel": ("pixel", "xyxy"), "yxyx_pixel": ("pixel", "yxyx"),
            "xyxy_normalized_01": ("normalized_01", "xyxy"),
            "yxyx_normalized_01": ("normalized_01", "yxyx"),
            "xyxy_normalized_1000": ("normalized_1000", "xyxy"),
            "yxyx_normalized_1000": ("normalized_1000", "yxyx"),
        }
        if coordinate_system is not None and coordinate_system not in declared:
            raise ProviderRequestError("WeVisOne 未知坐标协议声明", code="MODEL_COORDINATE_SPACE_UNKNOWN")
        space = (declared[coordinate_system][0] if coordinate_system else
                 str(row.get("space") or row.get("coordinate_space") or payload.get("coordinate_space") or ""))
        order = (declared[coordinate_system][1] if coordinate_system else
                 str(row.get("coordinate_order") or payload.get("coordinate_order") or "xyxy"))
        origin = str(row.get("coordinate_origin") or payload.get("coordinate_origin") or "top_left")
        image_space = str(payload.get("coordinate_image_space") or "original_input")
        if space not in {"pixel", "normalized_01", "normalized_1000"} or order not in {"xyxy", "yxyx"} or origin not in {"top_left", "bottom_left"}:
            raise ProviderRequestError("WeVisOne API 未明确声明受支持的坐标单位、顺序和原点", code="MODEL_COORDINATE_SPACE_UNKNOWN")
        if image_space != "original_input":
            raise ProviderRequestError("WeVisOne 服务处理图缺少坐标还原几何证据", code="MODEL_COORDINATE_GEOMETRY_UNVERIFIED")
        # Native raw <ref>/<box> text always uses its own documented 0..1000
        # contract; otherwise the declared structured wire contract must match
        # the operator's saved expectation. No magnitude-based guessing.
        raw_fallback = "boxes" not in payload and "detections" not in payload and "space" in row
        if expected_contract and not raw_fallback:
            actual = {"coordinate_space": space, "coordinate_order": order,
                      "coordinate_origin": origin, "coordinate_image_space": image_space}
            if any(str(expected_contract.get(key) or default) != value
                   for key, default, value in (
                       ("coordinate_space", "pixel", actual["coordinate_space"]),
                       ("coordinate_order", "xyxy", actual["coordinate_order"]),
                       ("coordinate_origin", "top_left", actual["coordinate_origin"]),
                       ("coordinate_image_space", "original_input", actual["coordinate_image_space"]),
                   )):
                raise ProviderRequestError("WeVisOne 实际坐标协议与已保存配置不一致，请核对真实响应并重新验证配置",
                                           code="MODEL_COORDINATE_CONTRACT_MISMATCH")
        if "bbox_xyxy" in row:
            if coordinate_system != "xyxy_pixel":
                raise ProviderRequestError("WeVisOne bbox_xyxy 缺少 xyxy_pixel 坐标声明", code="MODEL_COORDINATE_SPACE_UNKNOWN")
            coords = row["bbox_xyxy"]
        elif "bbox_yxyx" in row:
            if coordinate_system != "yxyx_pixel":
                raise ProviderRequestError("WeVisOne bbox_yxyx 缺少 yxyx_pixel 坐标声明", code="MODEL_COORDINATE_SPACE_UNKNOWN")
            coords = row["bbox_yxyx"]
        elif "bbox_normalized" in row:
            if space != "normalized_01":
                raise ProviderRequestError("WeVisOne 归一化框缺少 normalized_01 声明", code="MODEL_COORDINATE_SPACE_UNKNOWN")
            coords = row["bbox_normalized"]
        else:
            coords = row.get("coordinates") or row.get("bbox") or row.get("box")
        if coords is None and all(key in row for key in ("x1", "y1", "x2", "y2")):
            coords = [row[key] for key in ("x1", "y1", "x2", "y2")]
        if not isinstance(coords, (list, tuple)) or len(coords) != 4:
            raise ProviderRequestError("WeVisOne 目标框缺少 XYXY 坐标", code="MODEL_COORDINATE_INVALID")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in coords):
            raise ProviderRequestError("WeVisOne 坐标不是有限数字", code="MODEL_COORDINATE_INVALID")
        x1, y1, x2, y2 = map(float, coords)
        if order == "yxyx":
            x1, y1, x2, y2 = y1, x1, y2, x2
        if space in {"normalized_01", "normalized_1000"}:
            divisor = 1 if space == "normalized_01" else 1000
            if not all(0 <= v <= divisor for v in (x1, y1, x2, y2)):
                raise ProviderRequestError("WeVisOne 归一化坐标越界", code="MODEL_COORDINATE_INVALID")
            x1, x2 = x1 * width / divisor, x2 * width / divisor
            y1, y2 = y1 * height / divisor, y2 * height / divisor
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ProviderRequestError("WeVisOne 像素坐标反向或超出原图", code="MODEL_COORDINATE_INVALID")
        if origin == "bottom_left":
            y1, y2 = height - y2, height - y1
        confidence = row.get("confidence")
        if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (float, int)) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ProviderRequestError("WeVisOne 置信度无效", code="MODEL_OUTPUT_PARSE_ERROR")
        if "confidence_status" in row and row["confidence_status"] != ("provided" if confidence is not None else "unavailable"):
            raise ProviderRequestError("WeVisOne 置信度声明与数值矛盾", code="MODEL_OUTPUT_PARSE_ERROR")
        converted.append({"label": label, "confidence": confidence,
                          "confidence_status": "provided" if confidence is not None else "unavailable",
                          "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return converted


class WeVisOneVisionProvider:
    def __init__(self, *, base_url: str, model: str, api_key: str = "", timeout: float = 180,
                 session: Any = requests, label_queries: Mapping[str, str] | None = None,
                 coordinate_contract: Mapping[str, str] | None = None):
        self.model = str(model or "").strip()
        if not self.model:
            raise ValueError("WeVisOne 模型 ID 不能为空")
        self.base_url = base_url
        self.timeout, self.session, self.api_key = timeout, session, str(api_key or "")
        self.label_queries = normalize_label_queries(label_queries)
        self.coordinate_contract = dict(coordinate_contract or {})
        self.detect_endpoint = _endpoint(base_url, "detect")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        return headers

    def _request(self, operation: str, *, image_bytes: bytes, labels: list[str], prompt: str = "") -> tuple[dict, int]:
        # The installed FastAPI service consumes image/image_url as a *data URI*
        # and query as a list or string. Generic chat prompts are NOT supported;
        # use label-specific native detection descriptions instead.
        del prompt
        _, _, mime = _validate_image(image_bytes)
        if not labels or len(labels) > 100 or any(not isinstance(x, str) or not x.strip() for x in labels):
            raise ProviderRequestError("WeVisOne 需提供 1～100 个冻结目标标签", code="MODEL_LABEL_NOT_ALLOWED")
        queries = [self.label_queries.get(label, label) if operation == "detect" else label for label in labels]
        if len({_label_key(query) for query in queries}) != len(queries):
            raise ProviderRequestError("WeVisOne 不同正式标签使用了相同的检测描述", code="MODEL_LABEL_AMBIGUOUS")
        data = {"image": f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii"),
                "query": queries}
        start = time.perf_counter()
        try:
            response = self.session.post(_endpoint(self.base_url, operation), json=data, headers=self._headers(), timeout=self.timeout)
        except requests.Timeout:
            raise ProviderRequestError("WeVisOne 推理超时", code="MODEL_REQUEST_TIMEOUT", solution="检查模型是否已加载及 GPU 负载。") from None
        except requests.RequestException:
            raise ProviderRequestError("WeVisOne 服务不可达", code="MODEL_SERVICE_UNREACHABLE", solution="检查地址、内网连通性与 model-switch 当前模型。") from None
        if not response.ok:
            try:
                error_payload = response.json()
            except (ValueError, AttributeError):
                error_payload = None
            metadata = response_metadata(response, error_payload, sensitive=(self.api_key, data["image"], data["image"].partition(",")[2]))
            error = ProviderRequestError(f"WeVisOne HTTP {response.status_code}", **metadata, **http_error(response, metadata), solution="请核对 image Data URI、冻结 query 数组、网关路径、鉴权及当前加载模型。")
            error.stage = "model_request"
            # Shape-only evidence: never echo a response body that may contain
            # submitted image data, credentials or user-controlled query text.
            error.diagnostics = {"request_contract": {"image": "data_uri", "query": "list[str]", "query_count": len(queries), "operation": operation}}
            raise error
        metadata = response_metadata(response, sensitive=(self.api_key, data["image"], data["image"].partition(",")[2]))
        try:
            payload = response.json()
        except ValueError:
            error = ProviderRequestError("WeVisOne 接口未返回 JSON", code="MODEL_OUTPUT_PARSE_ERROR", **metadata)
            error.stage = "response_parse"
            error.diagnostics = {"provider": "wevisone_vl", "model": self.model,
                                 "parser_source": "invalid_json", "label_match_status": "unavailable",
                                 "response_summary": {"parser_source": "invalid_json"}}
            raise error from None
        if not isinstance(payload, dict):
            error = ProviderRequestError("WeVisOne 接口响应格式错误", code="MODEL_OUTPUT_PARSE_ERROR", **metadata)
            error.stage = "response_parse"
            error.diagnostics = {"provider": "wevisone_vl", "model": self.model,
                                 "parser_source": "invalid_json_shape", "label_match_status": "unavailable",
                                 "response_summary": {"parser_source": "invalid_json_shape"}}
            raise error
        payload = dict(payload)
        payload["_platform_response_metadata"] = response_metadata(response, payload, sensitive=(self.api_key, data["image"], data["image"].partition(",")[2]))
        return payload, round((time.perf_counter() - start) * 1000)

    def inspect_model(self) -> dict[str, Any]:
        try:
            response = self.session.get(_endpoint(self.base_url, "models"), headers=self._headers(), timeout=8)
        except requests.RequestException:
            raise ProviderRequestError("WeVisOne 模型清单不可达", code="MODEL_SERVICE_UNREACHABLE") from None
        if not response.ok:
            metadata = response_metadata(response, sensitive=(self.api_key,))
            raise ProviderRequestError("WeVisOne 模型清单读取失败", **metadata, **http_error(response, metadata))
        try:
            data = response.json()
            listed = data.get("data") if isinstance(data, dict) else None
            model_ids = [str(x.get("id")) for x in listed if isinstance(x, dict)] if isinstance(listed, list) else []
        except ValueError:
            model_ids = []
        if self.model not in model_ids:
            raise ProviderRequestError("服务可达，但当前未加载所选 WeVisOne 模型", code="MODEL_NOT_LOADED", solution="先通过 model-switch 加载对应模型，再重新测试。")
        return {"reachable": True, "model_loaded": True}

    def annotate(self, *, image_bytes: bytes, prompt: str, output_schema: Mapping[str, Any],
                 labels: list[str] | None = None, label_aliases: Mapping[str, Sequence[str]] | None = None) -> dict:
        del output_schema
        labels = list(labels or [])
        if not labels:
            raise ValueError("WeVisOne 专用检测需要本次任务明确允许的标签")
        width, height, _ = _validate_image(image_bytes)
        aliases = {code: list(names) for code, names in (label_aliases or {}).items()}
        for code in labels:
            description = self.label_queries.get(code)
            if description:
                aliases.setdefault(code, []).append(description)
        _label_mapping(labels, aliases)  # Fail before network I/O on ambiguous frozen bindings.
        payload, elapsed = self._request("detect", image_bytes=image_bytes, labels=labels, prompt=prompt)
        response_info = payload.get("_platform_response_metadata") or {}
        evidence = {"provider": "wevisone_vl", "model": self.model,
                    "allowed_labels": list(labels)[:32],
                    "configured_queries": {code: _public_label(self.label_queries.get(code, code)) for code in labels[:32]},
                    "parser_source": "structured_boxes" if "boxes" in payload else "native_ref_box",
                    "response_summary": _response_summary(payload),
                    "backend_instance_id": response_info.get("backend_instance_id") or "",
                    "request_id": response_info.get("request_id") or ""}
        try:
            boxes = normalize_detection(payload, width=width, height=height, labels=labels,
                                        label_aliases=aliases, expected_contract=self.coordinate_contract)
        except ProviderRequestError as error:
            error.diagnostics = {**evidence, **dict(getattr(error, "diagnostics", {}) or {})}
            for key, value in response_info.items():
                setattr(error, key, value)
            error.status_code = int(response_info.get("status_code") or 200)
            error.stage = "coordinate_validation" if "COORDINATE" in error.code else "response_parse"
            raise
        return {"text": json.dumps({"boxes": boxes}, ensure_ascii=False), "latency_ms": elapsed,
                "provider": "wevisone_vl", "model": self.model, "api_protocol": "wevisone_native_v1",
                "diagnostics": {"parser_source": evidence["parser_source"],
                                "response_summary": evidence["response_summary"],
                                "zero_box": not boxes,
                                "label_match_status": "matched" if boxes else "no_targets"},
                "native_descriptions_applied": bool(self.label_queries and any(code in self.label_queries for code in labels)),
                **{k: v for k, v in payload.get("_platform_response_metadata", {}).items() if k != "server_error_code"}}

    def preview(self, operation: str, *, image_bytes: bytes, labels: list[str]) -> dict:
        if operation not in {"segment", "matting"}:
            raise ValueError("未知的 WeVisOne 视觉预览能力")
        payload, elapsed = self._request(operation, image_bytes=image_bytes, labels=labels)
        if payload.get("error") or payload.get("status") in {"failed", "error", "refused"}:
            raise ProviderRequestError("WeVisOne 预览推理失败", code="MODEL_OUTPUT_FAILED")
        if payload.get("detail"):
            raise ProviderRequestError("WeVisOne 预览服务返回错误", code="MODEL_OUTPUT_FAILED")
        total_base64_length = 0
        def decode_images(row: dict, fields: Mapping[str, str]) -> dict[str, str]:
            nonlocal total_base64_length
            images = {}
            for name, field in fields.items():
                raw = row.get(field)
                if raw is None:
                    continue
                if not isinstance(raw, str) or len(raw) > 14_000_000:
                    raise ProviderRequestError("WeVisOne 预览图过大或类型无效", code="MODEL_OUTPUT_PARSE_ERROR")
                total_base64_length += len(raw)
                if total_base64_length > 28_000_000:
                    raise ProviderRequestError("WeVisOne 预览图片总量超过 28MB", code="MODEL_OUTPUT_PARSE_ERROR")
                if raw.startswith("data:image/png;base64,"):
                    raw = raw.partition(",")[2]
                try:
                    binary = base64.b64decode(raw, validate=True)
                    with Image.open(io.BytesIO(binary)) as image:
                        if image.format != "PNG" or image.width * image.height > _MAX_IMAGE_PIXELS:
                            raise ValueError("preview must be bounded PNG")
                        image.verify()
                except (ValueError, OSError, binascii.Error, Image.DecompressionBombError):
                    raise ProviderRequestError("WeVisOne 预览图不是有效 PNG", code="MODEL_OUTPUT_PARSE_ERROR") from None
                images[name] = "data:image/png;base64," + raw
            return images

        if "instances" in payload:
            rows = payload["instances"]
            if not isinstance(rows, list) or len(rows) > _MAX_PREVIEW_INSTANCES:
                raise ProviderRequestError("WeVisOne 实例预览列表无效或过长", code="MODEL_OUTPUT_PARSE_ERROR")
            instances = []
            for index, row in enumerate(rows):
                if not isinstance(row, dict):
                    raise ProviderRequestError("WeVisOne 分割实例不是对象", code="MODEL_OUTPUT_PARSE_ERROR")
                name = str(row.get("label") or row.get("category") or "").strip()
                if name and name not in labels:
                    raise ProviderRequestError("WeVisOne 预览包含目标范围外类别", code="MODEL_LABEL_NOT_ALLOWED")
                images = decode_images(row, _PNG_FIELDS)
                if not images:
                    raise ProviderRequestError("WeVisOne 分割实例没有 PNG", code="MODEL_OUTPUT_PARSE_ERROR")
                instances.append({"index": index + 1, "label": name, "images": images})
            if not instances:
                return {"ok": True, "operation": operation, "latency_ms": elapsed,
                        "images": {}, "instances": [], "no_target": True,
                        "notice": "本图无可预览实例；不写入正式 GT。"}
            images = instances[0]["images"]
        else:
            images = decode_images(payload, _IMAGE_FIELDS)
            if not images:
                raise ProviderRequestError("WeVisOne 未返回可预览的实例 PNG", code="MODEL_OUTPUT_PARSE_ERROR", solution="检查 4070 专用接口响应字段合同。")
            instances = [{"index": 1, "label": "", "images": images}]
        return {"ok": True, "operation": operation, "latency_ms": elapsed, "images": images,
                "instances": instances, "no_target": False, "notice": "仅用于预览，不写入正式 GT。"}
