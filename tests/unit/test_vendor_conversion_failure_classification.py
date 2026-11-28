"""Focused regression for vendor compiler failures and stale-artifact fences."""

import subprocess

import pytest

import deployment_worker as worker
from rknn_convert_runner import checked_rknn_step


@pytest.mark.parametrize("code", [
    "RKNN_CONFIG_FAILED", "RKNN_LOAD_ONNX_FAILED", "RKNN_BUILD_FAILED", "RKNN_EXPORT_FAILED",
])
def test_rknn_runner_emits_exact_failed_stage_without_masking_sdk_trace(capsys, code):
    with pytest.raises(RuntimeError, match="sdk failure"):
        checked_rknn_step(code, "SDK", lambda: (_ for _ in ()).throw(RuntimeError("sdk failure")))
    assert f"__RKNN_STAGE_ERROR__={code}" in capsys.readouterr().out


@pytest.mark.parametrize("marker,expected", [
    ("RKNN_CONFIG_FAILED", "RKNN_CONFIG_FAILED"),
    ("RKNN_LOAD_ONNX_FAILED", "RKNN_LOAD_ONNX_FAILED"),
    ("RKNN_BUILD_FAILED", "RKNN_BUILD_FAILED"),
    ("RKNN_EXPORT_FAILED", "RKNN_EXPORT_FAILED"),
])
def test_rknn_error_stage_is_preserved_from_isolated_runner(marker, expected):
    failure = worker.classify_rknn_conversion_failure(
        RuntimeError(f"命令执行失败，退出码 1\n__RKNN_STAGE_ERROR__={marker}\nOriginal SDK traceback"))
    assert failure.code == expected
    assert "数值不一致" in str(failure)


def test_rknn_unrecognized_error_never_claims_numeric_mismatch():
    assert worker.classify_rknn_conversion_failure(RuntimeError("memory exhausted")).code == "RKNN_CONVERSION_FAILED"
    assert worker.classify_rknn_conversion_failure(
        subprocess.TimeoutExpired(["rknn_convert_runner.py"], 60)).code == "RKNN_CONVERSION_TIMEOUT"


def test_rknn_old_output_cannot_be_reused_if_new_runner_generates_nothing(tmp_path, monkeypatch):
    source = tmp_path / "model.onnx"
    source.write_bytes(b"onnx-source")
    stale = tmp_path / "model_rk3568_fp.rknn"
    stale.write_bytes(b"previous-attempt-model")
    monkeypatch.setattr(worker, "run_cmd", lambda *_args, **_kwargs: "")
    with pytest.raises(ValueError, match="不存在或为空"):
        worker.build_rockchip(source, tmp_path, {}, {"chip": "rk3568", "precision": "fp16"},
                              None, tmp_path / "convert.log", verified_toolchain={})
    assert not stale.exists()


def test_rknn_new_zero_byte_model_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "model.onnx"
    source.write_bytes(b"onnx-source")

    def runner(_argv, *_args, **_kwargs):
        (tmp_path / "model_rk3568_fp.rknn").write_bytes(b"")
        return ""

    monkeypatch.setattr(worker, "run_cmd", runner)
    with pytest.raises(ValueError, match="不存在或为空"):
        worker.build_rockchip(source, tmp_path, {}, {"chip": "rk3568", "precision": "fp16"},
                              None, tmp_path / "convert.log", verified_toolchain={})
