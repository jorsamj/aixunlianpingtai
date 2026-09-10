"""Canonical Ultralytics training configuration contract.

Only this module translates user-facing values into the configuration passed to
Ultralytics.  Task metadata may contain many other fields, but none of them may
silently override this contract once ``requested_config`` has been persisted.
"""
from __future__ import annotations

from typing import Any, Mapping

from .training_devices import normalize_training_device


DEFAULTS: dict[str, Any] = {
    "model": "yolo11n.pt", "epochs": 50, "imgsz": 640, "batch": 8,
    "workers": 0, "device": "auto", "patience": 100, "optimizer": "auto",
    "lr0": 0.01, "lrf": 0.01, "momentum": 0.937, "weight_decay": 0.0005,
    "warmup_epochs": 3.0, "mosaic": 1.0, "close_mosaic": 10, "mixup": 0.0,
    "multi_scale": 0.0, "hsv_h": 0.015, "hsv_s": 0.7, "hsv_v": 0.4,
    "degrees": 0.0, "translate": 0.1, "scale": 0.5, "shear": 0.0,
    "perspective": 0.0, "flipud": 0.0, "fliplr": 0.5, "seed": 0,
    "save_period": -1, "freeze": 0, "cache": False, "amp": True,
    "pretrained": True, "deterministic": True, "cos_lr": False,
    "single_cls": False, "rect": False,
}
TRAINING_KEYS = tuple(DEFAULTS)
_INTS = {"epochs", "imgsz", "batch", "workers", "patience", "close_mosaic", "seed", "save_period", "freeze"}
_FLOATS = {"lr0", "lrf", "momentum", "weight_decay", "warmup_epochs", "mosaic", "mixup", "multi_scale",
           "hsv_h", "hsv_s", "hsv_v", "degrees", "translate", "scale", "shear", "perspective", "flipud", "fliplr"}
_BOOLS = {"amp", "pretrained", "deterministic", "cos_lr", "single_cls", "rect"}


def _boolean(value: Any, key: str) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, str)) and str(value).strip().lower() in {"1", "true"}:
        return True
    if isinstance(value, (int, str)) and str(value).strip().lower() in {"0", "false"}:
        return False
    raise ValueError(f"TRAINING_CONFIG_INVALID: {key} must be boolean")


def _cache(value: Any) -> bool | str:
    text = str(value).strip().lower()
    if value is False or text in {"", "0", "false", "none"}:
        return False
    if value is True or text in {"1", "true", "ram"}:
        return "ram"
    if text == "disk":
        return "disk"
    raise ValueError("TRAINING_CONFIG_INVALID: cache must be false, ram, or disk")


def normalize_training_config(values: Mapping[str, Any], *, strict: bool = False) -> dict[str, Any]:
    if strict:
        unknown = sorted(set(values) - set(TRAINING_KEYS))
        if unknown:
            raise ValueError(f"TRAINING_CONFIG_UNKNOWN: {', '.join(unknown)}")
    result = dict(DEFAULTS)
    for key in TRAINING_KEYS:
        if key not in values or values[key] is None:
            continue
        value = values[key]
        if key in _INTS:
            if isinstance(value, bool):
                raise ValueError(f"TRAINING_CONFIG_INVALID: {key} must be integer")
            value = int(value)
        elif key in _FLOATS:
            value = float(value)
        elif key in _BOOLS:
            value = _boolean(value, key)
        elif key == "cache":
            value = _cache(value)
        elif key == "device":
            value = normalize_training_device(value)
        else:
            value = str(value).strip()
        result[key] = value
    if not result["model"]:
        raise ValueError("TRAINING_CONFIG_INVALID: model is required")
    if result["epochs"] < 1 or result["imgsz"] < 32:
        raise ValueError("TRAINING_CONFIG_INVALID: epochs/imgsz out of range")
    if result["batch"] == 0 or result["batch"] < -1 or result["workers"] < 0:
        raise ValueError("TRAINING_CONFIG_INVALID: batch/workers out of range")
    if result["optimizer"].lower() not in {"auto", "sgd", "adam", "adamw", "nadam", "radam", "rmsprop"}:
        raise ValueError("TRAINING_CONFIG_INVALID: unsupported optimizer")
    return result


def requested_training_config(payload: Mapping[str, Any]) -> dict[str, Any]:
    nested = payload.get("requested_config")
    top = {key: payload[key] for key in TRAINING_KEYS if key in payload}
    if isinstance(nested, Mapping):
        normalized = normalize_training_config(nested, strict=True)
        for key, value in top.items():
            if normalize_training_config({key: value})[key] != normalized[key]:
                raise ValueError(f"TRAINING_CONFIG_CONFLICT: {key}")
        return normalized
    return normalize_training_config(top)


def effective_training_config(requested: Mapping[str, Any], *, assigned_device: str,
                              actual_model: str, resolved_resources: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    config = normalize_training_config(requested, strict=True)
    assigned = normalize_training_device(assigned_device)
    if assigned == "auto" or (config["device"] != "auto" and config["device"] != assigned):
        raise ValueError(f"TRAINING_DEVICE_ASSIGNMENT_MISMATCH: requested={config['device']}; assigned={assigned}")
    effective = {**config, "model": str(actual_model), "device": assigned,
                 "batch": int(resolved_resources["resolved_batch"]),
                 "workers": int(resolved_resources["resolved_workers"]),
                 "cache": _cache(resolved_resources["resolved_cache"])}
    reasons = list(resolved_resources.get("reasons") or [])
    if config["device"] != assigned:
        reasons.insert(0, f"device: {config['device']} -> {assigned} (scheduler assignment)")
    for key in ("model", "batch", "workers", "cache"):
        if config[key] != effective[key]:
            reasons.append(f"{key}: {config[key]} -> {effective[key]}")
    return effective, reasons


def ultralytics_training_args(config: Mapping[str, Any]) -> dict[str, Any]:
    normalized = normalize_training_config(config, strict=True)
    result = {key: value for key, value in normalized.items() if key not in {"model", "device"}}
    result["device"] = "cpu" if normalized["device"] == "cpu" else "0"
    return result
