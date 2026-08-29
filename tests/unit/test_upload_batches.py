import json
import threading

import pytest

from platform_core.upload_batches import (
    UploadBatchStore,
    apply_decisions,
    create_upload_batch,
)


def test_create_upload_batch_persists_ordered_pending_items(tmp_path):
    batch = create_upload_batch(
        tmp_path,
        "batch-1",
        ["image-b", "image-a"],
        "2026-08-29T10:00:00",
    )

    assert batch == {
        "id": "batch-1",
        "created_at": "2026-08-29T10:00:00",
        "items": [
            {"image_id": "image-b", "decision": "pending"},
            {"image_id": "image-a", "decision": "pending"},
        ],
    }
    assert json.loads((tmp_path / "batch-1.json").read_text(encoding="utf-8")) == batch


def test_apply_decisions_preserves_order_and_unspecified_decisions():
    original = {
        "id": "batch-1",
        "created_at": "now",
        "items": [
            {"image_id": "one", "decision": "pending"},
            {"image_id": "two", "decision": "ready"},
            {"image_id": "three", "decision": "pending"},
        ],
    }

    updated = apply_decisions(original, {"one"}, set())

    assert [item["image_id"] for item in updated["items"]] == ["one", "two", "three"]
    assert [item["decision"] for item in updated["items"]] == ["clean", "ready", "pending"]
    assert original["items"][0]["decision"] == "pending"


def test_apply_decisions_rejects_overlap_and_non_member_ids():
    batch = {
        "id": "batch-1",
        "created_at": "now",
        "items": [{"image_id": "one", "decision": "pending"}],
    }

    with pytest.raises(ValueError, match="同时选择"):
        apply_decisions(batch, {"one"}, {"one"})
    with pytest.raises(ValueError, match="不属于"):
        apply_decisions(batch, {"other"}, set())


@pytest.mark.parametrize("batch_id", ["", "../batch", "batch/name", "batch\\name", ".hidden"])
def test_store_rejects_path_unsafe_batch_ids(tmp_path, batch_id):
    store = UploadBatchStore(tmp_path)

    with pytest.raises(ValueError, match="批次"):
        store.read(batch_id)


def test_store_rejects_invalid_json_shape(tmp_path):
    (tmp_path / "bad.json").write_text(
        json.dumps({"id": "bad", "created_at": "now", "items": "wrong"}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="items"):
        UploadBatchStore(tmp_path).read("bad")


def test_store_serializes_concurrent_decisions_without_lost_updates(tmp_path):
    store = UploadBatchStore(tmp_path)
    store.create("batch", ["one", "two"], "now")
    barrier = threading.Barrier(2)
    errors = []

    def decide(clean_ids, ready_ids):
        try:
            barrier.wait(timeout=5)
            store.update_decisions("batch", clean_ids, ready_ids)
        except Exception as error:  # pragma: no cover - assertion reports worker error
            errors.append(error)

    first = threading.Thread(target=decide, args=({"one"}, set()))
    second = threading.Thread(target=decide, args=(set(), {"two"}))
    first.start()
    second.start()
    first.join(5)
    second.join(5)

    assert not errors
    assert not first.is_alive()
    assert not second.is_alive()
    assert [item["decision"] for item in store.read("batch")["items"]] == [
        "clean",
        "ready",
    ]
