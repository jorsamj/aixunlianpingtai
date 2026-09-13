from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_PATH = ROOT / "app.py"


OLD = '''def v19_write_job(project_id: str, job: Dict[str, Any]):
    job["updated_at"] = now_iso()
    f = v19_job_file(project_id, job["id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    persisted = dict(job)
    images = persisted.pop("images", None)
    if isinstance(images, list):
        v19_write_scan_images(project_id, str(job["id"]), images)
        persisted["scan_images_ref"] = "scan-images.json"
    write_json(f, persisted)
'''

NEW = '''def v19_write_job(project_id: str, job: Dict[str, Any]):
    job["updated_at"] = now_iso()
    f = v19_job_file(project_id, job["id"])
    f.parent.mkdir(parents=True, exist_ok=True)
    persisted = dict(job)
    images = persisted.pop("images", None)
    if isinstance(images, list):
        v19_write_scan_images(project_id, str(job["id"]), images)
        persisted["scan_images_ref"] = "scan-images.json"
    # v19 job.json is the browser-visible progress truth. Never expose a
    # truncated JSON document while the worker is updating progress.
    atomic_write_json(f, persisted)
'''


def main() -> None:
    text = APP_PATH.read_text(encoding="utf-8")
    count = text.count(OLD)
    if count != 1:
        raise RuntimeError(f"expected one v19_write_job block, found {count}")
    APP_PATH.write_text(text.replace(OLD, NEW, 1), encoding="utf-8")


if __name__ == "__main__":
    main()
