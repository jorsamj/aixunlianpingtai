"""WeVisOne protocol isolation and deterministic geometry tests."""

import json
import base64
from types import SimpleNamespace

import pytest
from PIL import Image
from io import BytesIO

from platform_core.auto_label import parse_candidate_response, provider_factory, nms_candidates
from platform_core.annotation_task_service import annotate_one
from platform_core.providers.base import ProviderRequestError
from platform_core.providers.wevisone_vision import (
    WeVisOneVisionProvider, _endpoint, normalize_detection, normalize_label_queries, effective_detection_config,
)


def test_factory_explicitly_selects_dedicated_adapter():
    special = provider_factory({"provider_adapter": "wevisone_vl", "base_url": "http://127.0.0.1:18000", "model_name": "wevisone-vl-2b"})
    assert isinstance(special, WeVisOneVisionProvider)
    assert special.detect_endpoint == "http://127.0.0.1:18000/v1/vision/detect"
    assert _endpoint("http://127.0.0.1:18000/v1", "models").endswith("/v1/models")
    assert provider_factory({"provider_adapter": "local_openai", "base_url": "http://127.0.0.1:18000/v1", "model_name": "wevisone-vl-2b"}).provider == "local_openai"


@pytest.mark.parametrize("width,height", [(1280, 960), (1920, 1080), (1080, 1920), (640, 480)])
def test_native_normalized_xyxy_uses_each_original_axis(width, height):
    boxes = normalize_detection({"response": "<ref>person</ref><box><100><200><500><800></box>"}, width=width, height=height, labels=["person"])
    assert boxes[0]["x1"] == width * 0.1
    assert boxes[0]["x2"] == width * 0.5
    assert boxes[0]["y1"] == height * 0.2
    assert boxes[0]["y2"] == height * 0.8
    assert boxes[0]["confidence"] is None
    assert boxes[0]["confidence_status"] == "unavailable"


def test_native_multiple_targets_keep_independent_boxes_and_labels():
    payload = {"response": "<ref>person</ref><box><100><100><200><250>,<400><500><700><800></box>, <ref>helmet</ref><box><410><510><450><560></box>"}
    boxes = normalize_detection(payload, width=1000, height=1000, labels=["person", "helmet"])
    assert len(boxes) == 3
    assert [box["label"] for box in boxes] == ["person", "person", "helmet"]


def test_empty_is_not_fabricated_and_generic_schema_remains_strict():
    assert normalize_detection({"response": "None"}, width=128, height=128, labels=["fire"]) == []
    assert normalize_detection({"boxes": []}, width=128, height=128, labels=["fire"]) == []
    text = json.dumps({"boxes": [{"label": "person", "confidence": None, "confidence_status": "unavailable", "x1": 12, "y1": 24, "x2": 60, "y2": 120}]})
    parsed = parse_candidate_response(text, width=128, height=128, label_ids={"person": 0}, coordinate_space="pixel", allow_missing_confidence=True)
    assert parsed[0]["confidence"] is None
    assert len(nms_candidates(parsed)) == 1
    with pytest.raises(ValueError, match="字段不符合协议"):
        parse_candidate_response(text, width=128, height=128, label_ids={"person": 0}, coordinate_space="pixel")


def test_live_4070_empty_detection_ref_box_none_is_not_a_broken_box():
    # Captured from the user's live 4070 diagnostic on 2026-11-06.  In
    # particular, "<box>none</box>" is a native no-target declaration, NOT
    # a malformed set of four coordinates.
    payload = {
        "model": "wevisone-vl-2b", "width": 128, "height": 128,
        "response": "<ref>fire</ref><box>none</box>",
        "latency_s": 1.0, "coordinate_system": "xyxy_pixel", "boxes": [],
    }
    assert normalize_detection(payload, width=128, height=128, labels=["fire"]) == []
    assert normalize_detection({"response": payload["response"]}, width=128, height=128, labels=["fire"]) == []


@pytest.mark.parametrize("response,code", [
    ("<ref>fire</ref><box>maybe</box>", "MODEL_OUTPUT_PARSE_ERROR"),
    ("<ref>fire</ref><box>none</box> malformed", "MODEL_OUTPUT_PARSE_ERROR"),
    ("<ref>fire</ref><box><100><200><500><800></box>", "MODEL_OUTPUT_PARSE_ERROR"),
])
def test_empty_structured_boxes_still_reject_invalid_or_mismatched_native_response(response, code):
    with pytest.raises(ProviderRequestError) as error:
        normalize_detection({"coordinate_system": "xyxy_pixel", "boxes": [], "response": response},
                            width=1280, height=960, labels=["fire"])
    assert error.value.code == code


