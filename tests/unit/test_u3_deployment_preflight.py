from pathlib import Path

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.u3_deployment_preflight import preflight, rollback_readiness


def test_preflight_fails_closed_without_postgres_or_projects(tmp_path):
    result = preflight(tmp_path / "data", "")
    assert result["status"] == "BLOCKED"
    assert "PG_UNAVAILABLE" in result["blockers"]
    assert "NO_PROJECTS" in result["blockers"]
    assert result["writes_performed"] is False
    assert result["read_switch_enabled"] is False


def test_rollback_readiness_keeps_sqlite_owner_with_pg_unavailable(tmp_path):
    data_dir = tmp_path / "data"
    project = data_dir / "projects" / "p1"
    MaterialRepository(project)
    AnnotationRepository(project)
    result = preflight(data_dir, "")
    assert result["projects"]["p1"]["status"] == "AVAILABLE"
    rollback = rollback_readiness(data_dir, "")
    assert rollback["sqlite_owner_available"] is True
    assert rollback["read_switch_enabled"] is False
    assert rollback["keep_owner_data"] is True
    assert rollback["ready"] is False
