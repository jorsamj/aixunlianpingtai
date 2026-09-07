from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from platform_core.material_repository import MaterialRepository


MILESTONES = (100_000, 500_000, 1_000_000)


@pytest.mark.scale
@pytest.mark.skipif(
    os.environ.get("RUN_MATERIAL_SCALE") != "1",
    reason="set RUN_MATERIAL_SCALE=1 for the 100k/500k/1m material-index acceptance test",
)
def test_material_repository_remains_paginated_at_one_million_rows(
    tmp_path: Path,
    record_property,
):
    repository = MaterialRepository(tmp_path / "project")
    batch_size = 10_000
    timings: dict[int, dict[str, float]] = {}
    started = time.perf_counter()

    for start in range(0, MILESTONES[-1], batch_size):
        repository.upsert_many(
            {
                "id": f"material-{index:07d}",
                "filename": f"camera-{index:07d}.jpg",
                "storage_source_id": "default_local" if index % 2 == 0 else "remote-a",
                "storage_type": "local" if index % 2 == 0 else "s3",
                "object_key": f"materials/{index // 1000:04d}/{index:07d}.jpg",
                "content_sha256": f"{index:064x}",
                "size_bytes": 1024 + index % 4096,
                "processing_status": "processed",
                "labels": ["fire"] if index % 10 == 0 else (["smoke"] if index % 10 == 1 else []),
                "created_at": f"2026-01-{(index % 28) + 1:02d}T00:{(index // 28) % 60:02d}:{index % 60:02d}.{index:07d}+00:00",
            }
            for index in range(start, start + batch_size)
        )
        current = start + batch_size
        if current in MILESTONES:
            query_started = time.perf_counter()
            page = repository.list_page(limit=100, storage_source_ids=["remote-a"], labels=["fire", "smoke"])
            query_elapsed = time.perf_counter() - query_started
            assert repository.count() == current
            assert len(page.items) == 100
            assert page.next_cursor
            assert all(row["storage_source_id"] == "remote-a" for row in page.items)
            assert all(set(row["labels"]) & {"fire", "smoke"} for row in page.items)
            timings[current] = {
                "elapsed_seconds": round(time.perf_counter() - started, 3),
                "filtered_page_seconds": round(query_elapsed, 3),
            }

    record_property("material_scale_timings", timings)
    assert repository.path.stat().st_size > 0
