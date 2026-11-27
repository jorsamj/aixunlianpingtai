"""U3-P1 picker read provider contracts against a real PostgreSQL projection.

The SQLite owner is the semantic baseline; the PostgreSQL provider must return the
same ids, order, counts and DTOs for the P1-supported filters, must paginate
stably, must read batches without N+1, and must fail closed when the published
snapshot cannot be proven equal to the current owner.
"""
from __future__ import annotations

import json
import pathlib
import sqlite3
import tempfile

import pytest


def _require_or_skip(module_name: str, reason: str):
    import importlib
    import os

    try:
        return importlib.import_module(module_name)
    except ImportError:
        if os.environ.get("MC_REQUIRE_POSTGRES", "").strip() == "1":
            raise RuntimeError(f"MC_REQUIRE_POSTGRES=1 but {module_name} is unavailable: {reason}")
        pytest.skip(reason, allow_module_level=True)


psycopg = _require_or_skip("psycopg", "psycopg 3 is required for PostgreSQL contracts")

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.negative_pool import _DDL as POOL_DDL
from platform_core.training_material_picker_api import _gt_material_filter_page
from platform_core.training_material_picker_read import (
    PostgresPickerReadProvider,
    PickerCursorContextMismatch,
    PickerFilter,
    PickerOwnerUnverifiable,
    PickerProjectionUnavailable,
    PickerQuery,
    PickerSnapshotNotReady,
    PickerSnapshotStale,
    PickerUnsupportedFilter,
    SQLitePickerReadProvider,
    sqlite_owner_revision_source,
)
from platform_core.u3_shadow import (
    SCHEMA_NAME,
    ensure_schema,
    export_project_snapshot,
    import_project_snapshot,
)


class _ExternalPostgres:
    def __init__(self, dsn: str):
        self._dsn = dsn

    def get_uri(self) -> str:
        return self._dsn

    def cleanup(self) -> None:
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute(f"DROP SCHEMA IF EXISTS {SCHEMA_NAME} CASCADE")
                connection.commit()
        except Exception:
            pass


@pytest.fixture(scope="module")
def pg():
    import os

    external = os.environ.get("MC_TEST_POSTGRES_DSN", "").strip()
    if external:
        server = _ExternalPostgres(external)
        yield server
        server.cleanup()
        return
    pgserver = _require_or_skip("pgserver", "an isolated local PostgreSQL server is required")
    root = pathlib.Path(tempfile.mkdtemp(prefix="pgp1-")) / "data"
    server = pgserver.get_server(root, cleanup_mode="delete")
    yield server
    server.cleanup()


# ---------------------------------------------------------------------------
# Fixtures: one owner project exported into PostgreSQL
# ---------------------------------------------------------------------------
def _material(index: int, *, source: str, created_at: str) -> dict:
    return {
        "id": f"m{index:03d}",
        "filename": f"Material-{index:03d}.jpg",
        "storage_source_id": source,
        "storage_type": "local",
        "object_key": f"uploads/m{index:03d}.jpg",
        "content_sha256": f"{index + 1:064x}"[-64:],
        "size_bytes": 1024 + index,
        "processing_status": "processed",
        "box_count": 1,
        "annotated": True,
        "created_at": created_at,
        "updated_at": "2026-09-15T12:00:00+00:00",
    }