@pytest.mark.parametrize("response", [
    "<ref>person</ref><box>none</box>",
    "<ref>A person standing in the room</ref>\n<box>none</box>",
    "<ref>unconfigured_description</ref><box>NONE</box>",
])
def test_unknown_descriptive_ref_with_explicit_none_is_empty_not_failed(response):
    for payload in ({"response": response}, {"coordinate_system": "xyxy_pixel", "boxes": [], "response": response}):
        assert normalize_detection(payload, width=480, height=480, labels=["person", "tangzhe"]) == []


def test_unknown_ref_with_actual_box_is_rejected_with_bounded_identity():
    with pytest.raises(ProviderRequestError) as failure:
        normalize_detection({"response": "<ref>standing human</ref><box><100><200><300><400></box>"},
                            width=480, height=480, labels=["person", "tangzhe"])
    assert failure.value.code == "MODEL_LABEL_NOT_ALLOWED"
    assert failure.value.diagnostics == {
        "returned_label": "standing human", "label_match_status": "not_allowed",
        "parser_source": "native_ref_box", "allowed_labels": ["person", "tangzhe"], "zero_box": False,
    }


def test_joined_detection_query_cannot_become_a_single_structured_class():
    person = 'An upright human standing or walking on the floor, not lying in bed'
    lying = 'A human lying or reclining on a bed, covered or uncovered by a blanket'
    joined = person + '. ' + lying + '.'
    response = '<ref>' + joined + '</ref><box><100><200><400><600></box>'
    payload = {'coordinate_system': 'xyxy_pixel', 'boxes': [
        {'label': joined, 'bbox_xyxy': [128, 192, 512, 576]},
    ], 'response': response}
    for sample in (payload, {'response': response}):
        with pytest.raises(ProviderRequestError) as error:
            normalize_detection(sample, width=1280, height=960, labels=['person', 'tangzhe'],
                                label_aliases={'person': [person], 'tangzhe': [lying]})
        assert error.value.code == 'MODEL_LABEL_NOT_ALLOWED'
        assert error.value.diagnostics['label_match_status'] == 'not_allowed'


def test_structured_box_class_cannot_hide_unknown_parseable_native_ref():
    payload = {'coordinate_system': 'xyxy_pixel', 'boxes': [
        {'label': 'person', 'bbox_xyxy': [10, 20, 40, 60]},
    ], 'response': '<ref>person. tangzhe.</ref><box><100><100><400><500></box>'}
    with pytest.raises(ProviderRequestError) as error:
        normalize_detection(payload, width=100, height=100, labels=['person', 'tangzhe'])
    assert error.value.code == 'MODEL_LABEL_NOT_ALLOWED'


def test_exact_one_query_can_restore_a_formal_class_without_guessing():
    description = 'An upright human standing or walking on the floor, not lying in bed'
    payload = {'coordinate_system': 'xyxy_pixel', 'width': 1280, 'height': 960,
               'boxes': [{'label': description + '.', 'bbox_xyxy': [128, 192, 512, 576]}],
               'response': '<ref>' + description + '.</ref><box><100><200><400><600></box>'}
    boxes = normalize_detection(payload, width=1280, height=960, labels=['person'],
                                label_aliases={'person': [description]})
    assert [(b['label'], b['x1'], b['y1'], b['x2'], b['y2']) for b in boxes] == [
        ('person', 128, 192, 512, 576)]


def test_frozen_native_config_matches_description_mode_and_has_no_secrets():
    config = {'model_name': 'wevisone-vl-2b', 'provider_adapter': 'wevisone_vl',
              'wevisone_label_queries': {'person': 'A standing human', 'tangzhe': 'A lying human'},
              'coordinate_space': 'pixel', 'coordinate_order': 'xyxy',
              'coordinate_origin': 'top_left', 'coordinate_image_space': 'original_input',
              'api_key': 'do-not-display', 'base_url': 'http://localhost:18000/v1'}
    native = effective_detection_config(config, ['person', 'tangzhe'])
    assert native['task'] == 'detection' and native['request_mode'] == 'per_label'
    assert native['label_queries']['person'] == 'A standing human'
    assert native['coordinate_space'] == 'pixel' and native['coordinate_image_space'] == 'original_input'
    assert native['generic_prompt_applied'] is False
    assert 'do-not-display' not in json.dumps(native)
    assert effective_detection_config(config, ['person'])['request_mode'] == 'category_list'
    assert effective_detection_config({'model_name': 'we', 'wevisone_label_queries': {}},
                                      ['person', 'tangzhe'])['request_mode'] == 'category_list'


