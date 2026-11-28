"""L5 delivery-admission gate for the conversion consistency matrix (synthetic only).

The matrix (docs/architecture/CONVERSION_L0_L5_EVIDENCE_MATRIX_20261126.md)
separates what the code really measures per level from what it actually gates.
These tests pin the one software gate this change closes:

A BMODEL conversion (`target=sophon`, `bmodel_expected=true`) whose numeric
verification only compared PT -> ONNX used to be reported by
``assert_delivery_quality_eligibility`` as ``eligible=True`` even though the
BMODEL itself was never compared (``bmodel_numeric_status=unavailable``) or was
compared and differed (``bmodel_detection_status=difference_detected``).

No test here touches a real SDK, board, GPU or production data. All identities
are synthetic and every check is deterministic.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from platform_core.deployment import numeric_consistency as numeric

JOB_ID = "conversion-sophon-1"
PROJECT_ID = "p1"
VERIFICATION_DIR = "nv_0123456789abcdef01234567"


# ---------------------------------------------------------------------------
# Synthetic, fully-bound conversion layout (job.json + manifest + artifacts).
# ---------------------------------------------------------------------------
def _source_manifest(*, onnx_path, onnx_sha, source_sha, bmodel_name, bmodel_sha, bmodel_size):
    from platform_core.conversion import build_source_manifest

    return build_source_manifest(
        source={"sha256": source_sha, "size_bytes": 1, "file_name": "best.pt",
                "algorithm_id": "a1", "version_id": "v1",
                "label_codes": ["smoke", "fire"]},
        export={"opset": 12, "dynamic": False, "simplify": False, "batch": 1,
                "imgsz": [64, 64], "precision": "fp16", "half": False},
        tool={"name": "tpu-mlir", "version": "1.30.2",
              "python_path": sys.executable, "dependencies": {}},
        onnx={"name": onnx_path.name, "sha256": onnx_sha,
              "size_bytes": onnx_path.stat().st_size, "opset_imports": {"": 12},
              "input_shapes": [[1, 3, 64, 64]], "input_types": ["tensor(float)"],
              "input_names": ["images"], "output_shapes": [[1, 7, 84]],
              "output_types": ["tensor(float)"], "output_names": ["output0"],
              "output_inferred_shapes": [[1, 7, 84]], "output_dtypes": ["float32"],
              "floating_tensor_types": ["FLOAT16"]},
        outputs=[{"name": onnx_path.name, "sha256": onnx_sha,
                  "size_bytes": onnx_path.stat().st_size},
                 {"name": bmodel_name, "sha256": bmodel_sha, "size_bytes": bmodel_size}],
    )


def _layout(tmp_path: Path) -> dict:
    from platform_core.conversion import sha256_file, source_manifest_digest

    deploy = tmp_path / "deployment"
    job_dir = deploy / "jobs" / JOB_ID
    (job_dir / "source").mkdir(parents=True)
    (job_dir / "artifacts").mkdir(parents=True)
    source = job_dir / "source" / "best.pt"
    onnx = job_dir / "artifacts" / "model.onnx"
    bmodel = job_dir / "artifacts" / "model_bm1684x_fp16.bmodel"
    source.write_bytes(b"synthetic-pt-bytes")
    onnx.write_bytes(b"synthetic-onnx-bytes")
    bmodel.write_bytes(b"synthetic-bmodel-bytes")
    source_sha, onnx_sha, bmodel_sha = (sha256_file(source), sha256_file(onnx),
                                        sha256_file(bmodel))
    manifest = {
        "job_id": JOB_ID, "status": "done", "target": "sophon",
        "source": {"sha256": source_sha},
        "onnx": {"sha256": onnx_sha, "input_shapes": [[1, 3, 64, 64]],
                 "output_names": ["output0"]},
        "tool": {"name": "tpu-mlir", "version": "1.30.2"},
        "outputs": [
            {"name": onnx.name, "sha256": onnx_sha, "size_bytes": onnx.stat().st_size},
            {"name": bmodel.name, "sha256": bmodel_sha,
             "size_bytes": bmodel.stat().st_size},
        ],
        "source_manifest": _source_manifest(
            onnx_path=onnx, onnx_sha=onnx_sha, source_sha=source_sha,
            bmodel_name=bmodel.name, bmodel_sha=bmodel_sha,
            bmodel_size=bmodel.stat().st_size),
    }
    manifest["manifest_digest"] = source_manifest_digest(manifest)
    manifest_path = job_dir / "artifacts" / "manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    job = {
        "id": JOB_ID, "project_id": PROJECT_ID, "status": "done", "target": "sophon",
        "source_path": str(source),
        "source_trace": {"algorithm_id": "a1", "version_id": "v1", "sha256": source_sha,
                         "label_codes": ["smoke", "fire"]},
        "params": {"precision": "fp16", "chip": "bm1684x"},
        "manifest_path": str(manifest_path), "manifest_digest": manifest["manifest_digest"],
        "outputs": [
            {"name": onnx.name, "path": str(onnx), "sha256": onnx_sha,
             "size_bytes": onnx.stat().st_size},
            {"name": bmodel.name, "path": str(bmodel), "sha256": bmodel_sha,
             "size_bytes": bmodel.stat().st_size},
        ],
    }
    job_path = job_dir / "job.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    verification = deploy / "numeric-validations" / VERIFICATION_DIR
    (verification / "images").mkdir(parents=True)
    names = ["image_01.png", "image_02.png"]
    for index, name in enumerate(names):
        (verification / "images" / name).write_bytes(f"image-bytes-{index}".encode())
    receipt = {
        "id": VERIFICATION_DIR, "project_id": PROJECT_ID, "conversion_job_id": JOB_ID,
        "request_id": "request-sophon-0001", "created_at": "2026-11-26T00:00:00+00:00",
        "source_path": str(source), "onnx_path": str(onnx),
        "source_sha256": source_sha, "onnx_sha256": onnx_sha,
        "bmodel_path": str(bmodel), "bmodel_sha256": bmodel_sha, "bmodel_expected": True,
        "precision": "fp16", "confidence": 0.25, "nms_iou": 0.7,
        "input_color_order": "rgb",
        "preprocessing": {"pixel_format": "rgb", "channel_format": "nchw",
                          "resize_interpolation": "opencv_linear",
                          "letterbox_mode": "fixed_shape_center", "pad_value": 114,
                          "scale": [1 / 255] * 3},
        "input_shapes": [[1, 3, 64, 64]], "frozen_imgsz": [64, 64], "frozen_batch": 1,
        "label_codes": ["smoke", "fire"], "label_schema": [], "image_names": names,
    }
    (verification / "request.json").write_text(json.dumps(receipt), encoding="utf-8")
    return {"job_path": job_path, "verification": verification, "receipt": receipt,
            "source_sha": source_sha, "onnx_sha": onnx_sha, "bmodel_sha": bmodel_sha,
            "bmodel": bmodel, "image_names": names}


def _detection_row(*, within_tolerance: bool) -> dict:
    return {
        "comparable": True, "within_tolerance": within_tolerance,
        "matched_pairs": 1 if within_tolerance else 0,
        "unmatched_reference": 0 if within_tolerance else 1,
        "unmatched_converted": 0, "threshold_crossings": 0,
        "mean_matched_iou": 0.998 if within_tolerance else None,
        "original_coordinates": {"status": "mapped"},
    }


def _result(*, bmodel_numeric: str, bmodel_detection: str, detection_ok: bool = True) -> dict:
    """What verify_images records for a BMODEL conversion (synthetic, no inference)."""
    return {
        "protocol": numeric.PROTOCOL, "status": "completed",
        "raw_verdict": "consistent",
        "verdict": "consistent" if detection_ok else "difference_detected",
        "detection_status": "consistent" if detection_ok else "difference_detected",
        "comparison_confidence": 0.25, "comparison_nms_iou": 0.7,
        "sample_count": 2, "precision": "fp16",
        "source": "PT", "compared": "ONNX",
        "hardware_verified": False, "ground_truth_used": False, "bmodel_verified": False,
        "bmodel_numeric_status": bmodel_numeric,
        "bmodel_detection_status": bmodel_detection,
        "bmodel_numeric_error": "" if bmodel_numeric == "consistent"
        else "未配置本机可用的 Sophon SDK Python／模型模拟器",
        "deployment_preprocessing_aligned": True,
        "label_identity": {"status": "verified", "mapping_sha256": "a" * 64},
        "input_color_space": "rgb",
        "input_contract": {"status": "resolved", "resolved_input_shape": [1, 3, 64, 64],
                           "input_shape_source": "frozen_manifest"},
        "dynamic_resolution": "static", "dynamic_resolution_reason": "",
        "runtime_versions": {"numpy": {"version": "synthetic", "error": None}},
        "rejection": None, "scope_note": "",
        "completed_at": "2026-11-26T00:00:00+00:00",
        "images": [
            {"image": name, "comparable": True, "within_tolerance": detection_ok,
             "normalized_mae": 0.0001 * (index + 1), "cosine_similarity": 0.99999,
             "max_abs_error": 0.01, "detection": _detection_row(within_tolerance=detection_ok)}
            for index, name in enumerate(("image_01.png", "image_02.png"))
        ],
    }


def _publish(layout: dict, monkeypatch, result: dict) -> dict:
    payload = json.loads(json.dumps(result))
    monkeypatch.setattr(numeric, "verify_images", lambda *args, **kwargs: json.loads(
        json.dumps(payload)))
    final = numeric.run_verification_directory(layout["verification"])
    assert final["status_projection"]["status"] == "projected"
    return final


def _job(layout: dict) -> dict:
    return json.loads(layout["job_path"].read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# The closed gap: BMODEL deliverables are refused without BMODEL evidence.
# ---------------------------------------------------------------------------
def test_bmodel_deliverable_without_bmodel_comparison_is_refused(tmp_path, monkeypatch):
    layout = _layout(tmp_path)
    _publish(layout, monkeypatch, _result(bmodel_numeric="unavailable",
                                          bmodel_detection="unavailable"))
    # The mutable PT/ONNX summary still says "consistent": the refusal must come
    # from the immutable evidence gate, not from the summary label.
    assert _job(layout)["numeric_status"] == "consistent"
    verdict = numeric.assert_delivery_quality_eligibility(layout["verification"])
    assert verdict["eligible"] is False
    assert verdict["code"] == numeric.BMODEL_EVIDENCE_NOT_ELIGIBLE_CODE
    assert numeric.BMODEL_EVIDENCE_NOT_ELIGIBLE_CODE in verdict["failure_codes"]
    assert verdict["bmodel"]["numeric_status"] == "unavailable"
    assert verdict["bmodel"]["detection_status"] == "unavailable"
    assert verdict["evidence_digest_verified"] is True
    assert verdict["binding_status"] == "verified"
    assert verdict["target_artifact_sha256"] == layout["bmodel_sha"]


def test_bmodel_detection_difference_is_refused_even_when_bmodel_tensors_match(
    tmp_path, monkeypatch,
):
    layout = _layout(tmp_path)
    _publish(layout, monkeypatch, _result(bmodel_numeric="consistent",
                                          bmodel_detection="difference_detected"))
    verdict = numeric.assert_delivery_quality_eligibility(layout["verification"])
    assert verdict["eligible"] is False
    assert verdict["code"] == numeric.BMODEL_EVIDENCE_NOT_ELIGIBLE_CODE
    assert verdict["bmodel"]["numeric_status"] == "consistent"
    assert verdict["bmodel"]["detection_status"] == "difference_detected"


def test_bmodel_deliverable_with_bound_bmodel_evidence_still_passes(tmp_path, monkeypatch):
    layout = _layout(tmp_path)
    _publish(layout, monkeypatch, _result(bmodel_numeric="consistent",
                                          bmodel_detection="consistent"))
    verdict = numeric.assert_delivery_quality_eligibility(layout["verification"])
    assert verdict["eligible"] is True, verdict
    assert verdict["code"] == ""
    assert verdict["reasons"] == []
    assert verdict["bmodel"]["numeric_status"] == "consistent"
    assert verdict["bmodel"]["detection_status"] == "consistent"
    assert verdict["target_artifact_sha256"] == layout["bmodel_sha"]
    assert verdict["hardware_verified"] is False
    assert verdict["numeric_status_sufficient_for_eligibility"] is False


def test_onnx_only_deliverable_is_unchanged(tmp_path, monkeypatch):
    """The gate applies to BMODEL deliverables only; ONNX evidence keeps passing."""
    layout = _layout(tmp_path)
    result = _result(bmodel_numeric="not_applicable", bmodel_detection="not_applicable")
    job = _job(layout)
    job["target"] = "onnx"
    job["outputs"] = [row for row in job["outputs"] if row["name"].endswith(".onnx")]
    layout["job_path"].write_text(json.dumps(job), encoding="utf-8")
    receipt = dict(layout["receipt"], bmodel_path="", bmodel_sha256="",
                   bmodel_expected=False)
    (layout["verification"] / "request.json").write_text(
        json.dumps(receipt), encoding="utf-8")
    _publish(layout, monkeypatch, result)
    verdict = numeric.assert_delivery_quality_eligibility(layout["verification"])
    assert verdict["eligible"] is True, verdict
    assert verdict["code"] == ""


def test_source_manifest_preserves_label_and_preprocessing_contracts(tmp_path):
    from platform_core.conversion import build_source_manifest, sha256_file

    onnx = tmp_path / "model.onnx"
    onnx.write_bytes(b"onnx-bytes")
    digest = sha256_file(onnx)
    manifest = build_source_manifest(
        source={
            "sha256": "a" * 64, "size_bytes": 3, "file_name": "best.pt",
            "algorithm_id": "a1", "version_id": "v1",
            "label_codes": ["smoke", "fire"],
            "label_binding": {
                "status": "verified", "class_count": 2,
                "class_ids": [0, 1], "mapping_sha256": "b" * 64,
            },
            "preprocessing_contract": {
                "status": "declared", "pixel_format": "rgb",
                "letterbox_mode": "fixed_shape_center",
            },
            "output_contract": {"status": "declared", "layout": "yolo_v8"},
        },
        export={"opset": 12, "dynamic": False, "simplify": False, "batch": 1,
                "imgsz": [64, 64], "precision": "fp16", "half": False},
        tool={"name": "onnx", "version": "1", "python_path": "python",
              "dependencies": {}},
        onnx={"name": onnx.name, "sha256": digest, "size_bytes": onnx.stat().st_size,
              "opset_imports": {"": 12}, "input_shapes": [[1, 3, 64, 64]],
              "input_types": ["tensor(float)"], "input_names": ["images"],
              "output_shapes": [[1, 7, 6]], "output_types": ["tensor(float)"],
              "output_names": ["output0"], "output_inferred_shapes": [[1, 7, 6]],
              "output_dtypes": ["float32"], "floating_tensor_types": []},
        outputs=[{"name": onnx.name, "sha256": digest, "size_bytes": onnx.stat().st_size}],
    )
    source = manifest["source"]
    assert source["label_binding"]["status"] == "verified"
    assert source["preprocessing_contract"]["letterbox_mode"] == "fixed_shape_center"
    assert source["output_contract"]["layout"] == "yolo_v8"