def _build_project(tmp_path, project_id: str = "p1", *, confirmations: bool = False):
    project = tmp_path / "projects" / project_id
    project.mkdir(parents=True)
    repository = MaterialRepository(project)
    # m000-m003 share a created_at on purpose: ordering must fall back to id.
    records = []
    for index in range(12):
        created_at = (
            "2026-09-15T12:00:00+00:00" if index < 4
            else f"2026-09-15T12:00:{index - 3:02d}+00:00"
        )
        records.append(_material(
            index, source="nas-1" if index in {0, 3, 6, 9} else "default_local",
            created_at=created_at,
        ))
    repository.upsert_many(records)
    with sqlite3.connect(repository.path) as database:
        for statement in POOL_DDL:
            database.execute(statement)
    annotations = AnnotationRepository(project)
    payload = []
    for index in range(10):
        label = "smoke" if index % 2 == 0 else "person"
        payload.append({
            "image_id": f"m{index:03d}",
            "annotation_state": "annotated",
            "boxes": [{"id": f"b{index}", "label": label, "x1": 10, "y1": 10, "x2": 40, "y2": 40}],
        })
    # m006 is a formal confirmed-empty with a smoke scope; m010/m011 are unannotated.
    payload = [row for row in payload if row["image_id"] not in {"m006"}]
    payload.append({
        "image_id": "m006", "annotation_state": "confirmed_empty",
        "boxes": [], "annotation_scope": ["smoke"],
    })
    annotations.upsert_many(payload)
    with sqlite3.connect(repository.path) as database:
        # Declared material label without formal GT: must never satisfy a GT filter.
        database.execute("INSERT INTO material_labels(material_id, label_code, box_count) VALUES ('m011','smoke',0)")
        database.execute("INSERT INTO negative_pool_members VALUES ('m002','2026-09-16T00:00:00+00:00')")
        database.execute("INSERT INTO negative_pool_members VALUES ('m003','2026-09-17T00:00:00+00:00')")
        database.execute("INSERT INTO negative_pool_categories VALUES ('cat-1','fire',1)")
        database.execute("INSERT INTO negative_pool_categories VALUES ('cat-2','smoke',1)")
        database.execute("INSERT INTO negative_pool_links VALUES ('m002','cat-2')")
        database.execute("INSERT INTO negative_pool_links VALUES ('m003','cat-1')")
        database.execute("INSERT INTO negative_pool_algorithm_members VALUES ('algo-1','m002','2026-09-16T00:00:00+00:00')")
    if confirmations:
        repository_annotations = AnnotationRepository(project)
        record = repository_annotations.get("m000")
        for receipt in ("r-1", "r-2"):
            repository_annotations.confirm_task_negatives(
                "ctx-a",
                [{
                    "receipt_id": receipt, "context_key": "ctx-a", "image_id": "m000",
                    "annotation_version": int(record["version"]),
                    "annotation_hash": str(record["content_digest"]),
                }],
                {"actor_id": "tester"},
            )
    return project


_PROJECT_TABLES = (
    "negative_pool_link", "negative_pool_algorithm_member", "negative_pool_member",
    "negative_pool_category", "material_label", "material_annotation_scope",
    "annotation_label_reference", "annotation", "material", "evidence_row",
    "table_state", "store_revision", "picker_snapshot_state",
    "u3_projection_cursor", "task_negative_confirmation", "u3_shadow_import",
)


def _reset(pg, project_id: str) -> None:
    """Each test starts from an empty projection for its project id."""
    with psycopg.connect(pg.get_uri()) as connection:
        ensure_schema(connection)
        with connection.transaction():
            with connection.cursor() as cursor:
                for table in _PROJECT_TABLES:
                    cursor.execute(
                        f"DELETE FROM {SCHEMA_NAME}.{table} WHERE project_id=%s",
                        (project_id,),
                    )


def _publish(pg, project, project_id: str = "p1"):
    snapshot = export_project_snapshot(project, project_id)
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot)
    return snapshot


def _providers(pg, project, project_id: str = "p1"):
    _reset(pg, project_id)
    _publish(pg, project, project_id)
    sqlite_provider = SQLitePickerReadProvider(project)
    postgres_provider = PostgresPickerReadProvider.from_dsn(
        pg.get_uri(), owner_revisions=sqlite_owner_revision_source(project),
    )
    return sqlite_provider, postgres_provider


def _page(provider, *, project_id="p1", filters=None, **kwargs):
    return provider.read_page(PickerQuery(
        project_id=project_id, filters=filters or PickerFilter(), **kwargs,
    ))


# ---------------------------------------------------------------------------
# A. base filters
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("filters", [
    PickerFilter(),
    PickerFilter(query="MATERIAL-00"),
    PickerFilter(query="material-01"),
    PickerFilter(storage_source_ids=("nas-1",)),
    PickerFilter(created_from="2026-09-15T12:00:03+00:00"),
    PickerFilter(created_to="2026-09-15"),
    PickerFilter(
        query="Material", storage_source_ids=("default_local",),
        created_from="2026-09-15", created_to="2026-09-15",
    ),
    PickerFilter(image_ids=("m002", "m005", "m002")),
])
def test_base_filters_match_the_sqlite_baseline(pg, tmp_path, filters):
    sqlite_provider, postgres_provider = _providers(pg, _build_project(tmp_path))
    baseline = _page(sqlite_provider, filters=filters, page=1, page_size=100)
    candidate = _page(postgres_provider, filters=filters, page=1, page_size=100)
    assert [item.id for item in candidate.items] == [item.id for item in baseline.items]
    assert candidate.total == baseline.total
    assert candidate.has_more == baseline.has_more
    assert [(item.id, item.filename, item.storage_source_id, item.created_at)
            for item in candidate.items] == [
        (item.id, item.filename, item.storage_source_id, item.created_at)
        for item in baseline.items
    ]


