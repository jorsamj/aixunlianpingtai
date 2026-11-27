"""U2 provider boundary for storage-source metadata (no PostgreSQL server).

Real PostgreSQL behaviour (schema, import idempotency, reconciliation) lives in
``tests/integration/test_storage_source_postgres.py`` and is never claimed here.
"""
from __future__ import annotations

import json
import sqlite3

import pytest

from platform_core.storage.source_repository import (
    CONTRACT_VERSION,
    StorageSourceAdmissionRequired,
    StorageSourceConflictError,
    StorageSourceOperationBlocked,
    StorageSourceProviderConfigError,
    StorageSourceRepository,
    admission_record_path,
    admission_transition_path,
    open_storage_source_repository,
    resolve_provider,
)
from platform_core.storage_source_migration import (
    StorageSourceMigrationError,
    export_snapshot,
    import_snapshot,
    reconcile,
)
from platform_core.storage_source_postgres_store import PostgresStorageSourceRepository


def _admission(path, *, scope="platform", revoked=None, provider="postgresql"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "contract_version": CONTRACT_VERSION,
                "admission_id": "admit-test",
                "scope": scope,
                "authoritative_provider": provider,
                "source_count": 1,
                "content_digest": "0" * 64,
                "writer_generation": 1,
                "admitted_at": "2026-11-26T00:00:00+00:00",
                "revoked_at": revoked,
                "operator": "ops",
                "reason": "pilot",
            }
        ),
        encoding="utf-8",
    )


def _repository(tmp_path):
    return StorageSourceRepository(
        tmp_path / "storage" / "storage_sources.sqlite3",
        reference_counter=lambda _source_id: 0,
    )


def test_default_provider_is_sqlite_and_unknown_values_fail(tmp_path):
    assert resolve_provider(None, environ={}) == "sqlite"
    assert (
        resolve_provider(None, environ={"STORAGE_SOURCE_PROVIDER": "postgresql"})
        == "postgresql"
    )
    with pytest.raises(StorageSourceProviderConfigError) as error:
        resolve_provider("mysql", environ={})
    assert error.value.code == "STORAGE_SOURCE_PROVIDER_UNKNOWN"
    repository = open_storage_source_repository(tmp_path / "storage" / "sources.sqlite3")
    assert isinstance(repository, StorageSourceRepository)
    assert repository.default().id == "default_local"


def test_postgresql_selection_requires_dsn_and_admission(tmp_path):
    path = tmp_path / "storage" / "sources.sqlite3"
    with pytest.raises(StorageSourceProviderConfigError) as dsn:
        open_storage_source_repository(path, provider="postgresql", environ={})
    assert dsn.value.code == "STORAGE_SOURCE_POSTGRES_DSN_MISSING"
    with pytest.raises(StorageSourceAdmissionRequired) as admission:
        open_storage_source_repository(
            path,
            provider="postgresql",
            dsn="postgresql://example.invalid/db",
            environ={},
        )
    assert admission.value.code == "STORAGE_SOURCE_POSTGRES_ADMISSION_REQUIRED"


def test_active_postgres_admission_blocks_every_sqlite_writer(tmp_path):
    repository = _repository(tmp_path)
    path = repository.path
    _admission(admission_record_path(path))

    # A fresh open is refused, and a long-lived instance cannot write either:
    # the guard is re-checked per write, not only at construction.
    with pytest.raises(StorageSourceAdmissionRequired) as stale:
        StorageSourceRepository(path)
    assert stale.value.code == "STORAGE_SOURCE_SQLITE_STALE_AFTER_CUTOVER"
    with pytest.raises(StorageSourceAdmissionRequired):
        repository.create({"id": "nas-1", "name": "NAS", "type": "local"})
    with pytest.raises(StorageSourceAdmissionRequired):
        repository.update("default_local", {"name": "Renamed"})
    with pytest.raises(StorageSourceAdmissionRequired):
        repository.set_default("default_local")
    with pytest.raises(StorageSourceAdmissionRequired):
        repository.record_health("default_local", ok=True, message="ok")
    with pytest.raises(StorageSourceAdmissionRequired):
        repository.delete("nas-1")

    # A verified rollback revokes the admission and re-opens the SQLite writer.
    _admission(admission_record_path(path), revoked="2026-11-26T01:00:00+00:00")
    assert repository.update("default_local", {"name": "Local"}).name == "Local"


