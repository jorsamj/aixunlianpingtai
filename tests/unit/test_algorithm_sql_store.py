import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from platform_core.algorithms import (
    attach_version,
    create_algorithm,
    delete_algorithm,
    list_algorithms,
    save_algorithms,
    update_algorithm,
)
import platform_core.algorithm_sql_store as algorithm_sql_store_module
from platform_core.algorithm_sql_store import AlgorithmSqlStore
from platform_core.external_algorithm_platform import mirror_products_to_algorithms


def _legacy_rows():
    return [
        {
            "id": "legacy-local",
            "name": "原有烟火算法",
            "remark": "历史算法",
            "industry": "消防安全",
            "algorithm_type": "yolo_ultralytics",
            "current_version_id": "legacy-v1",
            "version_operations": [{"type": "create", "at": "2026-09-01T00:00:00Z"}],
            "versions": [
                {
                    "id": "legacy-v1",
                    "version_name": "20260901000000",
                    "framework": "ultralytics",
                    "training_status": "SUCCEEDED",
                    "artifact_verified": True,
                    "trainable": True,
                    "stored_path": "/models/legacy-v1/best.pt",
                    "custom_legacy_metric": 0.88,
                }
            ],
            "custom_legacy_field": "must-survive",
            "created_at": "2026-09-01T00:00:00Z",
            "updated_at": "2026-09-01T01:00:00Z",
        }
    ]


class _ConnectionWithoutJournalMode:
    def __init__(self, connection):
        self._connection = connection

    @property
    def row_factory(self):
        return self._connection.row_factory

    @row_factory.setter
    def row_factory(self, value):
        self._connection.row_factory = value

    def execute(self, sql, *args, **kwargs):
        if "journal_mode" in str(sql).lower():
            raise AssertionError("ordinary AlgorithmSqlStore._connect() must not touch journal_mode")
        return self._connection.execute(sql, *args, **kwargs)

    def close(self):
        return self._connection.close()

    def __getattr__(self, name):
        return getattr(self._connection, name)


def test_ordinary_connection_does_not_negotiate_journal_mode(tmp_path: Path, monkeypatch):
    project = tmp_path / "projects" / "p-connect"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")
    store = AlgorithmSqlStore(json_path)
    real_connect = sqlite3.connect

    def guarded_connect(*args, **kwargs):
        return _ConnectionWithoutJournalMode(real_connect(*args, **kwargs))

    monkeypatch.setattr(algorithm_sql_store_module.sqlite3, "connect", guarded_connect)

    connection = store._connect()
    try:
        assert int(connection.execute("PRAGMA busy_timeout").fetchone()[0]) == 30000
    finally:
        connection.close()


def test_ready_store_skips_repeated_schema_bootstrap(tmp_path: Path, monkeypatch):
    project = tmp_path / "projects" / "p-ready"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")

    AlgorithmSqlStore(json_path).ensure_ready()

    reopened = AlgorithmSqlStore(json_path)

    def forbidden_schema(_connection):
        raise AssertionError("ready algorithm store must not rerun schema bootstrap")

    monkeypatch.setattr(reopened, "_ensure_schema", forbidden_schema)

    reopened.ensure_ready()


def test_ready_store_fast_path_does_not_take_init_file_lock(tmp_path: Path, monkeypatch):
    project = tmp_path / "projects" / "p-ready-fast"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")

    AlgorithmSqlStore(json_path).ensure_ready()
    reopened = AlgorithmSqlStore(json_path)

    class ForbiddenInitLock:
        def __init__(self, *args, **kwargs):
            raise AssertionError("ready algorithm store must bypass init FileLock")

    monkeypatch.setattr(algorithm_sql_store_module, "FileLock", ForbiddenInitLock)

    reopened.ensure_ready()


