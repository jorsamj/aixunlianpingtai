"""Isolated real YOLO conversion benchmark; never connects to production.

Run BEFORE and AFTER the fix with the same Python/environment:
  python tools/benchmark_zip_import_metadata.py --case all --output C:/tmp/zip-before.json
Existing material rows are synthetic; incoming files are real 32x32 PNGs.
Timings cover conversion/storage/GT/index commit, not HTTP ZIP transfer/extraction.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

CASES = {"A": (1000, 1000), "B": (5000, 1000), "C": (10000, 1000), "D": (10000, 10000)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", choices=[*CASES, "all"], default="all")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(tempfile.mkdtemp(prefix="zip-metadata-benchmark-")).resolve()
    os.environ.update(MC_TRAIN_DATA_DIR=str(root), MC_PLATFORM_VERSION="test",
                      MC_ALLOW_MULTIPLE_PROJECTS_FOR_TESTS="1")
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import app as api
    from PIL import Image
    import psutil
    from platform_core.material_repository import MaterialRepository
    from platform_core.storage.manager import StorageManager
    from platform_core.storage.local import LocalStorageProvider
    from platform_core.annotation_repository import AnnotationRepository

    process = psutil.Process()
    memory = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(memory, format="PNG")
    image_bytes = memory.getvalue()
    expected_sha = hashlib.sha256(image_bytes).hexdigest()
    output = {"git_head": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "environment": {"os": platform.platform(), "python": platform.python_version(),
                              "cpu": platform.processor(), "logical_cpus": os.cpu_count(),
                              "temporary_root": str(root), "storage": "local disk; real 32x32 PNG; fsync enabled",
                              "free_disk_bytes": psutil.disk_usage(str(root)).free},
              "kind": "isolated synthetic-history, real-file conversion integration microbenchmark",
              "timing": "conversion and final commit; excludes ZIP transfer, scan and extraction; stages inclusive",
              "results": []}
    for name in (CASES if args.case == "all" else [args.case]):
        existing, incoming = CASES[name]
        project = api.create_project(api.ProjectCreate(name="zip-metadata-" + name, labels=["target"]))
        pid = project["id"]
        api.ensure_default_datasets(pid)
        repository = api.material_store(pid)
        repository.upsert_many({"id": f"history-{i:06d}", "filename": f"history-{i}.png",
                                "object_key": f"uploads/history-{i}.png", "dataset_id": "default",
                                "width": 32, "height": 32, "created_at": "2026-01-01T00:00:00"}
                               for i in range(existing))
        source = root / ("source-" + name)
        (source / "images" / "train").mkdir(parents=True)
        (source / "labels" / "train").mkdir(parents=True)
        (source / "data.yaml").write_text("names: [target]\n", encoding="utf-8")
        for i in range(incoming):
            (source / "images" / "train" / f"image-{i:06d}.png").write_bytes(image_bytes)
            (source / "labels" / "train" / f"image-{i:06d}.txt").write_text("0 0.5 0.5 0.5 0.5\n", encoding="utf-8")
        durations, calls = defaultdict(float), defaultdict(int)
        latencies = []
        rss_start = process.memory_info().rss
        rss_peak = rss_start

        def timed(owner, attr, key):
            original = getattr(owner, attr)
            def run(*a, **kw):
                started = time.perf_counter()
                try:
                    return original(*a, **kw)
                finally:
                    durations[key] += time.perf_counter() - started
                    calls[key] += 1
            return patch.object(owner, attr, run)

        original_connect = MaterialRepository._connect
        def traced_connect(self):
            connection = original_connect(self)
            def trace(statement):
                calls["material_sql_statements"] += 1
                if statement.lstrip().upper().startswith("SELECT"):
                    calls["material_sql_selects"] += 1
            connection.set_trace_callback(trace)
            return connection

        original_add = api.add_image_record
        def measured_add(*a, **kw):
            nonlocal rss_peak
            started = time.perf_counter()
            try:
                return original_add(*a, **kw)
            finally:
                latencies.append(time.perf_counter() - started)
                rss_peak = max(rss_peak, process.memory_info().rss)

        report = api.v19_build_report_base({"id": "benchmark-" + name, "file_name": name + ".zip"})
        with ExitStack() as stack:
            for owner, attr, key in [
                (api, "image_info", "A_image_dimensions"),
                (StorageManager, "upload_object", "B_storage_upload"),
                (LocalStorageProvider, "_atomic_copy", "C_copy_fsync_and_same_pass_sha256"),
                (api, "sha256_file", "C_fallback_sha256"),
                (api, "_v50_assert_dataset_writable_locked", "D_dataset_admission"),
                (api, "_v50_recover_dataset_deletions", "E_delete_recovery"),
                (api, "_v50_clear_orphan_dataset_delete_claims", "F_orphan_claims"),
                (MaterialRepository, "read", "G_full_material_read"),
                (api, "write_annotation", "H_annotation_conversion_staging"),
                (AnnotationRepository, "upsert_many", "H_annotation_durable_commit"),
                (api, "_v50_end_image_batch", "I_final_batch_commit"),
            ]:
                stack.enter_context(timed(owner, attr, key))
            stack.enter_context(patch.object(MaterialRepository, "_connect", traced_connect))
            stack.enter_context(patch.object(api, "add_image_record", measured_add))
            started = time.perf_counter()
            api._v50_begin_image_batch(pid)
            try:
                assert api._v18_import_yolo(pid, source, "default", report)
                api._v50_end_image_batch(save=True)
            except BaseException:
                if api._v50_active_image_batch(pid):
                    api._v50_end_image_batch(save=False)
                raise
            elapsed = time.perf_counter() - started
        ids = report["imported_image_ids"]
        assert len(ids) == incoming and report["boxes"] == incoming
        assert repository.count() == existing + incoming
        annotation_repository = AnnotationRepository(api.project_dir(pid))
        verified = 0
        for offset in range(0, len(ids), 500):
            for row in repository.get_many(ids[offset:offset + 500]):
                assert (row["width"], row["height"], row["content_sha256"]) == (32, 32, expected_sha)
                annotation = annotation_repository.get(row["id"])
                assert len(annotation["boxes"]) == 1
                box = annotation["boxes"][0]
                assert box["label"] == "target" and box["class_id"] == 0
                assert [box[k] for k in ("x1", "y1", "x2", "y2")] == [8.0, 8.0, 24.0, 24.0]
                verified += 1
        assert verified == incoming
        result = {"case": name, "existing": existing, "incoming": incoming,
                  "elapsed_seconds": elapsed, "images_per_second": incoming / elapsed,
                  "mean_image_seconds": statistics.mean(latencies),
                  "p50_image_seconds": statistics.median(latencies),
                  "p95_image_seconds": sorted(latencies)[int((len(latencies) - 1) * .95)],
                  "stage_seconds": dict(durations), "calls": dict(calls),
                  "rss_start_bytes": rss_start, "rss_sampled_peak_bytes": rss_peak,
                  "rss_after_bytes": process.memory_info().rss,
                  "imported": incoming, "verified_material_and_gt": verified,
                  "remote_image_reads": 0}
        output["results"].append(result)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps({k: result[k] for k in ("case", "existing", "incoming", "elapsed_seconds", "images_per_second")}), flush=True)
    print("Aggregated evidence saved to", args.output, flush=True)


if __name__ == "__main__":
    main()
