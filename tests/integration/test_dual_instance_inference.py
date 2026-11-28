"""Loopback simulation only: validates scheduling, never GPU performance."""
import json
import threading
import time
from contextlib import ExitStack, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import requests
from PIL import Image

from platform_core.annotation_task_service import annotate_one, run_ai_annotation
from platform_core.providers.wevisone_vision import WeVisOneVisionProvider
from platform_core.task_runtime import TaskStatus
from tests.unit.test_annotation_inference_execution import setup_context


@contextmanager
def serve(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.parametrize("capacity", [1, 2])
def test_real_native_servers_overlap_only_with_attested_capacity(tmp_path, monkeypatch, capacity, capsys):
    lock = threading.Lock()
    barrier = threading.Barrier(2) if capacity == 2 else None
    state = {"active":0, "maximum":0, "dispatch":0, "requests":[], "instances":set()}
    model = "wevisone-vl-2b-revision-frozen"
    def backend(instance):
        class Backend(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                assert self.path == "/v1/vision/detect"
                assert set(body) == {"image", "query"}
                assert body["image"].startswith("data:image/")
                assert body["query"] == ["fire"]
                with lock:
                    state["active"] += 1
                    state["maximum"] = max(state["maximum"], state["active"])
                    state["requests"].append(body["query"])
                    state["instances"].add(instance)
                try:
                    if barrier:
                        barrier.wait(timeout=5)
                    time.sleep(.03)
                    payload = json.dumps({"coordinate_system":"xyxy_pixel", "boxes":[],
                        "model":model,"backend_instance_id":instance}).encode()
                    self.send_response(200)
                    self.send_header("Content-Length",str(len(payload)))
                    self.send_header("X-Request-ID", instance + "-request")
                    self.end_headers()
                    self.wfile.write(payload)
                finally:
                    with lock:
                        state["active"] -= 1
        return Backend
    with ExitStack() as stack:
        urls = [stack.enter_context(serve(backend("stand-in-a"))), stack.enter_context(serve(backend("stand-in-b")))]
        class Gateway(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass
            def do_POST(self):
                body = self.rfile.read(int(self.headers["Content-Length"]))
                with lock:
                    target = urls[state["dispatch"] % 2]
                    state["dispatch"] += 1
                response = requests.post(target+self.path, data=body, headers={"Content-Type":"application/json"},timeout=10)
                self.send_response(response.status_code)
                self.send_header("Content-Length",str(len(response.content)))
                self.send_header("X-Request-ID",response.headers["X-Request-ID"])
                self.end_headers()
                self.wfile.write(response.content)
        gateway = stack.enter_context(serve(Gateway))
        context, store = setup_context(tmp_path, monkeypatch, concurrency=capacity,count=4)
        image = tmp_path / "source.png"
        Image.new("RGB",(1280,960),"white").save(image)
        monkeypatch.setattr("platform_core.annotation_task_service.load_task_images",lambda *_: [
            {"id":str(i),"path":str(image),"width":1280,"height":960,"source_content_sha256":"a"*64} for i in range(4)])
        provider = WeVisOneVisionProvider(base_url=gateway,model=model,timeout=10)
        config = {"id":"frozen-config","provider_adapter":"wevisone_vl","model_name":model,
                  "coordinate_space":"pixel","coordinate_order":"xyxy"}
        monkeypatch.setattr("platform_core.annotation_task_service._prepare_runtime_request",lambda _project,request,**_kw: {
            **request,"_provider":provider,"_provider_config":config,"label_ids":{"fire":0},
            "label_catalog":[{"code":"fire","class_id":0}],"label_aliases":{}})
        outcome = run_ai_annotation(context,annotate=annotate_one)
        assert outcome.status is TaskStatus.AWAITING_CONFIRMATION
        assert state["maximum"] == capacity
        assert state["instances"] == {"stand-in-a","stand-in-b"}
        assert state["requests"] == [["fire"]]*4
        assert store.statistics()["empty"] == 4
        assert store.statistics()["gt_committed"] == 0
        assert all(row["request_id"].startswith("stand-in-") for row in store.iter_items())

        generation = context.artifacts.read_json("task","generation.json")
        metrics = generation["execution"]
        assert metrics["concurrency"] == capacity
        assert metrics["processed_this_execution"] == 4
        assert metrics["mean_ms"] >= 0 and metrics["p50_ms"] >= 0 and metrics["p95_ms"] >= metrics["p50_ms"]
        from tools.probe_inference_capacity import main
        assert main(["--base-url",gateway,"--image",str(image),"--model",model,"--labels","fire",
                     "--workers",str(capacity),"--repeat","2"]) == 0
        report = json.loads(capsys.readouterr().out)
        probe = report["gateway"]
        assert probe["success"] == probe["empty"] == 2
        assert probe["failure"] == probe["retries"] == 0
        assert probe["observed_backend_instance_ids"] == ["stand-in-a","stand-in-b"]
        assert probe["observed_model_ids"] == [model]
        assert all(row["model_matches_expected"] for row in probe["results"])
        assert probe["gpu_participation"] == "NOT VERIFIED"
        assert probe["requests_per_minute"] > 0 and probe["wall_seconds"] > 0
        assert report["gt_written"] is report["capacity_manifest_written"] is False
        assert "data:image" not in json.dumps(report)


def test_probe_cli_credential_is_env_only_and_missing_identity_stays_unknown(tmp_path, monkeypatch, capsys):
    import tools.probe_inference_capacity as tool
    from platform_core.providers.base import ProviderRequestError
    calls = []
    class Provider:
        def __init__(self, **kwargs):
            calls.append(kwargs)
        def annotate(self, **kwargs):
            assert set(kwargs) == {"image_bytes","prompt","output_schema","labels"}
            if len(calls) == 1:
                return {"text":'{"boxes":[]}',"status_code":200}
            raise ProviderRequestError("do not echo sk-test-secret or data:image/png;base64,secret",code="MODEL_SERVICE_ERROR",status_code=503)
    monkeypatch.setattr(tool,"WeVisOneVisionProvider",Provider)
    monkeypatch.setenv("EXPLICIT_PROBE_KEY","sk-test-secret")
    image = tmp_path / "probe.png"
    Image.new("RGB",(16,16)).save(image)
    argv = ["--base-url","http://127.0.0.1:1","--direct-base-url","http://127.0.0.1:2",
            "--image",str(image),"--model","frozen","--labels","fire","--repeat","1","--api-key-env","EXPLICIT_PROBE_KEY"]
    assert tool.main(argv) == 1
    output = capsys.readouterr().out
    assert "sk-test-secret" not in output and "base64" not in output
    report = json.loads(output)
    assert report["direct"][0]["instance_identity_status"] == "unknown"
    assert report["gateway"]["failure"] == 1
    assert report["gateway"]["results"][0]["http_status"] == 503
    assert all(call["api_key"] == "sk-test-secret" for call in calls)
