from __future__ import annotations

import hashlib
import json
import mimetypes
import sqlite3
import requests
import tempfile
import uuid
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import quote

from filelock import FileLock
from pydantic import BaseModel, Field

from .algorithms import list_algorithms
from .errors import PlatformError
from .secrets import SecretCredentialStore
from .storage import StorageProviderFactory, StorageSourceRepository


SUCCESSFUL_CONVERSION_STATUSES = {
    "done", "finished", "completed", "success", "succeeded", "partial_success", "blocked_by_hardware",
}

_DELIVERABLE_SUFFIXES: dict[str, frozenset[str]] = {
    "onnx": frozenset({".onnx"}),
    "rockchip": frozenset({".rknn"}),
    "tensorrt": frozenset({".engine"}),
    "sophon": frozenset({".bmodel"}),
    "ascend": frozenset({".om"}),
}


def _is_conversion_deliverable(target: str, path: Path) -> bool:
    candidate = Path(path)
    if candidate.name.lower() == "manifest.json":
        return False
    suffixes = _DELIVERABLE_SUFFIXES.get(str(target or "").strip().lower())
    return True if suffixes is None else candidate.suffix.lower() in suffixes


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_segment(value: Any, fallback: str = "item") -> str:
    import re
    text = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "").strip()).strip("-._")
    return (text or fallback)[:120]


