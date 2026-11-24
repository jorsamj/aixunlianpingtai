"""T8.1-T8.3 real PostgreSQL verification for the algorithm domain.

Runs only with an isolated local PostgreSQL (``pgserver`` + ``psycopg`` 3).
Every test uses a throwaway server rooted in a temporary directory; nothing
here points at a shared or production database.
"""
from __future__ import annotations

import copy
import json
import pathlib
import os
import tempfile

import pytest


def _require_or_skip(module_name: str, reason: str):
    """Import a PostgreSQL dependency, or skip - unless CI demands real PG.

    ``MC_REQUIRE_POSTGRES=1`` turns "no PostgreSQL here" into a hard failure, so
    a CI job can never report green by silently skipping the contracts.
    """
    import importlib

    try:
        return importlib.import_module(module_name)
    except ImportError:
        if os.environ.get("MC_REQUIRE_POSTGRES", "").strip() == "1":
            raise RuntimeError(
                f"MC_REQUIRE_POSTGRES=1 but {module_name} is unavailable: {reason}"
            )
        pytest.skip(reason, allow_module_level=True)


psycopg = _require_or_skip("psycopg", "psycopg 3 is required for PostgreSQL provider tests")
_EXTERNAL_DSN_ENV = "MC_TEST_POSTGRES_DSN"

from platform_core.algorithm_cutover import (
    admit_cutover,
    assess_rollback,
    cutover_status,
    rollback,
)
from platform_core.algorithm_migration import (
    AlgorithmMigrationError,
    build_report,
    content_digest,
    export_source_snapshot,
    import_snapshot,
    run_status,
)
from platform_core.algorithm_postgres_schema import (
    AlgorithmSchemaError,
    ensure_schema,
    schema_status,
)
from platform_core.algorithm_postgres_store import (
    PostgresAlgorithmRepository,
    export_target_snapshot,
)
from platform_core.algorithm_repository import (
    AlgorithmAdmissionRequired,
    admission_record_path,
    open_algorithm_repository,
)
from platform_core.algorithm_shadow import _digest, _snapshot_body
from platform_core.algorithm_sql_store import AlgorithmSqlStore


class _ExternalPostgres:
    """A PostgreSQL server supplied by CI (service container) instead of pgserver."""

    def __init__(self, dsn: str):
        self._dsn = dsn

    def get_uri(self) -> str:
        return self._dsn

    def cleanup(self) -> None:
        # Leave the container as we found it: the contracts create the
        # algorithm schema themselves, so only that schema is removed.
        try:
            with psycopg.connect(self._dsn) as connection:
                with connection.cursor() as cursor:
                    cursor.execute("DROP SCHEMA IF EXISTS w5_algorithm CASCADE")
                connection.commit()
        except Exception:
            pass


@pytest.fixture(scope="module")
def pg():
    external = os.environ.get(_EXTERNAL_DSN_ENV, "").strip()
    if external:
        yield _ExternalPostgres(external)
        return
    pgserver = _require_or_skip(
        "pgserver", "an isolated local PostgreSQL server is required"
    )
    root = pathlib.Path(tempfile.mkdtemp(prefix="t8pg-")) / "data"
    server = pgserver.get_server(root, cleanup_mode="delete")
    try:
        yield server
    finally:
        server.cleanup()


def _rows():
    return [
        {
            "id": "algo-a",
            "name": "烟火 A",
            "remark": "",
            "industry": "fire",
            "algorithm_type": "yolo_ultralytics",
            "current_version_id": "v-a2",
            "custom_legacy_field": {"nested": [1, None, "x"]},
            "versions": [
                {
                    "id": "v-a1", "version_name": "20260101000000", "training_status": "SUCCEEDED",
                    "stored_path": "oss://bucket/models/a1.pt", "artifact_verified": True,
                    "trainable": False, "created_at": "2026-01-01", "finished_at": None,
                    "metrics": {"map50": 0.5}, "empty_string_field": "",
                },
                {
                    "id": "v-a2", "version_name": "2", "training_status": "SUCCEEDED",
                    "stored_path": None, "created_at": "2026-02-01",
                    "evaluation": {"status": "DONE", "evaluation_id": "e1",
                                   "metrics": {"map50": 0.61}},
                },
            ],
            "external_analyses": [
                {"analysis_id": "an-1", "analysis_name": "A1", "analysis_type": "1",
                 "status": "1", "compute_platform_ids": ["p1", "p2"], "active": True},
                {"analysis_id": "an-2", "analysis_name": "A2", "analysis_type": "0",
                 "status": "0"},
            ],
            "external_analysis_id": "an-1",
        },
        {
            "id": "algo-b", "name": "B", "source_type": "EXTERNAL",
            "provider_type": "CHANG_LIAN", "external_product_id": "prod-1",
            "external_active": 1, "master_data_readonly": 0,
            "current_version_id": None, "versions": [], "external_analyses": [],
        },
    ]


