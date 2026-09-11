from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import yaml


SUCCESS_STATUSES = {"done", "finished", "completed", "succeeded", "success"}
DEFAULT_DATA_DIR = Path("/data/platform-data")
DEFAULT_BASE_URL = "http://127.0.0.1:8010"


def _json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _http_json(base_url: str, path: str, timeout: float = 10.0) -> Any:
    url = f"{base_url.rstrip('/')}/{path.lstrip('/')}"
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {error.code} {url}: {body[:1000]}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"无法访问 {url}: {error}") from error


def _cache(value: Any) -> Any:
    if value is False or value is True:
        return value
    raw = str(value if value is not None else "").strip().lower()
    if raw in {"", "false", "0", "no", "off", "none"}:
        return False
    if raw in {"true", "1", "yes", "on", "ram"}:
        return "ram"
    if raw == "disk":
        return "disk"
    return value


def _device(value: Any) -> str:
    raw = str(value if value is not None else "").strip().lower()
    if raw.startswith("cuda:"):
        raw = raw.split(":", 1)[1]
    return raw


def _label_codes(schema: Iterable[dict[str, Any]]) -> list[str]:
    rows = sorted(
        (dict(row) for row in schema if str(row.get("code") or "").strip()),
        key=lambda row: (int(row.get("class_id", 10**9)), str(row.get("code"))),
    )
    return [str(row["code"]) for row in rows]


def _yaml_names(data: dict[str, Any]) -> list[str]:
    names = data.get("names") or {}
    if isinstance(names, dict):
        pairs = sorted(((int(key), str(value)) for key, value in names.items()), key=lambda row: row[0])
        return [value for _, value in pairs]
    if isinstance(names, list):
        return [str(value) for value in names]
    return []


@dataclass
class Check:
    name: str
    ok: bool
    expected: Any = None
    actual: Any = None
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": "PASS" if self.ok else "FAIL",
            "expected": self.expected,
            "actual": self.actual,
            "detail": self.detail,
        }


@dataclass
class Report:
    mode: str
    checks: list[Check] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)

    def add(self, name: str, ok: bool, *, expected: Any = None, actual: Any = None, detail: str = "") -> None:
        self.checks.append(Check(name, bool(ok), expected, actual, detail))

    @property
    def ok(self) -> bool:
        return all(check.ok for check in self.checks)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "mode": self.mode,
            "summary": {
                "passed": sum(1 for row in self.checks if row.ok),
                "failed": sum(1 for row in self.checks if not row.ok),
            },
            "checks": [row.as_dict() for row in self.checks],
            "evidence": self.evidence,
        }


def _run_json(command: list[str], timeout: float = 20.0) -> tuple[int, Any, str]:
    completed = subprocess.run(command, text=True, capture_output=True, timeout=timeout, check=False)
    stdout = completed.stdout.strip()
    try:
        parsed = json.loads(stdout.splitlines()[-1]) if stdout else None
    except json.JSONDecodeError:
        parsed = None
    return completed.returncode, parsed, (completed.stderr or "").strip()