@pytest.mark.parametrize("label", [" PERSON ", "person.", "Person。", "PeRsOn! "])
def test_presentational_label_variants_are_deterministic_without_fuzzy_matching(label):
    boxes = normalize_detection({"coordinate_system": "xyxy_pixel", "boxes": [
        {"label": label, "bbox_xyxy": [10, 20, 30, 50]},
    ]}, width=480, height=480, labels=["person"])
    assert [box["label"] for box in boxes] == ["person"]


def test_display_equivalent_alias_conflicts_fail_closed():
    with pytest.raises(ProviderRequestError) as error:
        normalize_detection({"boxes": []}, width=480, height=480, labels=["person", "tangzhe"],
                            label_aliases={"person": ["Standing human"], "tangzhe": [" standing HUMAN. "]})
    assert error.value.code == "MODEL_LABEL_AMBIGUOUS"
    with pytest.raises(ValueError, match="不能重复"):
        normalize_label_queries({"person": "A person standing.", "tangzhe": "a person standing"})


def test_uppercase_frozen_code_can_still_register_its_explicit_alias():
    boxes = normalize_detection({"coordinate_system": "xyxy_pixel", "boxes": [
        {"label": " Standing Human. ", "bbox_xyxy": [10, 20, 30, 50]},
    ]}, width=480, height=480, labels=["Person"],
        label_aliases={"Person": ["standing human"]})
    assert [box["label"] for box in boxes] == ["Person"]


def test_raw_structure_and_empty_structured_boxes_conflict_even_with_unknown_label():
    with pytest.raises(ProviderRequestError) as error:
        normalize_detection({"coordinate_system": "xyxy_pixel", "boxes": [],
                            "response": "<ref>unknown_object</ref><box><100><100><300><300></box>"},
                            width=480, height=480, labels=["person"])
    assert error.value.code == "MODEL_OUTPUT_PARSE_ERROR"
    assert error.value.diagnostics["label_match_status"] == "protocol_conflict"


def test_missing_upstream_request_id_keeps_safe_label_and_wire_diagnostics():
    provider = WeVisOneVisionProvider(
        base_url="http://127.0.0.1:18002/wevis2/v1", model="wevisone-vl-2b",
        label_queries={"person": "An upright human standing or walking on the floor, not lying in bed"},
        session=SimpleNamespace(post=lambda *_a, **_kw: SimpleNamespace(
            ok=True, status_code=200, headers={"x-backend-instance-id": "gpu0"},
            json=lambda: {"coordinate_system": "xyxy_pixel", "width": 64, "height": 64,
                          "boxes": [{"label": "standing human", "bbox_xyxy": [2, 3, 20, 30]}]},
        )),
    )
    image = BytesIO();Image.new("RGB", (64, 64), "white").save(image, "PNG")
    with pytest.raises(ProviderRequestError) as error:
        provider.annotate(image_bytes=image.getvalue(), prompt="", output_schema={}, labels=["person"])
    assert error.value.code == "MODEL_LABEL_NOT_ALLOWED"
    assert error.value.status_code == 200
    assert error.value.request_id == ""
    assert error.value.diagnostics["returned_label"] == "standing human"
    assert error.value.diagnostics["allowed_labels"] == ["person"]
    assert error.value.diagnostics["response_summary"]["structured_box_count"] == 1
    assert error.value.diagnostics["backend_instance_id"] == "gpu0"


@pytest.mark.parametrize("response_value,source", [(None,"invalid_json"), ([],"invalid_json_shape")])
def test_http_200_invalid_json_or_wrong_shape_has_bounded_parser_evidence(response_value, source):
    def parse():
        if response_value is None:
            raise ValueError("invalid JSON")
        return response_value
    provider = WeVisOneVisionProvider(base_url="http://127.0.0.1:18000/v1", model="wevisone-vl-2b",
                                     session=SimpleNamespace(post=lambda *_a, **_k: SimpleNamespace(
                                         ok=True, status_code=200, headers={}, json=parse)))
    image = BytesIO();Image.new("RGB", (64, 64), "white").save(image,"PNG")
    with pytest.raises(ProviderRequestError) as failure:
        provider.annotate(image_bytes=image.getvalue(),prompt="",output_schema={},labels=["person"])
    assert failure.value.code == "MODEL_OUTPUT_PARSE_ERROR" and failure.value.status_code == 200
    assert failure.value.diagnostics["parser_source"] == source
    assert failure.value.diagnostics["response_summary"] == {"parser_source": source}


def test_structured_positive_boxes_reject_raw_no_target_for_same_label():
    with pytest.raises(ProviderRequestError) as error:
        normalize_detection({"coordinate_system": "xyxy_pixel", "boxes": [
            {"label": "fire", "bbox_xyxy": [10, 20, 30, 40]},
        ], "response": "<ref>fire</ref><box>none</box>"},
                            width=1280, height=960, labels=["fire"])
    assert error.value.code == "MODEL_OUTPUT_PARSE_ERROR"


