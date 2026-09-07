from pathlib import Path


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
