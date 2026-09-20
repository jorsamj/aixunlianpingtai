from __future__ import annotations

import hashlib
import json
import mimetypes
import re
import sqlite3
import threading
import time
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Literal, Mapping, Optional

from fastapi import APIRouter, Query
from fastapi.responses import RedirectResponse, StreamingResponse
from filelock import FileLock, Timeout
from pydantic import BaseModel, Field

from .algorithms import list_algorithms, update_algorithm_version
from .errors import PlatformError
from .integration_audit import IntegrationAuditRepository
from .model_artifacts import ModelArtifactConfigPayload, ModelArtifactService, StorageTestPayload
from .external_algorithm_platform import (
    DEFAULT_CONFIG as EXTERNAL_PLATFORM_DEFAULT_CONFIG,
    PROVIDER_CHANGLIAN,
    SOURCE_EXTERNAL,
    ChangLianClient,
    ChangLianEndpoints,
    ExternalPlatformRepository,
    assert_external_algorithm_master_data_current,
    extract_items,
)
from .secrets import SecretCredentialStore
from .storage import StorageProviderFactory, StorageSourceRepository


PUBLICATION_SCHEMA_VERSION = 2
DEFAULT_AUTO_PUBLISH_RETRY_SECONDS = 300
SUCCESSFUL_VERSION_STATUSES = {"SUCCEEDED", "PARTIAL_SUCCESS", "DONE", "FINISHED", "COMPLETED"}
ACTIVE_CONVERSION_STATUSES = {"queued", "running", "waiting", "pending", "cancel_requested"}
SUCCESSFUL_CONVERSION_STATUSES = {"done", "finished", "completed", "success", "succeeded", "partial_success"}
TARGET_KEYS = ("onnx", "tensorrt", "ascend", "rockchip", "sophon", "paddle_inference", "original")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _safe_segment(value: Any, fallback: str = "item") -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return (text or fallback)[:120]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _remote_data(body: Any) -> Any:
    if not isinstance(body, dict):
        return body
    code = body.get("code")
    success = body.get("success")
    if success is False or (code is not None and str(code) not in {"0", "200", "SUCCESS", "success"}):
        raise RuntimeError(str(body.get("message") or body.get("msg") or body.get("reason") or "新畅联返回失败"))
    if "data" in body:
        return body["data"]
    if "result" in body:
        return body["result"]
    return body


def _remote_id(body: Any, keys: Iterable[str]) -> str:
    value = _remote_data(body)
    if isinstance(value, dict):
        for key in keys:
            current = value.get(key)
            if current not in (None, ""):
                return str(current)
        return ""
    if value not in (None, "") and isinstance(value, (str, int)):
        return str(value)
    return ""


def _status_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _canonical_chip_code(value: Any) -> str:
    text = str(value or "").strip()
    compact = re.sub(r"[^A-Za-z0-9]+", "", text).upper()
    if compact == "RK3568":
        return "RK3568"
    if compact == "RK3576":
        return "RK3576"
    return text


_DELIVERABLE_SUFFIXES: Dict[str, frozenset[str]] = {
    "onnx": frozenset({".onnx"}),
    "rockchip": frozenset({".rknn"}),
    "tensorrt": frozenset({".engine"}),
    "sophon": frozenset({".bmodel"}),
    "ascend": frozenset({".om"}),
}


def _is_publishable_conversion_output(target: Any, path: Path) -> bool:
    """Exclude conversion intermediates/metadata from ChangLian weight registration."""
    normalized = str(target or "").strip().lower()
    candidate = Path(path)
    if candidate.name.lower() == "manifest.json":
        return False
    suffixes = _DELIVERABLE_SUFFIXES.get(normalized)
    if suffixes is None:
        # Preserve legacy multi-file targets (for example Paddle inference)
        # while still excluding the platform manifest metadata.
        return True
    return candidate.suffix.lower() in suffixes


class TargetMapping(BaseModel):
    compute_platform_id: str = ""
    chip_code: str = ""
    enabled: bool = True


LEGACY_PUBLISH_ENDPOINTS = {
    "/algorithm-version/listByProduct/{productId}": "/internal/algorithm/algorithm-version/listByProduct/{productId}",
    "/algorithm-weight/listByVersion/{algoVersionId}": "/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}",
}


def _canonical_publish_endpoint(value: Any, fallback: str) -> str:
    path = str(value or fallback).strip()
    if path and not path.startswith("/"):
        path = "/" + path
    return LEGACY_PUBLISH_ENDPOINTS.get(path, path)


class ExternalPublishConfigPayload(BaseModel):
    storage_source_id: str = ""
    public_base_url: str = ""
    publish_original_model: bool = True
    target_mappings: Dict[str, TargetMapping] = Field(default_factory=dict)
    version_list_by_product: str = "/internal/algorithm/algorithm-version/listByProduct/{productId}"
    weight_list_by_version: str = "/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}"


DEFAULT_PUBLISH_CONFIG: Dict[str, Any] = {
    "schema_version": PUBLICATION_SCHEMA_VERSION,
    "storage_source_id": "",
    "public_base_url": "",
    "publish_original_model": True,
    "target_mappings": {key: {"compute_platform_id": "", "chip_code": "", "enabled": True} for key in TARGET_KEYS},
    "version_list_by_product": "/internal/algorithm/algorithm-version/listByProduct/{productId}",
    "weight_list_by_version": "/internal/algorithm/algorithm-weight/listByVersion/{algoVersionId}",
    "updated_at": None,
}


_SCHEMA = """
CREATE TABLE IF NOT EXISTS external_version_publications (
    publication_key TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    algorithm_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    external_product_id TEXT NOT NULL,
    external_analysis_id TEXT NOT NULL DEFAULT '',
    version_name TEXT NOT NULL,
    external_algo_version_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'PENDING',
    last_error TEXT NOT NULL DEFAULT '',
    attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    published_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_external_publication_project_version
ON external_version_publications(project_id, algorithm_id, version_id);

CREATE TABLE IF NOT EXISTS external_model_artifacts (
    artifact_id TEXT PRIMARY KEY,
    publication_key TEXT NOT NULL,
    project_id TEXT NOT NULL,
    algorithm_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    target TEXT NOT NULL,
    file_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    source_sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    compute_platform_id TEXT NOT NULL DEFAULT '',
    chip_code TEXT NOT NULL DEFAULT '',
    storage_source_id TEXT NOT NULL DEFAULT '',
    object_key TEXT NOT NULL DEFAULT '',
    public_url TEXT NOT NULL DEFAULT '',
    upload_status TEXT NOT NULL DEFAULT 'PENDING',
    external_weight_id TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'PENDING',
    last_error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(publication_key) REFERENCES external_version_publications(publication_key) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS ix_external_artifacts_publication
ON external_model_artifacts(publication_key, target, file_name);
"""


