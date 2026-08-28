import base64
import time
from typing import Any, Mapping, Optional

import requests

from .base import ProviderRequestError, VisionProviderResult


PRESETS = {
    "volcengine_ark": {
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "api": "chat_completions",
    },
    "aliyun_qwen": {"base_url": "", "api": "chat_completions"},
    "local_openai": {"base_url": "http://127.0.0.1:8000/v1", "api": "chat_completions"},
}


def _image_media_type(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if image_bytes.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _chat_endpoint(base_url: str) -> str:
    clean = str(base_url or "").strip().rstrip("/")
    if clean.endswith("/chat/completions"):
        return clean
    return clean + "/chat/completions"


class OpenAICompatibleVisionProvider:
    def __init__(
        self,
        *,
        provider: str,
        base_url: str = "",
        api_key: str = "",
        model: str,
        timeout: float = 180,
        headers: Optional[Mapping[str, Any]] = None,
        session: Any = requests,
    ):
        preset = PRESETS.get(provider, {})
        resolved_base = str(base_url or preset.get("base_url") or "").strip()
        if not resolved_base:
            raise ValueError("该模型服务必须配置 Base URL")
        if not str(model or "").strip():
            raise ValueError("模型名称不能为空")
        self.provider = provider
        self.endpoint = _chat_endpoint(resolved_base)
        self.api_key = str(api_key or "")
        self.model = str(model).strip()
        self.timeout = timeout
        self.headers = {str(key): str(value) for key, value in (headers or {}).items()}
        self.session = session

    def _request_body(self, *, image_bytes: bytes, prompt: str, output_schema: Mapping[str, Any], json_schema: bool) -> dict:
        encoded = base64.b64encode(image_bytes).decode("ascii")
        response_format = (
            {
                "type": "json_schema",
                "json_schema": {
                    "name": "candidate_annotations",
                    "strict": True,
                    "schema": dict(output_schema),
                },
            }
            if json_schema
            else {"type": "json_object"}
        )
        return {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": [
                    {"type": "text", "text": str(prompt)},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{_image_media_type(image_bytes)};base64,{encoded}"},
                    },
                ],
            }],
            "response_format": response_format,
            "temperature": 0,
        }

    def _post(self, body: Mapping[str, Any]):
        headers = {"Content-Type": "application/json", **self.headers}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        try:
            return self.session.post(self.endpoint, headers=headers, json=dict(body), timeout=self.timeout)
        except requests.RequestException as error:
            raise ProviderRequestError(
                f"无法连接模型服务 {self.endpoint}",
                code="MODEL_SERVICE_UNREACHABLE",
                solution="请检查服务地址、网络连接和模型是否已启动。",
            ) from error

    def annotate(self, *, image_bytes: bytes, prompt: str, output_schema: Mapping[str, Any]) -> VisionProviderResult:
        started = time.perf_counter()
        response = self._post(self._request_body(
            image_bytes=image_bytes,
            prompt=prompt,
            output_schema=output_schema,
            json_schema=True,
        ))
        if response.status_code == 400:
            response = self._post(self._request_body(
                image_bytes=image_bytes,
                prompt=prompt,
                output_schema=output_schema,
                json_schema=False,
            ))
        if not response.ok:
            raise ProviderRequestError(
                f"模型服务请求失败（HTTP {response.status_code}）",
                solution="请检查 API Key、模型名称、服务地域和接口权限。",
            )
        try:
            payload = response.json()
            message = payload["choices"][0]["message"]
            content = message.get("content", "")
            if isinstance(content, list):
                content = "".join(str(item.get("text") or "") for item in content if isinstance(item, dict))
            if not isinstance(content, str) or not content.strip():
                raise ValueError("响应中没有文本内容")
        except (ValueError, KeyError, IndexError, TypeError) as error:
            raise ProviderRequestError("模型服务返回格式不符合 OpenAI Chat Completions 协议") from error
        request_id = str(response.headers.get("x-request-id") or payload.get("id") or "")
        return {
            "text": content,
            "request_id": request_id,
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "provider": self.provider,
            "model": self.model,
        }


__all__ = ["OpenAICompatibleVisionProvider", "PRESETS", "ProviderRequestError"]