def test_unresolved_transition_blocks_both_providers(tmp_path):
    repository = _repository(tmp_path)
    marker = admission_transition_path(admission_record_path(repository.path))
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text("{}", encoding="utf-8")
    with pytest.raises(StorageSourceAdmissionRequired) as blocked:
        repository.create({"id": "nas-1", "name": "NAS", "type": "local"})
    assert blocked.value.code == "STORAGE_SOURCE_CUTOVER_IN_PROGRESS"
    with pytest.raises(StorageSourceAdmissionRequired):
        open_storage_source_repository(repository.path)


def test_export_is_deterministic_and_never_exports_credentials(tmp_path):
    repository = _repository(tmp_path)
    repository.create(
        {
            "id": "nas-1",
            "name": "NAS",
            "type": "remote",
            "config": {"root": "/mnt/nas"},
            "secret_ref": "secret://storage-source/nas-1",
            "enabled": True,
        }
    )
    repository.set_default("nas-1")
    first = export_snapshot(repository.path, "platform")
    second = export_snapshot(repository.path, "platform")
    assert first == second
    assert first["contract_version"]
    assert [row["id"] for row in first["rows"]] == ["default_local", "nas-1"]
    payload = json.dumps(first, ensure_ascii=False)
    assert "secret://storage-source/nas-1" in payload
    assert [row["id"] for row in first["rows"] if row["is_default"]] == ["nas-1"]

    # A row that somehow holds credential material cannot be exported.
    with sqlite3.connect(repository.path) as database:
        database.execute(
            "UPDATE storage_sources SET config_json=? WHERE id='nas-1'",
            (json.dumps({"api_key": "sk-live"}),),
        )
    with pytest.raises(ValueError):
        export_snapshot(repository.path, "platform")


def test_reconcile_explains_every_difference(tmp_path):
    repository = _repository(tmp_path)
    repository.create({"id": "nas-1", "name": "NAS", "type": "remote"})
    snapshot = export_snapshot(repository.path, "platform")
    assert reconcile(snapshot, snapshot)["same"] is True
    assert reconcile(snapshot, None)["verdict"] == "TARGET_MISSING"

    missing = {**snapshot, "rows": [row for row in snapshot["rows"] if row["id"] != "nas-1"]}
    report = reconcile(missing, snapshot)
    assert report["verdict"] == "MISMATCH"
    assert "extra_rows" in report["blocking_findings"]

    renamed = json.loads(json.dumps(snapshot))
    for row in renamed["rows"]:
        if row["id"] == "nas-1":
            row["name"] = "NAS renamed"
    report = reconcile(snapshot, renamed)
    assert "identity_differences" in report["blocking_findings"]
    assert report["checks"]["identity_differences"][0]["field"] == "name"


def test_import_snapshot_rejects_a_malformed_snapshot_before_touching_the_target():
    base = {
        "contract_version": "storage-source-migration-v1",
        "scope": "platform",
        "backend": "sqlite",
        "rows": [],
        "counts": {"sources": 0},
        "content_digest": "0" * 64,
    }
    with pytest.raises(StorageSourceMigrationError) as contract:
        import_snapshot(None, {**base, "contract_version": "unknown"})
    assert contract.value.code == "STORAGE_SOURCE_MIGRATION_CONTRACT_MISMATCH"
    with pytest.raises(StorageSourceMigrationError) as scope:
        import_snapshot(None, {**base, "scope": ""})
    assert scope.value.code == "STORAGE_SOURCE_MIGRATION_SCOPE_MISSING"
    row = {
        "id": "nas-1",
        "name": "NAS",
        "type": "remote",
        "config": {},
        "secret_ref": "",
        "runtime_revision": 1,
        "enabled": True,
        "is_default": True,
        "health_status": "UNKNOWN",
        "health_message": "",
        "last_checked_at": None,
        "created_at": "",
        "updated_at": "",
    }
    with pytest.raises(StorageSourceMigrationError) as duplicate:
        import_snapshot(None, {**base, "rows": [row, dict(row)]})
    assert duplicate.value.code == "STORAGE_SOURCE_MIGRATION_DUPLICATE_ID"
    second = {**row, "id": "nas-2", "name": "NAS 2"}
    with pytest.raises(StorageSourceMigrationError) as defaults:
        import_snapshot(None, {**base, "rows": [row, second]})
    assert defaults.value.code == "STORAGE_SOURCE_MIGRATION_DUPLICATE_DEFAULT"


def test_cross_domain_delete_stays_blocked_without_admitted_evidence():
    repository = PostgresStorageSourceRepository(
        "postgresql://example.invalid/db", "platform"
    )
    # Refused before any connection: the capability gap is declared, not attempted.
    with pytest.raises(StorageSourceOperationBlocked) as blocked:
        repository.delete("nas-1")
    assert blocked.value.code == "STORAGE_SOURCE_DELETE_REQUIRES_CROSS_DOMAIN_EVIDENCE"
    assert repository.unsupported_operations() == ("delete",)
    assert "example.invalid" not in repr(repository)

    admitted = PostgresStorageSourceRepository(
        "postgresql://example.invalid/db", "platform", allow_cross_domain_delete=True
    )
    assert admitted.unsupported_operations() == ()
    assert "delete" in admitted.capabilities()


