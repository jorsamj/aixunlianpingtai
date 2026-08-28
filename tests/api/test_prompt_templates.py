import uuid


def _payload(name: str, prompt: str) -> dict:
    return {
        "name": name,
        "framework": "ultralytics",
        "task_type": "目标检测",
        "labels": ["fire"],
        "prompt": prompt,
        "output_schema": "bbox_json",
        "threshold": 0.5,
        "save_format": "yolo",
    }


def test_prompt_template_versions_preview_and_rejects_unknown_variables(client):
    name = f"prompt-{uuid.uuid4().hex[:8]}"
    created = client.post(
        "/api/v35/prompt-templates",
        json=_payload(name, "检测 {{labels_json}}，尺寸 {{image_width}}x{{image_height}}。{{output_schema}}"),
    )
    assert created.status_code == 200, created.text
    first = created.json()
    assert first["version"] == 1
    assert len(first["version_id"]) == 64

    preview = client.post(
        "/api/v35/prompt-templates/preview",
        json={
            "prompt": first["prompt"],
            "labels": [{"code": "fire", "display_name_zh": "明火"}],
            "image_width": 1280,
            "image_height": 720,
            "business_instruction": "只标可见火焰",
        },
    )
    assert preview.status_code == 200, preview.text
    assert '"code": "fire"' in preview.json()["rendered_prompt"]
    assert "1280x720" in preview.json()["rendered_prompt"]
    assert '"boxes"' in preview.json()["rendered_prompt"]

    updated = client.put(
        f"/api/v35/prompt-templates/{first['id']}",
        json=_payload(name, "新版：{{business_instruction}} {{labels_json}} {{output_schema}}"),
    )
    assert updated.status_code == 200, updated.text
    second = updated.json()
    assert second["version"] == 2
    assert second["version_id"] != first["version_id"]
    assert second["history"][-1]["version_id"] == first["version_id"]

    rejected = client.post(
        "/api/v35/prompt-templates",
        json=_payload(name + "-bad", "不要泄露 {{api_key}}"),
    )
    assert rejected.status_code == 400
    assert "未知模板变量" in rejected.text
