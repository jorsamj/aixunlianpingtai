import threading

from platform_core.material_store import MaterialStore


def test_annotation_patch_cannot_overwrite_concurrent_upload(tmp_path):
    store = MaterialStore(tmp_path / "images.json")
    store.upsert({"id": "old", "filename": "old.jpg"})
    stale = store.read().rows
    gate = threading.Barrier(2)

    def background_index():
        gate.wait()
        store.patch({"old": {"annotation_summary_at": "indexed", "box_count": 0}})

    thread = threading.Thread(target=background_index)
    thread.start()
    gate.wait()
    store.upsert({"id": "new", "filename": "new.jpg"})
    thread.join()

    assert [row["id"] for row in store.read().rows] == ["old", "new"]
    assert stale == [{"id": "old", "filename": "old.jpg"}]
    assert store.read().revision >= 3