def test_algorithm_list_prefetches_versions_and_analyses_without_n_plus_one(
    tmp_path: Path, monkeypatch
):
    project = tmp_path / "projects" / "p-prefetch"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")
    store = AlgorithmSqlStore(json_path)
    store.ensure_ready()
    store.replace_all([
        {
            "id": f"algo-{index}",
            "name": f"算法 {index}",
            "source_type": "EXTERNAL",
            "provider_type": "CHANG_LIAN",
            "external_product_id": f"product-{index}",
            "external_analysis_id": f"analysis-{index}",
            "external_analyses": [{
                "analysis_id": f"analysis-{index}",
                "analysis_name": f"分析 {index}",
                "analysis_type": "1",
                "status": "1",
            }],
            "versions": [{
                "id": f"version-{index}",
                "task_id": f"task-{index}",
                "training_status": "SUCCEEDED",
                "artifact_verified": True,
                "trainable": True,
                "framework": "ultralytics",
            }],
        }
        for index in range(5)
    ])

    statements = []
    real_connect = store._connect

    def traced_connect():
        connection = real_connect()
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(store, "_connect", traced_connect)

    rows = store.read_all()

    assert len(rows) == 5
    version_selects = [
        statement for statement in statements
        if "FROM algorithm_versions" in statement
    ]
    analysis_selects = [
        statement for statement in statements
        if "FROM algorithm_external_analyses" in statement
    ]
    assert len(version_selects) == 1
    assert len(analysis_selects) == 1
    assert all(len(row["versions"]) == 1 for row in rows)
    assert all(len(row["external_analyses"]) == 1 for row in rows)


def test_schema_v1_store_upgrades_indexes_without_rewriting_data(tmp_path: Path):
    project = tmp_path / "projects" / "p-schema-v2"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")

    store = AlgorithmSqlStore(json_path)
    store.ensure_ready()
    store.create_algorithm({
        "id": "algorithm-preserved",
        "name": "保留算法",
        "versions": [],
        "current_version_id": None,
    })

    with sqlite3.connect(store.db_path) as connection:
        connection.execute("DROP INDEX IF EXISTS idx_algorithms_project_sort")
        connection.execute("DROP INDEX IF EXISTS idx_analyses_algorithm_sort")
        connection.execute(
            "UPDATE algorithm_store_meta SET value='1' WHERE key='schema_version'"
        )
        connection.commit()

    reopened = AlgorithmSqlStore(json_path)
    reopened.ensure_ready()

    with sqlite3.connect(reopened.db_path) as connection:
        schema_version = connection.execute(
            "SELECT value FROM algorithm_store_meta WHERE key='schema_version'"
        ).fetchone()[0]
        indexes = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }

    assert schema_version == "2"
    assert "idx_algorithms_project_sort" in indexes
    assert "idx_analyses_algorithm_sort" in indexes
    assert reopened.read_one("algorithm-preserved")["name"] == "保留算法"


def test_concurrent_attach_version_keeps_both_versions_after_store_initialization(tmp_path: Path):
    project = tmp_path / "projects" / "p-concurrent-attach"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")

    store = AlgorithmSqlStore(json_path)
    store.ensure_ready()
    store.create_algorithm({
        "id": "algorithm-concurrent",
        "name": "并发归档算法",
        "remark": "",
        "industry": "测试",
        "algorithm_type": "yolo_ultralytics",
        "versions": [],
        "current_version_id": None,
        "created_at": "2026-09-21T00:00:00Z",
        "updated_at": "2026-09-21T00:00:00Z",
    })

    barrier = threading.Barrier(2)

    def attach(index: int):
        barrier.wait(timeout=2)
        return AlgorithmSqlStore(json_path).attach_version(
            "algorithm-concurrent",
            {
                "id": f"version-task-{index}",
                "task_id": f"task-{index}",
                "training_status": "SUCCEEDED",
                "artifact_verified": True,
                "trainable": True,
                "framework": "ultralytics",
                "finished_at": f"2026-09-21T00:00:0{index}Z",
                "stored_path": f"/models/version-task-{index}/best.pt",
            },
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(attach, index) for index in (1, 2)]
        for future in futures:
            future.result(timeout=5)

    persisted = AlgorithmSqlStore(json_path).read_one("algorithm-concurrent")
    assert persisted is not None
    assert {version["id"] for version in persisted["versions"]} == {
        "version-task-1",
        "version-task-2",
    }


