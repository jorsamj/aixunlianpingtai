from __future__ import annotations

import sys

import platform_core.rknn_runtime as runtime


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


def test_probe_rknn_toolkit_reports_only_targets_that_pass_config_probe(monkeypatch):
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(
            stdout='{"version":"2.3.2","onnx_version":"1.18.0","onnx_mapping_available":true,"supported_chips":["rk3568","rk3576"]}\n'
        ),
    )
    result = runtime.probe_rknn_toolkit(sys.executable)
    assert result["available"] is True
    assert result["version"] == "2.3.2"
    assert result["supported_chips"] == ["rk3568", "rk3576"]


def test_probe_rknn_toolkit_does_not_claim_target_that_fails_config_probe(monkeypatch):
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(
            stdout='{"version":"1.6.1b13","onnx_version":"1.16.1","onnx_mapping_available":true,"supported_chips":["rk3568"]}\n'
        ),
    )
    result = runtime.probe_rknn_toolkit(sys.executable)
    assert result["available"] is True
    assert result["supported_chips"] == ["rk3568"]


def test_probe_rknn_toolkit_fails_closed_when_import_fails(monkeypatch):
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(
            returncode=1,
            stderr="No module named rknn",
        ),
    )
    result = runtime.probe_rknn_toolkit(sys.executable)
    assert result["available"] is False
    assert result["supported_chips"] == []
    assert "No module named rknn" in result["error"]


def test_probe_rknn_toolkit_fails_closed_when_no_supported_target_passes(monkeypatch):
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(
            stdout='{"version":"2.3.2","onnx_version":"1.18.0","onnx_mapping_available":true,"supported_chips":[]}\n'
        ),
    )
    result = runtime.probe_rknn_toolkit(sys.executable)
    assert result["available"] is False
    assert result["version"] == "2.3.2"
    assert result["supported_chips"] == []
    assert "neither rk3568 nor rk3576" in result["error"]



def test_rknn_probe_rejects_missing_onnx_mapping_even_when_config_supported(monkeypatch):
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(
            stdout='{"version":"2.3.2","onnx_version":"1.20.0","onnx_mapping_available":false,"supported_chips":["rk3568","rk3576"]}\n'
        ),
    )
    result = runtime.probe_rknn_toolkit(sys.executable)
    assert result["available"] is False
    assert result["supported_chips"] == []
    assert result["error_code"] == "RKNN_ONNX_DEPENDENCY_INCOMPATIBLE"
    assert "onnx.mapping" in result["error"]
    assert "1.20.0" in result["error"]


def test_rknn_probe_rejects_missing_onnx_dependency_evidence(monkeypatch):
    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(
            stdout='{"version":"2.3.2","supported_chips":["rk3568"]}\n'
        ),
    )
    result = runtime.probe_rknn_toolkit(sys.executable)
    assert result["available"] is False
    assert result["error_code"] == "RKNN_ONNX_DEPENDENCY_INCOMPATIBLE"


def test_rknn_onnx_dependency_compatibility_does_not_block_valid_mapping():
    assert runtime.rknn_onnx_dependency_error("1.18.0", True) == ""
    assert "onnx.mapping" in runtime.rknn_onnx_dependency_error("1.19.1", False)


def test_rknn_conversion_runner_rejects_incompatible_onnx_before_loading_model(monkeypatch):
    import types
    import pytest
    import rknn_convert_runner

    fake_onnx = types.ModuleType("onnx")
    fake_onnx.__version__ = "1.20.0"
    monkeypatch.setitem(sys.modules, "onnx", fake_onnx)
    monkeypatch.setattr(sys, "argv", [
        "rknn_convert_runner.py",
        "--onnx", "/does/not/need/to/exist.onnx",
        "--output", "/tmp/unused.rknn",
        "--chip", "rk3568",
    ])

    with pytest.raises(SystemExit) as raised:
        rknn_convert_runner.main()
    assert "RKNN_ONNX_DEPENDENCY_INCOMPATIBLE" in str(raised.value)
    assert "onnx.mapping" in str(raised.value)



def test_standalone_rknn_runner_does_not_import_platform_control_plane():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "rknn_convert_runner.py").read_text(
        encoding="utf-8"
    )
    assert "from platform_core" not in source
    assert "import platform_core" not in source
    assert "RKNN_ONNX_DEPENDENCY_INCOMPATIBLE" in source
