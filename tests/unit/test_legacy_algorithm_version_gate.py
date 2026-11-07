"""Minimal-safe-launch guards for legacy algorithm version mutation routes."""

import pytest
from fastapi import HTTPException

import app


def test_manual_model_version_assignment_is_fail_closed():
    # The legacy route previously fabricated training_status=SUCCEEDED and
    # artifact_verified=True for arbitrary local model files.
    with pytest.raises(HTTPException) as error:
        app.v12_assign_version("project", "algorithm", None)
    assert error.value.status_code == 409
    assert "手工模型归属暂未开放" in str(error.value.detail)


def test_legacy_training_archive_uses_existing_atomic_version_cas():
    from pathlib import Path

    source = (Path(__file__).resolve().parents[2] / "app.py").read_text(encoding="utf-8")
    archive = source.split("def _v48_archive_training_version(", 1)[1].split(
        "# v16：测试环境选择", 1
    )[0]
    assert "attach_algorithm_version_if_current(" in archive
    assert "expected_current_version_id=" in archive
    assert "attach_algorithm_version(" not in archive
    assert "shutil.rmtree(vd, ignore_errors=True)" in archive