def test_legacy_json_is_migrated_losslessly_and_sql_becomes_source_of_truth(tmp_path: Path):
    project = tmp_path / "projects" / "p1"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text(json.dumps(_legacy_rows(), ensure_ascii=False), encoding="utf-8")

    rows = list_algorithms(json_path)

    assert [row["id"] for row in rows] == ["legacy-local"]
    assert rows[0]["versions"][0]["id"] == "legacy-v1"
    assert rows[0]["versions"][0]["custom_legacy_metric"] == 0.88
    assert rows[0]["custom_legacy_field"] == "must-survive"
    assert (project / "algorithms.sqlite3").exists()
    assert (project / "algorithms.json.pre-sql-migration-backup").exists()

    # After migration, editing the old JSON cannot silently replace SQL data.
    json_path.write_text("[]", encoding="utf-8")
    assert [row["id"] for row in list_algorithms(json_path)] == ["legacy-local"]

    status = AlgorithmSqlStore(json_path).migration_status()
    assert status["backend"] == "sqlite"
    assert status["legacy_json_migrated"] is True
    assert status["algorithm_count"] == 1
    assert status["version_count"] == 1


def test_existing_algorithm_crud_keeps_frontend_shape_on_sql(tmp_path: Path):
    project = tmp_path / "projects" / "p1"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")

    created = create_algorithm(
        json_path,
        {"name": "人员检测", "remark": "demo", "industry": "园区", "algorithm_type": "yolo_ultralytics"},
        "2026-09-17T08:00:00Z",
        algorithm_id="a-new",
    )
    assert created["id"] == "a-new"

    attach_version(
        json_path,
        "a-new",
        {
            "id": "v-new",
            "version_name": "20260917080000",
            "training_status": "SUCCEEDED",
            "artifact_verified": True,
            "trainable": True,
            "framework": "ultralytics",
            "stored_path": "/models/v-new/best.pt",
            "created_at": "2026-09-17T08:10:00Z",
        },
    )
    update_algorithm(
        json_path,
        "a-new",
        {"name": "人员检测升级", "remark": "updated", "industry": "园区", "algorithm_type": "yolo_ultralytics"},
        "2026-09-17T08:20:00Z",
    )

    rows = list_algorithms(json_path)
    assert len(rows) == 1
    assert rows[0]["name"] == "人员检测升级"
    assert rows[0]["current_version_id"] == "v-new"
    assert rows[0]["versions"][0]["id"] == "v-new"

    delete_algorithm(json_path, "a-new")
    assert list_algorithms(json_path) == []


