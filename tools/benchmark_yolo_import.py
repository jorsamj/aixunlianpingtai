#!/usr/bin/env python3
"""Measure real local YOLO import phases without mutating project data.

This benchmark is intentionally read-only for the dataset.  It exercises the
same LocalStorageProvider, ImportCandidateStore, YoloImportScanner and image
inspection code used by the durable Storage Worker, but stores its temporary
manifest outside the project and never writes MaterialRepository/annotations.

Examples:
  python tools/benchmark_yolo_import.py --root /data/datasets/D-Fire_raw --yaml data.yaml
  python tools/benchmark_yolo_import.py --root /data/storage --prefix imports/my-dataset --yaml imports/my-dataset/data.yaml

Use --limit-images only for diagnostics.  Acceptance runs for 10k/50k/100k
must omit it so every dataset image is hashed and verified.
"""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.storage.import_tasks import StorageImportHandler, iter_provider_objects
from platform_core.storage.local import LocalStorageProvider
from platform_core.storage.models import StorageType
from platform_core.storage.yolo_import import YoloImportScanner


def _seconds(start: float) -> float:
    return round(time.perf_counter() - start, 6)


def _rate(count: int, seconds: float) -> float:
    return round(count / seconds, 2) if seconds > 0 else 0.0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark durable local YOLO import phases")
    parser.add_argument("--root", required=True, help="Local Storage Source root")
    parser.add_argument("--prefix", default="", help="Dataset prefix relative to root")
    parser.add_argument("--yaml", default="", help="Dataset YAML path relative to root")
    parser.add_argument("--workers", type=int, default=0, help="Image verify/hash workers; 0=auto")
    parser.add_argument("--limit-images", type=int, default=0, help="Diagnostic cap; 0=all images")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    root = Path(args.root).expanduser().resolve()
    if not root.is_dir():
        raise SystemExit(f"root is not a directory: {root}")
    workers = args.workers or min(8, max(1, int(os.cpu_count() or 1)))
    workers = max(1, min(workers, 16))

    provider = LocalStorageProvider("benchmark-local", root)
    source = SimpleNamespace(id="benchmark-local", type=StorageType.LOCAL.value)
    observed_progress = {"last": "", "ticks": 0}

    def progress(key: str) -> None:
        observed_progress["last"] = str(key)
        observed_progress["ticks"] += 1

    with tempfile.TemporaryDirectory(prefix="mc-yolo-benchmark-") as temporary:
        store = ImportCandidateStore(Path(temporary) / "candidates.sqlite3", import_id="benchmark")
        scanner = YoloImportScanner(
            provider,
            store,
            iter_provider_objects,
            cancelled=lambda: False,
            progress=progress,
        )

        started_total = time.perf_counter()
        started = time.perf_counter()
        detected = scanner.prepare(
            "yolo",
            prefix=args.prefix,
            recursive=True,
            dataset_yaml=args.yaml or None,
        )
        prepare_seconds = _seconds(started)
        if detected != "yolo":
            raise RuntimeError(f"expected yolo, got {detected}")

        images = []
        started = time.perf_counter()
        for item in scanner.iter_images():
            images.append(item)
            if args.limit_images and len(images) >= args.limit_images:
                break
        enumerate_seconds = _seconds(started)

        started = time.perf_counter()
        if workers == 1:
            inspected = [StorageImportHandler._inspect(provider, source, item) for item in images]
        else:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="benchmark-inspect") as executor:
                inspected = list(executor.map(
                    lambda item: StorageImportHandler._inspect(provider, source, item),
                    images,
                ))
        inspect_seconds = _seconds(started)
        valid = sum(row.get("status") == "IMPORTABLE" for row in inspected)
        invalid = len(inspected) - valid
        inspected_bytes = sum(max(0, int(row.get("size_bytes") or 0)) for row in inspected)

        annotation_seconds = None
        quality = None
        if not args.limit_images:
            started = time.perf_counter()
            quality = scanner.scan_annotations()
            annotation_seconds = _seconds(started)

        total_seconds = _seconds(started_total)
        result = {
            "root": str(root),
            "prefix": args.prefix,
            "yaml": scanner.yaml_key,
            "workers": workers,
            "image_count": len(images),
            "valid_images": valid,
            "invalid_images": invalid,
            "image_bytes": inspected_bytes,
            "timings_seconds": {
                "inventory_and_layout": prepare_seconds,
                "enumerate_manifest_images": enumerate_seconds,
                "image_verify_and_sha256": inspect_seconds,
                "annotation_scan": annotation_seconds,
                "total": total_seconds,
            },
            "rates": {
                "image_verify_and_sha256_per_second": _rate(len(images), inspect_seconds),
                "total_images_per_second": _rate(len(images), total_seconds),
                "mib_hashed_per_second": round(
                    (inspected_bytes / 1024 / 1024) / inspect_seconds, 2
                ) if inspect_seconds > 0 else 0.0,
            },
            "quality": quality,
            "progress_ticks": observed_progress["ticks"],
            "last_progress_key": observed_progress["last"],
            "notes": [
                "Dataset source is read-only; benchmark manifest is temporary.",
                "This excludes final MaterialRepository/AnnotationRepository indexing.",
                "Use the durable server_zip task for end-to-end ZIP extraction/index acceptance.",
            ],
        }
        print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
