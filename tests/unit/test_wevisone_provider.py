"""WeVisOne protocol isolation and deterministic geometry tests."""

import json
from types import SimpleNamespace

import pytest
from PIL import Image
from io import BytesIO

from platform_core.auto_label import parse_candidate_response, provider_factory, nms_candidates
from platform_core.annotation_task_service import annotate_one
from platform_core.providers.base import ProviderRequestError
from platform_core.providers.wevisone_vision import (
    WeVisOneVisionProvider, _endpoint, normalize_detection,
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


@pytest.mark.parametrize("payload,code", [
    ({"response": "I cannot see anything"}, "MODEL_OUTPUT_PARSE_ERROR"),
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
    assert calls[0][1]["json"]["labels"] == ["fire"]
    assert calls[0][1]["json"]["model"] == "wevisone-vl-2b"


def test_timeout_is_not_misreported_as_empty_detection():
    import requests
    b = BytesIO(); Image.new("RGB", (8, 8)).save(b, "PNG")
    provider = WeVisOneVisionProvider(base_url="http://127.0.0.1:18000", model="wevisone-vl-2b", session=SimpleNamespace(post=lambda *_a, **_k: (_ for _ in ()).throw(requests.Timeout("secret"))))
    with pytest.raises(ProviderRequestError) as error:
        provider.annotate(image_bytes=b.getvalue(), prompt="", output_schema={}, labels=["person"])
    assert error.value.code == "MODEL_REQUEST_TIMEOUT"
    assert "secret" not in str(error.value)


def test_preview_keeps_png_only_and_never_writes_gt():
    b = BytesIO(); Image.new("RGBA", (16, 16), (0, 0, 0, 0)).save(b, "PNG")
    png = __import__("base64").b64encode(b.getvalue()).decode()
    provider = WeVisOneVisionProvider(base_url="http://127.0.0.1:18000", model="wevisone-vl-2b", session=SimpleNamespace(post=lambda *_args, **_kwargs: SimpleNamespace(ok=True, json=lambda: {"mask_image_base64": png, "alpha_matte_base64": png})))
    result = provider.preview("segment", image_bytes=b.getvalue(), labels=["person"])
    assert result["images"]["mask"].startswith("data:image/png;base64,")
    assert result["notice"] == "仅用于预览，不写入正式 GT。"


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
