import time

import pytest


class FakeVisionProvider:
    def annotate(self, *, image_bytes, prompt, output_schema):
        assert image_bytes
        assert "fire" in prompt
        assert output_schema["required"] == ["boxes"]
        return {
            "text": '{"boxes":[{"label":"fire","confidence":0.95,"x1":10,"y1":10,"x2":80,"y2":80}]}',
            "request_id": "fake-request-1",
            "latency_ms": 12,
            "provider": "fake",
            "model": "fake-vlm",
        }


@pytest.fixture
def fake_provider(monkeypatch):
    monkeypatch.setattr(
        "platform_core.auto_label.provider_factory",
        lambda provider_id: FakeVisionProvider(),
    )
    return "fake-provider"


def wait_for_task(client, pid, task_id, expected, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v47/projects/{pid}/ai-label-tasks/{task_id}/result")
        response.raise_for_status()
        body = response.json()
        if body.get("task", {}).get("status") == expected:
            return body
        time.sleep(0.05)
    raise AssertionError(f"task {task_id} did not reach {expected}")


def test_auto_label_candidates_do_not_modify_annotation_until_confirmed(
    client, seeded_project, fake_provider
):
    pid, image = seeded_project
    before = client.get(f"/api/projects/{pid}/annotations/{image['id']}").json()
    assert before["boxes"] == []

    created = client.post(f"/api/v47/projects/{pid}/ai-label-tasks", json={
        "image_ids": [image["id"]],
        "labels_text": "fire",
        "provider_id": fake_provider,
        "prompt_template_id": "default",
        "preview_count": 1,
    })
    assert created.status_code == 200, created.text
    task = created.json()
    completed = wait_for_task(client, pid, task["id"], "awaiting_confirmation")

    untouched = client.get(f"/api/projects/{pid}/annotations/{image['id']}").json()
    assert untouched["boxes"] == []
    item = completed["result"]["items"][0]
    assert item["status"] == "success"
    assert item["boxes"][0]["label"] == "fire"
    assert item["request_id"] == "fake-request-1"
    assert len(item["raw_response_hash"]) == 64
    assert "raw_response" not in item

    confirmed = client.post(
        f"/api/v47/projects/{pid}/ai-label-tasks/{task['id']}/confirm",
        json={"image_ids": [image["id"]]},
    )
    assert confirmed.status_code == 200, confirmed.text
    annotation = client.get(f"/api/projects/{pid}/annotations/{image['id']}").json()
    assert annotation["boxes"][0]["source"] == "ai_candidate_confirmed"

    repeated = client.post(
        f"/api/v47/projects/{pid}/ai-label-tasks/{task['id']}/confirm",
        json={"image_ids": [image["id"]]},
    )
    assert repeated.status_code == 409
