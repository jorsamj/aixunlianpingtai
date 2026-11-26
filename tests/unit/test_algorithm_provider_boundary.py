"""T8.1-T8.3 unit contracts that do not need a PostgreSQL server.

Real PostgreSQL behaviour (schema, import, cutover, rollback) is covered by
``tests/integration/test_algorithm_migration_postgres.py`` and is never claimed
here.
"""
from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from platform_core.algorithm_migration import (
    AlgorithmMigrationError,
    build_report,
    content_digest,
    normalized_tables,
)
from platform_core.algorithm_postgres_schema import MIGRATIONS, SCHEMA_VERSION, migration_checksum
from platform_core.algorithm_postgres_store import (
    PostgresAlgorithmRepository,
    UNSUPPORTED_OPERATIONS,
)
from platform_core.algorithm_repository import (
    CLEANUP_OPERATIONS,
    CONTRACT_VERSION,
    HISTORY_EVIDENCE_OPERATIONS,
    admission_transition_path,
    CORE_OPERATIONS,
    PRESENTATION_OPERATIONS,
    AlgorithmAdmissionRequired,
    AlgorithmProviderConfigError,
    AlgorithmProviderUnsupported,
    SqliteAlgorithmRepository,
    admission_record_path,
    open_algorithm_repository,
    resolve_provider,
)
from platform_core.algorithm_shadow import _digest, _snapshot_body
from platform_core.algorithm_sql_store import AlgorithmSqlStore

BUSINESS_MODULES = (
    "app.py",
    "platform_core/algorithms.py",
    "platform_core/external_algorithm_publish.py",
    "platform_core/model_artifacts.py",
    "platform_core/training_tasks.py",
)


def _rows():
    return [
        {
            "id": "algo-1", "name": "Algo", "current_version_id": "v1",
            "versions": [{"id": "v1", "version_name": "1", "created_at": "2026-01-01"}],
            "external_analyses": [{"analysis_id": "a1", "analysis_name": "A"}],
        },
        {"id": "algo-2", "name": "Algo 2", "versions": [], "external_analyses": []},
    ]


def _store(tmp_path: Path) -> AlgorithmSqlStore:
    store = AlgorithmSqlStore(tmp_path / "project" / "algorithms.json")
    store.replace_all(_rows())
    return store


def _snapshot(store, db_path=None):
    from platform_core.algorithm_migration import export_source_snapshot

    return export_source_snapshot(db_path or store.db_path, store.project_id)


def _admission(path: Path, *, project="project", provider="postgresql", revoked=None):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "contract_version": "algorithm-repository-v1",
        "admission_id": "admit-test",
        "project_id": project,
        "authoritative_provider": provider,
        "algorithm_revision": 1,
        "snapshot_digest": "0" * 64,
        "content_digest": "0" * 64,
        "writer_generation": 1,
        "admitted_at": "2026-11-24T00:00:00+00:00",
        "revoked_at": revoked,
        "operator": "ops",
        "reason": "pilot",
    }), encoding="utf-8")


# ---------------------------------------------------------------------------
# provider boundary
# ---------------------------------------------------------------------------
def test_sqlite_is_the_default_provider_and_delegates_unchanged(tmp_path):
    store = _store(tmp_path)
    repository = open_algorithm_repository(store.json_path)
    assert isinstance(repository, SqliteAlgorithmRepository)
    assert repository.provider_name == "sqlite"
    assert repository.unsupported_operations() == ()
    assert set(CORE_OPERATIONS + PRESENTATION_OPERATIONS) <= repository.capabilities()
    assert repository.read_all() == store.read_all()
    assert repository.revision() == store.revision()
    repository.create_algorithm({"id": "algo-3", "name": "Algo 3"})
    assert store.read_one("algo-3")["name"] == "Algo 3"
    # Presentation projections keep working through the pass-through adapter.
    assert repository.bootstrap_summary()[2] == store.revision()


def test_provider_resolution_is_explicit_and_unknown_values_fail(tmp_path):
    assert resolve_provider(None, environ={}) == "sqlite"
    assert resolve_provider(None, environ={"ALGORITHM_STORE_PROVIDER": "postgresql"}) == "postgresql"
    assert resolve_provider("SQLITE", environ={}) == "sqlite"
    with pytest.raises(AlgorithmProviderConfigError) as error:
        resolve_provider("mysql", environ={})
    assert error.value.code == "ALGORITHM_PROVIDER_UNKNOWN"


