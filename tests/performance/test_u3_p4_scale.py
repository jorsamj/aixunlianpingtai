"""P4-A U3 scale measurement and provider differential (opt-in, synthetic only).

Run locally at a small scale:
    SCALE_MATERIALS=2000 SCALE_GT=400 RUN_U3_P4_SCALE=1 \
        python -m pytest -q tests/performance/test_u3_p4_scale.py -s

The 200k run is intended for the explicit GitHub workflow, never for every push.
"""
from __future__ import annotations

import importlib.util
import json
import os
import pathlib
import platform
import sqlite3
import statistics
import time
from dataclasses import replace

import pytest


RUN = os.environ.get("RUN_U3_P4_SCALE") == "1"
if not RUN:
    pytest.skip(
        "set RUN_U3_P4_SCALE=1 for the isolated U3 P4 scale measurement",
        allow_module_level=True,
    )

psycopg = pytest.importorskip("psycopg")
_EXTERNAL_DSN = os.environ.get("MC_TEST_POSTGRES_DSN", "").strip()
pgserver = None if _EXTERNAL_DSN else pytest.importorskip("pgserver")

os.environ.setdefault("SCALE_MATERIALS", "200000")
os.environ.setdefault("SCALE_GT", "40000")

_BASELINE_PATH = pathlib.Path(__file__).with_name("test_scale_200k_baseline.py")
_SPEC = importlib.util.spec_from_file_location("_p4_scale_baseline", _BASELINE_PATH)
baseline = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(baseline)

from fastapi import FastAPI
from fastapi.testclient import TestClient

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
from platform_core.training_material_business_read import (
    BusinessFilter,
    BusinessQuery,
    BusinessReadProvider,
)
from platform_core.training_material_picker_api import training_material_picker_router
from platform_core.training_material_picker_read import (
    PickerFilter,
    PickerQuery,
    PostgresPickerReadProvider,
    SQLitePickerReadProvider,
    sqlite_owner_revision_source,
)
from platform_core.training_material_usage import TrainingMaterialUsage
from platform_core.u3_incremental_sync import synchronize_project
from platform_core.u3_shadow import (
    ensure_schema,
    export_project_snapshot,
    import_project_snapshot,
    read_target_snapshot,
    reconcile,
)

RESULT: dict = {"layers": {}, "matches": []}


def _percentile(values, quantile):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * quantile))))
    return ordered[index]


def _measure(fn, *, samples=7, warmup=1):
    for _ in range(warmup):
        fn()
    took = []
    result = None
    for _ in range(samples):
        began = time.perf_counter()
        result = fn()
        took.append((time.perf_counter() - began) * 1000)
    return {
        "p50_ms": round(statistics.median(took), 2),
        "p95_ms": round(_percentile(took, 0.95), 2),
        "samples": samples,
    }, result


def _ids(page):
    return [item.material.id for item in page.items]


def _roles(page):
    return [(item.material.id, item.sample_role, item.history_state) for item in page.items]


def _enrich(world, project_id, algorithm_id):
    repository: MaterialRepository = world["repository"]
    annotations: AnnotationRepository = world["annotations"]
    pool = world["negative_pool"]
    category = pool.category(name="p4-fire-negative")
    ids = [f"img-{index:06d}" for index in range(0, min(1000, baseline.TOTAL_MATERIALS))]
    for offset in range(0, len(ids), 200):
        pool.members(ids[offset:offset + 200], category_ids=[category["id"]])

    receipts = 0
    for index in range(0, min(100, baseline.TOTAL_GT)):
        image_id = f"img-{index:06d}"
        gt = annotations.get(image_id)
        if not gt:
            continue
        annotations.confirm_task_negatives(
            f"p4-context-{index}",
            [{
                "receipt_id": f"p4-receipt-{index}",
                "image_id": image_id,
                "annotation_version": gt["version"],
                "annotation_hash": gt["content_digest"],
            }],
            "p4-fixture",
        )
        receipts += 1

    usage: TrainingMaterialUsage = world["usage"]
    rows = repository.get_many([f"img-{index:06d}" for index in range(0, 100)])
    if rows:
        usage.record_selected(
            project_id, algorithm_id, "p4-test-reservation",
            {"snapshot_id": "p4-test-snapshot",
             "images": [{"image_id": row["id"], "role": "test",
                         "content_sha256": row["content_sha256"]} for row in rows]},
            source_images=rows,
        )
        usage.record_execution("p4-test-reservation", test_observed=True)

    retired = repository.retire_many(
        [f"img-{baseline.TOTAL_MATERIALS - index:06d}" for index in range(1, 6)],
        task_id="p4-retirement", actor_id="p4-fixture",
    )
    return {"negative_members": len(ids), "confirmations": receipts,
            "test_reservation": len(rows), "retired": retired}