def test_changlian_sync_adds_external_algorithm_without_removing_legacy_local(tmp_path: Path):
    project = tmp_path / "projects" / "p1"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text(json.dumps(_legacy_rows(), ensure_ascii=False), encoding="utf-8")

    # Trigger migration first, matching an upgraded real project.
    assert len(list_algorithms(json_path)) == 1

    result = mirror_products_to_algorithms(
        algorithms_path=json_path,
        products=[{
            "productId": "product-100",
            "productName": "新畅联抽烟检测",
            "productCode": "SMOKE-100",
            "categoryId": "cat-fire",
        }],
        categories=[{"categoryId": "cat-fire", "categoryName": "消防安全"}],
        analyses_by_product={
            "product-100": [
                {"analysisId": "analysis-a", "analysisName": "视觉分析 A", "analysisType": 1, "status": 1},
                {"analysisId": "analysis-b", "analysisName": "视觉分析 B", "analysisType": 1, "status": 1},
            ]
        },
        synced_at="2026-09-17T09:00:00Z",
    )

    assert result["added"] == 1
    rows = list_algorithms(json_path)
    assert {row["id"] for row in rows} >= {"legacy-local"}
    legacy = next(row for row in rows if row["id"] == "legacy-local")
    external = next(row for row in rows if row.get("external_product_id") == "product-100")
    assert legacy["custom_legacy_field"] == "must-survive"
    assert legacy["versions"][0]["id"] == "legacy-v1"
    assert external["source_type"] == "EXTERNAL"
    assert external["provider_type"] == "CHANG_LIAN"
    assert external["external_category_id"] == "cat-fire"
    assert external["external_analysis_ids"] == ["analysis-a", "analysis-b"]

    # A second sync updates the same external row instead of duplicating it.
    mirror_products_to_algorithms(
        algorithms_path=json_path,
        products=[{
            "productId": "product-100",
            "productName": "新畅联抽烟检测（更新）",
            "productCode": "SMOKE-100",
            "categoryId": "cat-fire",
        }],
        categories=[{"categoryId": "cat-fire", "categoryName": "消防安全"}],
        analyses_by_product={"product-100": [{"analysisId": "analysis-a", "analysisName": "视觉分析 A", "analysisType": 1, "status": 1}]},
        synced_at="2026-09-17T09:10:00Z",
    )
    rows = list_algorithms(json_path)
    assert len([row for row in rows if row.get("external_product_id") == "product-100"]) == 1
    assert next(row for row in rows if row.get("external_product_id") == "product-100")["name"] == "新畅联抽烟检测（更新）"


def test_save_algorithms_preserves_replace_semantics_in_sql(tmp_path: Path):
    project = tmp_path / "projects" / "p1"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text(json.dumps(_legacy_rows(), ensure_ascii=False), encoding="utf-8")
    rows = list_algorithms(json_path)
    assert len(rows) == 1

    save_algorithms(json_path, [])
    assert list_algorithms(json_path) == []



def test_external_sync_cannot_overwrite_concurrent_training_version(tmp_path: Path):
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from platform_core.algorithms import attach_version, list_algorithms

    project = tmp_path / "projects" / "p1"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")
    mirror_products_to_algorithms(
        algorithms_path=json_path,
        products=[{"productId": "product-200", "productName": "并发算法", "categoryId": "cat"}],
        categories=[{"categoryId": "cat", "categoryName": "测试"}],
        analyses_by_product={"product-200": [{"analysisId": "analysis-1", "analysisName": "视觉", "analysisType": 1, "status": 1}]},
        synced_at="2026-09-17T10:00:00Z",
    )
    algorithm = next(row for row in list_algorithms(json_path) if row.get("external_product_id") == "product-200")
    barrier = threading.Barrier(2)

    def finish_training():
        barrier.wait(timeout=2)
        attach_version(json_path, algorithm["id"], {
            "id": "concurrent-v1", "task_id": "train-concurrent", "training_status": "SUCCEEDED",
            "artifact_verified": True, "trainable": True, "framework": "ultralytics",
            "finished_at": "2026-09-17T10:01:00Z", "stored_path": "/models/concurrent-v1/best.pt",
        })

    def sync_master():
        barrier.wait(timeout=2)
        mirror_products_to_algorithms(
            algorithms_path=json_path,
            products=[{"productId": "product-200", "productName": "并发算法（更新）", "categoryId": "cat"}],
            categories=[{"categoryId": "cat", "categoryName": "测试"}],
            analyses_by_product={"product-200": [{"analysisId": "analysis-1", "analysisName": "视觉", "analysisType": 1, "status": 1}]},
            synced_at="2026-09-17T10:01:00Z",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(finish_training), executor.submit(sync_master)]
        for future in futures:
            future.result(timeout=5)

    persisted = next(row for row in list_algorithms(json_path) if row["id"] == algorithm["id"])
    assert persisted["name"] == "并发算法（更新）"
    assert persisted["current_version_id"] == "concurrent-v1"
    assert [row["id"] for row in persisted["versions"]] == ["concurrent-v1"]