def _store(root: pathlib.Path, project: str, rows=None) -> AlgorithmSqlStore:
    store = AlgorithmSqlStore(root / project / "algorithms.json")
    store.replace_all(rows if rows is not None else _rows())
    return store


def _connect(server):
    return psycopg.connect(server.get_uri())


def _initialized(server):
    with _connect(server) as connection:
        ensure_schema(connection, allow_upgrade=True)


def _import(server, snapshot, **kwargs):
    with _connect(server) as connection:
        return import_snapshot(connection, snapshot, **kwargs)


def test_schema_init_is_explicit_versioned_and_idempotent(pg):
    with _connect(pg) as connection:
        before = schema_status(connection)
        assert before["present"] is False and before["version"] == 0
        with pytest.raises(AlgorithmSchemaError) as error:
            ensure_schema(connection)
        assert error.value.code == "ALGORITHM_PG_SCHEMA_UPGRADE_REQUIRED"

        dry = ensure_schema(connection, allow_upgrade=True, dry_run=True)
        assert dry["applied"] and dry["dry_run"] is True
        assert schema_status(connection)["present"] is False

        applied = ensure_schema(connection, allow_upgrade=True)
        assert [item["version"] for item in applied["applied"]] == [1]
        current = schema_status(connection)
        assert current["up_to_date"] is True and current["version"] == 1
        assert current["checksum_mismatch"] == [] and current["missing_tables"] == []

        again = ensure_schema(connection, allow_upgrade=True)
        assert again["already_current"] is True and again["applied"] == []
        assert [row["version"] for row in current["applied"]] == [1]


def test_import_is_idempotent_resumable_and_refuses_unsafe_overwrites(pg):
    _initialized(pg)
    store = _store(pathlib.Path(tempfile.mkdtemp(prefix="t8imp-")), "imports")
    snapshot = export_source_snapshot(store.db_path, "imports")
    first = _import(pg, snapshot)
    assert first["action"] == "apply" and first["changed"] is True and first["resumed"] is False

    second = _import(pg, snapshot)
    assert second["action"] == "noop" and second["changed"] is False

    # A newer SQLite revision is applied, a dry run never persists it.
    store.patch_algorithm("algo-a", {"name": "烟火 A v2"})
    newer = export_source_snapshot(store.db_path, "imports")
    dry = _import(pg, newer, dry_run=True)
    assert dry["action"] == "apply" and dry["dry_run"] is True and dry["changed"] is False
    with _connect(pg) as connection:
        target = export_target_snapshot(connection, "imports")
    assert target["algorithm_revision"] == snapshot["algorithm_revision"]
    assert content_digest(target) == content_digest(snapshot)

    applied = _import(pg, newer)
    assert applied["changed"] is True
    with pytest.raises(AlgorithmMigrationError) as regression:
        _import(pg, snapshot)
    assert regression.value.code == "ALGORITHM_MIGRATION_REVISION_REGRESSION"

    # Same revision, different content can never overwrite the target.
    tampered = copy.deepcopy(newer)
    tampered["tables"]["algorithms"][0]["name"] = "tampered"
    tampered["snapshot_digest"] = _digest(_snapshot_body(
        tampered["project_id"], tampered["algorithm_revision"], tampered["tables"]))
    with pytest.raises(AlgorithmMigrationError) as conflict:
        _import(pg, tampered)
    assert conflict.value.code == "ALGORITHM_MIGRATION_DIGEST_CONFLICT"

    # Interruption evidence: a stale RUNNING row is only taken over with --resume.
    with _connect(pg) as connection:
        connection.execute(
            "INSERT INTO w5_algorithm.migration_run (run_id,project_id,snapshot_digest,"
            "content_digest,algorithm_revision,mode,status,actor,started_at,heartbeat_at) "
            "VALUES ('stale-run',%s,%s,%s,%s,'APPLY','RUNNING','test',"
            "now()-interval '1 hour', now()-interval '1 hour')",
            ("imports", newer["snapshot_digest"], content_digest(newer),
             newer["algorithm_revision"]),
        )
        connection.commit()
    with pytest.raises(AlgorithmMigrationError) as busy:
        _import(pg, newer)
    assert busy.value.code == "ALGORITHM_MIGRATION_RUN_IN_PROGRESS"
    resumed = _import(pg, newer, resume=True)
    assert resumed["resumed"] is True
    with _connect(pg) as connection:
        runs = run_status(connection, "imports")["runs"]
    assert any(row["run_id"] == "stale-run" and row["status"] == "ABORTED" for row in runs)
    assert runs[0]["status"] == "COMPLETED"


