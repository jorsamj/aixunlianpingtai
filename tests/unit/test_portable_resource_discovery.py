from pathlib import Path
from types import SimpleNamespace


def test_resource_discovery_uses_configured_cross_platform_roots(monkeypatch, tmp_path: Path):
    import app as app_module

    first = tmp_path / "ultralytics runtime"
    second = tmp_path / "paddle runtime"
    monkeypatch.setenv("MC_ULTRALYTICS_ROOTS", str(first))
    monkeypatch.setenv("MC_PADDLE_ROOTS", str(second))

    ultra = app_module.default_ultralytics_roots()
    paddle = app_module.default_paddle_roots()

    assert ultra[0] == str(first)
    assert paddle[0] == str(second)
    assert all("yolosuanfa" not in value.lower() for value in ultra[:1] + paddle[:1])


def test_ultralytics_probe_decodes_child_output_as_utf8(monkeypatch, tmp_path: Path):
    import app as app_module

    captured = {}

    def run_probe(*args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(
            returncode=0,
            stdout='{"ok": true, "version": "版本", "package_path": "包/路径"}\n',
            stderr="",
        )

    monkeypatch.setattr(app_module.subprocess, "run", run_probe)
    result = app_module._check_ultralytics_python(Path("python"), tmp_path)

    assert result is not None
    assert result["version"] == "版本"
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"
