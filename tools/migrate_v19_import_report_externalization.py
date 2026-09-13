from pathlib import Path


APP = Path(__file__).resolve().parents[1] / 'app.py'


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f'{label}: expected exactly one source match, found {count}')
    return text.replace(old, new, 1)


def main() -> None:
    text = APP.read_text(encoding='utf-8')

    old_helpers = '''def v19_scan_images_file(project_id: str, job_id: str) -> Path:\n    return v19_job_dir(project_id, job_id) / "scan-images.json"\n\n\ndef v19_write_scan_images'''
    new_helpers = '''def v19_scan_images_file(project_id: str, job_id: str) -> Path:\n    return v19_job_dir(project_id, job_id) / "scan-images.json"\n\n\ndef v19_report_file(project_id: str, job_id: str) -> Path:\n    return v19_job_dir(project_id, job_id) / "report.json"\n\n\ndef v19_write_import_report(project_id: str, job_id: str, report: Dict[str, Any]):\n    path = v19_report_file(project_id, job_id)\n    path.parent.mkdir(parents=True, exist_ok=True)\n    atomic_write_json(path, dict(report or {}))\n\n\ndef v19_read_import_report(project_id: str, job_id: str, job: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:\n    current = dict(job or v19_read_job(project_id, job_id) or {})\n    if current.get("report_ref"):\n        value = read_json(v19_report_file(project_id, job_id), {})\n        if isinstance(value, dict):\n            return value\n    value = current.get("report")\n    return dict(value) if isinstance(value, dict) else {}\n\n\ndef v19_write_scan_images'''
    text = replace_once(text, old_helpers, new_helpers, 'v19 report helpers')

    old_persistence = '''    if isinstance(images, list):\n        v19_write_scan_images(project_id, str(job["id"]), images)\n        persisted["scan_images_ref"] = "scan-images.json"\n    # v19 job.json is the browser-visible progress truth. Never expose a\n    # truncated JSON document while the worker is updating progress.\n    atomic_write_json(f, persisted)'''
    new_persistence = '''    if isinstance(images, list):\n        v19_write_scan_images(project_id, str(job["id"]), images)\n        persisted["scan_images_ref"] = "scan-images.json"\n    report = persisted.get("report")\n    if isinstance(report, dict) and "imported_image_ids" in report:\n        v19_write_import_report(project_id, str(job["id"]), report)\n        compact_report = dict(report)\n        compact_report.pop("imported_image_ids", None)\n        persisted["report"] = compact_report\n        persisted["report_ref"] = "report.json"\n    # v19 job.json is the browser-visible progress truth. Never expose a\n    # truncated JSON document while the worker is updating progress.\n    atomic_write_json(f, persisted)'''
    text = replace_once(text, old_persistence, new_persistence, 'v19 report persistence boundary')

    old_review = '''    report = job.get('report') or {}\n    ids = [str(x) for x in (report.get('imported_image_ids') or [])]'''
    new_review = '''    report = v19_read_import_report(project_id, job_id, job)\n    ids = [str(x) for x in (report.get('imported_image_ids') or [])]'''
    text = replace_once(text, old_review, new_review, 'v52 review report owner')

    APP.write_text(text, encoding='utf-8')


if __name__ == '__main__':
    main()