def test_postgresql_selection_requires_dsn_and_admission(tmp_path):
    store = _store(tmp_path)
    with pytest.raises(AlgorithmProviderConfigError) as dsn:
        open_algorithm_repository(store.json_path, provider="postgresql", environ={})
    assert dsn.value.code == "ALGORITHM_POSTGRES_DSN_MISSING"
    with pytest.raises(AlgorithmAdmissionRequired) as admission:
        open_algorithm_repository(
            store.json_path, provider="postgresql",
            dsn="postgresql://example.invalid/db", environ={},
        )
    assert admission.value.code == "ALGORITHM_POSTGRES_ADMISSION_REQUIRED"


def test_stale_sqlite_after_cutover_is_refused_unless_explicitly_allowed(tmp_path):
    store = _store(tmp_path)
    path = admission_record_path(store.json_path)
    _admission(path)
    with pytest.raises(AlgorithmAdmissionRequired) as error:
        open_algorithm_repository(store.json_path, provider="sqlite")
    assert error.value.code == "ALGORITHM_SQLITE_STALE_AFTER_CUTOVER"
    allowed = open_algorithm_repository(
        store.json_path, provider="sqlite", allow_stale_sqlite=True
    )
    assert allowed.read_all() == store.read_all()

    _admission(path, revoked="2026-11-24T01:00:00+00:00")
    assert open_algorithm_repository(store.json_path, provider="sqlite").provider_name == "sqlite"

    _admission(path, provider="sqlite")
    assert open_algorithm_repository(store.json_path, provider="sqlite").provider_name == "sqlite"


def test_malformed_admission_record_is_refused(tmp_path):
    store = _store(tmp_path)
    path = admission_record_path(store.json_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"contract_version": "unknown"}), encoding="utf-8")
    with pytest.raises(AlgorithmAdmissionRequired) as error:
        open_algorithm_repository(store.json_path, provider="sqlite")
    assert error.value.code == "ALGORITHM_ADMISSION_RECORD_INVALID"


def test_postgres_provider_declares_and_fails_closed_on_unported_operations():
    repository = PostgresAlgorithmRepository("postgresql://example.invalid/db", "project")
    # Declared capabilities must equal what the class really serves: core plus
    # the presentation projections that are ported, never the whole set. The
    # external-algorithm cleanup domain is served by SQLite only, and is declared
    # unsupported instead of silently reaching into a SQLite copy.
    assert set(repository.capabilities()) == (
        (set(CORE_OPERATIONS) | set(PRESENTATION_OPERATIONS) - set(UNSUPPORTED_OPERATIONS))
        | set(HISTORY_EVIDENCE_OPERATIONS)
    )
    assert set(repository.unsupported_operations()) == set(UNSUPPORTED_OPERATIONS) | set(
        CLEANUP_OPERATIONS
    )
    assert set(UNSUPPORTED_OPERATIONS) <= set(PRESENTATION_OPERATIONS)
    assert repository.cleanup_supported is False
    # Every declared-unsupported presentation projection fails closed.
    for name in UNSUPPORTED_OPERATIONS:
        with pytest.raises(AlgorithmProviderUnsupported):
            getattr(repository, name)()
    # The cleanup ledger is implemented (schema V2) but the business gate stays
    # closed until the snapshot/import/report/restore contract covers it: the
    # capability declaration is what keeps the domain off, and without an
    # admission record every cleanup call still fails closed.
    assert set(CLEANUP_OPERATIONS) <= set(repository.unsupported_operations())
    # No admission: cleanup refuses before any connection is attempted (the DSN
    # in this contract is deliberately unreachable, so a connection would raise
    # OperationalError instead).
    with pytest.raises(AlgorithmAdmissionRequired):
        repository.cleanup_list()
    with pytest.raises(AlgorithmAdmissionRequired):
        repository.cleanup_summary(project_id="project", suspected_state="SUSPECTED_DELETED")
    assert "example.invalid" not in repr(repository)


