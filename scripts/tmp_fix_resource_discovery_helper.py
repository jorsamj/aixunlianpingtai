from pathlib import Path

helper_path = Path("scripts/tmp_resource_discovery_p1_patch.py")
text = helper_path.read_text(encoding="utf-8")

start = text.index("# Expose the exact durable discovery request")
end = text.index("# Render durable roots", start)
replacement = '''# Expose the exact durable discovery request that the API froze before queueing.\nreplace_once(\n    "app.py",\n    ''' + "'''" + '''    response["progress_determinate"] = False\n    progress = shared_task_artifacts().read_json(\n''' + "'''" + ''',\n    ''' + "'''" + '''    response["progress_determinate"] = False\n    request_payload = shared_task_artifacts().read_json(\n        task.task_id, "request.json", default={}\n    )\n    if not isinstance(request_payload, dict):\n        request_payload = {}\n    scan_roots = [\n        str(root).strip()\n        for root in (request_payload.get("roots") or [])\n        if str(root).strip()\n    ]\n    response["discovery_scope"] = str(request_payload.get("scope") or "").strip().lower()\n    response["scan_roots"] = scan_roots\n    response["scan_root_count"] = len(scan_roots)\n    progress = shared_task_artifacts().read_json(\n''' + "'''" + ''',\n)\n\n'''
text = text[:start] + replacement + text[end:]
text = text.replace("assert 'read_json(task.task_id, \"request.json\", default={})' in source", "assert '\"request.json\"' in source")
text = text.replace("assert 'public[\"discovery_scope\"]' in source", "assert 'response[\"discovery_scope\"]' in source")
text = text.replace("assert 'public[\"scan_roots\"] = scan_roots' in source", "assert 'response[\"scan_roots\"] = scan_roots' in source")
text = text.replace("assert 'public[\"scan_root_count\"] = len(scan_roots)' in source", "assert 'response[\"scan_root_count\"] = len(scan_roots)' in source")
helper_path.write_text(text, encoding="utf-8")
Path(__file__).unlink()