@pytest.mark.parametrize("payload,code", [
    ({"response": "I cannot see anything"}, "MODEL_OUTPUT_FAILED"),
    ({"boxes": [{"label": "pedestrian", "bbox": [1, 2, 4, 5]}], "coordinate_space": "pixel"}, "MODEL_LABEL_NOT_ALLOWED"),
    ({"boxes": [{"label": "person", "bbox": [100, 200, 500, 800]}]}, "MODEL_COORDINATE_SPACE_UNKNOWN"),
    ({"boxes": [{"label": "person", "bbox": [0, 0, 1100, 900]}], "coordinate_space": "normalized_1000"}, "MODEL_COORDINATE_INVALID"),
    ({"boxes": [{"label": "person", "bbox": [20, 10, 2, 5]}], "coordinate_space": "pixel"}, "MODEL_COORDINATE_INVALID"),
    ({"status": "failed", "boxes": []}, "MODEL_OUTPUT_FAILED"),
])
def test_native_invalid_results_fail_closed(payload, code):
    with pytest.raises(ProviderRequestError) as error:
        normalize_detection(payload, width=640, height=480, labels=["person"])
    assert error.value.code == code


def test_json_pixel_boxes_do_not_get_scaled_twice():
    rows = normalize_detection({"coordinate_space": "pixel", "boxes": [{"label": "person", "box": [128, 96, 640, 480]}]}, width=1280, height=960, labels=["person"])
    assert (rows[0]["x1"], rows[0]["y1"], rows[0]["x2"], rows[0]["y2"]) == (128, 96, 640, 480)


def test_reported_4070_detect_contract_pixel_xyxy_and_frozen_label_aliases():
    # This reproduces the HTTP field names reported from the deployed FastAPI;
    # the service source file /data/ai-runtime/.../app.py is NOT available here.
    payload = {"coordinate_system": "xyxy_pixel", "boxes": [
        {"label": "人员", "bbox_xyxy": [128, 192, 640, 768], "bbox_normalized": [100, 200, 500, 800]},
        {"label": "person", "bbox_xyxy": [700, 100, 900, 400], "bbox_normalized": [547, 104, 703, 417], "confidence": 0.9},
    ], "response": "<ref>person</ref><box><100><200><500><800></box>"}
    boxes = normalize_detection(payload, width=1280, height=960, labels=["person"], label_aliases={"person": ["人员"]})
    assert [(b["x1"], b["y1"], b["x2"], b["y2"]) for b in boxes] == [(128, 192, 640, 768), (700, 100, 900, 400)]
    assert [b["label"] for b in boxes] == ["person", "person"]
    assert [b["confidence_status"] for b in boxes] == ["unavailable", "provided"]


def test_exact_4070_480_response_reaches_worker_candidate_without_fabricated_score(tmp_path):
    # Byte/field-equivalent to the incident sample (confidence/score absent).
    payload = {"model": "wevisone-vl-2b", "width": 480, "height": 480,
               "coordinate_system": "xyxy_pixel", "boxes": [
                   {"label": "person", "bbox_xyxy": [230.88, 168.0, 250.08, 199.68],
                    "bbox_normalized": [0.481, 0.35, 0.521, 0.416]},
               ]}
    cfg = {"id": "8d5cc70403d5", "provider_adapter": "wevisone_vl",
           "base_url": "http://127.0.0.1:18003/v1", "model_name": "wevisone-vl-2b",
           "coordinate_space": "pixel", "coordinate_order": "xyxy",
           "coordinate_origin": "top_left", "coordinate_image_space": "original_input"}
    provider = provider_factory(cfg)
    provider.session = SimpleNamespace(post=lambda *_a, **_kw: SimpleNamespace(ok=True, json=lambda: payload))
    image = tmp_path / "incident.png"
    Image.new("RGB", (480, 480), "white").save(image)
    request = {"_provider": provider, "_provider_config": cfg, "label_ids": {"person": 0},
               "label_aliases": {"person": []}, "label_catalog": [{"code": "person", "class_id": 0}],
               "threshold": 0.9}
    result = annotate_one(request, {"id": "incident-1", "path": str(image), "width": 480, "height": 480})
    assert len(result["boxes"]) == 1
    box = result["boxes"][0]
    assert (box["x1"], box["y1"], box["x2"], box["y2"]) == (230.88, 168.0, 250.08, 199.68)
    assert box["confidence"] is None and box["confidence_status"] == "unavailable"
    assert result["diagnostics"]["confidence_unavailable_count"] == 1