def _pg_fixture(tmp_path):
    external = os.environ.get("MC_TEST_POSTGRES_DSN", "").strip()
    if external:
        return external, tmp_path
    root = pathlib.Path(tmp_path) / "pgdata"

    class External:
        def __init__(self, dsn):
            self._dsn = dsn

        def get_uri(self):
            return self._dsn

        def cleanup(self):
            with psycopg.connect(self._dsn) as connection:
                connection.execute("DROP SCHEMA IF EXISTS w3_material_gt CASCADE")
                connection.commit()

    return pgserver.get_server(root, cleanup_mode="delete"), tmp_path


def test_u3_p4_scale_measurement(tmp_path):
    server, _ = _pg_fixture(tmp_path)
    project_id = baseline.PROJECT
    world = baseline._build_world(pathlib.Path(tmp_path) / "scale")
    enriched = _enrich(world, project_id, baseline.ALGO_ACTIVE)
    project = world["project_path"]

    snapshot = export_project_snapshot(project, project_id)
    with psycopg.connect(server.get_uri()) as connection:
        ensure_schema(connection)
        import_project_snapshot(connection, snapshot)
        sqlite_picker = SQLitePickerReadProvider(project, project_id=project_id)
        postgres_picker = PostgresPickerReadProvider.from_dsn(
            server.get_uri(),
            owner_revisions=sqlite_owner_revision_source(project, project_id),
        )
        sqlite_business = BusinessReadProvider(
            sqlite_picker, project, project_id=project_id
        )
        postgres_business = BusinessReadProvider(
            postgres_picker, project, project_id=project_id
        )

        def business_query(
            *, labels=("fire",), sources=(), pool_only=False,
            history="include_history", role="", usage_role="train",
            usage_state="", count_mode="exact", page=1, page_size=50,
        ):
            return BusinessQuery(
                project_id=project_id,
                filters=BusinessFilter(
                    base=PickerFilter(
                        labels=tuple(labels), storage_source_ids=tuple(sources),
                        negative_pool_only=bool(pool_only),
                    ),
                    label_codes=tuple(labels),
                    algorithm_asset_id=baseline.ALGO_ACTIVE,
                    history_policy=history,
                    sample_role=role,
                    usage_role=usage_role,
                    usage_state=usage_state,
                ),
                count_mode=count_mode,
                page=page,
                page_size=page_size,
            )

        scenarios = {
            "base_label": business_query(),
            "combo_source": business_query(
                labels=("fire",), sources=(baseline.FOCUS_SOURCE,)
            ),
            "pool_only": business_query(labels=("fire",), pool_only=True),
            "sparse_person": business_query(labels=("person",)),
            "no_match": business_query(labels=("does-not-exist",)),
            "deferred": business_query(count_mode="deferred"),
            "deep_page": business_query(page=100),
            "history_excluded": business_query(history="new_for_algorithm"),
            "test_role": business_query(usage_role="test", usage_state="test_reserved"),
        }
        for name, query in scenarios.items():
            sqlite_metrics, sqlite_page = _measure(
                lambda q=query: sqlite_business.read_page(q), samples=int(
                    os.environ.get("P4_SAMPLES", "7")
                )
            )
            postgres_metrics, postgres_page = _measure(
                lambda q=query: postgres_business.read_page(q), samples=int(
                    os.environ.get("P4_SAMPLES", "7")
                )
            )
            same = (
                _ids(sqlite_page), _roles(sqlite_page), sqlite_page.total
            ) == (
                _ids(postgres_page), _roles(postgres_page), postgres_page.total
            )
            RESULT["layers"].setdefault("business", {})[name] = {
                "sqlite": sqlite_metrics,
                "postgres": postgres_metrics,
                "ids": len(_ids(sqlite_page)),
                "total": sqlite_page.total,
                "same": same,
            }
            RESULT["matches"].append({"case": name, "same": same})
            assert same, (name, _ids(sqlite_page)[:10], _ids(postgres_page)[:10])

        # Cursor continuation is compared separately from offset paging.
        first_query = business_query(page=None, page_size=25, count_mode="deferred")
        sqlite_first = sqlite_business.read_page(first_query)
        postgres_first = postgres_business.read_page(first_query)
        if sqlite_first.next_cursor and postgres_first.next_cursor:
            sqlite_second = sqlite_business.read_page(
                replace(first_query, cursor=sqlite_first.next_cursor)
            )
            postgres_second = postgres_business.read_page(
                replace(first_query, cursor=postgres_first.next_cursor)
            )
            cursor_same = _ids(sqlite_second) == _ids(postgres_second)
        else:
            cursor_same = (
                len(sqlite_first.items) == len(postgres_first.items) == 0
                and not sqlite_first.has_more and not postgres_first.has_more
            )
        RESULT["layers"]["business"]["cursor"] = {"same": cursor_same}
        assert cursor_same

        # Original formal API single-page baseline (base filter, newest order).
        app = FastAPI()
        app.include_router(training_material_picker_router(
            lambda pid: {"id": pid} if pid == project_id else None,
            lambda: world["data_dir"],
            algorithm_provider=lambda pid, algorithm_id: (
                {"id": algorithm_id, "name": "algorithm-000",
                 "versions": [], "algorithm_type": "yolo_ultralytics"}
            ),
        ))
        client = TestClient(app)
        original_metrics, original_response = _measure(
            lambda: client.post(
                f"/api/v62/projects/{project_id}/training-materials/page",
                json={
                    "algorithm_asset_id": baseline.ALGO_ACTIVE,
                    "history_policy": "include_history",
                    "labels": ["fire"],
                    "page": 1, "page_size": 50, "sort_order": "newest",
                },
            ),
            samples=3,
        )
        assert original_response.status_code == 200, original_response.text
        original_body = original_response.json()
        original_ids = [item["id"] for item in original_body["items"]]
        sqlite_base = sqlite_business.read_page(
            business_query(page_size=50).__class__(
                project_id=project_id,
                filters=BusinessFilter(
                    base=PickerFilter(labels=("fire",)),
                    label_codes=("fire",),
                    algorithm_asset_id=baseline.ALGO_ACTIVE,
                    history_policy="include_history",
                    browse_only=True,
                ),
                sort_order="newest", count_mode="exact", page=1, page_size=50,
            )
        )
        original_same = original_ids == _ids(sqlite_base)
        common = 0
        for left, right in zip(original_ids, _ids(sqlite_base)):
            if left != right:
                break
            common += 1
        RESULT["layers"]["original_api"] = {
            "metrics": original_metrics,
            "total": original_body.get("total"),
            "ids": len(original_ids),
            "sqlite_total": sqlite_base.total,
            "sqlite_ids": len(_ids(sqlite_base)),
            "common_prefix": common,
            "same_as_sqlite": original_same,
        }
        RESULT["matches"].append({"case": "original_api_base_page", "same": original_same})

        # Incremental changes followed by READY publication, then compare with a
        # fresh full import of the same final Owner state.
        repo = MaterialRepository(project)
        for index in range(20):
            row = repo.get(f"img-{index:06d}")
            row.update(filename=f"p4-incremental-{index:02d}.jpg")
            repo.upsert(row)
        annotations = AnnotationRepository(project)
        for index in range(20, 30):
            image_id = f"img-{index:06d}"
            gt = annotations.get(image_id)
            annotations.upsert(
                image_id,
                [{"label": "fire", "x1": 11, "y1": 12, "x2": 80, "y2": 90}],
                annotation_scope=["fire"], expected_version=gt["version"],
                project_material=False,
            )
        pool = world["negative_pool"]
        pool.category(name="p4-late-category")
        synchronized = synchronize_project(
            connection, project_dir=project, project_id=project_id,
            limit=int(os.environ.get("P4_SYNC_LIMIT", "500")),
            max_batches=int(os.environ.get("P4_SYNC_BATCHES", "40")),
        )
        assert synchronized["status"] == "READY", synchronized
        final_snapshot = export_project_snapshot(project, project_id)
        target = read_target_snapshot(connection, project_id)
        comparison = dict(target)
        comparison["revisions"] = dict(final_snapshot["revisions"])
        report = reconcile(final_snapshot, comparison)
        RESULT["layers"]["incremental"] = {
            "status": synchronized["status"], "applied": synchronized["applied"],
            "same": report["same"], "blocking": report["blocking_findings"],
        }
        assert report["same"] is True, report["blocking_findings"]

    RESULT["environment"] = {
        "platform": platform.platform(), "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version, "postgres": "server",
        "machine": platform.machine(),
        "materials": baseline.TOTAL_MATERIALS, "gt": baseline.TOTAL_GT,
        "samples": int(os.environ.get("P4_SAMPLES", "7")),
        "enriched": enriched,
    }
    result_path = os.environ.get("P4_RESULTS_PATH", "").strip()
    if result_path:
        pathlib.Path(result_path).write_text(
            json.dumps(RESULT, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    print(json.dumps(RESULT, ensure_ascii=False, default=str))
