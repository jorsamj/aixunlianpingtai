import pytest

from platform_core.auto_label import nms_candidates, parse_candidate_response, raw_response_hash


def test_valid_boxes_are_normalized_and_markdown_fence_is_allowed():
    result = parse_candidate_response(
        '```json\n{"boxes":[{"label":"fire","confidence":0.9,"x1":10,"y1":20,"x2":100,"y2":120}]}\n```',
        width=640,
        height=480,
        label_ids={"fire": 0},
    )
    assert result == [{
        "class_id": 0,
        "label": "fire",
        "confidence": 0.9,
        "x1": 10.0,
        "y1": 20.0,
        "x2": 100.0,
        "y2": 120.0,
    }]


@pytest.mark.parametrize(
    "text",
    [
        '{"boxes":[{"label":"unknown","confidence":0.9,"x1":0,"y1":0,"x2":10,"y2":10}]}',
        '{"boxes":[{"label":"fire","confidence":0.9,"x1":-1,"y1":0,"x2":700,"y2":10}]}',
        '{"boxes":[{"label":"fire","confidence":1.2,"x1":0,"y1":0,"x2":10,"y2":10}]}',
        '[{"label":"fire","confidence":0.9,"x1":0,"y1":0,"x2":10,"y2":10}]',
        '说明文字 {"boxes":[]}',
    ],
)
def test_unknown_invalid_or_non_object_output_is_rejected(text):
    with pytest.raises(ValueError):
        parse_candidate_response(text, width=640, height=480, label_ids={"fire": 0})


def test_nms_is_deterministic_and_only_suppresses_same_label():
    boxes = [
        {"class_id": 0, "label": "fire", "confidence": 0.8, "x1": 11, "y1": 11, "x2": 101, "y2": 101},
        {"class_id": 1, "label": "smoke", "confidence": 0.7, "x1": 10, "y1": 10, "x2": 100, "y2": 100},
        {"class_id": 0, "label": "fire", "confidence": 0.9, "x1": 10, "y1": 10, "x2": 100, "y2": 100},
    ]
    result = nms_candidates(boxes, iou_threshold=0.5)
    assert [(box["label"], box["confidence"]) for box in result] == [("fire", 0.9), ("smoke", 0.7)]


def test_raw_response_hash_is_stable_without_storing_response():
    assert raw_response_hash("secret response") == raw_response_hash("secret response")
    assert len(raw_response_hash("secret response")) == 64