def test_report_proves_ids_counts_associations_json_null_and_digest(pg):
    _initialized(pg)
    store = _store(pathlib.Path(tempfile.mkdtemp(prefix="t8rep-")), "reporting")
    snapshot = export_source_snapshot(store.db_path, "reporting")
    _import(pg, snapshot)
    with _connect(pg) as connection:
        target = export_target_snapshot(connection, "reporting")
        report = build_report(snapshot, target, schema=schema_status(connection))
    assert report["verdict"] == "OK", report["blocking_findings"]
    assert all(check["ok"] for check in report["checks"].values())
    assert report["checks"]["primary_keys"]["tables"]["algorithms"]["missing"] == []
    assert report["checks"]["primary_keys"]["tables"]["algorithms"]["extra"] == []
    assert report["checks"]["primary_keys"]["ids_regenerated"] == 0
    assert report["checks"]["revision"]["relation"] == "equal"
    assert report["checks"]["object_references"]["resolved"] is False
    assert report["checks"]["object_references"]["non_string"] == []
    assert len(report["summary_digest"]) == 64
    assert report["source"]["content_digest"] == report["target"]["content_digest"]

    # A regenerated id and a lost empty string are reported, not accepted.
    broken = copy.deepcopy(target)
    broken["tables"]["algorithms"][0]["id"] = "algo-regenerated"
    broken["tables"]["versions"][0]["version_name"] = None
    broken["snapshot_digest"] = _digest(_snapshot_body(
        broken["project_id"], broken["algorithm_revision"], broken["tables"]))
    bad = build_report(snapshot, broken)
    assert bad["verdict"] == "MISMATCH"
    assert "primary_keys" in bad["blocking_findings"]
    assert bad["checks"]["primary_keys"]["ids_regenerated"] >= 1
    assert "null_vs_empty" in bad["blocking_findings"]


def _admitted_repository(server, store, project_id: str):
    """Open the PostgreSQL provider through the real admission contract.

    PostgreSQL writes require an admission; a test may not bypass it, so the
    parity test performs the same isolated cutover admission production uses and
    then opens the repository with that record.
    """
    snapshot = export_source_snapshot(store.db_path, project_id)
    _import(server, snapshot)
    with _connect(server) as connection:
        admitted = admit_cutover(
            connection, db_path=store.db_path, project_id=project_id,
            expected_generation=0, operator="parity-test", reason="isolated parity",
            acknowledge_unported=True,
        )
    assert admitted["admitted"] is True, admitted
    return PostgresAlgorithmRepository(
        server.get_uri(), project_id, admission=admitted["admission"],
    )


