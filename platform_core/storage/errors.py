from __future__ import annotations

import re
from typing import Any


_SECRET_PATTERNS = (
    re.compile(r"(?i)(authorization\s*:\s*bearer\s+)[^\s,;]+"),
    re.compile(
        r"(?i)((?:api[_-]?key|access[_-]?token|secret(?:_access_key)?|token)\s*[=:]\s*)[^\s,;]+"
    ),
    re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b"),
)


def redact_storage_error(value: object) -> str:
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(
            lambda match: (match.group(1) if match.lastindex else "") + "[REDACTED]",
            text,
        )
    return text[:2000]


class StorageError(RuntimeError):
    def __init__(
        self,
        *,
        code: str,
        message: str,
        detail: str = "",
        solution: str = "",
        retryable: bool = False,
        context: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(detail or message)
        self.code = str(code)
        self.message = str(message)
        self.detail = str(detail)
        self.solution = str(solution)
        self.retryable = bool(retryable)
        self.context = dict(context or {})

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": redact_storage_error(self.message),
            "detail": redact_storage_error(self.detail),
            "solution": redact_storage_error(self.solution),
            "retryable": self.retryable,
            "context": {
                str(key): redact_storage_error(value)
                for key, value in self.context.items()
            },
        }

