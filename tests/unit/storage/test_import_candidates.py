from __future__ import annotations

import sqlite3
import uuid
from concurrent.futures import ThreadPoolExecutor

import pytest

from platform_core.storage.import_candidates import ImportCandidateStore, normalize_candidate


def candidate(key, **values):
    return {"object_key": key, "status": "IMPORTABLE", **values}


@pytest.fixture
def store(tmp_path):
    return ImportCandidateStore(tmp_path / "artifacts" / "candidates.sqlite3")


def test_upsert_is_idempotent_and_status_iteration_is_ordered(store):
    assert store.upsert_many(candidate(key) for key in ["b.jpg", "a.jpg"]) == 2
    assert store.upsert_many([candidate("b.jpg", status="FAILED")]) == 0
    assert store.counts() == {"IMPORTABLE": 2}
    assert [r["object_key"] for r in store.iter_status("IMPORTABLE", batch_size=1)] == ["a.jpg", "b.jpg"]
    assert list(store.iter_status("FAILED")) == []


def test_failed_candidates_have_bounded_pages_and_persisted_errors(store):
    store.upsert_many(candidate(f"{i:04}.jpg", status="FAILED", error="unreadable image") for i in range(601))
    assert len(store.failure_page(limit=100000)) == 500
    assert len(store.failure_page(limit=0)) == 1
    assert len(store.failure_page()) == 200
    reopened = ImportCandidateStore(store.path)
    assert reopened.failure_page(limit=1)[0]["error"] == "unreadable image"


def test_confirmation_is_order_independent_immutable_and_recoverable(store):
    store.upsert_many(candidate(key) for key in ["a", "b", "c"])
    first = store.confirm(iter(["b", "a", "a"]))
    assert first.selected_count == 2
    assert len(first.digest) == 64
    assert first.confirmed_at
    assert store.confirm(["a", "b"]) == first
    assert ImportCandidateStore(store.path).confirm(["b", "a"]) == first
    with pytest.raises(ValueError, match="conflicting"):
        store.confirm(["c"])
    assert [r["object_key"] for r in store.pending_index_batch(20)] == ["a", "b"]


@pytest.mark.parametrize("selection", [["missing"], ["good", "bad"]])
def test_unknown_or_nonimportable_selection_rolls_back(store, selection):
    store.upsert_many([candidate("good"), candidate("bad", status="FAILED")])
    with pytest.raises(ValueError, match="unknown|IMPORTABLE"):
        store.confirm(selection)
    assert store.pending_index_batch(10) == []
    assert store.confirm(["good"]).selected_count == 1


def test_empty_selection_is_a_valid_immutable_confirmation(store):
    store.upsert_many([candidate("a")])
    first = store.confirm([])
    assert first.selected_count == 0
    assert store.confirm(iter([])) == first
    with pytest.raises(ValueError, match="conflicting"):
        store.confirm(["a"])


def test_confirmation_digest_has_unambiguous_key_boundaries(tmp_path):
    first = ImportCandidateStore(tmp_path / "one.db")
    second = ImportCandidateStore(tmp_path / "two.db")
    for item in [first, second]:
        item.upsert_many(candidate(k) for k in ["a", "bc", "ab", "c"])
    assert first.confirm(["a", "bc"]).digest != second.confirm(["ab", "c"]).digest


def test_assignment_is_deterministic_batched_and_persists_across_reopen(store, tmp_path):
    store.upsert_many(candidate(key) for key in ["c", "a", "b"])
    store.confirm(["b", "a"])
    assert store.assign_image_ids("task-1", batch_size=1) == 2
    first = store.pending_index_batch(limit=1)[0]
    assert first["object_key"] == "a"
    assert uuid.UUID(first["image_id"]).version == 5
    reopened = ImportCandidateStore(store.path)
    assert reopened.assign_image_ids("task-1", batch_size=1) == 0
    assert reopened.pending_index_batch(1)[0]["image_id"] == first["image_id"]
    copy = ImportCandidateStore(tmp_path / "copy.db")
    copy.upsert_many([candidate("a")])
    copy.confirm(["a"])
    copy.assign_image_ids("task-1", 1)
    assert copy.pending_index_batch(1)[0]["image_id"] == first["image_id"]
    assert next(r for r in store.iter_status("IMPORTABLE") if r["object_key"] == "c")["image_id"] is None


