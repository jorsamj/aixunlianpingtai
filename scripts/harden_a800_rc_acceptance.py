from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, found {count}: {old[:140]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


script = "a800_rc_acceptance.py"
replace_once(script, "import argparse\nimport json", "import argparse\nimport hashlib\nimport json")
replace_once(
    script,
    "def _json(path: Path, default: Any = None) -> Any:\n    if not path.is_file():\n        return default\n    return json.loads(path.read_text(encoding=\"utf-8\"))\n",
    "def _json(path: Path, default: Any = None) -> Any:\n    if not path.is_file():\n        return default\n    return json.loads(path.read_text(encoding=\"utf-8\"))\n\n\ndef _sha256(path: Path) -> str:\n    digest = hashlib.sha256()\n    with path.open(\"rb\") as stream:\n        for chunk in iter(lambda: stream.read(1024 * 1024), b\"\"):\n            digest.update(chunk)\n    return digest.hexdigest()\n",
)
replace_once(
    script,
    "    verified_models = result.get(\"verified_models\") or []\n    report.add(\"verified trained model exists\", bool(verified_models), expected=\">=1 verified model\", actual=verified_models)\n\n    report.evidence[\"resources\"] = {",
    "    verified_models = result.get(\"verified_models\") or []\n    model_evidence = []\n    for item in verified_models:\n        ref = str(item.get(\"ref\") or \"\") if isinstance(item, dict) else str(item or \"\")\n        model_path = task_root / ref if ref else task_root / \"__missing_model_ref__\"\n        size = model_path.stat().st_size if model_path.is_file() else None\n        digest = _sha256(model_path) if size and size > 0 else None\n        expected_size = item.get(\"size_bytes\") if isinstance(item, dict) else None\n        expected_sha = str(item.get(\"sha256\") or \"\") if isinstance(item, dict) else \"\"\n        ok = bool(size and size > 0)\n        if expected_size is not None:\n            ok = ok and int(expected_size) == int(size or -1)\n        if expected_sha:\n            ok = ok and digest == expected_sha\n        model_evidence.append({\"ref\": ref, \"path\": str(model_path), \"size\": size, \"sha256\": digest, \"ok\": ok})\n    report.evidence[\"verified_models\"] = model_evidence\n    report.add(\"verified trained model artifacts are intact\", bool(model_evidence) and all(row[\"ok\"] for row in model_evidence),\n               expected=\"all verified model refs exist with matching size/SHA256\", actual=model_evidence)\n\n    report.evidence[\"resources\"] = {",
)
replace_once(
    script,
    "    report.evidence[\"iteration\"] = {\n        \"base_version_name\": result.get(\"base_version_name\") or job.get(\"base_version_name\"),\n        \"base_selection_reason\": result.get(\"base_selection_reason\") or job.get(\"base_selection_reason\"),\n    }\n    return report",
    "    base_version_id = str(result.get(\"base_version_id\") or job.get(\"base_version_id\") or \"\")\n    base_version_name = str(result.get(\"base_version_name\") or job.get(\"base_version_name\") or \"\")\n    base_reason = str(result.get(\"base_selection_reason\") or job.get(\"base_selection_reason\") or \"\")\n    report.evidence[\"iteration\"] = {\n        \"base_version_id\": base_version_id,\n        \"base_version_name\": base_version_name,\n        \"base_selection_reason\": base_reason,\n    }\n    if args.require_iteration:\n        algorithms_path = data_dir / \"projects\" / args.project_id / \"algorithms.json\"\n        algorithms = _json(algorithms_path, []) or []\n        algorithm_id = str(job.get(\"asset_algorithm_id\") or job.get(\"algorithm_asset_id\") or \"\")\n        algorithm = next((row for row in algorithms if str(row.get(\"id\") or \"\") == algorithm_id), None)\n        versions = list((algorithm or {}).get(\"versions\") or [])\n        successful = {\"SUCCEEDED\", \"PARTIAL_SUCCESS\", \"DONE\", \"FINISHED\", \"COMPLETED\"}\n        eligible = [row for row in versions\n                    if str(row.get(\"training_status\") or \"\").upper() in successful\n                    and row.get(\"artifact_verified\") is True\n                    and row.get(\"trainable\") is not False\n                    and str(row.get(\"framework\") or \"ultralytics\").lower() == \"ultralytics\"]\n        eligible.sort(key=lambda row: str(row.get(\"finished_at\") or row.get(\"created_at\") or row.get(\"version_name\") or \"\"), reverse=True)\n        expected_base = eligible[0] if eligible else None\n        expected_base_id = str((expected_base or {}).get(\"id\") or \"\")\n        report.evidence[\"iteration\"].update({\n            \"algorithm_id\": algorithm_id,\n            \"algorithms_path\": str(algorithms_path),\n            \"expected_latest_successful_version_id\": expected_base_id,\n        })\n        report.add(\"iteration uses latest verified version reason\", base_reason == \"latest_verified_version\",\n                   expected=\"latest_verified_version\", actual=base_reason)\n        report.add(\"iteration base is latest successful trainable version\", bool(expected_base_id) and base_version_id == expected_base_id,\n                   expected=expected_base_id, actual=base_version_id)\n        if args.expected_base_version:\n            expected_literal = str(args.expected_base_version)\n            report.add(\"iteration base matches explicitly expected version\",\n                       expected_literal in {base_version_id, base_version_name},\n                       expected=expected_literal, actual={\"id\": base_version_id, \"name\": base_version_name})\n    return report",
)
replace_once(
    script,
    "    verify.add_argument(\"--expected-cache\", action=argparse.BooleanOptionalAction, default=False)\n    verify.set_defaults(handler=verify_job)",
    "    verify.add_argument(\"--expected-cache\", action=argparse.BooleanOptionalAction, default=False)\n    verify.add_argument(\"--require-iteration\", action=\"store_true\", help=\"要求本任务严格从最新成功可训练版本继续训练\")\n    verify.add_argument(\"--expected-base-version\", default=None, help=\"可选：进一步锁定期望的 base version id 或 version_name\")\n    verify.set_defaults(handler=verify_job)",
)

test = "tests/unit/test_a800_rc_acceptance.py"
text = Path(test).read_text(encoding="utf-8")
replace_once(test, "import argparse\nimport json", "import argparse\nimport hashlib\nimport json")
replace_once(
    test,
    "    result = {\n        \"snapshot_id\": \"snap-rc\",",
    "    model_bytes = b\"verified-model\"\n    model_sha = hashlib.sha256(model_bytes).hexdigest()\n    result = {\n        \"snapshot_id\": \"snap-rc\",",
)
replace_once(test, "\"verified_models\": [{\"ref\": \"outputs/00_best.pt\", \"sha256\": \"abc\"}],", "\"verified_models\": [{\"ref\": \"outputs/00_best.pt\", \"sha256\": model_sha, \"size_bytes\": len(model_bytes)}],")
replace_once(test, "    model.write_bytes(b\"verified-model\")", "    model.write_bytes(model_bytes)")
replace_once(
    test,
    "        expected_device=\"0\",\n        output=None,",
    "        expected_device=\"0\",\n        require_iteration=False,\n        expected_base_version=None,\n        output=None,",
)
append = r'''

def test_verify_job_rejects_missing_verified_model_artifact(tmp_path):
    data_dir, job_path, task_id = _fixture(tmp_path)
    model = data_dir / "task_runtime" / "artifacts" / task_id / "outputs" / "00_best.pt"
    model.unlink()
    report = rc.verify_job(_args(data_dir, job_path, task_id))
    assert report.ok is False
    failed = {row.name for row in report.checks if not row.ok}
    assert "verified trained model artifacts are intact" in failed


def test_verify_iteration_matches_latest_successful_trainable_version(tmp_path):
    data_dir, job_path, task_id = _fixture(tmp_path)
    job = json.loads(job_path.read_text(encoding="utf-8"))
    job.update({
        "asset_algorithm_id": "alg-1",
        "base_version_id": "v-good-new",
        "base_version_name": "20260911090000",
        "base_selection_reason": "latest_verified_version",
    })
    job_path.write_text(json.dumps(job), encoding="utf-8")
    result_path = data_dir / "task_runtime" / "artifacts" / task_id / "result.json"
    result = json.loads(result_path.read_text(encoding="utf-8"))
    result.update({
        "base_version_id": "v-good-new",
        "base_version_name": "20260911090000",
        "base_selection_reason": "latest_verified_version",
    })
    result_path.write_text(json.dumps(result), encoding="utf-8")
    algorithms = [{
        "id": "alg-1",
        "versions": [
            {"id": "v-failed-later", "version_name": "20260911100000", "finished_at": "2026-09-11T10:00:00Z", "training_status": "FAILED", "artifact_verified": False, "framework": "ultralytics"},
            {"id": "v-good-new", "version_name": "20260911090000", "finished_at": "2026-09-11T09:00:00Z", "training_status": "SUCCEEDED", "artifact_verified": True, "trainable": True, "framework": "ultralytics"},
            {"id": "v-good-old", "version_name": "20260910090000", "finished_at": "2026-09-10T09:00:00Z", "training_status": "SUCCEEDED", "artifact_verified": True, "trainable": True, "framework": "ultralytics"},
        ],
    }]
    algorithms_path = data_dir / "projects" / "project-rc" / "algorithms.json"
    _write(algorithms_path, algorithms)
    args = _args(data_dir, job_path, task_id)
    args.require_iteration = True
    args.expected_base_version = "v-good-new"
    report = rc.verify_job(args)
    assert report.ok, json.dumps(report.as_dict(), ensure_ascii=False, indent=2)
    assert report.evidence["iteration"]["expected_latest_successful_version_id"] == "v-good-new"
'''
current = Path(test).read_text(encoding="utf-8")
if "test_verify_job_rejects_missing_verified_model_artifact" in current:
    raise SystemExit("tests already appended")
Path(test).write_text(current.rstrip() + append + "\n", encoding="utf-8")
print("hardened A800 RC verifier and tests")
