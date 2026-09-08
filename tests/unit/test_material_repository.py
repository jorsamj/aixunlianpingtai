from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor

from platform_core.material_repository import MaterialRepository


def material(image_id: str, *, source: str = "default_local", labels=(), status="processed"):
    return {
        "id": image_id,
        "filename": f"{image_id}.jpg",
        "stored_name": f"{image_id}.jpg",
        "storage_source_id": source,
        "storage_type": "local" if source == "default_local" else "s3",
        "object_key": f"uploads/{image_id}.jpg" if source == "default_local" else f"materials/{image_id}.jpg",
        "width": 640,
        "height": 480,
        "processing_status": status,
        "labels": list(labels),
        "box_count": len(labels),
        "created_at": f"2026-09-07T00:00:{int(image_id[-1], 16):02d}+00:00",
    }


def test_crud_and_revision_use_sqlite_rows(tmp_path):
    repository = MaterialRepository(tmp_path)
    assert repository.journal_mode() == "wal"
    assert repository.read().rows == []

    first = repository.upsert(material("image-1", labels=("fire",)))
    assert first["id"] == "image-1"
    before = repository.read().revision
    repository.patch({"image-1": {"processing_status": "cleaning", "labels": ["fire", "smoke"]}})
    assert repository.get("image-1")["processing_status"] == "cleaning"
    assert repository.get("image-1")["labels"] == ["fire", "smoke"]
    assert repository.read().revision > before

    removed = repository.remove(["image-1"])
    assert [row["id"] for row in removed] == ["image-1"]
    assert repository.count() == 0