def test_mark_indexed_is_idempotent_preserves_image_id_and_time(store):
    store.upsert_many([candidate("a"), candidate("b")])
    store.confirm(["a", "b"])
    store.assign_image_ids("task", 1)
    original = store.pending_index_batch(1)[0]["image_id"]
    assert store.mark_indexed([{"object_key": "a", "image_id": "must-not-replace"}]) == 1
    indexed = next(store.iter_status("IMPORTABLE"))
    assert indexed["indexed"] == 1
    assert indexed["image_id"] == original
    assert indexed["indexed_at"]
    assert store.mark_indexed([{"object_key": "a"}]) == 0
    assert next(ImportCandidateStore(store.path).iter_status("IMPORTABLE"))["indexed_at"] == indexed["indexed_at"]
    assert [r["object_key"] for r in store.pending_index_batch(100)] == ["b"]
    assert store.assign_image_ids("different-task", 1) == 0


@pytest.mark.parametrize("invalid", ["missing", "unselected", "unassigned"])
def test_mark_indexed_rolls_back_invalid_batches(store, invalid):
    store.upsert_many(candidate(k) for k in ["a", "unselected", "unassigned"])
    store.confirm(["a", "unassigned"])
    store.assign_image_ids("task", 1)
    # Simulate recovery of an interrupted assignment batch.
    with sqlite3.connect(store.path) as connection:
        connection.execute("UPDATE candidates SET image_id=NULL WHERE object_key='unassigned'")
    with pytest.raises(ValueError):
        store.mark_indexed([{"object_key": "a"}, {"object_key": invalid}])
    assert next(store.iter_status("IMPORTABLE"))["indexed"] == 0


def test_hash_lookup_chunks_parameters_and_normalizes_inputs(store, monkeypatch):
    hashes = [f"{i:064x}" for i in range(1207)]
    store.upsert_many(candidate(str(i), content_sha256=h) for i, h in enumerate(hashes))
    original_connect = store._connect
    parameter_counts = []

    class ParameterBoundedConnection:
        def __init__(self, connection):
            self.connection = connection

        def execute(self, sql, parameters=()):
            if " IN (" in sql.upper():
                count = sql.count("?")
                assert count <= 500
                assert len(parameters) <= 500
                parameter_counts.append(count)
            return self.connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self.connection, name)

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

    monkeypatch.setattr(store, "_connect", lambda: ParameterBoundedConnection(original_connect()))
    assert store.find_content_hashes(iter([None, "", " ", *[h.upper() for h in hashes], hashes[0], "absent"])) == set(hashes)
    assert len(parameter_counts) >= 3
    assert max(parameter_counts) == 500


def test_normalization_is_scalar_and_whitelisted_and_does_not_leak_secrets(store):
    raw = candidate(42, filename=17, size_bytes="12", width="3", height="bad", duplicate="false",
                    storage_type="S3", content_sha256=" ABC ", etag={"token": "nested-secret"},
                    access_key="access-value", secret="secret-value", token="token-value",
                    config={"root": "C:\\private\\images"}, local_root="C:\\private\\images",
                    error="access_key=access-value secret=secret-value token=token-value at C:\\private\\images\\a.jpg")
    normalized = normalize_candidate(raw)
    assert normalized["object_key"] == "42"
    assert normalized["filename"] == "17"
    assert normalized["size_bytes"] == 12
    assert normalized["width"] == 3
    assert normalized["height"] == 0
    assert normalized["duplicate"] == 0
    assert normalized["storage_type"] == "s3"
    assert normalized["content_sha256"] == "abc"
    assert normalized["etag"] == ""
    assert not {"access_key", "secret", "token", "config", "local_root"} & normalized.keys()
    store.upsert_many([raw])
    with sqlite3.connect(store.path) as connection:
        persisted = " ".join(connection.iterdump())
    for text in [str(normalized), persisted, str(list(store.iter_status("IMPORTABLE")))]:
        for sensitive in ["access-value", "secret-value", "token-value", "nested-secret", "C:\\private\\images"]:
            assert sensitive not in text


