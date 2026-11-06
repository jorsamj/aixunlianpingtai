import base64
import time
from typing import Any, Mapping

import requests

from .base import ProviderRequestError, VisionProviderResult, response_metadata, http_error


class OllamaVisionProvider:
    def __init__(
        self,
        *,
        model: str,
        base_url: str = "http://127.0.0.1:11434",
        timeout: float = 180,
        session: Any = requests,
    ):
        if not str(model or "").strip():
            raise ValueError("Ollama 模型名称不能为空")
        clean = str(base_url or "http://127.0.0.1:11434").strip().rstrip("/")
        self.endpoint = clean if clean.endswith("/api/chat") else clean + "/api/chat"
        self.model = str(model).strip()
        self.timeout = timeout
        self.session = session

    def annotate(self, *, image_bytes: bytes, prompt: str, output_schema: Mapping[str, Any]) -> VisionProviderResult:
        body = {
            "model": self.model,
            "messages": [{
                "role": "user",
                "content": str(prompt),
                "images": [base64.b64encode(image_bytes).decode("ascii")],
            }],
            "format": dict(output_schema),
            "stream": False,
            "options": {"temperature": 0},
        }
        started = time.perf_counter()
        try:
            response = self.session.post(self.endpoint, json=body, timeout=self.timeout)
        except requests.Timeout:
            raise ProviderRequestError("Ollama 推理超时", code="MODEL_REQUEST_TIMEOUT") from None
        except requests.RequestException:
            raise ProviderRequestError(
                "无法连接本地 Ollama 服务",
                code="MODEL_SERVICE_UNREACHABLE",
                solution="请检查本地服务地址、确认 Ollama 已启动，并确认视觉模型已经加载。",
            ) from None
        if not response.ok:
            try:
                error_payload = response.json()
            except ValueError:
                error_payload = None
            metadata = response_metadata(response, error_payload, sensitive=(body["messages"][0]["images"][0],))
            raise ProviderRequestError(
                f"Ollama 请求失败（HTTP {response.status_code}）", **metadata, **http_error(response, metadata),
                solution="请检查本地服务地址和模型名称，确认该模型支持图片输入且已经加载。",
            )
        try:
            payload = response.json()
            content = payload["message"]["content"]
            if not isinstance(content, str) or not content.strip():
                raise ValueError("响应中没有文本内容")
        except (ValueError, KeyError, TypeError) as error:
            raise ProviderRequestError("Ollama 返回格式无效，缺少 message.content") from None
        return {
            "text": content,
            **{k: v for k, v in response_metadata(response, payload, sensitive=(body["messages"][0]["images"][0],)).items() if k != "server_error_code"},
            "latency_ms": round((time.perf_counter() - started) * 1000),
            "provider": "ollama",
            "model": self.model,
        }
