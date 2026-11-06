"""Optional WeVisOne native vision API integration.

This provider owns its wire format.  All boxes returned to the platform are
canonical original-image pixels; generic OpenAI providers are untouched.
"""

import base64
import io
import json
import math
import re
import time
from typing import Any, Mapping
from urllib.parse import urlsplit, urlunsplit

import requests
from PIL import Image

from .base import ProviderRequestError


_REF_BOX = re.compile(r"<ref>([^<>]+)</ref>\s*<box>(.*?)</box>", re.I | re.S)
_COORD = re.compile(r"<(\d{1,4})>")
_EMPTY = {"none", "null", "no objects", "no object", "no targets", "无目标", "未检测到目标"}
_IMAGE_FIELDS = {"mask": "mask_image_base64", "alpha": "alpha_matte_base64", "foreground": "foreground_base64"}


def _endpoint(base_url: str, operation: str) -> str:
    parts = urlsplit(str(base_url or "").strip())
    if (parts.scheme not in {"http", "https"} or not parts.hostname or
            parts.username or parts.password or parts.query or parts.fragment):
        raise ValueError("WeVisOne 服务地址须为不含账号、查询参数的 HTTP(S) 地址")
    path = parts.path.rstrip("/")
    path = re.sub(r"/vision/(detect|segment|matting)$", "", path)
    path = re.sub(r"/models$", "", path)
    if path.endswith("/v1"):
        root = path
    elif not path or path == "/":
        root = "/v1"
    else:
        raise ValueError("WeVisOne 地址应为服务根地址或 /v1，不接受自定义聊天接口路径")
    return urlunsplit(parts._replace(path=root + ("/models" if operation == "models" else "/vision/" + operation)))


def _native_boxes(raw: str) -> list[dict[str, Any]]:
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
    for match in matches:
        label = match.group(1).strip()
        body = match.group(2).strip()
        groups = [part.strip() for part in body.split(",")]
        for part in groups:
            coords = _COORD.findall(part)
            if not label or len(coords) != 4 or _COORD.sub("", part).strip():
                raise ProviderRequestError("WeVisOne 原生目标框格式错误", code="MODEL_OUTPUT_PARSE_ERROR")
            boxes.append({"label": label, "coordinates": [int(c) for c in coords], "space": "normalized_1000"})
    return boxes


