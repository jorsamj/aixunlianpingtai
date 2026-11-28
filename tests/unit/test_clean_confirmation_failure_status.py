"""A failed delete must never turn a bad image into 'processed'."""
import sqlite3
from contextlib import closing
from platform_core.cleaning_management_service import CleaningManagementService
from platform_core.task_runtime import TaskKind
from fastapi import HTTPException

from types import SimpleNamespace

import pytest

import app


@pytest.mark.parametrize("deleted,failed,remaining", [
    (["delete-ok"], ["delete-error"], ["keep", "delete-error"]),
    ([], ["delete-ok", "delete-error"], ["keep", "delete-ok", "delete-error"]),
])
def test_clean_confirm_does_not_mark_failed_deletions_processed(
    monkeypatch, deleted, failed, remaining,
):
    task_id = "clean-confirm-partial"
    written = {}
    patches = []

    class FakeMaterials:
        def get_many(self, image_ids):
            return [{"id": image_id} for image_id in image_ids if image_id in remaining]

        def patch_many(self, image_ids, patch, **kwargs):
            patches.append((list(image_ids), dict(patch)))

    monkeypatch.setattr(app, "_v33_get_task", lambda *_: {"id": task_id, "status": "done"})
    monkeypatch.setattr(CleaningManagementService, "_v47_validate_clean_confirmation", staticmethod(lambda *_: {"keep", "delete-ok", "delete-error"}))
    monkeypatch.setattr(CleaningManagementService, "_v47_frozen_clean_selection_ids", staticmethod(lambda *_: ["keep", "delete-ok", "delete-error"]))
    monkeypatch.setattr(app, "material_store", lambda *_: FakeMaterials())
    monkeypatch.setattr(app, "v46_batch_delete_images", lambda *_args, **_kwargs: {
        "ok": not failed,
        "deleted": len(deleted),
        "deleted_images": [{"id": image_id} for image_id in deleted],
        "failed_items": [{"id": image_id, "errors": ["delete failed"]} for image_id in failed],
    })
    monkeypatch.setattr(
        app, "shared_task_artifacts",
        lambda: SimpleNamespace(atomic_write_json=lambda task, name, payload: written.update(payload)),
    )

    # Legacy synchronous deletion was retired before this workbench change.
    # It must refuse before any mocked deletion, material patch or receipt write.
    with pytest.raises(HTTPException) as failure:
        app.v47_confirm_clean(
            "project-1", task_id,
            app.V47CleanConfirmReq(delete_ids=["delete-ok", "delete-error"]),
        )
    assert failure.value.status_code == 409
    assert failure.value.detail["code"] == "MATERIAL_DELETE_PREVIEW_REQUIRED"
    assert patches == []
    assert written == {}


def test_clean_link_checks_exact_registered_delete_manifest_membership(tmp_path):
    manifest = tmp_path / 'selection.sqlite3'
    digest = 'a' * 64
    with closing(sqlite3.connect(manifest)) as database, database:
        database.executescript('CREATE TABLE selection(image_id TEXT); '
                               'CREATE TABLE integrity_plan_items(image_id TEXT,content_sha256 TEXT);')
        database.execute('INSERT INTO selection VALUES (?)', ('selected-image',))
        database.execute('INSERT INTO integrity_plan_items VALUES (?, ?)', ('selected-image', digest))
    artifacts = SimpleNamespace(artifact_path=lambda *_: manifest, read_json=lambda *_args, **_kw: {
        'operation': 'DELETE_INDEX', 'options': {'material_integrity_plan_id': 'plan'},
    })
    repository = SimpleNamespace(get=lambda _id: SimpleNamespace(
        kind=TaskKind.MATERIAL_BATCH, project_id='p', payload_ref='request.json',
    ))
    service = CleaningManagementService(SimpleNamespace(
        shared_task_artifacts=lambda: artifacts, shared_task_repository=lambda: repository,
    ))
    assert service._linked_deletion_hashes('p', 'plan', {'selected-image'}) == {'selected-image': digest}
    with pytest.raises(HTTPException, match='排除项与原删除冻结范围'):
        service._linked_deletion_hashes('p', 'plan', {'other-image'})
