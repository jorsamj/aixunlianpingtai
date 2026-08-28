import pytest

from platform_core.conversion import build_manifest, file_record, validate_target


def test_rknn_chip_must_be_explicit_and_supported():
    with pytest.raises(ValueError, match="rk3588|rk3568"):
        validate_target("rockchip", {})
    with pytest.raises(ValueError, match="rk3588|rk3568"):
        validate_target("rockchip", {"chip": "rk3576"})


def test_atlas_soc_and_tensorrt_environment_are_required():
    with pytest.raises(ValueError, match="soc_version"):
        validate_target("ascend", {})
    with pytest.raises(ValueError, match="target_environment"):
        validate_target("tensorrt", {"precision": "fp16"})


def test_int8_requires_calibration_snapshot():
    with pytest.raises(ValueError, match="calibration_snapshot"):
        validate_target("rockchip", {"chip": "rk3588", "precision": "int8"})


def test_manifest_records_source_tool_outputs_and_validation_state(tmp_path):
    output = tmp_path / "model.rknn"
    output.write_bytes(b"real-artifact")
    manifest = build_manifest(
        source={"version_id": "v1", "sha256": "abc"},
        target={"kind": "rockchip", "chip": "rk3588"},
        tool={"name": "rknn-toolkit2", "version": "2.3.2"},
        outputs=[file_record(output)],
        hardware_verified=False,
    )
    assert manifest["target"]["chip"] == "rk3588"
    assert manifest["outputs"][0]["sha256"]
    assert manifest["status"] == "converted_unverified"
    assert manifest["hardware_verified"] is False
