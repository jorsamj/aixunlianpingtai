"""Shared training resource policy primitives.

This module owns only deterministic policy/math shared by admission and the
canonical resource resolver. It never selects a GPU and never mutates a
training request.
"""
from __future__ import annotations

from typing import Mapping

from .training_precision import normalize_training_precision

GIB = 1024 ** 3

_PROFILE_CONFIGS = {
    "stability": {
        "gpu_fraction": 0.58,
        "worker_cap": 4,
        "ram_fraction": 0.22,
        "batch_cap": 64,
    },
    "balanced": {
        "gpu_fraction": 0.70,
        "worker_cap": 8,
        "ram_fraction": 0.35,
        "batch_cap": 128,
    },
    "performance": {
        "gpu_fraction": 0.82,
        "worker_cap": 12,
        "ram_fraction": 0.50,
        "batch_cap": 256,
    },
}


def resource_profile_config(value: object) -> dict[str, float | int]:
    profile = str(value or "balanced").strip().lower()
    config = _PROFILE_CONFIGS.get(profile)
    if config is None:
        raise ValueError("RESOURCE_PROFILE_INVALID")
    return dict(config)


def precision_policy(
    request: Mapping[str, object],
    *,
    device: object | None = None,
) -> dict[str, object]:
    requested = normalize_training_precision(request.get("precision") or "auto")
    selected_device = str(
        request.get("device") if device is None else device
    ).strip().lower()
    resolved = requested
    if requested == "auto":
        resolved = (
            "fp16"
            if selected_device.startswith("cuda:") and request.get("amp") is not False
            else "fp32"
        )
    return {
        "requested_precision": requested,
        "resolved_precision": resolved,
        "activation_precision_factor": 2.0 if resolved == "fp32" else 1.0,
    }


def model_memory_components(
    request: Mapping[str, object],
    model,
    *,
    device: object | None = None,
) -> dict[str, object]:
    policy = precision_policy(request, device=device)
    params = sum(int(value.numel()) for value in model.model.parameters())
    fixed = max(GIB, params * 24)
    per_image = int(
        256 * 1024 ** 2
        * max(1.0, (params / 3_000_000) ** 0.55)
        * (int(request.get("imgsz") or 640) / 640) ** 2
        * (1 + float(request.get("multi_scale") or 0)) ** 2
        * float(policy["activation_precision_factor"])
    )
    return {
        **policy,
        "parameter_count": params,
        "fixed_bytes": fixed,
        "per_image_bytes": per_image,
    }


def auto_admission_evidence(
    request: Mapping[str, object],
    model,
) -> dict[str, object]:
    if str(request.get("resource_strategy") or "auto").strip().lower() != "auto":
        raise ValueError("RESOURCE_STRATEGY_INVALID")
    profile = str(request.get("resource_profile") or "balanced").strip().lower()
    profile_cfg = resource_profile_config(profile)
    memory = model_memory_components(request, model, device="cuda:0")
    floor = int(memory["fixed_bytes"]) + int(memory["per_image_bytes"])
    return {
        "schema_version": 1,
        "mode": "deferred_auto_assignment",
        "resource_profile": profile,
        "target_gpu_memory_fraction": float(profile_cfg["gpu_fraction"]),
        "gpu_memory_floor_bytes": floor,
        "memory_model": {
            "parameter_count": int(memory["parameter_count"]),
            "fixed_bytes": int(memory["fixed_bytes"]),
            "per_image_bytes": int(memory["per_image_bytes"]),
            "requested_precision": memory["requested_precision"],
            "resolved_precision": memory["resolved_precision"],
            "activation_precision_factor": memory["activation_precision_factor"],
        },
    }


def deferred_auto_reservation_bytes(
    payload: Mapping[str, object],
    *,
    total_bytes: int,
    free_bytes: int,
    already_reserved_bytes: int,
    active_count: int,
) -> int | None:
    if payload.get("resource_resolution_deferred") is not True:
        return None
    if str(payload.get("resource_strategy") or "auto").strip().lower() != "auto":
        raise ValueError("RESOURCE_DEFERRED_STRATEGY_INVALID")
    floor = int(payload.get("gpu_memory_floor_bytes") or 0)
    if floor <= 0:
        raise ValueError("RESOURCE_ADMISSION_ESTIMATE_MISSING")
    profile_cfg = resource_profile_config(payload.get("resource_profile") or "balanced")
    total = max(0, int(total_bytes))
    free = max(0, int(free_bytes))
    reserved = max(0, int(already_reserved_bytes))
    reserve_floor = max(GIB, int(total * 0.05))
    available = max(0, free - reserved - reserve_floor)
    planning_budget = max(0, int(available * float(profile_cfg["gpu_fraction"])))
    if planning_budget < floor:
        return 0
    # An idle card may reserve the whole profile planning budget so the one
    # canonical resolver can exploit its real capacity after assignment.
    # Shared admission stays at the batch=1 floor and therefore remains
    # conservative until runtime evidence proves headroom.
    return floor if int(active_count) > 0 else planning_budget
