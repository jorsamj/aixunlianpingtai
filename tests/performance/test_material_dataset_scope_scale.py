"""Opt-in 50k benchmark for dataset-scoped atomic split updates."""
from __future__ import annotations

import json
import math
import os
import sqlite3
import statistics
import time
from pathlib import Path

import pytest

from platform_core.material_repository import MaterialRepository


@pytest.mark.scale
@pytest.mark.skipif(
    os.environ.get("RUN_MATERIAL_DATASET_SCALE") != "1",
    reason="set RUN_MATERIAL_DATASET_SCALE=1 for the isolated dataset-scope benchmark",
)
def test_dataset_scope_atomic_update_scale(tmp_path: Path):
    repository = MaterialRepository(tmp_path / "project")
    for base in range(0, 50_000, 5_000):
        repository.upsert_many([
            {
                "id": f"m{index:07d}",
                "filename": f"camera-{index:07d}.jpg",
                "object_key": f"{index}.jpg",
                "content_sha256": f"{index + 1:064x}",
                "processing_status": "processed",
                "storage_source_id": "local-a",
                "labels": ["fire"],
                "dataset_id": (
                    "small" if index < 100
                    else "medium" if index < 5_100
                    else "large" if index < 49_999
                    else "bulk"
                ),
                "split": "unassigned",
                "created_at": "2026-11-04T00:00:00+00:00",
            }
            for index in range(base, base + 5_000)
        ])

    with sqlite3.connect(repository.path) as database:
        plan = database.execute(
            "EXPLAIN QUERY PLAN SELECT id, payload_json FROM materials "
            "WHERE COALESCE(CAST(json_extract(payload_json, '$.dataset_id') AS TEXT), 'default') = ?",
            ("medium",),
        ).fetchall()
    plan_text = " | ".join(str(row[-1]) for row in plan)
    assert "ix_materials_dataset" in plan_text, plan_text

    def run(target: str, old: bool, split: str) -> float:
        def apply(rows):
            changed = 0
            for row in rows:
                if str(row.get("dataset_id", "default")) != target:
                    continue
                row["split"] = split
                changed += 1
            return changed

        began = time.perf_counter()
        if old:
            repository.mutate(apply)
        else:
            repository.mutate_dataset(target, apply)
        return (time.perf_counter() - began) * 1000

    def p95(values: list[float]) -> float:
        return round(sorted(values)[max(0, math.ceil(len(values) * 0.95) - 1)], 2)

    report = {"fixture_only": True, "rows": 50_000, "samples": 7,
              "query_plan": plan_text, "cases": []}
    for target, size in (("small", 100), ("medium", 5_000), ("large", 44_899)):
        old = [run(target, True, "train" if index % 2 else "test") for index in range(7)]
        new = [run(target, False, "test" if index % 2 else "train") for index in range(7)]
        report["cases"].append({
            "dataset": target, "matched_rows": size,
            "old_p50_ms": round(statistics.median(old), 2),
            "old_p95_ms": p95(old),
            "new_p50_ms": round(statistics.median(new), 2),
            "new_p95_ms": p95(new),
        })
    print(json.dumps(report, ensure_ascii=False))
