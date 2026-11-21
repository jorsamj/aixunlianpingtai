"""Focused invariants for the extracted PaddleDetection catalog formatter."""

from pathlib import Path
import re

import pytest

from platform_core.paddle_detection_catalog import (
    _parse_paddle_config_name,
    _safe_key,
)


@pytest.mark.parametrize(
    ("relative", "family", "size", "imgsz", "batch", "recommended"),
    [
        ("configs/ppyoloe/ppyoloe_plus_crn_s_80e_coco.yml", "PP-YOLOE+", "S", 640, 4, True),
        ("configs/picodet/picodet_s_320_coco.yml", "PicoDet", "S", 320, 4, True),
        ("configs/rtdetr/rtdetr_r50_6x_coco.yml", "RT-DETR", "R50", 640, 1, False),
    ],
)
def test_parser_retains_presentation_and_training_defaults(
    tmp_path, relative, family, size, imgsz, batch, recommended,
):
    root = tmp_path / "PaddleDetection"
    source = root / Path(relative)
    projected = _parse_paddle_config_name(source, root)
    assert projected["family"] == family
    assert projected["size"] == size
    assert projected["default_imgsz"] == imgsz
    assert projected["default_batch"] == batch
    assert projected["recommended"] is recommended
    assert projected["framework"] == "paddle"
    assert projected["engine"] == "PaddleDetection"
    assert projected["config_relpath"] == relative
    assert projected["config_path"] == str(source)
    assert projected["dataset"] == "COCO"
    assert projected["key"] == "paddledet_" + _safe_key(relative)
    assert projected["command_template"].count("{batch}") == 2
    assert "{paddle_class_options}" in projected["command_template"]
    assert "{paddle_lr_options}" in projected["command_template"]


def test_fallback_outside_root_preserves_basename_and_safe_key(tmp_path):
    cfg = tmp_path / "external" / "det model.yml"
    result = _parse_paddle_config_name(cfg, tmp_path / "PaddleDetection")
    assert result["config_relpath"] == "det model.yml"
    assert result["key"] == "paddledet_det_model_yml"
    assert _safe_key("a\\\\b/++ C.yml") == "a_b_c_yml"
    assert re.fullmatch(r"[0-9a-f]{8}", _safe_key(" / + ")) is not None