def _json_load(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


class ModelArtifactConfigPayload(BaseModel):
    storage_source_id: str = ""
    root_prefix: str = ""
    # Read-only migration input for callers that have not yet moved to
    # root_prefix. New durable config writes only root_prefix.
    object_prefix: str = ""
    # Legacy request compatibility only. Stable public URL now belongs to the
    # selected StorageSource and is never written to artifact binding config.
    public_base_url: str = ""
    auto_upload_enabled: bool = True


class StorageTestPayload(BaseModel):
    storage_source_id: str
    public_base_url: str = ""


DEFAULT_CONFIG: dict[str, Any] = {
    "schema_version": 3,
    "storage_source_id": "",
    "root_prefix": "changlian-ai/artifacts",
    "auto_upload_enabled": True,
    "updated_at": None,
}


def _canonical_prefix(value: Any, default: str = "changlian-ai/artifacts") -> str:
    text = str(value or default).replace("\\", "/").strip().strip("/")
    parts = [part for part in text.split("/") if part]
    if not parts or any(part in {".", ".."} for part in parts):
        raise PlatformError(
            "MODEL_ARTIFACT_ROOT_PREFIX_INVALID",
            "算法产物根目录不合法",
            str(value or ""),
            "请填写 Bucket 内的安全相对目录，例如 changlian-ai/artifacts/。",
            422,
        )
    return "/".join(parts)


def build_artifact_object_key(
    *,
    root_prefix: str,
    project_id: Any,
    algorithm_id: Any,
    version_id: Any,
    target: Any,
    chip_code: Any = "",
    sha256: Any,
    file_name: Any,
) -> str:
    """Build the final Bucket-relative immutable artifact object key."""
    root = _canonical_prefix(root_prefix)
    normalized_target = str(target or "original").strip().lower()
    normalized_chip = str(chip_code or "").strip().lower()
    if normalized_target in {"original", "training", "best", "last"}:
        artifact_directory = ["training"]
    elif normalized_target == "onnx":
        artifact_directory = ["onnx"]
    elif normalized_target in {"rockchip", "rknn"}:
        if not normalized_chip:
            raise PlatformError(
                "MODEL_ARTIFACT_CHIP_REQUIRED",
                "RKNN 产物缺少芯片身份",
                "chip_code 为空",
                "生成 RKNN Object Key 前必须提供真实芯片型号。",
                422,
            )
        artifact_directory = ["rknn", _safe_segment(normalized_chip, "chip").lower()]
    elif normalized_target in {"report", "reports", "training-report", "metrics"}:
        artifact_directory = ["reports"]
    else:
        artifact_directory = ["conversions", _safe_segment(normalized_target, "artifact").lower()]
        if normalized_chip:
            artifact_directory.append(_safe_segment(normalized_chip, "chip").lower())
    digest = str(sha256 or "").strip().lower()
    if len(digest) < 16:
        raise PlatformError(
            "MODEL_ARTIFACT_HASH_INVALID",
            "算法产物 SHA256 不完整",
            f"sha256={digest or '<empty>'}",
            "生成不可变 Object Key 前必须完成 SHA256 计算。",
            422,
        )
    immutable_name = f"{digest[:16]}-{_safe_segment(Path(str(file_name or 'model.bin')).name, 'model.bin')}"
    return "/".join([
        root,
        "projects", _safe_segment(project_id, "project"),
        "algorithms", _safe_segment(algorithm_id, "algorithm"),
        "versions", _safe_segment(version_id, "version"),
        *artifact_directory,
        immutable_name,
    ])


def build_public_url(public_base_url: Any, object_key: Any) -> str:
    """Join a StorageSource long-lived public root with one final object key."""
    base_url = str(public_base_url or "").strip().rstrip("/")
    key = str(object_key or "").replace("\\", "/").lstrip("/")
    if not base_url or not key:
        return ""
    if not base_url.startswith(("http://", "https://")):
        raise PlatformError(
            "MODEL_ARTIFACT_PUBLIC_URL_INVALID",
            "算法产物长期访问根地址格式不正确",
            base_url,
            "请在 StorageSource 填写以 http:// 或 https:// 开头的 OSS Bucket 域名或 CDN 域名。",
            422,
        )
    return f"{base_url}/{quote(key, safe='/-._~')}"


_SCHEMA = """
CREATE TABLE IF NOT EXISTS model_artifacts (
    artifact_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    algorithm_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    artifact_kind TEXT NOT NULL,
    target TEXT NOT NULL,
    chip_code TEXT NOT NULL DEFAULT '',
    conversion_job_id TEXT NOT NULL DEFAULT '',
    file_name TEXT NOT NULL,
    source_path TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    storage_source_id TEXT NOT NULL DEFAULT '',
    object_key TEXT NOT NULL DEFAULT '',
    public_url TEXT NOT NULL DEFAULT '',
    storage_status TEXT NOT NULL DEFAULT 'PENDING',
    storage_error TEXT NOT NULL DEFAULT '',
    uploaded_at TEXT,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_model_artifacts_version
ON model_artifacts(project_id, algorithm_id, version_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_model_artifacts_storage_status
ON model_artifacts(storage_status, updated_at);
"""


class ModelArtifactRepository:
    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir) / "model_artifacts"
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "artifacts.sqlite3"
        self.config_path = self.root / "config.json"
        self.lock = FileLock(str(self.root / ".config.lock"), timeout=30)
        with closing(self._connect()) as database:
            database.executescript(_SCHEMA)
            self._migrate_schema(database)

    @staticmethod
    def _migrate_schema(database: sqlite3.Connection) -> None:
        columns = {
            str(row["name"])
            for row in database.execute("PRAGMA table_info(model_artifacts)").fetchall()
        }
        if "chip_code" not in columns:
            database.execute(
                "ALTER TABLE model_artifacts ADD COLUMN chip_code TEXT NOT NULL DEFAULT ''"
            )
        if "public_url" not in columns:
            database.execute(
                "ALTER TABLE model_artifacts ADD COLUMN public_url TEXT NOT NULL DEFAULT ''"
            )
        rows = database.execute(
            "SELECT artifact_id, chip_code, metadata_json FROM model_artifacts"
        ).fetchall()
        for row in rows:
            if str(row["chip_code"] or "").strip():
                continue
            try:
                metadata = json.loads(str(row["metadata_json"] or "{}"))
            except (TypeError, json.JSONDecodeError):
                metadata = {}
            chip = str(
                metadata.get("chip_code")
                or metadata.get("chip")
                or metadata.get("soc_version")
                or ""
            ).strip().lower()
            if chip:
                database.execute(
                    "UPDATE model_artifacts SET chip_code = ? WHERE artifact_id = ?",
                    (chip, str(row["artifact_id"])),
                )
        database.execute("DROP INDEX IF EXISTS ux_model_artifacts_identity")
        database.execute(
            """
            CREATE UNIQUE INDEX ux_model_artifacts_identity
            ON model_artifacts(
                project_id, algorithm_id, version_id, target, chip_code, sha256
            )
            """
        )

    def _connect(self) -> sqlite3.Connection:
        database = sqlite3.connect(self.db_path, timeout=5, isolation_level=None)
        database.row_factory = sqlite3.Row
        database.execute("PRAGMA journal_mode=WAL")
        database.execute("PRAGMA busy_timeout=5000")
        return database

    def config(self) -> dict[str, Any]:
        with self.lock:
            stored = _json_load(self.config_path, {})
        result = dict(DEFAULT_CONFIG)
        if isinstance(stored, dict):
            result.update(stored)
        root_prefix = _canonical_prefix(
            result.get("root_prefix") or result.get("object_prefix") or DEFAULT_CONFIG["root_prefix"]
        )
        result["schema_version"] = 3
        result["root_prefix"] = root_prefix
        # Compatibility read alias only; config.json has one durable owner.
        result["object_prefix"] = root_prefix
        result.pop("public_base_url", None)
        # Model delivery is a platform invariant once a storage source is configured.
        result["auto_upload_enabled"] = True
        return result

    def save_config(self, payload: ModelArtifactConfigPayload) -> dict[str, Any]:
        prefix = _canonical_prefix(payload.root_prefix or payload.object_prefix)
        body = {
            "schema_version": 3,
            "storage_source_id": str(payload.storage_source_id or "").strip(),
            "root_prefix": prefix,
            "auto_upload_enabled": True,
            "updated_at": utc_now(),
        }
        with self.lock:
            temporary = self.config_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(body, ensure_ascii=False, indent=2), encoding="utf-8")
            temporary.replace(self.config_path)
        return self.config()

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as database:
            row = database.execute("SELECT * FROM model_artifacts WHERE artifact_id = ?", (str(artifact_id),)).fetchone()
        return self._public(row) if row else None

    @staticmethod
    def _public(row: sqlite3.Row | Mapping[str, Any]) -> dict[str, Any]:
        value = dict(row)
        try:
            value["metadata"] = json.loads(value.pop("metadata_json") or "{}")
        except (TypeError, json.JSONDecodeError):
            value["metadata"] = {}
        return value

    def upsert(self, discovered: Mapping[str, Any]) -> dict[str, Any]:
        stamp = utc_now()
        metadata = dict(discovered.get("metadata") or {})
        chip_code = str(
            discovered.get("chip_code")
            or metadata.get("chip_code")
            or metadata.get("chip")
            or metadata.get("soc_version")
            or ""
        ).strip().lower()
        requested_artifact_id = str(discovered["artifact_id"])
        project_id = str(discovered["project_id"])
        algorithm_id = str(discovered["algorithm_id"])
        version_id = str(discovered["version_id"])
        target = str(discovered.get("target") or "unknown")
        digest = str(discovered["sha256"])
        with closing(self._connect()) as database:
            existing = database.execute(
                """
                SELECT artifact_id
                FROM model_artifacts
                WHERE project_id = ? AND algorithm_id = ? AND version_id = ?
                  AND target = ? AND chip_code = ? AND sha256 = ?
                """,
                (project_id, algorithm_id, version_id, target, chip_code, digest),
            ).fetchone()
            artifact_id = (
                str(existing["artifact_id"])
                if existing is not None
                else requested_artifact_id
            )
            values = (
                artifact_id, project_id, algorithm_id, version_id,
                str(discovered.get("artifact_kind") or "conversion"),
                target, chip_code, str(discovered.get("conversion_job_id") or ""),
                str(discovered["file_name"]), str(discovered["source_path"]), digest,
                int(discovered["size_bytes"]),
                json.dumps(metadata, ensure_ascii=False, sort_keys=True), stamp, stamp,
            )
            database.execute(
                """
                INSERT INTO model_artifacts (
                    artifact_id, project_id, algorithm_id, version_id, artifact_kind, target,
                    chip_code, conversion_job_id, file_name, source_path, sha256, size_bytes,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(artifact_id) DO UPDATE SET
                    source_path=excluded.source_path,
                    file_name=excluded.file_name,
                    size_bytes=excluded.size_bytes,
                    chip_code=excluded.chip_code,
                    conversion_job_id=excluded.conversion_job_id,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                values,
            )
        return self.get(artifact_id) or {}

    def patch(self, artifact_id: str, **changes: Any) -> dict[str, Any]:
        allowed = {"storage_source_id", "object_key", "public_url", "storage_status", "storage_error", "uploaded_at", "updated_at"}
        values = {key: value for key, value in changes.items() if key in allowed}
        values.setdefault("updated_at", utc_now())
        if not values:
            return self.get(artifact_id) or {}
        sql = "UPDATE model_artifacts SET " + ", ".join(f"{key} = ?" for key in values) + " WHERE artifact_id = ?"
        with closing(self._connect()) as database:
            database.execute(sql, (*values.values(), str(artifact_id)))
        row = self.get(artifact_id)
        if row is None:
            raise KeyError(artifact_id)
        return row

    def list(
        self,
        *,
        project_id: str = "",
        algorithm_id: str = "",
        version_id: str = "",
        status: str = "",
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        clauses = ["1=1"]
        args: list[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            args.append(str(project_id))
        if algorithm_id:
            clauses.append("algorithm_id = ?")
            args.append(str(algorithm_id))
        if version_id:
            clauses.append("version_id = ?")
            args.append(str(version_id))
        if status:
            clauses.append("storage_status = ?")
            args.append(str(status).upper())
        args.extend([max(1, min(500, int(limit))), max(0, int(offset))])
        sql = "SELECT * FROM model_artifacts WHERE " + " AND ".join(clauses) + " ORDER BY updated_at DESC LIMIT ? OFFSET ?"
        with closing(self._connect()) as database:
            rows = database.execute(sql, args).fetchall()
        return [self._public(row) for row in rows]

    def summary(self, *, project_id: str = "") -> dict[str, int]:
        clause = "WHERE project_id = ?" if project_id else ""
        args = (str(project_id),) if project_id else ()
        with closing(self._connect()) as database:
            row = database.execute(
                f"""
                SELECT COUNT(*) AS total,
                       SUM(CASE WHEN storage_status='UPLOADED' THEN 1 ELSE 0 END) AS uploaded,
                       SUM(CASE WHEN storage_status='FAILED' THEN 1 ELSE 0 END) AS failed,
                       SUM(CASE WHEN storage_status IN ('PENDING','UPLOADING') THEN 1 ELSE 0 END) AS pending
                FROM model_artifacts {clause}
                """,
                args,
            ).fetchone()
        return {
            "total": int(row["total"] or 0),
            "uploaded": int(row["uploaded"] or 0),
            "failed": int(row["failed"] or 0),
            "pending": int(row["pending"] or 0),
        }


class ModelArtifactService:
    def __init__(
        self,
        *,
        data_dir: str | Path,
        project_dir: Callable[[str], Path],
        algorithms_file: Callable[[str], Path],
        storage_sources_factory: Callable[[], StorageSourceRepository],
        storage_credentials_factory: Callable[[], SecretCredentialStore],
    ):
        self.data_dir = Path(data_dir)
        self.project_dir = project_dir
        self.algorithms_file = algorithms_file
        self.storage_sources_factory = storage_sources_factory
        self.storage_credentials_factory = storage_credentials_factory
        self.repository = ModelArtifactRepository(self.data_dir)

    def public_config(self) -> dict[str, Any]:
        config = self.repository.config()
        credentials = self.storage_credentials_factory()
        sources = []
        for source in self.storage_sources_factory().list():
            state = credentials.public_state(source.secret_ref) if source.secret_ref else {"configured": False, "masked": ""}
            sources.append(source.to_public_dict(
                secret_configured=bool(state.get("configured")),
                secret_masked=str(state.get("masked") or ""),
            ))
        return {"config": config, "storage_sources": sources, "summary": self.repository.summary()}

    def save_config(self, payload: ModelArtifactConfigPayload) -> dict[str, Any]:
        source_id = str(payload.storage_source_id or "").strip()
        if source_id:
            source = self.storage_sources_factory().get(source_id)
            if source is None:
                raise PlatformError("MODEL_STORAGE_SOURCE_NOT_FOUND", "算法与转换结果存储源不存在", source_id, "请先在存储配置中创建该存储源。", 404)
            if not source.enabled:
                raise PlatformError("MODEL_STORAGE_SOURCE_DISABLED", "算法与转换结果存储源已停用", source_id, "请启用存储源后再保存。", 409)
        return self.repository.save_config(payload)

    def _provider(self, project_id: str, source_id: str):
        source = self.storage_sources_factory().get(source_id)
        if source is None:
            raise PlatformError("MODEL_STORAGE_SOURCE_NOT_FOUND", "算法与转换结果存储源不存在", source_id, "请到“存储配置 → 算法与转换结果存储”重新选择存储源。", 404)
        secret: Mapping[str, str] = {}
        if source.secret_ref:
            secret = self.storage_credentials_factory().get(source.secret_ref) or {}
        # Artifact object_key is already the final Bucket-relative key. Keep a
        # StorageSource prefix available for material callers, but never apply
        # that provider namespace a second time to canonical artifact keys.
        artifact_source = replace(
            source,
            config={**source.config, "prefix": ""},
        )
        return StorageProviderFactory(
            data_dir=self.data_dir,
            project_dir=self.project_dir(project_id),
            credentials={source.id: secret},
        ).create(artifact_source)

    def public_url(self, artifact: Mapping[str, Any]) -> str:
        """Return a stable externally reachable object URL, never an expiring signed URL."""
        config = self.repository.config()
        source_id = str(artifact.get("storage_source_id") or config.get("storage_source_id") or "").strip()
        source = self.storage_sources_factory().get(source_id) if source_id else None
        if source is None:
            return ""
        base_url = str(source.config.get("public_base_url") or "").strip().rstrip("/")
        object_key = str(artifact.get("object_key") or "").replace("\\", "/").lstrip("/")
        return build_public_url(base_url, object_key)

    def test_storage(self, source_id: str, _legacy_public_base_url: str = "") -> dict[str, Any]:
        source_id = str(source_id or "").strip()
        if not source_id:
            raise PlatformError("MODEL_STORAGE_SOURCE_REQUIRED", "请选择算法与转换结果存储源", "storage_source_id 为空", "请选择 OSS / MinIO / S3 / 本地存储源后测试。", 422)
        source = self.storage_sources_factory().get(source_id)
        if source is None:
            raise PlatformError("MODEL_STORAGE_SOURCE_NOT_FOUND", "算法与转换结果存储源不存在", source_id, "请先在存储配置中创建该存储源。", 404)
        public_base_url = str(source.config.get("public_base_url") or "").strip().rstrip("/")
        probe_project = "_model_artifact_probe"
        self.project_dir(probe_project).mkdir(parents=True, exist_ok=True)
        provider = self._provider(probe_project, source_id)
        health = provider.health_check()
        if not health.ok:
            raise PlatformError(
                "MODEL_STORAGE_HEALTH_AUTH_FAILED",
                "算法产物存储认证或 Bucket 访问失败",
                str(health.message or ""),
                "请检查 Endpoint、Bucket、AccessKey ID、AccessKey Secret 和 Bucket 权限。",
                503,
            )
        probe_id = uuid.uuid4().hex
        root_prefix = str(self.repository.config().get("root_prefix") or "changlian-ai/artifacts")
        key = f"{_canonical_prefix(root_prefix)}/.changlian-health-check/{probe_id}.txt"
        payload = b"model-artifact-storage-healthcheck"
        with tempfile.NamedTemporaryFile("wb", delete=False) as stream:
            stream.write(payload)
            temporary = Path(stream.name)
        direct_url = ""
        direct_url_reachable = False
        stages = {
            "authenticated": True,
            "written": False,
            "stat_checked": False,
            "read_checked": False,
            "deleted": False,
            "public_url_checked": False,
        }
        operation_error: Exception | None = None
        try:
            meta = provider.upload(key, temporary, content_type="text/plain", metadata={"purpose": "healthcheck"})
            stages["written"] = True
            checked = provider.stat(key)
            if int(checked.size_bytes) != int(meta.size_bytes) or int(checked.size_bytes) <= 0:
                raise RuntimeError("写入后对象大小校验失败")
            stages["stat_checked"] = True
            reader = provider.open_reader(key)
            try:
                content = reader.read()
            finally:
                close = getattr(reader, "close", None)
                if callable(close):
                    close()
            if content != payload:
                raise RuntimeError("读取内容与写入内容不一致")
            stages["read_checked"] = True
            if public_base_url:
                direct_url = build_public_url(public_base_url, key)
                try:
                    response = requests.get(
                        direct_url,
                        headers={"Range": "bytes=0-0", "Cache-Control": "no-cache"},
                        timeout=10,
                        allow_redirects=False,
                    )
                except requests.RequestException as error:
                    raise PlatformError(
                        "MODEL_ARTIFACT_PUBLIC_URL_UNREACHABLE",
                        "OSS 长期访问地址无法读取测试文件",
                        str(error),
                        "OSS 凭据读写正常，但畅联云使用的 filePath 当前不可访问。请检查公网/专网连通、Bucket 权限或 CDN 域名。",
                        409,
                    ) from error
                if response.status_code not in {200, 206}:
                    raise PlatformError(
                        "MODEL_ARTIFACT_PUBLIC_URL_UNREACHABLE",
                        "OSS 长期访问地址无法读取测试文件",
                        f"HTTP {response.status_code}",
                        "OSS 凭据读写正常，但长期链接无法直接读取。若 Bucket 为私有，请配置畅联云可访问的专用域名/CDN/网关，而不要写会过期的临时签名 URL。",
                        409,
                    )
                direct_url_reachable = True
                stages["public_url_checked"] = True
        except Exception as error:
            operation_error = error
        finally:
            try:
                provider.delete(key)
                if provider.exists(key):
                    raise RuntimeError("DELETE 后测试对象仍然存在")
                stages["deleted"] = True
            except Exception as error:
                temporary.unlink(missing_ok=True)
                raise PlatformError(
                    "MODEL_STORAGE_HEALTH_DELETE_FAILED",
                    "OSS 测试对象删除失败",
                    str(error),
                    "测试对象未能确认删除，连接测试不会返回成功；请检查 Bucket 删除权限并清理 .changlian-health-check/。",
                    409,
                ) from error
            temporary.unlink(missing_ok=True)
        if operation_error is not None:
            if isinstance(operation_error, PlatformError):
                raise operation_error
            raise PlatformError(
                "MODEL_STORAGE_HEALTH_ROUNDTRIP_FAILED",
                "OSS 写入、读取或校验失败",
                str(operation_error),
                "请检查 Endpoint、Bucket、凭据以及对象的 PUT、HEAD/STAT、GET 权限。",
                503,
            ) from operation_error
        return {
            "ok": True,
            "storage_source_id": source_id,
            "health": getattr(health, "status", None) or "AVAILABLE",
            "stages": stages,
            "public_url_checked": bool(public_base_url),
            "public_url_reachable": direct_url_reachable,
            "message": (
                "OSS 读写与长期访问地址测试均通过"
                if public_base_url and direct_url_reachable
                else "写入、读取元数据和删除测试通过；尚未测试长期访问地址"
            ),
            "tested_at": utc_now(),
        }

    def _conversion_jobs(self, project_id: str, algorithm_id: str, version_id: str) -> list[dict[str, Any]]:
        project = self.project_dir(project_id)
        # The Agent commit root is authoritative when the same durable task ID
        # also exists in the legacy/control-plane deployment root.
        roots = (project / "deploy" / "jobs", project / "deployment" / "jobs")
        rows: list[dict[str, Any]] = []
        seen: set[str] = set()
        for root in roots:
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
                identity = str(job.get("id") or job_file.resolve())
                if exact and identity not in seen:
                    seen.add(identity)
                    rows.append(job)
        return rows

    def discover_version_artifacts(self, project_id: str, algorithm: Mapping[str, Any], version: Mapping[str, Any]) -> list[dict[str, Any]]:
        algorithm_id = str(algorithm.get("id") or "")
        version_id = str(version.get("id") or "")
        candidates: list[tuple[str, str, Path, str, dict[str, Any]]] = []
        for key in ("best_path", "stored_path", "last_path", "path"):
            raw = str(version.get(key) or "").strip()
            if raw:
                candidates.append(("original", "original", Path(raw).expanduser(), "", {"version_field": key}))
        for job in self._conversion_jobs(project_id, algorithm_id, version_id):
            status = str(job.get("status") or "").strip().lower()
            if status and status not in SUCCESSFUL_CONVERSION_STATUSES:
                continue
            target = str(job.get("target") or "converted").strip().lower() or "converted"
            params = job.get("params") or {}
            chip = str(params.get("chip") or params.get("soc_version") or "")
            for output in job.get("outputs") or []:
                if not isinstance(output, dict) or output.get("available") is False:
                    continue
                raw = str(output.get("path") or "").strip()
                if raw:
                    output_path = Path(raw).expanduser()
                    if _is_conversion_deliverable(target, output_path):
                        candidates.append(("conversion", target, output_path, str(job.get("id") or ""), {"chip_code": chip}))
        seen: set[tuple[str, str, str]] = set()
        result: list[dict[str, Any]] = []
        for kind, target, path, job_id, metadata in candidates:
            try:
                path = path.resolve()
            except (OSError, RuntimeError):
                continue
            if not path.is_file() or path.stat().st_size <= 0:
                continue
            digest = _sha256(path)
            chip_code = str(metadata.get("chip_code") or "").strip().lower()
            identity = (target, chip_code, digest)
            if identity in seen:
                continue
            seen.add(identity)
            artifact_id = hashlib.sha256(
                f"{project_id}:{algorithm_id}:{version_id}:{target}:{chip_code}:{digest}".encode("utf-8")
            ).hexdigest()[:32]
            result.append({
                "artifact_id": artifact_id,
                "project_id": project_id,
                "algorithm_id": algorithm_id,
                "version_id": version_id,
                "artifact_kind": kind,
                "target": target,
                "chip_code": chip_code,
                "conversion_job_id": job_id,
                "file_name": path.name,
                "source_path": str(path),
                "sha256": digest,
                "size_bytes": path.stat().st_size,
                "metadata": metadata,
            })
        return result

    def ensure_uploaded(self, discovered: Mapping[str, Any], *, force: bool = False) -> dict[str, Any]:
        row = self.repository.upsert(discovered)
        config = self.repository.config()
        source_id = str(config.get("storage_source_id") or "").strip()
        if not source_id:
            return self.repository.patch(str(row["artifact_id"]), storage_status="PENDING", storage_error="尚未配置算法与转换结果存储源")
        provider = self._provider(str(row["project_id"]), source_id)
        source_path = Path(str(row["source_path"])).resolve()
        if not source_path.is_file() or source_path.stat().st_size <= 0:
            return self.repository.patch(str(row["artifact_id"]), storage_status="FAILED", storage_error="模型源文件不存在")
        root_prefix = str(config.get("root_prefix") or "changlian-ai/artifacts")
        object_key = str(row.get("object_key") or "")
        if not object_key or str(row.get("storage_source_id") or "") != source_id:
            object_key = build_artifact_object_key(
                root_prefix=root_prefix,
                project_id=row["project_id"],
                algorithm_id=row["algorithm_id"],
                version_id=row["version_id"],
                target=row["target"],
                chip_code=row.get("chip_code") or "",
                sha256=row["sha256"],
                file_name=row["file_name"],
            )
        if not force and str(row.get("storage_status") or "").upper() == "UPLOADED" and str(row.get("storage_source_id") or "") == source_id:
            try:
                meta = provider.stat(object_key)
                if int(meta.size_bytes) == int(row["size_bytes"]) and (not meta.sha256 or str(meta.sha256) == str(row["sha256"])):
                    public_url = self.public_url(row)
                    if public_url != str(row.get("public_url") or ""):
                        return self.repository.patch(str(row["artifact_id"]), public_url=public_url)
                    return row
            except Exception:
                pass
        self.repository.patch(str(row["artifact_id"]), storage_source_id=source_id, object_key=object_key, storage_status="UPLOADING", storage_error="")
        try:
            if provider.exists(object_key):
                meta = provider.stat(object_key)
                if int(meta.size_bytes) != int(row["size_bytes"]) or (meta.sha256 and str(meta.sha256) != str(row["sha256"])):
                    raise RuntimeError("同名对象已存在但内容校验不一致")
            else:
                meta = provider.upload(
                    object_key,
                    source_path,
                    content_type=mimetypes.guess_type(source_path.name)[0] or "application/octet-stream",
                    metadata={
                        "sha256": str(row["sha256"]),
                        "algorithm": str(row["algorithm_id"]),
                        "version": str(row["version_id"]),
                        "target": str(row["target"]),
                        "chip_code": str(row.get("chip_code") or ""),
                    },
                )
            if int(meta.size_bytes) != int(row["size_bytes"]):
                raise RuntimeError("上传后文件大小校验失败")
            if meta.sha256 and str(meta.sha256) != str(row["sha256"]):
                raise RuntimeError("上传后 SHA256 校验失败")
        except Exception as error:
            return self.repository.patch(
                str(row["artifact_id"]), storage_source_id=source_id, object_key=object_key,
                storage_status="FAILED", storage_error=str(error)[:2000],
            )
        uploaded = self.repository.patch(
            str(row["artifact_id"]), storage_source_id=source_id, object_key=object_key,
            storage_status="UPLOADED", storage_error="", uploaded_at=utc_now(),
        )
        public_url = self.public_url(uploaded)
        if public_url:
            uploaded = self.repository.patch(str(row["artifact_id"]), public_url=public_url)
        return uploaded

    def register_verified_remote_artifact(
        self,
        *,
        project_id: str,
        algorithm_id: str,
        version_id: str,
        target: str,
        file_name: str,
        sha256: str,
        size_bytes: int,
        storage_source_id: str,
        object_key: str,
        source_path: str = "",
        artifact_kind: str = "original",
        metadata: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Register an object already uploaded by a fenced remote execution.

        The object is re-stat'ed here and must expose exact server-visible
        SHA256 + size evidence. This never trusts an Agent-reported object key
        alone and never performs a second upload through the control plane.
        """
        digest = str(sha256 or "").strip().lower()
        if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
            raise PlatformError(
                "MODEL_REMOTE_ARTIFACT_HASH_INVALID",
                "远程模型资产哈希无效",
                f"sha256={digest or '<empty>'}",
                "请重新上传模型资产并完成 SHA256 校验。",
                422,
            )
        try:
            expected_size = int(size_bytes)
        except (TypeError, ValueError) as error:
            raise PlatformError(
                "MODEL_REMOTE_ARTIFACT_SIZE_INVALID",
                "远程模型资产大小无效",
                f"size_bytes={size_bytes!r}",
                "请重新上传模型资产并完成文件大小校验。",
                422,
            ) from error
        if expected_size <= 0:
            raise PlatformError(
                "MODEL_REMOTE_ARTIFACT_SIZE_INVALID",
                "远程模型资产大小无效",
                f"size_bytes={expected_size}",
                "请重新上传模型资产并完成文件大小校验。",
                422,
            )
        source_id = str(storage_source_id or "").strip()
        key = str(object_key or "").strip()
        if not source_id or not key:
            raise PlatformError(
                "MODEL_REMOTE_ARTIFACT_OBJECT_INVALID",
                "远程模型资产对象引用不完整",
                f"storage_source_id={source_id!r}, object_key={key!r}",
                "请重新执行远程训练模型上传。",
                422,
            )
        config = self.repository.config()
        configured_source = str(config.get("storage_source_id") or "").strip()
        if not configured_source or configured_source != source_id:
            raise PlatformError(
                "MODEL_REMOTE_ARTIFACT_STORAGE_MISMATCH",
                "远程模型资产未写入当前统一模型存储",
                f"expected={configured_source or '<missing>'}, actual={source_id}",
                "请确认“存储配置 → 算法与转换结果存储”后重新执行远程训练。",
                409,
            )
        provider = self._provider(str(project_id), source_id)
        try:
            object_meta = provider.stat(key)
        except Exception as error:
            raise PlatformError(
                "MODEL_REMOTE_ARTIFACT_NOT_FOUND",
                "远程模型资产对象不可用",
                str(error),
                "请重新上传模型文件后再完成训练归档。",
                409,
            ) from error
        actual_sha = str(object_meta.sha256 or "").strip().lower()
        if int(object_meta.size_bytes) != expected_size or not actual_sha or actual_sha != digest:
            raise PlatformError(
                "MODEL_REMOTE_ARTIFACT_EVIDENCE_MISMATCH",
                "远程模型资产完整性校验失败",
                (
                    f"expected_size={expected_size}, actual_size={int(object_meta.size_bytes)}; "
                    f"expected_sha256={digest}, actual_sha256={actual_sha or '<missing>'}"
                ),
                "请重新上传模型文件；禁止使用缺少服务端 SHA256 元数据的对象。",
                409,
            )
        artifact_metadata = dict(metadata or {})
        chip_code = str(
            artifact_metadata.get("chip_code")
            or artifact_metadata.get("chip")
            or artifact_metadata.get("soc_version")
            or ""
        ).strip().lower()
        artifact_id = hashlib.sha256(
            f"{project_id}:{algorithm_id}:{version_id}:{target}:{chip_code}:{digest}".encode("utf-8")
        ).hexdigest()[:32]
        row = self.repository.upsert({
            "artifact_id": artifact_id,
            "project_id": str(project_id),
            "algorithm_id": str(algorithm_id),
            "version_id": str(version_id),
            "artifact_kind": str(artifact_kind or "original"),
            "target": str(target or "original"),
            "chip_code": chip_code,
            "conversion_job_id": "",
            "file_name": Path(str(file_name or "model.pt")).name,
            "source_path": str(source_path or ""),
            "sha256": digest,
            "size_bytes": expected_size,
            "metadata": artifact_metadata,
        })
        uploaded = self.repository.patch(
            str(row["artifact_id"]),
            storage_source_id=source_id,
            object_key=key,
            storage_status="UPLOADED",
            storage_error="",
            uploaded_at=utc_now(),
        )
        public_url = self.public_url(uploaded)
        if public_url:
            uploaded = self.repository.patch(str(row["artifact_id"]), public_url=public_url)
        return uploaded

    def ingest_version(self, project_id: str, algorithm: Mapping[str, Any], version: Mapping[str, Any]) -> dict[str, int]:
        summary = {"discovered": 0, "uploaded": 0, "failed": 0, "pending": 0}
        for item in self.discover_version_artifacts(project_id, algorithm, version):
            summary["discovered"] += 1
            row = self.ensure_uploaded(item)
            status = str(row.get("storage_status") or "PENDING").upper()
            if status == "UPLOADED":
                summary["uploaded"] += 1
            elif status == "FAILED":
                summary["failed"] += 1
            else:
                summary["pending"] += 1
        return summary

    def run_auto_upload_once(self) -> dict[str, int]:
        summary = {"versions": 0, "discovered": 0, "uploaded": 0, "failed": 0, "pending": 0}
        config = self.repository.config()
        if not bool(config.get("auto_upload_enabled")) or not str(config.get("storage_source_id") or "").strip():
            return summary
        projects = _json_load(self.data_dir / "projects.json", [])
        if not isinstance(projects, list):
            return summary
        for project in projects:
            project_id = str(project.get("id") or "") if isinstance(project, dict) else ""
            if not project_id:
                continue
            for algorithm in list_algorithms(self.algorithms_file(project_id)):
                for version in algorithm.get("versions") or []:
                    if not isinstance(version, dict) or version.get("artifact_verified") is not True:
                        continue
                    summary["versions"] += 1
                    current = self.ingest_version(project_id, algorithm, version)
                    for key in ("discovered", "uploaded", "failed", "pending"):
                        summary[key] += current[key]
        return summary

    def retry(self, artifact_id: str) -> dict[str, Any]:
        row = self.repository.get(artifact_id)
        if row is None:
            raise PlatformError("MODEL_ARTIFACT_NOT_FOUND", "模型资产不存在", artifact_id, "请刷新模型资产列表。", 404)
        discovered = {
            "artifact_id": row["artifact_id"], "project_id": row["project_id"], "algorithm_id": row["algorithm_id"],
            "version_id": row["version_id"], "artifact_kind": row["artifact_kind"], "target": row["target"],
            "conversion_job_id": row.get("conversion_job_id") or "", "file_name": row["file_name"],
            "source_path": row["source_path"], "sha256": row["sha256"], "size_bytes": row["size_bytes"],
            "metadata": row.get("metadata") or {},
        }
        return self.ensure_uploaded(discovered, force=True)

    def download(self, artifact_id: str):
        row = self.repository.get(artifact_id)
        if row is None or str(row.get("storage_status") or "").upper() != "UPLOADED":
            raise PlatformError("MODEL_ARTIFACT_NOT_FOUND", "模型资产不存在或尚未上传", artifact_id, "请重新执行资产上传。", 404)
        provider = self._provider(str(row["project_id"]), str(row["storage_source_id"]))
        return row, provider