# ---------------------------------------------------------------------------
# B. labels / formal GT
# ---------------------------------------------------------------------------
def test_label_and_formal_gt_filters_match_the_baseline(pg, tmp_path):
    sqlite_provider, postgres_provider = _providers(pg, _build_project(tmp_path))
    cases = [
        PickerFilter(labels=("smoke",)),
        PickerFilter(labels=("person",)),
        PickerFilter(labels=("smoke", "person")),
        PickerFilter(labels=("smoke", "smoke")),
        PickerFilter(labels=("smoke", "person"), label_mode="all"),
        PickerFilter(require_ground_truth=True),
        PickerFilter(annotation_state="annotated"),
        PickerFilter(annotation_state="confirmed_empty"),
        PickerFilter(annotation_state="unannotated"),
        PickerFilter(labels=("smoke",), annotation_state="confirmed_empty"),
    ]
    for filters in cases:
        baseline = _page(sqlite_provider, filters=filters, page=1, page_size=100)
        candidate = _page(postgres_provider, filters=filters, page=1, page_size=100)
        assert [item.id for item in candidate.items] == [item.id for item in baseline.items], filters
        assert candidate.total == baseline.total, filters
    # Formal GT wins over the declared material label.
    smoke = _page(postgres_provider, filters=PickerFilter(labels=("smoke",)))
    assert "m011" not in {item.id for item in smoke.items}
    # confirmed_empty keeps its scope: it satisfies require_ground_truth, not a positive label.
    ground_truth = _page(postgres_provider, filters=PickerFilter(require_ground_truth=True))
    assert "m006" in {item.id for item in ground_truth.items}
    assert "m006" not in {item.id for item in smoke.items}


# ---------------------------------------------------------------------------
# C. negative pool
# ---------------------------------------------------------------------------
def test_negative_pool_filters_match_the_baseline(pg, tmp_path):
    sqlite_provider, postgres_provider = _providers(pg, _build_project(tmp_path))
    cases = [
        PickerFilter(negative_pool_only=True),
        PickerFilter(negative_category_ids=("cat-1",)),
        PickerFilter(negative_category_ids=("cat-2",)),
        # Existing contract: an algorithm id alone does not activate pool filtering;
        # it narrows an active pool filter.
        PickerFilter(algorithm_asset_id="algo-1"),
        PickerFilter(negative_pool_only=True, algorithm_asset_id="algo-1"),
        PickerFilter(negative_category_ids=("cat-2",), algorithm_asset_id="algo-1"),
        PickerFilter(negative_pool_only=True, query="m002"),
    ]
    for filters in cases:
        baseline = _page(sqlite_provider, filters=filters, page=1, page_size=100)
        candidate = _page(postgres_provider, filters=filters, page=1, page_size=100)
        assert [item.id for item in candidate.items] == [item.id for item in baseline.items], filters
        assert candidate.total == baseline.total, filters
    members = _page(postgres_provider, filters=PickerFilter(negative_pool_only=True))
    assert {item.id for item in members.items} == {"m002", "m003"}
    algorithm_only = _page(postgres_provider, filters=PickerFilter(algorithm_asset_id="algo-1"))
    assert algorithm_only.total == 12
    algorithm_scoped = _page(
        postgres_provider,
        filters=PickerFilter(negative_pool_only=True, algorithm_asset_id="algo-1"),
    )
    assert {item.id for item in algorithm_scoped.items} == {"m002"}
    # Membership never grants training-negative eligibility: P1 only reads relations.
    relations = postgres_provider.get_pool_relations("p1", ["m002", "m003", "m004"])
    assert relations["m002"].member is True
    assert relations["m002"].algorithm_ids == ("algo-1",)
    assert relations["m004"].member is False


