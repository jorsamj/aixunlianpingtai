import math
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Mapping, Protocol, TypedDict


class VisionProviderResult(TypedDict, total=False):
    text: str
    request_id: str
    latency_ms: int
    provider: str
    model: str
    backend_instance_id: str
    actual_model: str
    status_code: int
    api_protocol: str


class VisionProvider(Protocol):
    def annotate(self, *, image_bytes: bytes, prompt: str, output_schema: Mapping[str, Any]) -> VisionProviderResult:
        ...


class ProviderRequestError(RuntimeError):
    def __init__(self, message: str, *, code: str = "MODEL_REQUEST_FAILED", solution: str = "请检查模型服务配置后重试。", request_id: str = "", server_error_code: str = "", status_code: int = 0, retryable: bool | None = None, retry_after_seconds: float | None = None, backend_instance_id: str = "", actual_model: str = ""):
        evidence = "；".join(value for value in (
            f"服务端错误码：{server_error_code}" if server_error_code else "",
            f"request_id：{request_id}" if request_id else "",
        ) if value)
        super().__init__(message + ("；" + evidence if evidence else ""))
        self.code, self.solution = code, ("请检查服务商账户余额、可用额度和计费状态；处理后手动重试。" if code == "MODEL_QUOTA_EXCEEDED" else solution)
        self.request_id, self.server_error_code, self.status_code = request_id, server_error_code, status_code

        self.retryable = (code in {"MODEL_REQUEST_TIMEOUT", "MODEL_SERVICE_UNREACHABLE", "MODEL_RATE_LIMITED"} or status_code in {500, 502, 503, 504}) if retryable is None else retryable
        self.retry_after_seconds = retry_after_seconds
        self.backend_instance_id, self.actual_model = backend_instance_id, actual_model


def response_metadata(response, payload=None, *, sensitive=()):
    """Bounded trace identifiers only; never echo upstream messages."""
    headers = {str(k).lower(): v for k, v in getattr(response, "headers", {}).items()}
    root = payload if isinstance(payload, dict) else {}
    error = root.get("error") if isinstance(root.get("error"), dict) else root
    def safe(value):
        text = str(value or "")
        return text if re.fullmatch(r"[A-Za-z0-9_./:-]{1,160}", text) and not text.lower().startswith(("data:", "bearer", "sk-")) and not any(secret and str(secret) in text for secret in sensitive) else ""
    return {"request_id": safe(headers.get("x-request-id") or headers.get("x-tt-logid") or error.get("request_id") or root.get("request_id") or root.get("id")),
            "backend_instance_id": safe(headers.get("x-backend-instance-id") or root.get("backend_instance_id")),
            "actual_model": safe(root.get("model") or root.get("actual_model")),
            "server_error_code": safe(error.get("code")), "status_code": getattr(response, "status_code", 200)}


def retry_after(response):
    headers = {str(k).lower(): v for k, v in getattr(response, "headers", {}).items()}
    value = str(headers.get("retry-after", "")).strip()
    try:
        seconds = float(value) if re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", value) else (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds()
        return seconds if math.isfinite(seconds) and 0 <= seconds <= 86400 else None
    except (ValueError, TypeError, OverflowError):
        return None


def http_error(response, metadata, *, provider=""):
    status = response.status_code
    code = {400: "MODEL_REQUEST_CONTRACT_INVALID", 422: "MODEL_REQUEST_CONTRACT_INVALID", 401: "MODEL_AUTHENTICATION_FAILED", 403: "MODEL_PERMISSION_DENIED", 404: "MODEL_RESOURCE_NOT_FOUND", 429: "MODEL_RATE_LIMITED"}.get(status, "MODEL_SERVICE_ERROR" if status >= 500 else "MODEL_REQUEST_FAILED")
    server_code = metadata.get("server_error_code", "").lower()
    exhausted = {"billing_hard_limit_reached", "quota_exceeded", "insufficient_balance", "arrearage", "allocationquota.freetieronly"}
    # Alibaba documents insufficient_quota / Throttling.AllocationQuota as TPM
    # throttling; the same OpenAI code elsewhere can mean depleted billing quota.
    if provider != "aliyun_qwen":
        exhausted.add("insufficient_quota")
    if status in {403,429} and server_code in exhausted:
        code = "MODEL_QUOTA_EXCEEDED"
    return {"code": code, "retryable": status in {429, 500, 502, 503, 504} and code != "MODEL_QUOTA_EXCEEDED", "retry_after_seconds": retry_after(response)}
