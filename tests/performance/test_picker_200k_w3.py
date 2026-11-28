"""Opt-in 200k picker measurement (synthetic, isolated, no production data)."""
from __future__ import annotations

import json
import os
import sqlite3
import time

import pytest

from platform_core.annotation_repository import AnnotationRepository
from platform_core.material_repository import MaterialRepository
import platform_core.training_material_picker_api as picker


@pytest.mark.scale
@pytest.mark.skipif(
    os.environ.get("RUN_PICKER_200K") != "1",
    reason="set RUN_PICKER_200K=1 for the isolated 200k picker measurement",
)
def test_picker_200k_role_and_deep_gt_page(tmp_path):
    total = 200_000
    repo = MaterialRepository(tmp_path / "project")
    annotations = AnnotationRepository(repo.project_path)
    for base in range(0, total, 1_000):
        materials = []
        gt = []
        for index in range(base, base + 1_000):
            labels = (["fire", "smoke"] if index % 5 == 0
                      else ["smoke"] if index % 2 == 0 else ["person"])
            image_id = f"img-{index:06d}"
            materials.append({
                "id": image_id, "filename": f"camera-{index:06d}.jpg",
                "object_key": f"{index}.jpg", "content_sha256": f"{index + 1:064x}",
                "storage_source_id": "remote-a" if index % 3 else "remote-b",
                "processing_status": "processed" if index % 7 else "pending_decision",
                "labels": labels, "created_at": f"2026-10-28T00:{index // 60000:02d}:{index % 60:02d}.{index:06d}+00:00",
                "width": 800, "height": 800,
            })
            if index % 11 == 0:
                gt.append({"image_id": image_id, "annotation_state": "confirmed_empty",
                           "annotation_scope": labels, "boxes": []})
            else:
                gt.append({"image_id": image_id, "annotation_state": "annotated",
                           "annotation_scope": labels,
                           "boxes": [{"label": label, "x1": 20, "y1": 30, "x2": 200, "y2": 300}
                                     for label in labels]})
        repo.upsert_many(materials)
        for offset in range(0, len(gt), 500):
            annotations.upsert_many(gt[offset:offset + 500])

    with sqlite3.connect(repo.path) as database:
        database.execute("ATTACH DATABASE ? AS annotation_gt", (str(annotations.path),))
        plan = " | ".join(str(row[-1]) for row in database.execute(
            "EXPLAIN QUERY PLAN SELECT COUNT(*) FROM annotation_gt.annotation_label_references gt "
            "JOIN materials m ON m.id=gt.image_id "
            "WHERE gt.annotation_state='annotated' AND gt.box_count>0 AND gt.label_code IN ('fire') "
            "AND m.processing_status='processed'"
        ).fetchall())
    assert "ix_annotation_label_references_code" in plan, plan

    picker._cached_role_index.cache_clear()
    began = time.perf_counter()
    first = picker._role_material_page(
        repo, annotations, {"effective_label_codes": ["person"]}, limit=60,
        defer_role_counts=True, count_mode="deferred",
    )
    cold_ms = (time.perf_counter() - began) * 1000
    began = time.perf_counter()
    second = picker._role_material_page(
        repo, annotations, {"effective_label_codes": ["person"]}, page=2, limit=60,
        defer_role_counts=True, count_mode="deferred",
    )
    cached_ms = (time.perf_counter() - began) * 1000
    begin_legacy = time.perf_counter()
    legacy = picker._role_material_page(
        repo, annotations, {"effective_label_codes": ["person"]}, limit=60,
    )
    legacy_ms = (time.perf_counter() - begin_legacy) * 1000

    began = time.perf_counter()
    deep = picker._gt_material_filter_page(
        repo, annotations, page=2_000, limit=60, include_payload=False,
    )
    deep_ms = (time.perf_counter() - began) * 1000
    began = time.perf_counter()
    filtered = picker._gt_material_filter_page(
        repo, annotations, page=1, limit=60, labels=("fire",),
        include_payload=False,
    )
    filtered_ms = (time.perf_counter() - began) * 1000
    began = time.perf_counter()
    filtered_deferred = picker._gt_material_filter_page(
        repo, annotations, page=1, limit=60, labels=("fire",),
        include_payload=False, count_mode="deferred",
    )
    filtered_deferred_ms = (time.perf_counter() - began) * 1000
    assert first["total"] is None and second["total"] is None
    assert deep["total"] >= filtered["total"] > 0
    assert legacy["total"] > 0
    print(json.dumps({
        "fixture_only": True, "rows": total,
        "role_deferred_ms": round(cold_ms, 2), "role_deferred_page2_ms": round(cached_ms, 2),
        "role_legacy_cold_ms": round(legacy_ms, 2),
        "role_total": first["total"], "deep_page_ms": round(deep_ms, 2),
        "filtered_page_ms": round(filtered_ms, 2),
        "filtered_deferred_ms": round(filtered_deferred_ms, 2),
    }))
