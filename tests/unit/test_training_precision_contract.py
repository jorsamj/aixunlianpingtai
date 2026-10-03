import pytest

from platform_core.training_precision import (
    TrainingPrecisionError,
    normalize_training_precision,
    ultralytics_amp_value,
    verify_effective_training_precision,
)


def test_pinned_ultralytics_precision_contract_maps_to_boolean_amp():
    assert normalize_training_precision("auto") == "auto"
    assert normalize_training_precision("FP16") == "fp16"
    assert normalize_training_precision("fp32") == "fp32"
    assert ultralytics_amp_value("auto", True) is True
    assert ultralytics_amp_value("auto", False) is False
    assert ultralytics_amp_value("fp16", False) is True
    assert ultralytics_amp_value("fp32", True) is False


def test_bf16_fails_closed_until_runtime_is_explicitly_upgraded():
    with pytest.raises(TrainingPrecisionError, match="TRAINING_PRECISION_UNSUPPORTED"):
        normalize_training_precision("bf16")


def test_explicit_precision_must_match_ultralytics_runtime_truth():
    assert verify_effective_training_precision("auto", True) == "fp16"
    assert verify_effective_training_precision("auto", False) == "fp32"
    assert verify_effective_training_precision("fp16", True) == "fp16"
    assert verify_effective_training_precision("fp32", False) == "fp32"
    with pytest.raises(RuntimeError, match="TRAINING_PRECISION_UNAVAILABLE"):
        verify_effective_training_precision("fp16", False)
    with pytest.raises(RuntimeError, match="TRAINING_PRECISION_MISMATCH"):
        verify_effective_training_precision("fp32", True)