# ---------------------------------------------------------------------------
# D. pagination
# ---------------------------------------------------------------------------
def test_page_and_cursor_pagination_match_the_baseline(pg, tmp_path):
    sqlite_provider, postgres_provider = _providers(pg, _build_project(tmp_path))
    for sort_order in ("oldest", "newest"):
        baseline = _page(sqlite_provider, sort_order=sort_order, page=1, page_size=100)
        expected = [item.id for item in baseline.items]
        # page mode
        for page in (1, 2, 3):
            candidate = _page(postgres_provider, sort_order=sort_order, page=page, page_size=5)
            start = (page - 1) * 5
            assert [item.id for item in candidate.items] == expected[start:start + 5]
            assert candidate.total == len(expected)
        # cursor mode: complete traversal, no duplicates, no gaps
        collected: list[str] = []
        cursor = None
        while True:
            candidate = _page(
                postgres_provider, sort_order=sort_order, page_size=3, cursor=cursor,
            )
            collected.extend(item.id for item in candidate.items)
            assert candidate.total == len(expected)
            if not candidate.has_more:
                break
            cursor = candidate.next_cursor
            assert cursor
        assert collected == expected
        assert len(set(collected)) == len(collected)
    # Deferred count never runs the full COUNT and still reports has_more.
    deferred = _page(postgres_provider, count_mode="deferred", page_size=5)
    assert deferred.total is None
    assert deferred.has_more is True
    exact = _page(postgres_provider, count_mode="exact", page_size=5)
    assert exact.total == 12


def test_invalid_or_stale_cursors_are_refused(pg, tmp_path):
    project = _build_project(tmp_path)
    _, postgres_provider = _providers(pg, project)
    first = _page(postgres_provider, page_size=5)
    cursor = first.next_cursor
    assert cursor
    with pytest.raises(PickerCursorContextMismatch):
        _page(postgres_provider, page_size=5, cursor="not-a-cursor")
    with pytest.raises(PickerCursorContextMismatch):
        _page(postgres_provider, filters=PickerFilter(storage_source_ids=("nas-1",)),
              page_size=5, cursor=cursor)
    # A new published snapshot invalidates the old cursor.
    repository = MaterialRepository(project)
    repository.upsert(_material(99, source="default_local", created_at="2026-09-16T00:00:00+00:00"))
    _publish(pg, project)
    with pytest.raises(PickerCursorContextMismatch):
        _page(postgres_provider, page_size=5, cursor=cursor)
    with pytest.raises(PickerUnsupportedFilter):
        _page(postgres_provider, page=99, page_size=5)


# ---------------------------------------------------------------------------
# E. batch reads / isolation
# ---------------------------------------------------------------------------
def test_batch_reads_are_bounded_and_scoped(pg, tmp_path):
    sqlite_provider, postgres_provider = _providers(pg, _build_project(tmp_path))
    requested = ["m003", "missing", "m003", "m000"]
    for provider in (sqlite_provider, postgres_provider):
        materials = provider.get_many("p1", requested)
        assert list(materials) == ["m003", "m000"]
        assert materials["m003"].filename == "Material-003.jpg"
        annotations = provider.get_annotations("p1", ["m000", "m006", "m010", "m011"])
        assert set(annotations.annotations) == {"m000", "m006"}
        assert annotations.annotations["m006"].annotation_state == "confirmed_empty"
        assert set(annotations.missing_ids) == {"m010", "m011"}
        assert annotations.unproven_legacy_ids == ()


def test_legacy_references_are_reported_as_unproven(pg, tmp_path):
    project = _build_project(tmp_path, "legacy")
    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.execute(
            "INSERT INTO annotation_label_references"
            "(image_id,label_code,box_count,scope_ref,annotation_state,source_kind) "
            "VALUES ('m010','smoke',1,1,'annotated','legacy')"
        )
    _publish(pg, project, "legacy")
    provider = PostgresPickerReadProvider.from_dsn(
        pg.get_uri(), owner_revisions=sqlite_owner_revision_source(project),
    )
    annotations = provider.get_annotations("legacy", ["m010", "m009"])
    assert "m010" in annotations.unproven_legacy_ids
    assert "m010" not in annotations.annotations
    # The reference is still usable for filtering in BOTH providers (same contract).
    sqlite_provider = SQLitePickerReadProvider(project)
    filters = PickerFilter(labels=("smoke",))
    assert [item.id for item in _page(sqlite_provider, project_id="legacy", filters=filters).items] == [
        item.id for item in _page(provider, project_id="legacy", filters=filters).items
    ]


