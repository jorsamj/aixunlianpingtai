from platform_core.runtime_paths import resolve_data_dir


def test_data_dir_prefers_explicit_then_shared_environment(monkeypatch, tmp_path):
    configured = tmp_path / "configured data"
    explicit = tmp_path / "explicit data"
    monkeypatch.setenv("MC_TRAIN_DATA_DIR", str(configured))
    monkeypatch.setenv("MC_DATA_DIR", str(tmp_path / "legacy data"))
    assert resolve_data_dir() == configured.resolve()
    assert resolve_data_dir(explicit) == explicit.resolve()


def test_data_dir_supports_legacy_environment_only_as_fallback(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy data"
    monkeypatch.delenv("MC_TRAIN_DATA_DIR", raising=False)
    monkeypatch.setenv("MC_DATA_DIR", str(legacy))
    assert resolve_data_dir() == legacy.resolve()
