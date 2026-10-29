"""Deep material pages should hydrate the requested rows only, preserving filters."""

import sqlite3
import statistics
import time

import pytest

from platform_core.material_repository import (
    MaterialFilters,
    MaterialRepository,
    _deferred_material_page_sql,
)


@pytest.fixture
def dense_materials(tmp_path):
    repository = MaterialRepository(tmp_path / "materials")
    records = []
    for number in range(6000):
        records.append({
            "id": f"m-{number:06d}",
            "filename": f"camera-{number:06d}.jpg" if number % 2 else f"other-{number:06d}.jpg",
            "object_key": f"uploads/m-{number:06d}.jpg",
            "storage_source_id": "remote-a" if number % 3 else "remote-b",
            "processing_status": "processed" if number % 4 else "pending_decision",
            "created_at": f"2026-10-28T00:{number // 120:02d}:00+00:00",
            "padding": "x" * 2048,
        })
    repository.upsert_many(records)
    return repository


@pytest.mark.parametrize("descending", [False, True])
@pytest.mark.parametrize("filtered", [False, True])
def test_deep_page_deferred_hydration_matches_original_query(dense_materials, descending, filtered):
    repository = dense_materials
    filters = MaterialFilters(
        query="camera-" if filtered else "",
        storage_source_ids=("remote-a",) if filtered else (),
        processing_status="processed" if filtered else None,
    )
    clauses, params = repository._filters(filters)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    order = " DESC" if descending else ""
    limit = 31
    offset = 450 if filtered else 5500
    old_query = (
        "SELECT m.id,m.created_at,m.payload_json FROM materials m" + where
        + f" ORDER BY m.created_at{order},m.id{order} LIMIT ? OFFSET ?"
    )
    new_query = _deferred_material_page_sql(where, descending=descending, include_payload=True, offset=True)
    with sqlite3.connect(repository.path) as db:
        expected = db.execute(old_query, [*params, limit, offset]).fetchall()
        actual = db.execute(new_query, [*params, limit, offset]).fetchall()
        plan = " ".join(str(step[3]) for step in db.execute(
            "EXPLAIN QUERY PLAN " + new_query, [*params, limit, offset],
        ))
        timings = {"old": [], "deferred": []}
        for _ in range(3):
            for name, statement in (("old", old_query), ("deferred", new_query)):
                started = time.perf_counter()
                db.execute(statement, [*params, limit, offset]).fetchall()
                timings[name].append((time.perf_counter() - started) * 1000)
    assert expected == actual
    if filtered:
        assert "MATERIALIZE" not in plan  # Wildcard search still needs a row scan.
    else:
        assert "MATERIALIZE" in plan
        assert "SEARCH m USING INDEX sqlite_autoindex_materials_1" in plan
    print("material_deep_page_ms", {key: round(statistics.median(value), 2)
                                    for key, value in timings.items()})


def test_filtered_count_cached_only_until_revision_changes(dense_materials, monkeypatch):
    repository = dense_materials
    recorded = []
    original = repository._connect

    def tracked():
        db = original()
        db.set_trace_callback(lambda sql: recorded.append(sql))
        return db

    monkeypatch.setattr(repository, "_connect", tracked)
    first = repository.list_page(page=1, limit=24, query="camera-")
    second = repository.list_page(page=3, limit=24, query="camera-")
    assert first.total == second.total == 3000
    queries = [sql for sql in recorded if "SELECT COUNT(*) FROM materials m" in sql]
    assert len(queries) == 1

    repository.upsert({
        "id": "additional-match", "filename": "camera-added.jpg", "object_key": "uploads/added.jpg",
        "created_at": "2026-10-29T00:00:00+00:00",
    })
    third = repository.list_page(page=1, limit=24, query="camera-")
    assert third.total == 3001
    queries = [sql for sql in recorded if "SELECT COUNT(*) FROM materials m" in sql]
    assert len(queries) == 2


def test_filtered_count_cross_instance_write_invalidates_cached_snapshot(dense_materials):
    reader = dense_materials
    other_worker = MaterialRepository(reader.path.parent)
    assert reader.count_filtered({"processing_status": "processed"}) == 4500
    assert other_worker.count_filtered({"processing_status": "processed"}) == 4500

    other_worker.upsert({
        "id": "cross-worker-write", "filename": "updated.jpg",
        "processing_status": "processed", "object_key": "uploads/updated.jpg",
        "created_at": "2026-10-29T00:00:00+00:00",
    })
    assert reader.count_filtered({"processing_status": "processed"}) == 4501


def test_page_and_cursor_use_same_order_and_total(dense_materials):
    repository = dense_materials
    first = repository.list_page(page=1, limit=25, sort_order="newest", annotated=False)
    assert first.total == 6000
    cursor_first = repository.list_page(limit=25, sort_order="newest", annotated=False)
    second = repository.list_page(cursor=cursor_first.next_cursor, limit=25, sort_order="newest", annotated=False)
    assert [row["id"] for row in first.items] == [row["id"] for row in cursor_first.items]
    assert [row["id"] for row in second.items] == [
        row["id"] for row in repository.list_page(page=2, limit=25, sort_order="newest", annotated=False).items
    ]