def normalize_detection(payload: Any, *, width: int, height: int, labels: list[str]) -> list[dict[str, Any]]:
    """Reject unknown wire contracts; never infer coordinate units from magnitude."""
    if not isinstance(payload, dict):
        raise ProviderRequestError("WeVisOne 检测响应不是 JSON 对象", code="MODEL_OUTPUT_PARSE_ERROR")
    if payload.get("error") or payload.get("status") in {"failed", "refused", "error"}:
        raise ProviderRequestError("WeVisOne 检测失败或拒识", code="MODEL_OUTPUT_FAILED")
    if "boxes" in payload and isinstance(payload["boxes"], list):
        rows = payload["boxes"]
    elif isinstance(payload.get("detections"), list):
        rows = payload["detections"]
    elif isinstance(payload.get("response"), str):
        rows = _native_boxes(payload["response"])
    elif isinstance(payload.get("text"), str):
        rows = _native_boxes(payload["text"])
    elif payload.get("no_target") is True:
        rows = []
    else:
        raise ProviderRequestError("WeVisOne 没有返回可识别的检测结果", code="MODEL_OUTPUT_PARSE_ERROR")
    allowed = set(labels)
    converted = []
    for row in rows:
        if not isinstance(row, dict):
            raise ProviderRequestError("WeVisOne 目标框必须为对象", code="MODEL_OUTPUT_PARSE_ERROR")
        label = str(row.get("label") or row.get("category") or "").strip()
        if label not in allowed:
            raise ProviderRequestError("WeVisOne 返回了本次任务范围外的标签", code="MODEL_LABEL_NOT_ALLOWED", solution="请检查目标标签，或先在已有标签映射中确认对应关系。")
        coords = row.get("coordinates") or row.get("bbox") or row.get("box")
        if coords is None and all(key in row for key in ("x1", "y1", "x2", "y2")):
            coords = [row[key] for key in ("x1", "y1", "x2", "y2")]
        if not isinstance(coords, (list, tuple)) or len(coords) != 4:
            raise ProviderRequestError("WeVisOne 目标框缺少 XYXY 坐标", code="MODEL_COORDINATE_INVALID")
        space = str(row.get("space") or row.get("coordinate_space") or payload.get("coordinate_space") or "")
        if space not in {"pixel", "normalized_1000"}:
            raise ProviderRequestError("WeVisOne API 未明确声明坐标单位", code="MODEL_COORDINATE_SPACE_UNKNOWN", solution="请使专用服务返回 coordinate_space=pixel 或 normalized_1000；不能依据数值猜测。")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in coords):
            raise ProviderRequestError("WeVisOne 坐标不是有限数字", code="MODEL_COORDINATE_INVALID")
        x1, y1, x2, y2 = map(float, coords)
        if space == "normalized_1000":
            if not all(0 <= v <= 1000 for v in (x1, y1, x2, y2)):
                raise ProviderRequestError("WeVisOne 归一化坐标越界", code="MODEL_COORDINATE_INVALID")
            x1, x2 = x1 * width / 1000, x2 * width / 1000
            y1, y2 = y1 * height / 1000, y2 * height / 1000
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ProviderRequestError("WeVisOne 像素坐标反向或超出原图", code="MODEL_COORDINATE_INVALID")
        confidence = row.get("confidence")
        if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (float, int)) or not math.isfinite(confidence) or not 0 <= confidence <= 1):
            raise ProviderRequestError("WeVisOne 置信度无效", code="MODEL_OUTPUT_PARSE_ERROR")
        converted.append({"label": label, "confidence": confidence,
                          "confidence_status": "provided" if confidence is not None else "unavailable",
                          "x1": x1, "y1": y1, "x2": x2, "y2": y2})
    return converted


