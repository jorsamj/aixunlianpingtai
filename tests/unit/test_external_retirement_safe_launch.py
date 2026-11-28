"""Remote deletion must be isolated until durable reconciliation is proven."""

import pytest
from fastapi import HTTPException

import app


def test_safe_launch_blocks_only_external_changlian_algorithm_retirement(monkeypatch):
    algorithms = [{
        "id": "external-1", "source_type": "EXTERNAL",
        "provider_type": "CHANG_LIAN",
    }, {
        "id": "local-1", "source_type": "LOCAL",
        "provider_type": "",
    }]
    monkeypatch.setattr(app, "list_algorithms_internal", lambda *_: algorithms)
    with pytest.raises(HTTPException) as error:
        app._safe_launch_reject_external_version_retirement("project", "external-1")
    assert error.value.status_code == 409
    assert "暂时停用" in str(error.value.detail)
    assert app._safe_launch_reject_external_version_retirement("project", "local-1") is None


def test_version_delete_and_rollback_routes_consume_safe_launch_guard():
    from pathlib import Path

    import ast

    root = Path(__file__).resolve().parents[2]
    source = (root / "platform_core/algorithm_catalog_service.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    service = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "AlgorithmCatalogService")
    methods = {node.name: ast.get_source_segment(source, node) for node in service.body if isinstance(node, ast.FunctionDef)}
    assert "self._safe_launch_reject_external_version_retirement(" in methods["v12_delete_version"]
    assert "self._safe_launch_reject_external_version_retirement(" in methods["v12_rollback_version"]
    api = (root / "platform_core/algorithm_catalog_api.py").read_text(encoding="utf-8")
    assert "return service().v12_delete_version(" in api
    assert "return service().v12_rollback_version(" in api
