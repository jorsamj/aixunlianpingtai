from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from pathlib import Path
from typing import Any, Mapping, Sequence

from .errors import PlatformError


SCHEMA_VERSION = 1
DB_FILENAME = "algorithms.sqlite3"
BACKUP_FILENAME = "algorithms.json.pre-sql-migration-backup"


class AlgorithmSqlStore:
    """SQL-backed algorithm asset store with lossless JSON migration.

    Public callers keep using the legacy algorithm object shape. Internally the
    algorithm, version and external-analysis records live in relational tables.
    Unknown/future fields are retained in payload_json so migrations remain
    forward compatible.
    """

    def __init__(self, json_path: Path):
        self.json_path = Path(json_path)
        self.project_dir = self.json_path.parent
        self.db_path = self.project_dir / DB_FILENAME
        self.backup_path = self.project_dir / BACKUP_FILENAME
        self.project_id = self.project_dir.name
        self.project_dir.mkdir(parents=True, exist_ok=True)

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def ensure_ready(self) -> None:
        with self._connect() as conn:
            self._ensure_schema(conn)
            migrated = self._meta(conn, "legacy_json_migrated") == "1"
            count = int(conn.execute("SELECT COUNT(*) FROM algorithms").fetchone()[0])
            if not migrated and count == 0 and self.json_path.exists():
                legacy = self._read_legacy_json()
                self._backup_legacy_json()
                self._replace_all(conn, legacy)
                self._set_meta(conn, "legacy_json_migrated", "1")
                self._set_meta(conn, "legacy_json_sha256", self._sha256_file(self.json_path))
                self._set_meta(conn, "schema_version", str(SCHEMA_VERSION))
            elif not migrated:
                self._set_meta(conn, "legacy_json_migrated", "1")
                self._set_meta(conn, "schema_version", str(SCHEMA_VERSION))

    def read_all(self) -> list[dict]:
        self.ensure_ready()
        with self._connect() as conn:
            algorithm_rows = conn.execute(
                "SELECT * FROM algorithms WHERE project_id=? ORDER BY sort_index ASC, created_at DESC, id ASC",
                (self.project_id,),
            ).fetchall()
            result: list[dict] = []
            for row in algorithm_rows:
                item = self._json_object(row["payload_json"])
                item.update({
                    "id": row["id"],
                    "name": row["name"],
                    "remark": row["remark"] or "",
                    "industry": row["industry"] or "",
                    "algorithm_type": row["algorithm_type"] or "",
                    "current_version_id": row["current_version_id"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                })
                self._overlay_optional(item, row, (
                    "source_type", "provider_type", "external_product_id", "external_product_code",
                    "external_category_id", "external_analysis_id", "external_active",
                    "master_data_readonly", "external_last_synced_at",
                ))
                versions = conn.execute(
                    "SELECT * FROM algorithm_versions WHERE algorithm_id=? ORDER BY sort_index ASC, id ASC",
                    (row["id"],),
                ).fetchall()
                item["versions"] = [self._version_from_row(v) for v in versions]
                analyses = conn.execute(
                    "SELECT * FROM algorithm_external_analyses WHERE algorithm_id=? ORDER BY sort_index ASC, external_analysis_id ASC",
                    (row["id"],),
                ).fetchall()
                if analyses:
                    item["external_analyses"] = [self._analysis_from_row(a) for a in analyses]
                    item["external_analysis_ids"] = [str(a["external_analysis_id"]) for a in analyses]
                item.setdefault("version_operations", [])
                result.append(item)
            return result

    def replace_all(self, algorithms: Sequence[Mapping[str, Any]]) -> None:
        self.ensure_ready()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                self._replace_all(conn, algorithms)
                self._set_meta(conn, "schema_version", str(SCHEMA_VERSION))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def migration_status(self) -> dict[str, Any]:
        self.ensure_ready()
        with self._connect() as conn:
            algorithm_count = int(conn.execute("SELECT COUNT(*) FROM algorithms").fetchone()[0])
            version_count = int(conn.execute("SELECT COUNT(*) FROM algorithm_versions").fetchone()[0])
            analysis_count = int(conn.execute("SELECT COUNT(*) FROM algorithm_external_analyses").fetchone()[0])
            return {
                "backend": "sqlite",
                "db_path": str(self.db_path),
                "legacy_json_path": str(self.json_path),
                "legacy_backup_path": str(self.backup_path),
                "legacy_backup_exists": self.backup_path.exists(),
                "algorithm_count": algorithm_count,
                "version_count": version_count,
                "external_analysis_count": analysis_count,
                "schema_version": int(self._meta(conn, "schema_version") or SCHEMA_VERSION),
                "legacy_json_migrated": self._meta(conn, "legacy_json_migrated") == "1",
            }

    def _ensure_schema(self, conn: sqlite3.Connection) -> None:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS algorithm_store_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS algorithms (
                id TEXT PRIMARY KEY,
                project_id TEXT NOT NULL,
                name TEXT NOT NULL,
                remark TEXT NOT NULL DEFAULT '',
                industry TEXT NOT NULL DEFAULT '',
                algorithm_type TEXT NOT NULL DEFAULT '',
                current_version_id TEXT,
                source_type TEXT,
                provider_type TEXT,
                external_product_id TEXT,
                external_product_code TEXT,
                external_category_id TEXT,
                external_analysis_id TEXT,
                external_active INTEGER,
                master_data_readonly INTEGER,
                external_last_synced_at TEXT,
                created_at TEXT,
                updated_at TEXT,
                sort_index INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL DEFAULT '{}'
            );

            CREATE TABLE IF NOT EXISTS algorithm_versions (
                id TEXT PRIMARY KEY,
                algorithm_id TEXT NOT NULL,
                version_name TEXT,
                version_no TEXT,
                training_job_id TEXT,
                framework TEXT,
                training_status TEXT,
                stored_path TEXT,
                model_name TEXT,
                artifact_verified INTEGER,
                trainable INTEGER,
                external_analysis_id TEXT,
                external_algo_version_id TEXT,
                external_publish_status TEXT,
                created_at TEXT,
                finished_at TEXT,
                sort_index INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY (algorithm_id) REFERENCES algorithms(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS algorithm_external_analyses (
                algorithm_id TEXT NOT NULL,
                external_analysis_id TEXT NOT NULL,
                analysis_name TEXT,
                analysis_type TEXT,
                is_default INTEGER NOT NULL DEFAULT 0,
                active INTEGER NOT NULL DEFAULT 1,
                compute_platform_ids_json TEXT NOT NULL DEFAULT '[]',
                sort_index INTEGER NOT NULL DEFAULT 0,
                payload_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (algorithm_id, external_analysis_id),
                FOREIGN KEY (algorithm_id) REFERENCES algorithms(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_algorithms_project ON algorithms(project_id);
            CREATE INDEX IF NOT EXISTS idx_algorithms_source ON algorithms(project_id, source_type);
            CREATE INDEX IF NOT EXISTS idx_algorithms_external_product ON algorithms(provider_type, external_product_id);
            CREATE INDEX IF NOT EXISTS idx_algorithms_external_category ON algorithms(external_category_id);
            CREATE INDEX IF NOT EXISTS idx_versions_algorithm ON algorithm_versions(algorithm_id, sort_index);
            CREATE INDEX IF NOT EXISTS idx_versions_training_job ON algorithm_versions(training_job_id);
            CREATE INDEX IF NOT EXISTS idx_versions_external_id ON algorithm_versions(external_algo_version_id);
            """
        )
        self._set_meta(conn, "schema_version", str(SCHEMA_VERSION))

    def _replace_all(self, conn: sqlite3.Connection, algorithms: Sequence[Mapping[str, Any]]) -> None:
        rows = [dict(item) for item in algorithms]
        ids = [str(item.get("id") or "").strip() for item in rows]
        if any(not value for value in ids):
            raise PlatformError(
                "ALGORITHM_ID_REQUIRED",
                "算法数据缺少 ID，无法写入数据库",
                "SQL 迁移要求每个算法都保留原有稳定 ID。",
                "请修复 algorithms.json 中缺失 ID 的记录后重新迁移。",
                409,
            )
        if len(set(ids)) != len(ids):
            raise PlatformError(
                "ALGORITHM_ID_DUPLICATED",
                "算法 ID 重复，无法写入数据库",
                "algorithms.json 中存在重复算法 ID。",
                "请先修复重复 ID，避免历史训练关系串联错误。",
                409,
            )

        conn.execute("DELETE FROM algorithm_external_analyses")
        conn.execute("DELETE FROM algorithm_versions")
        conn.execute("DELETE FROM algorithms WHERE project_id=?", (self.project_id,))

        version_ids: set[str] = set()
        for index, item in enumerate(rows):
            algorithm_id = str(item["id"])
            versions = [dict(v) for v in (item.get("versions") or []) if isinstance(v, Mapping)]
            analyses = [dict(a) for a in (item.get("external_analyses") or []) if isinstance(a, Mapping)]
            payload = dict(item)
            payload.pop("versions", None)
            payload.pop("external_analyses", None)
            payload.pop("external_analysis_ids", None)

            conn.execute(
                """INSERT INTO algorithms (
                    id, project_id, name, remark, industry, algorithm_type, current_version_id,
                    source_type, provider_type, external_product_id, external_product_code,
                    external_category_id, external_analysis_id, external_active, master_data_readonly,
                    external_last_synced_at, created_at, updated_at, sort_index, payload_json
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    algorithm_id,
                    self.project_id,
                    str(item.get("name") or ""),
                    str(item.get("remark") or ""),
                    str(item.get("industry") or ""),
                    str(item.get("algorithm_type") or ""),
                    self._nullable_text(item.get("current_version_id")),
                    self._nullable_text(item.get("source_type")),
                    self._nullable_text(item.get("provider_type")),
                    self._nullable_text(item.get("external_product_id")),
                    self._nullable_text(item.get("external_product_code")),
                    self._nullable_text(item.get("external_category_id")),
                    self._nullable_text(item.get("external_analysis_id")),
                    self._nullable_bool(item.get("external_active")),
                    self._nullable_bool(item.get("master_data_readonly")),
                    self._nullable_text(item.get("external_last_synced_at")),
                    self._nullable_text(item.get("created_at")),
                    self._nullable_text(item.get("updated_at")),
                    index,
                    self._dumps(payload),
                ),
            )

            for version_index, version in enumerate(versions):
                version_id = str(version.get("id") or "").strip()
                if not version_id:
                    raise PlatformError(
                        "ALGORITHM_VERSION_ID_REQUIRED",
                        "算法版本缺少 ID，无法迁移",
                        f"算法 {algorithm_id} 存在没有 ID 的版本。",
                        "请先修复历史版本数据后重新迁移。",
                        409,
                    )
                if version_id in version_ids:
                    raise PlatformError(
                        "ALGORITHM_VERSION_ID_DUPLICATED",
                        "算法版本 ID 重复，无法迁移",
                        version_id,
                        "请修复重复版本 ID，避免转换、发布和报告引用错误。",
                        409,
                    )
                version_ids.add(version_id)
                conn.execute(
                    """INSERT INTO algorithm_versions (
                        id, algorithm_id, version_name, version_no, training_job_id, framework,
                        training_status, stored_path, model_name, artifact_verified, trainable,
                        external_analysis_id, external_algo_version_id, external_publish_status,
                        created_at, finished_at, sort_index, payload_json
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        version_id,
                        algorithm_id,
                        self._nullable_text(version.get("version_name")),
                        self._nullable_text(version.get("version_no")),
                        self._nullable_text(version.get("task_id") or version.get("job_id") or version.get("training_job_id")),
                        self._nullable_text(version.get("framework")),
                        self._nullable_text(version.get("training_status") or version.get("status")),
                        self._nullable_text(version.get("stored_path")),
                        self._nullable_text(version.get("model_name")),
                        self._nullable_bool(version.get("artifact_verified")),
                        self._nullable_bool(version.get("trainable")),
                        self._nullable_text(version.get("external_analysis_id")),
                        self._nullable_text(version.get("external_algo_version_id")),
                        self._nullable_text(version.get("external_publish_status")),
                        self._nullable_text(version.get("created_at")),
                        self._nullable_text(version.get("finished_at")),
                        version_index,
                        self._dumps(version),
                    ),
                )

            if not analyses:
                analysis_ids = [str(v) for v in (item.get("external_analysis_ids") or []) if str(v or "").strip()]
                analyses = [{"analysis_id": analysis_id} for analysis_id in analysis_ids]
            default_analysis_id = str(item.get("external_analysis_id") or "")
            seen_analysis_ids: set[str] = set()
            for analysis_index, analysis in enumerate(analyses):
                analysis_id = str(analysis.get("analysis_id") or analysis.get("analysisId") or "").strip()
                if not analysis_id or analysis_id in seen_analysis_ids:
                    continue
                seen_analysis_ids.add(analysis_id)
                compute_platform_ids = analysis.get("compute_platform_ids") or analysis.get("computePlatformIds") or []
                conn.execute(
                    """INSERT INTO algorithm_external_analyses (
                        algorithm_id, external_analysis_id, analysis_name, analysis_type,
                        is_default, active, compute_platform_ids_json, sort_index, payload_json
                    ) VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        algorithm_id,
                        analysis_id,
                        self._nullable_text(analysis.get("analysis_name") or analysis.get("analysisName")),
                        self._nullable_text(analysis.get("analysis_type") or analysis.get("analysisType")),
                        1 if analysis_id == default_analysis_id else 0,
                        0 if analysis.get("active") is False else 1,
                        self._dumps(list(compute_platform_ids) if isinstance(compute_platform_ids, (list, tuple, set)) else []),
                        analysis_index,
                        self._dumps(analysis),
                    ),
                )

    def _version_from_row(self, row: sqlite3.Row) -> dict:
        value = self._json_object(row["payload_json"])
        value["id"] = row["id"]
        self._overlay_optional(value, row, (
            "version_name", "version_no", "framework", "training_status", "stored_path", "model_name",
            "artifact_verified", "trainable", "external_analysis_id", "external_algo_version_id",
            "external_publish_status", "created_at", "finished_at",
        ))
        if row["training_job_id"] and not value.get("task_id") and not value.get("job_id"):
            value["task_id"] = row["training_job_id"]
        return value

    def _analysis_from_row(self, row: sqlite3.Row) -> dict:
        value = self._json_object(row["payload_json"])
        value["analysis_id"] = row["external_analysis_id"]
        if row["analysis_name"] is not None:
            value["analysis_name"] = row["analysis_name"]
        if row["analysis_type"] is not None:
            value["analysis_type"] = row["analysis_type"]
        compute_platform_ids = self._json_list(row["compute_platform_ids_json"])
        if "compute_platform_ids" in value or compute_platform_ids:
            value["compute_platform_ids"] = compute_platform_ids
        if "active" in value or not bool(row["active"]):
            value["active"] = bool(row["active"])
        return value

    def _read_legacy_json(self) -> list[dict]:
        try:
            value = json.loads(self.json_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise PlatformError(
                "ALGORITHM_STORE_INVALID",
                "算法资产文件无法读取，SQL 迁移已停止",
                str(error),
                "请先恢复有效的 algorithms.json；系统不会覆盖损坏的历史数据。",
                500,
            ) from error
        if not isinstance(value, list):
            raise PlatformError(
                "ALGORITHM_STORE_INVALID",
                "算法资产文件格式不正确，SQL 迁移已停止",
                "algorithms.json 根节点必须是数组。",
                "请恢复正确的历史算法文件后重试。",
                500,
            )
        return [dict(row) for row in value if isinstance(row, Mapping)]

    def _backup_legacy_json(self) -> None:
        if self.backup_path.exists() or not self.json_path.exists():
            return
        shutil.copy2(self.json_path, self.backup_path)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)

    @staticmethod
    def _json_object(value: Any) -> dict:
        try:
            decoded = json.loads(value or "{}")
        except (TypeError, json.JSONDecodeError):
            return {}
        return decoded if isinstance(decoded, dict) else {}

    @staticmethod
    def _json_list(value: Any) -> list:
        try:
            decoded = json.loads(value or "[]")
        except (TypeError, json.JSONDecodeError):
            return []
        return decoded if isinstance(decoded, list) else []

    @staticmethod
    def _nullable_text(value: Any) -> str | None:
        if value in (None, ""):
            return None
        return str(value)

    @staticmethod
    def _nullable_bool(value: Any) -> int | None:
        if value is None:
            return None
        return 1 if bool(value) else 0

    @staticmethod
    def _overlay_optional(target: dict, row: sqlite3.Row, keys: Sequence[str]) -> None:
        for key in keys:
            value = row[key]
            if value is None:
                continue
            if key in {"external_active", "master_data_readonly", "artifact_verified", "trainable"}:
                target[key] = bool(value)
            else:
                target[key] = value

    @staticmethod
    def _meta(conn: sqlite3.Connection, key: str) -> str | None:
        row = conn.execute("SELECT value FROM algorithm_store_meta WHERE key=?", (key,)).fetchone()
        return str(row[0]) if row is not None else None

    @staticmethod
    def _set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
        conn.execute(
            "INSERT INTO algorithm_store_meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (key, str(value)),
        )