def test_read_and_write_parity_with_sqlite_store(pg):
    _initialized(pg)
    root = pathlib.Path(tempfile.mkdtemp(prefix="t8par-"))
    store = AlgorithmSqlStore(root / "parity" / "algorithms.json")
    store.ensure_ready()
    repo = _admitted_repository(pg, store, "parity")
    assert store.read_all() == [] and repo.read_all() == []

    store.create_algorithm({"id": "x1", "name": "X1", "algorithm_type": "yolo_ultralytics"})
    assert repo.create_algorithm(
        {"id": "x1", "name": "X1", "algorithm_type": "yolo_ultralytics"}
    )["id"] == "x1"
    assert store.read_all() == repo.read_all()

    store.attach_version("x1", {"id": "v1", "version_name": "1", "created_at": "2026-01-01"})
    repo.attach_version("x1", {"id": "v1", "version_name": "1", "created_at": "2026-01-01"})
    assert store.read_all() == repo.read_all()

    store.attach_version_if_current(
        "x1", {"id": "v2", "version_name": "2", "created_at": "2026-02-01"},
        expected_current_version_id="v1",
    )
    repo.attach_version_if_current(
        "x1", {"id": "v2", "version_name": "2", "created_at": "2026-02-01"},
        expected_current_version_id="v1",
    )
    assert store.read_all() == repo.read_all()

    store.patch_version("x1", "v2", {"training_status": "SUCCEEDED"}, now="2026-02-02")
    repo.patch_version("x1", "v2", {"training_status": "SUCCEEDED"}, now="2026-02-02")
    assert store.read_all() == repo.read_all()

    store.patch_algorithm("x1", {"remark": "note"})
    repo.patch_algorithm("x1", {"remark": "note"})
    assert store.read_all() == repo.read_all()

    operation = {"id": "op-1", "action": "ROLLBACK"}
    removed = store.rollback_version(
        "x1", "v1", expected_current_version_id="v2", operation=operation,
        now="2026-02-03", delete_current_version=False,
    )
    assert repo.rollback_version(
        "x1", "v1", expected_current_version_id="v2", operation=operation,
        now="2026-02-03", delete_current_version=False,
    ) == removed
    assert store.read_all() == repo.read_all()

    store.update_version_operation("x1", "op-1", {"status": "DONE"})
    repo.update_version_operation("x1", "op-1", {"status": "DONE"})
    assert store.read_all() == repo.read_all()

    store.attach_version("x1", {"id": "v3", "version_name": "3", "created_at": "2026-03-01"})
    repo.attach_version("x1", {"id": "v3", "version_name": "3", "created_at": "2026-03-01"})
    store.rollback_version(
        "x1", "v1", expected_current_version_id="v3",
        operation={"id": "op-2", "action": "ROLLBACK"}, now="2026-03-02",
        delete_current_version=False,
    )
    repo.rollback_version(
        "x1", "v1", expected_current_version_id="v3",
        operation={"id": "op-2", "action": "ROLLBACK"}, now="2026-03-02",
        delete_current_version=False,
    )
    store.delete_version_with_operation(
        "x1", "v2", expected_current_version_id="v1",
        operation={"id": "op-3", "action": "DELETE"}, now="2026-03-03",
    )
    repo.delete_version_with_operation(
        "x1", "v2", expected_current_version_id="v1",
        operation={"id": "op-3", "action": "DELETE"}, now="2026-03-03",
    )
    assert store.read_all() == repo.read_all()

    incoming = {
        "prod-9": {
            "id": "ext-9", "name": "EXT 9", "source_type": "EXTERNAL",
            "provider_type": "CHANG_LIAN", "external_product_id": "prod-9",
            "external_analysis_id": "a9",
            "external_analyses": [
                {"analysis_id": "a9", "analysis_type": "1", "status": "1"}
            ],
        }
    }
    assert store.sync_external_algorithms(incoming, provider="changlian",
                                          synced_at="2026-03-03") == repo.sync_external_algorithms(
        incoming, provider="changlian", synced_at="2026-03-03")
    assert store.read_all() == repo.read_all()
    assert store.revision() == repo.revision()

    store.replace_all(_rows())
    repo.replace_all(_rows())
    assert store.read_all() == repo.read_all()
    assert store.read_one("algo-a") == repo.read_one("algo-a")
    assert store.read_all(summary_only=True) == repo.read_all(summary_only=True)