def test_business_callers_embed_no_dialect_specific_sql(tmp_path):
    root = Path(__file__).resolve().parents[2]
    allowed = {
        "platform_core/algorithm_sql_store.py",
        "platform_core/algorithm_postgres_store.py",
        "platform_core/algorithm_postgres_schema.py",
        "platform_core/algorithm_migration.py",
        "platform_core/algorithm_cutover.py",
        "platform_core/algorithm_migration_cli.py",
        "platform_core/algorithm_shadow.py",
        "platform_core/algorithm_shadow_cli.py",
    }
    offenders = []
    for relative in BUSINESS_MODULES:
        path = root / relative
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"\bimport\s+psycopg\b|\bfrom\s+psycopg\b", text):
            offenders.append(f"{relative}: psycopg import")
        if "w5_algorithm." in text or "w5_shadow." in text:
            offenders.append(f"{relative}: PostgreSQL schema reference")
        if "%s::jsonb" in text:
            offenders.append(f"{relative}: PostgreSQL cast")
    assert offenders == []
    port_source = (root / "platform_core" / "algorithm_repository.py").read_text(encoding="utf-8")
    for keyword in ("SELECT ", "INSERT ", "UPDATE ", "DELETE ", "CREATE TABLE"):
        assert keyword not in port_source


# ---------------------------------------------------------------------------
# migration report semantics (pure, no server)
# ---------------------------------------------------------------------------
def test_normalized_content_digest_is_engine_independent(tmp_path):
    store = _store(tmp_path)
    snapshot = _snapshot(store)
    normalized = normalized_tables(snapshot)
    assert isinstance(normalized["algorithms"][0]["payload_json"], dict)
    # PostgreSQL JSONB may reorder keys; the content digest must not care.
    reordered = copy.deepcopy(snapshot)
    for name in ("algorithms", "versions", "analyses"):
        for row in reordered["tables"][name]:
            payload = json.loads(row["payload_json"])
            row["payload_json"] = json.dumps(dict(reversed(list(payload.items()))))
    assert content_digest(reordered) == content_digest(snapshot)

    # Boolean 0/1 and false normalize to the same value; NULL stays distinct.
    from platform_core.algorithm_migration import normalize_row

    assert normalize_row("algorithms", {"external_active": False})["external_active"] == 0
    assert normalize_row("algorithms", {"external_active": True})["external_active"] == 1
    assert normalize_row("algorithms", {"external_active": None})["external_active"] is None
    assert normalize_row(
        "algorithms", {"payload_json": '{"b": 1, "a": 2}'}
    )["payload_json"] == {"b": 1, "a": 2}


def test_report_accepts_identical_target_and_flags_each_regression(tmp_path):
    store = _store(tmp_path)
    source = _snapshot(store)
    assert build_report(source, source)["verdict"] == "OK"

    renamed = copy.deepcopy(source)
    renamed["tables"]["algorithms"][0]["id"] = "generated-id"
    renamed["snapshot_digest"] = _digest(_snapshot_body(
        renamed["project_id"], renamed["algorithm_revision"], renamed["tables"]))
    report = build_report(source, renamed)
    assert report["verdict"] == "MISMATCH"
    assert report["checks"]["primary_keys"]["ids_regenerated"] == 1

    lost_empty = copy.deepcopy(source)
    lost_empty["tables"]["algorithms"][0]["remark"] = None
    lost_empty["snapshot_digest"] = _digest(_snapshot_body(
        lost_empty["project_id"], lost_empty["algorithm_revision"], lost_empty["tables"]))
    assert "null_vs_empty" in build_report(source, lost_empty)["blocking_findings"]

    extra_project = copy.deepcopy(source)
    extra_project["tables"]["algorithms"][0]["project_id"] = "other"
    extra_project["snapshot_digest"] = _digest(_snapshot_body(
        extra_project["project_id"], extra_project["algorithm_revision"],
        extra_project["tables"]))
    assert "project_isolation" in build_report(source, extra_project)["blocking_findings"]

    older = copy.deepcopy(source)
    older["algorithm_revision"] = max(0, source["algorithm_revision"] - 1)
    older["snapshot_digest"] = _digest(_snapshot_body(
        older["project_id"], older["algorithm_revision"], older["tables"]))
    report = build_report(source, older)
    assert report["checks"]["revision"]["relation"] == "target_behind"

    missing = build_report(source, None)
    assert missing["verdict"] == "TARGET_MISSING"
    assert missing["target"] is None


