from __future__ import annotations

import copy
import pathlib
import tempfile
from concurrent.futures import ThreadPoolExecutor

import pytest

psycopg = pytest.importorskip("psycopg")
pgserver = pytest.importorskip("pgserver")

from platform_core.algorithm_shadow import (
    AlgorithmShadowError,
    _digest,
    _snapshot_body,
    export_snapshot,
    import_snapshot,
    load_shadow_snapshot,
    reconcile,
)
from platform_core.algorithm_sql_store import AlgorithmSqlStore


def _store(root, project, version=1):
    store = AlgorithmSqlStore(root / project / "algorithms.json")
    store.replace_all([{
        "id": f"algo-{project}", "name": f"Algo {project}",
        "current_version_id": f"v-{project}",
        "versions": [{"id": f"v-{project}", "version_name": f"{version}",
                      "training_status": "SUCCEEDED"}],
        "external_analyses": [{"analysis_id": f"analysis-{project}", "analysis_name": "A"}],
    }])
    return store


@pytest.fixture(scope="module")
def pg():
    root = pathlib.Path(tempfile.mkdtemp(prefix="pgw5-")) / "data"
    server = pgserver.get_server(root, cleanup_mode="delete")
    yield server
    server.cleanup()


def test_real_postgres_shadow_import_idempotency_conflict_and_reconcile(pg):
    root = pathlib.Path(tempfile.mkdtemp(prefix="w5real-"))
    store = _store(root, "p1")
    snapshot = export_snapshot(store)
    with psycopg.connect(pg.get_uri()) as connection:
        assert import_snapshot(connection, snapshot) is True
        assert import_snapshot(connection, snapshot) is False
        loaded = load_shadow_snapshot(connection, "p1")
        assert loaded is not None
        assert reconcile(snapshot, loaded)["same"] is True

        # New revision replaces the old snapshot.
        store.patch_algorithm("algo-p1", {"name": "Algo p1 v2"})
        newer = export_snapshot(store)
        assert newer["algorithm_revision"] > snapshot["algorithm_revision"]
        assert import_snapshot(connection, newer) is True
        assert load_shadow_snapshot(connection, "p1")["algorithm_revision"] == newer["algorithm_revision"]

        # Older revision must never overwrite the newer shadow.
        with pytest.raises(AlgorithmShadowError) as older:
            import_snapshot(connection, snapshot)
        assert older.value.code == "ALGORITHM_SHADOW_REVISION_REGRESSION"
        assert load_shadow_snapshot(connection, "p1")["snapshot_digest"] == newer["snapshot_digest"]

        # Same revision with different content digest is a conflict.
        conflict = copy.deepcopy(newer)
        conflict["tables"]["algorithms"][0]["name"] = "tampered"
        conflict["snapshot_digest"] = _digest(_snapshot_body(
            conflict["project_id"], conflict["algorithm_revision"], conflict["tables"]))
        with pytest.raises(AlgorithmShadowError) as digest:
            import_snapshot(connection, conflict)
        assert digest.value.code == "ALGORITHM_SHADOW_DIGEST_CONFLICT"
        assert load_shadow_snapshot(connection, "p1")["snapshot_digest"] == newer["snapshot_digest"]


def test_real_postgres_canonical_order_and_analysis_relations(pg):
    root = pathlib.Path(tempfile.mkdtemp(prefix="w5order-"))
    store = AlgorithmSqlStore(root / "order" / "algorithms.json")
    store.replace_all([
        {"id": "a-1", "name": "A1", "current_version_id": "z-1",
         "versions": [{"id": "z-1", "version_name": "1"}, {"id": "a-2", "version_name": "2"}],
         "external_analyses": [{"analysis_id": "m-1"}, {"analysis_id": "b-1"}]},
        {"id": "a-2", "name": "A2", "current_version_id": "b-2",
         "versions": [{"id": "b-2", "version_name": "1"}],
         "external_analyses": [{"analysis_id": "a-1"}]},
    ])
    snapshot = export_snapshot(store)
    with psycopg.connect(pg.get_uri()) as connection:
        assert import_snapshot(connection, snapshot) is True
        loaded = load_shadow_snapshot(connection, "order")
        assert [row["id"] for row in loaded["tables"]["algorithms"]] == ["a-1", "a-2"]
        assert [(row["algorithm_id"], row["id"]) for row in loaded["tables"]["versions"]] == [
            ("a-1", "a-2"), ("a-1", "z-1"), ("a-2", "b-2"),
        ]
        assert [(row["algorithm_id"], row["external_analysis_id"])
                for row in loaded["tables"]["analyses"]] == [
            ("a-1", "b-1"), ("a-1", "m-1"), ("a-2", "a-1"),
        ]
        assert reconcile(snapshot, loaded)["same"] is True


def test_real_postgres_non_idle_read_requires_repeatable_read(pg):
    root = pathlib.Path(tempfile.mkdtemp(prefix="w5txn-"))
    snapshot = export_snapshot(_store(root, "txn"))
    with psycopg.connect(pg.get_uri()) as setup:
        assert import_snapshot(setup, snapshot) is True

    connection = psycopg.connect(pg.get_uri(), autocommit=True)
    try:
        connection.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
        with pytest.raises(AlgorithmShadowError) as error:
            load_shadow_snapshot(connection, "txn")
        assert error.value.code == "ALGORITHM_SHADOW_TRANSACTION_ISOLATION_UNSUPPORTED"
        assert connection.execute("SELECT 1").fetchone() == (1,)
        connection.rollback()

        connection.execute("BEGIN ISOLATION LEVEL REPEATABLE READ")
        loaded = load_shadow_snapshot(connection, "txn")
        assert loaded is not None and loaded["snapshot_digest"] == snapshot["snapshot_digest"]
        assert connection.execute("SELECT 1").fetchone() == (1,)
        connection.rollback()
    finally:
        connection.close()


def test_real_postgres_first_import_concurrency_and_project_isolation(pg):
    root = pathlib.Path(tempfile.mkdtemp(prefix="w5race-"))
    snapshot = export_snapshot(_store(root, "project-a"))
    barrier = __import__("threading").Barrier(2)

    def attempt(_index):
        with psycopg.connect(pg.get_uri()) as connection:
            barrier.wait(timeout=10)
            return import_snapshot(connection, snapshot)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert sorted(results) == [False, True]

    other = export_snapshot(_store(root, "project-b"))
    with psycopg.connect(pg.get_uri()) as connection:
        assert import_snapshot(connection, other) is True
        # Updating project-a must not remove project-b.
        assert load_shadow_snapshot(connection, "project-b") is not None
        assert load_shadow_snapshot(connection, "project-b")["snapshot_digest"] == other["snapshot_digest"]