@pytest.mark.parametrize("field", [
    "access_key", "Access-Key-ID", "ACCESS_KEY_SECRET", "secret", "secret-key",
    "Api_Key", "TOKEN", "Password", "secret_access_key",
    "security_token", "session_token", "access_token", "bearer_token",
    "aws_access_key_id", "aws_secret_access_key", "client_secret", "aws_session_token",
    "X-API-Key", "AWS-SESSION-TOKEN", "Client-Secret",
])
@pytest.mark.parametrize("style", ["json", "python", "assignment", "quoted_assignment"])
def test_error_credentials_are_redacted_before_persistence(store, field, style):
    secret = "private-credential-value"
    if style == "json":
        diagnostic = '{"' + field + '":"' + secret + ' with spaces","detail":"image decoding failed"}'
    elif style == "python":
        diagnostic = "{'" + field + "': '" + secret + " with spaces', 'detail': 'image decoding failed'}"
    elif style == "quoted_assignment":
        diagnostic = field + '="' + secret + ' with spaces"; image decoding failed'
    else:
        diagnostic = field + "=" + secret + "; image decoding failed"
    raw = candidate("a.jpg", status="FAILED", error=diagnostic)
    normalized = normalize_candidate(raw)
    assert secret not in normalized["error"]
    assert "with spaces" not in normalized["error"]
    assert field in normalized["error"]
    assert "[REDACTED]" in normalized["error"]
    assert "image decoding failed" in normalized["error"]
    store.upsert_many([raw])
    assert store.failure_page(1)[0]["error"] == normalized["error"]
    with sqlite3.connect(store.path) as connection:
        assert secret not in " ".join(connection.iterdump())
    for artifact in store.path.parent.glob(store.path.name + "*"):
        assert secret.encode() not in artifact.read_bytes()


def test_normal_error_text_is_preserved():
    error = "image decoding failed: expected size=100 bytes; endpoint=https://storage.example.invalid; bucket=images"
    assert normalize_candidate(candidate("a.jpg", error=error))["error"] == error


@pytest.mark.parametrize("diagnostic,path", [
    ("cannot read path:/private/images/a.jpg", "/private/images/a.jpg"),
    ("cannot read path:C:/private/images/a.jpg", "C:/private/images/a.jpg"),
    ("cannot read root:/private/images", "/private/images"),
])
def test_colon_prefixed_absolute_paths_are_redacted_before_storage(store, diagnostic, path):
    raw = candidate("a.jpg", status="FAILED", error=diagnostic)
    normalized = normalize_candidate(raw)
    assert path not in normalized["error"]
    assert "[REDACTED PATH]" in normalized["error"]
    assert "cannot read" in normalized["error"]
    store.upsert_many([raw])
    assert store.failure_page(1)[0]["error"] == normalized["error"]
    with sqlite3.connect(store.path) as connection:
        assert path not in " ".join(connection.iterdump())
    for artifact in store.path.parent.glob(store.path.name + "*"):
        assert path.encode() not in artifact.read_bytes()


