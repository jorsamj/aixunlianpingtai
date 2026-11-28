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
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace

import pytest

try:
    import psutil
except ImportError:  # pragma: no cover - CI installs psutil
    psutil = None


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


@pytest.fixture(autouse=True)
def _flush_results():
    """Keep partial structured evidence even when a measurement assertion fails."""
    yield
    path = os.environ.pop("P4_RESULTS_PATH", "").strip()
    if path:
        pathlib.Path(path).write_text(
            json.dumps(RESULT, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )


def _percentile(values, quantile):
    ordered = sorted(values)
    if not ordered:
        return None
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * quantile))))
    return ordered[index]


def _rss_mb():
    return round(psutil.Process().memory_info().rss / 1024 / 1024, 1) if psutil else None


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
        from platform_core.task_runtime import TaskKind, TaskRecord
        from platform_core.task_runtime.models import TaskStatus
        task = TaskRecord.new(
            "p4-test-reservation", project_id, TaskKind.TRAINING,
            "payload.json", "training:p4-test-reservation",
        )
        world["tasks"].create(replace(task, status=TaskStatus.RUNNING))

    retired = repository.retire_many(
        [f"img-{baseline.TOTAL_MATERIALS - index:06d}" for index in range(1, 6)],
        task_id="p4-retirement", actor_id="p4-fixture",
    )
    return {"negative_members": len(ids), "confirmations": receipts,
            "test_reservation": len(rows), "retired": retired}


class _ExternalPostgres:
    def __init__(self, dsn):
        self._dsn = dsn

    def get_uri(self):
        return self._dsn

    def cleanup(self):
        with psycopg.connect(self._dsn) as connection:
            connection.execute("DROP SCHEMA IF EXISTS w3_material_gt CASCADE")
            connection.commit()


def _pg_fixture(tmp_path):
    external = os.environ.get("MC_TEST_POSTGRES_DSN", "").strip()
    if external:
        return _ExternalPostgres(external), tmp_path
    root = pathlib.Path(tmp_path) / "pgdata"
    return pgserver.get_server(root, cleanup_mode="delete"), tmp_path


