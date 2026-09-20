from __future__ import annotations

import hashlib
import json
import threading
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Literal, Mapping, Optional
from urllib.parse import urljoin

import requests
from fastapi import APIRouter, Query, Request
from filelock import FileLock, Timeout
from pydantic import BaseModel, Field

from .algorithm_sql_store import AlgorithmSqlStore
from .algorithms import list_algorithms
from .annotations import atomic_write_json
from .errors import PlatformError
from .integration_audit import IntegrationAuditRepository, redact
from .secrets import SecretCredentialStore, secret_ref


PROVIDER_LOCAL = "LOCAL"
PROVIDER_CHANGLIAN = "CHANG_LIAN"
SOURCE_LOCAL = "LOCAL"
SOURCE_EXTERNAL = "EXTERNAL"
CONFIG_SCHEMA_VERSION = 2
CACHE_SCHEMA_VERSION = 1
MAX_SYNC_HISTORY = 100
DEFAULT_AUTO_SYNC_INTERVAL_SECONDS = 600

CHANG_LIAN_API_DOCUMENTS: tuple[dict[str, str], ...] = (
    {"key":"login_method","group":"登录验证","title":"登录方法","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/439653047e0.md","status":"reference","method":"POST","path":"/login","auth":"human_login"},
    {"key":"auth_token","group":"应用鉴权","title":"内部应用鉴权获取Token","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515307570e0.md","status":"wired","method":"POST","path":"/internal/auth/token","auth":"application_signature"},
    {"key":"auth_test_sign","group":"应用鉴权","title":"内部应用签名测试","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515307571e0.md","status":"wired","method":"POST","path":"/internal/auth/test-sign","auth":"application_signature"},
    {"key":"auth_logout","group":"应用鉴权","title":"内部应用登出","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515307572e0.md","status":"wired","method":"POST","path":"/internal/auth/logout","auth":"bearer"},
    {"key":"weight_edit","group":"算法权重文件管理","title":"修改算法权重文件","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837707e0.md","status":"wired","method":"POST","path":"/internal/algorithm/algorithm-weight/edit","auth":"bearer"},
    {"key":"weight_add","group":"算法权重文件管理","title":"新增算法权重文件","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837708e0.md","status":"wired","method":"POST","path":"/internal/algorithm/algorithm-weight/add","auth":"bearer"},
    {"key":"weight_remove","group":"算法权重文件管理","title":"删除算法权重文件","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837709e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-weight/remove/{weightIds}","auth":"bearer"},
    {"key":"weight_list","group":"算法权重文件管理","title":"查询算法权重文件列表(分页)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837710e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-weight/list","auth":"bearer"},
    {"key":"weight_list_by_version","group":"算法权重文件管理","title":"查询某算法版本下全部算法权重文件(含算力环境名称/编号)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837711e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}","auth":"bearer"},
    {"key":"weight_list_by_product","group":"算法权重文件管理","title":"按算法产品查询算法权重文件(算法调度用)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837712e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-weight/listByProduct/{productId}","auth":"bearer"},
    {"key":"weight_detail","group":"算法权重文件管理","title":"查询算法权重文件详细信息","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837713e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-weight/getInfo/{weightId}","auth":"bearer"},
    {"key":"version_edit","group":"算法版本管理","title":"修改算法版本","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837714e0.md","status":"wired","method":"POST","path":"/internal/algorithm/algorithm-version/edit","auth":"bearer"},
    {"key":"version_add","group":"算法版本管理","title":"新增算法版本","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837715e0.md","status":"wired","method":"POST","path":"/internal/algorithm/algorithm-version/add","auth":"bearer"},
    {"key":"version_remove","group":"算法版本管理","title":"删除算法版本(同时删除其下全部算法权重文件)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837716e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-version/remove/{algoVersionIds}","auth":"bearer"},
    {"key":"version_list","group":"算法版本管理","title":"查询算法版本列表(分页)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837717e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-version/list","auth":"bearer"},
    {"key":"version_list_by_product","group":"算法版本管理","title":"查询某算法产品下全部算法版本(含权重文件数量)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837718e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-version/listByProduct/{productId}","auth":"bearer"},
    {"key":"version_list_by_analysis","group":"算法版本管理","title":"查询某分析方式下全部算法版本(含权重文件数量)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837719e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-version/listByAnalysis/{analysisId}","auth":"bearer"},
    {"key":"version_list_all","group":"算法版本管理","title":"查询算法版本列表(不分页)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837720e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-version/listAll","auth":"bearer"},
    {"key":"version_detail","group":"算法版本管理","title":"查询算法版本详细信息","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837721e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-version/getInfo/{algoVersionId}","auth":"bearer"},
    {"key":"product_list","group":"算法产品管理","title":"查询算法产品列表(分页)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837722e0.md","status":"wired","method":"GET","path":"/internal/algorithm/product-ai/list","auth":"bearer"},
    {"key":"product_list_all","group":"算法产品管理","title":"查询算法产品列表(不分页)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837723e0.md","status":"wired","method":"GET","path":"/internal/algorithm/product-ai/listAll","auth":"bearer"},
    {"key":"product_detail","group":"算法产品管理","title":"查询算法产品详细信息","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837724e0.md","status":"wired","method":"GET","path":"/internal/algorithm/product-ai/getInfo/{productId}","auth":"bearer"},
    {"key":"analysis_list","group":"算法产品分析方式管理","title":"查询分析方式列表(分页)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837725e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-analysis/list","auth":"bearer"},
    {"key":"analysis_list_by_product","group":"算法产品分析方式管理","title":"查询某算法产品下全部分析方式(含关联明细)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837726e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-analysis/listByProduct/{productId}","auth":"bearer"},
    {"key":"analysis_list_all","group":"算法产品分析方式管理","title":"查询分析方式列表(不分页)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837727e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-analysis/listAll","auth":"bearer"},
    {"key":"analysis_detail","group":"算法产品分析方式管理","title":"查询分析方式详细信息(含关联明细)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837728e0.md","status":"wired","method":"GET","path":"/internal/algorithm/algorithm-analysis/getInfo/{analysisId}","auth":"bearer"},
    {"key":"compute_list","group":"算力环境管理","title":"查询算力环境列表(分页)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837729e0.md","status":"wired","method":"GET","path":"/internal/base/compute-platform/list","auth":"bearer"},
    {"key":"compute_list_all","group":"算力环境管理","title":"查询算力环境列表(不分页)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837730e0.md","status":"wired","method":"GET","path":"/internal/base/compute-platform/listAll","auth":"bearer"},
    {"key":"category_tree","group":"算法品目管理","title":"查询算法品目树(父节点含所有子节点数量)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837731e0.md","status":"wired","method":"GET","path":"/internal/base/category/tree","auth":"bearer"},
    {"key":"category_list","group":"算法品目管理","title":"查询算法品目列表(分页)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837732e0.md","status":"wired","method":"GET","path":"/internal/base/category/list","auth":"bearer"},
    {"key":"category_list_all","group":"算法品目管理","title":"查询算法品目列表(不分页)","doc_url":"https://s.apifox.cn/c5c8b6af-b230-4873-8094-717498d6b5b6/515837733e0.md","status":"wired","method":"GET","path":"/internal/base/category/listAll","auth":"bearer"},
)


def changlian_api_documents() -> list[Dict[str, str]]:
    return [dict(item) for item in CHANG_LIAN_API_DOCUMENTS]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _clean_path(value: Any, fallback: str = "") -> str:
    text = str(value or fallback).strip()
    if text and not text.startswith("/"):
        text = "/" + text
    return text


LEGACY_CHANGLIAN_ENDPOINTS: Dict[str, str] = {
    "/algorithm-category/tree": "/internal/base/category/tree",
    "/internal/base/algorithm-category/tree": "/internal/base/category/tree",
    "/algorithm-product/listAll": "/internal/algorithm/product-ai/listAll",
    "/internal/algorithm/algorithm-product/listAll": "/internal/algorithm/product-ai/listAll",
    "/algorithm-product-analysis/listByProduct/{productId}": "/internal/algorithm/algorithm-analysis/listByProduct/{productId}",
    "/internal/algorithm/algorithm-product-analysis/listByProduct/{productId}": "/internal/algorithm/algorithm-analysis/listByProduct/{productId}",
    "/compute-platform/listAll": "/internal/base/compute-platform/listAll",
    "/algorithm-version/add": "/internal/algorithm/algorithm-version/add",
    "/algorithm-version/listByProduct/{productId}": "/internal/algorithm/algorithm-version/listByProduct/{productId}",
    "/algorithm-weight/add": "/internal/algorithm/algorithm-weight/add",
    "/algorithm-weight/listByVersion/{algoVersionId}": "/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}",
}


def _canonical_endpoint_path(value: Any, fallback: str) -> str:
    path = _clean_path(value, fallback)
    return LEGACY_CHANGLIAN_ENDPOINTS.get(path, path)


@dataclass(frozen=True)
class ChangLianEndpoints:
    """Canonical 新畅联 internal API contract extracted from the official OpenAPI compilation."""

    test_sign: str = "/internal/auth/test-sign"
    token: str = "/internal/auth/token"
    logout: str = "/internal/auth/logout"

    category_tree: str = "/internal/base/category/tree"
    category_list: str = "/internal/base/category/list"
    category_list_all: str = "/internal/base/category/listAll"

    product_list_page: str = "/internal/algorithm/product-ai/list"
    product_list: str = "/internal/algorithm/product-ai/listAll"
    product_detail: str = "/internal/algorithm/product-ai/getInfo/{productId}"

    analysis_list_page: str = "/internal/algorithm/algorithm-analysis/list"
    analysis_by_product: str = "/internal/algorithm/algorithm-analysis/listByProduct/{productId}"
    analysis_list_all: str = "/internal/algorithm/algorithm-analysis/listAll"
    analysis_detail: str = "/internal/algorithm/algorithm-analysis/getInfo/{analysisId}"

    compute_platform_list_page: str = "/internal/base/compute-platform/list"
    compute_platform_list: str = "/internal/base/compute-platform/listAll"

    version_edit: str = "/internal/algorithm/algorithm-version/edit"
    version_create: str = "/internal/algorithm/algorithm-version/add"
    version_remove: str = "/internal/algorithm/algorithm-version/remove/{algoVersionIds}"
    version_list_page: str = "/internal/algorithm/algorithm-version/list"
    version_list_by_product: str = "/internal/algorithm/algorithm-version/listByProduct/{productId}"
    version_list_by_analysis: str = "/internal/algorithm/algorithm-version/listByAnalysis/{analysisId}"
    version_list_all: str = "/internal/algorithm/algorithm-version/listAll"
    version_detail: str = "/internal/algorithm/algorithm-version/getInfo/{algoVersionId}"

    weight_edit: str = "/internal/algorithm/algorithm-weight/edit"
    weight_create: str = "/internal/algorithm/algorithm-weight/add"
    weight_remove: str = "/internal/algorithm/algorithm-weight/remove/{weightIds}"
    weight_list_page: str = "/internal/algorithm/algorithm-weight/list"
    weight_list_by_version: str = "/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}"
    weight_list_by_product: str = "/internal/algorithm/algorithm-weight/listByProduct/{productId}"
    weight_detail: str = "/internal/algorithm/algorithm-weight/getInfo/{weightId}"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "ChangLianEndpoints":
        data = dict(value or {})
        defaults = cls()
        return cls(**{
            field_name: _canonical_endpoint_path(data.get(field_name), getattr(defaults, field_name))
            for field_name in defaults.__dataclass_fields__
        })


