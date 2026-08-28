import socket
import threading
import time

import pytest
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from platform_core.auto_label import CANDIDATE_OUTPUT_SCHEMA
from platform_core.secrets import MemorySecretStore


@pytest.fixture(scope="module")
def fake_vision_server():
    api = FastAPI()
    state = {"requests": [], "reject_token": "", "reject_schema_once": False}

    @api.post("/v1/chat/completions")
    async def chat(request: Request):
        body = await request.json()
        authorization = request.headers.get("authorization", "")
        state["requests"].append({"authorization": authorization, "body": body})
        if state["reject_token"] and state["reject_token"] in authorization:
            return JSONResponse(status_code=401, content={"detail": f"rejected {state['reject_token']}"})
        if state["reject_schema_once"] and body.get("response_format", {}).get("type") == "json_schema":
            state["reject_schema_once"] = False
            return JSONResponse(status_code=400, content={"detail": "json_schema unsupported"})
        return JSONResponse(
            headers={"x-request-id": "fake-request-header"},
            content={
                "id": "fake-response-id",
                "choices": [{
                    "message": {
                        "content": '{"boxes":[{"label":"fire","confidence":0.95,"x1":10,"y1":10,"x2":80,"y2":80}]}'
                    }
                }],
            },
        )

    @api.post("/api/chat")
    async def ollama_chat(request: Request):
        body = await request.json()
        state["requests"].append({"ollama": True, "body": body})
        return {
            "message": {
                "content": '{"boxes":[{"label":"fire","confidence":0.91,"x1":2,"y1":3,"x2":40,"y2":50}]}'
            },
            "total_duration": 1000,
        }

    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(api, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.01)
    assert server.started
    yield f"http://127.0.0.1:{port}/v1", state
    server.should_exit = True
    thread.join(timeout=5)


def test_openai_compatible_provider_sends_bearer_image_prompt_and_schema(fake_vision_server):
    from platform_core.providers.openai_vision import OpenAICompatibleVisionProvider

    base_url, state = fake_vision_server
    state["requests"].clear()
    provider = OpenAICompatibleVisionProvider(
        provider="volcengine_ark",
        base_url=base_url,
        api_key="sk-private-token",
        model="vision-endpoint",
    )
    result = provider.annotate(
        image_bytes=b"fake-jpeg",
        prompt="find fire",
        output_schema=CANDIDATE_OUTPUT_SCHEMA,
    )

    request = state["requests"][-1]
    assert request["authorization"] == "Bearer sk-private-token"
    assert request["body"]["model"] == "vision-endpoint"
    assert request["body"]["response_format"]["type"] == "json_schema"
    content = request["body"]["messages"][0]["content"]
    assert content[0] == {"type": "text", "text": "find fire"}
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert '"boxes"' in result["text"]
    assert result["request_id"] == "fake-request-header"
    assert result["provider"] == "volcengine_ark"


def test_openai_provider_errors_do_not_leak_token(fake_vision_server):
    from platform_core.providers.openai_vision import OpenAICompatibleVisionProvider, ProviderRequestError

    base_url, state = fake_vision_server
    token = "sk-reject-me"
    state["reject_token"] = token
    provider = OpenAICompatibleVisionProvider(
        provider="aliyun_qwen",
        base_url=base_url,
        api_key=token,
        model="qwen-vl",
    )
    with pytest.raises(ProviderRequestError) as captured:
        provider.annotate(image_bytes=b"image", prompt="prompt", output_schema=CANDIDATE_OUTPUT_SCHEMA)
    state["reject_token"] = ""
    assert token not in str(captured.value)


def test_openai_provider_falls_back_to_json_object(fake_vision_server):
    from platform_core.providers.openai_vision import OpenAICompatibleVisionProvider

    base_url, state = fake_vision_server
    state["requests"].clear()
    state["reject_schema_once"] = True
    provider = OpenAICompatibleVisionProvider(
        provider="local_openai",
        base_url=base_url,
        model="local-vlm",
    )
    provider.annotate(image_bytes=b"image", prompt="prompt", output_schema=CANDIDATE_OUTPUT_SCHEMA)
    assert [item["body"]["response_format"]["type"] for item in state["requests"]] == [
        "json_schema",
        "json_object",
    ]


def test_saved_model_connection_test_parses_candidates(client, monkeypatch, fake_vision_server):
    import app as app_module

    base_url, _state = fake_vision_server
    monkeypatch.setattr(app_module, "MODEL_SECRET_STORE", MemorySecretStore())
    created = client.post("/api/v35/model-configs", json={
        "name": "fake volc vision",
        "provider_type": "volcengine_ark",
        "model_kind": "vlm",
        "base_url": base_url,
        "detect_url": base_url,
        "model_name": "vision-endpoint",
        "api_key": "sk-test-only",
    })
    assert created.status_code == 200, created.text

    tested = client.post(f"/api/v35/model-configs/{created.json()['id']}/test-annotation")
    assert tested.status_code == 200, tested.text
    result = tested.json()
    assert result["reachable"] is True
    assert result["provider"] == "volcengine_ark"
    assert result["model"] == "vision-endpoint"
    assert result["latency_ms"] >= 0
    assert result["parsed_boxes"][0]["label"] == "fire"
    assert "boxes" in result["raw_preview"]


def test_ollama_provider_sends_images_schema_and_non_streaming(fake_vision_server):
    from platform_core.providers.ollama_vision import OllamaVisionProvider

    base_url, state = fake_vision_server
    ollama_base = base_url.removesuffix("/v1")
    state["requests"].clear()
    provider = OllamaVisionProvider(base_url=ollama_base, model="qwen2.5vl:7b")
    result = provider.annotate(
        image_bytes=b"local-image",
        prompt="find fire",
        output_schema=CANDIDATE_OUTPUT_SCHEMA,
    )
    body = state["requests"][-1]["body"]
    assert body["model"] == "qwen2.5vl:7b"
    assert body["stream"] is False
    assert body["format"] == CANDIDATE_OUTPUT_SCHEMA
    assert body["messages"][0]["content"] == "find fire"
    assert body["messages"][0]["images"]
    assert result["provider"] == "ollama"
    assert '"boxes"' in result["text"]


def test_ollama_unreachable_error_is_actionable():
    from platform_core.providers.base import ProviderRequestError
    from platform_core.providers.ollama_vision import OllamaVisionProvider

    provider = OllamaVisionProvider(base_url="http://127.0.0.1:1", model="local-vlm", timeout=0.2)
    with pytest.raises(ProviderRequestError) as captured:
        provider.annotate(image_bytes=b"image", prompt="prompt", output_schema=CANDIDATE_OUTPUT_SCHEMA)
    assert captured.value.code == "MODEL_SERVICE_UNREACHABLE"
    assert "地址" in captured.value.solution
    assert "模型" in captured.value.solution
