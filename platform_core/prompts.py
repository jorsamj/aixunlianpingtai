import hashlib
import json
import re
from typing import Any, Mapping, Sequence


ALLOWED_VARIABLES = {
    "labels_json",
    "image_width",
    "image_height",
    "business_instruction",
    "output_schema",
}
VARIABLE_PATTERN = re.compile(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}")

BOX_OUTPUT_SCHEMA = {
    "boxes": [
        {
            "label": "标签库中的英文 code",
            "confidence": 0.0,
            "x1": 0,
            "y1": 0,
            "x2": 0,
            "y2": 0,
        }
    ]
}


def template_version_id(content: str) -> str:
    return hashlib.sha256(str(content).encode("utf-8")).hexdigest()


def render_prompt(
    template: str,
    *,
    labels: Sequence[Mapping[str, Any]],
    width: int,
    height: int,
    business_instruction: str,
) -> str:
    variables = set(VARIABLE_PATTERN.findall(str(template or "")))
    unknown = sorted(variables - ALLOWED_VARIABLES)
    if unknown:
        raise ValueError("未知模板变量：" + "、".join(unknown))
    normalized_labels = [
        {
            "code": str(item.get("code") or ""),
            "display_name_zh": str(item.get("display_name_zh") or item.get("display_name") or ""),
        }
        for item in labels
        if str(item.get("code") or "").strip()
    ]
    values = {
        "labels_json": json.dumps(normalized_labels, ensure_ascii=False, indent=2),
        "image_width": str(int(width)),
        "image_height": str(int(height)),
        "business_instruction": str(business_instruction or ""),
        "output_schema": json.dumps(BOX_OUTPUT_SCHEMA, ensure_ascii=False, indent=2),
    }
    return VARIABLE_PATTERN.sub(lambda match: values[match.group(1)], str(template or ""))


def template_content_hash(data: Mapping[str, Any]) -> str:
    canonical = {
        key: data.get(key)
        for key in ("name", "framework", "task_type", "labels", "prompt", "output_schema", "model_config_id", "threshold", "save_format", "overwrite", "remark")
    }
    return template_version_id(json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def version_template(data: Mapping[str, Any], *, template_id: str, now: str, previous: Mapping[str, Any] | None = None) -> dict:
    record = dict(data)
    record["id"] = template_id
    version_id = template_content_hash(record)
    previous_version = str((previous or {}).get("version_id") or "")
    history = list((previous or {}).get("history") or [])
    version_number = int((previous or {}).get("version") or 0)
    if previous and previous_version and previous_version != version_id:
        history.append({
            "version": version_number,
            "version_id": previous_version,
            "prompt": previous.get("prompt") or "",
            "updated_at": previous.get("updated_at") or previous.get("created_at") or "",
        })
    if not previous or previous_version != version_id:
        version_number += 1
    record.update({
        "version": max(1, version_number),
        "version_id": version_id,
        "history": history[-50:],
        "created_at": (previous or {}).get("created_at") or record.get("created_at") or now,
        "updated_at": now,
    })
    return record
