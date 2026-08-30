import threading
import json

import platform_core.material_store as material_store_module

from platform_core.material_store import MaterialStore


def test_annotation_patch_cannot_overwrite_concurrent_upload(tmp_path):
    path = tmp_path / "images.json"
    store = MaterialStore(path)
    store.upsert({"id": "old", "filename": "old.jpg"})
    stale = store.read().rows
    mutation_started = threading.Event()
    release_mutation = threading.Event()
    upload_started = threading.Event()
    upload_finished = threading.Event()

    def background_index():
        def apply(rows):
            mutation_started.set()
            assert release_mutation.wait(timeout=1)
            rows[0].update({"annotation_summary_at": "indexed", "box_count": 0})

        store.mutate(apply)

    def upload():
        upload_started.set()
        MaterialStore(path).upsert({"id": "new", "filename": "new.jpg"})
        upload_finished.set()

    index_thread = threading.Thread(target=background_index)
    index_thread.start()
    assert mutation_started.wait(timeout=1)
    upload_thread = threading.Thread(target=upload)
    upload_thread.start()
    assert upload_started.wait(timeout=1)
    assert not upload_finished.wait(timeout=0.05)
    release_mutation.set()
    index_thread.join(timeout=1)
    upload_thread.join(timeout=1)

    assert [row["id"] for row in store.read().rows] == ["old", "new"]
    assert stale == [{"id": "old", "filename": "old.jpg"}]
    assert store.read().rows[0]["annotation_summary_at"] == "indexed"
    assert store.read().revision >= 3


def test_upsert_normalizes_numeric_and_string_ids(tmp_path):
    store = MaterialStore(tmp_path / "images.json")
    store.upsert({"id": 1, "filename": "old.jpg", "source": "upload"})

    stored = store.upsert({"id": "1", "filename": "new.jpg"})

    assert stored == {"id": "1", "filename": "new.jpg", "source": "upload"}
    assert store.read().rows == [stored]


def test_patch_accepts_integer_id_keys(tmp_path):
    store = MaterialStore(tmp_path / "images.json")
    store.upsert({"id": "1", "filename": "old.jpg"})

    changed = store.patch({1: {"box_count": 0}})

    assert changed == [{"id": "1", "filename": "old.jpg", "box_count": 0}]


def test_remove_accepts_a_non_set_iterable(tmp_path):
    store = MaterialStore(tmp_path / "images.json")
    store.upsert({"id": "1", "filename": "one.jpg"})
    store.upsert({"id": "2", "filename": "two.jpg"})

    removed = store.remove(["1"])

    assert removed == [{"id": "1", "filename": "one.jpg"}]
    assert store.read().rows == [{"id": "2", "filename": "two.jpg"}]


def test_read_reuses_index_until_images_file_changes(tmp_path, monkeypatch):
    path = tmp_path / "images.json"
    path.write_text(json.dumps([{"id": "one", "filename": "one.jpg"}]), encoding="utf-8")
    store = MaterialStore(path)
    original = material_store_module.read_rows
    calls = 0

    def counted_read_rows(value):
        nonlocal calls
        calls += 1
        return original(value)

    monkeypatch.setattr(material_store_module, "read_rows", counted_read_rows)

    assert store.read().rows == [{"id": "one", "filename": "one.jpg"}]
    assert store.read().rows == [{"id": "one", "filename": "one.jpg"}]
    assert calls == 1

    path.write_text(json.dumps([{"id": "two", "filename": "two.jpg"}]), encoding="utf-8")

    assert store.read().rows == [{"id": "two", "filename": "two.jpg"}]
    assert calls == 2


def test_count_tracks_cached_and_external_rows(tmp_path):
    path = tmp_path / "images.json"
    path.write_text(json.dumps([{"id": "one"}]), encoding="utf-8")
    store = MaterialStore(path)

    assert store.count() == 1

    path.write_text(json.dumps([{"id": "one"}, {"id": "two"}]), encoding="utf-8")

    assert store.count() == 2
