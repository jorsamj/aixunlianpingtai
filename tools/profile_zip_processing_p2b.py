import argparse
import functools
import io
import json
import os
import shutil
import sys
import tempfile
import time
from collections import defaultdict
from pathlib import Path

from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--images", type=int, default=1000)
    return parser.parse_args()


def tiny_jpeg() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buffer, format="JPEG", quality=75)
    return buffer.getvalue()


def main():
    args = parse_args()
    root = Path(tempfile.mkdtemp(prefix="zip-processing-p2b-profile-")).resolve()
    os.environ["MC_TRAIN_DATA_DIR"] = str(root / "platform-data")
    os.environ["MC_PLATFORM_VERSION"] = "test"

    import app
    from platform_core.annotation_repository import AnnotationRepository
    from platform_core.material_repository import MaterialRepository
    from platform_core.storage import StorageManager

    project = app.create_project(app.ProjectCreate(name="zip-processing-p2b-profile", labels=[]))
    project_id = project["id"]
    app.ensure_default_datasets(project_id)

    dataset = root / "source"
    images_dir = dataset / "images" / "train"
    labels_dir = dataset / "labels" / "train"
    images_dir.mkdir(parents=True, exist_ok=True)
    labels_dir.mkdir(parents=True, exist_ok=True)
    payload = tiny_jpeg()
    for index in range(args.images):
        stem = f"image_{index:05d}"
        (images_dir / f"{stem}.jpg").write_bytes(payload)
        (labels_dir / f"{stem}.txt").write_text(
            "0 0.5 0.5 0.5 0.5\n", encoding="utf-8"
        )
    (dataset / "data.yaml").write_text(
        "train: images/train\nnames: [object]\n", encoding="utf-8"
    )

    timings = defaultdict(float)
    counts = defaultdict(int)
    restores = []

    def instrument(owner, name, key):
        original = getattr(owner, name)

        @functools.wraps(original)
        def wrapped(*call_args, **call_kwargs):
            started = time.perf_counter()
            try:
                return original(*call_args, **call_kwargs)
            finally:
                counts[key] += 1
                timings[key] += time.perf_counter() - started

        setattr(owner, name, wrapped)
        restores.append((owner, name, original))

    # Nested timings intentionally overlap. They answer which operations dominate
    # the real import loop without changing product code or transaction boundaries.
    instrument(app, "add_image_record", "add_image_record")
    instrument(app, "image_info", "image_info")
    instrument(app, "sha256_file", "sha256_file")
    instrument(app, "write_annotation", "write_annotation")
    instrument(app, "_v18_set_image_split", "set_image_split")
    instrument(app, "_v50_assert_dataset_writable_locked", "dataset_writable_check")
    instrument(app, "_v50_queue_image_patch", "queue_image_patch")
    instrument(app, "get_project", "get_project")
    instrument(StorageManager, "upload_object", "storage_upload_object")
    instrument(AnnotationRepository, "_connect", "annotation_connect")
    instrument(AnnotationRepository, "upsert_many", "annotation_upsert_many")
    instrument(MaterialRepository, "patch", "material_patch")
    instrument(MaterialRepository, "mutate", "material_mutate")

    report = app.v19_build_report_base({"id": "profile", "file_name": "profile.zip"})
    imported = False
    import_seconds = 0.0
    commit_seconds = 0.0
    try:
        started = time.perf_counter()
        app._v50_begin_image_batch(project_id)
        try:
            imported = app._v18_import_yolo(project_id, dataset, "default", report)
            import_seconds = time.perf_counter() - started
            commit_started = time.perf_counter()
            app._v50_end_image_batch(save=True)
            commit_seconds = time.perf_counter() - commit_started
        except BaseException:
            app._v50_end_image_batch(save=False)
            raise
    finally:
        for owner, name, original in reversed(restores):
            setattr(owner, name, original)

    material_summary = app.material_store(project_id).summary()
    annotation_summary = AnnotationRepository(app.project_dir(project_id)).summary()
    wall_seconds = import_seconds + commit_seconds
    assert imported is True
    assert int(report.get("imported_images") or 0) == args.images, report
    assert int(report.get("boxes") or 0) == args.images, report
    assert int(material_summary.get("total") or 0) == args.images, material_summary
    assert int(material_summary.get("boxes") or 0) == args.images, material_summary
    assert int(annotation_summary.get("total") or 0) == args.images, annotation_summary
    assert int(annotation_summary.get("annotated") or 0) == args.images, annotation_summary

    metrics = {}
    for key in sorted(set(counts) | set(timings)):
        seconds = timings[key]
        count = counts[key]
        metrics[key] = {
            "count": count,
            "seconds": round(seconds, 6),
            "per_call_ms": round(seconds * 1000 / count, 4) if count else 0.0,
            "wall_share_pct": round(seconds * 100 / wall_seconds, 2) if wall_seconds else 0.0,
        }

    result = {
        "images": args.images,
        "import_seconds": round(import_seconds, 6),
        "commit_seconds": round(commit_seconds, 6),
        "wall_seconds": round(wall_seconds, 6),
        "report_imported_images": int(report.get("imported_images") or 0),
        "report_boxes": int(report.get("boxes") or 0),
        "material_total": int(material_summary.get("total") or 0),
        "material_boxes": int(material_summary.get("boxes") or 0),
        "annotation_total": int(annotation_summary.get("total") or 0),
        "annotation_annotated": int(annotation_summary.get("annotated") or 0),
        "metrics": metrics,
    }
    print("P2B_PROFILE=" + json.dumps(result, ensure_ascii=False, sort_keys=True))
    print("P2B_TOP_CUMULATIVE")
    for key, value in sorted(metrics.items(), key=lambda item: item[1]["seconds"], reverse=True):
        print(
            f"{key}: count={value['count']} seconds={value['seconds']:.6f} "
            f"per_call_ms={value['per_call_ms']:.4f} wall_share={value['wall_share_pct']:.2f}%"
        )

    shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    main()