class WeVisOneVisionProvider:
    def __init__(self, *, base_url: str, model: str, api_key: str = "", timeout: float = 180, session: Any = requests):
        self.model = str(model or "").strip()
        if not self.model:
            raise ValueError("WeVisOne 模型 ID 不能为空")
        self.base_url = base_url
        self.timeout, self.session, self.api_key = timeout, session, str(api_key or "")
        self.detect_endpoint = _endpoint(base_url, "detect")

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        return headers

    def _request(self, operation: str, *, image_bytes: bytes, labels: list[str], prompt: str = "") -> tuple[dict, int]:
        # This wire contract must be checked against the installed 4070 service;
        # the Tencent model library itself does not define HTTP endpoint shapes.
        data = {"model": self.model, "image_base64": base64.b64encode(image_bytes).decode("ascii"),
                "labels": labels, "prompt": prompt}
        start = time.perf_counter()
        try:
            response = self.session.post(_endpoint(self.base_url, operation), json=data, headers=self._headers(), timeout=self.timeout)
        except requests.Timeout:
            raise ProviderRequestError("WeVisOne 推理超时", code="MODEL_REQUEST_TIMEOUT", solution="检查模型是否已加载及 GPU 负载。") from None
        except requests.RequestException:
            raise ProviderRequestError("WeVisOne 服务不可达", code="MODEL_SERVICE_UNREACHABLE", solution="检查地址、内网连通性与 model-switch 当前模型。") from None
        if not response.ok:
            code = "MODEL_RESOURCE_NOT_FOUND" if response.status_code == 404 else "MODEL_AUTHENTICATION_FAILED" if response.status_code in (401, 403) else "MODEL_SERVICE_ERROR"
            raise ProviderRequestError(f"WeVisOne 接口返回 HTTP {response.status_code}", code=code, status_code=response.status_code, solution="核对专用接口地址、当前加载模型以及服务请求合同。")
        try:
            payload = response.json()
        except ValueError:
            raise ProviderRequestError("WeVisOne 接口未返回 JSON", code="MODEL_OUTPUT_PARSE_ERROR") from None
        if not isinstance(payload, dict):
            raise ProviderRequestError("WeVisOne 接口响应格式错误", code="MODEL_OUTPUT_PARSE_ERROR")
        return payload, round((time.perf_counter() - start) * 1000)

    def inspect_model(self) -> dict[str, Any]:
        try:
            response = self.session.get(_endpoint(self.base_url, "models"), headers=self._headers(), timeout=8)
        except requests.RequestException:
            raise ProviderRequestError("WeVisOne 模型清单不可达", code="MODEL_SERVICE_UNREACHABLE") from None
        if not response.ok:
            raise ProviderRequestError("WeVisOne 模型清单读取失败", code="MODEL_SERVICE_ERROR", status_code=response.status_code)
        try:
            data = response.json()
            listed = data.get("data") if isinstance(data, dict) else None
            model_ids = [str(x.get("id")) for x in listed if isinstance(x, dict)] if isinstance(listed, list) else []
        except ValueError:
            model_ids = []
        if self.model not in model_ids:
            raise ProviderRequestError("服务可达，但当前未加载所选 WeVisOne 模型", code="MODEL_NOT_LOADED", solution="先通过 model-switch 加载对应模型，再重新测试。")
        return {"reachable": True, "model_loaded": True}

    def annotate(self, *, image_bytes: bytes, prompt: str, output_schema: Mapping[str, Any], labels: list[str] | None = None) -> dict:
        del output_schema
        labels = list(labels or [])
        if not labels:
            raise ValueError("WeVisOne 专用检测需要本次任务明确允许的标签")
        with Image.open(io.BytesIO(image_bytes)) as image:
            width, height = image.size
        payload, elapsed = self._request("detect", image_bytes=image_bytes, labels=labels, prompt=prompt)
        boxes = normalize_detection(payload, width=width, height=height, labels=labels)
        return {"text": json.dumps({"boxes": boxes}, ensure_ascii=False), "latency_ms": elapsed,
                "provider": "wevisone_vl", "model": self.model, "api_protocol": "wevisone_native_v1",
                "request_id": ""}

    def preview(self, operation: str, *, image_bytes: bytes, labels: list[str]) -> dict:
        if operation not in {"segment", "matting"}:
            raise ValueError("未知的 WeVisOne 视觉预览能力")
        payload, elapsed = self._request(operation, image_bytes=image_bytes, labels=labels)
        if payload.get("error") or payload.get("status") in {"failed", "error", "refused"}:
            raise ProviderRequestError("WeVisOne 预览推理失败", code="MODEL_OUTPUT_FAILED")
        images = {}
        for name, field in _IMAGE_FIELDS.items():
            raw = payload.get(field)
            if raw is None:
                continue
            if not isinstance(raw, str) or len(raw) > 14_000_000:
                raise ProviderRequestError("WeVisOne 预览图过大或类型无效", code="MODEL_OUTPUT_PARSE_ERROR")
            if raw.startswith("data:image/png;base64,"):
                raw = raw.partition(",")[2]
            try:
                binary = base64.b64decode(raw, validate=True)
                with Image.open(io.BytesIO(binary)) as image:
                    if image.format != "PNG" or image.width * image.height > 25_000_000:
                        raise ValueError("preview must be bounded PNG")
            except (ValueError, OSError):
                raise ProviderRequestError("WeVisOne 预览图不是有效 PNG", code="MODEL_OUTPUT_PARSE_ERROR") from None
            images[name] = "data:image/png;base64," + raw
        if not images:
            raise ProviderRequestError("WeVisOne 未返回可预览的 Mask/Alpha/前景 PNG", code="MODEL_OUTPUT_PARSE_ERROR", solution="检查 4070 专用接口响应字段合同。")
        return {"ok": True, "operation": operation, "latency_ms": elapsed, "images": images,
                "notice": "仅用于预览，不写入正式 GT。"}
