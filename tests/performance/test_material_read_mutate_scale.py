"""Opt-in isolated benchmark for the H2/H3 full-table read/mutate cost.

Run with RUN_MATERIAL_READ_SCALE=1.  It uses synthetic SQLite metadata only and
never reads production storage.
"""
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
    os.environ.get("RUN_MATERIAL_READ_SCALE") != "1",
    reason="set RUN_MATERIAL_READ_SCALE=1 for the isolated 50k read/mutate benchmark",
)
def test_material_read_and_noop_mutate_scale(tmp_path: Path):
    repository = MaterialRepository(tmp_path / "project")
    started = time.perf_counter()
    for base in range(0, 50_000, 5_000):
        repository.upsert_many([
            {
                "id": f"m{index:07d}",
                "filename": f"camera-{index:07d}.jpg",
                "object_key": f"{index}.jpg",
                "content_sha256": f"{index + 1:064x}",
                "processing_status": "processed",
                "storage_source_id": "local-a" if index % 2 else "local-b",
                "labels": ["fire"] if index % 3 else ["smoke"],
                "created_at": "2026-11-04T00:00:00+00:00",
            }
            for index in range(base, base + 5_000)
        ])
    seed_seconds = round(time.perf_counter() - started, 3)

    reads: list[float] = []
    mutates: list[float] = []
    for _ in range(7):
        began = time.perf_counter()
        snapshot = repository.read()
        reads.append((time.perf_counter() - began) * 1000)
        assert len(snapshot.rows) == 50_000
    for _ in range(7):
        began = time.perf_counter()
        repository.mutate(lambda rows: None)
        mutates.append((time.perf_counter() - began) * 1000)

    report = {
        "fixture_only": True,
        "rows": 50_000,
        "seed_seconds": seed_seconds,
        "read_p50_ms": round(statistics.median(reads), 2),
        "read_p95_ms": round(sorted(reads)[-1], 2),
        "mutate_noop_p50_ms": round(statistics.median(mutates), 2),
        "mutate_noop_p95_ms": round(sorted(mutates)[-1], 2),
        "db_bytes": repository.path.stat().st_size,
    }
    print(json.dumps(report, ensure_ascii=False))
