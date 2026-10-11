from __future__ import annotations

import sys

import platform_core.rknn_board_runtime as runtime


class Completed:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


def test_detect_rockchip_soc_maps_rk356x_family_and_rk3576(tmp_path):
    compatible = tmp_path / "compatible"
    compatible.write_bytes(b"rockchip,rk3568\x00vendor,board")
    result = runtime.detect_rockchip_soc(compatible, machine="aarch64")
    assert result["supported"] is True
    assert result["chip"] == "rk3568"

    compatible.write_bytes(b"rockchip,rk3576\x00vendor,board")
    result = runtime.detect_rockchip_soc(compatible, machine="arm64")
    assert result["supported"] is True
    assert result["chip"] == "rk3576"


def test_board_probe_requires_arm64_supported_soc_and_rknnlite(tmp_path, monkeypatch):
    compatible = tmp_path / "compatible"
    compatible.write_bytes(b"rockchip,rk3576\x00vendor,board")

    unsupported = runtime.probe_rknn_board_runtime(
        sys.executable,
        compatible_path=compatible,
        machine="x86_64",
    )
    assert unsupported["available"] is False

    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(stdout='{"version":"2.3.2"}\n'),
    )
    ready = runtime.probe_rknn_board_runtime(
        sys.executable,
        compatible_path=compatible,
        machine="aarch64",
    )
    assert ready["available"] is True
    assert ready["chip"] == "rk3576"
    assert ready["rknn_lite_version"] == "2.3.2"

    monkeypatch.setattr(
        runtime.subprocess,
        "run",
        lambda *_args, **_kwargs: Completed(returncode=1, stderr="No module named rknnlite"),
    )
    missing = runtime.probe_rknn_board_runtime(
        sys.executable,
        compatible_path=compatible,
        machine="aarch64",
    )
    assert missing["available"] is False
    assert "rknnlite" in missing["error"]