def test_projects_are_isolated(pg, tmp_path):
    first = _build_project(tmp_path / "a", "p1")
    second = _build_project(tmp_path / "b", "p2")
    _reset(pg, "p1")
    _reset(pg, "p2")
    _publish(pg, first, "p1")
    _publish(pg, second, "p2")
    provider = PostgresPickerReadProvider.from_dsn(
        pg.get_uri(), owner_revisions=sqlite_owner_revision_source(first),
    )
    page = _page(provider, project_id="p1")
    assert page.total == 12
    assert all(item.id.startswith("m") for item in page.items)
    other = _page(provider, project_id="p2")
    assert other.total == 12
    assert provider.get_many("p1", ["m000"])["m000"].id == "m000"


# ---------------------------------------------------------------------------
# F. snapshot / owner consistency, fail closed
# ---------------------------------------------------------------------------
def test_snapshot_context_is_repeatable_read_only(pg, tmp_path):
    _, postgres_provider = _providers(pg, _build_project(tmp_path))
    info = postgres_provider.snapshot_context("p1")
    assert info.status == "READY"
    assert info.isolation == "REPEATABLE READ"
    assert info.read_only is True
    assert info.read_identity
    assert info.snapshot_id


def test_stale_and_non_ready_snapshots_are_refused(pg, tmp_path):
    project = _build_project(tmp_path)
    sqlite_provider, _ = _providers(pg, project)
    snapshot = export_project_snapshot(project, "p1")
    # Incremental import publishes STALE.
    with psycopg.connect(pg.get_uri()) as connection:
        import_project_snapshot(connection, snapshot, mode="incremental")
    provider = PostgresPickerReadProvider.from_dsn(
        pg.get_uri(), owner_revisions=sqlite_owner_revision_source(project),
    )
    with pytest.raises(PickerSnapshotNotReady):
        _page(provider)
    # Re-publish READY, then change the owner material revision.
    _publish(pg, project)
    MaterialRepository(project).upsert(
        _material(50, source="default_local", created_at="2026-09-17T00:00:00+00:00")
    )
    with pytest.raises(PickerSnapshotStale):
        _page(provider)
    # Re-publish, then advance only the materials evidence generation.
    _publish(pg, project)
    MaterialRepository(project).record_deferred_cleanup(
        {"id": "m000"}, owner="tester", error="boom",
    )
    with pytest.raises(PickerSnapshotStale):
        _page(provider)


def test_owner_structure_change_is_stale_and_unverifiable_without_source(pg, tmp_path):
    project = _build_project(tmp_path)
    _providers(pg, project)
    with sqlite3.connect(project / "materials.sqlite3") as database:
        database.execute("DROP TABLE material_cleanup_deferred")
    MaterialRepository(project).reconcile_evidence_structure()
    _publish(pg, project)
    provider = PostgresPickerReadProvider.from_dsn(
        pg.get_uri(), owner_revisions=sqlite_owner_revision_source(project),
    )
    # Certified structure transition is accepted by the snapshot itself...
    page = _page(provider)
    assert page.total == 12
    # ...but a version that no source can prove is refused, never assumed safe.
    blind = PostgresPickerReadProvider.from_dsn(pg.get_uri())
    with pytest.raises(PickerOwnerUnverifiable):
        _page(blind)


def test_projection_and_query_failures_are_not_empty_results(pg, tmp_path):
    project = _build_project(tmp_path)
    _providers(pg, project)
    provider = PostgresPickerReadProvider.from_dsn(
        "postgresql://postgres:postgres@127.0.0.1:1/does_not_exist",
        owner_revisions=sqlite_owner_revision_source(project),
    )
    with pytest.raises(PickerProjectionUnavailable):
        _page(provider)
    # Missing snapshot row for a project that was never imported.
    other = PostgresPickerReadProvider.from_dsn(
        pg.get_uri(), owner_revisions=sqlite_owner_revision_source(project),
    )
    with pytest.raises(Exception) as missing:
        _page(other, project_id="never-imported")
    assert missing.value.code in {"PICKER_SNAPSHOT_MISSING", "PICKER_OWNER_UNVERIFIABLE"}