def test_cutover_admission_gates_single_writer_and_stale_sqlite(pg):
    _initialized(pg)
    root = pathlib.Path(tempfile.mkdtemp(prefix="t8cut-"))
    store = _store(root, "cutover")
    snapshot = export_source_snapshot(store.db_path, "cutover")
    _import(pg, snapshot)
    record_path = admission_record_path(store.db_path)

    with _connect(pg) as connection:
        refused = admit_cutover(
            connection, db_path=store.db_path, project_id="cutover",
            expected_generation=5, operator="ops", reason="pilot",
            acknowledge_unported=True,
        )
    assert refused["admitted"] is False
    assert "WRITER_GENERATION_MATCHES" in refused["blocking"]

    with _connect(pg) as connection:
        admitted = admit_cutover(
            connection, db_path=store.db_path, project_id="cutover",
            expected_generation=0, operator="ops", reason="pilot",
            acknowledge_unported=True,
        )
    assert admitted["admitted"] is True, admitted["blocking"]
    # Every presentation projection is implemented now, so the admission
    # records an empty gap; the single-writer safety assertions still hold.
    assert admitted["admission"]["unported_operations"] == []
    from platform_core.algorithm_cutover import write_admission_record

    write_admission_record(admitted["admission"], record_path)

    with pytest.raises(AlgorithmAdmissionRequired) as stale:
        open_algorithm_repository(store.json_path, provider="sqlite")
    assert stale.value.code == "ALGORITHM_SQLITE_STALE_AFTER_CUTOVER"
    assert open_algorithm_repository(
        store.json_path, provider="sqlite", allow_stale_sqlite=True
    ).provider_name == "sqlite"

    provider = open_algorithm_repository(
        store.json_path, provider="postgresql", dsn=pg.get_uri()
    )
    assert provider.read_one("algo-a")["name"] == "烟火 A"
    assert provider.read_all() == store.read_all()

    with _connect(pg) as connection:
        again = admit_cutover(
            connection, db_path=store.db_path, project_id="cutover",
            expected_generation=1, operator="ops", reason="twice",
            acknowledge_unported=True,
        )
        status = cutover_status(connection, "cutover")
    assert again["admitted"] is False
    assert "SINGLE_AUTHORITATIVE_WRITER" in again["blocking"]
    assert status["authoritative_provider"] == "postgresql"
    assert status["writer_generation"] == 1

    # PostgreSQL receives a newer write: reverse restoration must be blocked.
    provider.patch_algorithm("algo-a", {"remark": "post-cutover change"})
    with _connect(pg) as connection:
        blocked = rollback(
            connection, db_path=store.db_path, admission_path=record_path,
            confirmed=True, operator="ops", reason="undo",
        )
    assert blocked["rolled_back"] is False
    assert "TARGET_HAS_NO_NEW_WRITES" in blocked["assessment"]["blocking"]


def test_concurrent_imports_never_admit_two_writers(pg):
    import threading
    from concurrent.futures import ThreadPoolExecutor

    _initialized(pg)
    root = pathlib.Path(tempfile.mkdtemp(prefix="t8race-"))
    store = _store(root, "race")
    snapshot = export_source_snapshot(store.db_path, "race")
    barrier = threading.Barrier(2)

    def attempt(_index):
        with _connect(pg) as connection:
            barrier.wait(timeout=10)
            try:
                result = import_snapshot(connection, snapshot)
                return ("ok", result["action"], result["changed"])
            except AlgorithmMigrationError as error:
                return ("error", error.code)

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(attempt, range(2)))
    assert results.count(("ok", "apply", True)) == 1, results
    for item in results:
        assert item in (
            ("ok", "apply", True),
            ("ok", "noop", False),
            ("error", "ALGORITHM_MIGRATION_RUN_IN_PROGRESS"),
        ), results
    with _connect(pg) as connection:
        target = export_target_snapshot(connection, "race")
        runs = run_status(connection, "race")["runs"]
    assert target["algorithm_revision"] == snapshot["algorithm_revision"]
    assert [row for row in runs if row["status"] == "RUNNING"] == []
    assert any(row["status"] == "COMPLETED" for row in runs)


