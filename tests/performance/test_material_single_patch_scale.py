"""Opt-in 50k benchmark for the single-image dataset patch path.

Compares the legacy full-table read+mutate path with the targeted get+mutate_ids
path used by PATCH /api/v12/projects/{pid}/images/{image_id}.
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
    os.environ.get("RUN_MATERIAL_PATCH_SCALE") != "1",
    reason="set RUN_MATERIAL_PATCH_SCALE=1 for the isolated 50k single-patch benchmark",
)
def test_single_material_dataset_patch_scale(tmp_path: Path):
    repository = MaterialRepository(tmp_path / "project")
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
                "dataset_id": "default",
                "created_at": "2026-11-04T00:00:00+00:00",
            }
            for index in range(base, base + 5_000)
        ])
    target = "m0000001"
    old_samples: list[float] = []
    new_samples: list[float] = []
    samples = 30
    for index in range(samples):
        dataset = f"legacy-{index}"
        began = time.perf_counter()
        current = next(row for row in repository.read().rows if row["id"] == target)

        def legacy_patch(rows):
            for row in rows:
                if row["id"] == target:
                    row["dataset_id"] = dataset
                    return dict(row)
            raise KeyError(target)

        repository.mutate(legacy_patch)
        old_samples.append((time.perf_counter() - began) * 1000)
        assert current["dataset_id"] != "missing"
    for index in range(samples):
        dataset = f"targeted-{index}"
        began = time.perf_counter()
        current = repository.get(target)

        def targeted_patch(rows):
            rows[0]["dataset_id"] = dataset
            return dict(rows[0])

        repository.mutate_ids([target], targeted_patch)
        new_samples.append((time.perf_counter() - began) * 1000)
        assert current is not None
    assert repository.get(target)["dataset_id"] == f"targeted-{samples - 1}"
    p95 = lambda rows: round(sorted(rows)[max(0, int(len(rows) * 0.95) - 1)], 2)
    report = {
        "fixture_only": True,
        "rows": 50_000,
        "samples": samples,
        "legacy_read_mutate_p50_ms": round(statistics.median(old_samples), 2),
        "legacy_read_mutate_p95_ms": p95(old_samples),
        "targeted_get_mutate_ids_p50_ms": round(statistics.median(new_samples), 2),
        "targeted_get_mutate_ids_p95_ms": p95(new_samples),
        "revision": repository.read_revision() if hasattr(repository, "read_revision") else None,
    }
    print(json.dumps(report, ensure_ascii=False))
