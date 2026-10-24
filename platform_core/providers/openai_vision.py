import base64
import json
import re
import time
from typing import Any, Mapping, Optional
from urllib.parse import unquote, urlsplit, urlunsplit

import requests

from .base import ProviderRequestError, VisionProviderResult


PRESETS = {
    "volcengine_ark": {"base_url": "https://ark.cn-beijing.volces.com/api/v3", "api": "chat_completions"},
    "aliyun_qwen": {"base_url": "", "api": "chat_completions"},
    "local_openai": {"base_url": "http://127.0.0.1:8000/v1", "api": "chat_completions"},
}
API_PROTOCOLS = {"auto", "chat_completions", "responses"}
OUTPUT_FORMATS = {"auto", "json_schema", "json_object", "prompt"}
ENDPOINTS = {"chat_completions": "/chat/completions", "responses": "/responses"}


def resolve_api_endpoint(base_url: str, api_protocol: str = "auto") -> tuple[str, str]:
    """Resolve paths, never hostname/query substrings, without rewriting saved config."""
    if api_protocol not in API_PROTOCOLS:
        raise ValueError("API 协议必须为 auto、chat_completions 或 responses")
    parts = urlsplit(str(base_url or "").strip())
    if parts.scheme not in {"http", "https"} or not parts.netloc or parts.fragment:
        raise ValueError("模型接口须为不含 fragment 的 HTTP(S) 地址")
    path = parts.path.rstrip("/")
    detected = next((name for name, suffix in ENDPOINTS.items() if path.endswith(suffix)), None)
    protocol = detected if api_protocol == "auto" and detected else api_protocol
    if detected:
        path = path[:-len(ENDPOINTS[detected])] + ENDPOINTS[protocol]
    elif not path or re.search(r"/v\d+$", path):
        protocol = "chat_completions" if protocol == "auto" else protocol
        path += ENDPOINTS[protocol]
    elif protocol == "auto":
        raise ProviderRequestError(
            "自定义模型接口路径无法自动识别，请在高级设置确认 API 协议；已保存地址保持原样。",
            code="MODEL_PROTOCOL_REQUIRED", solution="选择 Chat Completions 或 Responses；自定义完整路径将原样使用。",
        )
    return urlunsplit(parts._replace(path=path)), protocol


def _chat_endpoint(base_url: str) -> str:
    return resolve_api_endpoint(base_url, "chat_completions")[0]


def _image_media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _image_reference(image_bytes: bytes, image_url: str) -> str:
    if image_url:
        if image_bytes:
            raise ValueError("图片字节与图片 URL 只能指定一种")
        if image_url.startswith("data:"):
            match = re.fullmatch(r"data:image/(?:jpeg|jpg|png|gif|webp);base64,([A-Za-z0-9+/=]+)", image_url)
            if not match:
                raise ValueError("图片 Data URL 格式无效")
            try:
                valid = bool(base64.b64decode(match[1], validate=True))
            except ValueError:
                valid = False
            if not valid:
                raise ValueError("图片 Base64 编码无效")
        else:
            parts = urlsplit(image_url)
            if parts.scheme not in {"http", "https"} or not parts.netloc or parts.username or parts.password:
                raise ValueError("图片 URL 必须为 HTTP(S) 或标准图片 Data URL")
        return image_url
    if not image_bytes:
        raise ValueError("图片输入不能为空")
    return f"data:{_image_media_type(image_bytes)};base64,{base64.b64encode(image_bytes).decode('ascii')}"


def _unsupported_format(response, payload) -> bool:
    if response.status_code != 400:
        return False
    error = payload.get("error", payload) if isinstance(payload, dict) else {"message": str(getattr(response, "text", ""))[:2000]}
    if not isinstance(error, dict):
        return False
    code = re.sub(r"[^a-z]", "", str(error.get("code") or "").lower())
    if any(reason in code for reason in ("invalidapikey", "authentication", "unauthorized", "accessdenied", "permission", "modelnotfound", "invalidmodel", "unsupportedmodel", "invalidendpoint", "quota", "ratelimit", "balance")):
        return False
    param = str(error.get("param") or "").lower()
    fields = ("text.format", "response_format", "json_schema", "json_object")
    if param and not any(param == f or param.startswith(f + ".") for f in fields):
        return False
    text = " ".join(str(error.get(k) or "") for k in ("code", "message", "detail", "param")).lower()
    return any(f in text for f in fields) and any(word in text for word in (
        "unsupported", "not supported", "not support", "doesn't support", "unrecognized", "unknown parameter", "不支持",
    ))


