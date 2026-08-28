import pytest

from platform_core.prompts import render_prompt, template_version_id


def test_prompt_injects_labels_and_image_size():
    result = render_prompt(
        "检测 {{labels_json}}，图片尺寸 {{image_width}}x{{image_height}}。{{output_schema}}",
        labels=[{"code": "fire", "display_name_zh": "明火"}],
        width=640,
        height=480,
        business_instruction="只标注可见火焰",
    )
    assert '"code": "fire"' in result
    assert "640x480" in result
    assert '"boxes"' in result


def test_unknown_template_variable_is_rejected():
    with pytest.raises(ValueError, match="未知模板变量"):
        render_prompt("{{api_key}}", labels=[], width=1, height=1, business_instruction="")


def test_template_version_is_stable_and_changes_with_content():
    assert template_version_id("hello") == template_version_id("hello")
    assert template_version_id("hello") != template_version_id("hello world")
