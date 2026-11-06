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
    WeVisOneVisionProvider, _endpoint, normalize_detection, normalize_label_queries,
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
    ("<ref>smoke</ref><box>none</box>", "MODEL_LABEL_NOT_ALLOWED"),
    ("<ref>fire</ref><box><100><200><500><800></box>", "MODEL_OUTPUT_PARSE_ERROR"),
])
def test_empty_structured_boxes_still_reject_invalid_or_mismatched_native_response(response, code):
    with pytest.raises(ProviderRequestError) as error:
        normalize_detection({"coordinate_system": "xyxy_pixel", "boxes": [], "response": response},
                            width=1280, height=960, labels=["fire"])
    assert error.value.code == code


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
    assert error.value.code == "MODEL_SERVICE_ERROR"


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
