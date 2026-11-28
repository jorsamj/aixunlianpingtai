"""Opt-in 50k benchmark for v49 mark-processed explicit-ID sets."""
from __future__ import annotations

import json
import os
import statistics
import time
from pathlib import Path

import pytest

from platform_core.material_repository import MaterialRepository


@pytest.mark.scale
@pytest.mark.skipif(
    os.environ.get("RUN_MATERIAL_MARK_SCALE") != "1",
    reason="set RUN_MATERIAL_MARK_SCALE=1 for the isolated mark-processed benchmark",
)
def test_mark_processed_explicit_sets_scale(tmp_path: Path):
    repository = MaterialRepository(tmp_path / "project")
    for base in range(0, 50_000, 5_000):
        repository.upsert_many([
            {
                "id": f"m{index:07d}",
                "filename": f"camera-{index:07d}.jpg",
                "object_key": f"{index}.jpg",
                "content_sha256": f"{index + 1:064x}",
                "processing_status": "pending",
                "storage_source_id": "local-a",
                "labels": ["fire"],
                "dataset_id": "default",
                "split": "unassigned",
                "created_at": "2026-11-04T00:00:00+00:00",
            }
            for index in range(base, base + 5_000)
        ])

    def run(target: set[str], old: bool, stamp: str) -> float:
        def apply(rows):
            changed = 0
            for row in rows:
                if str(row.get("id")) not in target:
                    continue
                row["processing_status"] = "processed"
                row["cleaned_at"] = stamp
                changed += 1
            return changed

        started = time.perf_counter()
        if old:
            repository.mutate(apply)
        else:
            repository.mutate_ids(target, apply)
        return (time.perf_counter() - started) * 1000

    report = {"fixture_only": True, "rows": 50_000, "cases": []}
    for size in (1, 100, 1_000, 2_000, 5_000, 10_000, 50_000):
        target = {f"m{index:07d}" for index in range(size)}
        old = [run(target, True, f"old-{size}-{index}") for index in range(3)]
        new = [run(target, False, f"new-{size}-{index}") for index in range(3)]
        report["cases"].append({
            "target_ids": size,
            "samples": 3,
            "old_p50_ms": round(statistics.median(old), 2),
            "old_p95_ms": round(sorted(old)[-1], 2),
            "new_p50_ms": round(statistics.median(new), 2),
            "new_p95_ms": round(sorted(new)[-1], 2),
        })
    print(json.dumps(report, ensure_ascii=False))
