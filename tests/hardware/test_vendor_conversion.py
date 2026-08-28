import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.hardware
def test_configured_vendor_sdk_produces_real_loadable_artifact(tmp_path):
    target = os.environ.get("XJALGO_VENDOR_TARGET", "").strip().lower()
    source = Path(os.environ.get("XJALGO_VENDOR_TEST_ONNX", ""))
    if target not in {"ascend", "rockchip", "tensorrt"} or not source.is_file():
        pytest.skip("未显式配置 XJALGO_VENDOR_TARGET 和 XJALGO_VENDOR_TEST_ONNX，不能宣称厂商转换通过")

    params = {"precision": os.environ.get("XJALGO_VENDOR_PRECISION", "fp16")}
    resource = {"id": "hardware-test", "name": "hardware-test", "version": ""}
    expected_suffix = {"ascend": ".om", "rockchip": ".rknn", "tensorrt": ".engine"}[target]
    if target == "ascend":
        params["soc_version"] = os.environ.get("XJALGO_ATLAS_SOC", "")
        resource["atc_path"] = os.environ.get("XJALGO_ATC_PATH", "")
    elif target == "rockchip":
        params["chip"] = os.environ.get("XJALGO_RKNN_CHIP", "")
        resource["python_path"] = os.environ.get("XJALGO_RKNN_PYTHON", "")
    else:
        params["target_environment"] = os.environ.get("XJALGO_TENSORRT_ENVIRONMENT", "")
        resource["trtexec_path"] = os.environ.get("XJALGO_TRTEXEC_PATH", "")

    job_dir = tmp_path / "vendor-job"
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True)
    local_source = source_dir / source.name
    local_source.write_bytes(source.read_bytes())
    job = {
        "id": "hardware-test",
        "source_id": "hardware-test-source",
        "source_path": str(local_source),
        "target": target,
        "resource": resource,
        "params": params,
        "status": "queued",
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")
    completed = subprocess.run(
        [sys.executable, str(ROOT / "deployment_worker.py"), "--job-dir", str(job_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=7200,
    )
    result = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0, result.get("error") or completed.stdout or completed.stderr
    artifacts = list((job_dir / "artifacts").rglob(f"*{expected_suffix}"))
    assert artifacts and all(path.stat().st_size > 0 for path in artifacts)
    manifest = json.loads((job_dir / "artifacts" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["status"] == "converted_unverified"
    assert manifest["outputs"]
