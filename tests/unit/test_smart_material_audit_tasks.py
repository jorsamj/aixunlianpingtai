import json
import sqlite3

import pytest

from platform_core.material_batches import BatchRequestError
from platform_core.material_repository import MaterialRepository
from platform_core.task_runtime import ArtifactStore, TaskRepository, TaskKind


def setup_project(tmp_path):
    project = tmp_path / "projects/p"
    store = MaterialRepository(project)
    store.upsert_many([dict(id=name, filename=name+".png", content_sha256="a"*64) for name in ("one", "two")])
    return project, store, TaskRepository(tmp_path/"tasks.sqlite3"), ArtifactStore(tmp_path/"artifacts")


def enable(tmp_path, max_images=1000):
    environment = tmp_path / "optional-env"
    binary = environment / "Scripts/python.exe"
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b"test configuration only, not executed")
    (environment/"pyvenv.cfg").write_text("include-system-site-packages = false\n")
    (tmp_path/"smart_material_audit.json").write_text(json.dumps(dict(enabled=True, python=str(binary), max_images=max_images)))


def test_disabled_audit_does_not_change_materials_or_create_tasks(tmp_path):
    from platform_core.smart_material_audit.service import estimate_audit
    project, store, repository, artifacts = setup_project(tmp_path)
    before = store.read()
    with pytest.raises(BatchRequestError, match="未启用") as caught:
        estimate_audit(tmp_path, "p", {"scope": "FILTERED", "filters": {}})
    assert caught.value.code == "SMART_AUDIT_DISABLED"
    assert store.read() == before
    assert not repository.list(project_id="p", limit=50).items


def test_audit_creation_is_idempotent_and_original_material_owner_is_readonly(tmp_path):
    from platform_core.smart_material_audit.service import estimate_audit, create_audit
    project, store, repository, artifacts = setup_project(tmp_path)
    enable(tmp_path)
    before = store.read()
    estimate = estimate_audit(tmp_path, "p", {"scope": "SELECTED", "image_ids": ["one", "two"]})
    payload = dict(selection_spec=estimate["selection_spec"], options={"request_id": "request-1"})
    first = create_audit(tmp_path, "p", repository, artifacts, payload, actor={"actor_id": "u"})
    second = create_audit(tmp_path, "p", repository, artifacts, payload, actor={"actor_id": "u"})
    assert first.task_id == second.task_id
    assert first.kind == TaskKind.MATERIAL_BATCH
    assert first.required_capabilities == ("materials.batch", "materials.smart_audit")
    assert len(repository.list(project_id="p", limit=50).items) == 1
    assert store.read() == before
    with sqlite3.connect(artifacts.artifact_path(first.task_id, "selection.sqlite3")) as frozen:
        assert frozen.execute("SELECT image_id FROM selection ORDER BY image_id").fetchall() == [("one",), ("two",)]
    with pytest.raises(BatchRequestError) as caught:
        create_audit(tmp_path, "p", repository, artifacts,
            dict(payload, options={"request_id": "request-1", "threshold": .5}), actor={"actor_id": "u"})
    assert caught.value.code == "SMART_AUDIT_REQUEST_CONFLICT"


def test_scope_limit_and_client_prediction_injection_are_rejected(tmp_path):
    from platform_core.smart_material_audit.service import estimate_audit, create_audit
    project, store, repository, artifacts = setup_project(tmp_path)
    enable(tmp_path, max_images=2)
    store.upsert(dict(id="three", filename="three.png"))
    with pytest.raises(BatchRequestError) as caught:
        estimate_audit(tmp_path, "p", {"scope": "FILTERED", "filters": {}})
    assert caught.value.code == "SMART_AUDIT_SCOPE_LIMIT"
    with pytest.raises(BatchRequestError, match="pred_boxes"):
        create_audit(tmp_path, "p", repository, artifacts,
            dict(selection_spec={"scope": "SELECTED", "image_ids": ["one"], "repository_revision": store.current_revision()},
                options={"request_id": "request-2", "pred_boxes": []}), actor={"actor_id": "u"})
