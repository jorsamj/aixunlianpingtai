from typing import Any, Mapping, Protocol, TypedDict


class VisionProviderResult(TypedDict, total=False):
    text: str
    request_id: str
    latency_ms: int
    provider: str
    model: str


class VisionProvider(Protocol):
    def annotate(self, *, image_bytes: bytes, prompt: str, output_schema: Mapping[str, Any]) -> VisionProviderResult:
        ...


class ProviderRequestError(RuntimeError):
    def __init__(self, message: str, *, code: str = "MODEL_REQUEST_FAILED", solution: str = "请检查模型服务配置后重试。"):
        super().__init__(message)
        self.code = code
        self.solution = solution