def test_cli_entry_points_run_the_full_cutover_cycle(pg, tmp_path, capsys):
    from platform_core.algorithm_migration_cli import main

    root = pathlib.Path(tempfile.mkdtemp(prefix="t8cli-"))
    store = _store(root, "cli")
    dsn = pg.get_uri()
    snapshot_path = tmp_path / "snapshot.json"
    report_path = tmp_path / "report.json"

    assert main([
        "export", "--db", str(store.db_path), "--project", "cli",
        "--out", str(snapshot_path),
    ]) == 0
    # Re-running schema-init without --allow-upgrade is a safe no-op, not a
    # hidden migration: the schema is already at the target version.
    assert main(["schema-init", "--dsn", dsn]) == 0
    assert main(["schema-init", "--dsn", dsn, "--allow-upgrade"]) == 0
    assert main(["import", "--snapshot", str(snapshot_path), "--dsn", dsn]) == 0
    assert main([
        "verify", "--db", str(store.db_path), "--project", "cli", "--dsn", dsn,
    ]) == 0
    assert main([
        "report", "--snapshot", str(snapshot_path), "--dsn", dsn,
        "--out", str(report_path),
    ]) == 0
    assert json.loads(report_path.read_text(encoding="utf-8"))["verdict"] == "OK"

    assert main([
        "cutover-admit", "--db", str(store.db_path), "--project", "cli", "--dsn", dsn,
        "--expected-generation", "0", "--operator", "ops", "--reason", "cli pilot",
        "--acknowledge-unported",
    ]) == 0
    assert main(["cutover-status", "--dsn", dsn, "--project", "cli"]) == 0
    # A second admission at the same generation is refused with exit code 3.
    assert main([
        "cutover-admit", "--db", str(store.db_path), "--project", "cli", "--dsn", dsn,
        "--expected-generation", "0", "--operator", "ops", "--reason", "twice",
        "--acknowledge-unported",
    ]) == 3
    assert main(["rollback-assess", "--db", str(store.db_path), "--dsn", dsn]) == 0
    assert main([
        "rollback-execute", "--db", str(store.db_path), "--dsn", dsn,
        "--operator", "ops", "--reason", "undo", "--confirm",
    ]) == 0

    captured = capsys.readouterr()
    assert dsn not in captured.out and dsn not in captured.err


def test_rollback_requires_matching_evidence_and_restores_sqlite(pg):
    _initialized(pg)
    root = pathlib.Path(tempfile.mkdtemp(prefix="t8rb-"))
    store = _store(root, "rollback")
    snapshot = export_source_snapshot(store.db_path, "rollback")
    _import(pg, snapshot)
    record_path = admission_record_path(store.db_path)
    with _connect(pg) as connection:
        admitted = admit_cutover(
            connection, db_path=store.db_path, project_id="rollback",
            expected_generation=0, operator="ops", reason="pilot",
            acknowledge_unported=True,
        )
        assert admitted["admitted"] is True
        from platform_core.algorithm_cutover import write_admission_record

        write_admission_record(admitted["admission"], record_path)
        assessment = assess_rollback(
            connection, db_path=store.db_path,
            admission=admitted["admission"],
        )
    assert assessment["allowed"] is True, assessment["blocking"]

    # A stale SQLite copy blocks restoration.
    store.patch_algorithm("algo-a", {"name": "local edit after cutover"})
    with _connect(pg) as connection:
        blocked = rollback(
            connection, db_path=store.db_path, admission_path=record_path,
            confirmed=True, operator="ops", reason="undo",
        )
    assert blocked["rolled_back"] is False
    assert "SQLITE_COPY_MATCHES_ADMITTED_CONTENT" in blocked["assessment"]["blocking"]

    # Restore the SQLite copy to the admitted content, then roll back for real.
    from platform_core.algorithm_migration import restore_source_snapshot

    restore_source_snapshot(store.db_path, "rollback", snapshot, confirmed=True, assessment={
        "allowed": True, "blocking": [], "restore_content_digest": content_digest(snapshot),
    })
    with _connect(pg) as connection:
        result = rollback(
            connection, db_path=store.db_path, admission_path=record_path,
            confirmed=True, operator="ops", reason="undo",
        )
        status = cutover_status(connection, "rollback")
    assert result["rolled_back"] is True, result["assessment"]["blocking"]
    assert result["restored"]["verified"] is True
    assert status["authoritative_provider"] == "sqlite"
    assert status["writer_generation"] == 2
    assert export_source_snapshot(store.db_path, "rollback")["counts"] == snapshot["counts"]
    reopened = open_algorithm_repository(store.json_path, provider="sqlite")
    assert reopened.provider_name == "sqlite"
    assert reopened.read_all() == store.read_all()


