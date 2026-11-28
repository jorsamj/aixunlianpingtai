"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable
from fastapi import HTTPException
from .ai_configuration_contracts import PrelabelServiceReq, V35CoordinateConfirmationReq, V35CoordinateSampleReq, V35ModelAvailabilityReq, V35ModelConfigReq, V35PromptPreviewReq, V35PromptTemplateReq

import json
import base64
import hashlib
import os
import time
import uuid
from io import BytesIO
import requests
from PIL import Image
from filelock import FileLock
from platform_core import auto_label as auto_label_core
from platform_core.errors import PlatformError
from platform_core.prompts import render_prompt, template_version_id, version_template
from platform_core.secrets import secret_ref

@dataclass(frozen=True)
class AiConfigurationDependencies:
    MODEL_CONFIGS_FILE: Callable[..., Any]
    PRELABEL_SERVICES_FILE: Callable[..., Any]
    PROMPT_LIBRARY_FILE: Callable[..., Any]
    _v35_clean_headers: Callable[..., Any]
    _v35_is_vision_provider: Callable[..., Any]
    _v35_model_items: Callable[..., Any]
    _v35_normalize_adapter: Callable[..., Any]
    _v35_prompt_items: Callable[..., Any]
    _v35_publish_model_config: Callable[..., Any]
    _v35_sanitize_secret: Callable[..., Any]
    _v35_save_items: Callable[..., Any]
    _v35_secret_store: Callable[..., Any]
    _v35_test_annotation: Callable[..., Any]
    _v35_unique_default: Callable[..., Any]
    _v35_validate_prompt: Callable[..., Any]
    list_prelabel_services_internal: Callable[..., Any]
    normalize_label: Callable[..., Any]
    now_iso: Callable[..., Any]
    write_json: Callable[..., Any]