def preflight(args: argparse.Namespace) -> Report:
    report = Report("preflight")
    data_dir = Path(args.data_dir).expanduser().resolve()
    report.evidence["data_dir"] = str(data_dir)
    report.evidence["base_url"] = args.base_url

    try:
        version = _http_json(args.base_url, "/api/system/version")
        report.evidence["system_version"] = version
        api_data_dir = Path(str(version.get("data_dir") or "")).expanduser().resolve()
        report.add("API uses expected persistent data dir", api_data_dir == data_dir,
                   expected=str(data_dir), actual=str(api_data_dir))
    except Exception as error:
        report.add("API reachable", False, expected=args.base_url, actual=None, detail=str(error))
        version = {}

    try:
        devices = _http_json(args.base_url, "/api/v62/training-devices")
        report.evidence["training_devices"] = devices
        options = devices.get("options") or []
        gpu0 = next((row for row in options if _device(row.get("id")) == _device(args.expected_device)), None)
        report.add("training device 0 is available", bool(gpu0 and gpu0.get("available") is not False),
                   expected=args.expected_device, actual=gpu0)
    except Exception as error:
        report.add("training devices endpoint", False, detail=str(error))

    try:
        resources = _http_json(args.base_url, "/api/v62/gpu-resources")
        report.evidence["gpu_resources"] = resources
        report.add("GPU resource endpoint reachable", True, actual=resources)
    except Exception as error:
        report.add("GPU resource endpoint reachable", False, detail=str(error))

    worker_cmd = [
        sys.executable,
        str(Path(__file__).resolve().parent / "task_worker.py"),
        "--check",
        "--data-dir", str(data_dir),
        "--roles", "all",
    ]
    try:
        code, worker, stderr = _run_json(worker_cmd)
        report.evidence["worker_check"] = worker
        report.add("task worker check succeeds", code == 0 and isinstance(worker, dict),
                   expected=0, actual=code, detail=stderr)
        report.add("execution fencing enabled", bool(worker and worker.get("execution_fencing") is True),
                   expected=True, actual=worker.get("execution_fencing") if worker else None)
        caps = set(worker.get("capabilities") or []) if worker else set()
        report.add("training.ultralytics capability registered", "training.ultralytics" in caps,
                   expected="training.ultralytics", actual=sorted(caps))
    except Exception as error:
        report.add("task worker check succeeds", False, detail=str(error))

    try:
        from platform_core.training_devices import training_python
        training_py = str(training_python(data_dir))
        probe = (
            "import json,torch;"
            "print(json.dumps({'python':__import__('sys').executable,'torch':torch.__version__,"
            "'cuda':torch.version.cuda,'available':torch.cuda.is_available(),"
            "'count':torch.cuda.device_count(),"
            "'gpu0':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None},ensure_ascii=False))"
        )
        code, env, stderr = _run_json([training_py, "-c", probe], timeout=30)
        report.evidence["training_python"] = training_py
        report.evidence["cuda_probe"] = env
        report.add("configured training Python starts", code == 0 and isinstance(env, dict),
                   expected=0, actual=code, detail=stderr)
        report.add("Torch CUDA is available", bool(env and env.get("available") and int(env.get("count") or 0) > 0),
                   expected=True, actual=env)
        gpu_name = str((env or {}).get("gpu0") or "")
        report.add("GPU 0 is A800", "a800" in gpu_name.lower(), expected="A800", actual=gpu_name)
    except Exception as error:
        report.add("configured training Python starts", False, detail=str(error))

    return report


def _load_job(args: argparse.Namespace) -> dict[str, Any]:
    if args.job_json:
        return _json(Path(args.job_json).expanduser().resolve(), {}) or {}
    return _http_json(args.base_url, f"/api/projects/{args.project_id}/jobs/{args.job_id}")


def _artifact_json(task_root: Path, *candidates: str) -> tuple[Any, Path | None]:
    for relative in candidates:
        path = task_root / relative
        if path.is_file():
            return _json(path), path
    return None, None


