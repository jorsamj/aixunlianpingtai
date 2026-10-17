import pytest

from platform_core.conversion import build_manifest, file_record, validate_target


def test_rknn_chip_must_be_explicit_and_supported():
    with pytest.raises(ValueError, match="rk3568.*rk3576"):
        validate_target("rockchip", {})
    assert validate_target("rockchip", {"chip": "rk3568"})["chip"] == "rk3568"
    assert validate_target("rockchip", {"chip": "rk3576"})["chip"] == "rk3576"
    with pytest.raises(ValueError, match="rk3568.*rk3576"):
        validate_target("rockchip", {"chip": "rk3578"})
    with pytest.raises(ValueError, match="rk3568.*rk3576"):
        validate_target("rockchip", {"chip": "rk3588"})


def test_atlas_soc_and_tensorrt_environment_are_required():
    with pytest.raises(ValueError, match="soc_version"):
        validate_target("ascend", {})
    with pytest.raises(ValueError, match="target_environment"):
        validate_target("tensorrt", {"precision": "fp16"})


def test_int8_requires_calibration_snapshot():
    with pytest.raises(ValueError, match="calibration_snapshot"):
        validate_target("rockchip", {"chip": "rk3568", "precision": "int8"})


def test_manifest_records_source_tool_outputs_and_validation_state(tmp_path):
    output = tmp_path / "model.rknn"
    output.write_bytes(b"real-artifact")
    manifest = build_manifest(
        source={"version_id": "v1", "sha256": "abc"},
        target={"kind": "rockchip", "chip": "rk3568"},
        tool={"name": "rknn-toolkit2", "version": "2.3.2"},
        outputs=[file_record(output)],
        hardware_verified=False,
    )
    assert manifest["target"]["chip"] == "rk3568"
    assert manifest["outputs"][0]["sha256"]
    assert manifest["status"] == "converted_unverified"
    assert manifest["hardware_verified"] is False


from platform_core.conversion import derive_version_conversion_defaults


def test_conversion_defaults_actual_lineage_and_runtime_precision():
    v = {"job_id": "job1", "training_lineage": {"parameters": {
        "requested": {"imgsz": 640, "precision": "auto"},
        "actual": {"imgsz": 800, "precision": "fp32"},
    }}}
    observed = derive_version_conversion_defaults(v, {"runtime_precision": "fp32", "imgsz": 640})
    assert observed["input_size"] == 800
    assert observed["training_precision"] == "fp32"
    assert observed["source_job_id"] == "job1"


def test_conversion_defaults_amp_flag_is_not_proof_of_runtime_precision():
    v = {"training_lineage": {"parameters": {"requested": {"imgsz": 800, "precision": "auto", "amp": True}}}}
    unknown = derive_version_conversion_defaults(v)
    assert unknown["input_size"] == 800
    assert unknown["training_precision"] is None
    assert derive_version_conversion_defaults(v, {"runtime_precision": "fp16"})["training_precision"] == "fp16"


def test_conversion_defaults_requested_precision_never_claims_actual_runtime():
    v = {"training_lineage": {"parameters": {
        "requested": {"imgsz": 800, "precision": "fp32", "effective_precision": "fp32", "amp": False}
    }}}
    unknown = derive_version_conversion_defaults(v, {"imgsz": 800, "precision": "fp32"})
    assert unknown["input_size"] == 800
    assert unknown["training_precision"] is None
    assert "未记录实际" in unknown["precision_source"]
    confirmed = derive_version_conversion_defaults(
        v, {"runtime_precision": "fp16", "actual_train_params": {"precision": "fp32"}},
    )
    assert confirmed["training_precision"] == "fp16"
    assert confirmed["precision_source"] == "训练任务实际运行精度"


def test_conversion_defaults_actual_train_effective_precision():
    actual = derive_version_conversion_defaults(
        {"training_lineage": {"parameters": {"requested": {"precision": "fp32"}}}},
        {"actual_train_params": {"effective_precision": "fp16"}},
    )
    assert actual["training_precision"] == "fp16"


def test_conversion_defaults_missing_corrupt_metadata_and_fp16_actual():
    x = derive_version_conversion_defaults({"training_lineage": {"parameters": {"actual": {"imgsz": -1, "precision": "auto"}}}})
    assert x["input_size"] == 640
    assert x["training_precision"] is None
    v = {"training_lineage": {"parameters": {"actual": {"imgsz": "800", "precision": "fp16"}, "requested": {"imgsz": 640, "precision": "fp32"}}}}
    assert derive_version_conversion_defaults(v)["training_precision"] == "fp16"
    assert derive_version_conversion_defaults(v)["input_size"] == 800


def test_auto_version_conversion_does_not_override_source_training_defaults():
    from pathlib import Path
    app_source = (Path(__file__).resolve().parents[2] / "app.py").read_text(encoding="utf-8")
    begin = app_source.index("def _v48_auto_convert_version(")
    end = app_source.index("def _v48_archive_training_version(", begin)
    code = app_source[begin:end]
    assert "params={}" in code
    assert 'params={"input_size":int(job.get("imgsz") or 640),"precision":"fp16"}' not in code
    assert "v39_create_deploy_job(" in code
