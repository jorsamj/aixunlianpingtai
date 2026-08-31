import pytest

from platform_core.deployment.inference_tasks import BOARD_ONLY, _last_json_line


def test_runtime_result_parser_uses_last_json_line():
    assert _last_json_line('loading\n{"ok": true, "detections": []}\n')["ok"] is True


def test_board_only_formats_have_truthful_block_messages():
    assert set(BOARD_ONLY) == {".rknn", ".om", ".bmodel"}
    assert all("无法执行真实板端测试" in message for message in BOARD_ONLY.values())


def test_runtime_result_parser_rejects_fake_success_text():
    with pytest.raises(RuntimeError, match="结构化结果"):
        _last_json_line("success")
