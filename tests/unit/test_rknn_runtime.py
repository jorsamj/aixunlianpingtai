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
            stdout='{"version":"2.3.2","supported_chips":["rk3568","rk3576"]}\n'
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
            stdout='{"version":"1.6.1b13","supported_chips":["rk3568"]}\n'
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
            stdout='{"version":"2.3.2","supported_chips":[]}\n'
        ),
    )
    result = runtime.probe_rknn_toolkit(sys.executable)
    assert result["available"] is False
    assert result["version"] == "2.3.2"
    assert result["supported_chips"] == []
    assert "neither rk3568 nor rk3576" in result["error"]