def test_report_flags_object_reference_types_and_unknown_fields(tmp_path):
    store = _store(tmp_path)
    source = _snapshot(store)
    target = copy.deepcopy(source)
    target["tables"]["versions"][0]["stored_path"] = {"bucket": "b"}
    payload = json.loads(target["tables"]["versions"][0]["payload_json"])
    payload["unknown_field"] = 1
    target["tables"]["versions"][0]["payload_json"] = json.dumps(payload)
    target["snapshot_digest"] = _digest(_snapshot_body(
        target["project_id"], target["algorithm_revision"], target["tables"]))
    report = build_report(source, target)
    assert report["checks"]["object_references"]["non_string"]
    assert report["checks"]["object_references"]["resolved"] is False
    assert report["checks"]["json_fields"]["field_differences"]


def test_credential_material_is_never_exported(tmp_path):
    store = AlgorithmSqlStore(tmp_path / "secret" / "algorithms.json")
    store.replace_all([{
        "id": "algo-secret", "name": "Secret",
        "versions": [{"id": "v1", "version_name": "1",
                      "deploy": {"api_key": "sk-live-plaintext"}}],
    }])
    from platform_core.algorithm_migration import export_source_snapshot

    with pytest.raises(AlgorithmMigrationError) as error:
        export_source_snapshot(store.db_path, "secret")
    assert error.value.code == "ALGORITHM_MIGRATION_SECRET_MATERIAL"

    # A reference is not a credential and stays a string.
    store.patch_version("algo-secret", "v1", {"deploy": {"api_key": "secret://deploy/key"}},
                        now="2026-01-02")
    snapshot = export_source_snapshot(store.db_path, "secret")
    assert snapshot["counts"]["versions"] == 1


def test_schema_migrations_are_monotonic_and_checksummed():
    versions = [version for version, _name, _statements in MIGRATIONS]
    assert versions == sorted(versions)
    assert versions[-1] == SCHEMA_VERSION
    assert migration_checksum(1) == migration_checksum(1)
    assert len(migration_checksum(1)) == 64
    first = migration_checksum(1)
    assert re.fullmatch(r"[0-9a-f]{64}", first)

def _admission_record(project_id: str, *, generation: int = 2, admission_id: str = "adm-1") -> dict:
    return {
        "contract_version": CONTRACT_VERSION,
        "admission_id": admission_id,
        "project_id": project_id,
        "authoritative_provider": "postgresql",
        "writer_generation": generation,
        "admitted_at": "2026-11-24T00:00:00+00:00",
        "revoked_at": None,
    }


class _FakeCursor:
    def __init__(self, row):
        self._row = row
        self.statements = []

    def execute(self, statement, parameters=None):
        self.statements.append((statement, parameters))

    def fetchone(self):
        return self._row

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class _FakeConnection:
    def __init__(self, row):
        self.cursor_obj = _FakeCursor(row)
        self.committed = False

    def cursor(self, *_args, **_kwargs):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


def _postgres_repo(tmp_path: Path, row, *, admission=None):
    repo = PostgresAlgorithmRepository("postgresql://example/db", "project-a", admission=admission)
    connection = _FakeConnection(row)
    repo._connect = lambda: connection  # never touch a real server
    return repo, connection


def test_postgres_write_requires_an_admission_and_locks_the_cutover_row(tmp_path):
    """A missing admission must fail before any statement of the write lands."""
    repo, connection = _postgres_repo(
        tmp_path,
        {"authoritative_provider": "postgresql", "admission_id": "adm-1",
         "writer_generation": 2, "revoked_at": None, "evidence": {}},
        admission=None,
    )

    with pytest.raises(AlgorithmAdmissionRequired) as excinfo:
        with repo._write():
            raise AssertionError("the write body must never run without authority")

    assert excinfo.value.code == "ALGORITHM_POSTGRES_WRITE_ADMISSION_REQUIRED"
    assert connection.committed is False