def test_count_page_and_annotations_share_one_mvcc_snapshot(pg, tmp_path):
    project = _build_project(tmp_path)
    _, postgres_provider = _providers(pg, project)
    with postgres_provider._read("p1", verify_owner=False) as (cursor, _state, identity, _owner):
        clauses, params = postgres_provider._where(_page_query("p1"))
        where = " WHERE " + " AND ".join(clauses)
        cursor.execute(f"SELECT COUNT(*) AS total FROM {SCHEMA_NAME}.material m{where}", params)
        before = int(cursor.fetchone()["total"])
        # Another committed writer is invisible inside this REPEATABLE READ snapshot.
        with psycopg.connect(pg.get_uri()) as writer:
            with writer.transaction():
                with writer.cursor() as other:
                    other.execute(
                        f"INSERT INTO {SCHEMA_NAME}.material"
                        "(project_id,id,filename,processing_status,created_at,payload) "
                        "VALUES ('p1','m999','late.jpg','processed','2026-09-30T00:00:00+00:00','{}'::jsonb)"
                    )
        cursor.execute(f"SELECT COUNT(*) AS total FROM {SCHEMA_NAME}.material m{where}", params)
        after = int(cursor.fetchone()["total"])
        assert after == before
    # A new read sees the committed row (MVCC snapshot is per read, not global).
    assert _page(postgres_provider, page_size=100).total == before + 1


def _page_query(project_id: str) -> PickerQuery:
    return PickerQuery(project_id=project_id)


def test_negative_confirmation_projection_authority(pg, tmp_path):
    project = _build_project(tmp_path, confirmations=True)
    _providers(pg, project)
    provider = PostgresPickerReadProvider.from_dsn(
        pg.get_uri(), owner_revisions=sqlite_owner_revision_source(project),
    )
    current = provider.get_task_negative_receipts("p1", "ctx-a", ["m000"])
    assert current.authoritative is True
    assert len(current.receipts) == 2
    # Remove the source table: retained projection rows are history, not current
    # confirmations. Evidence rows stay untouched.
    with sqlite3.connect(project / "annotations.sqlite3") as database:
        database.execute("DROP TABLE task_negative_confirmations")
    AnnotationRepository(project).reconcile_evidence_structure()
    _publish(pg, project)
    provider = PostgresPickerReadProvider.from_dsn(
        pg.get_uri(), owner_revisions=sqlite_owner_revision_source(project),
    )
    historic = provider.get_task_negative_receipts("p1", "ctx-a", ["m000"])
    assert historic.authoritative is False
    assert historic.receipts == ()
    with psycopg.connect(pg.get_uri()) as connection:
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.execute(
                    f"SELECT count(*) FROM {SCHEMA_NAME}.evidence_row "
                    "WHERE project_id='p1' AND table_name='task_negative_confirmations'"
                )
                assert cursor.fetchone()[0] == 2
                cursor.execute(
                    f"SELECT count(*) FROM {SCHEMA_NAME}.task_negative_confirmation "
                    "WHERE project_id='p1'"
                )
                assert cursor.fetchone()[0] == 2


# ---------------------------------------------------------------------------
# G. candidates + existing SQLite engine unchanged
# ---------------------------------------------------------------------------
def test_candidate_iteration_is_bounded_and_complete(pg, tmp_path):
    sqlite_provider, postgres_provider = _providers(pg, _build_project(tmp_path))
    expected = [item.id for item in _page(sqlite_provider, page_size=100).items]
    for provider in (sqlite_provider, postgres_provider):
        batches = list(provider.iter_candidates(
            PickerQuery(project_id="p1", filters=PickerFilter()), batch_size=5,
        ))
        assert all(0 < len(batch) <= 5 for batch in batches)
        assert [item.id for batch in batches for item in batch] == expected


def test_sqlite_provider_delegates_to_the_existing_picker_engine(tmp_path, monkeypatch):
    from platform_core import training_material_picker_api as api

    calls = {"count": 0}
    real = api._gt_material_filter_page

    def wrapper(*args, **kwargs):
        calls["count"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(api, "_gt_material_filter_page", wrapper)
    project = _build_project(tmp_path)
    provider = SQLitePickerReadProvider(project)
    page = _page(provider, page_size=5)
    assert calls["count"] == 1
    direct = _gt_material_filter_page(
        provider.repository, provider.annotations, limit=5, page=1,
        query="", labels=(), require_ground_truth=False, include_payload=True,
        sort_order="oldest", filters={"label_mode": "any", "browse_only": True},
        count_mode="exact",
    )
    assert [item.id for item in page.items] == [str(row["id"]) for row in direct["items"]]
    assert page.total == direct["total"]
