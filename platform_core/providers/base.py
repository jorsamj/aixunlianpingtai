from typing import Any, Mapping, Protocol, TypedDict


class VisionProviderResult(TypedDict, total=False):
    text: str
    request_id: str
    latency_ms: int
    provider: str
    model: str
    api_protocol: str


class VisionProvider(Protocol):
    def annotate(self, *, image_bytes: bytes, prompt: str, output_schema: Mapping[str, Any]) -> VisionProviderResult:
        ...


class ProviderRequestError(RuntimeError):
    def __init__(self, message: str, *, code: str = "MODEL_REQUEST_FAILED", solution: str = "请检查模型服务配置后重试。", request_id: str = "", server_error_code: str = "", status_code: int = 0):
        evidence = "；".join(value for value in (
            f"服务端错误码：{server_error_code}" if server_error_code else "",
            f"request_id：{request_id}" if request_id else "",
        ) if value)
        super().__init__(message + ("；" + evidence if evidence else ""))
        self.code, self.solution = code, solution
        self.request_id, self.server_error_code, self.status_code = request_id, server_error_code, status_code
