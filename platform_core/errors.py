from dataclasses import dataclass


@dataclass
class PlatformError(Exception):
    code: str
    message: str
    detail: str
    solution: str = ""
    status_code: int = 400


def error_body(error: PlatformError) -> dict:
    return {
        "ok": False,
        "code": error.code,
        "message": error.message,
        "detail": error.detail,
        "solution": error.solution,
    }