@pytest.mark.parametrize("payload,expected", [
    ({"coordinate_system": "xyxy_pixel", "boxes": [
        {"label": "person", "bbox_xyxy": [1, 2, 10, 20]},
        {"label": "person", "bbox_xyxy": [30, 40, 70, 80]},
    ]}, 2),
    ({"coordinate_system": "xyxy_pixel", "boxes": []}, 0),
    ({"coordinate_space": "normalized_01", "coordinate_order": "xyxy", "boxes": [
        {"label": "person", "bbox_normalized": [0.1, 0.2, 0.5, 0.8]},
    ]}, 1),
])
def test_structured_pixel_multiple_empty_and_normalized_01(payload, expected):
    rows = normalize_detection(payload, width=480, height=480, labels=["person"])
    assert len(rows) == expected
    if "coordinate_space" in payload:
        assert (rows[0]["x1"], rows[0]["y1"], rows[0]["x2"], rows[0]["y2"]) == (48, 96, 240, 384)


def test_configurable_yxyx_bottom_left_converts_once_and_mismatches_fail_closed():
    payload = {"coordinate_system": "yxyx_normalized_01", "coordinate_origin": "bottom_left",
               "boxes": [{"label": "person", "coordinates": [0.2, 0.1, 0.8, 0.5]}]}
    expected = {"coordinate_space": "normalized_01", "coordinate_order": "yxyx",
                "coordinate_origin": "bottom_left", "coordinate_image_space": "original_input"}
    rows = normalize_detection(payload, width=480, height=480, labels=["person"], expected_contract=expected)
    assert (rows[0]["x1"], rows[0]["y1"], rows[0]["x2"], rows[0]["y2"]) == (48, 96, 240, 384)
    with pytest.raises(ProviderRequestError) as mismatch:
        normalize_detection({"coordinate_system": "xyxy_pixel", "boxes": [
            {"label": "person", "bbox_xyxy": [10, 20, 30, 40]},
        ]}, width=480, height=480, labels=["person"], expected_contract=expected)
    assert mismatch.value.code == "MODEL_COORDINATE_CONTRACT_MISMATCH"


@pytest.mark.parametrize("payload,code", [
    ({"coordinate_system": "xyxy_pixel", "width": 320, "height": 480, "boxes": [
        {"label": "person", "bbox_xyxy": [1, 2, 10, 20]},
    ]}, "MODEL_COORDINATE_GEOMETRY_UNVERIFIED"),
    ({"coordinate_system": "xyxy_pixel", "boxes": [
        {"label": "person", "bbox_xyxy": [20, 30, 10, 50]},
    ]}, "MODEL_COORDINATE_INVALID"),
    ({"coordinate_system": "xyxy_pixel", "boxes": [
        {"label": "unknown", "bbox_xyxy": [1, 2, 10, 20]},
    ]}, "MODEL_LABEL_NOT_ALLOWED"),
    ({"coordinate_system": "xyxy_pixel", "boxes": [{}]}, "MODEL_LABEL_NOT_ALLOWED"),
])
def test_4070_invalid_geometry_and_labels_remain_per_image_errors(payload, code):
    with pytest.raises(ProviderRequestError) as error:
        normalize_detection(payload, width=480, height=480, labels=["person"])
    assert error.value.code == code


@pytest.mark.parametrize("payload,code", [
    ({"coordinate_system": "xyxy_pixel", "boxes": [{"label": "person", "bbox_xyxy": [0, 0, 1300, 500]}]}, "MODEL_COORDINATE_INVALID"),
    ({"coordinate_system": "xyxy_pixel", "boxes": [{"label": "person", "bbox_xyxy": [20, 30, 10, 50]}]}, "MODEL_COORDINATE_INVALID"),
    ({"coordinate_system": "xyxy_pixel", "boxes": [{"label": "dog", "bbox_xyxy": [20, 30, 40, 50]}]}, "MODEL_LABEL_NOT_ALLOWED"),
    ({"coordinate_system": "normalized_1000", "boxes": [{"label": "person", "bbox_xyxy": [20, 30, 40, 50]}]}, "MODEL_COORDINATE_SPACE_UNKNOWN"),
    ({"boxes": [{"label": "person", "bbox_xyxy": [20, 30, 40, 50]}]}, "MODEL_COORDINATE_SPACE_UNKNOWN"),
    ({"coordinate_system": "xyxy_pixel", "boxes": [{"label": "person", "bbox_xyxy": [20, 30, 40, 50], "confidence_status": "provided"}]}, "MODEL_OUTPUT_PARSE_ERROR"),
    ({"coordinate_system": "xyxy_pixel", "boxes": [{"label": "person", "bbox_xyxy": [20, 30, 40, 50], "confidence": 1.2}]}, "MODEL_OUTPUT_PARSE_ERROR"),
    ({"coordinate_system": "xyxy_pixel", "boxes": [] , "response": "<ref>person</ref><box><100><200><500><800></box>"}, "MODEL_OUTPUT_PARSE_ERROR"),
    ({"coordinate_system": "xyxy_pixel", "boxes": [], "response": "I cannot identify objects"}, "MODEL_OUTPUT_FAILED"),
    ({"coordinate_system": "xyxy_pixel", "boxes": "[]"}, "MODEL_OUTPUT_PARSE_ERROR"),
    ({"coordinate_system": "xyxy_pixel", "boxes": [{"label": "person", "bbox_xyxy": [1, 2, 3, 4]}] * 301}, "MODEL_OUTPUT_TOO_MANY_BOXES"),
])
def test_reported_4070_invalid_shapes_are_not_silent_no_targets(payload, code):
    with pytest.raises(ProviderRequestError) as error:
        normalize_detection(payload, width=1280, height=960, labels=["person"])
    assert error.value.code == code


