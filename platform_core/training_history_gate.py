"""Bounded, credential-free worker/Agent history authorization handshake."""
import json
import math
import os
from pathlib import Path
import time
from uuid import uuid4

_LIMIT = 8192


def _read(path):
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("history gate symlink rejected")
    try:
        with path.open("rb") as stream:
            raw = stream.read(_LIMIT + 1)
    except FileNotFoundError:
        return None
    if len(raw) > _LIMIT:
        raise ValueError("history gate message too large")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("history gate message must be an object")
    return value


def _write(path, value):
    if path.is_symlink():
        raise ValueError("history gate symlink rejected")
    raw = json.dumps(value, allow_nan=False).encode("utf-8")
    if len(raw) > _LIMIT:
        raise ValueError("history gate message too large")
    temporary = path.with_name(path.name + "." + uuid4().hex + ".tmp")
    try:
        with temporary.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _binding(task_id, attempt, snapshot_id, payload_ref):
    if type(attempt) is not int or attempt < 1 or not all(
        isinstance(x, str) and x for x in (task_id, snapshot_id, payload_ref)
    ):
        raise ValueError("invalid history gate binding")
    return dict(task_id=task_id, attempt=attempt, snapshot_id=snapshot_id, payload_ref=payload_ref)


def _validate(value, binding, *, fresh=True):
    if any(value.get(k) != v or type(value.get(k)) is not type(v) for k, v in binding.items()):
        raise ValueError("history gate binding mismatch")
    nonce = value.get("nonce")
    if not isinstance(nonce, str) or len(nonce) != 32 or any(c not in "0123456789abcdef" for c in nonce):
        raise ValueError("invalid history gate nonce")
    timestamp = value.get("timestamp")
    if (type(timestamp) not in (int, float) or not math.isfinite(timestamp)
            or (fresh and not (-5 <= time.time() - timestamp <= 60))):
        raise ValueError("expired history gate message")


def _directory(gate_dir):
    directory = Path(gate_dir)
    if directory.is_symlink() or (getattr(directory, 'is_junction', lambda: False)()):
        raise ValueError("history gate symlink rejected")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def request_history_gate(gate_dir, *, task_id, attempt, snapshot_id, payload_ref, timeout=30):
    binding = _binding(task_id, attempt, snapshot_id, payload_ref)
    directory = _directory(gate_dir)
    request = dict(binding, nonce=uuid4().hex, timestamp=time.time())
    _write(directory / "request.json", request)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = _read(directory / "response.json")
        if response is not None and response.get("nonce") == request["nonce"]:
            _validate(response, binding)
            if response.get("allowed") is not True:
                raise ValueError("history gate authorization denied")
            return response
        time.sleep(min(0.02, max(0, deadline - time.monotonic())))
    raise TimeoutError("history gate authorization timed out")


def service_history_gate(gate_dir, *, task_id, attempt, snapshot_id, payload_ref, check_callback):
    binding = _binding(task_id, attempt, snapshot_id, payload_ref)
    directory = _directory(gate_dir)
    request = _read(directory / "request.json")
    if request is None:
        return None
    _validate(request, binding, fresh=False)
    previous = _read(directory / "response.json")
    if previous is not None and previous.get("nonce") == request["nonce"]:
        # Already serviced work may remain while scoring/finalization continues.
        # Returning its record is not fresh authorization: the consumer always
        # validates response age and uses a fresh nonce for each new request.
        _validate(previous, binding, fresh=False)
        return previous
    _validate(request, binding)
    result = check_callback()
    if not isinstance(result, dict) or any(result.get(k) != v or type(result.get(k)) is not type(v) for k, v in binding.items()):
        raise ValueError("history gate callback binding mismatch")
    response = dict(binding, nonce=request["nonce"], timestamp=time.time(), allowed=result.get("allowed") is True)
    _write(directory / "response.json", response)
    return response
