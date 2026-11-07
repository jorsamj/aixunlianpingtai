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

    source = (Path(__file__).resolve().parents[2] / "app.py").read_text(encoding="utf-8")
    delete = source.split("def v12_delete_version(", 1)[1].split("@app.post(", 1)[0]
    rollback = source.split("def v12_rollback_version(", 1)[1].split("@app.get(", 1)[0]
    assert "_safe_launch_reject_external_version_retirement(" in delete
    assert "_safe_launch_reject_external_version_retirement(" in rollback
