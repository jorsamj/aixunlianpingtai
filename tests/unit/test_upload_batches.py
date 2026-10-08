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


def test_upload_request_receipt_is_idempotent_and_manifest_fenced(tmp_path):
    store = UploadBatchStore(tmp_path)
    manifest = [{"name": "a.jpg", "size": 12, "content_type": "image/jpeg"}]
    first, created = store.begin_upload_request(
        "upload-request-001", created_at="2026-09-28T10:00:00Z", manifest=manifest,
        dataset_id="default", storage_source_id="default_local",
    )
    assert created is True
    assert first["upload_request_status"] == "PROCESSING"
    repeated, created = store.begin_upload_request(
        "upload-request-001", created_at="2026-09-28T10:00:01Z", manifest=manifest,
        dataset_id="default", storage_source_id="default_local",
    )
    assert created is False
    assert repeated["upload_request_status"] == "PROCESSING"
    with pytest.raises(ValueError, match="已用于不同文件"):
        store.begin_upload_request(
            "upload-request-001", created_at="2026-09-28T10:00:02Z",
            manifest=[{"name": "different.jpg", "size": 99, "content_type": "image/jpeg"}],
            dataset_id="default", storage_source_id="default_local",
        )


def test_upload_request_receipt_persists_terminal_replay_truth(tmp_path):
    store = UploadBatchStore(tmp_path)
    store.begin_upload_request(
        "upload-request-002", created_at="2026-09-28T10:00:00Z",
        manifest=[{"name": "a.jpg", "size": 12, "content_type": "image/jpeg"}],
        dataset_id="default", storage_source_id="default_local",
    )
    completed = store.complete_upload_request(
        "upload-request-002", ["image-a"], failed=[{"name": "bad.txt", "reason": "unsupported"}],
        finished_at="2026-09-28T10:00:03Z", elapsed_seconds=3.2, material_total=8,
    )
    assert completed["upload_request_status"] == "SUCCEEDED"
    assert completed["items"] == [{"image_id": "image-a", "decision": "pending"}]
    assert completed["upload_failed"] == [{"name": "bad.txt", "reason": "unsupported"}]
    assert completed["upload_material_total"] == 8
    repeated = store.complete_upload_request(
        "upload-request-002", ["should-not-replace"], failed=[],
        finished_at="2026-09-28T10:00:04Z", elapsed_seconds=4, material_total=9,
    )
    assert repeated["items"] == [{"image_id": "image-a", "decision": "pending"}]


def test_prepared_upload_ids_are_immutable_across_receipt_completion(tmp_path):
    store = UploadBatchStore(tmp_path)
    store.begin_upload_request(
        "prepared-1", created_at="2026-10-08T00:00:00Z",
        manifest=[{"name": "a.jpg", "size": 12, "content_type": "image/jpeg"}],
        dataset_id="default", storage_source_id="default_local",
    )
    prepared = store.prepare_upload_request(
        "prepared-1", ["image-one"], failed=[],
        prepared_at="2026-10-08T00:00:01Z",
    )
    assert prepared["upload_prepared_image_ids"] == ["image-one"]
    with pytest.raises(ValueError, match="已经准备"):
        store.prepare_upload_request(
            "prepared-1", ["image-two"], failed=[],
            prepared_at="2026-10-08T00:00:02Z",
        )
    with pytest.raises(ValueError, match="不一致"):
        store.complete_upload_request(
            "prepared-1", ["image-two"], failed=[],
            finished_at="2026-10-08T00:00:03Z",
            elapsed_seconds=1.0, material_total=1,
        )
    assert store.read("prepared-1")["upload_request_status"] == "PROCESSING"
    completed = store.complete_upload_request(
        "prepared-1", ["image-one"], failed=[],
        finished_at="2026-10-08T00:00:04Z",
        elapsed_seconds=1.0, material_total=1,
    )
    assert completed["upload_request_status"] == "SUCCEEDED"
    assert completed["items"][0]["image_id"] == "image-one"


def test_upload_receipt_initializes_missing_directory_before_lock(tmp_path):
    directory = tmp_path / "new-project" / "upload_batches"
    assert not directory.exists()
    store = UploadBatchStore(directory)
    assert directory.is_dir()
    receipt, created = store.begin_upload_request(
        "first-upload", created_at="2026-10-08T12:00:00Z",
        manifest=[{"name": "first.jpg", "size": 1, "content_type": "image/jpeg"}],
        dataset_id="default", storage_source_id="default_local",
    )
    assert created is True
    assert receipt["upload_request_status"] == "PROCESSING"
    assert (directory / "first-upload.json").is_file()
