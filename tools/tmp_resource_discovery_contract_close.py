from __future__ import annotations

from pathlib import Path


def replace_once(path: Path, old: str, new: str, label: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one match, got {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


REQUEST_SCOPE = '''"""Freeze discovery scan roots before durable task creation.

Whole-machine discovery is an explicit user action, but the worker must still
receive concrete roots. Resolving visible local filesystems at the HTTP/task
creation boundary makes a queued task auditable and replayable while preserving
the scanner's network/virtual-filesystem exclusions.
"""
from __future__ import annotations

import os
from collections.abc import Iterable

from .scanner import local_scan_roots


def _clean_roots(roots: Iterable[object] | None) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in roots or ():
        value = str(item or "").strip()
        if not value:
            continue
        key = os.path.normcase(
            os.path.normpath(os.path.abspath(os.path.expanduser(value)))
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    return result


def resolve_discovery_request_roots(
    scope: str,
    roots: Iterable[object] | None,
) -> list[str]:
    """Return roots that are safe to persist in a durable discovery request.

    Non-full scopes preserve caller-supplied roots. ``full`` always means all
    visible local filesystems on the API host; arbitrary caller roots are not
    accepted as a substitute for machine scope.
    """

    normalized_scope = str(scope or "").strip().lower()
    if normalized_scope != "full":
        return _clean_roots(roots)

    resolved = _clean_roots(os.fspath(path) for path in local_scan_roots())
    if not resolved:
        raise ValueError("全机扫描未发现可用的本地磁盘根目录")
    return resolved


__all__ = ["resolve_discovery_request_roots"]
'''


SCOPE_TESTS = '''from pathlib import Path

import pytest

from platform_core.resource_discovery import request_scope, tasks


def test_directory_model_worker_requires_durable_explicit_roots():
    with pytest.raises(ValueError, match="requires at least one explicit root"):
        tasks._model_scan_roots("directory", [])


def test_full_model_worker_also_requires_durable_explicit_roots():
    with pytest.raises(ValueError, match="requires at least one explicit root"):
        tasks._model_scan_roots("full", [])


def test_full_model_worker_uses_roots_frozen_in_task_payload():
    roots = [Path("one"), Path("two")]
    assert tasks._model_scan_roots("full", roots) == roots


def test_full_environment_worker_rejects_missing_task_roots():
    with pytest.raises(ValueError, match="requires at least one explicit root"):
        tasks._environment_deep_scan_allowed("full", [], 0)


def test_full_request_scope_freezes_visible_local_roots(monkeypatch, tmp_path):
    first = tmp_path / "disk-one"
    second = tmp_path / "disk-two"
    monkeypatch.setattr(request_scope, "local_scan_roots", lambda: [first, second])

    roots = request_scope.resolve_discovery_request_roots("full", ["ignored"])

    assert roots == [str(first), str(second)]


def test_full_request_scope_fails_closed_when_no_local_roots(monkeypatch):
    monkeypatch.setattr(request_scope, "local_scan_roots", lambda: [])
    with pytest.raises(ValueError, match="本地磁盘根目录"):
        request_scope.resolve_discovery_request_roots("full", [])


def test_non_full_scope_preserves_only_explicit_roots(tmp_path):
    root = tmp_path / "models"
    assert request_scope.resolve_discovery_request_roots(
        "directory", [str(root), "", str(root)]
    ) == [str(root)]
    assert request_scope.resolve_discovery_request_roots("auto", None) == []


def test_api_freezes_full_scan_roots_before_both_durable_tasks():
    source = Path("app.py").read_text(encoding="utf-8")
    assert "roots = resolve_discovery_request_roots(payload.scope, payload.roots)" in source
    assert "roots = resolve_discovery_request_roots(scope, submitted_roots)" in source
    assert '_create_discovery_task("ultralytics_environment", payload.scope, roots)' in source
    assert '_create_discovery_task("local_models", scope, roots)' in source


def test_frontend_full_scan_actions_remain_explicit_user_actions():
    source = Path("static/modules/resource-discovery.js").read_text(encoding="utf-8")
    assert "runtime.detectEnvironment({scope: 'full'})" in source
    assert "runtime.scanModels({scope: 'full'})" in source


def test_worker_model_handler_never_uses_implicit_none_roots():
    import inspect

    source = inspect.getsource(tasks.ResourceDiscoveryHandler._models)
    assert "scan_roots = _model_scan_roots(scope, roots)" in source
    assert "scan_model_files(\\n            scan_roots," in source
    assert '"scan_root_mode": "explicit"' in source
'''


def patch_app() -> None:
    path = Path("app.py")
    replace_once(
        path,
        "from platform_core.resource_discovery.tasks import (\n",
        "from platform_core.resource_discovery.request_scope import resolve_discovery_request_roots\n"
        "from platform_core.resource_discovery.tasks import (\n",
        "app discovery request-scope import",
    )
    replace_once(
        path,
        '''@app.post("/api/ultralytics_env/detect", status_code=202)
def detect_ultralytics_env(payload: UltralyticsEnvDetectReq):
    return _public_discovery_task(
        _create_discovery_task("ultralytics_environment", payload.scope, payload.roots)
    )
''',
        '''@app.post("/api/ultralytics_env/detect", status_code=202)
def detect_ultralytics_env(payload: UltralyticsEnvDetectReq):
    try:
        roots = resolve_discovery_request_roots(payload.scope, payload.roots)
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return _public_discovery_task(
        _create_discovery_task("ultralytics_environment", payload.scope, roots)
    )
''',
        "ultralytics full-scan root freeze",
    )
    replace_once(
        path,
        '''@app.post("/api/local_models/scan", status_code=202)
def scan_local_models(payload: LocalModelScanReq):
    roots = [value for value in (payload.roots or []) if str(value).strip()]
    scope = payload.scope or ("directory" if roots else "full")
    if scope == "directory" and not roots:
        raise HTTPException(status_code=422, detail="指定目录扫描至少需要一个目录")
    return _public_discovery_task(_create_discovery_task("local_models", scope, roots))
''',
        '''@app.post("/api/local_models/scan", status_code=202)
def scan_local_models(payload: LocalModelScanReq):
    submitted_roots = [value for value in (payload.roots or []) if str(value).strip()]
    scope = payload.scope or ("directory" if submitted_roots else "full")
    if scope == "directory" and not submitted_roots:
        raise HTTPException(status_code=422, detail="指定目录扫描至少需要一个目录")
    try:
        roots = resolve_discovery_request_roots(scope, submitted_roots)
    except ValueError as error:
        raise HTTPException(status_code=503, detail=str(error)) from error
    return _public_discovery_task(_create_discovery_task("local_models", scope, roots))
''',
        "model full-scan root freeze",
    )


def patch_tasks() -> None:
    path = Path("platform_core/resource_discovery/tasks.py")
    replace_once(
        path,
        '''HTTP routes only allocate generations and queue these tasks. Filesystem
traversal and Python subprocess probes are deliberately confined to the
discovery worker. Environment deep scans remain bounded to explicit request
roots. An explicit model scope=full action delegates local-machine root
resolution to the scanner, which excludes network and virtual filesystems.
''',
        '''HTTP routes allocate generations and queue these tasks. Filesystem traversal
and Python subprocess probes are deliberately confined to the discovery worker.
Deep filesystem traversal is bounded to explicit request roots. Whole-machine
roots are resolved and frozen before durable task creation; the worker never
expands a missing root set into an implicit machine scan.
''',
        "discovery worker policy docstring",
    )
    replace_once(
        path,
        '''def _model_scan_roots(scope: str, roots: list[Path]) -> list[Path] | None:
    """Resolve model scan roots without weakening directory-scan safety.

    ``directory`` always requires caller-supplied roots. ``full`` is itself an
    explicit user action and therefore delegates machine-local root discovery to
    ``scan_model_files`` by passing ``None``. The scanner remains responsible for
    excluding network and virtual filesystems cross-platform.
    """

    if scope == "directory":
        _require_model_roots(roots)
        return roots
    if scope == "full":
        return None
    raise ValueError("model discovery scope must be directory or full")
''',
        '''def _model_scan_roots(scope: str, roots: list[Path]) -> list[Path]:
    """Require the durable request to carry concrete roots for every deep scan."""

    if scope not in {"directory", "full"}:
        raise ValueError("model discovery scope must be directory or full")
    _require_model_roots(roots)
    return roots
''',
        "model worker fail-closed root resolver",
    )
    replace_once(
        path,
        '            "scan_root_mode": "local_machine" if scan_roots is None else "explicit",\n',
        '            "scan_root_mode": "explicit",\n',
        "model result explicit-root evidence",
    )


def patch_permanent_workflow() -> None:
    path = Path(".github/workflows/resource-discovery-sqlite-stability.yml")
    text = path.read_text(encoding="utf-8")
    marker = "      - platform_core/resource_discovery/cache.py\n"
    replacement = (
        "      - app.py\n"
        "      - static/modules/resource-discovery.js\n"
        "      - platform_core/resource_discovery/cache.py\n"
        "      - platform_core/resource_discovery/request_scope.py\n"
    )
    matches = text.count(marker)
    if matches != 2:
        raise SystemExit(f"permanent workflow path marker: expected 2 matches, got {matches}")
    text = text.replace(marker, replacement)
    old_compile = (
        "python -m py_compile platform_core/resource_discovery/cache.py "
        "platform_core/resource_discovery/scanner.py platform_core/resource_discovery/tasks.py "
        "tests/unit/test_resource_discovery_sqlite_lifecycle.py "
        "tests/unit/test_resource_discovery_scope_contract.py"
    )
    new_compile = (
        "python -m py_compile app.py platform_core/resource_discovery/cache.py "
        "platform_core/resource_discovery/request_scope.py "
        "platform_core/resource_discovery/scanner.py platform_core/resource_discovery/tasks.py "
        "tests/unit/test_resource_discovery_sqlite_lifecycle.py "
        "tests/unit/test_resource_discovery_scope_contract.py"
    )
    if text.count(old_compile) != 1:
        raise SystemExit("permanent workflow compile command mismatch")
    text = text.replace(old_compile, new_compile, 1)
    text = text.replace(
        "SQLite lifecycle and model full-scan scope guards",
        "SQLite lifecycle and durable discovery-scope guards",
        1,
    )
    path.write_text(text, encoding="utf-8")


def main() -> None:
    Path("platform_core/resource_discovery/request_scope.py").write_text(
        REQUEST_SCOPE, encoding="utf-8"
    )
    patch_app()
    patch_tasks()
    Path("tests/unit/test_resource_discovery_scope_contract.py").write_text(
        SCOPE_TESTS, encoding="utf-8"
    )
    patch_permanent_workflow()
    Path(".github/workflows/tmp-resource-discovery-contract-close.yml").unlink()
    Path("tools/tmp_resource_discovery_contract_close.py").unlink()


if __name__ == "__main__":
    main()