def test_paginated_filters_and_multi_label_or(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([
        material("image-1", source="default_local", labels=("fire",)),
        material("image-2", source="oss-a", labels=("smoke",)),
        material("image-3", source="oss-a", labels=("helmet",), status="pending_decision"),
        material("image-4", source="s3-a", labels=("person",)),
    ])

    first = repository.list_page(limit=2)
    assert len(first.items) == 2
    assert first.next_cursor
    second = repository.list_page(limit=2, cursor=first.next_cursor)
    assert {row["id"] for row in first.items + second.items} == {
        "image-1", "image-2", "image-3", "image-4"
    }

    by_source = repository.list_page(storage_source_ids=["oss-a"], limit=20)
    assert {row["id"] for row in by_source.items} == {"image-2", "image-3"}
    by_status = repository.list_page(processing_status="pending_decision", limit=20)
    assert [row["id"] for row in by_status.items] == ["image-3"]
    by_name = repository.list_page(query="IMAGE-4", limit=20)
    assert [row["id"] for row in by_name.items] == ["image-4"]

    any_label = repository.list_page(labels=["fire", "smoke"], limit=20)
    assert {row["id"] for row in any_label.items} == {"image-1", "image-2"}
    assert repository.count(labels=["fire", "smoke"]) == 2


def test_unprocessed_filter_groups_transient_states(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([
        material("image-1", status="pending_decision"),
        material("image-2", status="cleaning"),
        material("image-3", status="unprocessed"),
        material("image-4", status="processed"),
    ])
    page = repository.list_page(processing_status="unprocessed", limit=20)
    assert {row["id"] for row in page.items} == {"image-1", "image-2", "image-3"}
    assert page.total == 3


def test_reference_count_and_id_only_page(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([
        material("image-1", source="oss-a", labels=("fire",)),
        material("image-2", source="oss-a", labels=("smoke",)),
        material("image-3", source="s3-a", labels=("fire",)),
    ])
    assert repository.reference_count("oss-a") == 2
    page = repository.list_ids(labels=["fire"], limit=10)
    assert set(page.items) == {"image-1", "image-3"}


def test_legacy_external_rows_get_collision_safe_working_name(tmp_path):
    repository = MaterialRepository(tmp_path)
    legacy = {
        "id": "remote-legacy-1",
        "filename": "camera.jpg",
        "stored_name": "",
        "storage_source_id": "oss-a",
        "storage_type": "oss",
        "object_key": "archive/2026/camera.jpg",
        "content_sha256": "a" * 64,
        "labels": [],
    }
    persisted = repository.upsert(legacy)
    assert persisted["stored_name"] == "remote-legacy-1.jpg"
    assert repository.get("remote-legacy-1")["stored_name"] == "remote-legacy-1.jpg"
    assert repository.get("remote-legacy-1")["object_key"] == "archive/2026/camera.jpg"

    # Simulate a row persisted by an older build where payload_json still had stored_name="".
    with repository._connect() as database:
        payload = dict(legacy)
        database.execute(
            "UPDATE materials SET payload_json = ? WHERE id = ?",
            (__import__("json").dumps(payload), "remote-legacy-1"),
        )
    recovered = repository.get("remote-legacy-1")
    assert recovered["stored_name"] == "remote-legacy-1.jpg"
    assert recovered["object_key"] == "archive/2026/camera.jpg"


def test_concurrent_readers_observe_committed_batches(tmp_path):
    repository = MaterialRepository(tmp_path)

    def write_batch(batch: int):
        repository.upsert_many([material(f"batch-{batch}-{index}") for index in range(5)])

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(write_batch, range(8)))
    with ThreadPoolExecutor(max_workers=8) as pool:
        counts = list(pool.map(lambda _index: repository.count(), range(16)))
    assert counts == [40] * 16


def test_compatibility_mutate_remains_atomic(tmp_path):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([material("image-1"), material("image-2")])

    changed = repository.mutate(
        lambda rows: [row.update({"processing_status": "processed"}) or row["id"] for row in rows]
    )

    assert changed == ["image-1", "image-2"]
    assert repository.count(processing_status="processed") == 2


def test_compatibility_mutate_only_rewrites_changed_rows(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)
    repository.upsert_many([material("image-1"), material("image-2")])
    original_write = MaterialRepository._write_row
    written = []

    def tracked_write(database, value):
        written.append(str(value.get("id")))
        return original_write(database, value)

    monkeypatch.setattr(MaterialRepository, "_write_row", staticmethod(tracked_write))

    def change_one(rows):
        rows[0]["processing_status"] = "cleaning"
        return rows[0]["id"]

    assert repository.mutate(change_one) == "image-1"
    assert written == ["image-1"]
    assert repository.get("image-2")["processing_status"] == "processed"


def test_find_existing_content_hashes_streams_normalized_single_pass_batches(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)
    existing_hashes = [f"{index:064x}" for index in range(1201)]
    repository.upsert_many([
        {**material(f"image-{index:04d}"), "content_sha256": content_hash}
        for index, content_hash in enumerate(existing_hashes)
    ])

    class OnePassHashes:
        def __init__(self, values, state):
            self.values = values
            self.state = state
            self.iterations = 0

        def __iter__(self):
            self.iterations += 1
            if self.iterations > 1:
                raise AssertionError("hash input was consumed more than once")
            for value in self.values:
                self.state["since_query"] += 1
                if self.state["since_query"] > 500:
                    raise AssertionError("hash input was materialized before the first batch query")
                yield value

    class TracedConnection:
        def __init__(self, connection):
            self.connection = connection
            self.exact_query_parameter_counts = []
            self.normalized_query_parameter_counts = []
            self.closed = False

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, sql, parameters=()):
            if "FROM material_content_hash_lookup" in sql and " IN (" in sql:
                query_state["since_query"] = 0
            if "FROM materials" in sql and " IN (" in sql:
                assert "content_sha256 <> ''" in sql
                if "lower(trim(content_sha256))" in sql:
                    self.normalized_query_parameter_counts.append(len(parameters))
                else:
                    self.exact_query_parameter_counts.append(len(parameters))
            return self.connection.execute(sql, parameters)

        def close(self):
            self.closed = True
            self.connection.close()

        def __getattr__(self, name):
            return getattr(self.connection, name)

    original_connect = repository._connect
    traced = TracedConnection(original_connect())
    monkeypatch.setattr(repository, "_connect", lambda: traced)
    query_state = {"since_query": 0}
    requested = OnePassHashes([
        *(content_hash.upper() for content_hash in existing_hashes),
        *(f"{index:064x}" for index in range(1201, 1300)),
        "",
        "   ",
        existing_hashes[0].upper(),
        f"  {existing_hashes[1].upper()}  ",
    ], query_state)

    assert repository.find_existing_content_hashes(requested) == set(existing_hashes)
    assert requested.iterations == 1
    assert traced.exact_query_parameter_counts == [500, 500, 300]
    assert traced.normalized_query_parameter_counts == [99]
    assert max([*traced.exact_query_parameter_counts, *traced.normalized_query_parameter_counts]) == 500
    assert traced.closed


def test_find_existing_content_hashes_ignores_blank_input_without_empty_in_clause(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)

    class TracedConnection:
        def __init__(self, connection):
            self.connection = connection
            self.executed_sql = []
            self.closed = False

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, sql, parameters=()):
            self.executed_sql.append(sql)
            return self.connection.execute(sql, parameters)

        def close(self):
            self.closed = True
            self.connection.close()

        def __getattr__(self, name):
            return getattr(self.connection, name)

    traced = TracedConnection(repository._connect())
    monkeypatch.setattr(repository, "_connect", lambda: traced)

    assert repository.find_existing_content_hashes(["", " ", "\t", None]) == set()
    assert not any("content_sha256 IN (" in sql for sql in traced.executed_sql)
    assert traced.closed