DEFAULT_CONFIG: Dict[str, Any] = {
    "schema_version": CONFIG_SCHEMA_VERSION,
    "mode": "local",
    "provider": "changlian",
    "base_url": "",
    "auto_sync_enabled": False,
    "auto_sync_interval_seconds": DEFAULT_AUTO_SYNC_INTERVAL_SECONDS,
    "auto_publish_enabled": False,
    "credential_ref": secret_ref("external-platform", "changlian"),
    "endpoints": asdict(ChangLianEndpoints()),
    "updated_at": None,
}


class EndpointPayload(BaseModel):
    test_sign: str = ChangLianEndpoints.test_sign
    token: str = ChangLianEndpoints.token
    logout: str = ChangLianEndpoints.logout
    category_tree: str = ChangLianEndpoints.category_tree
    category_list: str = ChangLianEndpoints.category_list
    category_list_all: str = ChangLianEndpoints.category_list_all
    product_list_page: str = ChangLianEndpoints.product_list_page
    product_list: str = ChangLianEndpoints.product_list
    product_detail: str = ChangLianEndpoints.product_detail
    analysis_list_page: str = ChangLianEndpoints.analysis_list_page
    analysis_by_product: str = ChangLianEndpoints.analysis_by_product
    analysis_list_all: str = ChangLianEndpoints.analysis_list_all
    analysis_detail: str = ChangLianEndpoints.analysis_detail
    compute_platform_list_page: str = ChangLianEndpoints.compute_platform_list_page
    compute_platform_list: str = ChangLianEndpoints.compute_platform_list
    version_edit: str = ChangLianEndpoints.version_edit
    version_create: str = ChangLianEndpoints.version_create
    version_remove: str = ChangLianEndpoints.version_remove
    version_list_page: str = ChangLianEndpoints.version_list_page
    version_list_by_product: str = ChangLianEndpoints.version_list_by_product
    version_list_by_analysis: str = ChangLianEndpoints.version_list_by_analysis
    version_list_all: str = ChangLianEndpoints.version_list_all
    version_detail: str = ChangLianEndpoints.version_detail
    weight_edit: str = ChangLianEndpoints.weight_edit
    weight_create: str = ChangLianEndpoints.weight_create
    weight_remove: str = ChangLianEndpoints.weight_remove
    weight_list_page: str = ChangLianEndpoints.weight_list_page
    weight_list_by_version: str = ChangLianEndpoints.weight_list_by_version
    weight_list_by_product: str = ChangLianEndpoints.weight_list_by_product
    weight_detail: str = ChangLianEndpoints.weight_detail


class ChangLianVersionMutationPayload(BaseModel):
    algoVersionId: int | str | None = None
    analysisId: int | str | None = None
    productId: int | str | None = None
    versionName: str = ""
    versionNo: str = ""


class ChangLianWeightMutationPayload(BaseModel):
    weightId: int | str | None = None
    algoVersionId: int | str | None = None
    computePlatformId: int | str | None = None
    chipCode: str = ""
    fileName: str = ""
    filePath: str = ""


class ExternalPlatformConfigPayload(BaseModel):
    mode: Literal["local", "external"] = "local"
    provider: Literal["changlian"] = "changlian"
    base_url: str = ""
    auto_sync_enabled: bool = False
    auto_sync_interval_seconds: int = Field(default=DEFAULT_AUTO_SYNC_INTERVAL_SECONDS, ge=60, le=86400)
    auto_publish_enabled: bool = False
    access_key: Optional[str] = None
    access_secret: Optional[str] = None
    endpoints: EndpointPayload = Field(default_factory=EndpointPayload)