HTTP_ERRORS = {
    400: ("MODEL_BAD_REQUEST", "请求参数错误", "请检查模型、图片输入和协议参数。"),
    401: ("MODEL_AUTHENTICATION_FAILED", "认证失败", "请检查该服务商 API Key 是否有效。"),
    403: ("MODEL_PERMISSION_DENIED", "访问权限不足", "请检查项目及模型访问权限。"),
    404: ("MODEL_RESOURCE_NOT_FOUND", "接口路径或模型资源不存在", "请检查完整接口地址、API 协议、地域及模型 ID。"),
    429: ("MODEL_RATE_LIMITED", "请求频率或额度限制", "请检查频率限制与可用额度，稍后再试。"),
}


class OpenAICompatibleVisionProvider:
    def __init__(self, *, provider: str, base_url: str = "", api_key: str = "", model: str,
                 api_protocol: str = "auto", structured_output: str = "auto", timeout: float = 180,
                 headers: Optional[Mapping[str, Any]] = None, session: Any = requests):
        resolved_base = str(base_url or PRESETS.get(provider, {}).get("base_url") or "").strip()
        if not resolved_base:
            raise ValueError("该模型服务必须配置 Base URL")
        if not str(model or "").strip():
            raise ValueError("模型名称不能为空")
        if structured_output not in OUTPUT_FORMATS:
            raise ValueError("结构化输出必须为 auto、json_schema、json_object 或 prompt")
        self.endpoint, self.api_protocol = resolve_api_endpoint(resolved_base, api_protocol)
        self.provider, self.model = provider, str(model).strip()
        self.api_key, self.structured_output = str(api_key or ""), structured_output
        self.timeout, self.session = timeout, session
        self.headers = {str(key): str(value) for key, value in (headers or {}).items()}

    def _request_body(self, *, image: str, prompt: str, output_schema: Mapping[str, Any], output_format: str) -> dict:
        if output_format in {"prompt", "json_object"}:
            prompt += "\n只输出一个合法 JSON 对象，不附加思考或说明。必须符合以下 JSON Schema：" + json.dumps(dict(output_schema), ensure_ascii=False)
        fmt = {"type": output_format}
        if output_format == "json_schema":
            fmt.update(name="candidate_annotations", strict=True, schema=dict(output_schema))
        if self.api_protocol == "responses":
            body = {"model": self.model, "stream": False, "store": False, "input": [{"role": "user", "content": [
                {"type": "input_text", "text": prompt}, {"type": "input_image", "image_url": image},
            ]}]}
            if output_format != "prompt":
                body["text"] = {"format": fmt}
            return body
        body = {"model": self.model, "stream": False, "temperature": 0, "messages": [{"role": "user", "content": [
            {"type": "text", "text": prompt}, {"type": "image_url", "image_url": {"url": image}},
        ]}]}
        if output_format != "prompt":
            body["response_format"] = {"type": "json_schema", "json_schema": {k: v for k, v in fmt.items() if k != "type"}} if output_format == "json_schema" else fmt
        return body

    def _post(self, body):
        headers = {"Content-Type": "application/json", **self.headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            return self.session.post(self.endpoint, headers=headers, json=body, timeout=self.timeout)
        except requests.Timeout:
            raise ProviderRequestError("模型服务请求超时", code="MODEL_REQUEST_TIMEOUT", solution="请检查模型响应耗时、服务负载和网络，确认后重试。") from None
        except requests.RequestException:
            raise ProviderRequestError("无法连接模型服务", code="MODEL_SERVICE_UNREACHABLE", solution="请检查服务地址、网络连接和模型是否已启动。") from None

    def _metadata(self, response, payload, image):
        error = payload.get("error") if isinstance(payload, dict) else None
        error = error if isinstance(error, dict) else {}
        sensitive = [self.api_key, image, image.partition(",")[2] if image.startswith("data:") else ""]
        parts = urlsplit(self.endpoint)
        sensitive.extend((parts.username or "", parts.password or "", unquote(parts.password or "")))
        for key, value in self.headers.items():
            if key.lower() in {"authorization", "x-api-key", "api-key", "apikey"}:
                sensitive.extend([value, value.removeprefix("Bearer ")])
        def safe(value):
            text = str(value or "")
            if not re.fullmatch(r"[A-Za-z0-9_./:-]{1,160}", text) or any(secret and secret in text for secret in sensitive):
                return ""
            return text
        headers = {str(k).lower(): v for k, v in response.headers.items()}
        return {
            "request_id": safe(headers.get("x-request-id") or headers.get("x-tt-logid") or error.get("request_id") or (payload.get("request_id") or payload.get("id") if isinstance(payload, dict) else "")),
            "server_error_code": safe(error.get("code")), "status_code": response.status_code,
        }

    def _output_text(self, payload):
        if not isinstance(payload, dict):
            raise ProviderRequestError("模型响应不是 JSON 对象", code="MODEL_OUTPUT_PARSE_ERROR")
        if self.api_protocol == "responses":
            state = payload.get("status")
            if state != "completed":
                code = "MODEL_OUTPUT_FAILED" if state == "failed" else "MODEL_OUTPUT_INCOMPLETE"
                raise ProviderRequestError("模型响应未完成，不能作为有效标注", code=code)
            texts = []
            for item in payload.get("output") or []:
                if not isinstance(item, dict) or item.get("type") != "message":
                    continue
                if item.get("status") not in {None, "completed"}:
                    raise ProviderRequestError("模型输出消息未完成", code="MODEL_OUTPUT_INCOMPLETE")
                if item.get("role", "assistant") != "assistant" or item.get("phase") not in {None, "final_answer"}:
                    continue
                for part in item.get("content") or []:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "refusal":
                        raise ProviderRequestError("模型拒绝提供标注结果", code="MODEL_OUTPUT_REFUSED")
                    if part.get("type") == "output_text" and isinstance(part.get("text"), str):
                        texts.append(part["text"])
            content = "".join(texts)
        else:
            choice = payload["choices"][0]
            message = choice["message"]
            if message.get("refusal") or choice.get("finish_reason") == "content_filter":
                raise ProviderRequestError("模型拒绝提供标注结果", code="MODEL_OUTPUT_REFUSED")
            if choice.get("finish_reason") not in {None, "stop"}:
                raise ProviderRequestError("模型回答被截断或未提供最终文本", code="MODEL_OUTPUT_INCOMPLETE")
            content = message.get("content", "")
            if isinstance(content, list):
                content = "".join(p.get("text", "") for p in content if isinstance(p, dict) and p.get("type") in {None, "text", "output_text"} and isinstance(p.get("text"), str))
        if not isinstance(content, str) or not content.strip():
            raise ProviderRequestError("模型响应没有可用的最终标注文本", code="MODEL_OUTPUT_PARSE_ERROR")
        return content

    def annotate(self, *, image_bytes: bytes = b"", image_url: str = "", prompt: str, output_schema: Mapping[str, Any]) -> VisionProviderResult:
        started = time.perf_counter()
        image = _image_reference(image_bytes, image_url)
        formats = ("json_schema", "json_object", "prompt") if self.structured_output == "auto" else (self.structured_output,)
        for index, fmt in enumerate(formats):
            response = self._post(self._request_body(image=image, prompt=prompt, output_schema=output_schema, output_format=fmt))
            try:
                payload = response.json()
            except ValueError:
                payload = None
            metadata = self._metadata(response, payload, image)
            if not response.ok:
                if index + 1 < len(formats) and _unsupported_format(response, payload):
                    continue
                code, message, solution = HTTP_ERRORS.get(response.status_code, ("MODEL_SERVICE_ERROR" if response.status_code >= 500 else "MODEL_REQUEST_FAILED", "模型服务端异常" if response.status_code >= 500 else "模型服务请求失败", "请联系模型服务方核查请求记录。"))
                raise ProviderRequestError(f"{message}（HTTP {response.status_code}）", code=code, solution=solution, **metadata)
            try:
                text = self._output_text(payload)
            except ProviderRequestError as error:
                raise ProviderRequestError(str(error), code=error.code, **metadata) from None
            except (KeyError, IndexError, TypeError, AttributeError, ValueError):
                raise ProviderRequestError("模型服务返回格式不符合配置的 API 协议", code="MODEL_OUTPUT_PARSE_ERROR", **metadata) from None
            return {"text": text, "request_id": metadata["request_id"], "latency_ms": round((time.perf_counter() - started) * 1000), "provider": self.provider, "model": self.model, "api_protocol": self.api_protocol}


__all__ = ["OpenAICompatibleVisionProvider", "PRESETS", "ProviderRequestError", "resolve_api_endpoint"]
