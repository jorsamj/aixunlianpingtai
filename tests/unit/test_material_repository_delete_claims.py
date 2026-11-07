from contextlib import closing
import sqlite3
import subprocess
import sys

import pytest

import platform_core.material_repository as module
from platform_core.material_repository_batch import _MATERIAL_INIT_READY
from platform_core.material_repository import MaterialRepository


def record(image_id, dataset="default", token=None):
    row = {"id": image_id, "filename": image_id + ".png", "object_key": "uploads/" + image_id + ".png",
           "dataset_id": dataset, "created_at": "2026-01-01T00:00:00", "width": 32, "height": 32}
    if token is not None:
        row["_dataset_delete_claim"] = token
    return row


def test_sparse_claim_query_never_decodes_unclaimed_rows_and_uses_actual_index(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([record(str(i)) for i in range(1000)] +
                           [record("claimed", "a", "orphan"), record("other", "b", "valid")])
    queries, decoded = [], []
    original_connect, original_payload = repository._connect, repository._row_payload
    def connect():
        db = original_connect()
        db.set_trace_callback(queries.append)
        return db
    def payload(row):
        value = original_payload(row)
        decoded.append(value["id"])
        return value
    monkeypatch.setattr(repository, "_connect", connect)
    monkeypatch.setattr(repository, "_row_payload", payload)
    assert [row["id"] for row in repository.list_dataset_delete_claims("a")] == ["claimed"]
    assert decoded == ["claimed"], "another dataset's deletion claims must not be decoded"
    query = next(query for query in queries if query.lstrip().upper().startswith("SELECT") and "FROM materials" in query)
    with closing(original_connect()) as db:
        plan = " ".join(str(row[3]) for row in db.execute("EXPLAIN QUERY PLAN " + query))
    assert "ix_materials_dataset_delete_claim" in plan
    assert "SEARCH materials USING INDEX ix_materials_dataset_delete_claim" in plan
    assert "SCAN materials" not in plan or "USING INDEX ix_materials_dataset_delete_claim" in plan


def test_orphan_clear_is_dataset_scoped_idempotent_and_preserves_valid_claims(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([record("stale", "a", "orphan"), record("active", "a", "valid"),
                           record("other", "b", "orphan"), record("plain", "a")])
    before = {key: repository.get(key) for key in ("stale", "active", "other", "plain")}
    revision = repository.current_revision()
    assert repository.clear_orphan_dataset_delete_claims("a", {"valid"}) == ["stale"]
    assert repository.get("stale") == {key: value for key, value in before["stale"].items() if key != "_dataset_delete_claim"}
    assert all(repository.get(key) == before[key] for key in ("active", "other", "plain"))
    assert repository.current_revision() == revision + 1
    assert repository.clear_orphan_dataset_delete_claims("a", {"valid"}) == []
    assert repository.current_revision() == revision + 1


def test_normal_claim_check_opens_no_writer_transaction(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)
    repository.upsert(record("plain"))
    queries, original = [], repository._connect
    def connect():
        db = original()
        db.set_trace_callback(queries.append)
        return db
    monkeypatch.setattr(repository, "_connect", connect)
    assert repository.clear_orphan_dataset_delete_claims("default", set()) == []
    assert not any(query.lstrip().upper().startswith(("BEGIN", "UPDATE", "DELETE", "INSERT")) for query in queries)


def test_default_dataset_legacy_identity_and_false_claim_semantics_are_preserved(tmp_path):
    repository = MaterialRepository(tmp_path)
    rows = [record("missing", token="orphan"), record("empty", "", "orphan"),
            record("false", None, False), record("zero", 0, "orphan")]
    rows[0].pop("dataset_id")
    repository.upsert_many(rows)
    assert set(repository.clear_orphan_dataset_delete_claims("default", set())) == {"missing", "empty", "zero"}
    assert repository.get("false")["_dataset_delete_claim"] is False


def test_orphan_clear_rechecks_latest_claim_inside_writer_transaction(tmp_path, monkeypatch):
    repository, concurrent = MaterialRepository(tmp_path), MaterialRepository(tmp_path)
    repository.upsert(record("image", "a", "orphan"))
    original = repository.list_dataset_delete_claims
    def changed(*args, **kwargs):
        snapshot = original(*args, **kwargs)
        concurrent.patch({"image": {"_dataset_delete_claim": "new-active", "filename": "updated.png"}})
        return snapshot
    monkeypatch.setattr(repository, "list_dataset_delete_claims", changed)
    assert repository.clear_orphan_dataset_delete_claims("a", {"new-active"}) == []
    assert repository.get("image")["_dataset_delete_claim"] == "new-active"
    assert repository.get("image")["filename"] == "updated.png"


def test_orphan_clear_rolls_back_all_rows_and_revision_on_failure(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([record("a", token="orphan"), record("b", token="orphan")])
    before = {key: repository.get(key) for key in ("a", "b")}
    revision, original = repository.current_revision(), repository._write_row
    calls = 0
    def fail_second(*args):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("isolated transaction failure")
        return original(*args)
    monkeypatch.setattr(repository, "_write_row", fail_second)
    with pytest.raises(OSError, match="isolated transaction failure"):
        repository.clear_orphan_dataset_delete_claims("default", set())
    assert all(repository.get(key) == before[key] for key in before)
    assert repository.current_revision() == revision


def test_old_schema_index_upgrade_is_restartable_and_does_not_rewrite_payloads(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([record("old"), record("orphan", token="orphan")])
    with closing(sqlite3.connect(repository.path)) as db:
        before = db.execute("SELECT id,payload_json FROM materials ORDER BY id").fetchall()
        db.execute("DROP INDEX IF EXISTS ix_materials_dataset_delete_claim")
        db.execute("PRAGMA user_version=5")
        db.commit()
    # Simulate a deployment/restart rather than a live database downgrade:
    # the existing batch owner caches successful initialization per process.
    _MATERIAL_INIT_READY.discard(repository.path.resolve())
    schema = module._SCHEMA
    with monkeypatch.context() as scoped:
        scoped.setattr(module, "_SCHEMA", schema + "\nINVALID INTERRUPTION;")
        with pytest.raises(sqlite3.OperationalError):
            MaterialRepository(tmp_path)
    reopened = MaterialRepository(tmp_path)
    assert [row["id"] for row in reopened.list_dataset_delete_claims()] == ["orphan"]
    with closing(reopened._connect()) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == module._SCHEMA_VERSION
        assert [tuple(row) for row in db.execute("SELECT id,payload_json FROM materials ORDER BY id")] == before
    class ForbiddenLock:
        def __init__(self, *args, **kwargs):
            raise AssertionError("ready schema must not repeat index initialization")
    monkeypatch.setattr(module, "FileLock", ForbiddenLock)
    _MATERIAL_INIT_READY.discard(repository.path.resolve())
    assert MaterialRepository(tmp_path).get("old") == reopened.get("old")


def test_claim_written_in_another_process_is_visible_without_cache(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert(record("image"))
    code = ("import sys; from platform_core.material_repository import MaterialRepository; "
            "MaterialRepository(sys.argv[1]).patch({'image': {'_dataset_delete_claim': 'child-orphan'}})")
    subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=True, capture_output=True, timeout=30)
    assert repository.clear_orphan_dataset_delete_claims("default", set()) == ["image"]
    assert "_dataset_delete_claim" not in repository.get("image")


@pytest.mark.parametrize("schema", [5, 6, 99])
def test_readonly_lifecycle_readers_accept_known_schemas_without_upgrade(tmp_path, monkeypatch, schema):
    from tests.unit.test_local_material_reclamation import setup_gc
    from platform_core.legacy_material_compatibility import LegacyMaterialCompatibilityService
    from platform_core.storage.lifecycle_summary import storage_lifecycle_summary
    service, repository, original, _ = setup_gc(tmp_path, monkeypatch)
    with closing(sqlite3.connect(repository.path)) as db:
        db.execute(f"PRAGMA user_version={schema}")
    compatibility = LegacyMaterialCompatibilityService(service.data_dir, "p")
    if schema == 99:
        with pytest.raises(ValueError, match="unsupported material schema"):
            compatibility._rows()
    else:
        assert compatibility._rows()[0] == []
    size = storage_lifecycle_summary(service.data_dir, "p")["metrics"]["original_index_logical_bytes"]["value"]
    assert size == (None if schema == 99 else 0)
    preview = service.preview("p", "retire", "a")
    assert ("UNKNOWN_PROJECT_INDEX" in preview["blockers"]) is (schema == 99)
    assert original.exists()
    with closing(sqlite3.connect(repository.path)) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == schema