def test_postgres_write_verifies_admission_inside_the_same_transaction(tmp_path):
    """The verdict and the write share one transaction (closed TOCTOU window)."""
    row = {"authoritative_provider": "postgresql", "admission_id": "adm-1",
           "writer_generation": 2, "revoked_at": None, "evidence": {"phase": "steady"}}
    repo, connection = _postgres_repo(
        tmp_path, row, admission=_admission_record("project-a", generation=2)
    )

    with repo._write() as cursor:
        cursor.execute("UPDATE w5_algorithm.algorithm SET name='x' WHERE project_id=%s", ("project-a",))

    statements = [statement for statement, _ in connection.cursor_obj.statements]
    authoritative = [s for s in statements if "cutover_state" in s]
    assert authoritative, "the write transaction must lock and re-read the cutover state"
    assert "FOR UPDATE" in authoritative[0]
    assert connection.committed is True
    assert statements.index(authoritative[0]) < len(statements) - 1


def test_postgres_write_refuses_a_stale_generation_or_an_unresolved_transition(tmp_path):
    stale_row = {"authoritative_provider": "postgresql", "admission_id": "adm-1",
                 "writer_generation": 3, "revoked_at": None, "evidence": {"phase": "steady"}}
    repo, _ = _postgres_repo(
        tmp_path, stale_row, admission=_admission_record("project-a", generation=2)
    )
    with pytest.raises(AlgorithmAdmissionRequired) as excinfo:
        with repo._write():
            pass
    assert excinfo.value.code == "ALGORITHM_POSTGRES_ADMISSION_STALE"

    transition_row = {**stale_row, "writer_generation": 2,
                      "evidence": {"phase": "writes_blocked"}}
    repo2, _ = _postgres_repo(
        tmp_path, transition_row, admission=_admission_record("project-a", generation=2)
    )
    with pytest.raises(AlgorithmAdmissionRequired) as excinfo2:
        with repo2._write():
            pass
    assert excinfo2.value.code == "ALGORITHM_POSTGRES_ADMISSION_STALE"
    assert "writes_blocked" in excinfo2.value.detail


def test_long_lived_sqlite_repository_stops_writing_after_cutover(tmp_path):
    """The guard re-checks authority per write, not only when the instance opens."""
    project = tmp_path / "project-a"
    project.mkdir()
    repository = open_algorithm_repository(project / "algorithms.json")
    algorithm = repository.create_algorithm({"id": "algo-1", "name": "demo"})
    assert algorithm["id"] == "algo-1"

    record_path = admission_record_path(project / "algorithms.json")
    record_path.parent.mkdir(parents=True, exist_ok=True)
    record_path.write_text(json.dumps(_admission_record("project-a")), encoding="utf-8")

    with pytest.raises(AlgorithmAdmissionRequired) as excinfo:
        repository.create_algorithm({"id": "algo-2", "name": "second"})
    assert excinfo.value.code == "ALGORITHM_SQLITE_STALE_AFTER_CUTOVER"


def test_unresolved_cutover_transition_blocks_both_providers(tmp_path):
    project = tmp_path / "project-a"
    project.mkdir()
    json_path = project / "algorithms.json"
    repository = open_algorithm_repository(json_path)
    repository.create_algorithm({"id": "algo-1", "name": "demo"})

    marker = admission_transition_path(admission_record_path(json_path))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}", encoding="utf-8")

    with pytest.raises(AlgorithmAdmissionRequired) as excinfo:
        repository.create_algorithm({"id": "algo-2", "name": "second"})
    assert excinfo.value.code == "ALGORITHM_CUTOVER_IN_PROGRESS"

    # A fresh factory open is refused as well, so a restart cannot bypass it.
    with pytest.raises(AlgorithmAdmissionRequired) as factory_error:
        open_algorithm_repository(json_path)
    assert factory_error.value.code == "ALGORITHM_CUTOVER_IN_PROGRESS"