def test_u3_p4_scale_measurement(tmp_path):
    server, _ = _pg_fixture(tmp_path)
    project_id = baseline.PROJECT
    world = baseline._build_world(pathlib.Path(tmp_path) / "scale")
    enriched = _enrich(world, project_id, baseline.ALGO_ACTIVE)
    project = world["project_path"]
    rss_samples = [_rss_mb()]

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
        profile: dict[str, dict[str, float]] = {}
        if os.environ.get("P4_PROFILE") == "1":
            for label, provider in (
                ("sqlite", sqlite_business), ("postgres", postgres_business),
            ):
                profile[label] = {
                    "read_page_ms": 0.0, "evaluate_ms": 0.0,
                    "history_ms": 0.0, "evaluate_calls": 0.0,
                    "history_calls": 0.0, "owner_gt_ms": 0.0,
                    "owner_gt_calls": 0.0, "usage_ms": 0.0,
                    "pg_gt_ms": 0.0, "pg_gt_calls": 0.0,
                    "receipts_ms": 0.0, "receipts_calls": 0.0,
                    "candidate_batches": 0.0, "candidate_rows": 0.0,
                    "materialized_batches": 0.0, "count_only_batches": 0.0,
                }
                original_evaluate = provider._evaluate_batch
                original_history = provider._history_facts
                original_owner_gt = provider.annotations.get_many
                original_usage_query = provider.usage.query_filter

                def timed_owner_gt(*args, _label=label, _fn=original_owner_gt, **kwargs):
                    began = time.perf_counter()
                    try:
                        return _fn(*args, **kwargs)
                    finally:
                        profile[_label]["owner_gt_ms"] += (
                            time.perf_counter() - began
                        ) * 1000
                        profile[_label]["owner_gt_calls"] += 1

                def timed_usage(*args, _label=label, _fn=original_usage_query, **kwargs):
                    began = time.perf_counter()
                    try:
                        return _fn(*args, **kwargs)
                    finally:
                        profile[_label]["usage_ms"] += (
                            time.perf_counter() - began
                        ) * 1000

                provider.annotations.get_many = timed_owner_gt
                provider.usage.query_filter = timed_usage

                def timed_evaluate(*args, _label=label, _fn=original_evaluate, **kwargs):
                    began = time.perf_counter()
                    try:
                        return _fn(*args, **kwargs)
                    finally:
                        profile[_label]["evaluate_ms"] += (
                            time.perf_counter() - began
                        ) * 1000
                        profile[_label]["evaluate_calls"] += 1
                        batch = args[2] if len(args) > 2 else ()
                        profile[_label]["candidate_batches"] += 1
                        profile[_label]["candidate_rows"] += len(batch)
                        if kwargs.get("materialize", True):
                            profile[_label]["materialized_batches"] += 1
                        else:
                            profile[_label]["count_only_batches"] += 1

                def timed_history(*args, _label=label, _fn=original_history, **kwargs):
                    began = time.perf_counter()
                    try:
                        return _fn(*args, **kwargs)
                    finally:
                        profile[_label]["history_ms"] += (
                            time.perf_counter() - began
                        ) * 1000
                        profile[_label]["history_calls"] += 1

                provider._evaluate_batch = timed_evaluate
                provider._history_facts = timed_history

            from platform_core.training_material_business_read import (
                _PostgresSession, _SQLiteSession,
            )
            original_pg_annotations = _PostgresSession.annotations
            original_pg_receipts = _PostgresSession.receipts
            original_sqlite_receipts = _SQLiteSession.receipts

            def timed_pg_annotations(self, *args):
                began = time.perf_counter()
                try:
                    return original_pg_annotations(self, *args)
                finally:
                    profile["postgres"]["pg_gt_ms"] += (
                        time.perf_counter() - began
                    ) * 1000
                    profile["postgres"]["pg_gt_calls"] += 1

            def timed_pg_receipts(self, *args):
                began = time.perf_counter()
                try:
                    return original_pg_receipts(self, *args)
                finally:
                    profile["postgres"]["receipts_ms"] += (
                        time.perf_counter() - began
                    ) * 1000
                    profile["postgres"]["receipts_calls"] += 1

            def timed_sqlite_receipts(self, *args):
                began = time.perf_counter()
                try:
                    return original_sqlite_receipts(self, *args)
                finally:
                    profile["sqlite"]["receipts_ms"] += (
                        time.perf_counter() - began
                    ) * 1000
                    profile["sqlite"]["receipts_calls"] += 1

            _PostgresSession.annotations = timed_pg_annotations
            _PostgresSession.receipts = timed_pg_receipts
            _SQLiteSession.receipts = timed_sqlite_receipts

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
            "positive_role": business_query(role="positive"),
            "confirmed_negative": business_query(role="confirmed_negative"),
            "pending_review": business_query(role="pending_review"),
        }
        for name, query in scenarios.items():
            before = {
                label: dict(values) for label, values in profile.items()
            } if profile else {}
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
            if profile:
                RESULT["layers"].setdefault("profile_scenarios", {})[name] = {
                    label: {
                        key: round(values[key] - before[label][key], 3)
                        for key in ("evaluate_ms", "evaluate_calls",
                                    "history_ms", "history_calls",
                                    "owner_gt_ms", "owner_gt_calls",
                                    "usage_ms", "pg_gt_ms", "pg_gt_calls",
                                    "receipts_ms", "receipts_calls",
                                    "candidate_batches", "candidate_rows",
                                    "materialized_batches", "count_only_batches")
                    }
                    for label, values in profile.items()
                }
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
        if profile:
            for label, provider in (
                ("sqlite", sqlite_business), ("postgres", postgres_business),
            ):
                began = time.perf_counter()
                provider.read_page(business_query(count_mode="exact"))
                profile[label]["read_page_ms"] = (
                    time.perf_counter() - began
                ) * 1000
            RESULT["layers"]["profile"] = profile
        rss_samples.append(_rss_mb())

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
        assert original_same, (
            original_ids[:10], _ids(sqlite_base)[:10],
            original_body.get("total"), sqlite_base.total,
        )
        assert int(original_body.get("total") or 0) == int(sqlite_base.total or 0)

        # Frozen selection is the original formal contract; its ID set must match
        # the P1 candidate stream for the same business context.
        from platform_core.training_selection_reference import read_selection, selection_context

        focus_base = {
            "algorithm_asset_id": baseline.ALGO_ACTIVE,
            "role": "train",
            "storage_source_ids": [baseline.FOCUS_SOURCE],
        }
        freeze_response = client.post(
            f"/api/v62/projects/{project_id}/training-materials/selection-reference",
            json={**focus_base, "history_policy": "include_history"},
        )
        assert freeze_response.status_code == 200, freeze_response.text
        frozen = freeze_response.json()
        context = selection_context(
            world["data_dir"], project_id,
            {**focus_base, "history_policy": "include_history"}, "train",
        )
        frozen_ids = read_selection(
            world["data_dir"], frozen["selection_ref"], context
        )
        assert len(frozen_ids) == int(frozen["count"])
        picker_ids = [
            item.material.id
            for batch in sqlite_business.iter_candidates(
                BusinessQuery(
                    project_id=project_id,
                    filters=BusinessFilter(
                        base=PickerFilter(
                            storage_source_ids=(baseline.FOCUS_SOURCE,)
                        ),
                        algorithm_asset_id=baseline.ALGO_ACTIVE,
                        history_policy="include_history",
                        browse_only=True,
                    ),
                    page_size=100,
                )
            )
            for item in batch
        ]
        excluded_ids = {
            f"img-{index:06d}" for index in range(0, 100)
        } | {
            f"img-{baseline.TOTAL_MATERIALS - index:06d}" for index in range(1, 6)
        }
        expected_picker = set(picker_ids) - excluded_ids
        frozen_same = set(frozen_ids) == expected_picker
        RESULT["layers"]["frozen_selection"] = {
            "count": len(frozen_ids), "picker_count": len(picker_ids),
            "expected_count": len(expected_picker),
            "missing": sorted(set(frozen_ids) - expected_picker)[:10],
            "extra": sorted(expected_picker - set(frozen_ids))[:10],
            "same_as_picker": frozen_same,
        }
        RESULT["matches"].append({"case": "frozen_selection", "same": frozen_same})
        assert frozen_same, RESULT["layers"]["frozen_selection"]

        # Incremental changes followed by READY publication, then compare with a
        # fresh full import of the same final Owner state.
        repo = MaterialRepository(project)
        with sqlite3.connect(project / "materials.sqlite3") as database:
            log_before = int(database.execute(
                "SELECT COUNT(*) FROM owner_change_log"
            ).fetchone()[0])
        write_started = time.perf_counter()
        for index in range(20):
            row = repo.get(f"img-{index:06d}")
            row.update(filename=f"p4-incremental-{index:02d}.jpg")
            repo.upsert(row)
        write_seconds = round(time.perf_counter() - write_started, 3)
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
        ready_profile: dict[str, float] = {}
        if os.environ.get("P4_PROFILE") == "1":
            import platform_core.u3_incremental_sync as sync_module

            original_export = sync_module.export_project_snapshot
            original_target = sync_module._read_target_snapshot_in_transaction
            original_reconcile = sync_module.reconcile

            def timed_export(*args, **kwargs):
                began = time.perf_counter()
                try:
                    return original_export(*args, **kwargs)
                finally:
                    ready_profile["owner_export_ms"] = (
                        time.perf_counter() - began
                    ) * 1000

            def timed_target(*args, **kwargs):
                began = time.perf_counter()
                try:
                    return original_target(*args, **kwargs)
                finally:
                    ready_profile["target_read_ms"] = (
                        time.perf_counter() - began
                    ) * 1000

            def timed_reconcile(*args, **kwargs):
                began = time.perf_counter()
                try:
                    return original_reconcile(*args, **kwargs)
                finally:
                    ready_profile["reconcile_ms"] = (
                        time.perf_counter() - began
                    ) * 1000

            sync_module.export_project_snapshot = timed_export
            sync_module._read_target_snapshot_in_transaction = timed_target
            sync_module.reconcile = timed_reconcile
        incremental_started = time.perf_counter()
        synchronized = synchronize_project(
            connection, project_dir=project, project_id=project_id,
            limit=int(os.environ.get("P4_SYNC_LIMIT", "500")),
            max_batches=int(os.environ.get("P4_SYNC_BATCHES", "40")),
        )
        incremental_seconds = round(time.perf_counter() - incremental_started, 3)
        if ready_profile:
            ready_profile["sync_total_ms"] = round(incremental_seconds * 1000, 3)
            RESULT["layers"]["ready_profile"] = ready_profile
        assert synchronized["status"] == "READY", synchronized
        final_snapshot = export_project_snapshot(project, project_id)
        target = read_target_snapshot(connection, project_id)
        comparison = dict(target)
        comparison["revisions"] = dict(final_snapshot["revisions"])
        report = reconcile(final_snapshot, comparison)
        with sqlite3.connect(project / "materials.sqlite3") as database:
            log_after = int(database.execute(
                "SELECT COUNT(*) FROM owner_change_log"
            ).fetchone()[0])
        rss_samples.append(_rss_mb())
        RESULT["layers"]["incremental"] = {
            "status": synchronized["status"], "applied": synchronized["applied"],
            "same": report["same"], "blocking": report["blocking_findings"],
            "seconds": incremental_seconds,
            "write_seconds": write_seconds,
            "change_log_growth": log_after - log_before,
        }
        assert report["same"] is True, report["blocking_findings"]

        def concurrent_page(provider):
            return _ids(provider.read_page(
                business_query(page=None, page_size=50, count_mode="deferred")
            ))

        started = time.perf_counter()
        with ThreadPoolExecutor(max_workers=2) as pool_executor:
            concurrent = list(pool_executor.map(
                concurrent_page, (sqlite_business, postgres_business)
            ))
        RESULT["layers"]["concurrency"] = {
            "seconds": round(time.perf_counter() - started, 3),
            "same": concurrent[0] == concurrent[1],
            "ids": len(concurrent[0]),
        }
        assert concurrent[0] == concurrent[1]

        write_repo = MaterialRepository(project)
        write_annotations = AnnotationRepository(project)
        write_ids = [f"p4-batch-{index:04d}" for index in range(100)]
        with sqlite3.connect(project / "materials.sqlite3") as database:
            write_log_before = int(database.execute(
                "SELECT COUNT(*) FROM owner_change_log"
            ).fetchone()[0])
        write_started = time.perf_counter()
        write_repo.upsert_many([
            {
                "id": image_id, "filename": image_id + ".jpg",
                "object_key": "uploads/" + image_id + ".jpg",
                "content_sha256": f"{index + 1:064x}",
                "size_bytes": 1024, "processing_status": "processed",
            }
            for index, image_id in enumerate(write_ids)
        ])
        material_write_ms = (time.perf_counter() - write_started) * 1000
        write_started = time.perf_counter()
        write_annotations.upsert_many([
            {
                "image_id": image_id, "annotation_state": "annotated",
                "annotation_scope": ["fire"],
                "boxes": [{
                    "label": "fire", "class_id": 0,
                    "x1": 1, "y1": 1, "x2": 12, "y2": 12,
                }],
            }
            for image_id in write_ids
        ])
        annotation_write_ms = (time.perf_counter() - write_started) * 1000
        with sqlite3.connect(project / "materials.sqlite3") as database:
            write_log_after = int(database.execute(
                "SELECT COUNT(*) FROM owner_change_log"
            ).fetchone()[0])
        RESULT["layers"]["write_cost"] = {
            "materials": 100, "annotations": 100,
            "material_ms": round(material_write_ms, 3),
            "annotation_ms": round(annotation_write_ms, 3),
            "change_log_growth": write_log_after - write_log_before,
        }

        with connection.cursor() as cursor:
            cursor.execute("SELECT version()")
            postgres_version = str(cursor.fetchone()[0])
        with sqlite3.connect(project / "materials.sqlite3") as database:
            counts = {
                table: int(database.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in (
                    "materials", "material_labels", "material_annotation_scopes",
                    "material_retirements", "material_storage_audit",
                    "negative_pool_members", "negative_pool_links",
                    "negative_pool_algorithm_members", "owner_change_log",
                )
            }
            counts["owner_change_meta_hwm"] = dict(database.execute(
                "SELECT stream,last_sequence FROM owner_change_meta"
            ).fetchall())
        with sqlite3.connect(project / "annotations.sqlite3") as database:
            counts["annotations"] = int(database.execute(
                "SELECT COUNT(*) FROM annotations"
            ).fetchone()[0])
            counts["task_negative_confirmations"] = int(database.execute(
                "SELECT COUNT(*) FROM task_negative_confirmations"
            ).fetchone()[0])
        wal_bytes = sum(
            path.stat().st_size for path in project.glob("*.sqlite3-wal")
        )
        process = psutil.Process() if psutil is not None else None

    RESULT["environment"] = {
        "git_sha": os.environ.get("GITHUB_SHA", ""),
        "platform": platform.platform(), "python": platform.python_version(),
        "sqlite": sqlite3.sqlite_version, "postgres": postgres_version,
        "cpu_count": os.cpu_count(), "machine": platform.machine(),
        "materials": baseline.TOTAL_MATERIALS, "gt": baseline.TOTAL_GT,
        "samples": int(os.environ.get("P4_SAMPLES", "7")),
        "rss_mb": round(process.memory_info().rss / 1024 / 1024, 1) if process else None,
        "rss_peak_mb": max(value for value in rss_samples if value is not None)
        if any(value is not None for value in rss_samples) else None,
        "rss_samples_mb": rss_samples,
        "counts": counts, "wal_bytes": wal_bytes,
        "db_sizes_bytes": world.get("sizes") or {},
        "enriched": enriched,
    }
    result_path = os.environ.get("P4_RESULTS_PATH", "").strip()
    if result_path:
        pathlib.Path(result_path).write_text(
            json.dumps(RESULT, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
    print(json.dumps(RESULT, ensure_ascii=False, default=str))
