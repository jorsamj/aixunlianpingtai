"""Retry policy evidence is transport metadata, never response-body text."""
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from io import BytesIO
from PIL import Image

import pytest

from platform_core.providers.base import ProviderRequestError, http_error, response_metadata, retry_after
from platform_core.providers.ollama_vision import OllamaVisionProvider
from platform_core.providers.wevisone_vision import WeVisOneVisionProvider
from tests.unit.test_openai_vision_protocol import HTTP, Reply, annotate, output, provider


def test_provider_specific_quota_codes_do_not_confuse_tpm_with_billing():
    response = Reply(429)
    assert http_error(response, {'server_error_code':'insufficient_quota'})['retryable'] is False
    aliyun = http_error(response, {'server_error_code':'insufficient_quota'}, provider='aliyun_qwen')
    assert aliyun['code'] == 'MODEL_RATE_LIMITED' and aliyun['retryable'] is True
    for code in ['Throttling.AllocationQuota', 'ModelAccountTpmRateLimitExceeded']:
        assert http_error(response, {'server_error_code':code})['retryable'] is True
    billing = http_error(Reply(403), {'server_error_code':'AllocationQuota.FreeTierOnly'}, provider='aliyun_qwen')
    assert billing['code'] == 'MODEL_QUOTA_EXCEEDED' and billing['retryable'] is False


@pytest.mark.parametrize('payload', [ValueError('untrusted body'), ['not-an-object']])
def test_malformed_200_keeps_http_and_request_evidence_for_native_adapters(payload):
    image = BytesIO()
    Image.new('RGB', (8,8)).save(image, 'PNG')
    reply = Reply(200, payload, {'X-Request-ID':'parse-trace','X-Backend-Instance-ID':'actual-instance'})
    clients = [OllamaVisionProvider(model='vision', session=HTTP(reply)),
               WeVisOneVisionProvider(base_url='http://loopback.invalid/v1', model='vision', session=HTTP(reply))]
    for client in clients:
        kwargs = {'image_bytes':image.getvalue(), 'prompt':'', 'output_schema':{}}
        if isinstance(client, WeVisOneVisionProvider):
            kwargs['labels'] = ['fire']
        with pytest.raises(ProviderRequestError) as caught:
            client.annotate(**kwargs)
        assert caught.value.code == 'MODEL_OUTPUT_PARSE_ERROR'
        assert caught.value.status_code == 200
        assert caught.value.request_id == 'parse-trace'
        assert caught.value.backend_instance_id == 'actual-instance'
        assert caught.value.retryable is False
        assert 'untrusted body' not in str(caught.value)


@pytest.mark.parametrize("status,code,retryable", [(400,"MODEL_REQUEST_CONTRACT_INVALID",False),(422,"MODEL_REQUEST_CONTRACT_INVALID",False),(401,"MODEL_AUTHENTICATION_FAILED",False),(403,"MODEL_PERMISSION_DENIED",False),(429,"MODEL_RATE_LIMITED",True),(500,"MODEL_SERVICE_ERROR",True),(502,"MODEL_SERVICE_ERROR",True),(503,"MODEL_SERVICE_ERROR",True)])
def test_policy_is_identical_for_all_adapters(status, code, retryable):
    image = BytesIO()
    Image.new("RGB", (128,128), "white").save(image, "PNG")
    response = Reply(status, {"error": {"code": "upstream_code"}}, {"Retry-After": "3", "X-Request-ID": "trace-7"})
    http = HTTP(response)
    clients = [provider(http), OllamaVisionProvider(model="vision", session=http), WeVisOneVisionProvider(base_url="http://localhost:18000", model="wevisone-vl-2b", session=http)]
    for client in clients:
        http.replies = [response]
        with pytest.raises(ProviderRequestError) as caught:
            if isinstance(client, WeVisOneVisionProvider):
                client._request("detect", image_bytes=image.getvalue(), labels=["person"])
            else:
                client.annotate(image_bytes=b"image", prompt="detect", output_schema={})
        error = caught.value
        assert (error.code,error.retryable,error.retry_after_seconds,error.request_id) == (code,retryable,3,"trace-7")
    assert len(http.calls) == 3


@pytest.mark.parametrize("upstream", ["insufficient_quota", "billing_hard_limit_reached", "quota_exceeded", "insufficient_balance"])
def test_quota_is_not_retried(upstream):
    response = Reply(429, {"error": {"code":upstream}})
    policy = http_error(response,response_metadata(response,response.payload))
    assert policy["code"] == "MODEL_QUOTA_EXCEEDED"
    assert policy["retryable"] is False


@pytest.mark.parametrize("value", ["", "-1", "NaN", "Infinity", "86401", "1e100", "bad-date"])
def test_invalid_or_unbounded_retry_after_ignored(value):
    assert retry_after(Reply(headers={"Retry-After":value})) is None


def test_retry_after_http_date_and_trace_are_bounded():
    value = format_datetime(datetime.now(timezone.utc)+timedelta(seconds=30))
    assert 28 <= retry_after(Reply(headers={"Retry-After":value})) <= 30
    response = Reply(headers={"X-Request-ID":"data:image/png;base64,secret", "X-Backend-Instance-ID":"secret"})
    metadata = response_metadata(response,{"model":"secret"},sensitive=("secret",))
    assert metadata["request_id"] == metadata["backend_instance_id"] == metadata["actual_model"] == ""


def test_upstream_identity_is_optional_and_preserved_without_guessing():
    http = HTTP(Reply(payload=output(model="actual-v2",backend_instance_id="instance-b")))
    result = annotate(provider(http))
    assert result["actual_model"] == "actual-v2"
    assert result["backend_instance_id"] == "instance-b"
    result = annotate(provider())
    assert result["actual_model"] == result["backend_instance_id"] == ""



def test_long_valid_retry_after_is_preserved():
    assert retry_after(Reply(headers={"Retry-After":"3600"})) == 3600


def test_long_retry_after_prevents_retry_inside_short_task_budget(tmp_path, monkeypatch):
    from tests.unit.test_annotation_inference_execution import setup_context
    from platform_core.annotation_task_service import run_ai_annotation
    context, store = setup_context(tmp_path, monkeypatch, concurrency=1, count=1, max_attempts=3)
    http = HTTP(Reply(429, {"error":{"code":"rate_limit_exceeded"}}, {"Retry-After":"3600"}))
    client = provider(http)
    run_ai_annotation(context, annotate=lambda _request,_image: annotate(client))
    assert len(http.calls) == 1
    assert store.get("0")["error_code"] == "MODEL_RATE_LIMITED"