def test_postgres_provider_refuses_an_admission_for_another_scope():
    repository = PostgresStorageSourceRepository(
        "postgresql://example.invalid/db",
        "platform",
        admission={
            "contract_version": CONTRACT_VERSION,
            "scope": "another-deployment",
            "authoritative_provider": "postgresql",
            "revoked_at": None,
        },
    )
    with pytest.raises(StorageSourceAdmissionRequired) as mismatch:
        repository.ensure_ready()
    assert mismatch.value.code == "STORAGE_SOURCE_POSTGRES_ADMISSION_SCOPE_MISMATCH"


def test_conflict_error_is_a_value_error_for_the_existing_api_contract():
    assert issubclass(StorageSourceConflictError, ValueError)

def test_switch_lock_is_reentrant_and_excludes_other_threads(tmp_path):
    """The cutover switch and the writers share one mutex."""
    import threading

    from platform_core.storage.source_repository import storage_source_switch_lock

    path = tmp_path / "storage" / "storage_sources.sqlite3"
    path.parent.mkdir(parents=True)
    seen = {}

    with storage_source_switch_lock(path):
        # Re-entrant inside the owning thread (writer -> writer).
        with storage_source_switch_lock(path):
            seen["nested"] = True

        def contender():
            with storage_source_switch_lock(path, timeout=0.2):
                seen["acquired"] = True

        thread = threading.Thread(target=contender)
        thread.start()
        thread.join()
    assert seen["nested"] is True
    assert "acquired" not in seen


def test_switch_lock_reports_a_cutover_in_progress(tmp_path):
    import threading

    from platform_core.storage.source_repository import storage_source_switch_lock

    path = tmp_path / "storage" / "storage_sources.sqlite3"
    path.parent.mkdir(parents=True)
    outcome = {}

    with storage_source_switch_lock(path):
        def contender():
            try:
                with storage_source_switch_lock(path, timeout=0.2):
                    outcome["acquired"] = True
            except Exception as error:  # noqa: BLE001 - assert the stable code
                outcome["code"] = getattr(error, "code", type(error).__name__)

        thread = threading.Thread(target=contender)
        thread.start()
        thread.join()
    assert outcome.get("code") == "STORAGE_SOURCE_CUTOVER_IN_PROGRESS"


class _IdleConnection:
    """Minimal psycopg-like connection that reports an idle transaction."""

    def __init__(self):
        from psycopg.pq import TransactionStatus

        self.info = type("Info", (), {"transaction_status": TransactionStatus.IDLE})()


def test_admission_refuses_an_already_active_record(tmp_path):
    """A second switch cannot be admitted while one is published."""
    from platform_core.storage_source_cutover import admit_cutover

    repository = _repository(tmp_path)
    _admission(admission_record_path(repository.path))
    with pytest.raises(Exception) as admitted:
        admit_cutover(
            _IdleConnection(), repository.path, operator="ops", reason="second"
        )
    assert getattr(admitted.value, "code", "") == "STORAGE_SOURCE_CUTOVER_ALREADY_ADMITTED"


def test_admission_refuses_a_busy_caller_transaction(tmp_path):
    """An open caller transaction must not be adopted as a savepoint."""
    from psycopg.pq import TransactionStatus

    from platform_core.storage_source_cutover import admit_cutover

    repository = _repository(tmp_path)

    class _Busy:
        info = type("Info", (), {"transaction_status": TransactionStatus.INTRANS})()

    with pytest.raises(Exception) as busy:
        admit_cutover(_Busy(), repository.path, operator="ops", reason="busy")
    assert getattr(busy.value, "code", "") == "STORAGE_SOURCE_CUTOVER_TRANSACTION_BUSY"
    # Nothing was published: the marker is gone and SQLite still owns writes.
    assert not admission_transition_path(
        admission_record_path(repository.path)
    ).exists()
    assert repository.update("default_local", {"name": "Local still"}).name == "Local still"


