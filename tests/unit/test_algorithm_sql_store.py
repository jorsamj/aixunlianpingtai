import json
from pathlib import Path

from platform_core.algorithms import (
    attach_version,
    create_algorithm,
    delete_algorithm,
    list_algorithms,
    save_algorithms,
    update_algorithm,
)
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
                {"analysisId": "analysis-a", "analysisName": "视觉分析 A", "analysisType": "vision"},
                {"analysisId": "analysis-b", "analysisName": "视觉分析 B", "analysisType": "vision"},
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
        analyses_by_product={"product-100": [{"analysisId": "analysis-a", "analysisName": "视觉分析 A"}]},
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
        analyses_by_product={"product-200": [{"analysisId": "analysis-1", "analysisName": "视觉"}]},
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
            analyses_by_product={"product-200": [{"analysisId": "analysis-1", "analysisName": "视觉"}]},
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
            "created_at": "2026-09-19T00:10:00Z",
        },
    )
    persisted = list_algorithms(json_path)[0]["versions"][0]
    assert persisted["dataset_revision_id"] == "a" * 64
    assert persisted["training_lineage"] == lineage
    assert persisted["evaluation"] == evaluation
    assert persisted["iteration_decision"] == iteration_decision
