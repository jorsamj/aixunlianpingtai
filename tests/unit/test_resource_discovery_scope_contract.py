from pathlib import Path

import pytest

from platform_core.resource_discovery import scanner, tasks


def test_directory_model_scan_still_requires_explicit_root():
    with pytest.raises(ValueError, match="requires at least one explicit root"):
        tasks._model_scan_roots("directory", [])


def test_full_model_scan_delegates_machine_root_resolution_to_scanner():
    assert tasks._model_scan_roots("full", []) is None
    assert tasks._model_scan_roots("full", [Path("ignored-for-full-scope")]) is None


def test_model_handler_uses_scope_resolver_for_scanner_invocation():
    import inspect

    source = inspect.getsource(tasks.ResourceDiscoveryHandler._models)
    assert "scan_roots = _model_scan_roots(scope, roots)" in source
    assert "scan_model_files(\n            scan_roots," in source


def test_scanner_none_roots_discovers_visible_local_roots(monkeypatch, tmp_path):
    model = tmp_path / "best.pt"
    model.write_bytes(b"model")
    discovered = []

    monkeypatch.setattr(scanner, "local_scan_roots", lambda platform=None: [tmp_path])
    monkeypatch.setattr(scanner, "mount_boundaries", lambda platform=None: ())

    report = scanner.scan_model_files(None, on_item=discovered.append)

    assert report.models_found == 1
    assert [Path(row["path"]).name for row in discovered] == ["best.pt"]


def test_full_scope_does_not_reuse_caller_roots_as_fake_machine_roots():
    roots = [Path("one"), Path("two")]
    assert tasks._model_scan_roots("full", roots) is None
