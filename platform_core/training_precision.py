"""Canonical training-precision policy for the pinned Ultralytics runtime."""
from __future__ import annotations

SUPPORTED_TRAINING_PRECISIONS = frozenset({"auto", "fp16", "fp32"})


class TrainingPrecisionError(ValueError):
    pass


def normalize_training_precision(value: object) -> str:
    precision = str(value or "auto").strip().lower()
    if precision == "bf16":
        raise TrainingPrecisionError(
            "TRAINING_PRECISION_UNSUPPORTED: BF16 is not supported by the pinned "
            "Ultralytics training runtime; use auto, fp16 or fp32"
        )
    if precision not in SUPPORTED_TRAINING_PRECISIONS:
        raise TrainingPrecisionError(
            f"TRAINING_PRECISION_INVALID: unsupported precision {precision!r}"
        )
    return precision


def ultralytics_amp_value(precision: object, default_amp: bool = True) -> bool:
    """Map platform precision to Ultralytics 8.4.127's boolean amp contract."""
    normalized = normalize_training_precision(precision)
    if normalized == "auto":
        return bool(default_amp)
    if normalized == "fp16":
        return True
    return False


def verify_effective_training_precision(precision: object, trainer_amp: object) -> str:
    """Fail closed if an explicit precision request was not actually honored."""
    normalized = normalize_training_precision(precision)
    effective_amp = bool(trainer_amp)
    if normalized == "fp16" and not effective_amp:
        raise RuntimeError(
            "TRAINING_PRECISION_UNAVAILABLE: FP16 was requested but Ultralytics "
            "disabled AMP for the assigned runtime/device"
        )
    if normalized == "fp32" and effective_amp:
        raise RuntimeError(
            "TRAINING_PRECISION_MISMATCH: FP32 was requested but AMP is active"
        )
    return "fp16" if effective_amp else "fp32"
