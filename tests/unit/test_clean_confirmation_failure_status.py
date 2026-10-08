"""A failed delete must never turn a bad image into 'processed'."""

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
    monkeypatch.setattr(app, "_v47_validate_clean_confirmation", lambda *_: {"keep", "delete-ok", "delete-error"})
    monkeypatch.setattr(app, "_v47_frozen_clean_selection_ids", lambda *_: ["keep", "delete-ok", "delete-error"])
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

    result = app.v47_confirm_clean(
        "project-1", task_id,
        app.V47CleanConfirmReq(delete_ids=["delete-ok", "delete-error"]),
    )

    assert result["ok"] is False
    assert result["processed_ids"] == ["keep"]
    assert len(patches) == 1
    assert patches[0][0] == ["keep"]
    assert patches[0][1]["processing_status"] == "processed"
    assert written["delete_failures"] == len(failed)
    assert written["processed_ids"] == ["keep"]
