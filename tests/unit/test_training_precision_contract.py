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


# The following contracts exercise the same Worker-local admission used by
# both the controller's training subprocess and a remote Agent subprocess.
from types import SimpleNamespace
from unittest.mock import Mock

from platform_core import training_precision as precision_module
from platform_core.training_precision import (
    AmpPreflight, preflight_worker_amp, scoped_worker_amp_check,
)


def _framework(cuda=True, version="8.4.127"):
    return (
        SimpleNamespace(cuda=SimpleNamespace(is_available=lambda: cuda)),
        SimpleNamespace(__version__=version, SETTINGS={}),
        SimpleNamespace(model=object()),
    )


def test_missing_reference_with_real_local_probe_result_never_downloads(tmp_path, monkeypatch):
    torch, ultra, model = _framework()
    checks = []
    monkeypatch.setattr(precision_module, "cuda_numeric_amp_probe", lambda runtime: checks.append(runtime) or True)
    monkeypatch.setattr(precision_module, "_reference_amp_check",
                        lambda *args: pytest.fail("missing reference must not invoke Ultralytics YOLO"))
    choice = preflight_worker_amp(requested_amp=True, torch=torch, ultralytics=ultra,
                                  train_model=model, project_dir=tmp_path / "projects" / "one")
    assert choice.enabled and choice.method == "cuda_numeric" and choice.result == "passed"
    assert checks == [torch]
    assert choice.reference_model == ""


def test_missing_reference_and_failed_numeric_probe_fall_back_to_fp32(tmp_path, monkeypatch):
    torch, ultra, model = _framework()
    monkeypatch.setattr(precision_module, "cuda_numeric_amp_probe", lambda _: False)
    choice = preflight_worker_amp(requested_amp=True, torch=torch, ultralytics=ultra,
                                  train_model=model, project_dir=tmp_path / "projects" / "one")
    assert not choice.enabled
    assert choice.result == "failed"
    assert choice.reason == "CUDA_FP16_PROBE_FAILED"


def test_numeric_probe_exception_is_not_a_successful_amp_check(tmp_path, monkeypatch):
    torch, ultra, model = _framework()
    def fail(_):
        raise RuntimeError("CUDA kernel unsupported")
    monkeypatch.setattr(precision_module, "cuda_numeric_amp_probe", fail)
    choice = preflight_worker_amp(requested_amp=True, torch=torch, ultralytics=ultra,
                                  train_model=model, project_dir=tmp_path / "projects" / "one")
    assert not choice.enabled and choice.method == "cuda_numeric"
    assert "CUDA_FP16_PROBE_ERROR" in choice.reason


def test_valid_local_check_model_uses_original_reference_contract(tmp_path, monkeypatch):
    torch, ultra, model = _framework()
    project = tmp_path / "projects" / "one"
    check_file = project / "models" / "yolo26n.pt"
    check_file.parent.mkdir(parents=True)
    check_file.write_bytes(b"unit-fixture")
    visited = []
    monkeypatch.setattr(precision_module, "_reference_amp_check",
                        lambda *args: visited.append(args[-1]) or True)
    monkeypatch.setattr(precision_module, "cuda_numeric_amp_probe",
                        lambda _: pytest.fail("reference exists: do not use numeric fallback"))
    choice = preflight_worker_amp(requested_amp=True, torch=torch, ultralytics=ultra,
                                  train_model=model, project_dir=project)
    assert choice.enabled and choice.method == "ultralytics_reference"
    assert visited == [check_file.resolve()]
    assert choice.reference_model == str(check_file.resolve())


def test_corrupt_reference_must_not_use_network_or_report_amp_passed(tmp_path, monkeypatch):
    torch, ultra, model = _framework()
    project = tmp_path / "projects" / "one"
    check_file = project / "models" / "yolo26n.pt"
    check_file.parent.mkdir(parents=True)
    check_file.write_bytes(b"corrupted")
    monkeypatch.setattr(precision_module, "_reference_amp_check",
                        lambda *args: (_ for _ in ()).throw(ValueError("corrupt checkpoint")))
    monkeypatch.setattr(precision_module, "cuda_numeric_amp_probe",
                        lambda _: pytest.fail("corrupt local reference must fail closed"))
    choice = preflight_worker_amp(requested_amp=True, torch=torch, ultralytics=ultra,
                                  train_model=model, project_dir=project)
    assert not choice.enabled and choice.result == "failed"
    assert "AMP_REFERENCE_INVALID" in choice.reason


def test_cpu_and_unknown_installed_runtime_do_not_claim_cuda_amp(tmp_path, monkeypatch):
    torch, ultra, model = _framework(cuda=False)
    monkeypatch.setattr(precision_module, "cuda_numeric_amp_probe",
                        lambda _: pytest.fail("CPU probe must not run"))
    assert not preflight_worker_amp(requested_amp=True, torch=torch, ultralytics=ultra,
                                    train_model=model, project_dir=tmp_path).enabled
    torch, ultra, model = _framework(version="8.4.143")
    choice = preflight_worker_amp(requested_amp=True, torch=torch, ultralytics=ultra,
                                  train_model=model, project_dir=tmp_path)
    assert not choice.enabled and choice.method == "version_guard"


def test_explicit_fp32_does_not_probe_or_patch(tmp_path, monkeypatch):
    torch, ultra, model = _framework()
    monkeypatch.setattr(precision_module, "cuda_numeric_amp_probe",
                        lambda _: pytest.fail("FP32 must never probe"))
    choice = preflight_worker_amp(requested_amp=False, torch=torch, ultralytics=ultra,
                                  train_model=model, project_dir=tmp_path)
    assert not choice.enabled and choice.result == "disabled"


def test_scoped_prevalidated_check_is_cuda_only_and_is_restored(monkeypatch):
    import sys
    import types

    package = types.ModuleType("ultralytics")
    engine = types.ModuleType("ultralytics.engine")
    trainer = types.ModuleType("ultralytics.engine.trainer")
    original = Mock(return_value=False)
    trainer.check_amp = original
    package.engine = engine
    engine.trainer = trainer
    monkeypatch.setitem(sys.modules, "ultralytics", package)
    monkeypatch.setitem(sys.modules, "ultralytics.engine", engine)
    monkeypatch.setitem(sys.modules, "ultralytics.engine.trainer", trainer)

    class Model:
        def __init__(self, name): self.name = name
        def parameters(self): return iter([SimpleNamespace(device=SimpleNamespace(type=self.name))])

    decision = AmpPreflight(True, "cuda_numeric", "passed", "numeric test passed")
    with scoped_worker_amp_check(decision):
        assert trainer.check_amp(Model("cuda")) is True
        assert trainer.check_amp(Model("cpu")) is False
    assert trainer.check_amp is original
    with pytest.raises(RuntimeError, match="AMP_RUNTIME_CHECK_HOOK_NOT_USED"):
        with scoped_worker_amp_check(decision):
            pass
    assert trainer.check_amp is original
    with pytest.raises(ValueError, match="original training failure"):
        with scoped_worker_amp_check(decision):
            trainer.check_amp(Model("cuda"))
            raise ValueError("original training failure")
    assert trainer.check_amp is original