def test_find_existing_content_hashes_uses_distinct_rows_per_requested_hash(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)
    repeated_hashes = ("a" * 64, "b" * 64)
    with repository._connect() as database:
        database.executemany(
            "INSERT INTO materials(id, object_key, content_sha256, payload_json) VALUES (?, ?, ?, ?)",
            (
                (f"duplicate-{index:04d}", f"uploads/{index:04d}.jpg", repeated_hashes[index % 2], "{}")
                for index in range(2000)
            ),
        )

    class TracedCursor:
        def __init__(self, cursor, rows_per_query):
            self.cursor = cursor
            self.rows_per_query = rows_per_query

        def fetchall(self):
            rows = self.cursor.fetchall()
            self.rows_per_query.append(len(rows))
            return rows

        def __getattr__(self, name):
            return getattr(self.cursor, name)

    class TracedConnection:
        def __init__(self, connection):
            self.connection = connection
            self.exact_parameter_counts = []
            self.rows_per_query = []
            self.closed = False

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, sql, parameters=()):
            cursor = self.connection.execute(sql, parameters)
            if "FROM materials" not in sql or " IN (" not in sql:
                return cursor
            assert "content_sha256 <> ''" in sql
            if "lower(trim(content_sha256))" in sql:
                assert "SELECT DISTINCT lower(trim(content_sha256))" in sql
                return cursor
            assert "SELECT DISTINCT content_sha256" in sql
            self.exact_parameter_counts.append(len(parameters))
            return TracedCursor(cursor, self.rows_per_query)

        def close(self):
            self.closed = True
            self.connection.close()

        def __getattr__(self, name):
            return getattr(self.connection, name)

    traced = TracedConnection(repository._connect())
    monkeypatch.setattr(repository, "_connect", lambda: traced)

    assert repository.find_existing_content_hashes([*repeated_hashes, "c" * 64]) == set(repeated_hashes)
    assert traced.rows_per_query == [2]
    assert all(rows <= parameters for rows, parameters in zip(traced.rows_per_query, traced.exact_parameter_counts))
    assert traced.closed


def test_find_existing_content_hashes_checkpoints_missing_hashes_in_temp_table(tmp_path, monkeypatch):
    repository = MaterialRepository(tmp_path)
    missing_hashes = [f"{index + 5000:064x}" for index in range(500)]
    state = {"since_checkpoint": 0}

    def repeated_hashes():
        for _batch in range(3):
            for content_hash in missing_hashes:
                state["since_checkpoint"] += 1
                if state["since_checkpoint"] > 500:
                    raise AssertionError("input was read past a batch before its TEMP checkpoint")
                yield content_hash

    class TracedConnection:
        def __init__(self, connection):
            self.connection = connection
            self.exact_query_parameter_counts = []
            self.normalized_query_parameter_counts = []
            self.closed = False

        def __enter__(self):
            self.connection.__enter__()
            return self

        def __exit__(self, *args):
            return self.connection.__exit__(*args)

        def execute(self, sql, parameters=()):
            if "FROM material_content_hash_lookup" in sql and " IN (" in sql:
                state["since_checkpoint"] = 0
            if "FROM materials" in sql and " IN (" in sql:
                assert "content_sha256 <> ''" in sql
                if "lower(trim(content_sha256))" in sql:
                    self.normalized_query_parameter_counts.append(len(parameters))
                else:
                    self.exact_query_parameter_counts.append(len(parameters))
            return self.connection.execute(sql, parameters)

        def close(self):
            self.closed = True
            self.connection.close()

        def __getattr__(self, name):
            return getattr(self.connection, name)

    traced = TracedConnection(repository._connect())
    monkeypatch.setattr(repository, "_connect", lambda: traced)

    assert repository.find_existing_content_hashes(repeated_hashes()) == set()
    assert traced.exact_query_parameter_counts == [500]
    assert traced.normalized_query_parameter_counts == [500]
    assert traced.closed