class AiConfigurationService:
    def __init__(self, dependencies: AiConfigurationDependencies):
        self.dependencies = dependencies

    def v35_list_model_configs(self, ):
        return {"items": [self.dependencies._v35_sanitize_secret(x) for x in self.dependencies._v35_model_items()]}

    def v35_save_model_config(self, payload: V35ModelConfigReq):
        with FileLock(str(self.dependencies.MODEL_CONFIGS_FILE()) + ".lock", timeout=10):
            name = (payload.name or "").strip()
            if not name:
                raise HTTPException(status_code=400, detail="模型名称不能为空")
            detect_url = (payload.detect_url or payload.base_url or "").strip()
            if not detect_url:
                raise HTTPException(status_code=400, detail="检测接口地址不能为空")
            config_id = uuid.uuid4().hex[:12]
            item = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
            self.dependencies._v35_normalize_adapter(item)
            api_key = str(item.pop("api_key", "") or "")
            if api_key:
                item["inference_account_identity"] = hashlib.sha256(api_key.encode()).hexdigest()
            item["headers_json"] = self.dependencies._v35_clean_headers(item.get("headers_json"))
            if api_key:
                reference = secret_ref("model-config", config_id)
                self.dependencies._v35_secret_store().set(reference, api_key)
                item["secret_ref"] = reference
            item.update({"coordinate_config_revision": uuid.uuid4().hex, "id": config_id, "name": name, "detect_url": detect_url, "created_at": self.dependencies.now_iso(), "updated_at": self.dependencies.now_iso()})
            items = self.dependencies._v35_model_items()
            self.dependencies._v35_unique_default(items, item)
            items.insert(0, item)
            self.dependencies._v35_save_items(self.dependencies.MODEL_CONFIGS_FILE(), items[:100])
            return self.dependencies._v35_publish_model_config(item)

    def v35_update_model_config(self, config_id: str, payload: V35ModelConfigReq):
        with FileLock(str(self.dependencies.MODEL_CONFIGS_FILE()) + ".lock", timeout=10):
            items = self.dependencies._v35_model_items()
            found = False
            for i, item in enumerate(items):
                if item.get("id") == config_id:
                    data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
                    for field in ("api_protocol", "structured_output"):
                        if field not in payload.model_fields_set:
                            data[field] = item.get(field) or "auto"
                    if "enabled" not in payload.model_fields_set:
                        data["enabled"] = item.get("enabled", True)
                    if "wevisone_label_queries" not in payload.model_fields_set and "wevisone_label_queries" in item:
                        data["wevisone_label_queries"] = item["wevisone_label_queries"]
                    for field in ("coordinate_space", "coordinate_order", "coordinate_origin", "coordinate_image_space", "output_protocol", "coordinate_contract_version"):
                        if field not in payload.model_fields_set:
                            if field in item:
                                data[field] = item[field]
                            else:
                                data.pop(field, None)
                    self.dependencies._v35_normalize_adapter(data)
                    api_key = str(data.pop("api_key", "") or "")
                    existing_reference = str(item.get("secret_ref") or "")
                    if api_key and existing_reference:
                        saved = self.dependencies._v35_secret_store().get(existing_reference)
                        if not saved or hashlib.sha256(saved.encode()).digest() != hashlib.sha256(api_key.encode()).digest():
                            raise PlatformError("AI_MODEL_CREDENTIAL_REFERENCES_UNVERIFIED", "原凭据可能仍被已冻结任务引用",
                                "本次未替换凭据。", "可停用原配置，并为新任务新建模型配置。", 409)
                        # An identical key is a no-op for the original secret reference.
                        api_key = ""
                    if api_key:
                        data["inference_account_identity"] = hashlib.sha256(api_key.encode()).hexdigest()
                    elif item.get("inference_account_identity"):
                        data["inference_account_identity"] = item["inference_account_identity"]
                    reference = str(item.get("secret_ref") or secret_ref("model-config", config_id))
                    if api_key:
                        self.dependencies._v35_secret_store().set(reference, api_key)
                        data["secret_ref"] = reference
                    elif item.get("secret_ref"):
                        data["secret_ref"] = item.get("secret_ref")
                    data["headers_json"] = self.dependencies._v35_clean_headers(data.get("headers_json"))
                    data.update({"coordinate_config_revision": uuid.uuid4().hex, "id": config_id, "created_at": item.get("created_at") or self.dependencies.now_iso(), "updated_at": self.dependencies.now_iso()})
                    if not data.get("detect_url"):
                        data["detect_url"] = data.get("base_url") or item.get("detect_url") or ""
                    data["coordinate_validation"] = {"status": "unverified", "reason": "配置已保存，请重新验证真实样本"}
                    items[i] = data
                    self.dependencies._v35_unique_default(items, data)
                    found = True
                    break
            if not found:
                raise HTTPException(status_code=404, detail="模型配置不存在")
            self.dependencies._v35_save_items(self.dependencies.MODEL_CONFIGS_FILE(), items)
            return self.dependencies._v35_publish_model_config(items[i])

    def v35_check_model_capacity(self, config_id: str):
        """Read server evidence only; connection/image checks remain separate."""
        from platform_core.inference_policy import resolve_inference_policy, config_fingerprint
        cfg = next((row for row in self.dependencies._v35_model_items() if row.get("id") == config_id), None)
        if cfg is None:
            raise HTTPException(status_code=404, detail="模型配置不存在")
        return {"policy": resolve_inference_policy(cfg), "config_fingerprint": config_fingerprint(cfg),
                "message": "容量依据运维证据；连接成功或图片解析通过不能证明双实例。未证明时串行。"}

    def v35_delete_model_config(self, config_id: str):
        with FileLock(str(self.dependencies.MODEL_CONFIGS_FILE()) + ".lock", timeout=10):
            current = self.dependencies._v35_model_items()
            removed = next((x for x in current if x.get("id") == config_id), None)
            if removed and removed.get("secret_ref"):
                raise PlatformError("AI_MODEL_CREDENTIAL_REFERENCES_UNVERIFIED", "原凭据可能仍被已冻结任务引用",
                    "本次未删除配置或凭据。", "当前可停用该模型配置。", 409)
            items = [x for x in current if x.get("id") != config_id]
            self.dependencies._v35_save_items(self.dependencies.MODEL_CONFIGS_FILE(), items)
            self.dependencies._v35_publish_model_config(removed_id=config_id)
            return {"ok": True}

    def v35_set_model_availability(self, config_id: str, payload: V35ModelAvailabilityReq):
        """Change availability without invalidating a saved coordinate proof."""
        with FileLock(str(self.dependencies.MODEL_CONFIGS_FILE()) + ".lock", timeout=10):
            items = self.dependencies._v35_model_items()
            current = next((row for row in items if row.get("id") == config_id), None)
            if not current:
                raise HTTPException(status_code=404, detail="模型配置不存在")
            current["enabled"] = payload.enabled
            if not payload.enabled:
                current["default_for_annotation"] = False
            self.dependencies._v35_save_items(self.dependencies.MODEL_CONFIGS_FILE(), items)
            return self.dependencies._v35_publish_model_config(current)

    def v35_test_model_config(self, payload: V35ModelConfigReq):
        config = payload.model_dump()
        if self.dependencies._v35_is_vision_provider(config):
            self.dependencies._v35_normalize_adapter(config)
            config["_api_key"] = config.pop("api_key", "") or ""
            return self.dependencies._v35_test_annotation(config)
        url = (payload.health_url or payload.detect_url or payload.base_url or "").strip()
        if not url:
            raise HTTPException(status_code=400, detail="接口地址为空")
        headers = dict(payload.headers_json or {})
        if payload.api_key:
            headers.setdefault("Authorization", f"Bearer {payload.api_key}")
        try:
            r = requests.get(url, headers=headers, timeout=8)
            text = r.text[:1200]
            body: Any = text
            if "json" in r.headers.get("content-type", ""):
                try:
                    body = r.json()
                except Exception:
                    pass
            return {"ok": True, "status_code": r.status_code, "response": body}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"连接失败：{e}")

    def v35_test_saved_model_annotation(self, config_id: str):
        cfg = next((item for item in self.dependencies._v35_model_items() if item.get("id") == config_id), None)
        if not cfg:
            raise HTTPException(status_code=404, detail="模型配置不存在")
        if cfg.get("enabled") is False:
            raise HTTPException(status_code=409, detail="模型配置已停用，请先启用后再测试")
        runtime_cfg = dict(cfg)
        reference = str(cfg.get("secret_ref") or "")
        runtime_cfg["_api_key"] = self.dependencies._v35_secret_store().get(reference) if reference else ""
        try:
            result = self.dependencies._v35_test_annotation(runtime_cfg)
            record = {"status": "protocol_passed", "checked_at": self.dependencies.now_iso(),
                      "no_target": result["no_target"], "model_loaded": result.get("model_loaded"),
                      "latency_ms": result.get("latency_ms")}
        except PlatformError as error:
            record = {"status": "failed", "checked_at": self.dependencies.now_iso(),
                      "code": str(getattr(error, "code", "MODEL_CONNECTION_TEST_FAILED"))}
            result = None
            failure = error
        # Legacy probe used to be read-only; do not silently rewrite pre-revision
        # configurations merely because someone checks their existing service.
        if cfg.get("coordinate_config_revision"):
            with FileLock(str(self.dependencies.MODEL_CONFIGS_FILE()) + ".lock", timeout=10):
                items = self.dependencies._v35_model_items()
                current = next((item for item in items if item.get("id") == config_id), None)
                if current and current.get("coordinate_config_revision") == cfg.get("coordinate_config_revision"):
                    current["last_test"] = record
                    self.dependencies._v35_save_items(self.dependencies.MODEL_CONFIGS_FILE(), items)
                    self.dependencies._v35_publish_model_config(current)
        if result is None:
            raise failure
        return result

    def v35_verify_model_coordinates(self, config_id: str, payload: V35CoordinateSampleReq):
        from PIL import ImageOps
        from platform_core.annotation_runtime import build_annotation_prompt
        cfg = next((x for x in self.dependencies._v35_model_items() if x.get("id") == config_id), None)
        if not cfg:
            raise HTTPException(status_code=404, detail="模型配置不存在")
        if cfg.get("enabled") is False:
            raise HTTPException(status_code=409, detail="模型配置已停用，请先启用再验证")
        if len(payload.image_base64) > 14_000_000 or not payload.labels or len(payload.labels) > 100:
            raise HTTPException(status_code=400, detail="样本最大 10MB，需提供 1～100 个目标标签")
        try:
            raw = base64.b64decode(payload.image_base64, validate=True)
            if len(raw) > 10_000_000:
                raise ValueError("图片超过 10MB")
            with Image.open(BytesIO(raw)) as source:
                if source.width * source.height > 25_000_000:
                    raise ValueError("图片超过 2500 万像素")
                image = ImageOps.exif_transpose(source).convert("RGB")
                width, height = image.size
                buffer = BytesIO()
                image.save(buffer, format="JPEG", quality=95)
        except Exception as error:
            raise HTTPException(status_code=400, detail="无效或过大的真实样本图片") from error
        runtime_cfg = dict(cfg)
        reference = str(cfg.get("secret_ref") or "")
        runtime_cfg["_api_key"] = os.environ.get(reference[4:], "") if reference.startswith("env:") else (self.dependencies._v35_secret_store().get(reference) if reference else "")
        labels = list(dict.fromkeys(x.strip() for x in payload.labels if x.strip()))
        if not labels:
            raise HTTPException(status_code=400, detail="目标标签不能为空")
        if payload.operation != "detect":
            if (cfg.get("provider_adapter") or cfg.get("provider_type")) != "wevisone_vl":
                raise HTTPException(status_code=400, detail="当前模型适配器不支持分割或抠图预览")
            from platform_core.providers.base import ProviderRequestError
            try:
                provider = auto_label_core.provider_factory(runtime_cfg)
                provider.inspect_model()
                return provider.preview(payload.operation, image_bytes=buffer.getvalue(), labels=labels)
            except ProviderRequestError as error:
                key = runtime_cfg["_api_key"]
                detail = str(error)
                solution = error.solution
                if key:
                    detail = detail.replace(key, "[已隐藏凭据]")
                    solution = solution.replace(key, "[已隐藏凭据]")
                raise PlatformError(code=error.code, message="专用视觉预览失败", detail=detail, solution=solution, status_code=400) from error
        contract = auto_label_core.coordinate_contract(cfg, legacy=True)
        if contract["coordinate_space"] == "legacy_auto":
            raise HTTPException(status_code=400, detail="请先明确并保存坐标范围，再验证样本")
        prompt = build_annotation_prompt(cfg, [{"code": x, "class_id": i} for i, x in enumerate(labels)], width=width, height=height, business_instruction="")
        try:
            result = self.dependencies._v35_test_annotation(runtime_cfg, image_bytes=buffer.getvalue(), sample_prompt=prompt, sample_labels=labels, sample_size=(width, height))
        except PlatformError:
            with FileLock(str(self.dependencies.MODEL_CONFIGS_FILE()) + ".lock", timeout=10):
                items = self.dependencies._v35_model_items()
                current = next((x for x in items if x.get("id") == config_id), None)
                if current is not None and (current.get("coordinate_config_revision") or current.get("updated_at")) == (cfg.get("coordinate_config_revision") or cfg.get("updated_at")) and current.get("coordinate_validation") == cfg.get("coordinate_validation"):
                    current["coordinate_validation"] = {"status": "failed", "checked_at": self.dependencies.now_iso(), "reason": "样本调用或坐标解析不通过，请检查连接、原始输出和坐标合同"}
                    self.dependencies._v35_save_items(self.dependencies.MODEL_CONFIGS_FILE(), items)
                    self.dependencies._v35_publish_model_config(current)
            raise
        # Evidence belongs to this exact saved revision, and is never accepted from clients.
        with FileLock(str(self.dependencies.MODEL_CONFIGS_FILE()) + ".lock", timeout=10):
            revision = cfg.get("coordinate_config_revision") or cfg.get("updated_at")
            items = self.dependencies._v35_model_items()
            current = next((x for x in items if x.get("id") == config_id), None)
            if current is None or (current.get("coordinate_config_revision") or current.get("updated_at")) != revision or current.get("coordinate_validation") != cfg.get("coordinate_validation"):
                raise HTTPException(status_code=409, detail="验证期间配置已改变，请重试")
            evidence = {"status": "unverified", "reason": "样本解析通过，需人工检查原始输出与最终框；不代表识别准确率通过", "checked_at": self.dependencies.now_iso(), "config_revision": revision, "sample_sha256": hashlib.sha256(raw).hexdigest(), "box_count": len(result["parsed_boxes"]), "receipt": uuid.uuid4().hex, "expires_at_epoch": time.time() + 900, "parsed_boxes_sha256": hashlib.sha256(json.dumps(result["parsed_boxes"], sort_keys=True).encode()).hexdigest()}
            current["coordinate_validation"] = evidence
            self.dependencies._v35_save_items(self.dependencies.MODEL_CONFIGS_FILE(), items)
            self.dependencies._v35_publish_model_config(current)
        return {**result, "coordinate_validation": evidence, "coordinate_contract": contract, "image_width": width, "image_height": height, "input_image_url": "data:image/jpeg;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"), "geometry": "EXIF 已校正；发送的 JPEG 与展示图片尺寸一致；无平台裁剪或填充。模型内部变换须由服务按该输入坐标返回。"}

    def v35_confirm_model_coordinates(self, config_id: str, payload: V35CoordinateConfirmationReq):
        with FileLock(str(self.dependencies.MODEL_CONFIGS_FILE()) + ".lock", timeout=10):
            items = self.dependencies._v35_model_items()
            cfg = next((x for x in items if x.get("id") == config_id), None)
            if not cfg:
                raise HTTPException(status_code=404, detail="模型配置不存在")
            evidence = cfg.get("coordinate_validation") or {}
            if (evidence.get("status") != "unverified" or not evidence.get("receipt")
                or evidence.get("receipt") != payload.receipt
                or evidence.get("config_revision") != payload.config_revision
                or (cfg.get("coordinate_config_revision") or cfg.get("updated_at")) != payload.config_revision
                or evidence.get("sample_sha256") != payload.sample_sha256
                or evidence.get("expires_at_epoch", 0) < time.time()
                or not evidence.get("box_count")):
                raise HTTPException(status_code=409, detail="样本验证已失效或无有效框，请重新验证含目标的真实样本")
            evidence.update({"status": "verified", "confirmed_at": self.dependencies.now_iso(), "reason": "已人工确认此真实样本的框位置；仅验证当前配置和样本，不代表模型整体准确率"})
            evidence.pop("receipt", None)
            cfg["coordinate_contract_version"] = 1
            self.dependencies._v35_save_items(self.dependencies.MODEL_CONFIGS_FILE(), items)
            return self.dependencies._v35_publish_model_config(cfg)

    def v35_list_prompt_templates(self, ):
        return {"items": self.dependencies._v35_prompt_items()}

    def v35_save_prompt_template(self, payload: V35PromptTemplateReq):
        name = (payload.name or "").strip()
        if not name:
            raise HTTPException(status_code=400, detail="模板名称不能为空")
        if not (payload.prompt or "").strip():
            raise HTTPException(status_code=400, detail="提示词不能为空")
        self.dependencies._v35_validate_prompt(payload.prompt)
        data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
        data["name"] = name
        item = version_template(data, template_id=uuid.uuid4().hex[:12], now=self.dependencies.now_iso())
        items = self.dependencies._v35_prompt_items()
        items.insert(0, item)
        self.dependencies._v35_save_items(self.dependencies.PROMPT_LIBRARY_FILE(), items[:200])
        return item

    def v35_update_prompt_template(self, template_id: str, payload: V35PromptTemplateReq):
        if not (payload.name or "").strip():
            raise HTTPException(status_code=400, detail="模板名称不能为空")
        if not (payload.prompt or "").strip():
            raise HTTPException(status_code=400, detail="提示词不能为空")
        self.dependencies._v35_validate_prompt(payload.prompt)
        items = self.dependencies._v35_prompt_items()
        for i, item in enumerate(items):
            if item.get("id") == template_id:
                payload_data = payload.model_dump() if hasattr(payload, "model_dump") else payload.dict()
                data = version_template(payload_data, template_id=template_id, now=self.dependencies.now_iso(), previous=item)
                items[i] = data
                self.dependencies._v35_save_items(self.dependencies.PROMPT_LIBRARY_FILE(), items)
                return data
        raise HTTPException(status_code=404, detail="提示词模板不存在")

    def v35_delete_prompt_template(self, template_id: str):
        items = [x for x in self.dependencies._v35_prompt_items() if x.get("id") != template_id]
        self.dependencies._v35_save_items(self.dependencies.PROMPT_LIBRARY_FILE(), items)
        return {"ok": True}

    def v35_preview_prompt_template(self, payload: V35PromptPreviewReq):
        try:
            rendered = render_prompt(
                payload.prompt,
                labels=payload.labels or [],
                width=payload.image_width,
                height=payload.image_height,
                business_instruction=payload.business_instruction,
            )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return {"rendered_prompt": rendered, "version_id": template_version_id(payload.prompt)}

    def list_prelabel_services(self, ):
        return self.dependencies.list_prelabel_services_internal()

    def save_prelabel_service(self, payload: PrelabelServiceReq):
        name = payload.name.strip()
        detect_url = payload.detect_url.strip()
        if not name or not detect_url:
            raise HTTPException(status_code=400, detail="服务名称和检测地址不能为空")
        item = {
            "id": uuid.uuid4().hex[:10],
            "name": name,
            "detect_url": detect_url,
            "health_url": (payload.health_url or "").strip(),
            "request_mode": payload.request_mode,
            "image_field": payload.image_field or "image",
            "threshold": float(payload.threshold),
            "target_label": self.dependencies.normalize_label(payload.target_label or "person"),
            "created_at": self.dependencies.now_iso(),
        }
        services = self.dependencies.list_prelabel_services_internal()
        services.insert(0, item)
        self.dependencies.write_json(self.dependencies.PRELABEL_SERVICES_FILE(), services[:30])
        return item

    def delete_prelabel_service(self, service_id: str):
        services = [s for s in self.dependencies.list_prelabel_services_internal() if s.get("id") != service_id]
        self.dependencies.write_json(self.dependencies.PRELABEL_SERVICES_FILE(), services)
        return {"ok": True}

    def test_prelabel_service(self, payload: PrelabelServiceReq):
        url = (payload.health_url or payload.detect_url).strip()
        try:
            r = requests.get(url, timeout=8)
            return {"ok": True, "status_code": r.status_code, "response": r.json() if "json" in r.headers.get("content-type", "") else r.text[:1000]}
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"连接失败：{e}")
