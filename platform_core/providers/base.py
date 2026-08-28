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
