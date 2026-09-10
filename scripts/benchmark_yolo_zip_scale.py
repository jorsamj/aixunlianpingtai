from __future__ import annotations

"""Measure the real 42.25 YOLO ZIP discovery path without mutating project data.

This benchmark intentionally exercises the production ZIP extractor, local
storage provider, disk-backed YOLO manifest, image validation/SHA256 path, and
annotation parser.  It does not create MaterialRepository rows, so it is safe to
run against a copy of a dataset or against a ZIP in a scratch directory.

Examples
--------
python scripts/benchmark_yolo_zip_scale.py --zip /data/incoming/dataset.zip --work-dir /data/bench/yolo-10k
python scripts/benchmark_yolo_zip_scale.py --dataset-root /data/datasets/D-Fire_raw --workers 8
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
from typing import Iterable

# Allow execution from the repository root without installing the package.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from platform_core.storage.import_candidates import ImportCandidateStore
from platform_core.storage.import_tasks import StorageImportHandler, iter_provider_objects
from platform_core.storage.local import LocalStorageProvider
from platform_core.storage.zip_import import extract_server_zip, finalize_server_zip_publication
from platform_core.storage.yolo_import import YoloImportScanner


BATCH_SIZE = 500


def _seconds(started: float) -> float:
    return round(max(0.0, time.perf_counter() - started), 6)


def _rate(count: int, seconds: float) -> float:
    return round(count / seconds, 3) if seconds > 0 else 0.0


def _mib_per_second(byte_count: int, seconds: float) -> float:
    return round(byte_count / (1024 * 1024) / seconds, 3) if seconds > 0 else 0.0


def _inspect_images(
    scanner: YoloImportScanner,
    provider: LocalStorageProvider,
    *,
    workers: int,
) -> dict:
    source = SimpleNamespace(id="benchmark-local", type="local")
    counts = {"IMPORTABLE": 0, "INVALID": 0, "FAILED": 0, "SKIPPED": 0}
    image_count = 0
    byte_count = 0
    started = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="bench-inspect") if workers > 1 else None
    batch = []

    def consume(items: Iterable[object]) -> None:
        nonlocal image_count, byte_count
        if executor is None:
            rows = [StorageImportHandler._inspect(provider, source, item) for item in items]
        else:
            rows = list(executor.map(lambda item: StorageImportHandler._inspect(provider, source, item), items))
        for row in rows:
            status = str(row.get("status") or "FAILED")
            counts[status] = counts.get(status, 0) + 1
            if status != "SKIPPED":
                image_count += 1
                byte_count += max(0, int(row.get("size_bytes") or 0))

    try:
        for item in scanner.iter_images():
            batch.append(item)
            if len(batch) >= BATCH_SIZE:
                consume(batch)
                batch.clear()
        if batch:
            consume(batch)
    finally:
        if executor is not None:
            executor.shutdown(wait=True, cancel_futures=True)

    elapsed = _seconds(started)
    return {
        "seconds": elapsed,
        "images": image_count,
        "bytes": byte_count,
        "images_per_second": _rate(image_count, elapsed),
        "mib_per_second": _mib_per_second(byte_count, elapsed),
        "status_counts": counts,
    }


def _dataset_yaml_key(prefix: str, dataset_yaml: str | None) -> str | None:
    if not dataset_yaml:
        return None
    value = str(dataset_yaml).replace("\\", "/").lstrip("/")
    root = str(prefix or "").strip("/")
    if root and value != root and not value.startswith(root + "/"):
        value = f"{root}/{value}"
    return value


def benchmark_dataset(
    storage_root: Path,
    *,
    prefix: str = "",
    dataset_yaml: str | None = None,
    workers: int = 8,
    manifest_dir: Path,
) -> dict:
    provider = LocalStorageProvider("benchmark-local", storage_root)
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / "candidates.sqlite3"
    manifest_path.unlink(missing_ok=True)
    for suffix in ("-wal", "-shm"):
        Path(str(manifest_path) + suffix).unlink(missing_ok=True)
    store = ImportCandidateStore(manifest_path, import_id="benchmark")
    scanner = YoloImportScanner(provider, store, iter_provider_objects)

    prepare_started = time.perf_counter()
    detected_format = scanner.prepare(
        "yolo",
        prefix=prefix,
        recursive=True,
        dataset_yaml=_dataset_yaml_key(prefix, dataset_yaml),
    )
    prepare_seconds = _seconds(prepare_started)

    inspection = _inspect_images(scanner, provider, workers=workers)

    annotation_started = time.perf_counter()
    quality = scanner.scan_annotations()
    annotation_seconds = _seconds(annotation_started)

    total_seconds = round(prepare_seconds + inspection["seconds"] + annotation_seconds, 6)
    image_count = int(inspection["images"])
    return {
        "format": detected_format,
        "prefix": prefix,
        "dataset_yaml": scanner.yaml_key,
        "workers": workers,
        "prepare_seconds": prepare_seconds,
        "image_inspection": inspection,
        "annotation_seconds": annotation_seconds,
        "total_scan_seconds": total_seconds,
        "scan_images_per_second": _rate(image_count, total_seconds),
        "quality": quality,
        "manifest_bytes": manifest_path.stat().st_size if manifest_path.exists() else 0,
    }


def benchmark_zip(
    archive: Path,
    *,
    work_dir: Path,
    dataset_yaml: str | None,
    workers: int,
) -> dict:
    storage_root = work_dir / "storage"
    manifest_dir = work_dir / "manifest"
    storage_root.mkdir(parents=True, exist_ok=True)
    prefix = "dataset"
    target = storage_root / prefix
    if target.exists():
        shutil.rmtree(target)
    staging = storage_root / ".import-staging"
    if staging.exists():
        shutil.rmtree(staging)

    extraction_events = 0
    extraction_completed_events = 0

    def progress(event):
        nonlocal extraction_events, extraction_completed_events
        extraction_events += 1
        if event.completed_member is not None:
            extraction_completed_events += 1
        return True

    extract_started = time.perf_counter()
    report = extract_server_zip(
        archive,
        storage_root,
        prefix,
        task_id="benchmark-yolo-zip",
        completed={},
        on_progress=progress,
    )
    extract_seconds = _seconds(extract_started)
    finalize_server_zip_publication(storage_root, prefix, task_id="benchmark-yolo-zip")

    scan = benchmark_dataset(
        storage_root,
        prefix=prefix,
        dataset_yaml=dataset_yaml,
        workers=workers,
        manifest_dir=manifest_dir,
    )
    total_seconds = round(extract_seconds + scan["total_scan_seconds"], 6)
    return {
        "archive": archive.name,
        "archive_bytes": archive.stat().st_size,
        "extracted_files": report.extracted_files,
        "extracted_bytes": report.extracted_bytes,
        "extract_seconds": extract_seconds,
        "extract_mib_per_second": _mib_per_second(report.extracted_bytes, extract_seconds),
        "progress_callback_events": extraction_events,
        "completed_member_events": extraction_completed_events,
        "scan": scan,
        "total_seconds": total_seconds,
        "end_to_end_images_per_second": _rate(int(scan["image_inspection"]["images"]), total_seconds),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark YOLO ZIP/import discovery throughput")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--zip", type=Path, help="YOLO ZIP to extract and scan")
    source.add_argument("--dataset-root", type=Path, help="Already extracted local dataset/storage root")
    parser.add_argument("--prefix", default="", help="Dataset prefix under --dataset-root")
    parser.add_argument("--dataset-yaml", default=None, help="Optional data.yaml path relative to the dataset prefix")
    parser.add_argument("--workers", type=int, default=min(8, max(1, os.cpu_count() or 1)))
    parser.add_argument("--work-dir", type=Path, default=None, help="Scratch directory; required to retain benchmark artifacts")
    parser.add_argument("--json-out", type=Path, default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not 1 <= args.workers <= 16:
        raise SystemExit("--workers must be between 1 and 16")

    temporary = None
    if args.work_dir is None:
        temporary = tempfile.TemporaryDirectory(prefix="yolo-import-benchmark-")
        work_dir = Path(temporary.name)
    else:
        work_dir = args.work_dir.expanduser().resolve()
        work_dir.mkdir(parents=True, exist_ok=True)

    try:
        if args.zip is not None:
            archive = args.zip.expanduser().resolve()
            if not archive.is_file():
                raise SystemExit(f"ZIP does not exist: {archive}")
            result = benchmark_zip(
                archive,
                work_dir=work_dir,
                dataset_yaml=args.dataset_yaml,
                workers=args.workers,
            )
        else:
            root = args.dataset_root.expanduser().resolve()
            if not root.is_dir():
                raise SystemExit(f"dataset root does not exist: {root}")
            result = benchmark_dataset(
                root,
                prefix=args.prefix,
                dataset_yaml=args.dataset_yaml,
                workers=args.workers,
                manifest_dir=work_dir / "manifest",
            )

        result["benchmark_work_dir"] = str(work_dir)
        payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
        print(payload)
        if args.json_out is not None:
            destination = args.json_out.expanduser().resolve()
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(payload + "\n", encoding="utf-8")
        return 0
    finally:
        if temporary is not None:
            temporary.cleanup()


if __name__ == "__main__":
    raise SystemExit(main())