class ExternalPublicationRepository:
    def __init__(self, data_dir: Path):
        self.root = Path(data_dir) / "external_algorithm_publish"
        self.root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.root / "config.json"
        self.db_path = self.root / "publications.sqlite3"
        self.lock = FileLock(str(self.root / ".config.lock"), timeout=30)
        with closing(self._connect()) as database:
            database.executescript(_SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA foreign_keys=ON")
        database.execute("PRAGMA busy_timeout=5000")
        return database

    def config(self) -> Dict[str, Any]:
        with self.lock:
            stored = _json_load(self.config_path, {})
        result = json.loads(json.dumps(DEFAULT_PUBLISH_CONFIG))
        if isinstance(stored, dict):
            result.update({key: value for key, value in stored.items() if key != "target_mappings"})
            # Provider paths are official contract, not user configuration.
            # Ignore both legacy and arbitrary stored overrides on read.
            result["version_list_by_product"] = ChangLianEndpoints.version_list_by_product
            result["weight_list_by_version"] = ChangLianEndpoints.weight_list_by_version
            mappings = result["target_mappings"]
            for key, value in (stored.get("target_mappings") or {}).items():
                if isinstance(value, dict):
                    mappings[str(key)] = {**mappings.get(str(key), {}), **value}
        # Training output delivery is mandatory: the original trained model is
        # always included in the ChangLian delivery chain.
        result["publish_original_model"] = True
        result.setdefault("target_mappings", {}).setdefault("original", {})["enabled"] = True
        return result

    def save_config(self, payload: ExternalPublishConfigPayload) -> Dict[str, Any]:
        body = payload.model_dump()
        body["schema_version"] = PUBLICATION_SCHEMA_VERSION
        body["public_base_url"] = str(body.get("public_base_url") or "").strip().rstrip("/")
        body["storage_source_id"] = str(body.get("storage_source_id") or "").strip()
        body["publish_original_model"] = True
        mappings = body.setdefault("target_mappings", {})
        original = dict(mappings.get("original") or {})
        original["enabled"] = True
        mappings["original"] = original
        body["version_list_by_product"] = ChangLianEndpoints.version_list_by_product
        body["weight_list_by_version"] = ChangLianEndpoints.weight_list_by_version
        body["updated_at"] = utc_now()
        with self.lock:
            temp = self.config_path.with_suffix(".tmp")
            temp.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.config_path)
        return self.config()

    @staticmethod
    def publication_key(project_id: str, algorithm_id: str, version_id: str) -> str:
        return hashlib.sha256(f"{project_id}:{algorithm_id}:{version_id}".encode("utf-8")).hexdigest()[:32]

    def publication(self, project_id: str, algorithm_id: str, version_id: str) -> Dict[str, Any] | None:
        key = self.publication_key(project_id, algorithm_id, version_id)
        with closing(self._connect()) as database:
            row = database.execute("SELECT * FROM external_version_publications WHERE publication_key = ?", (key,)).fetchone()
        return dict(row) if row else None

    def ensure_publication(self, *, project_id: str, algorithm: Mapping[str, Any], version: Mapping[str, Any]) -> Dict[str, Any]:
        key = self.publication_key(project_id, str(algorithm.get("id") or ""), str(version.get("id") or ""))
        stamp = utc_now()
        with closing(self._connect()) as database:
            database.execute(
                """
                INSERT INTO external_version_publications
                (publication_key, project_id, algorithm_id, version_id, external_product_id, external_analysis_id,
                 version_name, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
                ON CONFLICT(publication_key) DO UPDATE SET
                    external_product_id=excluded.external_product_id,
                    external_analysis_id=excluded.external_analysis_id,
                    version_name=excluded.version_name,
                    updated_at=excluded.updated_at
                """,
                (
                    key, project_id, str(algorithm.get("id") or ""), str(version.get("id") or ""),
                    str(algorithm.get("external_product_id") or ""), str(version.get("external_analysis_id") or algorithm.get("external_analysis_id") or ""),
                    str(version.get("version_name") or version.get("id") or ""), stamp, stamp,
                ),
            )
        return self.publication(project_id, str(algorithm.get("id") or ""), str(version.get("id") or "")) or {}

    def patch_publication(self, publication_key: str, **changes: Any) -> Dict[str, Any]:
        allowed = {"external_algo_version_id", "status", "last_error", "attempts", "updated_at", "published_at"}
        values = {key: value for key, value in changes.items() if key in allowed}
        values.setdefault("updated_at", utc_now())
        if not values:
            raise ValueError("no publication changes")
        sql = "UPDATE external_version_publications SET " + ", ".join(f"{key} = ?" for key in values) + " WHERE publication_key = ?"
        with closing(self._connect()) as database:
            database.execute(sql, (*values.values(), publication_key))
            row = database.execute("SELECT * FROM external_version_publications WHERE publication_key = ?", (publication_key,)).fetchone()
        if not row:
            raise KeyError(publication_key)
        return dict(row)

    def artifact(self, artifact_id: str) -> Dict[str, Any] | None:
        with closing(self._connect()) as database:
            row = database.execute("SELECT * FROM external_model_artifacts WHERE artifact_id = ?", (str(artifact_id),)).fetchone()
        return dict(row) if row else None

    def artifacts(self, publication_key: str) -> list[Dict[str, Any]]:
        with closing(self._connect()) as database:
            rows = database.execute(
                "SELECT * FROM external_model_artifacts WHERE publication_key = ? ORDER BY target, file_name",
                (publication_key,),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_artifact(self, publication_key: str, discovered: Mapping[str, Any], mapping: Mapping[str, Any]) -> Dict[str, Any]:
        artifact_id = str(discovered["artifact_id"])
        stamp = utc_now()
        with closing(self._connect()) as database:
            database.execute(
                """
                INSERT INTO external_model_artifacts
                (artifact_id, publication_key, project_id, algorithm_id, version_id, target, file_name,
                 source_path, source_sha256, size_bytes, compute_platform_id, chip_code, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    source_path=excluded.source_path,
                    source_sha256=excluded.source_sha256,
                    size_bytes=excluded.size_bytes,
                    compute_platform_id=excluded.compute_platform_id,
                    chip_code=excluded.chip_code,
                    updated_at=excluded.updated_at
                """,
                (
                    artifact_id, publication_key, str(discovered["project_id"]), str(discovered["algorithm_id"]),
                    str(discovered["version_id"]), str(discovered["target"]), str(discovered["file_name"]),
                    str(discovered["source_path"]), str(discovered["sha256"]), int(discovered["size_bytes"]),
                    str(mapping.get("compute_platform_id") or ""), _canonical_chip_code(discovered.get("chip_code") or mapping.get("chip_code") or ""),
                    stamp, stamp,
                ),
            )
        return self.artifact(artifact_id) or {}

    def patch_artifact(self, artifact_id: str, **changes: Any) -> Dict[str, Any]:
        allowed = {
            "storage_source_id", "object_key", "public_url", "upload_status", "external_weight_id",
            "sync_status", "last_error", "compute_platform_id", "chip_code", "updated_at",
        }
        values = {key: value for key, value in changes.items() if key in allowed}
        values.setdefault("updated_at", utc_now())
        sql = "UPDATE external_model_artifacts SET " + ", ".join(f"{key} = ?" for key in values) + " WHERE artifact_id = ?"
        with closing(self._connect()) as database:
            database.execute(sql, (*values.values(), artifact_id))
        row = self.artifact(artifact_id)
        if not row:
            raise KeyError(artifact_id)
        return row

    def auto_retry_due(self, publication: Mapping[str, Any]) -> bool:
        status = str(publication.get("status") or "PENDING").upper()
        if status in {"PUBLISHED", "UNKNOWN"}:
            return False
        if status not in {"FAILED", "PARTIAL"}:
            return True
        last = _status_time(str(publication.get("updated_at") or ""))
        return not last or (datetime.now(timezone.utc) - last).total_seconds() >= DEFAULT_AUTO_PUBLISH_RETRY_SECONDS


class PublishingChangLianClient(ChangLianClient):
    """Publishing facade pinned to the official ChangLian version/weight contracts."""

    def create_algorithm_version(self, payload: Mapping[str, Any]) -> Any:
        return self.version_create(payload)

    def list_product_versions(self, product_id: Any) -> Any:
        return self.version_list_by_product(product_id)

    def create_weight(self, payload: Mapping[str, Any]) -> Any:
        return self.weight_create(payload)

    def list_version_weights(self, algo_version_id: Any) -> Any:
        return self.weight_list_by_version(algo_version_id)


class ExternalAlgorithmPublishService:
    def __init__(
        self,
        *,
        data_dir: Path,
        project_dir: Callable[[str], Path],
        algorithms_file: Callable[[str], Path],
        external_secret_store_factory: Callable[[], Any],
        storage_sources_factory: Callable[[], StorageSourceRepository],
        storage_credentials_factory: Callable[[], SecretCredentialStore],
        client_factory: Callable[..., PublishingChangLianClient] = PublishingChangLianClient,
    ):
        self.data_dir = Path(data_dir)
        self.project_dir = project_dir
        self.algorithms_file = algorithms_file
        self.external_secret_store_factory = external_secret_store_factory
        self.storage_sources_factory = storage_sources_factory
        self.storage_credentials_factory = storage_credentials_factory
        self.client_factory = client_factory
        self.repository = ExternalPublicationRepository(self.data_dir)
        self.external_repository = ExternalPlatformRepository(self.data_dir)
        self.audit = IntegrationAuditRepository(self.data_dir)
        self.model_assets = ModelArtifactService(
            data_dir=self.data_dir, project_dir=self.project_dir, algorithms_file=self.algorithms_file,
            storage_sources_factory=self.storage_sources_factory,
            storage_credentials_factory=self.storage_credentials_factory,
        )
        legacy_publish = self.repository.config()
        asset_config = self.model_assets.repository.config()
        legacy_source = str(legacy_publish.get("storage_source_id") or "")
        legacy_public_url = str(legacy_publish.get("public_base_url") or "")
        if (
            (not str(asset_config.get("storage_source_id") or "") and legacy_source)
            or (not str(asset_config.get("public_base_url") or "") and legacy_public_url)
        ):
            self.model_assets.save_config(ModelArtifactConfigPayload(
                storage_source_id=str(asset_config.get("storage_source_id") or legacy_source),
                object_prefix=str(asset_config.get("object_prefix") or "model-assets"),
                public_base_url=str(asset_config.get("public_base_url") or legacy_public_url),
                auto_upload_enabled=bool(asset_config.get("auto_upload_enabled", True)),
            ))

    def public_config(self) -> Dict[str, Any]:
        config = self.repository.config()
        sources = []
        credential_store = self.storage_credentials_factory()
        for source in self.storage_sources_factory().list():
            state = credential_store.public_state(source.secret_ref) if source.secret_ref else {"configured": False, "masked": ""}
            sources.append(source.to_public_dict(
                secret_configured=bool(state.get("configured")),
                secret_masked=str(state.get("masked") or ""),
            ))
        external_cache = self.external_repository.cache()
        return {
            "config": config,
            "storage_sources": sources,
            "compute_platforms": external_cache.get("compute_platforms") or [],
        }

    def _current_compute_platform_ids(self) -> set[str]:
        rows = self.external_repository.cache().get("compute_platforms") or []
        result: set[str] = set()
        for row in rows:
            if not isinstance(row, Mapping):
                continue
            value = str(
                row.get("computePlatformId")
                or row.get("compute_platform_id")
                or row.get("id")
                or ""
            ).strip()
            if value:
                result.add(value)
        return result

    def _assert_current_compute_platform(self, compute_platform_id: Any, *, target: str = "") -> str:
        value = str(compute_platform_id or "").strip()
        if not value:
            return ""
        current = self._current_compute_platform_ids()
        if not current:
            raise PlatformError(
                "EXTERNAL_COMPUTE_PLATFORM_CACHE_REQUIRED",
                "尚未同步畅联云算力环境",
                f"转换目标 {target or '-'} 配置了算力环境 {value}，但本平台没有可校验的最新算力环境主数据。",
                "请先在“配置中心 → 平台对接”执行“立即同步”，再重新选择算力环境。",
                409,
            )
        if value not in current:
            raise PlatformError(
                "EXTERNAL_COMPUTE_PLATFORM_MAPPING_STALE",
                "畅联云算力环境映射已失效",
                f"转换目标 {target or '-'} 当前映射的 computePlatformId={value} 已不在最近一次同步的算力环境中。",
                "请先重新同步畅联云主数据，然后重新选择该转换目标对应的算力环境。",
                409,
            )
        return value

    def save_config(self, payload: ExternalPublishConfigPayload) -> Dict[str, Any]:
        source_id = str(payload.storage_source_id or "").strip()
        if source_id and self.storage_sources_factory().get(source_id) is None:
            raise PlatformError(
                "ARTIFACT_STORAGE_SOURCE_NOT_FOUND", "模型发布存储源不存在", source_id,
                "请在存储源配置中创建或恢复该存储源。", 404,
            )
        if payload.public_base_url and not str(payload.public_base_url).startswith(("http://", "https://")):
            raise PlatformError(
                "ARTIFACT_PUBLIC_URL_INVALID", "模型下载服务地址格式不正确", str(payload.public_base_url),
                "请填写以 http:// 或 https:// 开头的本平台外部访问地址。", 422,
            )
        for target, mapping in payload.target_mappings.items():
            if mapping.enabled and str(mapping.compute_platform_id or "").strip():
                self._assert_current_compute_platform(mapping.compute_platform_id, target=str(target))
        saved = self.repository.save_config(payload)
        # Legacy migration only: model-asset storage is the canonical owner.
        # Never overwrite an explicit current model-asset storage choice with a
        # stale external-publish storage_source_id.
        current = self.model_assets.repository.config()
        current_source_id = str(current.get("storage_source_id") or "").strip()
        current_public_url = str(current.get("public_base_url") or "").strip()
        legacy_public_url = str(payload.public_base_url or "").strip()
        if (source_id and not current_source_id) or (legacy_public_url and not current_public_url):
            self.model_assets.save_config(ModelArtifactConfigPayload(
                storage_source_id=current_source_id or source_id,
                object_prefix=str(current.get("object_prefix") or "model-assets"),
                public_base_url=current_public_url or legacy_public_url,
                auto_upload_enabled=bool(current.get("auto_upload_enabled", True)),
            ))
        return saved

    def _external_client(self) -> PublishingChangLianClient:
        config = self.external_repository.config()
        if str(config.get("mode") or "local") != "external" or str(config.get("provider") or "") != "changlian":
            raise PlatformError(
                "EXTERNAL_PLATFORM_NOT_ACTIVE", "当前未启用新畅联主数据", "外部平台配置未处于新畅联模式。",
                "请先在“配置中心 → 平台对接”启用并同步新畅联。", 409,
            )
        ref = str(config.get("credential_ref") or EXTERNAL_PLATFORM_DEFAULT_CONFIG["credential_ref"])
        credentials = SecretCredentialStore(self.external_secret_store_factory()).get(ref) or {}
        return self.client_factory(
            base_url=str(config.get("base_url") or ""),
            access_key=str(credentials.get("access_key_id") or ""),
            access_secret=str(credentials.get("access_secret") or ""),
            endpoints=ChangLianEndpoints.from_mapping(config.get("endpoints")),
            audit_callback=self.audit.record,
        )

    def _provider(self, project_id: str, source_id: str):
        source = self.storage_sources_factory().get(source_id)
        if source is None:
            raise PlatformError(
                "ARTIFACT_STORAGE_SOURCE_NOT_FOUND", "模型发布存储源不存在", source_id,
                "请重新选择模型发布存储源。", 404,
            )
        secret: Mapping[str, str] = {}
        if source.secret_ref:
            secret = self.storage_credentials_factory().get(source.secret_ref) or {}
        return StorageProviderFactory(
            data_dir=self.data_dir,
            project_dir=self.project_dir(project_id),
            credentials={source.id: secret},
        ).create(source)

    def _algorithm_version(self, project_id: str, algorithm_id: str, version_id: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
        algorithms = list_algorithms(self.algorithms_file(project_id))
        algorithm = next((row for row in algorithms if str(row.get("id") or "") == str(algorithm_id)), None)
        if algorithm is None:
            raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", algorithm_id, "请刷新算法列表。", 404)
        if str(algorithm.get("source_type") or "").upper() != SOURCE_EXTERNAL or str(algorithm.get("provider_type") or "").upper() != PROVIDER_CHANGLIAN:
            raise PlatformError(
                "ALGORITHM_NOT_EXTERNAL", "当前算法不是新畅联算法", str(algorithm.get("name") or algorithm_id),
                "只有来源为新畅联的算法版本可以同步到新畅联。", 409,
            )
        version = next((row for row in algorithm.get("versions") or [] if str(row.get("id") or "") == str(version_id)), None)
        if version is None:
            raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", version_id, "请刷新算法列表。", 404)
        return dict(algorithm), dict(version)

    def _assert_current_external_identity(
        self,
        algorithm: Mapping[str, Any],
        version: Mapping[str, Any],
    ) -> None:
        if algorithm.get("external_active") is False:
            raise PlatformError(
                "EXTERNAL_ALGORITHM_INACTIVE",
                "该畅联云算法已下架，不能发布新版本",
                str(algorithm.get("name") or algorithm.get("id") or ""),
                "请先在新畅联恢复该算法产品并执行“立即同步”；历史训练成果仍会保留。",
                409,
            )
        assert_external_algorithm_master_data_current(self.data_dir, algorithm)
        version_analysis_id = str(
            version.get("external_analysis_id")
            or algorithm.get("external_analysis_id")
            or ""
        ).strip()
        current_analysis_ids = self._algorithm_analysis_ids(algorithm)
        if version_analysis_id and current_analysis_ids and version_analysis_id not in current_analysis_ids:
            raise PlatformError(
                "EXTERNAL_VERSION_ANALYSIS_STALE",
                "该训练版本绑定的畅联云分析方式已失效",
                version_analysis_id,
                "请先在“配置中心 → 平台对接”执行“立即同步”并核对分析方式；平台不会把该版本发布到其他分析方式。",
                409,
            )

    def _external_identity_state(
        self,
        algorithm: Mapping[str, Any],
        version: Mapping[str, Any],
    ) -> Dict[str, Any]:
        try:
            self._assert_current_external_identity(algorithm, version)
            return {"ready": True, "issues": []}
        except PlatformError as error:
            return {
                "ready": False,
                "issues": [{
                    "code": str(getattr(error, "code", "") or "EXTERNAL_IDENTITY_NOT_READY"),
                    "message": str(getattr(error, "message", "") or error),
                    "detail": str(getattr(error, "detail", "") or ""),
                    "solution": str(getattr(error, "solution", "") or ""),
                }],
            }

    def _conversion_jobs(self, project_id: str, algorithm_id: str, version_id: str) -> list[Dict[str, Any]]:
        root = self.project_dir(project_id) / "deployment" / "jobs"
        rows: list[Dict[str, Any]] = []
        for job_file in root.glob("*/job.json") if root.exists() else ():
            job = _json_load(job_file, {})
            if not isinstance(job, dict):
                continue
            source = job.get("source_meta") or {}
            trace = job.get("source_trace") or {}
            exact = (
                (str(source.get("algorithm_id") or "") == str(algorithm_id) and str(source.get("version_id") or "") == str(version_id))
                or (str(trace.get("algorithm_id") or "") == str(algorithm_id) and str(trace.get("version_id") or "") == str(version_id))
                or str(job.get("source_id") or "") == f"version::{algorithm_id}::{version_id}"
            )
            if exact:
                rows.append(job)
        return rows

    def conversion_active(self, project_id: str, algorithm_id: str, version_id: str) -> bool:
        return any(str(job.get("status") or "").strip().lower() in ACTIVE_CONVERSION_STATUSES for job in self._conversion_jobs(project_id, algorithm_id, version_id))

    def discover_artifacts(self, project_id: str, algorithm: Mapping[str, Any], version: Mapping[str, Any]) -> list[Dict[str, Any]]:
        algorithm_id = str(algorithm.get("id") or "")
        version_id = str(version.get("id") or "")
        config = self.repository.config()
        candidates: list[tuple[str, Path, str]] = []
        if bool(config.get("publish_original_model")):
            raw = next((str(version.get(key) or "").strip() for key in ("stored_path", "best_path", "last_path", "path") if str(version.get(key) or "").strip()), "")
            if raw:
                candidates.append(("original", Path(raw).expanduser(), ""))
        for job in self._conversion_jobs(project_id, algorithm_id, version_id):
            status = str(job.get("status") or "").strip().lower()
            if status and status not in SUCCESSFUL_CONVERSION_STATUSES:
                continue
            target = str(job.get("target") or "").strip().lower() or "converted"
            params = job.get("params") or {}
            chip = _canonical_chip_code(params.get("chip") or params.get("soc_version") or "")
            for output in job.get("outputs") or []:
                if not isinstance(output, dict) or output.get("available") is False:
                    continue
                raw = str(output.get("path") or "").strip()
                if raw:
                    output_path = Path(raw).expanduser()
                    if _is_publishable_conversion_output(target, output_path):
                        candidates.append((target, output_path, chip))
        dedupe: set[tuple[str, str, str]] = set()
        result: list[Dict[str, Any]] = []
        for target, path, chip in candidates:
            try:
                path = path.resolve()
            except (OSError, RuntimeError):
                continue
            if not path.is_file() or path.stat().st_size <= 0:
                continue
            digest = _sha256(path)
            chip_identity = _canonical_chip_code(chip)
            key = (target, chip_identity, digest)
            if key in dedupe:
                continue
            dedupe.add(key)
            artifact_id = hashlib.sha256(
                f"{project_id}:{algorithm_id}:{version_id}:{target}:{chip_identity}:{digest}".encode("utf-8")
            ).hexdigest()[:32]
            result.append({
                "artifact_id": artifact_id,
                "project_id": project_id,
                "algorithm_id": algorithm_id,
                "version_id": version_id,
                "target": target,
                "file_name": path.name,
                "source_path": str(path),
                "sha256": digest,
                "size_bytes": path.stat().st_size,
                "chip_code": chip_identity,
            })
        return result

    def _mapping(self, target: str) -> Dict[str, Any] | None:
        mappings = self.repository.config().get("target_mappings") or {}
        row = mappings.get(str(target)) or {}
        if not isinstance(row, dict) or row.get("enabled") is False or not str(row.get("compute_platform_id") or "").strip():
            return None
        mapping = dict(row)
        mapping["compute_platform_id"] = self._assert_current_compute_platform(
            mapping.get("compute_platform_id"),
            target=str(target),
        )
        return mapping

    def _mapping_state(self, target: str) -> Dict[str, Any]:
        mappings = self.repository.config().get("target_mappings") or {}
        row = mappings.get(str(target)) or {}
        if not isinstance(row, dict):
            row = {}
        if row.get("enabled") is False:
            return {
                "status": "ignored",
                "enabled": False,
                "mapping": None,
                "detail": "该转换目标已明确关闭畅联云权重发布",
            }
        compute_platform_id = str(row.get("compute_platform_id") or "").strip()
        if not compute_platform_id:
            return {
                "status": "blocked",
                "enabled": True,
                "mapping": None,
                "detail": "尚未配置畅联云算力环境",
            }
        try:
            mapping = self._mapping(target)
        except PlatformError as error:
            return {
                "status": "blocked",
                "enabled": True,
                "mapping": None,
                "detail": str(getattr(error, "detail", "") or getattr(error, "message", "") or error),
                "code": str(getattr(error, "code", "") or ""),
                "message": str(getattr(error, "message", "") or error),
                "solution": str(getattr(error, "solution", "") or ""),
                "status_code": int(getattr(error, "status_code", 409) or 409),
            }
        return {
            "status": "mapped",
            "enabled": True,
            "mapping": mapping,
            "detail": str((mapping or {}).get("compute_platform_id") or ""),
        }

    @staticmethod
    def _remote_version_id(row: Mapping[str, Any]) -> str:
        for key in ("algoVersionId", "algorithmVersionId", "versionId", "id"):
            if row.get(key) not in (None, ""):
                return str(row[key])
        return ""

    @staticmethod
    def _remote_version_analysis_id(row: Mapping[str, Any]) -> str:
        for key in ("analysisId", "algoProductAnalysisId", "productAnalysisId", "analysis_id"):
            if row.get(key) not in (None, ""):
                return str(row[key])
        return ""

    def _remote_version_match(
        self,
        rows: Iterable[Mapping[str, Any]],
        version_name: str,
        *,
        analysis_id: str = "",
        require_analysis_identity: bool = False,
    ) -> str:
        matches = [
            dict(row)
            for row in rows
            if str(row.get("versionName") or row.get("versionNo") or row.get("name") or "") == str(version_name)
        ]
        if not matches:
            return ""
        expected_analysis = str(analysis_id or "").strip()
        if expected_analysis:
            identified = [
                row for row in matches
                if self._remote_version_analysis_id(row)
            ]
            exact = [
                row for row in identified
                if self._remote_version_analysis_id(row) == expected_analysis
            ]
            if len(exact) == 1:
                return self._remote_version_id(exact[0])
            if exact or identified or require_analysis_identity:
                return ""
        if len(matches) != 1:
            return ""
        return self._remote_version_id(matches[0])

    @staticmethod
    def _algorithm_analysis_ids(algorithm: Mapping[str, Any]) -> set[str]:
        values = {
            str(value).strip()
            for value in (algorithm.get("external_analysis_ids") or [])
            if str(value or "").strip()
        }
        for row in (algorithm.get("external_analyses") or []):
            if not isinstance(row, Mapping):
                continue
            value = str(row.get("analysis_id") or row.get("analysisId") or "").strip()
            if value:
                values.add(value)
        default_id = str(algorithm.get("external_analysis_id") or "").strip()
        if default_id:
            values.add(default_id)
        return values

    def _recover_external_version(
        self,
        client: PublishingChangLianClient,
        product_id: str,
        version_name: str,
        *,
        analysis_id: str = "",
        require_analysis_identity: bool = False,
    ) -> str:
        try:
            return self._remote_version_match(
                extract_items(client.list_product_versions(product_id)),
                version_name,
                analysis_id=analysis_id,
                require_analysis_identity=require_analysis_identity,
            )
        except Exception:
            return ""

    def _ensure_external_version(self, publication: Mapping[str, Any], algorithm: Mapping[str, Any], version: Mapping[str, Any], client: PublishingChangLianClient) -> str:
        existing = str(publication.get("external_algo_version_id") or "")
        if existing:
            return existing
        product_id = str(algorithm.get("external_product_id") or "")
        version_name = str(version.get("version_name") or version.get("id") or "")
        analysis_id = str(version.get("external_analysis_id") or algorithm.get("external_analysis_id") or "")
        require_analysis_identity = bool(analysis_id and len(self._algorithm_analysis_ids(algorithm)) > 1)
        recovered = self._recover_external_version(
            client,
            product_id,
            version_name,
            analysis_id=analysis_id,
            require_analysis_identity=require_analysis_identity,
        )
        if recovered:
            self.repository.patch_publication(str(publication["publication_key"]), external_algo_version_id=recovered, status="VERSION_READY", last_error="")
            return recovered
        payload: Dict[str, Any] = {"versionName": version_name, "versionNo": version_name}
        if analysis_id:
            payload["analysisId"] = analysis_id
        else:
            payload["productId"] = product_id
        try:
            response = client.create_algorithm_version(payload)
        except Exception as error:
            recovered = self._recover_external_version(
                client,
                product_id,
                version_name,
                analysis_id=analysis_id,
                require_analysis_identity=require_analysis_identity,
            )
            if recovered:
                self.repository.patch_publication(str(publication["publication_key"]), external_algo_version_id=recovered, status="VERSION_READY", last_error="")
                return recovered
            self.repository.patch_publication(str(publication["publication_key"]), status="UNKNOWN", last_error=str(error))
            raise PlatformError(
                "EXTERNAL_VERSION_CREATE_UNKNOWN", "新畅联算法版本创建结果无法确认", str(error),
                "请先检查新畅联版本列表；确认是否已生成该版本后，再执行重新同步。系统不会在结果未知时盲目重复创建。", 502,
            ) from error
        version_id = _remote_id(response, ("algoVersionId", "algorithmVersionId", "versionId", "id"))
        if not version_id:
            version_id = self._recover_external_version(
                client,
                product_id,
                version_name,
                analysis_id=analysis_id,
                require_analysis_identity=require_analysis_identity,
            )
        if not version_id:
            self.repository.patch_publication(str(publication["publication_key"]), status="UNKNOWN", last_error="新增版本接口未返回 algoVersionId，且版本列表无法反查")
            raise PlatformError(
                "EXTERNAL_VERSION_ID_MISSING", "新畅联未返回算法版本 ID", "创建接口成功但没有可解析的 algoVersionId。",
                "请让新畅联创建版本接口直接返回 algoVersionId，或确认版本列表接口路径可用于反查。", 502,
            )
        self.repository.patch_publication(str(publication["publication_key"]), external_algo_version_id=version_id, status="VERSION_READY", last_error="")
        return version_id

    def _upload_artifact(self, artifact: Mapping[str, Any], algorithm: Mapping[str, Any], version: Mapping[str, Any]) -> Dict[str, Any]:
        discovered = {
            "artifact_id": str(artifact["artifact_id"]),
            "project_id": str(artifact["project_id"]),
            "algorithm_id": str(artifact["algorithm_id"]),
            "version_id": str(artifact["version_id"]),
            "artifact_kind": "original" if str(artifact.get("target") or "") == "original" else "conversion",
            "target": str(artifact.get("target") or "unknown"),
            "conversion_job_id": "",
            "file_name": str(artifact["file_name"]),
            "source_path": str(artifact["source_path"]),
            "sha256": str(artifact.get("source_sha256") or artifact.get("sha256") or ""),
            "size_bytes": int(artifact["size_bytes"]),
            "metadata": {"chip_code": str(artifact.get("chip_code") or "")},
        }
        stored = self.model_assets.ensure_uploaded(discovered)
        if str(stored.get("storage_status") or "").upper() != "UPLOADED":
            raise RuntimeError(str(stored.get("storage_error") or "模型资产上传失败"))
        public_url = self.model_assets.public_url(stored)
        if not public_url:
            # Backward-compatible delivery gateway for existing installations.
            base_url = str(self.repository.config().get("public_base_url") or "").rstrip("/")
            if base_url:
                public_url = f"{base_url}/api/v64/model-artifacts/{artifact['artifact_id']}/download"
        if not public_url:
            raise PlatformError(
                "MODEL_ARTIFACT_PUBLIC_URL_REQUIRED",
                "算法产物缺少长期访问地址",
                str(stored.get("object_key") or ""),
                "请到“存储配置 → 算法与转换结果存储”填写 OSS Bucket 域名或 CDN 域名。",
                409,
            )
        return self.repository.patch_artifact(
            str(artifact["artifact_id"]),
            storage_source_id=str(stored.get("storage_source_id") or ""),
            object_key=str(stored.get("object_key") or ""),
            public_url=public_url, upload_status="UPLOADED", last_error="",
        )

    def _recover_weight(self, client: PublishingChangLianClient, external_version_id: str, artifact: Mapping[str, Any]) -> str:
        try:
            rows = extract_items(client.list_version_weights(external_version_id))
        except Exception:
            return ""
        for row in rows:
            same_file = str(row.get("fileName") or row.get("name") or "") == str(artifact.get("file_name") or "")
            same_platform = str(row.get("computePlatformId") or "") == str(artifact.get("compute_platform_id") or "")
            same_chip = not artifact.get("chip_code") or str(row.get("chipCode") or "") == str(artifact.get("chip_code") or "")
            if same_file and same_platform and same_chip:
                for key in ("weightId", "algorithmWeightId", "id"):
                    if row.get(key) not in (None, ""):
                        return str(row[key])
        return ""

    def _sync_weight(self, artifact: Mapping[str, Any], external_version_id: str, client: PublishingChangLianClient) -> Dict[str, Any]:
        current = self.repository.artifact(str(artifact["artifact_id"])) or dict(artifact)
        if str(current.get("external_weight_id") or ""):
            return current
        recovered = self._recover_weight(client, external_version_id, current)
        if recovered:
            return self.repository.patch_artifact(str(current["artifact_id"]), external_weight_id=recovered, sync_status="SYNCED", last_error="")
        payload = {
            "algoVersionId": external_version_id,
            "computePlatformId": str(current.get("compute_platform_id") or ""),
            "chipCode": str(current.get("chip_code") or ""),
            "fileName": str(current.get("file_name") or ""),
            "filePath": str(current.get("public_url") or ""),
        }
        try:
            response = client.create_weight(payload)
        except Exception as error:
            recovered = self._recover_weight(client, external_version_id, current)
            if recovered:
                return self.repository.patch_artifact(str(current["artifact_id"]), external_weight_id=recovered, sync_status="SYNCED", last_error="")
            self.repository.patch_artifact(str(current["artifact_id"]), sync_status="UNKNOWN", last_error=str(error))
            raise PlatformError(
                "EXTERNAL_WEIGHT_CREATE_UNKNOWN", "新畅联权重文件登记结果无法确认", str(error),
                "请先检查新畅联该版本下的权重文件；系统不会在结果未知时盲目重复登记。", 502,
            ) from error
        weight_id = _remote_id(response, ("weightId", "algorithmWeightId", "id"))
        if not weight_id:
            weight_id = self._recover_weight(client, external_version_id, current)
        if not weight_id:
            self.repository.patch_artifact(str(current["artifact_id"]), sync_status="UNKNOWN", last_error="新增权重接口未返回 weightId，且列表无法反查")
            raise PlatformError(
                "EXTERNAL_WEIGHT_ID_MISSING", "新畅联未返回权重文件 ID", str(current.get("file_name") or ""),
                "请让新畅联新增权重接口直接返回 weightId，或确认版本权重列表接口可用于反查。", 502,
            )
        return self.repository.patch_artifact(str(current["artifact_id"]), external_weight_id=weight_id, sync_status="SYNCED", last_error="")

    def _publish_transport_state(self) -> Dict[str, Any]:
        issues: list[Dict[str, str]] = []
        publish_config = self.repository.config()
        model_asset_config = self.model_assets.repository.config()
        public_base_url = str(
            model_asset_config.get("public_base_url")
            or publish_config.get("public_base_url")
            or ""
        ).strip().rstrip("/")
        if not public_base_url:
            issues.append({
                "code": "EXTERNAL_PUBLISH_CONFIG_INCOMPLETE",
                "message": "尚未配置算法产物长期访问域名（OSS Bucket 域名或 CDN 域名）",
            })
        storage_source_id = str(model_asset_config.get("storage_source_id") or "").strip()
        if not storage_source_id:
            issues.append({
                "code": "MODEL_ARTIFACT_STORAGE_NOT_CONFIGURED",
                "message": "尚未配置模型资产存储源",
            })
        elif self.storage_sources_factory().get(storage_source_id) is None:
            issues.append({
                "code": "ARTIFACT_STORAGE_SOURCE_NOT_FOUND",
                "message": f"模型资产存储源不存在：{storage_source_id}",
            })
        return {
            "ready": not issues,
            "public_base_url": public_base_url,
            "storage_source_id": storage_source_id,
            "issues": issues,
        }

    def _assert_publish_transport_ready(self) -> Dict[str, Any]:
        state = self._publish_transport_state()
        if state["ready"]:
            return state
        issue = state["issues"][0]
        code = str(issue.get("code") or "EXTERNAL_PUBLISH_CONFIG_INCOMPLETE")
        if code == "MODEL_ARTIFACT_STORAGE_NOT_CONFIGURED":
            raise PlatformError(
                code,
                "模型资产存储尚未配置",
                str(issue.get("message") or ""),
                "请先在“模型资产存储”配置可用存储源，再同步到新畅联。",
                409,
            )
        if code == "ARTIFACT_STORAGE_SOURCE_NOT_FOUND":
            raise PlatformError(
                code,
                "模型资产存储源不存在",
                str(issue.get("message") or ""),
                "请重新选择可用的模型资产存储源。",
                404,
            )
        raise PlatformError(
            "EXTERNAL_PUBLISH_CONFIG_INCOMPLETE",
            "模型发布配置不完整",
            str(issue.get("message") or ""),
            "请在“平台对接 → 畅联云版本发布”填写本平台外部访问地址。",
            422,
        )

    def publication_status(self, project_id: str, algorithm_id: str, version_id: str) -> Dict[str, Any]:
        algorithm, version = self._algorithm_version(project_id, algorithm_id, version_id)
        publication = self.repository.publication(project_id, algorithm_id, version_id)
        discovered = self.discover_artifacts(project_id, algorithm, version)
        mapped: list[Dict[str, Any]] = []
        blocked: list[Dict[str, Any]] = []
        ignored: list[Dict[str, Any]] = []
        classified: list[Dict[str, Any]] = []
        for item in discovered:
            state = self._mapping_state(str(item.get("target") or ""))
            row = {
                **dict(item),
                "publish_mapping_status": state["status"],
                "publish_mapping_detail": state.get("detail") or "",
            }
            if state.get("mapping"):
                row["compute_platform_id"] = str(state["mapping"].get("compute_platform_id") or "")
                row["mapped_chip_code"] = _canonical_chip_code(
                    item.get("chip_code") or state["mapping"].get("chip_code") or ""
                )
                mapped.append(row)
            elif state["status"] == "blocked":
                blocked.append(row)
            else:
                ignored.append(row)
            classified.append(row)
        conversion_active = self.conversion_active(project_id, algorithm_id, version_id)
        transport = self._publish_transport_state()
        identity = self._external_identity_state(algorithm, version)
        return {
            "ok": True,
            "algorithm": {"id": algorithm_id, "name": algorithm.get("name"), "external_product_id": algorithm.get("external_product_id")},
            "version": {"id": version_id, "version_name": version.get("version_name"), "external_publish_status": version.get("external_publish_status")},
            "publication": publication,
            "artifacts": self.repository.artifacts(str(publication["publication_key"])) if publication else [],
            "discovered": classified,
            "mapped_artifact_count": len(mapped),
            "blocked_artifact_count": len(blocked),
            "ignored_artifact_count": len(ignored),
            "transport_ready": bool(transport["ready"]),
            "transport_issues": list(transport["issues"]),
            "public_base_url_configured": bool(transport["public_base_url"]),
            "model_asset_storage_source_id": str(transport["storage_source_id"] or ""),
            "identity_ready": bool(identity["ready"]),
            "identity_issues": list(identity["issues"]),
            "publish_ready": bool(mapped) and not blocked and bool(transport["ready"]) and bool(identity["ready"]),
            "conversion_active": conversion_active,
        }

    def publish(self, *, project_id: str, algorithm_id: str, version_id: str, automatic: bool = False) -> Dict[str, Any]:
        algorithm, version = self._algorithm_version(project_id, algorithm_id, version_id)
        self._assert_current_external_identity(algorithm, version)
        if str(version.get("training_status") or "").upper() not in SUCCESSFUL_VERSION_STATUSES or version.get("artifact_verified") is not True:
            raise PlatformError(
                "ALGORITHM_VERSION_NOT_PUBLISHABLE", "算法版本尚不可发布", str(version.get("version_name") or version_id),
                "仅训练成功且模型产物已通过完整性校验的版本可以发布。", 409,
            )
        # Fail before any remote ChangLian write. Missing local delivery configuration
        # must never create an empty remote Algorithm Version.
        self._assert_publish_transport_ready()
        publication = self.repository.ensure_publication(project_id=project_id, algorithm=algorithm, version=version)
        if (
            automatic
            and str(publication.get("status") or "").upper() != "PUBLISHED"
            and not self.repository.auto_retry_due(publication)
        ):
            return {"ok": True, "skipped": True, "reason": "retry_not_due", "publication": publication}
        attempts = int(publication.get("attempts") or 0) + 1
        publication = self.repository.patch_publication(str(publication["publication_key"]), status="PREPARING", attempts=attempts, last_error="")
        discovered = self.discover_artifacts(project_id, algorithm, version)
        selected: list[tuple[Dict[str, Any], Dict[str, Any]]] = []
        blocked: list[Dict[str, Any]] = []
        for item in discovered:
            state = self._mapping_state(str(item.get("target") or ""))
            if state.get("mapping"):
                selected.append((item, state["mapping"]))
            elif state.get("status") == "blocked":
                blocked.append({
                    **dict(item),
                    "detail": state.get("detail") or "",
                    "code": state.get("code") or "",
                    "message": state.get("message") or "",
                    "solution": state.get("solution") or "",
                    "status_code": state.get("status_code") or 409,
                })
        if blocked:
            specific = next((row for row in blocked if str(row.get("code") or "").startswith("EXTERNAL_COMPUTE_PLATFORM_")), None)
            if specific is not None:
                raise PlatformError(
                    str(specific.get("code") or "EXTERNAL_COMPUTE_PLATFORM_MAPPING_INVALID"),
                    str(specific.get("message") or "畅联云算力环境映射不可用"),
                    str(specific.get("detail") or ""),
                    str(specific.get("solution") or "请重新同步畅联云主数据并重新选择算力环境。"),
                    int(specific.get("status_code") or 409),
                )
            detail = "；".join(
                f"{row.get('target') or '-'} / {row.get('file_name') or '-'}：{row.get('detail') or '缺少发布映射'}"
                for row in blocked
            )
            raise PlatformError(
                "MODEL_ARTIFACT_MAPPING_INCOMPLETE",
                "部分转换产物尚未配置畅联云算力环境",
                detail[:2000],
                "请在“平台对接 → 畅联云版本发布”补齐所有已启用转换目标的算力环境；不需要发布的目标请明确关闭。",
                409,
            )
        if not selected:
            self.repository.patch_publication(str(publication["publication_key"]), status="FAILED", last_error="没有可发布且已映射算力环境的转换产物")
            raise PlatformError(
                "NO_MAPPED_MODEL_ARTIFACT", "没有可发布的模型转换产物", "转换结果尚未生成，或转换目标未映射到新畅联算力环境。",
                "请先完成模型转换，并在“平台对接 → 训练成果发布”配置目标算力环境和芯片编码。", 409,
            )
        for item, mapping in selected:
            self.repository.upsert_artifact(str(publication["publication_key"]), item, mapping)

        # Upload and verify every local model artifact before creating a remote
        # ChangLian Algorithm Version. A storage failure must never leave an
        # empty remote version behind.
        uploaded_artifacts: list[Dict[str, Any]] = []
        for item, _mapping in selected:
            row = self.repository.artifact(str(item["artifact_id"])) or item
            try:
                uploaded_artifacts.append(self._upload_artifact(row, algorithm, version))
            except PlatformError as error:
                self.repository.patch_publication(
                    str(publication["publication_key"]),
                    status="FAILED",
                    last_error=str(getattr(error, "message", "") or error)[:2000],
                )
                raise
            except Exception as error:
                self.repository.patch_publication(
                    str(publication["publication_key"]),
                    status="FAILED",
                    last_error=str(error)[:2000],
                )
                raise PlatformError(
                    "MODEL_ARTIFACT_UPLOAD_FAILED",
                    "模型资产上传失败",
                    str(error),
                    "请检查模型资产存储连接和凭据；修复后重新同步。畅联云版本尚未创建。",
                    502,
                ) from error

        client = self._external_client()
        if hasattr(client, "set_audit_context"):
            client.set_audit_context(
                project_id=project_id, algorithm_id=algorithm_id, version_id=version_id,
                external_product_id=str(algorithm.get("external_product_id") or ""),
                external_analysis_id=str(version.get("external_analysis_id") or algorithm.get("external_analysis_id") or ""),
            )
        external_version_id = self._ensure_external_version(publication, algorithm, version, client)
        failures: list[str] = []
        synced = 0
        for uploaded in uploaded_artifacts:
            try:
                if hasattr(client, "set_audit_context"):
                    client.set_audit_context(
                        artifact_id=str(uploaded.get("artifact_id") or ""),
                        external_algo_version_id=external_version_id,
                    )
                self._sync_weight(uploaded, external_version_id, client)
                synced += 1
            except Exception as error:
                failures.append(f"{uploaded.get('file_name') or '-'}: {getattr(error, 'message', str(error))}")
        if failures:
            status = "PARTIAL" if synced else "FAILED"
            publication = self.repository.patch_publication(str(publication["publication_key"]), status=status, last_error="；".join(failures)[:2000])
        else:
            publication = self.repository.patch_publication(str(publication["publication_key"]), status="PUBLISHED", last_error="", published_at=utc_now())
        try:
            version_patch = {
                "external_publish_status": str(publication.get("status") or "").lower(),
                "external_algo_version_id": external_version_id,
                "external_publish_updated_at": utc_now(),
            }
            if publication.get("published_at"):
                version_patch["external_published_at"] = publication["published_at"]
            update_algorithm_version(self.algorithms_file(project_id), algorithm_id, version_id, version_patch, now=utc_now())
        except Exception:
            pass
        if failures:
            raise PlatformError(
                "EXTERNAL_PUBLISH_PARTIAL_FAILURE", "模型发布未全部完成", "；".join(failures),
                "已成功的版本和权重不会重复创建；请修复失败项后点击“重新同步”。", 502,
            )
        return {
            "ok": True,
            "publication": publication,
            "external_algo_version_id": external_version_id,
            "artifacts": self.repository.artifacts(str(publication["publication_key"])),
        }

    def publication_requires_sync(
        self,
        project_id: str,
        algorithm: Mapping[str, Any],
        version: Mapping[str, Any],
        publication: Mapping[str, Any] | None,
    ) -> bool:
        if not publication or str(publication.get("status") or "").upper() != "PUBLISHED":
            return True
        publication_key = str(publication.get("publication_key") or "")
        stored = {
            str(row.get("artifact_id") or ""): row
            for row in self.repository.artifacts(publication_key)
        }
        for item in self.discover_artifacts(project_id, algorithm, version):
            mapping_state = self._mapping_state(str(item.get("target") or ""))
            if mapping_state.get("status") == "ignored":
                continue
            artifact_id = str(item.get("artifact_id") or "")
            current = stored.get(artifact_id)
            if mapping_state.get("status") == "blocked":
                return True
            if not current or str(current.get("sync_status") or "").upper() != "SYNCED":
                return True
        return False

    def delete_version_for_rollback(
        self,
        *,
        project_id: str,
        algorithm: Mapping[str, Any],
        version: Mapping[str, Any],
    ) -> Dict[str, Any]:
        if (
            str(algorithm.get("source_type") or "").upper() != SOURCE_EXTERNAL
            or str(algorithm.get("provider_type") or "").upper() != PROVIDER_CHANGLIAN
        ):
            return {"required": False, "status": "local_only", "external_algo_version_id": ""}

        algorithm_id = str(algorithm.get("id") or "")
        version_id = str(version.get("id") or "")
        publication = self.repository.publication(project_id, algorithm_id, version_id)
        external_version_id = str(
            version.get("external_algo_version_id")
            or (publication or {}).get("external_algo_version_id")
            or ""
        ).strip()
        client = self._external_client()
        if hasattr(client, "set_audit_context"):
            client.set_audit_context(
                project_id=project_id,
                algorithm_id=algorithm_id,
                version_id=version_id,
                external_product_id=str(algorithm.get("external_product_id") or ""),
                external_analysis_id=str(version.get("external_analysis_id") or algorithm.get("external_analysis_id") or ""),
                external_algo_version_id=external_version_id,
            )

        if not external_version_id:
            product_id = str(algorithm.get("external_product_id") or "")
            version_name = str(version.get("version_name") or version_id)
            analysis_id = str(version.get("external_analysis_id") or algorithm.get("external_analysis_id") or "")
            try:
                rows = extract_items(client.list_product_versions(product_id))
            except Exception as error:
                raise PlatformError(
                    "EXTERNAL_VERSION_DELETE_LOOKUP_FAILED",
                    "回退前无法确认新畅联版本状态",
                    str(error),
                    "远端版本状态无法确认时不会删除本地版本；请检查新畅联连接后重试。",
                    502,
                ) from error
            external_version_id = self._remote_version_match(
                rows,
                version_name,
                analysis_id=analysis_id,
                require_analysis_identity=bool(analysis_id and len(self._algorithm_analysis_ids(algorithm)) > 1),
            )
            if not external_version_id:
                return {"required": True, "status": "not_present", "external_algo_version_id": ""}

        try:
            client.version_remove([external_version_id])
        except Exception as error:
            raise PlatformError(
                "EXTERNAL_VERSION_DELETE_FAILED",
                "新畅联算法版本删除失败，已停止回退",
                str(error),
                "平台不会只删除本地版本。请检查新畅联删除接口和版本状态后重试。",
                502,
            ) from error

        if publication:
            try:
                self.repository.patch_publication(
                    str(publication["publication_key"]),
                    status="DELETED",
                    last_error="",
                )
            except Exception:
                pass
        return {
            "required": True,
            "status": "deleted",
            "external_algo_version_id": external_version_id,
        }

    def auto_publish_ready(self) -> bool:
        external = self.external_repository.config()
        publish = self.repository.config()
        return bool(
            str(external.get("mode") or "local") == "external"
            and bool(external.get("auto_publish_enabled"))
            and self.model_assets.repository.config().get("storage_source_id")
            and publish.get("public_base_url")
        )

    def run_auto_publish_once(self) -> Dict[str, int]:
        summary = {"checked": 0, "published": 0, "skipped": 0, "failed": 0}
        if not self.auto_publish_ready():
            return summary
        projects = _json_load(self.data_dir / "projects.json", [])
        if not isinstance(projects, list):
            return summary
        for project in projects:
            project_id = str(project.get("id") or "") if isinstance(project, dict) else ""
            if not project_id:
                continue
            for algorithm in list_algorithms(self.algorithms_file(project_id)):
                if str(algorithm.get("source_type") or "").upper() != SOURCE_EXTERNAL or str(algorithm.get("provider_type") or "").upper() != PROVIDER_CHANGLIAN:
                    continue
                for version in algorithm.get("versions") or []:
                    if not version.get("external_publish_requested_at"):
                        continue
                    summary["checked"] += 1
                    publication = self.repository.publication(project_id, str(algorithm.get("id") or ""), str(version.get("id") or ""))
                    if not self.publication_requires_sync(project_id, algorithm, version, publication):
                        summary["skipped"] += 1
                        continue
                    try:
                        result = self.publish(
                            project_id=project_id,
                            algorithm_id=str(algorithm.get("id") or ""),
                            version_id=str(version.get("id") or ""),
                            automatic=True,
                        )
                        if result.get("skipped"):
                            summary["skipped"] += 1
                        else:
                            summary["published"] += 1
                    except Exception:
                        summary["failed"] += 1
        return summary

    def download(self, artifact_id: str):
        artifact = self.model_assets.repository.get(artifact_id)
        if artifact is not None and str(artifact.get("storage_status") or "").upper() == "UPLOADED":
            _row, provider = self.model_assets.download(artifact_id)
            object_key = str(artifact["object_key"])
            filename = str(artifact.get("file_name") or "model.bin").replace('"', "")
        else:
            artifact = self.repository.artifact(artifact_id)
            if artifact is None or str(artifact.get("upload_status") or "").upper() != "UPLOADED":
                raise PlatformError("MODEL_ARTIFACT_NOT_FOUND", "模型制品不存在或尚未上传", artifact_id, "请重新执行模型资产上传。", 404)
            provider = self._provider(str(artifact["project_id"]), str(artifact["storage_source_id"]))
            object_key = str(artifact["object_key"])
            filename = str(artifact.get("file_name") or "model.bin").replace('"', "")
        url = provider.generate_preview_url(object_key, expires_seconds=600)
        if url:
            return RedirectResponse(url=url, status_code=302)
        stream = provider.open_reader(object_key)

        def chunks():
            try:
                while True:
                    block = stream.read(1024 * 1024)
                    if not block:
                        break
                    yield block
            finally:
                try:
                    stream.close()
                except Exception:
                    pass

        return StreamingResponse(
            chunks(),
            media_type=mimetypes.guess_type(filename)[0] or "application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


def request_external_auto_publish_if_enabled(
    *, data_dir: Path, algorithms_path: Path, algorithm_id: str, version_id: str, now: str,
) -> bool:
    try:
        external = ExternalPlatformRepository(Path(data_dir)).config()
        if str(external.get("mode") or "local") != "external" or not bool(external.get("auto_publish_enabled")):
            return False
        algorithms = list_algorithms(Path(algorithms_path))
        algorithm = next((row for row in algorithms if str(row.get("id") or "") == str(algorithm_id)), None)
        if not algorithm or str(algorithm.get("source_type") or "").upper() != SOURCE_EXTERNAL:
            return False
        update_algorithm_version(
            Path(algorithms_path), str(algorithm_id), str(version_id),
            {"external_publish_requested_at": now, "external_publish_status": "pending"}, now=now,
        )
        return True
    except Exception:
        return False


def external_algorithm_publish_router(
    *,
    data_dir: Path,
    get_project: Callable[[str], Any],
    project_dir: Callable[[str], Path],
    algorithms_file: Callable[[str], Path],
    external_secret_store_factory: Callable[[], Any],
    storage_sources_factory: Callable[[], StorageSourceRepository],
    storage_credentials_factory: Callable[[], SecretCredentialStore],
) -> APIRouter:
    router = APIRouter(tags=["external-algorithm-publish"])
    service = ExternalAlgorithmPublishService(
        data_dir=Path(data_dir), project_dir=project_dir, algorithms_file=algorithms_file,
        external_secret_store_factory=external_secret_store_factory,
        storage_sources_factory=storage_sources_factory,
        storage_credentials_factory=storage_credentials_factory,
    )
    worker_lock = FileLock(str(service.repository.root / ".auto-publish-worker.lock"), timeout=0)
    asset_worker_lock = FileLock(str(service.model_assets.repository.root / ".auto-upload-worker.lock"), timeout=0)

    def worker_loop() -> None:
        while True:
            try:
                try:
                    with asset_worker_lock.acquire(timeout=0):
                        service.model_assets.run_auto_upload_once()
                except Timeout:
                    pass
                if service.auto_publish_ready():
                    try:
                        with worker_lock.acquire(timeout=0):
                            service.run_auto_publish_once()
                    except Timeout:
                        pass
            except Exception:
                pass
            time.sleep(30)

    threading.Thread(target=worker_loop, name="external-algorithm-auto-publish", daemon=True).start()

    @router.get("/api/v64/external-publish/config")
    def get_publish_config():
        return {"ok": True, **service.public_config()}

    @router.get("/api/v64/model-artifacts/config")
    def get_model_artifact_config():
        return {"ok": True, **service.model_assets.public_config()}

    @router.put("/api/v64/model-artifacts/config")
    def save_model_artifact_config(payload: ModelArtifactConfigPayload):
        return {"ok": True, "config": service.model_assets.save_config(payload)}

    @router.post("/api/v64/model-artifacts/storage-test")
    def test_model_artifact_storage(payload: StorageTestPayload):
        return service.model_assets.test_storage(payload.storage_source_id)

    @router.get("/api/v64/model-artifacts")
    def list_model_artifacts(
        project_id: str = Query(default=""), algorithm_id: str = Query(default=""),
        version_id: str = Query(default=""), status: str = Query(default=""),
        limit: int = Query(default=100, ge=1, le=500), offset: int = Query(default=0, ge=0),
    ):
        return {
            "ok": True,
            "items": service.model_assets.repository.list(
                project_id=project_id, algorithm_id=algorithm_id, version_id=version_id,
                status=status, limit=limit, offset=offset,
            ),
            "summary": service.model_assets.repository.summary(project_id=project_id),
        }

    @router.post("/api/v64/model-artifacts/{artifact_id}/retry")
    def retry_model_artifact(artifact_id: str):
        return {"ok": True, "artifact": service.model_assets.retry(artifact_id)}

    @router.post("/api/v64/model-artifacts/run-auto")
    def run_model_artifact_auto_upload():
        return {"ok": True, **service.model_assets.run_auto_upload_once()}

    @router.put("/api/v64/external-publish/config")
    def save_publish_config(payload: ExternalPublishConfigPayload):
        return {"ok": True, "config": service.save_config(payload)}

    @router.get("/api/v64/external-publish/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}")
    def get_publication_status(project_id: str, algorithm_id: str, version_id: str):
        get_project(project_id)
        return service.publication_status(project_id, algorithm_id, version_id)

    @router.post("/api/v64/external-publish/projects/{project_id}/algorithms/{algorithm_id}/versions/{version_id}/publish")
    def publish_version(project_id: str, algorithm_id: str, version_id: str):
        get_project(project_id)
        return service.publish(project_id=project_id, algorithm_id=algorithm_id, version_id=version_id, automatic=False)

    @router.get("/api/v64/model-artifacts/{artifact_id}/download")
    def download_artifact(artifact_id: str):
        return service.download(artifact_id)

    @router.post("/api/v64/external-publish/run-auto")
    def run_auto_publish():
        return {"ok": True, **service.run_auto_publish_once()}

    return router