def test_sqlite_attach_readers_refuse_a_postgres_admitted_project(tmp_path):
    """Direct SQL ATTACH readers must not serve a PostgreSQL-owned project."""
    from platform_core.algorithm_repository import (
        CONTRACT_VERSION,
        AlgorithmSqliteAttachRefused,
        require_authoritative_sqlite,
    )

    project = tmp_path / "projects" / "p"
    project.mkdir(parents=True)
    database = project / "algorithms.sqlite3"

    # No admission record: the local SQLite catalog is still authoritative.
    require_authoritative_sqlite(database)

    record = project / "algorithm_migration" / "cutover_admission.json"
    record.parent.mkdir()
    admission = {
        "contract_version": CONTRACT_VERSION,
        "project_id": "p",
        "admission_id": "a" * 24,
        "authoritative_provider": "postgresql",
        "revoked_at": None,
    }
    record.write_text(json.dumps(admission), encoding="utf-8")
    with pytest.raises(AlgorithmSqliteAttachRefused) as refused:
        require_authoritative_sqlite(database)
    assert refused.value.code == "ALGORITHM_SQLITE_STALE_AFTER_CUTOVER"

    # A verified rollback revokes the admission and re-opens the SQLite reader.
    record.write_text(json.dumps({**admission, "revoked_at": "2026-11-26T00:00:00Z"}), encoding="utf-8")
    require_authoritative_sqlite(database)


# ---------------------------------------------------------------------------
# U1 history-reference evidence (provider parity for the old ATTACH readers)
# ---------------------------------------------------------------------------
def test_history_evidence_pages_are_bounded_and_deterministic(tmp_path):
    store = _store(tmp_path)
    from platform_core.algorithm_history_evidence import (
        open_history_repository,
        revision_token,
    )
    repository = open_history_repository(store.json_path)
    provider, revision = revision_token(repository)
    assert provider == "sqlite"
    assert revision == str(store.revision())
    assert repository.history_has_versions() is True

    algorithms = []
    after = None
    while True:
        page = repository.history_algorithm_payloads(after=after, limit=1)
        assert len(page) <= 1
        algorithms.extend(record_id for record_id, _payload in page)
        if len(page) < 1:
            break
        after = page[-1][0]
    assert algorithms == sorted(algorithms) == ["algo-1", "algo-2"]

    versions = repository.history_version_payloads(limit=1)
    assert [record_id for record_id, _payload in versions] == ["v1"]
    assert versions[0][1]["version_name"] == "1"

    with pytest.raises(ValueError):
        repository.history_algorithm_payloads(limit=0)

    # A project bigger than the bounded reference scan fails closed instead of
    # silently checking only the first records.
    from platform_core.algorithm_history_evidence import iter_history_payloads
    from platform_core.algorithm_repository import AlgorithmRepositoryError

    with pytest.raises(AlgorithmRepositoryError) as overflow:
        list(iter_history_payloads(repository, page_size=1, max_records=2))
    assert overflow.value.code == "ALGORITHM_HISTORY_EVIDENCE_UNBOUNDED"


def test_history_evidence_fails_closed_for_a_postgres_owned_project(tmp_path):
    store = _store(tmp_path)
    from platform_core.algorithm_history_evidence import open_history_repository

    _admission(admission_record_path(store.json_path))

    # The SQLite provider must not serve a PostgreSQL-owned project...
    with pytest.raises(AlgorithmAdmissionRequired) as stale:
        open_history_repository(store.json_path, environ={})
    assert stale.value.code == "ALGORITHM_SQLITE_STALE_AFTER_CUTOVER"
    # ...and PostgreSQL is never opened without its own DSN/admission either.
    with pytest.raises(AlgorithmProviderConfigError) as missing:
        open_history_repository(store.json_path, provider="postgresql", environ={})
    assert missing.value.code == "ALGORITHM_POSTGRES_DSN_MISSING"


def test_reference_projection_refuses_instead_of_reporting_no_reference(tmp_path):
    """A PostgreSQL-owned project must yield "cannot verify", not "no reference"."""
    from platform_core.conversion_catalog_references import catalog_references
    from platform_core.errors import PlatformError

    root = tmp_path / "data"
    project = root / "projects" / "project"
    project.mkdir(parents=True)
    AlgorithmSqlStore(project / "algorithms.json").replace_all(_rows())
    catalog = {"vendors": [], "chips": []}
    # SQLite authority: the projection can really verify and reports no reference.
    verified = catalog_references(root, catalog, "vendors", {"id": "vendor-1"})
    assert verified["check_status"] == "VERIFIED"
    assert verified["can_delete"] is True

    _admission(admission_record_path(project / "algorithms.json"))
    with pytest.raises(PlatformError) as refused:
        catalog_references(root, catalog, "vendors", {"id": "vendor-1"})
    assert refused.value.code == "CATALOG_REFERENCE_CHECK_FAILED"


