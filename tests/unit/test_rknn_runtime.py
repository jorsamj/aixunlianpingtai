from __future__ import annotations
import sys
import platform_core.rknn_runtime as runtime

class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr

def test_probe_rknn_toolkit_reports_rk3568_and_rk3576_for_current_2x(monkeypatch):
    monkeypatch.setattr(runtime.subprocess, "run", lambda *_args, **_kwargs: Completed(stdout='{"version":"2.3.2"}\n'))
    result = runtime.probe_rknn_toolkit(sys.executable)
    assert result["available"] is True
    assert result["version"] == "2.3.2"
    assert result["supported_chips"] == ["rk3568", "rk3576"]

def test_probe_rknn_toolkit_does_not_claim_rk3576_for_old_toolkit(monkeypatch):
    monkeypatch.setattr(runtime.subprocess, "run", lambda *_args, **_kwargs: Completed(stdout='{"version":"1.6.0"}\n'))
    result = runtime.probe_rknn_toolkit(sys.executable)
    assert result["available"] is True
    assert result["supported_chips"] == ["rk3568"]

def test_probe_rknn_toolkit_fails_closed_when_import_fails(monkeypatch):
    monkeypatch.setattr(runtime.subprocess, "run", lambda *_args, **_kwargs: Completed(returncode=1, stderr="No module named rknn"))
    result = runtime.probe_rknn_toolkit(sys.executable)
    assert result["available"] is False
    assert result["supported_chips"] == []
    assert "No module named rknn" in result["error"]
