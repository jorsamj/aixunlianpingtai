"""Worker-safe AI configuration and prompt services (no Web application imports)."""
from __future__ import annotations

import json
import math
import os
import re
from pathlib import Path

from .auto_label import provider_factory
from .prompts import render_prompt, version_template
from .secrets import KeyringSecretStore


def _read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def label_catalog(project):
    metadata = {str(item.get("code")): item for item in project.get("label_meta", []) if isinstance(item, dict)}
    result = []
    for index, item in enumerate(project.get("labels", [])):
        code = str((item.get("code") if isinstance(item, dict) else item) or "").strip().replace(" ", "_")
        meta = item if isinstance(item, dict) else metadata.get(code, {})
        if code and str(meta.get("status") or "active") == "active":
            result.append({"code": code, "class_id": index,
                           "display_name_zh": str(meta.get("display_name_zh") or meta.get("display_name") or code)})
    return result


def build_annotation_prompt(cfg, labels, *, width, height, business_instruction, template=""):
    template = (template or cfg.get("annotation_prompt_template") or "").strip()
    if not template:
        template = ("你是视觉目标检测标注助手。只标注标签库中的目标：{{labels_json}}。"
                    "图片尺寸为 {{image_width}}x{{image_height}}。{{business_instruction}}"
                    "必须只返回符合此结构的 JSON，不要输出解释或 Markdown：{{output_schema}}")
    if "{{" in template:
        return render_prompt(template, labels=labels, width=width, height=height,
                             business_instruction=business_instruction)
    return template.replace("{labels}", "、".join(str(item.get("code")) for item in labels))


def prepare_request(data_dir, project_id, request, *, runtime=True):
    """Freeze public configuration at submit; resolve credentials once at execution."""
    data_dir = Path(data_dir)
    project = _read(data_dir / "projects" / project_id / "meta.json", None)
    if not isinstance(project, dict):
        raise ValueError("AI_PROJECT_NOT_FOUND: annotation project metadata is missing")
    allowed = {"labels", "labels_text", "reference_image_ids", "threshold", "overwrite", "task_name",
               "provider_id", "model_config_id", "prompt_template_id", "business_instruction", "preview_count",
               "prompt_template_snapshot", "prompt_template_version_id", "image_ids", "schema_version"}
    prepared = {key: value for key, value in request.items() if key in allowed}
    if not runtime:
        prepared.pop("prompt_template_snapshot", None)
    labels = prepared.get("labels") or re.split(r"[、,，;；\n\t]+", str(prepared.get("labels_text") or ""))
    labels = list(dict.fromkeys(str(label).strip().replace(" ", "_") for label in labels if str(label).strip()))
    references = prepared.get("reference_image_ids") or []
    if len(references) > 500:
        raise ValueError("AI_REFERENCE_LIMIT: at most 500 reference images are allowed")
    if references and not runtime:
        from .annotation_repository import AnnotationRepository
        annotations = AnnotationRepository(data_dir / "projects" / project_id)
        for image_id in references:
            for box in annotations.get(image_id).get("boxes") or []:
                label = str(box.get("label") or "").strip().replace(" ", "_")
                if label and label not in labels:
                    labels.append(label)
    if not labels:
        raise ValueError("AI_LABELS_REQUIRED: select annotation labels")
    catalog = [item for item in label_catalog(project) if item["code"] in labels]
    if set(labels) != {item["code"] for item in catalog}:
        raise ValueError("AI_LABEL_UNAVAILABLE: task labels are unavailable or inactive")
    threshold = float(prepared.get("threshold", 0.45))
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("AI_THRESHOLD_INVALID: threshold must be between 0 and 1")
    configs = _read(data_dir / "model_configs.json", [])
    selected_id = str(prepared.get("model_config_id") or prepared.get("provider_id") or "")
    config = next((item for item in configs if str(item.get("id")) == selected_id), None) if selected_id else next(
        (item for item in configs if item.get("default_for_annotation")), configs[0] if configs else None)
    if not config:
        raise ValueError("AI_MODEL_CONFIG_NOT_FOUND: configure an available annotation model")
    if not str(config.get("model_name") or "").strip():
        raise ValueError("AI_MODEL_NAME_MISSING: annotation model name is empty")
    template = prepared.get("prompt_template_snapshot")
    template_id = str(prepared.get("prompt_template_id") or "")
    if not isinstance(template, dict):
        template = {}
        if template_id and template_id != "default":
            template = next((item for item in _read(data_dir / "prompt_library.json", []) if item.get("id") == template_id), None)
            if not template:
                raise ValueError("AI_PROMPT_NOT_FOUND: prompt template does not exist")
            if not template.get("version_id"):
                template = version_template(template, template_id=template_id,
                    now=str(template.get("updated_at") or template.get("created_at") or ""))
    prepared.update({"labels": labels, "threshold": threshold, "model_config_id": config["id"],
                     "prompt_template_snapshot": template,
                     "prompt_template_version_id": template.get("version_id") or ""})
    if not runtime:
        return prepared
    runtime_config = dict(config)
    reference = str(config.get("secret_ref") or "")
    secret = (os.environ.get(reference[4:]) if reference.startswith("env:") else KeyringSecretStore().get(reference)) if reference else config.get("api_key", "")
    if reference and not secret:
        raise ValueError("AI_MODEL_SECRET_UNAVAILABLE: model credential is unavailable to this Worker")
    runtime_config["_api_key"] = secret or ""
    runtime_config["headers_json"] = {str(k): v for k, v in (config.get("headers_json") or {}).items()
                                      if str(k).lower() not in {"authorization", "x-api-key", "api-key", "apikey"}}
    public_config = {k: v for k, v in runtime_config.items() if k not in {"_api_key", "api_key", "secret_ref"}}
    prepared.update({"_provider": provider_factory(runtime_config), "_provider_config": public_config,
                     "label_catalog": catalog, "label_ids": {item["code"]: item["class_id"] for item in catalog},
                     "label_aliases": {item["code"]: [item["display_name_zh"]] for item in catalog},
                     "prompt_template": str(template.get("prompt") or "")})
    return prepared
