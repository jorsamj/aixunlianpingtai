"""Read-only report lookups must not hydrate the full algorithm catalog."""

from platform_core.algorithm_sql_store import AlgorithmSqlStore


def test_training_version_refs_use_existing_index_without_hydrating_payload(monkeypatch, tmp_path):
    store = AlgorithmSqlStore(tmp_path / "project" / "algorithms.json")
    store.create_algorithm({"id": "a", "name": "A"})
    store.create_algorithm({"id": "b", "name": "B"})
    store.attach_version("a", {"id": "va", "job_id": "training-1", "evaluation": {"large": "x" * 500_000}})
    store.attach_version("b", {"id": "vb", "job_id": "training-2", "label_contract": {"large": "y" * 500_000}})

    def reject_hydration(*_args, **_kwargs):
        raise AssertionError("index lookup hydrated a version payload")

    monkeypatch.setattr(store, "_version_from_row", reject_hydration)
    assert store.training_version_refs("training-1") == [("a", "va")]
    assert store.training_version_refs("no-such-task") == []


def test_report_reads_only_indexed_owner_and_preserves_frozen_identity(monkeypatch, tmp_path):
    from tests.api.test_training_metric_credibility_report import _setup_report

    platform = _setup_report(monkeypatch, tmp_path)
    catalog = tmp_path / "project" / "algorithms.sqlite3"
    catalog.touch()
    monkeypatch.setattr(AlgorithmSqlStore, "training_version_refs", lambda self, task: [("a", "va")])
    reads = []

    def read_algorithms(_project, *, algorithm_id=None):
        reads.append(algorithm_id)
        assert algorithm_id is not None, "report unexpectedly scanned all algorithms"
        return [{"id": "a", "name": "A", "versions": [{"id": "va", "job_id": "training-1"}]}]

    monkeypatch.setattr(platform, "list_algorithms_internal", read_algorithms)
    report = platform.v44_training_report("p", "training-1")["report"]
    assert report["identity"]["algorithm_id"] == "a"
    assert report["identity"]["version_id"] == "va"
    assert reads == ["a"]


def test_report_rejects_ambiguous_indexed_job_owners(monkeypatch, tmp_path):
    import pytest
    from fastapi import HTTPException
    from tests.api.test_training_metric_credibility_report import _setup_report

    platform = _setup_report(monkeypatch, tmp_path)
    (tmp_path / "project" / "algorithms.sqlite3").touch()
    monkeypatch.setattr(AlgorithmSqlStore, "training_version_refs", lambda self, task: [("a", "va"), ("b", "vb")])
    monkeypatch.setattr(
        platform, "list_algorithms_internal",
        lambda _project, *, algorithm_id=None: [{"id": algorithm_id, "versions": [
            {"id": "v" + algorithm_id, "job_id": "training-1"}
        ]}],
    )
    with pytest.raises(HTTPException) as error:
        platform.v44_training_report("p", "training-1")
    assert error.value.status_code == 409
    assert "REPORT_IDENTITY_AMBIGUOUS" in str(error.value.detail)


def test_report_keeps_legacy_catalog_fallback_when_index_has_no_match(monkeypatch, tmp_path):
    from tests.api.test_training_metric_credibility_report import _setup_report

    platform = _setup_report(monkeypatch, tmp_path)
    (tmp_path / "project" / "algorithms.sqlite3").touch()
    monkeypatch.setattr(AlgorithmSqlStore, "training_version_refs", lambda self, task: [])
    reads = []

    def read_algorithms(_project, *, algorithm_id=None):
        reads.append(algorithm_id)
        return [{"id": "legacy", "versions": [{
            "id": "legacy-version", "training_lineage": {"task_id": "training-1"},
        }]}]

    monkeypatch.setattr(platform, "list_algorithms_internal", read_algorithms)
    report = platform.v44_training_report("p", "training-1")["report"]
    assert report["identity"]["version_id"] == "legacy-version"
    assert reads == [None]