def _presentation_repository(server, store, project_id: str):
    """Admitted PostgreSQL provider for a presentation-contract test."""
    snapshot = export_source_snapshot(store.db_path, project_id)
    _import(server, snapshot)
    with _connect(server) as connection:
        admitted = admit_cutover(
            connection, db_path=store.db_path, project_id=project_id,
            expected_generation=0, operator="presentation", reason="isolated",
            acknowledge_unported=False,
        )
    assert admitted["admitted"] is True, admitted
    return PostgresAlgorithmRepository(
        server.get_uri(), project_id, admission=admitted["admission"],
    )


def test_all_seven_presentations_answer_real_business_queries(pg):
    """Every presentation projection is actually callable and keeps its contract."""
    _initialized(pg)
    root = pathlib.Path(tempfile.mkdtemp(prefix="t8pres-"))
    store = _store(root, "pres")
    repo = _presentation_repository(pg, store, "pres")

    rows, total, revision = repo.bootstrap_summary()
    assert total == 2 and {row["id"] for row in rows} == {"algo-a", "algo-b"}
    assert all(row["versions_deferred"] is True and row["versions"] == [] for row in rows)
    assert isinstance(revision, int)

    assert repo.training_display_refs([]) == {}
    assert repo.training_display_refs(["no-such-task"]) == {}

    basic = repo.asset_algorithm_basic("algo-a")
    assert basic["name"] == "烟火 A" and basic["editable"] is True
    assert basic["deferred_fields"] == []

    page = repo.asset_versions("algo-a", page=1, page_size=10)
    assert page["total"] == 2 and page["versions_deferred"] is False
    assert page["algorithm"]["id"] == "algo-a"
    assert repo.asset_versions("algo-a", page=2, page_size=10)["items"] == []

    one = repo.asset_version("algo-a", "v-a1", detail=True)
    assert one["id"] == "v-a1" and one["model_file"]["file_name"] == "a1.pt"
    assert one["metrics"]["map50"] == 0.5
    assert one["has_model"] is True

    listing = repo.asset_algorithms(page=1, page_size=10)
    assert listing["total"] == 2 and len(listing["items"]) == 2
    by_id = {item["id"]: item for item in listing["items"]}
    assert by_id["algo-a"]["current_version"]["id"] == "v-a2"
    assert set(listing["filter_options"]) == {
        "algorithm_type", "industry", "source_type", "status",
    }
    assert repo.asset_algorithms(query="nothing-matches")["total"] == 0

    library = repo.library_algorithms(
        statistics=[], master_digest="", categories=(), page=1, page_size=10,
    )
    assert library["total"] == 2
    card = next(item for item in library["items"] if item["id"] == "algo-a")
    assert card["id"] == "algo-a" and card["trainable"] is True
    # Current version v-a2 carries evaluation.metrics.map50 = 0.61 -> 61.0
    assert card["map50_percent"] == pytest.approx(61.0)
    assert card["current_version"]["id"] == "v-a2"
    assert library["items"][0]["versions_deferred"] is True
    assert repo.library_algorithms(
        statistics=[], page=2, page_size=10,
    )["items"] == []

    # Project isolation: identical ids in another project never leak across.
    other_repo = _presentation_repository(pg, _store(root, "other"), "other")
    assert repo.asset_versions("algo-a")["total"] == 2
    assert other_repo.asset_versions("algo-a")["total"] == 2
    assert repo.asset_algorithms()["total"] == 2
    assert other_repo.asset_algorithms()["total"] == 2

    # A stale admission still refuses writes.
    stale = dict(repo._admission)
    stale["writer_generation"] = int(stale["writer_generation"]) + 5
    stale_repo = PostgresAlgorithmRepository(
        pg.get_uri(), "pres", admission=stale,
    )
    with pytest.raises(AlgorithmAdmissionRequired):
        stale_repo.create_algorithm({"id": "leak", "name": "leak"})