def test_unknown_admission_provider_is_never_treated_as_sqlite(tmp_path):
    """A missing/unknown provider is invalid evidence, not "assume SQLite"."""
    from platform_core.storage.source_repository import (
        load_storage_source_admission_record,
    )
    from platform_core.storage_source_cutover import STATE_INCONSISTENT, cutover_status

    repository = _repository(tmp_path)
    record_path = admission_record_path(repository.path)
    for provider in ("mysql", "", None):
        record_path.parent.mkdir(parents=True, exist_ok=True)
        record_path.write_text(
            json.dumps(
                {
                    "contract_version": CONTRACT_VERSION,
                    "admission_id": "admit-unknown",
                    "scope": "platform",
                    "authoritative_provider": provider,
                    "writer_generation": 1,
                    "admitted_at": "2026-11-26T00:00:00+00:00",
                    "revoked_at": None,
                }
            ),
            encoding="utf-8",
        )
        with pytest.raises(StorageSourceAdmissionRequired) as invalid:
            load_storage_source_admission_record(record_path)
        assert invalid.value.code == "STORAGE_SOURCE_ADMISSION_RECORD_INVALID"
        # Every writer refuses, and the status reports the broken state.
        with pytest.raises(StorageSourceAdmissionRequired):
            repository.create({"id": "nas-x", "name": "NAS X", "type": "remote"})
        with pytest.raises(StorageSourceAdmissionRequired):
            StorageSourceRepository(repository.path)
        status = cutover_status(repository.path)
        assert status["state"] == STATE_INCONSISTENT
        assert status["sqlite_writable"] is False and status["postgres_writable"] is False
        assert status["admission_error"]["code"] == "STORAGE_SOURCE_ADMISSION_RECORD_INVALID"

    # A legal explicit SQLite authority record still allows writes.
    record_path.write_text(
        json.dumps(
            {
                "contract_version": CONTRACT_VERSION,
                "admission_id": "rollback-1",
                "scope": "platform",
                "authoritative_provider": "sqlite",
                "writer_generation": 3,
                "revoked_at": None,
            }
        ),
        encoding="utf-8",
    )
    assert repository.update("default_local", {"name": "Local ok"}).name == "Local ok"


def test_cutover_status_never_guesses_unknown_states(tmp_path):
    from platform_core.storage_source_cutover import (
        STATE_INCONSISTENT,
        STATE_POSTGRES,
        STATE_SQLITE,
        cutover_status,
    )

    repository = _repository(tmp_path)
    record_path = admission_record_path(repository.path)
    marker_path = admission_transition_path(record_path)
    assert cutover_status(repository.path)["state"] == STATE_SQLITE

    _admission(record_path)
    assert cutover_status(repository.path)["state"] == STATE_POSTGRES
    marker_path.write_text(
        json.dumps(
            {
                "contract_version": "storage-source-cutover-transition-v1",
                "operation_id": "op",
                "scope": "platform",
                "phase": "POSTGRES_ACTIVE",
                "writer_generation": 1,
            }
        ),
        encoding="utf-8",
    )
    status = cutover_status(repository.path)
    assert status["state"] == STATE_INCONSISTENT
    assert status["sqlite_writable"] is False and status["postgres_writable"] is False

    marker_path.write_text("{broken", encoding="utf-8")
    with pytest.raises(Exception) as invalid:
        cutover_status(repository.path)
    assert getattr(invalid.value, "code", "") == "STORAGE_SOURCE_CUTOVER_TRANSITION_INVALID"

