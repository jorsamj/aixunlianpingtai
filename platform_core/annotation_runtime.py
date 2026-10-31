"""Worker-safe AI configuration and prompt services (no Web application imports)."""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

from .auto_label import provider_factory
from .prompts import render_prompt, template_version_id, version_template
from .secrets import KeyringSecretStore


_SECRET_FIELDS = frozenset({
    "_api_key",
    "api_key",
    "access_key",
    "access_key_id",
    "access_key_secret",
    "access_secret",
    "password",
    "secret",
    "token",
})
_SECRET_HEADER_NAMES = frozenset({
    "authorization",
    "x-api-key",
    "api-key",
    "apikey",
    "x-access-key",
    "x-access-token",
})
MAX_TASK_PROMPT_LENGTH = 12_000
DEFAULT_ANNOTATION_PROMPT = (
    "你是视觉目标检测标注助手。只标注标签库中的目标：{{labels_json}}。"
    "图片尺寸为 {{image_width}}x{{image_height}}。{{business_instruction}}"
    "必须只返回符合此结构的 JSON，不要输出解释或 Markdown：{{output_schema}}"
)


def _read(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else default


def _json_clone(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False))


def _clean_headers(value: Any) -> dict[str, Any]:
    return {
        str(key): item
        for key, item in (value or {}).items()
        if str(key).strip().lower() not in _SECRET_HEADER_NAMES
    } if isinstance(value, Mapping) else {}


def freeze_model_config(config: Mapping[str, Any]) -> tuple[dict[str, Any], str]:
    """Freeze one executable model configuration without persisting credentials.

    The secret *reference* is immutable task input; the secret value never enters
    request.json. Workers resolve that reference only when the task executes.
    """
    snapshot = _json_clone(dict(config))
    for key in _SECRET_FIELDS:
        snapshot.pop(key, None)
    snapshot["headers_json"] = _clean_headers(snapshot.get("headers_json"))
    config_id = str(snapshot.get("id") or "").strip()
    if not config_id:
        raise ValueError("AI_MODEL_CONFIG_ID_MISSING: annotation model configuration has no id")
    if not str(snapshot.get("model_name") or "").strip():
        raise ValueError("AI_MODEL_NAME_MISSING: annotation model name is empty")
    body = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    revision = hashlib.sha256(body.encode("utf-8")).hexdigest()
    return snapshot, revision