@pytest.mark.parametrize("endpoint", [
    "http://storage.example.invalid:9000/images/check?limit=12&recursive=true",
    "https://storage.example.invalid:443/images/check?limit=12&recursive=true",
])
def test_http_endpoints_survive_path_redaction_without_placeholder_collisions(store, endpoint):
    error = f"endpoint={endpoint} __URL_0__ [URL:0] cannot read path:/private/images/a.jpg"
    expected = f"endpoint={endpoint} __URL_0__ [URL:0] cannot read path:[REDACTED PATH]"
    raw = candidate("a.jpg", status="FAILED", error=error)
    assert normalize_candidate(raw)["error"] == expected
    store.upsert_many([raw])
    assert store.failure_page(1)[0]["error"] == expected


@pytest.mark.parametrize("absolute", [
    "/private/images/a.jpg", "C:/private/images/a.jpg", "C:\\private\\images\\a.jpg",
    "\\\\server\\share\\a.jpg", "//server/share/a.jpg",
])
@pytest.mark.parametrize("field", ["object_key", "filename"])
def test_local_absolute_paths_are_rejected_without_persisting(store, field, absolute):
    raw = candidate("safe/a.jpg", storage_type=" LOCAL ")
    raw[field] = absolute
    with pytest.raises(ValueError, match=field):
        normalize_candidate(raw)
    with pytest.raises(ValueError, match=field):
        store.upsert_many([raw])
    assert store.counts() == {}
    with sqlite3.connect(store.path) as connection:
        assert absolute not in " ".join(connection.iterdump())
    for artifact in store.path.parent.glob(store.path.name + "*"):
        assert absolute.encode() not in artifact.read_bytes()


@pytest.mark.parametrize("key", ["folder/a.jpg", "目录/图像.jpg", "folder\\a.jpg", "space name/a.jpg"])
def test_relative_local_paths_remain_valid(key):
    assert normalize_candidate(candidate(key, storage_type="local"))["object_key"] == key


@pytest.mark.parametrize("key", ["/prefix/a.jpg", "C:/prefix/a.jpg", "//prefix/a.jpg"])
def test_s3_object_keys_are_not_treated_as_local_absolute_paths(key):
    assert normalize_candidate(candidate(key, storage_type="s3"))["object_key"] == key


@pytest.mark.parametrize("key", [None, "", "  ", {}, []])
def test_empty_or_nonscalar_keys_are_rejected(key):
    with pytest.raises(ValueError, match="object_key"):
        normalize_candidate(candidate(key))


@pytest.mark.parametrize("key", ["folder/a.jpg", "目录/图像.jpg", "folder\\a.jpg", "space name/file.jpg"])
def test_relative_provider_keys_are_preserved(key):
    assert normalize_candidate(candidate(key))["object_key"] == key


def test_concurrent_confirmations_only_accept_one_selection(store):
    store.upsert_many([candidate("a"), candidate("b")])

    def confirm(key):
        try:
            return ImportCandidateStore(store.path).confirm([key])
        except ValueError as error:
            assert "conflicting" in str(error)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(confirm, ["a", "b"]))
    assert sum(result is not None for result in results) == 1
    assert len(store.pending_index_batch(10)) == 1


def test_large_iteration_and_pending_batches_have_hard_limits(store):
    store.upsert_many(candidate(f"{i:05}") for i in range(6001))
    rows = store.iter_status("IMPORTABLE", batch_size=0)
    assert next(rows)["object_key"] == "00000"
    assert next(rows)["object_key"] == "00001"
    rows.close()
    assert sum(1 for _ in store.iter_status("IMPORTABLE", batch_size=1000000)) == 6001
    store.confirm((f"{i:05}" for i in range(6001)))
    assert len(store.pending_index_batch(1000000)) == 5000
    assert len(store.pending_index_batch(0)) == 1


def test_upsert_rollback_on_bad_input_and_connection_settings(store):
    with pytest.raises(ValueError, match="object_key"):
        store.upsert_many([candidate("valid"), candidate("")])
    assert store.counts() == {}
    connection = store._connect()
    try:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 30000
        assert connection.row_factory is sqlite3.Row
    finally:
        connection.close()
