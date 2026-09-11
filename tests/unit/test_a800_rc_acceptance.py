import argparse
import hashlib
import json
from pathlib import Path

import yaml

import a800_rc_acceptance as rc


def _write(path: Path, value, *, yaml_value=False):
    path.parent.mkdir(parents=True, exist_ok=True)
    if yaml_value:
        path.write_text(yaml.safe_dump(value, allow_unicode=True, sort_keys=False), encoding="utf-8")
    elif isinstance(value, (dict, list)):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    else:
        path.write_text(str(value), encoding="utf-8")


def _fixture(tmp_path: Path, *, wrong_label=False, negative_bytes=b""):
    data_dir = tmp_path / "platform-data"
    task_id = "task-a800-rc"
    task_root = data_dir / "task_runtime" / "artifacts" / task_id
    bundle = task_root / "work" / "bundle"
    labels = [
        {"class_id": 0, "code": "fire"},
        {"class_id": 1, "code": "smoke"},
    ]
    if wrong_label:
        labels.append({"class_id": 2, "code": "person"})
    snapshot = {
        "schema_version": 3,
        "snapshot_id": "snap-rc",
        "label_schema": labels,
        "images": [
            {"image_id": "img-fire", "role": "train", "annotation_state": "annotated"},
            {
                "image_id": "img-neg",
                "role": "validation",
                "annotation_state": "confirmed_empty",
                "annotation_scope": [row["code"] for row in labels],
            },
        ],
    }
    manifest = {
        "schema_version": 2,
        "snapshot_id": "snap-rc",
        "splits": {
            "train": [{"image_id": "img-fire", "label_ref": "dataset/labels/train/img-fire.txt"}],
            "validation": [{"image_id": "img-neg", "label_ref": "dataset/labels/validation/img-neg.txt"}],
            "test": [],
        },
    }
    resolved = {
        "requested_batch": 16,
        "resolved_batch": 16,
        "requested_workers": 4,
        "resolved_workers": 4,
        "requested_cache": False,
        "resolved_cache": False,
    }
    model_bytes = b"verified-model"
    model_sha = hashlib.sha256(model_bytes).hexdigest()
    result = {
        "snapshot_id": "snap-rc",
        "requested_device": "0",
        "assigned_device": "cuda:0",
        "actual_device": "cuda:0",
        "actual_train_params": {"batch": 16, "workers": 4, "cache": False},
        "verified_models": [{"ref": "outputs/00_best.pt", "sha256": model_sha, "size_bytes": len(model_bytes)}],
        "base_version_name": "",
        "base_selection_reason": "first_training",
    }
    job = {
        "id": task_id,
        "task_id": task_id,
        "status": "done",
        "snapshot_id": "snap-rc",
        "requested_device": "0",
        "assigned_device": "cuda:0",
        "actual_device": "cuda:0",
        "actual_train_params": {"batch": 16, "workers": 4, "cache": False},
    }
    _write(task_root / "snapshot.json", snapshot)
    _write(bundle / "snapshot.json", snapshot)
    _write(bundle / "manifest.json", manifest)
    _write(task_root / "resolved-resources.json", resolved)
    _write(task_root / "result.json", result)
    _write(bundle / "dataset" / "data.yaml", {
        "path": ".",
        "train": "images/train",
        "val": "images/validation",
        "test": "images/test",
        "names": {row["class_id"]: row["code"] for row in labels},
    }, yaml_value=True)
    _write(bundle / "dataset" / "labels" / "train" / "img-fire.txt", "0 0.5 0.5 0.2 0.2\n")
    negative = bundle / "dataset" / "labels" / "validation" / "img-neg.txt"
    negative.parent.mkdir(parents=True, exist_ok=True)
    negative.write_bytes(negative_bytes)
    model = task_root / "outputs" / "00_best.pt"
    model.parent.mkdir(parents=True, exist_ok=True)
    model.write_bytes(model_bytes)
    job_path = tmp_path / "job.json"
    _write(job_path, job)
    return data_dir, job_path, task_id


def _args(data_dir: Path, job_path: Path, task_id: str):
    return argparse.Namespace(
        data_dir=str(data_dir),
        base_url="http://127.0.0.1:8010",
        project_id="project-rc",
        job_id=task_id,
        task_id=None,
        job_json=str(job_path),
        expected_labels="fire,smoke",
        expected_batch=16,
        expected_workers=4,
        expected_cache=False,
        expected_device="0",
        require_iteration=False,
        expected_base_version=None,
        output=None,
    )


def test_verify_job_accepts_exact_a800_rc_evidence(tmp_path):
    data_dir, job_path, task_id = _fixture(tmp_path)
    report = rc.verify_job(_args(data_dir, job_path, task_id))
    assert report.ok, json.dumps(report.as_dict(), ensure_ascii=False, indent=2)
    assert report.evidence["labels"] == {"snapshot": ["fire", "smoke"], "data_yaml": ["fire", "smoke"], "nc": 2}
    negative = report.evidence["confirmed_empty"]
    assert negative == [{
        "image_id": "img-neg",
        "label": str(data_dir / "task_runtime" / "artifacts" / task_id / "work" / "bundle" / "dataset" / "labels" / "validation" / "img-neg.txt"),
        "size": 0,
        "ok": True,
    }]


def test_verify_job_rejects_extra_class_and_nonempty_negative(tmp_path):
    data_dir, job_path, task_id = _fixture(tmp_path, wrong_label=True, negative_bytes=b"2 0.5 0.5 0.2 0.2\n")
    report = rc.verify_job(_args(data_dir, job_path, task_id))
    assert report.ok is False
    failed = {row.name for row in report.checks if not row.ok}
    assert "Snapshot task label schema is exact" in failed
    assert "data.yaml names are exact" in failed
    assert "effective nc is expected" in failed
    assert "confirmed_empty labels are zero-byte YOLO files" in failed


def test_cache_and_device_normalization_support_runtime_forms():
    assert rc._cache(False) is False
    assert rc._cache("False") is False
    assert rc._cache("ram") == "ram"
    assert rc._device("cuda:0") == "0"
    assert rc._device("0") == "0"

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