def _snapshot_revision(snapshot: Mapping[str, Any]) -> str:
    body = json.dumps(dict(snapshot), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def label_catalog(project):
    metadata = {
        str(item.get("code")): item
        for item in project.get("label_meta", [])
        if isinstance(item, dict)
    }
    result = []
    for index, item in enumerate(project.get("labels", [])):
        code = str((item.get("code") if isinstance(item, dict) else item) or "").strip()
        meta = item if isinstance(item, dict) else metadata.get(code, {})
        if code and str(meta.get("status") or "active") == "active":
            aliases = list(dict.fromkeys(
                str(value).strip()
                for value in (meta.get("aliases") or [])
                if str(value).strip()
            ))
            result.append({
                "code": code,
                "class_id": index,
                "display_name_zh": str(meta.get("display_name_zh") or meta.get("display_name") or code),
                "aliases": aliases,
            })
    return result


def build_annotation_prompt(cfg, labels, *, width, height, business_instruction, template=""):
    template = (template or cfg.get("annotation_prompt_template") or "").strip()
    if not template:
        template = DEFAULT_ANNOTATION_PROMPT
    if "{{" in template:
        return render_prompt(
            template,
            labels=labels,
            width=width,
            height=height,
            business_instruction=business_instruction,
        )
    return template.replace("{labels}", "、".join(str(item.get("code")) for item in labels))


def prepare_request(
    data_dir,
    project_id,
    request,
    *,
    runtime=True,
    model_configs: Iterable[Mapping[str, Any]] | None = None,
    prompt_templates: Iterable[Mapping[str, Any]] | None = None,
):
    """Freeze public task input at submit; resolve only frozen credentials at execution."""
    data_dir = Path(data_dir)
    project = _read(data_dir / "projects" / project_id / "meta.json", None)
    if not isinstance(project, dict):
        raise ValueError("AI_PROJECT_NOT_FOUND: annotation project metadata is missing")

    allowed = {
        "labels",
        "labels_text",
        "reference_image_ids",
        "threshold",
        "overwrite",
        "task_name",
        "provider_id",
        "model_config_id",
        "prompt_template_id",
        "business_instruction",
        "preview_count",
        "prompt_template_snapshot",
        "prompt_template_version_id",
        "prompt_override",
        "effective_prompt_template",
        "effective_prompt_revision",
        "prompt_source",
        "rendered_prompt_preview",
        "image_ids",
        "schema_version",
        "model_config_snapshot",
        "model_config_revision",
        "model_config_name",
        "model_provider",
        "label_schema_snapshot",
        "label_schema_revision",
    }
    prepared = {key: value for key, value in request.items() if key in allowed}
    if not runtime:
        # A browser must never be allowed to submit its own frozen snapshots.
        prepared.pop("prompt_template_snapshot", None)
        prepared.pop("prompt_template_version_id", None)
        prepared.pop("model_config_snapshot", None)
        prepared.pop("model_config_revision", None)
        prepared.pop("model_config_name", None)
        prepared.pop("model_provider", None)
        prepared.pop("effective_prompt_template", None)
        prepared.pop("effective_prompt_revision", None)
        prepared.pop("prompt_source", None)
        prepared.pop("rendered_prompt_preview", None)
        prepared.pop("label_schema_snapshot", None)
        prepared.pop("label_schema_revision", None)

    labels = prepared.get("labels") or re.split(
        r"[、,，;；\n\t]+",
        str(prepared.get("labels_text") or ""),
    )
    labels = list(dict.fromkeys(
        str(label).strip() for label in labels if str(label).strip()
    ))
    references = list(dict.fromkeys(
        str(value) for value in (prepared.get("reference_image_ids") or []) if str(value)
    ))
    if not labels:
        raise ValueError("AI_LABELS_REQUIRED: select annotation labels")

    frozen_catalog = prepared.get("label_schema_snapshot") if runtime else None
    catalog = (
        _json_clone(frozen_catalog)
        if isinstance(frozen_catalog, list)
        else [item for item in label_catalog(project) if item["code"] in labels]
    )
    available_codes = {item["code"] for item in catalog}
    if set(labels) != available_codes:
        unknown = [label for label in labels if label not in available_codes]
        raise ValueError(
            "AI 标注标签必须显式使用当前标签库中的英文编码；"
            "系统不会根据中文名、别名或历史映射自动选择标签："
            + "、".join(unknown[:20])
        )

    threshold = float(prepared.get("threshold", 0.45))
    if not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("AI_THRESHOLD_INVALID: threshold must be between 0 and 1")

    snapshot = prepared.get("model_config_snapshot")
    if runtime and isinstance(snapshot, Mapping):
        snapshot = _json_clone(dict(snapshot))
        expected_revision = str(prepared.get("model_config_revision") or "").strip()
        actual_revision = _snapshot_revision(snapshot)
        if not expected_revision or actual_revision != expected_revision:
            raise ValueError(
                "AI_MODEL_CONFIG_SNAPSHOT_MISMATCH: frozen model configuration revision does not match"
            )
        requested_id = str(prepared.get("model_config_id") or "").strip()
        snapshot_id = str(snapshot.get("id") or "").strip()
        if not snapshot_id or (requested_id and snapshot_id != requested_id):
            raise ValueError(
                "AI_MODEL_CONFIG_SNAPSHOT_ID_MISMATCH: frozen model configuration id does not match"
            )
        config = snapshot
    else:
        configs = list(model_configs) if model_configs is not None else _read(
            data_dir / "model_configs.json", []
        )
        selected_id = str(prepared.get("model_config_id") or prepared.get("provider_id") or "")
        config = (
            next((item for item in configs if str(item.get("id")) == selected_id), None)
            if selected_id
            else next(
                (item for item in configs if item.get("default_for_annotation")),
                configs[0] if configs else None,
            )
        )
        if not config:
            raise ValueError(
                "AI_MODEL_CONFIG_NOT_FOUND: configure and select an available annotation model"
            )
        snapshot, revision = freeze_model_config(config)
        prepared.update({
            "model_config_id": snapshot["id"],
            "model_config_snapshot": snapshot,
            "model_config_revision": revision,
            "model_config_name": str(snapshot.get("name") or snapshot.get("model_name") or ""),
            "model_provider": str(
                snapshot.get("provider_adapter")
                or snapshot.get("provider_type")
                or ""
            ),
        })
        config = snapshot

    if runtime and isinstance(snapshot, Mapping):
        prepared["model_config_name"] = str(
            snapshot.get("name") or snapshot.get("model_name") or prepared.get("model_config_name") or ""
        )
        prepared["model_provider"] = str(
            snapshot.get("provider_adapter")
            or snapshot.get("provider_type")
            or prepared.get("model_provider")
            or ""
        )

    template = prepared.get("prompt_template_snapshot")
    template_id = str(prepared.get("prompt_template_id") or "")
    if not isinstance(template, dict):
        template = {}
        if template_id and template_id != "default":
            templates = list(prompt_templates) if prompt_templates is not None else _read(
                data_dir / "prompt_library.json", []
            )
            template = next(
                (item for item in templates if item.get("id") == template_id),
                None,
            )
            if not template:
                raise ValueError("AI_PROMPT_NOT_FOUND: prompt template does not exist")
            template = _json_clone(dict(template))
            if not template.get("version_id"):
                template = version_template(
                    template,
                    template_id=template_id,
                    now=str(template.get("updated_at") or template.get("created_at") or ""),
                )

    if runtime:
        effective_prompt = str(prepared.get("effective_prompt_template") or "").strip()
        expected_prompt_revision = str(prepared.get("effective_prompt_revision") or "").strip()
        if not effective_prompt or template_version_id(effective_prompt) != expected_prompt_revision:
            raise ValueError(
                "AI_PROMPT_SNAPSHOT_MISMATCH: frozen task prompt is missing or changed"
            )
        expected_schema_revision = str(prepared.get("label_schema_revision") or "").strip()
        schema_body = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if not expected_schema_revision or hashlib.sha256(schema_body.encode("utf-8")).hexdigest() != expected_schema_revision:
            raise ValueError(
                "AI_LABEL_SCHEMA_SNAPSHOT_MISMATCH: frozen label schema is missing or changed"
            )
    else:
        prompt_override = str(prepared.get("prompt_override") or "").strip()
        if len(prompt_override) > MAX_TASK_PROMPT_LENGTH:
            raise ValueError(
                f"AI_PROMPT_TOO_LONG: task prompt is limited to {MAX_TASK_PROMPT_LENGTH} characters"
            )
        template_prompt = str(template.get("prompt") or "").strip()
        model_prompt = str(config.get("annotation_prompt_template") or "").strip()
        effective_prompt = prompt_override or template_prompt or model_prompt or DEFAULT_ANNOTATION_PROMPT
        if len(effective_prompt) > MAX_TASK_PROMPT_LENGTH:
            raise ValueError(
                f"AI_PROMPT_TOO_LONG: effective prompt is limited to {MAX_TASK_PROMPT_LENGTH} characters"
            )
        rendered_preview = build_annotation_prompt(
            config,
            catalog,
            width=640,
            height=480,
            business_instruction=str(prepared.get("business_instruction") or ""),
            template=effective_prompt,
        )
        schema_body = json.dumps(catalog, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        prepared.update({
            "effective_prompt_template": effective_prompt,
            "effective_prompt_revision": template_version_id(effective_prompt),
            "prompt_source": (
                "task_override" if prompt_override else
                "prompt_template" if template_prompt else
                "model_default" if model_prompt else "platform_default"
            ),
            "rendered_prompt_preview": rendered_preview,
            "label_schema_snapshot": _json_clone(catalog),
            "label_schema_revision": hashlib.sha256(schema_body.encode("utf-8")).hexdigest(),
        })
        prepared.pop("prompt_override", None)

    prepared.update({
        "labels": labels,
        "reference_image_ids": references,
        "threshold": threshold,
        "model_config_id": str(config.get("id") or ""),
        "prompt_template_snapshot": template,
        "prompt_template_version_id": template.get("version_id") or "",
        "schema_version": max(2, int(prepared.get("schema_version") or 0)),
    })
    # provider_id is a legacy selector only. Durable execution is always tied to
    # the frozen model_config_id/snapshot pair.
    prepared.pop("provider_id", None)

    if not runtime:
        return prepared

    runtime_config = _json_clone(dict(config))
    reference = str(runtime_config.get("secret_ref") or "")
    secret = (
        os.environ.get(reference[4:])
        if reference.startswith("env:")
        else KeyringSecretStore().get(reference)
    ) if reference else ""
    if reference and not secret:
        raise ValueError(
            "AI_MODEL_SECRET_UNAVAILABLE: frozen model credential reference is unavailable to this Worker"
        )
    runtime_config["_api_key"] = secret or ""
    runtime_config["headers_json"] = _clean_headers(runtime_config.get("headers_json"))
    public_config = {
        key: value
        for key, value in runtime_config.items()
        if key not in {"_api_key", "api_key", "secret_ref"}
    }
    prepared.update({
        "_provider": provider_factory(runtime_config),
        "_provider_config": public_config,
        "label_catalog": catalog,
        "label_ids": {item["code"]: item["class_id"] for item in catalog},
        "label_aliases": {
            item["code"]: list(dict.fromkeys(
                value
                for value in [
                    item["display_name_zh"],
                    *list(item.get("aliases") or []),
                ]
                if value
            ))
            for item in catalog
        },
        "prompt_template": effective_prompt,
    })
    return prepared