def test_frozen_alias_collision_is_rejected():
    payload = {"coordinate_system": "xyxy_pixel", "boxes": [{"label": "同名", "bbox_xyxy": [1, 2, 3, 4]}]}
    with pytest.raises(ProviderRequestError, match="冲突"):
        normalize_detection(payload, width=80, height=60, labels=["fire", "smoke"],
                            label_aliases={"fire": ["同名"], "smoke": ["同名"]})


def test_provider_sends_explicit_labels_and_rejects_wrong_loaded_model():
    calls = []
    def fake_post(url, **kwargs):
        calls.append((url, kwargs))
        return SimpleNamespace(ok=True, json=lambda: {"response": "None"})
    provider = WeVisOneVisionProvider(base_url="http://127.0.0.1:18000", model="wevisone-vl-2b", session=SimpleNamespace(post=fake_post, get=lambda *a, **k: SimpleNamespace(ok=True, json=lambda: {"data": [{"id": "qwen3.5"}]})))
    with pytest.raises(ProviderRequestError) as error:
        provider.inspect_model()
    assert error.value.code == "MODEL_NOT_LOADED"
    b = BytesIO(); Image.new("RGB", (128, 128), "white").save(b, "JPEG")
    result = provider.annotate(image_bytes=b.getvalue(), prompt="detect fire", output_schema={}, labels=["fire"])
    assert json.loads(result["text"]) == {"boxes": []}
    assert calls[0][0].endswith("/v1/vision/detect")
    body = calls[0][1]["json"]
    assert set(body) == {"image", "query"}
    assert body["query"] == ["fire"]
    assert body["image"].startswith("data:image/jpeg;base64,")
    assert base64.b64decode(body["image"].partition(",")[2]) == b.getvalue()


def test_native_query_descriptions_are_sent_and_mapped_back_to_durable_codes():
    descriptions = {
        "person": "A standing or walking human outside any bed, never a fire extinguisher",
        "tangzhe": "A human reclining on a bed, including someone under a blanket",
    }
    calls = []
    def fake_post(url, **kwargs):
        calls.append((url, kwargs["json"]))
        return SimpleNamespace(ok=True, json=lambda: {
            "coordinate_system": "xyxy_pixel",
            "boxes": [
                {"label": descriptions["tangzhe"], "bbox_xyxy": [20, 40, 300, 200]},
                {"label": descriptions["person"], "bbox_xyxy": [420, 30, 520, 400]},
            ],
        })
    b = BytesIO(); Image.new("RGB", (640, 480)).save(b, "JPEG")
    provider = provider_factory({"provider_adapter": "wevisone_vl", "base_url": "http://127.0.0.1:18000",
                                 "model_name": "wevisone-vl-2b", "wevisone_label_queries": descriptions})
    provider.session = SimpleNamespace(post=fake_post)
    response = provider.annotate(image_bytes=b.getvalue(), prompt="THIS CHAT PROMPT MUST NOT BE SENT",
                                 output_schema={}, labels=["person", "tangzhe"])
    assert calls[0][0].endswith("/v1/vision/detect")
    assert calls[0][1]["query"] == [descriptions["person"], descriptions["tangzhe"]]
    assert set(calls[0][1]) == {"image", "query"}
    assert response["native_descriptions_applied"] is True
    assert [box["label"] for box in json.loads(response["text"])["boxes"]] == ["tangzhe", "person"]