def test_algorithm_version_training_lineage_survives_sql_round_trip(tmp_path: Path):
    project = tmp_path / "projects" / "p-lineage"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")
    create_algorithm(
        json_path,
        {"name": "溯源算法", "remark": "", "industry": "测试", "algorithm_type": "yolo_ultralytics"},
        "2026-09-19T00:00:00Z",
        algorithm_id="a-lineage",
    )
    lineage = {
        "schema_version": 1, "task_id": "train-lineage",
        "dataset_revision_id": "a" * 64, "snapshot_id": "b" * 64,
        "execution": {"mode": "agent", "worker_id": "agent:node-1", "node_id": "node-1"},
    }
    evaluation = {
        "schema_version": 1, "evaluation_id": "e" * 64, "status": "succeeded",
        "task_id": "train-lineage", "dataset_revision_id": "a" * 64,
        "snapshot_id": "b" * 64, "model_sha256": "c" * 64,
        "metrics": {"metrics/mAP50(B)": 0.88},
        "per_class": [{"class_id": 0, "label": "smoke", "map50": 0.88}],
    }
    feedback_adoption_outcome = {
        "schema_version": 1, "outcome_id": "9" * 64, "status": "comparable",
        "source_version_id": "v-source", "new_version_id": "v-lineage",
        "candidate_set_id": "8" * 64, "adoption_id": "7" * 64,
        "source_evaluation_id": "6" * 64, "new_evaluation_id": "e" * 64,
        "overall_metrics": {
            "metrics/mAP50(B)": {"before": 0.7, "after": 0.88, "delta": 0.18},
        },
        "weak_label_effects": [{"label": "smoke", "direction": "improved"}],
        "descriptive_only": True, "automatic_execution": False,
    }
    iteration_decision = {
        "schema_version": 1, "decision_id": "f" * 64,
        "evaluation_id": "e" * 64, "decision": "continue_training",
        "quality_gate": {
            "metric": "map50", "metric_key": "metrics/mAP50(B)",
            "metric_value": 0.88, "continue_threshold": 0.7, "stop_threshold": 0.9,
        },
        "recommended_actions": ["continue_from_current_version"],
        "automatic_execution": False, "requires_confirmation": True,
    }
    attach_version(
        json_path, "a-lineage",
        {
            "id": "v-lineage", "version_name": "20260919000000",
            "training_status": "SUCCEEDED", "artifact_verified": True, "trainable": True,
            "framework": "ultralytics", "stored_path": "/models/v-lineage/best.pt",
            "dataset_revision_id": "a" * 64, "snapshot_id": "b" * 64,
            "training_lineage": lineage, "evaluation": evaluation,
            "iteration_decision": iteration_decision,
            "feedback_adoption_outcome": feedback_adoption_outcome,
            "created_at": "2026-09-19T00:10:00Z",
        },
    )
    persisted = list_algorithms(json_path)[0]["versions"][0]
    assert persisted["dataset_revision_id"] == "a" * 64
    assert persisted["training_lineage"] == lineage
    assert persisted["evaluation"] == evaluation
    assert persisted["iteration_decision"] == iteration_decision
    assert persisted["feedback_adoption_outcome"] == feedback_adoption_outcome



