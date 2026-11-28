from dataclasses import dataclass


@dataclass
class PlatformError(Exception):
    code: str
    message: str
    detail: str
    solution: str = ""
    status_code: int = 400
    request_id: str = ""
    server_error_code: str = ""
    upstream_status: int = 0


def error_body(error: PlatformError) -> dict:
    body = {
        "ok": False,
        "code": error.code,
        "message": error.message,
        "detail": error.detail,
        "solution": error.solution,
    }

    for key in ("request_id", "server_error_code", "upstream_status"):
        if value := getattr(error, key):
            body[key] = value
    return body