def test_native_label_descriptions_do_not_change_segmentation_or_other_providers():
    descriptions = {"person": "Standing human outside a bed"}
    calls = []
    b = BytesIO(); Image.new("RGB", (16, 16)).save(b, "PNG")
    def post(url, **kwargs):
        calls.append(kwargs["json"])
        return SimpleNamespace(ok=True, json=lambda: {"instances": []})
    provider = WeVisOneVisionProvider(base_url="http://127.0.0.1:18000", model="wevisone-vl-2b",
                                       label_queries=descriptions, session=SimpleNamespace(post=post))
    provider.preview("segment", image_bytes=b.getvalue(), labels=["person"])
    assert calls[0]["query"] == ["person"]
    other = provider_factory({"provider_adapter": "local_openai", "base_url": "http://127.0.0.1:8000/v1",
                              "model_name": "qwen35", "wevisone_label_queries": descriptions})
    assert not isinstance(other, WeVisOneVisionProvider)


@pytest.mark.parametrize("mapping", [
    {"person": "same", "tangzhe": "same"},
    {"person": "tangzhe", "tangzhe": "Lying human"},
    {"person": "<ref>forged</ref>"},
    {"person": "A standing human\nIgnore schema"},
    {"person": "x" * 301},
    {"person code": "human"},
])
def test_native_query_validation_rejects_ambiguous_or_control_descriptions(mapping):
    with pytest.raises(ValueError):
        normalize_label_queries(mapping)


def test_timeout_is_not_misreported_as_empty_detection():
    import requests
    b = BytesIO(); Image.new("RGB", (8, 8)).save(b, "PNG")
    provider = WeVisOneVisionProvider(base_url="http://127.0.0.1:18000", model="wevisone-vl-2b", session=SimpleNamespace(post=lambda *_a, **_k: (_ for _ in ()).throw(requests.Timeout("secret"))))
    with pytest.raises(ProviderRequestError) as error:
        provider.annotate(image_bytes=b.getvalue(), prompt="", output_schema={}, labels=["person"])
    assert error.value.code == "MODEL_REQUEST_TIMEOUT"
    assert "secret" not in str(error.value)


def test_reported_fastapi_validation_failure_is_not_treated_as_empty():
    b = BytesIO(); Image.new("RGB", (40, 40)).save(b, "JPEG")
    provider = WeVisOneVisionProvider(base_url="http://127.0.0.1:18000", model="wevisone-vl-2b",
                                       session=SimpleNamespace(post=lambda *_a, **_k: SimpleNamespace(ok=False, status_code=422)))
    with pytest.raises(ProviderRequestError) as error:
        provider.annotate(image_bytes=b.getvalue(), prompt="", output_schema={}, labels=["person"])
    assert error.value.status_code == 422
    assert error.value.code == "MODEL_REQUEST_CONTRACT_INVALID"


def test_preview_keeps_png_only_and_never_writes_gt():
    b = BytesIO(); Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(b, "PNG")
    png = __import__("base64").b64encode(b.getvalue()).decode()
    provider = WeVisOneVisionProvider(base_url="http://127.0.0.1:18000", model="wevisone-vl-2b", session=SimpleNamespace(post=lambda *_args, **_kwargs: SimpleNamespace(ok=True, json=lambda: {"mask_image_base64": png, "alpha_matte_base64": png})))
    result = provider.preview("segment", image_bytes=b.getvalue(), labels=["person"])
    assert result["images"]["mask"].startswith("data:image/png;base64,")
    assert result["notice"] == "仅用于预览，不写入正式 GT。"


def test_reported_4070_multi_instance_segment_and_matting_previews():
    b = BytesIO(); Image.new("RGBA", (16, 16), (120, 30, 20, 150)).save(b, "PNG")
    png = base64.b64encode(b.getvalue()).decode()
    payload = {"instances": [
        {"label": "person", "mask_png": png, "cutout_png": png},
        {"label": "person", "mask_png": "data:image/png;base64," + png, "cutout_png": png},
    ]}
    provider = WeVisOneVisionProvider(base_url="http://127.0.0.1:18000", model="wevisone-vl-2b",
                                       session=SimpleNamespace(post=lambda *_a, **_k: SimpleNamespace(ok=True, json=lambda: payload)))
    for operation in ("segment", "matting"):
        result = provider.preview(operation, image_bytes=b.getvalue(), labels=["person"])
        assert result["no_target"] is False
        assert len(result["instances"]) == 2
        assert all(set(row["images"]) == {"mask", "foreground"} for row in result["instances"])
        assert result["images"] == result["instances"][0]["images"]
    payload["instances"] = []
    assert provider.preview("segment", image_bytes=b.getvalue(), labels=["person"])["no_target"] is True
    payload["instances"] = [{"label": "person", "mask_png": "not-base64"}]
    with pytest.raises(ProviderRequestError, match="有效 PNG"):
        provider.preview("segment", image_bytes=b.getvalue(), labels=["person"])