def test_repository_creates_content_sha256_partial_index_without_rewriting_existing_data(tmp_path):
    database_path = tmp_path / "materials.sqlite3"
    legacy_hash = f"  {'A' * 64}  "
    with sqlite3.connect(database_path) as database:
        database.execute(
            """
            CREATE TABLE materials (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL DEFAULT '',
                storage_source_id TEXT NOT NULL DEFAULT 'default_local',
                storage_type TEXT NOT NULL DEFAULT 'local',
                object_key TEXT NOT NULL,
                content_sha256 TEXT NOT NULL DEFAULT '',
                size_bytes INTEGER NOT NULL DEFAULT 0,
                etag TEXT NOT NULL DEFAULT '',
                processing_status TEXT NOT NULL DEFAULT 'pending_decision',
                box_count INTEGER NOT NULL DEFAULT 0,
                annotated INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL DEFAULT '',
                updated_at TEXT NOT NULL DEFAULT '',
                payload_json TEXT NOT NULL
            )
            """
        )
        database.execute(
            "INSERT INTO materials(id, object_key, content_sha256, payload_json) VALUES (?, ?, ?, ?)",
            ("legacy", "uploads/legacy.jpg", legacy_hash, '{"id":"legacy"}'),
        )

    repository = MaterialRepository(tmp_path)

    assert repository.get("legacy") == {"id": "legacy"}
    assert repository.find_existing_content_hashes(["a" * 64]) == {"a" * 64}
    assert repository.upsert({**material("new-hash-a"), "content_sha256": legacy_hash})["content_sha256"] == "a" * 64
    with repository._connect() as database:
        index = database.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("ix_materials_content_sha256",),
        ).fetchone()
        normalized_index = database.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'index' AND name = ?",
            ("ix_materials_content_sha256_normalized",),
        ).fetchone()
        legacy_row = database.execute(
            "SELECT id, content_sha256, payload_json FROM materials WHERE id = ?",
            ("legacy",),
        ).fetchone()
    assert index is not None
    assert "WHERE content_sha256 <> ''" in index["sql"]
    assert normalized_index is not None
    assert "lower(trim(content_sha256))" in normalized_index["sql"]
    assert dict(legacy_row) == {"id": "legacy", "content_sha256": legacy_hash, "payload_json": '{"id":"legacy"}'}


def test_content_sha256_lookup_queries_use_their_partial_indexes(tmp_path):
    repository = MaterialRepository(tmp_path)
    content_hash = "a" * 64
    repository.upsert({**material("indexed-hash-a"), "content_sha256": content_hash})

    with repository._connect() as database:
        exact_plan = database.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT DISTINCT content_sha256 FROM materials
            WHERE content_sha256 <> '' AND content_sha256 IN (?)
            """,
            (content_hash,),
        ).fetchall()
        normalized_plan = database.execute(
            """
            EXPLAIN QUERY PLAN
            SELECT DISTINCT lower(trim(content_sha256)) AS content_sha256 FROM materials
            WHERE content_sha256 <> '' AND lower(trim(content_sha256)) IN (?)
            """,
            (content_hash,),
        ).fetchall()

    assert any(
        "ix_materials_content_sha256" in row["detail"] and "normalized" not in row["detail"]
        for row in exact_plan
    )
    assert any("ix_materials_content_sha256_normalized" in row["detail"] for row in normalized_plan)