def test_changlian_trainable_analysis_subset_survives_sql_round_trip(tmp_path: Path):
    project = tmp_path / "projects" / "p-analysis-subset"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")

    result = mirror_products_to_algorithms(
        algorithms_path=json_path,
        products=[{
            "productId": "product-visual",
            "productName": "视觉训练产品",
            "productCode": "VISION-001",
            "categoryId": "cat-visual",
        }],
        categories=[{"categoryId": "cat-visual", "categoryName": "视觉算法"}],
        analyses_by_product={
            "product-visual": [
                {"analysisId": "vision-on", "analysisName": "视觉智能分析", "analysisType": 1, "status": 1},
                {"analysisId": "llm-on", "analysisName": "大模型智能分析", "analysisType": 3, "status": 1},
                {"analysisId": "vision-off", "analysisName": "停用视觉分析", "analysisType": 1, "status": 0},
            ],
        },
        synced_at="2026-09-20T08:00:00Z",
    )

    assert result["added"] == 1
    persisted = next(row for row in list_algorithms(json_path) if row.get("external_product_id") == "product-visual")
    assert persisted["external_analysis_id"] == "vision-on"
    assert persisted["external_analysis_ids"] == ["vision-on"]
    assert [row["analysis_id"] for row in persisted["external_analyses"]] == [
        "vision-on", "llm-on", "vision-off",
    ]
    by_id = {row["analysis_id"]: row for row in persisted["external_analyses"]}
    assert by_id["vision-on"]["status"] == "1"
    assert by_id["llm-on"]["status"] == "1"
    assert by_id["vision-off"]["status"] == "0"
    assert by_id["vision-off"]["active"] is False

    # Exercise replace_all/save_algorithms as well as incremental external sync.
    save_algorithms(json_path, list_algorithms(json_path))
    round_tripped = next(row for row in list_algorithms(json_path) if row.get("external_product_id") == "product-visual")
    assert round_tripped["external_analysis_id"] == "vision-on"
    assert round_tripped["external_analysis_ids"] == ["vision-on"]
    assert [row["analysis_id"] for row in round_tripped["external_analyses"]] == [
        "vision-on", "llm-on", "vision-off",
    ]
    assert next(row for row in round_tripped["external_analyses"] if row["analysis_id"] == "vision-off")["active"] is False



def test_legacy_sql_rows_without_trainable_subset_infer_only_active_visual_ids(tmp_path: Path):
    project = tmp_path / "projects" / "p-analysis-legacy"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")

    # Simulate an older persisted object that predates external_analysis_ids.
    save_algorithms(json_path, [{
        "id": "external-legacy-analysis",
        "name": "旧分析合同",
        "source_type": "EXTERNAL",
        "provider_type": "CHANG_LIAN",
        "external_product_id": "product-legacy",
        "external_analysis_id": "vision-on",
        "external_analyses": [
            {"analysis_id": "vision-on", "analysis_name": "视觉智能分析", "analysis_type": "1", "status": "1"},
            {"analysis_id": "llm-on", "analysis_name": "大模型智能分析", "analysis_type": "3", "status": "1"},
            {"analysis_id": "vision-off", "analysis_name": "停用视觉分析", "analysis_type": "1", "status": "0"},
        ],
        "versions": [],
        "current_version_id": None,
    }])

    persisted = list_algorithms(json_path)[0]
    assert persisted["external_analysis_id"] == "vision-on"
    assert persisted["external_analysis_ids"] == ["vision-on"]
    assert {row["analysis_id"] for row in persisted["external_analyses"]} == {
        "vision-on", "llm-on", "vision-off",
    }


def test_legacy_trainable_id_list_cannot_bypass_missing_status_or_type(tmp_path: Path):
    project = tmp_path / "projects" / "p-analysis-fail-closed"
    project.mkdir(parents=True)
    json_path = project / "algorithms.json"
    json_path.write_text("[]", encoding="utf-8")

    save_algorithms(json_path, [{
        "id": "external-legacy-unverified",
        "name": "旧未验证分析",
        "source_type": "EXTERNAL",
        "provider_type": "CHANG_LIAN",
        "external_product_id": "product-unverified",
        "external_analysis_id": "legacy-visual",
        "external_analysis_ids": ["legacy-visual", "missing-type"],
        "external_analyses": [
            {"analysis_id": "legacy-visual", "analysis_name": "视觉智能分析", "analysis_type": "1"},
            {"analysis_id": "missing-type", "analysis_name": "视觉智能分析", "status": "1"},
        ],
        "versions": [],
        "current_version_id": None,
    }])

    persisted = list_algorithms(json_path)[0]
    assert persisted["external_analysis_ids"] == []
    by_id = {row["analysis_id"]: row for row in persisted["external_analyses"]}
    assert by_id["legacy-visual"]["active"] is False
    assert by_id["missing-type"]["status"] == "1"