def test_image_payload_is_bounded_before_any_http_call():
    provider = WeVisOneVisionProvider(base_url="http://127.0.0.1:18000", model="wevisone-vl-2b",
                                       session=SimpleNamespace(post=lambda *_a, **_k: pytest.fail("must reject before HTTP")))
    with pytest.raises(ProviderRequestError) as error:
        provider.annotate(image_bytes=b"x" * 10_000_001, prompt="", output_schema={}, labels=["person"])
    assert error.value.code == "MODEL_IMAGE_TOO_LARGE"


def test_annotation_worker_keeps_unscored_boxes_for_human_review(tmp_path):
    path = tmp_path / "image.png"
    Image.new("RGB", (1280, 960), "white").save(path)

    class FakeProvider:
        def annotate(self, **kwargs):
            assert kwargs["labels"] == ["person"]
            return {"text": json.dumps({"boxes": [
                {"label": "person", "confidence": None, "confidence_status": "unavailable",
                 "x1": 128, "y1": 96, "x2": 640, "y2": 480}
            ]})}

    config = {"provider_adapter": "wevisone_vl", "coordinate_space": "pixel", "coordinate_order": "xyxy", "model_name": "wevisone-vl-2b", "id": "a"}
    result = annotate_one({"_provider": FakeProvider(), "_provider_config": config,
                           "label_catalog": [{"code": "person", "class_id": 0}],
                           "label_ids": {"person": 0}, "label_aliases": {}, "threshold": 0.9},
                          {"path": str(path), "width": 1280, "height": 960, "id": "img"})
    assert len(result["boxes"]) == 1
    assert result["boxes"][0]["confidence"] is None
    assert result["boxes"][0]["confidence_status"] == "unavailable"
    assert result["diagnostics"]["confidence_unavailable_count"] == 1
    assert result["diagnostics"]["counts"]["threshold_filtered"] == 0

@pytest.mark.parametrize('base', ['http://inference:18002/wevis2/v1', 'http://inference:18002/wevis2/v1/vision/detect'])
def test_gateway_prefix_preserved_for_models_and_detection(base):
    assert _endpoint(base, 'detect') == 'http://inference:18002/wevis2/v1/vision/detect'
    assert _endpoint(base, 'models') == 'http://inference:18002/wevis2/v1/models'

@pytest.mark.parametrize('path', ['/../v1', '/%2e%2e/v1', '//wevis2/v1', '/wevis2//v1'])
def test_gateway_prefix_rejects_ambiguous_paths(path):
    with pytest.raises(ValueError):
        _endpoint('http://inference:18002'+path, 'detect')

def test_native_422_reports_safe_request_contract_without_echoing_image():
    response = SimpleNamespace(ok=False, status_code=422, headers={'x-request-id':'native-422'})
    session = SimpleNamespace(post=lambda *a, **kw: response)
    provider = WeVisOneVisionProvider(base_url='http://inference:18000/v1', model='wevisone-vl-2b', session=session)
    binary=BytesIO();Image.new('RGB',(12,12)).save(binary,format='PNG')
    with pytest.raises(ProviderRequestError) as caught:
        provider.annotate(image_bytes=binary.getvalue(), prompt='', output_schema={}, labels=['person'])
    error=caught.value
    assert error.code == 'MODEL_REQUEST_CONTRACT_INVALID'
    assert error.status_code == 422
    assert error.request_id == 'native-422'
    assert error.stage == 'model_request'
    assert error.diagnostics['request_contract'] == {'image':'data_uri','query':'list[str]','query_count':1,'operation':'detect'}
    assert 'base64' not in str(error.diagnostics)

def test_failed_image_evidence_keeps_http_stage_and_scrubs_secrets():
    from platform_core.annotation_task_service import _failure_evidence
    error = ProviderRequestError('bad api_key=secret-value', code='MODEL_REQUEST_CONTRACT_INVALID', status_code=422, request_id='trace-1', solution='Check query')
    result = _failure_evidence(error, attempt=3)
    assert result['error_stage'] == 'model_request'
    assert result['http_status'] == 422
    assert result['attempt_count'] == 3
    assert result['request_id'] == 'trace-1'
    assert 'secret-value' not in str(result)

@pytest.mark.parametrize('code,stage', [('MODEL_COORDINATE_INVALID','coordinate_validation'),('MODEL_OUTPUT_PARSE_ERROR','response_parse'),('MODEL_REQUEST_TIMEOUT','model_request')])
def test_failed_image_evidence_distinguishes_stages(code,stage):
    from platform_core.annotation_task_service import _failure_evidence
    assert _failure_evidence(ProviderRequestError('failed',code=code),attempt=1)['error_stage']==stage
