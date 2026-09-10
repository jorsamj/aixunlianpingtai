from __future__ import annotations

"""One-shot, fail-closed patch for the legacy browser ZIP entry points.

app.py is intentionally kept as a compatibility surface and is unusually large.
This script applies two tiny audited edits without replacing unrelated legacy
code. It is idempotent and refuses to write if the expected source shape changed.
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
    if updated != original:
        APP.write_text(updated, encoding="utf-8", newline="\n")
        print("patched app.py browser YOLO ZIP entry to durable Storage Worker")
    else:
        print("app.py durable browser ZIP bridge already installed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
