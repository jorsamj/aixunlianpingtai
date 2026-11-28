from __future__ import annotations

import copy
import hashlib
import json

import pytest

from platform_core.algorithm_shadow import (
    AlgorithmShadowError,
    _digest,
    _snapshot_body,
    export_snapshot,
    load_snapshot,
    reconcile,
    validate_snapshot,
    write_snapshot,
)
from platform_core.algorithm_sql_store import AlgorithmSqlStore


def _rows():
    return [{
        "id": "algo-1",
        "name": "烟火算法",
        "remark": "legacy",
        "algorithm_type": "yolo_ultralytics",
        "current_version_id": "v1",
        "custom_legacy_field": "must-survive",
        "versions": [{
            "id": "v1",
            "version_name": "20260101000000",
            "training_status": "SUCCEEDED",
            "training_lineage": {"task_id": "train-1"},
            "custom_version_field": {"x": 1},
        }],
        "external_analyses": [{"analysis_id": "analysis-1", "analysis_name": "A"}],
    }]


def _store(tmp_path):
    store = AlgorithmSqlStore(tmp_path / "project" / "algorithms.json")
    store.replace_all(_rows())
    return store


def test_snapshot_is_repeatable_read_only_and_preserves_unknown_fields(tmp_path):
    store = _store(tmp_path)
    source_bytes = store.db_path.read_bytes()
    first = export_snapshot(store)
    second = export_snapshot(store)
    assert first["algorithm_revision"] == second["algorithm_revision"]
    assert first["snapshot_digest"] == second["snapshot_digest"]
    assert first["counts"] == {"algorithms": 1, "versions": 1, "analyses": 1}
    algorithm = first["tables"]["algorithms"][0]
    assert json.loads(algorithm["payload_json"])["custom_legacy_field"] == "must-survive"
    version = first["tables"]["versions"][0]
    version_payload = json.loads(version["payload_json"])
    assert version_payload["custom_version_field"] == {"x": 1}
    assert version["training_job_id"] is None
    assert store.db_path.read_bytes() == source_bytes
    destination = tmp_path / "snapshot.json"
    write_snapshot(first, destination)
    assert load_snapshot(destination)["snapshot_digest"] == first["snapshot_digest"]


def test_empty_project_snapshot_and_missing_source_error(tmp_path):
    store = AlgorithmSqlStore(tmp_path / "empty" / "algorithms.json")
    store.ensure_ready()
    snapshot = export_snapshot(store)
    assert snapshot["counts"] == {"algorithms": 0, "versions": 0, "analyses": 0}
    missing = AlgorithmSqlStore(tmp_path / "missing" / "algorithms.json")
    with pytest.raises(AlgorithmShadowError) as error:
        export_snapshot(missing)
    assert error.value.code == "ALGORITHM_SHADOW_SOURCE_MISSING"


def test_reconcile_same_digest_missing_extra_changed_and_revision(tmp_path):
    store = _store(tmp_path)
    source = export_snapshot(store)
    shadow = copy.deepcopy(source)
    assert reconcile(source, shadow)["same"] is True
    assert reconcile(source, None)["reason"] == "SHADOW_MISSING"

    changed = copy.deepcopy(source)
    changed["tables"]["algorithms"][0]["name"] = "changed"
    changed["snapshot_digest"] = _digest(_snapshot_body(
        changed["project_id"], changed["algorithm_revision"], changed["tables"]))
    result = reconcile(source, changed)
    assert result["same"] is False
    assert result["reason"] == "SNAPSHOT_DIGEST_MISMATCH"

    shadow["tables"]["algorithms"][0]["name"] = "shadow-only"
    shadow["snapshot_digest"] = _digest(_snapshot_body(
        shadow["project_id"], shadow["algorithm_revision"], shadow["tables"]))
    result = reconcile(source, shadow)
    assert result["same"] is False
    assert result["reason"] == "SNAPSHOT_DIGEST_MISMATCH"

    newer = copy.deepcopy(source)
    newer["algorithm_revision"] = source["algorithm_revision"] + 1
    newer["snapshot_digest"] = _digest(_snapshot_body(
        newer["project_id"], newer["algorithm_revision"], newer["tables"]))
    assert reconcile(source, newer)["reason"] == "SOURCE_REVISION_CHANGED"


def test_snapshot_validator_rejects_tampering_and_bad_contracts(tmp_path):
    source = export_snapshot(_store(tmp_path))
    for mutate in (
        lambda value: value["tables"]["algorithms"][0].update(name="tampered"),
        lambda value: value.update(algorithm_revision=source["algorithm_revision"] + 1),
        lambda value: value["counts"].update(algorithms=99),
        lambda value: value.update(contract_version="unknown"),
        lambda value: value["tables"]["algorithms"].append(dict(value["tables"]["algorithms"][0])),
        lambda value: value["tables"]["versions"].append({**value["tables"]["versions"][0], "id": "v2", "algorithm_id": "missing"}),
    ):
        tampered = copy.deepcopy(source)
        mutate(tampered)
        with pytest.raises(AlgorithmShadowError):
            validate_snapshot(tampered)
    validate_snapshot(source)


def test_snapshot_digest_detects_table_row_changes(tmp_path):
    store = _store(tmp_path)
    before = export_snapshot(store)
    store.patch_algorithm("algo-1", {"name": "renamed"})
    after = export_snapshot(store)
    assert before["algorithm_revision"] != after["algorithm_revision"]
    assert before["snapshot_digest"] != after["snapshot_digest"]
    assert after["tables"]["algorithms"][0]["name"] == "renamed"