def test_training_usage_freshness_uses_the_algorithm_provider(tmp_path):
    """Only a provider-proven empty history may be reported as fresh."""
    import sqlite3

    from platform_core.training_material_usage import TrainingMaterialUsage

    data = tmp_path / "data"
    project = data / "projects" / "p"
    project.mkdir(parents=True)
    tasks = data / "task_runtime" / "tasks.sqlite3"
    tasks.parent.mkdir()
    with sqlite3.connect(tasks) as database:
        database.execute("CREATE TABLE tasks (project_id TEXT, kind TEXT)")
    usage = TrainingMaterialUsage(tasks)

    def freshness(project_id="p"):
        with sqlite3.connect(tasks) as database:
            database.row_factory = sqlite3.Row
            return usage._empty_project_history(database, project_id)

    assert freshness() is True
    AlgorithmSqlStore(project / "algorithms.json").replace_all(_rows())
    assert freshness() is False

    # Another provider owns a project: a failed read is never "no history".
    other = data / "projects" / "q"
    other.mkdir()
    assert freshness("q") is True
    _admission(admission_record_path(other / "algorithms.json"), project="q")
    assert freshness("q") is False
def test_reference_scan_refuses_a_history_change_between_pages(tmp_path, monkeypatch):
    """A changing history is "cannot verify", never "no reference"."""
    from platform_core import conversion_catalog_references as references
    from platform_core.errors import PlatformError

    root = tmp_path / "data"
    project = root / "projects" / "project"
    project.mkdir(parents=True)
    store = AlgorithmSqlStore(project / "algorithms.json")
    store.replace_all(_rows())
    catalog = {"vendors": [], "chips": []}
    original = references.iter_history_payloads

    def changing(repository, **kwargs):
        for item in original(repository, **kwargs):
            # A concurrent algorithm write lands between the pages.
            store.patch_algorithm("algo-1", {"name": "Changed mid-scan"})
            yield item

    monkeypatch.setattr(references, "iter_history_payloads", changing)
    with pytest.raises(PlatformError) as failed:
        references.catalog_references(root, catalog, "vendors", {"id": "vendor-1"})
    assert failed.value.code == "CATALOG_REFERENCE_CHECK_FAILED"
    assert "ALGORITHM_HISTORY_CHANGED_DURING_SCAN" in str(failed.value.detail)

def test_reference_scan_refuses_when_no_revision_can_prove_stability(tmp_path, monkeypatch):
    """None == None is not proof: an unavailable revision blocks deletion."""
    from platform_core import conversion_catalog_references as references
    from platform_core.algorithm_history_evidence import require_revision_token
    from platform_core.algorithm_repository import AlgorithmRepositoryError
    from platform_core.errors import PlatformError

    class _NoRevisionRepository:
        provider_name = "sqlite"

        def history_revision(self):
            return None

        def history_has_versions(self):
            return None

        def history_algorithm_payloads(self, *, after=None, limit=200):
            return []

        def history_version_payloads(self, *, after=None, limit=200):
            return []

    with pytest.raises(AlgorithmRepositoryError) as unavailable:
        require_revision_token(_NoRevisionRepository())
    assert unavailable.value.code == "ALGORITHM_HISTORY_REVISION_UNAVAILABLE"

    root = tmp_path / "data"
    project = root / "projects" / "project"
    project.mkdir(parents=True)
    # A catalog file exists but cannot tokenise its history.
    (project / "algorithms.sqlite3").write_bytes(b"")
    monkeypatch.setattr(
        references, "open_history_repository",
        lambda _path, **_kwargs: _NoRevisionRepository(),
    )
    with pytest.raises(PlatformError) as failed:
        references.catalog_references(root, {"vendors": [], "chips": []}, "vendors", {"id": "v-1"})
    assert failed.value.code == "CATALOG_REFERENCE_CHECK_FAILED"
    assert "ALGORITHM_HISTORY_REVISION_UNAVAILABLE" in str(failed.value.detail)
