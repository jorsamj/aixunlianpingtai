from __future__ import annotations

"""One-shot, fail-closed patches for the legacy browser ZIP compatibility surface.

app.py is intentionally kept as a compatibility surface and is unusually large.
This script applies tiny audited edits without replacing unrelated legacy code.
It is idempotent and refuses to write if the expected source shape changed.
"""

from pathlib import Path


APP = Path(__file__).resolve().parents[1] / "app.py"

READ_OLD = '''def v19_read_job(project_id: str, job_id: str) -> Dict[str, Any]:
    f = v19_job_file(project_id, job_id)
    if not f.exists():
        raise HTTPException(status_code=404, detail="导入任务不存在")
    return read_json(f, {})
'''

READ_NEW = '''def v19_read_job(project_id: str, job_id: str) -> Dict[str, Any]:
    f = v19_job_file(project_id, job_id)
    if not f.exists():
        raise HTTPException(status_code=404, detail="导入任务不存在")
    job = read_json(f, {})
    if isinstance(job, dict) and job.get("durable_task_id"):
        try:
            from platform_core.storage.browser_v19_bridge import reconcile_v19_job
            return reconcile_v19_job(DATA_DIR, project_id, job_id, job)
        except Exception:
            # Compatibility GET remains readable; durable diagnostics stay in
            # TaskRepository/artifacts and the worker can continue independently.
            return job
    return job
'''

WORKER_OLD = '''def v19_import_worker(project_id: str, dataset_id: str, job_id: str, selected_paths: List[str]):
    job = v19_read_job(project_id, job_id)
'''

WORKER_NEW = '''def v19_import_worker(project_id: str, dataset_id: str, job_id: str, selected_paths: List[str]):
    # Modern YOLO ZIPs are orchestration-only here. All heavy validation,
    # extraction, image hash/verify, annotation scan and indexing run in the
    # durable Storage Worker. Unsupported/legacy formats keep the old parser.
    from platform_core.storage.browser_v19_entry import try_run_browser_v19_bridge
    if try_run_browser_v19_bridge(DATA_DIR, project_id, dataset_id, job_id, selected_paths):
        return
    job = v19_read_job(project_id, job_id)
'''

SCAN_OLD = '''def v19_scan_zip(zip_path: Path) -> Dict[str, Any]:
    images: List[Dict[str, Any]] = []
    hints = set()
    file_count = 0
    total_size = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = v19_normalize_zip_path(info.filename)
            if not name or name.endswith("/"):
                continue
            file_count += 1
            total_size += max(0, int(getattr(info, "file_size", 0) or 0))
            low = name.lower()
            suffix = Path(low).suffix
            if suffix in IMAGE_EXTS:
                images.append({
                    "path": name,
                    "name": Path(name).name,
                    "split": _v18_split_from_path(Path(name)),
                    "size_kb": round((info.file_size or 0) / 1024, 1),
                })
            if low.endswith("data.yaml") or low.endswith("data.yml") or "/labels/" in low:
                hints.add("YOLO")
            if low.endswith(".json") and ("coco" in low or "annotation" in low or "_annotations" in low):
                hints.add("COCO")
            if low.endswith(".xml"):
                hints.add("VOC")
    return {
        "file_count": file_count,
        "image_count": len(images),
        "images": images,
        "format_hints": sorted(hints) or ["未知"],
        "uncompressed_size_mb": round(total_size / 1024 / 1024, 2),
    }
'''

SCAN_NEW = '''def v19_scan_zip(zip_path: Path) -> Dict[str, Any]:
    # Compatibility preview only: never serialize 10k/50k/100k image rows into
    # job.json or the upload response. The durable Storage Worker owns the full
    # candidate manifest after /start.
    try:
        preview_limit = int(os.environ.get("MC_BROWSER_ZIP_PREVIEW_IMAGES", "500") or 500)
    except (TypeError, ValueError):
        preview_limit = 500
    preview_limit = max(50, min(2000, preview_limit))
    images: List[Dict[str, Any]] = []
    image_count = 0
    hints = set()
    file_count = 0
    total_size = 0
    with zipfile.ZipFile(zip_path, "r") as zf:
        for info in zf.infolist():
            name = v19_normalize_zip_path(info.filename)
            if not name or name.endswith("/"):
                continue
            file_count += 1
            total_size += max(0, int(getattr(info, "file_size", 0) or 0))
            low = name.lower()
            suffix = Path(low).suffix
            if suffix in IMAGE_EXTS:
                image_count += 1
                if len(images) < preview_limit:
                    images.append({
                        "path": name,
                        "name": Path(name).name,
                        "split": _v18_split_from_path(Path(name)),
                        "size_kb": round((info.file_size or 0) / 1024, 1),
                    })
            if low.endswith("data.yaml") or low.endswith("data.yml") or low.endswith("dataset.yaml") or "/labels/" in low:
                hints.add("YOLO")
            if low.endswith(".json") and ("coco" in low or "annotation" in low or "_annotations" in low):
                hints.add("COCO")
            if low.endswith(".xml"):
                hints.add("VOC")
    return {
        "file_count": file_count,
        "image_count": image_count,
        "images": images,
        "images_preview_count": len(images),
        "images_truncated": image_count > len(images),
        "format_hints": sorted(hints) or ["未知"],
        "uncompressed_size_mb": round(total_size / 1024 / 1024, 2),
    }
'''


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if new in text:
        return text
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"refusing to patch {label}: expected exactly one source block, found {count}")
    return text.replace(old, new, 1)


def main() -> int:
    original = APP.read_text(encoding="utf-8")
    updated = replace_once(original, READ_OLD, READ_NEW, "v19_read_job")
    updated = replace_once(updated, WORKER_OLD, WORKER_NEW, "v19_import_worker")
    updated = replace_once(updated, SCAN_OLD, SCAN_NEW, "v19_scan_zip")
    if updated != original:
        APP.write_text(updated, encoding="utf-8", newline="\n")
        print("patched app.py browser YOLO ZIP compatibility path")
    else:
        print("app.py browser ZIP scale patches already installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
