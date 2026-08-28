import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    ("target", "params", "error_code", "forbidden_suffix"),
    [
        ("ascend", {"soc_version": "Ascend310P3", "precision": "fp16"}, "ATC_NOT_FOUND", ".om"),
        ("rockchip", {"chip": "rk3588", "precision": "fp16"}, "RKNN_TOOLKIT_NOT_FOUND", ".rknn"),
        (
            "tensorrt",
            {"precision": "fp16", "target_environment": "test-gpu/cuda/tensorrt"},
            "TENSORRT_NOT_FOUND",
            ".engine",
        ),
    ],
)
def test_missing_vendor_compiler_fails_without_fake_artifact(
    tmp_path, target, params, error_code, forbidden_suffix
):
    job_dir = tmp_path / target
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True)
    source = source_dir / "source.onnx"
    source.write_bytes(b"not-used-before-compiler-check")
    job = {
        "id": f"job-{target}",
        "source_id": "test-source",
        "source_path": str(source),
        "source_trace": {"source_id": "test-source", "version_id": "v1", "sha256": "test"},
        "target": target,
        "resource": {"id": "missing-sdk", "name": "missing-sdk", "version": ""},
        "params": params,
        "status": "queued",
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    empty_path = tmp_path / "empty-path"
    empty_path.mkdir()
    environment = os.environ.copy()
    environment["PATH"] = str(empty_path)

    completed = subprocess.run(
        [sys.executable, str(ROOT / "deployment_worker.py"), "--job-dir", str(job_dir)],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=30,
    )
    assert completed.returncode != 0
    result = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert result["status"] == "failed"
    assert result["error_code"] == error_code
    assert not list((job_dir / "artifacts").rglob(f"*{forbidden_suffix}"))