def verify_job(args: argparse.Namespace) -> Report:
    report = Report("verify-job")
    data_dir = Path(args.data_dir).expanduser().resolve()
    expected_labels = [value.strip() for value in args.expected_labels.split(",") if value.strip()]
    job = _load_job(args)
    task_id = str(args.task_id or job.get("task_id") or args.job_id)
    task_root = data_dir / "task_runtime" / "artifacts" / task_id
    report.evidence.update({
        "project_id": args.project_id,
        "job_id": args.job_id,
        "task_id": task_id,
        "task_root": str(task_root),
        "job_status": job.get("status"),
    })

    status = str(job.get("status") or "").lower()
    report.add("training job completed successfully", status in SUCCESS_STATUSES,
               expected=sorted(SUCCESS_STATUSES), actual=status)
    report.add("task artifact directory exists", task_root.is_dir(), expected=str(task_root), actual=task_root.is_dir())

    snapshot, snapshot_path = _artifact_json(task_root, "snapshot.json", "work/bundle/snapshot.json")
    manifest, manifest_path = _artifact_json(task_root, "work/bundle/manifest.json")
    result, result_path = _artifact_json(task_root, "result.json")
    resolved, resolved_path = _artifact_json(task_root, "resolved-resources.json")
    data_yaml_path = task_root / "work" / "bundle" / "dataset" / "data.yaml"
    data_yaml = yaml.safe_load(data_yaml_path.read_text(encoding="utf-8")) if data_yaml_path.is_file() else None

    report.evidence["artifacts"] = {
        "snapshot": str(snapshot_path) if snapshot_path else None,
        "manifest": str(manifest_path) if manifest_path else None,
        "result": str(result_path) if result_path else None,
        "resolved_resources": str(resolved_path) if resolved_path else None,
        "data_yaml": str(data_yaml_path) if data_yaml_path.is_file() else None,
    }
    report.add("Snapshot exists", isinstance(snapshot, dict), actual=str(snapshot_path) if snapshot_path else None)
    report.add("portable manifest exists", isinstance(manifest, dict), actual=str(manifest_path) if manifest_path else None)
    report.add("task result exists", isinstance(result, dict), actual=str(result_path) if result_path else None)
    report.add("resolved resource evidence exists", isinstance(resolved, dict), actual=str(resolved_path) if resolved_path else None)
    report.add("portable data.yaml exists", isinstance(data_yaml, dict), actual=str(data_yaml_path))

    snapshot = snapshot or {}
    manifest = manifest or {}
    result = result or {}
    resolved = resolved or job.get("resolved_resources") or result.get("resolved_resources") or {}
    data_yaml = data_yaml or {}

    schema = snapshot.get("label_schema") or []
    snapshot_codes = _label_codes(schema)
    snapshot_ids = [int(row.get("class_id")) for row in sorted(schema, key=lambda row: int(row.get("class_id", 10**9)))] if schema else []
    yaml_codes = _yaml_names(data_yaml)
    report.add("Snapshot task label schema is exact", snapshot_codes == expected_labels,
               expected=expected_labels, actual=snapshot_codes)
    report.add("Snapshot class IDs are contiguous from zero", snapshot_ids == list(range(len(expected_labels))),
               expected=list(range(len(expected_labels))), actual=snapshot_ids)
    report.add("data.yaml names are exact", yaml_codes == expected_labels,
               expected=expected_labels, actual=yaml_codes)
    report.add("effective nc is expected", len(yaml_codes) == len(expected_labels),
               expected=len(expected_labels), actual=len(yaml_codes))

    snapshot_id = str(snapshot.get("snapshot_id") or "")
    manifest_snapshot_id = str(manifest.get("snapshot_id") or "")
    result_snapshot_id = str(result.get("snapshot_id") or job.get("snapshot_id") or "")
    report.add("Snapshot identity matches manifest", bool(snapshot_id) and snapshot_id == manifest_snapshot_id,
               expected=snapshot_id, actual=manifest_snapshot_id)
    if result_snapshot_id:
        report.add("Snapshot identity matches result/job", snapshot_id == result_snapshot_id,
                   expected=snapshot_id, actual=result_snapshot_id)

    report.add("requested batch preserved", int(resolved.get("requested_batch", -999)) == args.expected_batch,
               expected=args.expected_batch, actual=resolved.get("requested_batch"))
    report.add("effective batch preserved", int(resolved.get("resolved_batch", -999)) == args.expected_batch,
               expected=args.expected_batch, actual=resolved.get("resolved_batch"))
    report.add("requested workers preserved", int(resolved.get("requested_workers", -999)) == args.expected_workers,
               expected=args.expected_workers, actual=resolved.get("requested_workers"))
    report.add("effective workers preserved", int(resolved.get("resolved_workers", -999)) == args.expected_workers,
               expected=args.expected_workers, actual=resolved.get("resolved_workers"))
    report.add("requested cache preserved", _cache(resolved.get("requested_cache")) == args.expected_cache,
               expected=args.expected_cache, actual=_cache(resolved.get("requested_cache")))
    report.add("effective cache preserved", _cache(resolved.get("resolved_cache")) == args.expected_cache,
               expected=args.expected_cache, actual=_cache(resolved.get("resolved_cache")))

    actual = job.get("actual_train_params") or result.get("actual_train_params") or {}
    report.add("Ultralytics actual batch matches", int(actual.get("batch", -999)) == args.expected_batch,
               expected=args.expected_batch, actual=actual.get("batch"))
    report.add("Ultralytics actual workers match", int(actual.get("workers", -999)) == args.expected_workers,
               expected=args.expected_workers, actual=actual.get("workers"))
    report.add("Ultralytics actual cache matches", _cache(actual.get("cache")) == args.expected_cache,
               expected=args.expected_cache, actual=_cache(actual.get("cache")))

    requested_device = job.get("requested_device") or result.get("requested_device")
    assigned_device = job.get("assigned_device") or result.get("assigned_device")
    actual_device = job.get("actual_device") or result.get("actual_device")
    expected_device = _device(args.expected_device)
    report.add("requested device is GPU 0", _device(requested_device) == expected_device,
               expected=expected_device, actual=requested_device)
    report.add("assigned device is GPU 0", _device(assigned_device) == expected_device,
               expected=expected_device, actual=assigned_device)
    report.add("actual device is GPU 0", _device(actual_device) == expected_device,
               expected=expected_device, actual=actual_device)

    splits = manifest.get("splits") or {}
    manifest_members = {
        str(member.get("image_id")): (str(role), member)
        for role in ("train", "validation", "test")
        for member in (splits.get(role) or [])
    }
    confirmed = [row for row in (snapshot.get("images") or []) if row.get("annotation_state") == "confirmed_empty"]
    negative_results = []
    for row in confirmed:
        image_id = str(row.get("image_id"))
        role_member = manifest_members.get(image_id)
        if not role_member:
            negative_results.append({"image_id": image_id, "ok": False, "reason": "missing from manifest"})
            continue
        _, member = role_member
        label_ref = str(member.get("label_ref") or "")
        label_path = task_root / "work" / "bundle" / label_ref
        size = label_path.stat().st_size if label_path.is_file() else None
        negative_results.append({"image_id": image_id, "label": str(label_path), "size": size, "ok": size == 0})
    report.evidence["confirmed_empty"] = negative_results
    if confirmed:
        report.add("confirmed_empty labels are zero-byte YOLO files", all(row["ok"] for row in negative_results),
                   expected="all size=0", actual=negative_results)
    else:
        report.add("confirmed_empty sample present for RC negative proof", False,
                   expected="at least one confirmed_empty image", actual=0,
                   detail="本次任务没有负样本，无法完成 confirmed_empty 实机验收")

    verified_models = result.get("verified_models") or []
    report.add("verified trained model exists", bool(verified_models), expected=">=1 verified model", actual=verified_models)

    report.evidence["resources"] = {
        "resolved": resolved,
        "actual_train_params": actual,
        "requested_device": requested_device,
        "assigned_device": assigned_device,
        "actual_device": actual_device,
    }
    report.evidence["labels"] = {
        "snapshot": snapshot_codes,
        "data_yaml": yaml_codes,
        "nc": len(yaml_codes),
    }
    report.evidence["iteration"] = {
        "base_version_name": result.get("base_version_name") or job.get("base_version_name"),
        "base_selection_reason": result.get("base_selection_reason") or job.get("base_selection_reason"),
    }
    return report


