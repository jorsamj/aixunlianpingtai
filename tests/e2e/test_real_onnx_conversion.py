import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import onnx
import pytest


ROOT = Path(__file__).resolve().parents[2]
NOT_VERIFIED = (
    "NOT VERIFIED: 真实 ONNX 验收需要已准备的 yolo11n.pt；本机未提供该权重，"
    "未执行真实 Ultralytics 导出，也不冒充通过"
)


def local_yolo_checkpoint() -> Path:
    candidates = [ROOT / "yolo11n.pt", *(parent / "yolo11n.pt" for parent in ROOT.parents)]
    checkpoint = next((path for path in candidates if path.is_file()), None)
    if checkpoint is None:
        pytest.skip(NOT_VERIFIED)
    return checkpoint


def test_real_yolo_checkpoint_exports_and_loads_as_onnx(tmp_path):
    checkpoint = local_yolo_checkpoint()
    job_dir = tmp_path / "onnx-job"
    source_dir = job_dir / "source"
    source_dir.mkdir(parents=True)
    source = source_dir / "yolo11n.pt"
    shutil.copy2(checkpoint, source)
    source_sha = hashlib.sha256(source.read_bytes()).hexdigest()
    job = {
        "id": "real-onnx",
        "status": "queued",
        "target": "onnx",
        "source_id": "local-yolo11n",
        "source_path": str(source),
        "source_trace": {"source_id": "local-yolo11n", "sha256": source_sha},
        "resource": {"id": "builtin_ultralytics", "name": "Ultralytics", "python_path": sys.executable},
        "params": {"input_size": 128, "batch": 1, "opset": 12, "dynamic": False, "simplify": False},
    }
    (job_dir / "job.json").write_text(json.dumps(job), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, str(ROOT / "deployment_worker.py"), "--job-dir", str(job_dir)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="ignore",
        timeout=300,
    )
    final_job = json.loads((job_dir / "job.json").read_text(encoding="utf-8"))
    assert completed.returncode == 0, (completed.stdout + completed.stderr)[-12000:]
    assert final_job["status"] == "done", final_job
    manifest = json.loads(Path(final_job["manifest_path"]).read_text(encoding="utf-8"))
    assert manifest["onnx"]["checker"] == "passed"
    assert manifest["onnx"]["runtime"] == "onnxruntime"
    assert manifest["onnx"]["output_shapes"] and manifest["onnx"]["output_types"]
    assert manifest["onnx"]["output_dtypes"]
    assert final_job["manifest_digest"] and len(final_job["manifest_digest"]) == 64
    from platform_core.conversion import verify_source_manifest_digest
    assert verify_source_manifest_digest(manifest)["valid"] is True
    assert manifest["source_manifest"]["source"]["sha256_recheck"]["status"] == "matched"
    onnx_output = next(item for item in manifest["outputs"] if item["name"].endswith(".onnx"))
    assert onnx_output["sha256"]
    assert onnx_output["size_bytes"] > 0
    model = onnx.load(str(job_dir / "artifacts" / onnx_output["name"]))
    onnx.checker.check_model(model)
    assert manifest["hardware_verified"] is False