class ExternalPlatformRepository:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "external_algorithm_platform"
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "config.json"
        self.cache_path = self.root / "master-data-cache.json"
        self.history_path = self.root / "sync-history.json"
        self.lock = FileLock(str(self.root / ".lock"), timeout=30)

    def config(self) -> Dict[str, Any]:
        with self.lock:
            if not self.config_path.exists():
                return json.loads(json.dumps(DEFAULT_CONFIG))
            try:
                body = json.loads(self.config_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise PlatformError(
                    "EXTERNAL_PLATFORM_CONFIG_INVALID",
                    "外部平台配置无法读取",
                    str(error),
                    "请恢复 external_algorithm_platform/config.json，或重新保存平台对接配置。",
                    500,
                ) from error
            if not isinstance(body, dict):
                raise PlatformError(
                    "EXTERNAL_PLATFORM_CONFIG_INVALID",
                    "外部平台配置格式不正确",
                    "配置根节点必须为对象。",
                    "请重新保存平台对接配置。",
                    500,
                )
            result = json.loads(json.dumps(DEFAULT_CONFIG))
            result.update(body)
            result["endpoints"] = asdict(ChangLianEndpoints.from_mapping(body.get("endpoints")))
            return result

    def save_config(self, value: Mapping[str, Any]) -> Dict[str, Any]:
        current = self.config()
        result = dict(current)
        result.update({
            "schema_version": CONFIG_SCHEMA_VERSION,
            "mode": str(value.get("mode") or "local"),
            "provider": str(value.get("provider") or "changlian"),
            "base_url": normalize_base_url(value.get("base_url")),
            "auto_sync_enabled": bool(value.get("auto_sync_enabled", False)),
            "auto_sync_interval_seconds": max(60, min(86400, int(value.get("auto_sync_interval_seconds") or DEFAULT_AUTO_SYNC_INTERVAL_SECONDS))),
            "auto_publish_enabled": bool(value.get("auto_publish_enabled", False)),
            "credential_ref": current.get("credential_ref") or DEFAULT_CONFIG["credential_ref"],
            "endpoints": asdict(ChangLianEndpoints.from_mapping(value.get("endpoints"))),
            "updated_at": utc_now(),
        })
        with self.lock:
            atomic_write_json(self.config_path, result)
        return result

    def cache(self) -> Dict[str, Any]:
        with self.lock:
            if not self.cache_path.exists():
                return {"schema_version": CACHE_SCHEMA_VERSION, "provider": None}
            try:
                value = json.loads(self.cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {"schema_version": CACHE_SCHEMA_VERSION, "provider": None}
            return value if isinstance(value, dict) else {"schema_version": CACHE_SCHEMA_VERSION, "provider": None}

    def save_cache(self, value: Mapping[str, Any]) -> None:
        body = dict(value)
        body["schema_version"] = CACHE_SCHEMA_VERSION
        with self.lock:
            atomic_write_json(self.cache_path, body)

    def history(self) -> list[Dict[str, Any]]:
        with self.lock:
            if not self.history_path.exists():
                return []
            try:
                value = json.loads(self.history_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return []
            return list(value) if isinstance(value, list) else []

    def append_history(self, item: Mapping[str, Any]) -> None:
        with self.lock:
            rows: list[Dict[str, Any]] = []
            if self.history_path.exists():
                try:
                    raw = json.loads(self.history_path.read_text(encoding="utf-8"))
                    if isinstance(raw, list):
                        rows = list(raw)
                except (OSError, json.JSONDecodeError):
                    rows = []
            rows.insert(0, dict(item))
            atomic_write_json(self.history_path, rows[:MAX_SYNC_HISTORY])


def normalize_base_url(value: Any) -> str:
    text = str(value or "").strip().rstrip("/")
    if not text:
        return ""
    if not (text.startswith("http://") or text.startswith("https://")):
        raise PlatformError(
            "EXTERNAL_PLATFORM_URL_INVALID",
            "外部平台地址格式不正确",
            "服务地址必须以 http:// 或 https:// 开头。",
            "请填写新畅联 API 的完整服务地址。",
            422,
        )
    return text


def _value_from(body: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in body and body[key] not in (None, ""):
            return body[key]
    return None


SUCCESS_BUSINESS_CODES = {"0", "200", "SUCCESS", "success"}


def _business_code(body: Any) -> str:
    if not isinstance(body, dict) or "code" not in body or body.get("code") is None:
        return ""
    return str(body.get("code"))


def _business_failed(body: Any) -> bool:
    if not isinstance(body, dict):
        return False
    if body.get("success") is False:
        return True
    return body.get("code") is not None and _business_code(body) not in SUCCESS_BUSINESS_CODES


def _business_message(body: Any) -> str:
    if not isinstance(body, dict):
        return ""
    return str(body.get("message") or body.get("msg") or body.get("reason") or body.get("detail") or "")


class ChangLianBusinessError(RuntimeError):
    def __init__(self, *, code: str, message: str, endpoint: str = "", http_status: int | None = None):
        self.business_code = str(code or "")
        self.endpoint = str(endpoint or "")
        self.http_status = http_status
        self.remote_message = str(message or "新畅联返回失败")
        code_text = self.business_code or "-"
        self.detail = f"新畅联业务码 {code_text}：{self.remote_message}"
        super().__init__(self.detail)


def _unwrap(body: Any) -> Any:
    if not isinstance(body, dict):
        return body
    if _business_failed(body):
        raise ChangLianBusinessError(code=_business_code(body), message=_business_message(body) or "新畅联返回失败")
    for key in ("data", "result"):
        if key in body:
            return body[key]
    return body


def extract_items(value: Any) -> list[Dict[str, Any]]:
    value = _unwrap(value)
    if isinstance(value, list):
        return [dict(row) for row in value if isinstance(row, dict)]
    if not isinstance(value, dict):
        return []
    for key in ("items", "rows", "records", "list", "content", "data"):
        rows = value.get(key)
        if isinstance(rows, list):
            return [dict(row) for row in rows if isinstance(row, dict)]
        if isinstance(rows, dict):
            nested = extract_items(rows)
            if nested:
                return nested
    if any(key in value for key in ("categoryId", "productId", "computePlatformId", "analysisId")):
        return [dict(value)]
    return []


def flatten_category_tree(value: Any) -> list[Dict[str, Any]]:
    roots = extract_items(value)
    result: list[Dict[str, Any]] = []

    def walk(row: Mapping[str, Any], parent_id: Any = None) -> None:
        item = dict(row)
        item.setdefault("parentId", parent_id)
        children = item.pop("children", None)
        result.append(item)
        if isinstance(children, list):
            current_id = _value_from(item, "categoryId", "id")
            for child in children:
                if isinstance(child, dict):
                    walk(child, current_id)

    for root in roots:
        walk(root)
    return result


class _ResponseAdapter:
    @staticmethod
    def json(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError as error:
            raise RuntimeError(f"外部平台返回的不是 JSON（HTTP {response.status_code}）") from error



def _compact_params(values: Mapping[str, Any]) -> Dict[str, Any]:
    return {str(key): value for key, value in values.items() if value not in (None, "")}


def _remote_json_id(value: Any) -> Any:
    text = str(value or "").strip()
    if text.isdigit():
        return int(text)
    return value


def _remote_path_ids(values: Iterable[Any]) -> str:
    result = [str(value).strip() for value in values if str(value or "").strip()]
    if not result:
        raise ValueError("至少需要一个远端 ID")
    return ",".join(result)


def _dump_version_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    body = {key: value for key, value in dict(payload).items() if value not in (None, "")}
    for key in ("algoVersionId", "analysisId", "productId"):
        if key in body:
            body[key] = _remote_json_id(body[key])
    return body


def _dump_weight_payload(payload: Mapping[str, Any]) -> Dict[str, Any]:
    body = {key: value for key, value in dict(payload).items() if value not in (None, "")}
    for key in ("weightId", "algoVersionId", "computePlatformId"):
        if key in body:
            body[key] = _remote_json_id(body[key])
    return body

class ChangLianClient:
    def __init__(
        self,
        *,
        base_url: str,
        access_key: str,
        access_secret: str,
        endpoints: ChangLianEndpoints,
        session: Optional[requests.Session] = None,
        timeout: float = 15.0,
        audit_callback: Optional[Callable[[Mapping[str, Any]], Any]] = None,
    ):
        self.base_url = normalize_base_url(base_url)
        self.access_key = str(access_key or "").strip()
        self.access_secret = str(access_secret or "")
        self.endpoints = endpoints
        self.session = session or requests.Session()
        self.timeout = timeout
        self._token = ""
        self._token_type = "Bearer"
        self._token_expires_at = 0.0
        self._token_lock = threading.Lock()
        self.audit_callback = audit_callback
        self.audit_context: Dict[str, Any] = {}
        if not self.access_key or not self.access_secret:
            raise PlatformError(
                "EXTERNAL_PLATFORM_CREDENTIAL_REQUIRED",
                "新畅联应用凭据尚未配置",
                "AccessKey / AccessSecret 缺失。",
                "请先在“配置中心 → 平台对接”保存应用凭据。",
                422,
            )

    def _url(self, path: str) -> str:
        return urljoin(self.base_url + "/", str(path or "").lstrip("/"))

    def set_audit_context(self, **context: Any) -> None:
        self.audit_context.update({key: value for key, value in context.items() if value not in (None, "")})

    def _operation_for_path(self, path: str) -> str:
        current = str(path or "").split("?", 1)[0]
        if current == self.endpoints.test_sign:
            return "auth_signature"
        if current == self.endpoints.token:
            return "auth_token"
        if current == self.endpoints.logout:
            return "auth_logout"
        if "/internal/base/category/" in current:
            return "category_list"
        if "/internal/base/compute-platform/" in current:
            return "compute_platform_list"
        if "/internal/algorithm/product-ai/" in current:
            return "product_detail" if "/getInfo/" in current else "product_list"
        if "/internal/algorithm/algorithm-analysis/" in current:
            return "analysis_detail" if "/getInfo/" in current else "analysis_list"
        if "/internal/algorithm/algorithm-version/" in current:
            if current.endswith("/add"):
                return "version_create"
            if current.endswith("/edit"):
                return "version_edit"
            if "/remove/" in current:
                return "version_remove"
            if "/getInfo/" in current:
                return "version_detail"
            return "version_list"
        if "/internal/algorithm/algorithm-weight/" in current:
            if current.endswith("/add"):
                return "weight_create"
            if current.endswith("/edit"):
                return "weight_edit"
            if "/remove/" in current:
                return "weight_remove"
            if "/getInfo/" in current:
                return "weight_detail"
            return "weight_list"
        return "http_request"

    def _emit_audit(self, event: Mapping[str, Any]) -> None:
        if not self.audit_callback:
            return
        try:
            self.audit_callback(redact({"provider": "changlian", **self.audit_context, **dict(event)}))
        except Exception:
            # Audit persistence must never change remote-call semantics.
            pass

    def _request(
        self,
        method: str,
        path: str,
        *,
        auth: bool = False,
        **kwargs: Any,
    ) -> Any:
        headers = dict(kwargs.pop("headers", {}) or {})
        headers.setdefault("Accept", "application/json")
        if auth:
            token_type, token = self.token()
            # The official OpenAPI compilation declares Authorization: Bearer
            # for all internal business APIs. "Access-Token" in logout prose
            # names the token value; it is not the HTTP header name.
            headers.pop("Access-Token", None)
            headers["Authorization"] = f"{token_type} {token}".strip()
        started = time.perf_counter()
        correlation_id = hashlib.sha256(f"{time.time_ns()}:{method}:{path}".encode()).hexdigest()[:24]
        request_snapshot = {
            "headers": headers,
            "params": kwargs.get("params") or {},
            "json": kwargs.get("json") or {},
        }
        try:
            response = self.session.request(
                method.upper(),
                self._url(path),
                headers=headers,
                timeout=self.timeout,
                **kwargs,
            )
        except requests.RequestException as error:
            self._emit_audit({
                "operation": self._operation_for_path(path), "status": "UNKNOWN", "method": method,
                "endpoint": str(path), "duration_ms": int((time.perf_counter() - started) * 1000),
                "correlation_id": correlation_id, "request": request_snapshot,
                "error_code": type(error).__name__, "error_message": str(error),
            })
            raise RuntimeError(f"无法连接外部平台：{type(error).__name__}") from error
        try:
            body = response.json()
        except ValueError:
            body = {"raw": str(getattr(response, "text", ""))[:2000]}
        response_headers = getattr(response, "headers", {}) or {}
        request_id = str(
            response_headers.get("X-Request-Id") or response_headers.get("X-Request-ID")
            or response_headers.get("X-Correlation-Id") or response_headers.get("Trace-Id") or ""
        )
        business_code = _business_code(body)
        business_failed = _business_failed(body)
        http_ok = 200 <= response.status_code < 300
        message = _business_message(body)
        self._emit_audit({
            "operation": self._operation_for_path(path),
            "status": "SUCCESS" if http_ok and not business_failed else "FAILED",
            "method": method, "endpoint": str(path), "http_status": response.status_code,
            "business_code": business_code, "duration_ms": int((time.perf_counter() - started) * 1000),
            "request_id": request_id, "correlation_id": correlation_id,
            "request": request_snapshot, "response": body,
            "error_code": business_code if (business_failed or not http_ok) else "",
            "error_message": message if (business_failed or not http_ok) else "",
        })
        if not http_ok:
            suffix = f"：{message}" if message else ""
            raise RuntimeError(f"外部平台请求失败 HTTP {response.status_code}{suffix}")
        if business_failed:
            raise ChangLianBusinessError(code=business_code, message=message or "新畅联返回失败", endpoint=str(path), http_status=response.status_code)
        return body

    def _signature(self) -> Dict[str, str]:
        params = {"access_key": self.access_key, "access_secret": self.access_secret}
        body = _unwrap(self._request("POST", self.endpoints.test_sign, params=params))
        if not isinstance(body, dict):
            raise RuntimeError("签名测试接口未返回 timestamp / nonce / signature")
        timestamp = _value_from(body, "timestamp", "timeStamp")
        nonce = _value_from(body, "nonce", "nonceStr")
        signature = _value_from(body, "signature", "sign")
        if not timestamp or not nonce or not signature:
            raise RuntimeError("签名测试接口缺少 timestamp / nonce / signature")
        return {
            "Timestamp": str(timestamp),
            "Nonce": str(nonce),
            "Signature": str(signature),
        }

    def token(self) -> tuple[str, str]:
        now = time.monotonic()
        if self._token and now < self._token_expires_at:
            return self._token_type, self._token
        with self._token_lock:
            now = time.monotonic()
            if self._token and now < self._token_expires_at:
                return self._token_type, self._token
            signature_headers = self._signature()
            headers = {"Access-Key": self.access_key, **signature_headers}
            body = _unwrap(self._request("POST", self.endpoints.token, headers=headers))
            if not isinstance(body, dict):
                raise RuntimeError("Token 接口返回格式不正确")
            token = _value_from(body, "accessToken", "access_token", "token")
            if not token:
                raise RuntimeError("Token 接口未返回 accessToken")
            token_type = str(_value_from(body, "tokenType", "token_type") or "Bearer")
            try:
                expires_in = max(30, int(_value_from(body, "expiresIn", "expires_in") or 3600))
            except (TypeError, ValueError):
                expires_in = 3600
            self._token = str(token)
            self._token_type = token_type
            self._token_expires_at = time.monotonic() + max(15, int(expires_in * 0.8))
            return token_type, self._token

    def probe(self) -> Dict[str, Any]:
        token_type, _ = self.token()
        return {
            "ok": True,
            "provider": "changlian",
            "provider_name": "新畅联",
            "auth": "ok",
            "token_type": token_type,
        }

    def logout(self) -> Any:
        try:
            return self._request("POST", self.endpoints.logout, auth=True)
        finally:
            self._token = ""
            self._token_expires_at = 0.0

    def category_tree(self) -> Any:
        return self._request("GET", self.endpoints.category_tree, auth=True)

    def category_page(
        self,
        *,
        page_num: int,
        page_size: int,
        parent_id: Any = None,
        category_type: Any = None,
        category_code: Any = None,
        category_name: Any = None,
    ) -> Any:
        return self._request(
            "GET",
            self.endpoints.category_list,
            auth=True,
            params=_compact_params({
                "pageNum": page_num,
                "pageSize": page_size,
                "parentId": parent_id,
                "categoryType": category_type,
                "categoryCode": category_code,
                "categoryName": category_name,
            }),
        )

    def category_list_all(
        self,
        *,
        category_type: Any = None,
        category_code: Any = None,
        category_name: Any = None,
        parent_id: Any = None,
    ) -> Any:
        return self._request(
            "GET",
            self.endpoints.category_list_all,
            auth=True,
            params=_compact_params({
                "categoryType": category_type,
                "categoryCode": category_code,
                "categoryName": category_name,
                "parentId": parent_id,
            }),
        )

    def product_page(self, *, page_num: int, page_size: int, **filters: Any) -> Any:
        params = {"pageNum": page_num, "pageSize": page_size, **filters}
        params.setdefault("productType", "3")
        params.setdefault("status", "1")
        return self._request("GET", self.endpoints.product_list_page, auth=True, params=_compact_params(params))

    def products(self, **filters: Any) -> Any:
        params = dict(filters)
        params.setdefault("productType", "3")
        params.setdefault("status", "1")
        return self._request("GET", self.endpoints.product_list, auth=True, params=_compact_params(params))

    def product_info(self, product_id: Any) -> Any:
        path = self.endpoints.product_detail.replace("{productId}", str(product_id))
        return self._request("GET", path, auth=True)

    def analysis_page(self, *, page_num: int, page_size: int, **filters: Any) -> Any:
        params = {"pageNum": page_num, "pageSize": page_size, **filters}
        return self._request("GET", self.endpoints.analysis_list_page, auth=True, params=_compact_params(params))

    def analyses(self, product_id: Any) -> Any:
        path = self.endpoints.analysis_by_product.replace("{productId}", str(product_id))
        return self._request("GET", path, auth=True)

    def analysis_list_all(self, **filters: Any) -> Any:
        return self._request("GET", self.endpoints.analysis_list_all, auth=True, params=_compact_params(filters))

    def analysis_info(self, analysis_id: Any) -> Any:
        path = self.endpoints.analysis_detail.replace("{analysisId}", str(analysis_id))
        return self._request("GET", path, auth=True)

    def compute_platform_page(self, *, page_num: int, page_size: int, **filters: Any) -> Any:
        params = {"pageNum": page_num, "pageSize": page_size, **filters}
        return self._request("GET", self.endpoints.compute_platform_list_page, auth=True, params=_compact_params(params))

    def compute_platforms(self, **filters: Any) -> Any:
        return self._request("GET", self.endpoints.compute_platform_list, auth=True, params=_compact_params(filters))

    def version_create(self, payload: Mapping[str, Any]) -> Any:
        body = _dump_version_payload(payload)
        has_analysis = body.get("analysisId") not in (None, "")
        has_product = body.get("productId") not in (None, "")
        if has_analysis == has_product:
            raise ValueError("新增算法版本时 analysisId 与 productId 必须二选一")
        return self._request("POST", self.endpoints.version_create, auth=True, json=body)

    def version_edit(self, payload: Mapping[str, Any]) -> Any:
        body = _dump_version_payload(payload)
        if body.get("algoVersionId") in (None, ""):
            raise ValueError("修改算法版本必须提供 algoVersionId")
        return self._request("POST", self.endpoints.version_edit, auth=True, json=body)

    def version_remove(self, algo_version_ids: Iterable[Any]) -> Any:
        path = self.endpoints.version_remove.replace("{algoVersionIds}", _remote_path_ids(algo_version_ids))
        return self._request("GET", path, auth=True)

    def version_page(self, *, page_num: int, page_size: int, **filters: Any) -> Any:
        params = {"pageNum": page_num, "pageSize": page_size, **filters}
        return self._request("GET", self.endpoints.version_list_page, auth=True, params=_compact_params(params))

    def version_list_by_product(self, product_id: Any) -> Any:
        path = self.endpoints.version_list_by_product.replace("{productId}", str(product_id))
        return self._request("GET", path, auth=True)

    def version_list_by_analysis(self, analysis_id: Any) -> Any:
        path = self.endpoints.version_list_by_analysis.replace("{analysisId}", str(analysis_id))
        return self._request("GET", path, auth=True)

    def version_list_all(self, **filters: Any) -> Any:
        return self._request("GET", self.endpoints.version_list_all, auth=True, params=_compact_params(filters))

    def version_info(self, algo_version_id: Any) -> Any:
        path = self.endpoints.version_detail.replace("{algoVersionId}", str(algo_version_id))
        return self._request("GET", path, auth=True)

    def weight_create(self, payload: Mapping[str, Any]) -> Any:
        body = _dump_weight_payload(payload)
        if body.get("algoVersionId") in (None, ""):
            raise ValueError("新增算法权重文件必须提供 algoVersionId")
        return self._request("POST", self.endpoints.weight_create, auth=True, json=body)

    def weight_edit(self, payload: Mapping[str, Any]) -> Any:
        body = _dump_weight_payload(payload)
        if body.get("weightId") in (None, ""):
            raise ValueError("修改算法权重文件必须提供 weightId")
        return self._request("POST", self.endpoints.weight_edit, auth=True, json=body)

    def weight_remove(self, weight_ids: Iterable[Any]) -> Any:
        path = self.endpoints.weight_remove.replace("{weightIds}", _remote_path_ids(weight_ids))
        return self._request("GET", path, auth=True)

    def weight_page(self, *, page_num: int, page_size: int, **filters: Any) -> Any:
        params = {"pageNum": page_num, "pageSize": page_size, **filters}
        return self._request("GET", self.endpoints.weight_list_page, auth=True, params=_compact_params(params))

    def weight_list_by_version(self, algo_version_id: Any) -> Any:
        path = self.endpoints.weight_list_by_version.replace("{algoVersionId}", str(algo_version_id))
        return self._request("GET", path, auth=True)

    def weight_list_by_product(
        self,
        product_id: Any,
        *,
        algo_version_id: Any = None,
        compute_platform_id: Any = None,
        compute_platform_code: Any = None,
    ) -> Any:
        path = self.endpoints.weight_list_by_product.replace("{productId}", str(product_id))
        return self._request(
            "GET",
            path,
            auth=True,
            params=_compact_params({
                "algoVersionId": algo_version_id,
                "computePlatformId": compute_platform_id,
                "computePlatformCode": compute_platform_code,
            }),
        )

    def weight_info(self, weight_id: Any) -> Any:
        path = self.endpoints.weight_detail.replace("{weightId}", str(weight_id))
        return self._request("GET", path, auth=True)


def _category_id(row: Mapping[str, Any]) -> str:
    direct = _value_from(row, "categoryId", "category_id")
    if direct:
        return str(direct)
    category = row.get("category")
    if isinstance(category, dict):
        value = _value_from(category, "categoryId", "id")
        return str(value or "")
    return ""


def _product_id(row: Mapping[str, Any]) -> str:
    return str(_value_from(row, "productId", "product_id", "id") or "").strip()


def _analysis_id(row: Mapping[str, Any]) -> str:
    return str(_value_from(row, "analysisId", "analysis_id", "id") or "").strip()


def _compute_platform_id(row: Mapping[str, Any]) -> str:
    return str(_value_from(row, "computePlatformId", "compute_platform_id", "id") or "").strip()


def _algo_version_id(row: Mapping[str, Any]) -> str:
    return str(_value_from(row, "algoVersionId", "algorithmVersionId", "versionId", "id") or "").strip()


def _weight_id(row: Mapping[str, Any]) -> str:
    return str(_value_from(row, "weightId", "algorithmWeightId", "id") or "").strip()


def _validated_external_items(
    value: Any,
    *,
    id_resolver: Callable[[Mapping[str, Any]], str],
    error_code: str,
    entity_name: str,
) -> list[Dict[str, Any]]:
    rows = extract_items(value)
    missing = [index for index, row in enumerate(rows, start=1) if not id_resolver(row)]
    if missing:
        preview = "、".join(str(index) for index in missing[:10])
        suffix = "…" if len(missing) > 10 else ""
        raise PlatformError(
            error_code,
            f"{entity_name}缺少业务 ID",
            f"新畅联返回的{entity_name}记录中，第 {preview}{suffix} 条无法解析正式业务 ID。",
            "请核对新畅联接口字段契约；平台不会静默跳过缺少业务 ID 的主数据。",
            502,
        )
    return rows


def _analysis_name(row: Mapping[str, Any]) -> str:
    return str(_value_from(row, "analysisName", "analysisTypeName", "name", "analysisType") or "").strip()


def _analysis_summary(row: Mapping[str, Any]) -> Dict[str, Any]:
    status_value = _value_from(row, "status")
    return {
        "analysis_id": _analysis_id(row),
        "analysis_name": _analysis_name(row),
        "analysis_type": str(_value_from(row, "analysisType", "analysis_type") or "").strip(),
        "status": "" if status_value is None else str(status_value).strip(),
        "compute_platform_ids": list(row.get("computePlatformIds") or row.get("compute_platform_ids") or []),
    }


def _analysis_is_enabled(row: Mapping[str, Any]) -> bool:
    # Official ChangLian contract is exact: status=1 means enabled.
    # Missing, unknown, false-like, or any other value must fail closed.
    status_value = _value_from(row, "status")
    return status_value is not None and str(status_value).strip() == "1"


def _analysis_is_visual(row: Mapping[str, Any]) -> bool:
    # Official ChangLian contract is exact: analysisType=1 means visual AI.
    # Never infer training eligibility from names such as "视觉"/"vision".
    return str(_value_from(row, "analysisType", "analysis_type") or "").strip() == "1"


def _visual_analysis_rows(rows: Iterable[Mapping[str, Any]]) -> list[Dict[str, Any]]:
    return [
        dict(row)
        for row in rows
        if _analysis_id(row) and _analysis_is_visual(row) and _analysis_is_enabled(row)
    ]


def _choose_analysis(rows: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    values = [dict(row) for row in rows]
    visual = _visual_analysis_rows(values)
    return visual[0] if visual else {}


def _stable_external_id(provider: str, product_id: str) -> str:
    digest = hashlib.sha256(f"{provider}:{product_id}".encode("utf-8")).hexdigest()[:16]
    return f"ext_{provider.lower()}_{digest}"


def master_data_digest(
    *,
    categories: Iterable[Mapping[str, Any]],
    products: Iterable[Mapping[str, Any]],
    analyses_by_product: Mapping[str, Iterable[Mapping[str, Any]]],
    compute_platforms: Iterable[Mapping[str, Any]],
) -> str:
    def stable_rows(rows: Iterable[Mapping[str, Any]], id_resolver: Callable[[Mapping[str, Any]], str]):
        values = [dict(row) for row in rows]
        return sorted(
            values,
            key=lambda row: (
                str(id_resolver(row) or ""),
                json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
            ),
        )

    canonical = {
        "categories": stable_rows(
            categories,
            lambda row: str(_value_from(row, "categoryId", "id") or ""),
        ),
        "products": stable_rows(products, _product_id),
        "analyses_by_product": {
            str(product_id): stable_rows(rows, _analysis_id)
            for product_id, rows in sorted(
                ((str(key), value) for key, value in analyses_by_product.items()),
                key=lambda item: item[0],
            )
        },
        "compute_platforms": stable_rows(compute_platforms, _compute_platform_id),
    }
    encoded = json.dumps(
        canonical,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def mirror_products_to_algorithms(
    *,
    algorithms_path: Path,
    products: Iterable[Mapping[str, Any]],
    categories: Iterable[Mapping[str, Any]],
    analyses_by_product: Mapping[str, Iterable[Mapping[str, Any]]],
    provider: str = PROVIDER_CHANGLIAN,
    synced_at: Optional[str] = None,
    master_digest: str = "",
) -> Dict[str, int]:
    synced_at = synced_at or utc_now()
    algorithms_path = Path(algorithms_path)
    lock = FileLock(str(algorithms_path.resolve()) + ".lock", timeout=30)
    category_names: Dict[str, str] = {}
    for category in categories:
        cid = str(_value_from(category, "categoryId", "id") or "")
        if cid:
            category_names[cid] = str(_value_from(category, "categoryName", "name") or cid)

    incoming: Dict[str, Dict[str, Any]] = {}
    for raw in products:
        product = dict(raw)
        pid = _product_id(product)
        if not pid:
            continue
        analyses = [dict(item) for item in analyses_by_product.get(pid, [])]
        visual_analyses = _visual_analysis_rows(analyses)
        selected_analysis = _choose_analysis(analyses)
        cid = _category_id(product)
        name = str(_value_from(product, "productName", "name", "algorithmName") or pid).strip()
        incoming[pid] = {
            "id": _stable_external_id(provider, pid),
            "name": name,
            "remark": str(_value_from(product, "remark", "description", "productDesc") or ""),
            "industry": category_names.get(cid, str(_value_from(product, "categoryName") or "")),
            "algorithm_type": _analysis_name(selected_analysis) or "外部视觉算法",
            "source_type": SOURCE_EXTERNAL,
            "provider_type": provider,
            "source_name": "新畅联" if provider == PROVIDER_CHANGLIAN else provider,
            "master_data_readonly": True,
            "external_product_id": pid,
            "external_product_code": str(_value_from(product, "productCode", "code") or ""),
            "external_analysis_id": _analysis_id(selected_analysis),
            "external_analysis_ids": [_analysis_id(row) for row in visual_analyses],
            "external_analyses": [_analysis_summary(row) for row in analyses if _analysis_id(row)],
            "external_category_id": cid,
            "external_compute_platform_ids": list(
                selected_analysis.get("computePlatformIds")
                or selected_analysis.get("compute_platform_ids")
                or []
            ),
            "external_active": True,
            "external_last_synced_at": synced_at,
            "external_master_data_digest": str(master_digest or ""),
        }

    return AlgorithmSqlStore(algorithms_path).sync_external_algorithms(incoming, provider=provider, synced_at=synced_at)


def algorithm_is_external_readonly(algorithms_path: Path, algorithm_id: str) -> bool:
    row = next(
        (item for item in list_algorithms(Path(algorithms_path)) if str(item.get("id")) == str(algorithm_id)),
        None,
    )
    return bool(
        row
        and str(row.get("source_type") or "").upper() == SOURCE_EXTERNAL
        and row.get("master_data_readonly") is True
    )


def assert_algorithm_mutable(algorithms_path: Path, algorithm_id: str) -> None:
    if algorithm_is_external_readonly(algorithms_path, algorithm_id):
        raise PlatformError(
            "EXTERNAL_ALGORITHM_READONLY",
            "外部平台算法主数据为只读",
            "该算法来自新畅联，名称、品目和基础属性必须在新畅联维护。",
            "请在新畅联修改后回到“配置中心 → 平台对接”执行同步。",
            409,
        )


def resolve_external_training_analysis(algorithm: Mapping[str, Any] | None, requested_analysis_id: Any = "") -> str:
    if not algorithm:
        return ""
    if str(algorithm.get("source_type") or "").upper() != SOURCE_EXTERNAL:
        return ""
    if str(algorithm.get("provider_type") or "").upper() != PROVIDER_CHANGLIAN:
        return ""
    if algorithm.get("external_active") is False:
        raise PlatformError(
            "EXTERNAL_ALGORITHM_INACTIVE",
            "该外部算法已下架，不能新建训练任务",
            str(algorithm.get("name") or algorithm.get("id") or ""),
            "历史训练和版本仍可查看；如需继续训练，请先在新畅联恢复该算法产品并重新同步。",
            409,
        )
    summaries = [
        row for row in (algorithm.get("external_analyses") or [])
        if isinstance(row, dict) and str(row.get("analysis_id") or "").strip()
    ]
    explicit_visual_ids = [
        str(row.get("analysis_id") or "")
        for row in summaries
        if _analysis_is_visual(row) and _analysis_is_enabled(row)
    ]
    # Training eligibility must be provable from the synced analysis details.
    # external_analysis_ids alone is not sufficient because it does not prove
    # both official conditions (status=1 AND analysisType=1).
    analysis_ids = explicit_visual_ids
    default_id = str(algorithm.get("external_analysis_id") or "").strip()
    if default_id and analysis_ids and default_id not in analysis_ids:
        default_id = ""
    requested = str(requested_analysis_id or "").strip()

    all_analysis_ids = {str(row.get("analysis_id") or "") for row in summaries}
    if requested and requested in all_analysis_ids and requested not in analysis_ids:
        raise PlatformError(
            "EXTERNAL_ANALYSIS_NOT_VISUAL",
            "所选分析方式不是可训练的视觉智能分析",
            requested,
            "YOLO 训练只允许绑定新畅联中 status=1 且 analysisType=1 的分析方式。",
            409,
        )
    if requested and analysis_ids and requested not in analysis_ids:
        raise PlatformError(
            "EXTERNAL_ANALYSIS_INVALID",
            "所选分析方式不属于当前算法产品的可训练视觉分析",
            requested,
            "请刷新新畅联主数据后重新选择分析方式。",
            409,
        )
    if not analysis_ids:
        raise PlatformError(
            "EXTERNAL_VISUAL_ANALYSIS_MISSING",
            "当前算法产品没有可训练的视觉智能分析方式",
            str(algorithm.get("name") or algorithm.get("id") or ""),
            "请在新畅联确认该分析方式同时满足 status=1 且 analysisType=1 后重新同步。",
            409,
        )
    if len(analysis_ids) > 1 and not requested:
        raise PlatformError(
            "EXTERNAL_ANALYSIS_REQUIRED",
            "当前算法存在多个可训练视觉分析方式，请选择本次训练绑定的分析方式",
            str(algorithm.get("name") or algorithm.get("id") or ""),
            "请在创建训练任务时选择具体视觉分析方式。",
            409,
        )
    return requested or default_id or analysis_ids[0]


def assert_external_algorithm_master_data_current(data_dir: Path, algorithm: Mapping[str, Any] | None) -> None:
    if not algorithm:
        return
    if str(algorithm.get("source_type") or "").upper() != SOURCE_EXTERNAL:
        return
    if str(algorithm.get("provider_type") or "").upper() != PROVIDER_CHANGLIAN:
        return
    cache = ExternalPlatformRepository(Path(data_dir)).cache()
    expected = str(cache.get("master_data_digest") or "").strip()
    actual = str(algorithm.get("external_master_data_digest") or "").strip()
    if expected and actual and actual == expected:
        return
    raise PlatformError(
        "EXTERNAL_MASTER_DATA_STALE",
        "当前算法的畅联云主数据需要重新同步",
        str(algorithm.get("name") or algorithm.get("id") or ""),
        "请到“配置中心 → 平台对接”执行“立即同步”，再重新创建训练任务。",
        409,
    )


def assert_local_algorithm_create_allowed(data_dir: Path) -> None:
    config = ExternalPlatformRepository(Path(data_dir)).config()
    if str(config.get("mode") or "local") == "external":
        raise PlatformError(
            "EXTERNAL_MASTER_DATA_ACTIVE",
            "当前算法主数据由外部平台管理",
            "已启用新畅联算法主数据，当前平台不再创建独立算法产品。",
            "请先在新畅联创建算法产品，然后执行“立即同步”。",
            409,
        )


class ExternalAlgorithmPlatformService:
    def __init__(
        self,
        *,
        data_dir: Path,
        secret_store_factory: Callable[[], Any],
        client_factory: Callable[..., ChangLianClient] = ChangLianClient,
    ):
        self.repository = ExternalPlatformRepository(Path(data_dir))
        self.secret_store_factory = secret_store_factory
        self.client_factory = client_factory
        self.audit = IntegrationAuditRepository(Path(data_dir))

    def _credential_store(self) -> SecretCredentialStore:
        return SecretCredentialStore(self.secret_store_factory())

    def _sync_lock(self, project_id: str) -> FileLock:
        digest = hashlib.sha256(str(project_id).encode("utf-8")).hexdigest()[:20]
        return FileLock(str(self.repository.root / f".sync-{digest}.lock"), timeout=0)

    def public_config(self) -> Dict[str, Any]:
        config = self.repository.config()
        ref = str(config.get("credential_ref") or DEFAULT_CONFIG["credential_ref"])
        state = self._credential_store().public_state(ref)
        cache = self.repository.cache()
        history = self.repository.history()
        last = history[0] if history else None
        return {
            "schema_version": config.get("schema_version"),
            "mode": config.get("mode", "local"),
            "provider": config.get("provider", "changlian"),
            "provider_name": "新畅联" if config.get("provider") == "changlian" else config.get("provider"),
            "base_url": config.get("base_url", ""),
            "auto_sync_enabled": bool(config.get("auto_sync_enabled")),
            "auto_sync_interval_seconds": int(config.get("auto_sync_interval_seconds") or DEFAULT_AUTO_SYNC_INTERVAL_SECONDS),
            "auto_publish_enabled": bool(config.get("auto_publish_enabled")),
            "auth_mode": "test_sign_bridge",
            "business_auth_mode": "authorization_bearer",
            "credentials": state,
            "api_documents": changlian_api_documents(),
            "api_document_summary": {
                "total": len(CHANG_LIAN_API_DOCUMENTS),
                "wired": sum(1 for item in CHANG_LIAN_API_DOCUMENTS if item.get("status") == "wired"),
                "documented": sum(1 for item in CHANG_LIAN_API_DOCUMENTS if item.get("status") == "documented"),
                "reference": sum(1 for item in CHANG_LIAN_API_DOCUMENTS if item.get("status") == "reference"),
            },
            "endpoints": config.get("endpoints") or asdict(ChangLianEndpoints()),
            "updated_at": config.get("updated_at"),
            "last_sync": last,
            "cache": {
                "synced_at": cache.get("synced_at"),
                "master_data_digest": cache.get("master_data_digest"),
                "category_count": len(cache.get("categories") or []),
                "product_count": len(cache.get("products") or []),
                "analysis_count": sum(len(rows) for rows in (cache.get("analyses_by_product") or {}).values()),
                "compute_platform_count": len(cache.get("compute_platforms") or []),
            },
        }

    def readiness(self, *, algorithms_path: Optional[Path] = None) -> Dict[str, Any]:
        public = self.public_config()
        cache = self.repository.cache()
        history = self.repository.history()
        last_sync = history[0] if history else {}
        credentials = public.get("credentials") if isinstance(public.get("credentials"), dict) else {}
        categories = list(cache.get("categories") or [])
        products = list(cache.get("products") or [])
        analyses_by_product = cache.get("analyses_by_product") or {}
        compute_platforms = list(cache.get("compute_platforms") or [])
        analysis_count = sum(
            len(rows) for rows in analyses_by_product.values()
            if isinstance(rows, list)
        )
        external_rows: list[Dict[str, Any]] = []
        if algorithms_path is not None:
            try:
                external_rows = [
                    dict(row)
                    for row in list_algorithms(Path(algorithms_path))
                    if str(row.get("provider_type") or "").upper() == PROVIDER_CHANGLIAN
                    and str(row.get("source_type") or "").upper() == SOURCE_EXTERNAL
                ]
            except Exception:
                external_rows = []
        active_external = [row for row in external_rows if row.get("external_active") is not False]
        current_master_digest = str(cache.get("master_data_digest") or "").strip()
        stale_external = [
            row for row in active_external
            if not current_master_digest
            or str(row.get("external_master_data_digest") or "").strip() != current_master_digest
        ]

        checks = [
            {
                "key": "human_login",
                "name": "人员登录账号",
                "status": "not_required",
                "detail": "系统对接不使用人员用户名/密码；内部 API 使用 AccessKey / AccessSecret 应用鉴权。",
            },
            {
                "key": "external_mode",
                "name": "外部平台模式",
                "status": "ready" if public.get("mode") == "external" else "blocked",
                "detail": "已启用新畅联" if public.get("mode") == "external" else "当前仍是本地主数据模式",
            },
            {
                "key": "base_url",
                "name": "API 服务地址",
                "status": "ready" if str(public.get("base_url") or "").strip() else "blocked",
                "detail": str(public.get("base_url") or "") or "尚未配置",
            },
            {
                "key": "credentials",
                "name": "应用凭据",
                "status": "ready" if bool(credentials.get("configured")) else "blocked",
                "detail": (
                    f"已配置 · {credentials.get('backend') or 'secure-store'}"
                    if credentials.get("configured")
                    else ("安全存储不可用" if credentials.get("available") is False else "尚未配置 AccessKey / AccessSecret")
                ),
            },
            {
                "key": "last_sync",
                "name": "最近主数据同步",
                "status": "ready" if last_sync.get("status") == "success" else "blocked",
                "detail": (
                    str(last_sync.get("finished_at") or last_sync.get("started_at") or "")
                    if last_sync.get("status") == "success"
                    else str(last_sync.get("error") or "尚无成功同步记录")
                ),
            },
            {
                "key": "categories",
                "name": "算法品目",
                "status": "ready" if categories else "blocked",
                "count": len(categories),
            },
            {
                "key": "products",
                "name": "算法产品",
                "status": "ready" if products else "blocked",
                "count": len(products),
            },
            {
                "key": "analyses",
                "name": "产品分析方式",
                "status": "ready" if analysis_count else "blocked",
                "count": analysis_count,
            },
            {
                "key": "compute_platforms",
                "name": "算力环境",
                "status": "ready" if compute_platforms else "blocked",
                "count": len(compute_platforms),
            },
        ]
        if algorithms_path is not None:
            checks.append({
                "key": "project_algorithms",
                "name": "当前项目畅联云算法",
                "status": "ready" if active_external and not stale_external else "blocked",
                "count": len(active_external),
                "detail": (
                    f"同步算法 {len(external_rows)} 个，当前可训练 {len(active_external)} 个"
                    if not stale_external
                    else f"有 {len(stale_external)} 个算法仍基于旧主数据，请重新同步当前项目"
                ),
            })

        blocking = [row for row in checks if row.get("status") == "blocked"]
        return {
            "ok": True,
            "ready": not blocking,
            "scope": "master_data_training",
            "provider": "changlian",
            "auth_type": "application_credentials",
            "human_login_required": False,
            "checked_at": utc_now(),
            "checks": checks,
            "blocking_keys": [str(row.get("key") or "") for row in blocking],
        }

    def save(self, payload: ExternalPlatformConfigPayload) -> Dict[str, Any]:
        current = self.repository.config()
        ref = str(current.get("credential_ref") or DEFAULT_CONFIG["credential_ref"])
        credential_store = self._credential_store()
        existing = credential_store.get(ref) or {}
        access_key = str(payload.access_key or "").strip()
        access_secret = str(payload.access_secret or "")
        if access_key or access_secret:
            merged = dict(existing)
            if access_key:
                merged["access_key_id"] = access_key
            if access_secret:
                merged["access_secret"] = access_secret
            if not merged.get("access_key_id") or not merged.get("access_secret"):
                raise PlatformError(
                    "EXTERNAL_PLATFORM_CREDENTIAL_INCOMPLETE",
                    "应用凭据不完整",
                    "AccessKey 和 AccessSecret 必须同时可用。",
                    "请同时填写 AccessKey / AccessSecret；已保存的 Secret 留空时会继续沿用。",
                    422,
                )
            credential_store.set(ref, merged)
        self.repository.save_config(payload.model_dump(exclude={"access_key", "access_secret"}))
        return self.public_config()

    def _client_for_payload(self, payload: Optional[ExternalPlatformConfigPayload] = None) -> ChangLianClient:
        config = self.repository.config()
        provider = str(payload.provider if payload is not None else config.get("provider") or "changlian")
        if provider != "changlian":
            raise PlatformError(
                "EXTERNAL_PLATFORM_PROVIDER_UNSUPPORTED",
                "暂不支持该外部平台",
                provider,
                "当前版本已实现新畅联 Provider；其他平台后续通过 Provider 扩展。",
                422,
            )
        ref = str(config.get("credential_ref") or DEFAULT_CONFIG["credential_ref"])
        stored = self._credential_store().get(ref) or {}
        if payload is None:
            base_url = str(config.get("base_url") or "")
            access_key = str(stored.get("access_key_id") or "")
            access_secret = str(stored.get("access_secret") or "")
            endpoints = ChangLianEndpoints.from_mapping(config.get("endpoints"))
        else:
            # Draft credentials are used only for this request. Blank fields reuse the
            # already-saved credential so the browser never needs to read secrets back.
            base_url = str(payload.base_url or "")
            access_key = str(payload.access_key or "").strip() or str(stored.get("access_key_id") or "")
            access_secret = str(payload.access_secret or "") or str(stored.get("access_secret") or "")
            endpoints = ChangLianEndpoints.from_mapping(payload.endpoints.model_dump())
        return self.client_factory(
            base_url=base_url,
            access_key=access_key,
            access_secret=access_secret,
            endpoints=endpoints,
            audit_callback=self.audit.record,
        )

    def _client(self) -> ChangLianClient:
        return self._client_for_payload()

    def _append_algorithm_readonly_diagnostics(
        self,
        *,
        client: ChangLianClient,
        steps: list[Dict[str, Any]],
        record: Callable[..., Any],
        products: Any,
        empty_detail: str,
    ) -> None:
        product_rows = products if isinstance(products, list) else []
        if not product_rows:
            for key, name in (
                ("analysis", "产品分析方式"),
                ("versions", "算法版本"),
                ("weights", "算法权重"),
            ):
                steps.append({"key": key, "name": name, "status": "skipped", "detail": empty_detail})
            return

        product_id = _product_id(product_rows[0])
        record(
            "analysis",
            "产品分析方式",
            lambda: _validated_external_items(
                client.analyses(product_id),
                id_resolver=_analysis_id,
                error_code="EXTERNAL_ANALYSIS_ID_MISSING",
                entity_name="产品分析方式",
            ),
            count_items=True,
        )
        versions = record(
            "versions",
            "算法版本",
            lambda: _validated_external_items(
                client.version_list_by_product(product_id),
                id_resolver=_algo_version_id,
                error_code="EXTERNAL_ALGO_VERSION_ID_MISSING",
                entity_name="算法版本",
            ),
            count_items=True,
        )
        version_rows = versions if isinstance(versions, list) else []
        if not version_rows:
            steps.append({
                "key": "weights",
                "name": "算法权重",
                "status": "skipped",
                "detail": "当前抽查算法产品下没有算法版本",
            })
            return
        algo_version_id = _algo_version_id(version_rows[0])
        record(
            "weights",
            "算法权重",
            lambda: _validated_external_items(
                client.weight_list_by_version(algo_version_id),
                id_resolver=_weight_id,
                error_code="EXTERNAL_WEIGHT_ID_MISSING",
                entity_name="算法权重文件",
            ),
            count_items=True,
        )

    def test_connection(self, payload: Optional[ExternalPlatformConfigPayload] = None) -> Dict[str, Any]:
        client = self._client_for_payload(payload)
        steps: list[Dict[str, Any]] = []

        def record(key: str, name: str, action: Callable[[], Any], *, count_items: bool = False) -> Any:
            try:
                value = action()
                row: Dict[str, Any] = {"key": key, "name": name, "status": "success"}
                if count_items:
                    row["count"] = len(extract_items(value))
                steps.append(row)
                return value
            except Exception as error:
                steps.append({
                    "key": key,
                    "name": name,
                    "status": "failed",
                    "detail": str(getattr(error, "detail", error))[:500],
                })
                return None

        auth = record("auth", "应用鉴权", client.probe)
        if auth is not None:
            record("categories", "算法品目", lambda: flatten_category_tree(client.category_tree()), count_items=True)
            products = record(
                "products",
                "算法产品",
                lambda: _validated_external_items(
                    client.products(),
                    id_resolver=_product_id,
                    error_code="EXTERNAL_PRODUCT_ID_MISSING",
                    entity_name="算法产品",
                ),
                count_items=True,
            )
            record(
                "compute_platforms",
                "算力环境",
                lambda: _validated_external_items(
                    client.compute_platforms(),
                    id_resolver=_compute_platform_id,
                    error_code="EXTERNAL_COMPUTE_PLATFORM_ID_MISSING",
                    entity_name="算力环境",
                ),
                count_items=True,
            )
            self._append_algorithm_readonly_diagnostics(
                client=client,
                steps=steps,
                record=record,
                products=products,
                empty_detail="当前没有可用于连接测试的算法产品",
            )
        return {
            "ok": bool(steps) and all(row.get("status") in {"success", "skipped"} for row in steps),
            "provider": "changlian",
            "provider_name": "新畅联",
            "base_url": normalize_base_url(payload.base_url if payload is not None else self.repository.config().get("base_url")),
            "auth_mode": "test_sign_bridge",
            "tested_at": utc_now(),
            "steps": steps,
        }

    def diagnose(self, payload: Optional[ExternalPlatformConfigPayload] = None) -> Dict[str, Any]:
        client = self._client_for_payload(payload)
        steps: list[Dict[str, Any]] = []

        def record(key: str, name: str, action: Callable[[], Any], *, count_items: bool = False) -> Any:
            try:
                value = action()
                row: Dict[str, Any] = {"key": key, "name": name, "status": "success"}
                if count_items:
                    row["count"] = len(extract_items(value))
                steps.append(row)
                return value
            except Exception as error:
                steps.append({
                    "key": key,
                    "name": name,
                    "status": "failed",
                    "detail": str(getattr(error, "detail", error))[:500],
                })
                return None

        auth = record("auth", "应用鉴权", client.probe)
        if auth is None:
            return {"ok": False, "provider": "changlian", "auth_mode": "test_sign_bridge", "steps": steps}
        categories = record("categories", "算法品目", lambda: flatten_category_tree(client.category_tree()), count_items=True)
        products = record(
            "products",
            "算法产品",
            lambda: _validated_external_items(
                client.products(),
                id_resolver=_product_id,
                error_code="EXTERNAL_PRODUCT_ID_MISSING",
                entity_name="算法产品",
            ),
            count_items=True,
        )
        record(
            "compute_platforms",
            "算力环境",
            lambda: _validated_external_items(
                client.compute_platforms(),
                id_resolver=_compute_platform_id,
                error_code="EXTERNAL_COMPUTE_PLATFORM_ID_MISSING",
                entity_name="算力环境",
            ),
            count_items=True,
        )
        self._append_algorithm_readonly_diagnostics(
            client=client,
            steps=steps,
            record=record,
            products=products,
            empty_detail="当前没有可用于抽查的算法产品",
        )
        return {
            "ok": all(row.get("status") in {"success", "skipped"} for row in steps),
            "provider": "changlian",
            "auth_mode": "test_sign_bridge",
            "steps": steps,
            "category_sample_available": bool(categories) if isinstance(categories, list) else False,
        }

    def sync(
        self,
        *,
        project_id: str,
        algorithms_path: Path,
        sync_type: Literal["manual", "auto"] = "manual",
    ) -> Dict[str, Any]:
        config = self.repository.config()
        if str(config.get("mode") or "local") != "external":
            raise PlatformError(
                "EXTERNAL_PLATFORM_NOT_ACTIVE",
                "当前未启用外部算法主数据",
                "算法主数据来源仍为“本平台”。",
                "请先切换为“外部平台 / 新畅联”并保存。",
                409,
            )
        sync_lock = self._sync_lock(project_id)
        try:
            sync_lock.acquire(timeout=0)
        except Timeout as error:
            raise PlatformError(
                "EXTERNAL_PLATFORM_SYNC_BUSY",
                "新畅联主数据同步正在进行",
                f"项目 {project_id} 已有同步任务占用。",
                "请等待当前同步完成后再点击“立即同步”。",
                409,
            ) from error
        started_at = utc_now()
        history: Dict[str, Any] = {
            "id": hashlib.sha256(f"{project_id}:{started_at}".encode()).hexdigest()[:16],
            "project_id": project_id,
            "provider": "changlian",
            "sync_type": sync_type,
            "status": "running",
            "started_at": started_at,
        }
        try:
            client = self._client()
            categories = flatten_category_tree(client.category_tree())
            products = _validated_external_items(
                client.products(),
                id_resolver=_product_id,
                error_code="EXTERNAL_PRODUCT_ID_MISSING",
                entity_name="算法产品",
            )
            compute_platforms = _validated_external_items(
                client.compute_platforms(),
                id_resolver=_compute_platform_id,
                error_code="EXTERNAL_COMPUTE_PLATFORM_ID_MISSING",
                entity_name="算力环境",
            )
            analyses_by_product: Dict[str, list[Dict[str, Any]]] = {}
            for product in products:
                pid = _product_id(product)
                analyses_by_product[pid] = _validated_external_items(
                    client.analyses(pid),
                    id_resolver=_analysis_id,
                    error_code="EXTERNAL_ANALYSIS_ID_MISSING",
                    entity_name=f"算法产品 {pid} 的分析方式",
                )
            synced_at = utc_now()
            digest = master_data_digest(
                categories=categories,
                products=products,
                analyses_by_product=analyses_by_product,
                compute_platforms=compute_platforms,
            )
            cache = {
                "schema_version": CACHE_SCHEMA_VERSION,
                "provider": "changlian",
                "synced_at": synced_at,
                "master_data_digest": digest,
                "categories": categories,
                "products": products,
                "analyses_by_product": analyses_by_product,
                "compute_platforms": compute_platforms,
            }
            previous_cache = self.repository.cache()
            self.repository.save_cache(cache)
            try:
                mirror = mirror_products_to_algorithms(
                    algorithms_path=algorithms_path,
                    products=products,
                    categories=categories,
                    analyses_by_product=analyses_by_product,
                    provider=PROVIDER_CHANGLIAN,
                    synced_at=synced_at,
                    master_digest=digest,
                )
            except Exception:
                # Keep cache and project algorithm mirror on the same successful
                # synchronization generation. AlgorithmSqlStore rolls back its
                # SQLite transaction; restore the previous cache before surfacing
                # the failed manual/automatic sync.
                try:
                    self.repository.save_cache(previous_cache)
                except Exception:
                    pass
                raise
            history.update({
                "status": "success",
                "finished_at": utc_now(),
                "counts": {
                    "categories": len(categories),
                    "products": len(products),
                    "analyses": sum(len(rows) for rows in analyses_by_product.values()),
                    "compute_platforms": len(compute_platforms),
                    **mirror,
                },
            })
            self.repository.append_history(history)
            return {"ok": True, "sync": history, "mirror": mirror}
        except Exception as error:
            if isinstance(error, PlatformError):
                message = error.message
                detail = error.detail
            else:
                message = "新畅联同步失败"
                detail = str(error)
            history.update({
                "status": "failed",
                "finished_at": utc_now(),
                "error": message,
                "detail": detail[:1000],
            })
            self.repository.append_history(history)
            if isinstance(error, PlatformError):
                raise
            raise PlatformError(
                "EXTERNAL_PLATFORM_SYNC_FAILED",
                message,
                detail,
                "请先使用“测试连接”检查凭据和接口路径，再重新执行同步。",
                502,
            ) from error
        finally:
            try:
                sync_lock.release()
            except Exception:
                pass


    def auto_sync_due(self, *, now: Optional[datetime] = None) -> bool:
        config = self.repository.config()
        if str(config.get("mode") or "local") != "external":
            return False
        if not bool(config.get("auto_sync_enabled")):
            return False
        if not str(config.get("base_url") or "").strip():
            return False
        interval = max(60, min(86400, int(config.get("auto_sync_interval_seconds") or DEFAULT_AUTO_SYNC_INTERVAL_SECONDS)))
        history = self.repository.history()
        latest = history[0] if history else None
        if not latest:
            return True
        stamp = latest.get("finished_at") or latest.get("started_at")
        if not stamp:
            return True
        try:
            last = datetime.fromisoformat(str(stamp).replace("Z", "+00:00"))
        except ValueError:
            return True
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return (current - last).total_seconds() >= interval


def external_algorithm_platform_router(
    *,
    data_dir: Path,
    get_project: Callable[[str], Any],
    algorithms_file: Callable[[str], Path],
    secret_store_factory: Callable[[], Any],
) -> APIRouter:
    router = APIRouter(prefix="/api/v63/external-algorithm-platform", tags=["external-algorithm-platform"])
    service = ExternalAlgorithmPlatformService(
        data_dir=Path(data_dir),
        secret_store_factory=secret_store_factory,
    )
    auto_sync_lock = FileLock(str(service.repository.root / ".auto-sync-worker.lock"), timeout=0)

    def _auto_sync_projects() -> list[str]:
        projects_path = Path(data_dir) / "projects.json"
        if not projects_path.exists():
            return []
        try:
            rows = json.loads(projects_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(rows, list):
            return []
        result: list[str] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            project_id = str(row.get("id") or "").strip()
            if project_id:
                result.append(project_id)
        return result

    def _auto_sync_once() -> None:
        if not service.auto_sync_due():
            return
        try:
            with auto_sync_lock.acquire(timeout=0):
                if not service.auto_sync_due():
                    return
                for project_id in _auto_sync_projects():
                    try:
                        get_project(project_id)
                        service.sync(
                            project_id=project_id,
                            algorithms_path=algorithms_file(project_id),
                            sync_type="auto",
                        )
                    except Exception:
                        # sync() records provider failures; one project must not stop the worker.
                        continue
        except Timeout:
            return

    def _auto_sync_loop() -> None:
        while True:
            try:
                _auto_sync_once()
            except Exception:
                pass
            time.sleep(30)

    threading.Thread(
        target=_auto_sync_loop,
        name="external-algorithm-platform-auto-sync",
        daemon=True,
    ).start()

    @router.get("/config")
    def get_config():
        return {"ok": True, "config": service.public_config()}

    @router.put("/config")
    def save_config(payload: ExternalPlatformConfigPayload):
        return {"ok": True, "config": service.save(payload)}

    @router.post("/test")
    def test_connection(payload: Optional[ExternalPlatformConfigPayload] = None):
        try:
            result = service.test_connection(payload)
        except PlatformError:
            raise
        except Exception as error:
            raise PlatformError(
                "EXTERNAL_PLATFORM_CONNECTION_FAILED",
                "新畅联连接测试失败",
                str(error),
                "请检查 API 地址、AccessKey / AccessSecret 和鉴权接口路径。",
                502,
            ) from error
        return result

    @router.post("/diagnostics")
    def diagnostics(payload: Optional[ExternalPlatformConfigPayload] = None):
        return service.diagnose(payload)

    @router.post("/provider/logout")
    def provider_logout():
        return {"ok": True, "response": service._client().logout()}

    @router.get("/provider/categories/tree")
    def provider_category_tree():
        return {"ok": True, "response": service._client().category_tree()}

    @router.get("/provider/categories/page")
    def provider_category_page(
        pageNum: int = Query(..., ge=1),
        pageSize: int = Query(..., ge=1, le=500),
        parentId: str = Query(default=""),
        categoryType: str = Query(default=""),
        categoryCode: str = Query(default=""),
        categoryName: str = Query(default=""),
    ):
        return {
            "ok": True,
            "response": service._client().category_page(
                page_num=pageNum,
                page_size=pageSize,
                parent_id=parentId,
                category_type=categoryType,
                category_code=categoryCode,
                category_name=categoryName,
            ),
        }

    @router.get("/provider/categories")
    def provider_category_list_all(
        categoryType: str = Query(default=""),
        categoryCode: str = Query(default=""),
        categoryName: str = Query(default=""),
        parentId: str = Query(default=""),
    ):
        return {
            "ok": True,
            "response": service._client().category_list_all(
                category_type=categoryType,
                category_code=categoryCode,
                category_name=categoryName,
                parent_id=parentId,
            ),
        }

    @router.get("/provider/products/page")
    def provider_product_page(
        request: Request,
        pageNum: int = Query(..., ge=1),
        pageSize: int = Query(..., ge=1, le=500),
    ):
        filters = {key: value for key, value in request.query_params.items() if key not in {"pageNum", "pageSize"}}
        return {"ok": True, "response": service._client().product_page(page_num=pageNum, page_size=pageSize, **filters)}

    @router.get("/provider/products")
    def provider_products(request: Request):
        return {"ok": True, "response": service._client().products(**dict(request.query_params))}

    @router.get("/provider/products/{product_id}")
    def provider_product_info(product_id: str):
        return {"ok": True, "response": service._client().product_info(product_id)}

    @router.get("/provider/analyses/page")
    def provider_analysis_page(
        request: Request,
        pageNum: int = Query(..., ge=1),
        pageSize: int = Query(..., ge=1, le=500),
    ):
        filters = {key: value for key, value in request.query_params.items() if key not in {"pageNum", "pageSize"}}
        return {"ok": True, "response": service._client().analysis_page(page_num=pageNum, page_size=pageSize, **filters)}

    @router.get("/provider/analyses/by-product/{product_id}")
    def provider_analyses_by_product(product_id: str):
        return {"ok": True, "response": service._client().analyses(product_id)}

    @router.get("/provider/analyses")
    def provider_analysis_list_all(request: Request):
        return {"ok": True, "response": service._client().analysis_list_all(**dict(request.query_params))}

    @router.get("/provider/analyses/{analysis_id}")
    def provider_analysis_info(analysis_id: str):
        return {"ok": True, "response": service._client().analysis_info(analysis_id)}

    @router.get("/provider/compute-platforms/page")
    def provider_compute_platform_page(
        request: Request,
        pageNum: int = Query(..., ge=1),
        pageSize: int = Query(..., ge=1, le=500),
    ):
        filters = {key: value for key, value in request.query_params.items() if key not in {"pageNum", "pageSize"}}
        return {"ok": True, "response": service._client().compute_platform_page(page_num=pageNum, page_size=pageSize, **filters)}

    @router.get("/provider/compute-platforms")
    def provider_compute_platforms(request: Request):
        return {"ok": True, "response": service._client().compute_platforms(**dict(request.query_params))}

    @router.get("/provider/versions/page")
    def provider_version_page(
        request: Request,
        pageNum: int = Query(..., ge=1),
        pageSize: int = Query(..., ge=1, le=500),
    ):
        filters = {key: value for key, value in request.query_params.items() if key not in {"pageNum", "pageSize"}}
        return {"ok": True, "response": service._client().version_page(page_num=pageNum, page_size=pageSize, **filters)}

    @router.get("/provider/versions/by-product/{product_id}")
    def provider_versions_by_product(product_id: str):
        return {"ok": True, "response": service._client().version_list_by_product(product_id)}

    @router.get("/provider/versions/by-analysis/{analysis_id}")
    def provider_versions_by_analysis(analysis_id: str):
        return {"ok": True, "response": service._client().version_list_by_analysis(analysis_id)}

    @router.get("/provider/versions")
    def provider_version_list_all(request: Request):
        return {"ok": True, "response": service._client().version_list_all(**dict(request.query_params))}

    @router.post("/provider/versions")
    def provider_version_create(payload: ChangLianVersionMutationPayload):
        return {"ok": True, "response": service._client().version_create(payload.model_dump(exclude_none=True))}

    @router.put("/provider/versions/{algo_version_id}")
    def provider_version_edit(algo_version_id: str, payload: ChangLianVersionMutationPayload):
        body = payload.model_dump(exclude_none=True)
        body["algoVersionId"] = algo_version_id
        return {"ok": True, "response": service._client().version_edit(body)}

    @router.delete("/provider/versions/{algo_version_ids}")
    def provider_version_remove(
        algo_version_ids: str,
        confirm: bool = Query(default=False),
    ):
        if not confirm:
            raise PlatformError(
                "EXTERNAL_REMOTE_DELETE_CONFIRMATION_REQUIRED",
                "删除新畅联算法版本需要显式确认",
                "新畅联会同时删除该版本下全部算法权重文件。",
                "确认已核对远端版本后，使用 confirm=true 重新提交删除。",
                409,
            )
        ids = [value.strip() for value in algo_version_ids.split(",") if value.strip()]
        return {"ok": True, "response": service._client().version_remove(ids)}

    @router.get("/provider/versions/{algo_version_id}")
    def provider_version_info(algo_version_id: str):
        return {"ok": True, "response": service._client().version_info(algo_version_id)}

    @router.get("/provider/weights/page")
    def provider_weight_page(
        request: Request,
        pageNum: int = Query(..., ge=1),
        pageSize: int = Query(..., ge=1, le=500),
    ):
        filters = {key: value for key, value in request.query_params.items() if key not in {"pageNum", "pageSize"}}
        return {"ok": True, "response": service._client().weight_page(page_num=pageNum, page_size=pageSize, **filters)}

    @router.get("/provider/weights/by-version/{algo_version_id}")
    def provider_weights_by_version(algo_version_id: str):
        return {"ok": True, "response": service._client().weight_list_by_version(algo_version_id)}

    @router.get("/provider/weights/by-product/{product_id}")
    def provider_weights_by_product(
        product_id: str,
        algoVersionId: str = Query(default=""),
        computePlatformId: str = Query(default=""),
        computePlatformCode: str = Query(default=""),
    ):
        return {
            "ok": True,
            "response": service._client().weight_list_by_product(
                product_id,
                algo_version_id=algoVersionId,
                compute_platform_id=computePlatformId,
                compute_platform_code=computePlatformCode,
            ),
        }

    @router.post("/provider/weights")
    def provider_weight_create(payload: ChangLianWeightMutationPayload):
        return {"ok": True, "response": service._client().weight_create(payload.model_dump(exclude_none=True))}

    @router.put("/provider/weights/{weight_id}")
    def provider_weight_edit(weight_id: str, payload: ChangLianWeightMutationPayload):
        body = payload.model_dump(exclude_none=True)
        body["weightId"] = weight_id
        return {"ok": True, "response": service._client().weight_edit(body)}

    @router.delete("/provider/weights/{weight_ids}")
    def provider_weight_remove(
        weight_ids: str,
        confirm: bool = Query(default=False),
    ):
        if not confirm:
            raise PlatformError(
                "EXTERNAL_REMOTE_DELETE_CONFIRMATION_REQUIRED",
                "删除新畅联算法权重需要显式确认",
                str(weight_ids),
                "确认已核对远端权重后，使用 confirm=true 重新提交删除。",
                409,
            )
        ids = [value.strip() for value in weight_ids.split(",") if value.strip()]
        return {"ok": True, "response": service._client().weight_remove(ids)}

    @router.get("/provider/weights/{weight_id}")
    def provider_weight_info(weight_id: str):
        return {"ok": True, "response": service._client().weight_info(weight_id)}

    @router.get("/readiness")
    def readiness(project_id: str = Query(..., min_length=1)):
        get_project(project_id)
        return service.readiness(algorithms_path=algorithms_file(project_id))

    @router.post("/sync")
    def sync(project_id: str = Query(..., min_length=1)):
        get_project(project_id)
        return service.sync(project_id=project_id, algorithms_path=algorithms_file(project_id), sync_type="manual")

    @router.get("/sync-history")
    def sync_history(limit: int = Query(default=20, ge=1, le=100)):
        return {"ok": True, "items": service.repository.history()[:limit]}

    @router.get("/interaction-logs/summary")
    def interaction_log_summary(hours: int = Query(default=24, ge=1, le=720)):
        return {"ok": True, "summary": service.audit.summary(provider="changlian", hours=hours)}

    @router.get("/interaction-logs")
    def interaction_logs(
        status: str = Query(default=""), operation: str = Query(default=""),
        project_id: str = Query(default=""), limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ):
        return {
            "ok": True,
            "items": service.audit.list(
                provider="changlian", status=status, operation=operation, project_id=project_id,
                limit=limit, offset=offset,
            ),
        }

    @router.get("/interaction-logs/{log_id}")
    def interaction_log_detail(log_id: str):
        item = service.audit.get(log_id)
        if item is None:
            raise PlatformError("INTERACTION_LOG_NOT_FOUND", "交互日志不存在", log_id, "请刷新日志列表。", 404)
        return {"ok": True, "item": item}

    @router.get("/cache")
    def cache():
        current = service.repository.cache()
        return {
            "ok": True,
            "cache": {
                "provider": current.get("provider"),
                "synced_at": current.get("synced_at"),
                "categories": current.get("categories") or [],
                "products": current.get("products") or [],
                "analyses_by_product": current.get("analyses_by_product") or {},
                "compute_platforms": current.get("compute_platforms") or [],
            },
        }

    return router