def test_delete_requires_complete_cross_domain_evidence():
    """A zero reference count alone never authorises deleting a source."""
    from platform_core.storage_source_postgres_store import (
        PostgresStorageSourceRepository,
    )

    repository = PostgresStorageSourceRepository(
        "postgresql://example.invalid/db", "platform", allow_cross_domain_delete=True
    )
    assert repository.unsupported_operations() == ()
    identity = {
        "scope": "platform",
        "source_id": "nas-1",
        "config_digest": "0" * 64,
        "operation_id": "op-1",
        "checked_at": "2026-11-26T00:00:00+00:00",
    }

    # No evidence at all.
    with pytest.raises(Exception) as required:
        repository._require_delete_evidence(None)
    assert getattr(required.value, "code", "") == "STORAGE_SOURCE_DELETE_EVIDENCE_REQUIRED"

    # Incomplete evidence (no identity binding).
    with pytest.raises(Exception) as incomplete:
        repository._require_delete_evidence({"source_revision": 1})
    assert getattr(incomplete.value, "code", "") == "STORAGE_SOURCE_DELETE_EVIDENCE_INCOMPLETE"

    # Wrong scope is refused before anything else.
    with pytest.raises(Exception) as scope:
        repository._require_delete_evidence(
            {
                **identity,
                "scope": "another-deployment",
                "source_revision": 1,
                "material_references": 0,
                "artifact_references": 0,
                "physical_retirement": {"status": "RETIRED", "proof": "x"},
            }
        )
    assert getattr(scope.value, "code", "") == "STORAGE_SOURCE_DELETE_EVIDENCE_STALE"

    # Still referenced by another owner.
    with pytest.raises(Exception) as referenced:
        repository._require_delete_evidence(
            {
                **identity,
                "source_revision": 1,
                "material_references": 0,
                "artifact_references": 2,
                "physical_retirement": {"status": "RETIRED", "proof": "x"},
            }
        )
    assert getattr(referenced.value, "code", "") == "STORAGE_SOURCE_DELETE_STILL_REFERENCED"

    # Objects not proven retired (zero references is not proof).
    with pytest.raises(Exception) as unproven:
        repository._require_delete_evidence(
            {
                **identity,
                "source_revision": 1,
                "material_references": 0,
                "artifact_references": 0,
                "physical_retirement": {"status": "NOT_RETIRED", "proof": ""},
            }
        )
    assert getattr(unproven.value, "code", "") == "STORAGE_SOURCE_DELETE_RETIREMENT_UNPROVEN"

    # Complete, identity-bound evidence is accepted.
    evidence = repository._require_delete_evidence(
        {
            **identity,
            "source_revision": 3,
            "material_references": 0,
            "artifact_references": 0,
            "physical_retirement": {"status": "RETIRED", "proof": "s3://bucket/empty@digest"},
        }
    )
    assert evidence["source_revision"] == 3 and evidence["source_id"] == "nas-1"

def test_delete_evidence_binds_the_source_identity_and_scope(tmp_path):
    """Evidence from another source/scope can never authorise this delete."""
    from platform_core.material_repository import MaterialRepository
    from platform_core.storage.source_repository import StorageSource
    from platform_core.storage_source_delete_evidence import (
        DeleteEvidenceError,
        collect_delete_evidence,
    )

    source = StorageSource(
        id="nas-1", name="NAS", type="remote",
        config={"root": "/mnt/nas"}, secret_ref="secret://s/1", runtime_revision=2,
    )
    projects = tmp_path / "projects"
    (projects / "p1").mkdir(parents=True)
    MaterialRepository(projects / "p1").upsert(
        {"id": "m1", "storage_source_id": "nas-1", "object_key": "uploads/m1.jpg", "filename": "m1.jpg"}
    )
    retirement = lambda _source: {"status": "RETIRED", "proof": "s3://b/empty@sha"}

    evidence = collect_delete_evidence(
        source,
        scope="platform",
        projects_root=projects,
        project_ids=["p1"],
        artifact_reference_counter=lambda _source: 0,
        physical_retirement_probe=retirement,
    )
    assert evidence["scope"] == "platform"
    assert evidence["source_id"] == "nas-1"
    assert len(evidence["config_digest"]) == 64
    assert evidence["operation_id"]
    assert evidence["material_references"] == 1

    # The collector records the requested scope verbatim; the provider is the
    # authority that refuses evidence collected for another scope (covered by
    # test_delete_requires_complete_cross_domain_evidence).
    other_scope = collect_delete_evidence(
        source,
        scope="another-deployment",
        projects_root=projects,
        project_ids=["p1"],
        artifact_reference_counter=lambda _source: 0,
        physical_retirement_probe=retirement,
    )
    assert other_scope["scope"] == "another-deployment"

    # An unproven project scope is not "zero references": without a root or an
    # explicit id list the collector refuses instead of assuming no projects.
    with pytest.raises(DeleteEvidenceError) as empty:
        collect_delete_evidence(
            source,
            artifact_reference_counter=lambda _source: 0,
            physical_retirement_probe=retirement,
        )
    assert empty.value.code == "STORAGE_SOURCE_DELETE_EVIDENCE_INCOMPLETE"

    # A project list naming a directory that does not exist is incomplete.
    with pytest.raises(DeleteEvidenceError) as missing:
        collect_delete_evidence(
            source,
            projects_root=projects,
            project_ids=["p1", "ghost"],
            artifact_reference_counter=lambda _source: 0,
            physical_retirement_probe=retirement,
        )
    assert missing.value.code == "STORAGE_SOURCE_DELETE_EVIDENCE_INCOMPLETE"

    # The collected digest is exactly the provider-side configuration identity.
    from platform_core.storage.source_repository import storage_source_config_digest

    assert evidence["config_digest"] == storage_source_config_digest(source)
    changed = StorageSource(
        id="nas-1", name="NAS", type="remote",
        config={"root": "/mnt/other"}, secret_ref="secret://s/1", runtime_revision=2,
    )
    assert storage_source_config_digest(changed) != evidence["config_digest"]