def _print_report(report: Report, output: str | None = None) -> int:
    rendered = json.dumps(report.as_dict(), ensure_ascii=False, indent=2, default=str)
    print(rendered)
    if output:
        target = Path(output).expanduser().resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered + "\n", encoding="utf-8")
    return 0 if report.ok else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="v42.25 A800 RC 只读验收工具")
    sub = parser.add_subparsers(dest="command", required=True)

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--base-url", default=DEFAULT_BASE_URL)
    common.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    common.add_argument("--expected-device", default="0")
    common.add_argument("--output", default=None)

    pre = sub.add_parser("preflight", parents=[common], help="只读检查 API、Worker fencing 和 CUDA/A800 环境")
    pre.set_defaults(handler=preflight)

    verify = sub.add_parser("verify-job", parents=[common], help="只读核验一个已完成训练任务的 RC 证据")
    verify.add_argument("--project-id", required=True)
    verify.add_argument("--job-id", required=True)
    verify.add_argument("--task-id", default=None)
    verify.add_argument("--job-json", default=None, help="离线测试时可直接读取 job.json；正式验收建议走 API")
    verify.add_argument("--expected-labels", default="fire,smoke")
    verify.add_argument("--expected-batch", type=int, default=16)
    verify.add_argument("--expected-workers", type=int, default=4)
    verify.add_argument("--expected-cache", action=argparse.BooleanOptionalAction, default=False)
    verify.set_defaults(handler=verify_job)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = args.handler(args)
    except Exception as error:
        report = Report(args.command)
        report.add("acceptance tool execution", False, detail=f"{type(error).__name__}: {error}")
    return _print_report(report, args.output)


if __name__ == "__main__":
    raise SystemExit(main())
