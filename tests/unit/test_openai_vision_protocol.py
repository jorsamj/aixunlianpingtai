"""Protocol contracts using Mock HTTP only; no remote or billable calls."""
import base64

import pytest
import requests

from platform_core.auto_label import CANDIDATE_OUTPUT_SCHEMA, parse_candidate_response
from platform_core.providers.base import ProviderRequestError
from platform_core.providers.openai_vision import OpenAICompatibleVisionProvider

TEXT = '{"boxes":[]}'


def output(text=TEXT, **extra):
    return {"id": "resp-test", "status": "completed", "output": [
        {"type": "reasoning", "summary": [{"type": "summary_text", "text": "not an annotation"}]},
        {"type": "message", "role": "assistant", "status": "completed", "content": [{"type": "output_text", "text": text}]},
    ], **extra}


class Reply:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self.ok = 200 <= status < 300
        self.payload = payload if payload is not None else output()
        self.headers = headers or {"x-request-id": "req-test"}

    def json(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class HTTP:
    def __init__(self, *replies):
        self.replies = list(replies) or [Reply()]
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        assert self.replies, "unexpected additional HTTP request"
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def provider(http=None, **kwargs):
    return OpenAICompatibleVisionProvider(provider="volcengine_ark", base_url=kwargs.pop("base_url", "https://ark.cn-beijing.volces.com/api/v3/responses"), model="glm-5-3-flash-260828", session=http or HTTP(), **kwargs)


def annotate(p, **kwargs):
    return p.annotate(image_bytes=kwargs.pop("image_bytes", b"image"), prompt="only JSON boxes", output_schema=CANDIDATE_OUTPUT_SCHEMA, **kwargs)


@pytest.mark.parametrize("url,protocol,path", [
    ("https://ark.cn-beijing.volces.com/api/v3", "auto", "/api/v3/chat/completions"),
    ("https://host/v1/chat/completions/", "auto", "/v1/chat/completions"),
    ("https://host/api/v3/responses", "auto", "/api/v3/responses"),
    ("https://responses.example/v1", "auto", "/v1/chat/completions"),
    ("https://compat:legacy-password@proxy.example/v1", "auto", "/v1/chat/completions"),
    ("https://host/proxy/responses/v1", "auto", "/proxy/responses/v1/chat/completions"),
    ("https://host/api/v3/responses?region=cn", "auto", "/api/v3/responses?region=cn"),
    ("https://host/api/v3/responses", "chat_completions", "/api/v3/chat/completions"),
    ("https://host/v1/chat/completions", "responses", "/v1/responses"),
    ("https://host/v1", "responses", "/v1/responses"),
    ("https://host/custom/infer?route=responses", "responses", "/custom/infer?route=responses"),
])
def test_endpoint_path_is_exact_and_explicit_protocol_wins(url, protocol, path):
    p = provider(base_url=url, api_protocol=protocol)
    assert p.endpoint == url.split("/", 3)[0] + "//" + url.split("/", 3)[2] + path


def test_saved_responses_url_without_new_field_is_automatically_compatible():
    assert provider().endpoint.endswith("/api/v3/responses")
    assert annotate(provider())["text"] == TEXT


def test_custom_auto_address_requires_confirmation_without_network():
    http = HTTP()
    with pytest.raises(ProviderRequestError) as caught:
        provider(http, base_url="https://host/not-responses?responses=1")
    assert caught.value.code == "MODEL_PROTOCOL_REQUIRED"
    assert http.calls == []


def test_responses_request_and_final_output_exclude_reasoning():
    http = HTTP()
    result = annotate(provider(http), image_bytes=b"\x89PNG\r\n\x1a\nimage")
    url, request = http.calls[0]
    body = request["json"]
    assert url.endswith("/api/v3/responses")
    assert "messages" not in body and "response_format" not in body
    assert body["model"] == "glm-5-3-flash-260828" and body["stream"] is False
    assert body["text"]["format"]["type"] == "json_schema"
    assert body["text"]["format"]["schema"] == CANDIDATE_OUTPUT_SCHEMA
    content = body["input"][0]["content"]
    assert content[0]["type"] == "input_text"
    assert content[1]["type"] == "input_image"
    assert content[1]["image_url"].startswith("data:image/png;base64,")
    assert "thinking" not in body and "temperature" not in body
    assert result["text"] == TEXT and result["request_id"] == "req-test"
    assert result["api_protocol"] == "responses"


@pytest.mark.parametrize("image", ["https://images.example/image.png", "data:image/png;base64,aW1hZ2U="])
def test_responses_image_url_and_data_url_are_preserved(image):
    http = HTTP()
    annotate(provider(http), image_bytes=b"", image_url=image)
    assert http.calls[0][1]["json"]["input"][0]["content"][1]["image_url"] == image


def test_chat_old_configuration_keeps_messages_and_schema_contract():
    http = HTTP(Reply(payload={"choices": [{"message": {"content": TEXT}, "finish_reason": "stop"}]}))
    result = annotate(provider(http, base_url="https://host/api/v3"))
    body = http.calls[0][1]["json"]
    assert body["messages"][0]["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert body["response_format"]["type"] == "json_schema"
    assert "input" not in body and result["text"] == TEXT


@pytest.mark.parametrize("status,code", [(400,"MODEL_BAD_REQUEST"),(401,"MODEL_AUTHENTICATION_FAILED"),(403,"MODEL_PERMISSION_DENIED"),(404,"MODEL_RESOURCE_NOT_FOUND"),(429,"MODEL_RATE_LIMITED"),(500,"MODEL_SERVICE_ERROR")])
def test_http_errors_are_classified_without_blind_retry(status, code):
    http = HTTP(Reply(status, {"error": {"code": "upstream.resource", "message": "do not echo sensitive body"}}))
    with pytest.raises(ProviderRequestError) as caught:
        annotate(provider(http))
    assert caught.value.code == code
    assert caught.value.status_code == status
    assert caught.value.server_error_code == "upstream.resource"
    assert caught.value.request_id == "req-test"
    assert "req-test" in str(caught.value) and "upstream.resource" in str(caught.value)
    assert len(http.calls) == 1


def test_only_explicitly_unsupported_format_can_fall_back_to_prompt():
    http = HTTP(Reply(400, {"error": {"param": "text.format.type", "code": "UnsupportedParameter", "message": "json_schema not supported"}}), Reply(400, {"error": {"param": "text.format", "message": "json_object unsupported"}}), Reply())
    assert annotate(provider(http))["text"] == TEXT
    bodies = [c[1]["json"] for c in http.calls]
    assert [b.get("text", {}).get("format", {}).get("type") for b in bodies] == ["json_schema", "json_object", None]
    assert "boxes" in bodies[-1]["input"][0]["content"][0]["text"]
    assert len({c[0] for c in http.calls}) == 1
    assert len({b["input"][0]["content"][1]["image_url"] for b in bodies}) == 1


@pytest.mark.parametrize("error", [
    {"param": "model", "message": "model unsupported; text.format=json_schema"},
    {"param": "text.format.schema", "message": "invalid schema"},
    {"message": "insufficient balance"},
])
def test_bad_model_or_invalid_schema_is_not_a_capability_fallback(error):
    http = HTTP(Reply(400, {"error": error}))
    with pytest.raises(ProviderRequestError):
        annotate(provider(http))
    assert len(http.calls) == 1


@pytest.mark.parametrize("payload,code", [
    (output(status="incomplete"), "MODEL_OUTPUT_INCOMPLETE"),
    (output(status="failed"), "MODEL_OUTPUT_FAILED"),
    ({"status":"completed","output":[{"type":"reasoning","summary":[{"text":TEXT}]}]}, "MODEL_OUTPUT_PARSE_ERROR"),
    (output(""), "MODEL_OUTPUT_PARSE_ERROR"),
    ({"status":"completed","output":[{"type":"message","role":"assistant","content":[{"type":"refusal","refusal":"hidden"}]}]}, "MODEL_OUTPUT_REFUSED"),
    (ValueError("not JSON"), "MODEL_OUTPUT_PARSE_ERROR"),
])
def test_non_final_or_non_text_outputs_cannot_be_annotations(payload, code):
    with pytest.raises(ProviderRequestError) as caught:
        annotate(provider(HTTP(Reply(payload=payload))))
    assert caught.value.code == code


def test_timeout_has_its_own_error_and_does_not_retry():
    http = HTTP(requests.Timeout("sensitive network exception"))
    with pytest.raises(ProviderRequestError) as caught:
        annotate(provider(http))
    assert caught.value.code == "MODEL_REQUEST_TIMEOUT"
    assert "sensitive" not in str(caught.value) and len(http.calls) == 1


def test_error_metadata_never_echoes_api_key_or_image():
    secret = "sk-test-private-only"
    encoded = base64.b64encode(b"image").decode()
    http = HTTP(Reply(404, {"error":{"code":secret,"message":secret+encoded}}, headers={"x-request-id":encoded}))
    with pytest.raises(ProviderRequestError) as caught:
        annotate(provider(http, api_key=secret))
    public = str(caught.value) + caught.value.server_error_code + caught.value.request_id
    assert secret not in public and encoded not in public


def test_successful_http_does_not_bypass_existing_candidate_validation():
    text = '{"boxes":[{"label":"unexpected","confidence":1,"x1":0,"y1":0,"x2":1,"y2":1}]}'
    result = annotate(provider(HTTP(Reply(payload=output(text)))))
    with pytest.raises(ValueError, match="标签库"):
        parse_candidate_response(result["text"], width=128, height=128, label_ids={"fire":0})


@pytest.mark.parametrize("payload", [
    {"boxes":[],"image":"data:image/png;base64,cHJpdmF0ZS1pbWFnZS1kYXRh"},
    {"boxes":[{"label":"cHJpdmF0ZS1pbWFnZS1kYXRh","confidence":1,"x1":0,"y1":0,"x2":1,"y2":1}]},
])
def test_invalid_annotation_errors_do_not_echo_model_payload(payload):
    import json
    with pytest.raises(ValueError) as caught:
        parse_candidate_response(json.dumps(payload),width=128,height=128,label_ids={"fire":0})
    import traceback
    assert "cHJpdmF0ZS1pbWFnZS1kYXRh" not in str(caught.value)
    assert "cHJpdmF0ZS1pbWFnZS1kYXRh" not in "".join(traceback.format_exception(caught.value))


@pytest.mark.parametrize("mode", ["json_schema","json_object"])
def test_explicit_format_is_not_silently_changed(mode):
    http = HTTP(Reply(400,{"error":{"param":"text.format.type","message":mode+" unsupported"}}))
    with pytest.raises(ProviderRequestError):
        annotate(provider(http,structured_output=mode))
    assert len(http.calls) == 1


def test_explicit_prompt_mode_does_not_send_structured_parameters():
    http = HTTP()
    annotate(provider(http,structured_output="prompt"))
    assert "text" not in http.calls[0][1]["json"] and len(http.calls) == 1


def test_explicit_plain_text_unsupported_format_can_fall_back():
    rejected = Reply(400, ValueError("plain response"))
    rejected.text = "json_schema is not supported"
    http = HTTP(rejected, Reply())
    assert annotate(provider(http))["text"] == TEXT
    assert len(http.calls) == 2


def test_model_error_code_is_not_retried_even_if_model_name_contains_schema():
    http = HTTP(Reply(400,{"error":{"code":"UnsupportedModel","message":"The model json_schema-vision is not supported"}}))
    with pytest.raises(ProviderRequestError):
        annotate(provider(http))
    assert len(http.calls) == 1


def test_flat_gateway_error_keeps_original_code_and_request_id():
    http = HTTP(Reply(404,{"code":"Gateway.ModelMissing","message":"not echoed","request_id":"req-flat"},headers={"content-type":"application/json"}))
    with pytest.raises(ProviderRequestError) as caught:
        annotate(provider(http))
    assert caught.value.server_error_code == "Gateway.ModelMissing"
    assert caught.value.request_id == "req-flat"
