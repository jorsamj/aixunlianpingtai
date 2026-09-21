from __future__ import annotations

import hashlib
import json
import shutil
import sqlite3
from contextlib import closing
from pathlib import Path
from typing import Any, Mapping, Sequence

from filelock import FileLock

from .errors import PlatformError


SCHEMA_VERSION = 2
DB_FILENAME = "algorithms.sqlite3"
BACKUP_FILENAME = "algorithms.json.pre-sql-migration-backup"
_INIT_LOCK_TIMEOUT = 30
_LEGACY_REMOTE_VERSION_FIELDS = frozenset({
    "external_algo_version_id",
    "external_publish_status",
})


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
        # Ordinary connections never negotiate persistent journal state. Set
        # the wait policy first so concurrent writers rely on SQLite's own
        # busy handling instead of racing during connection initialization.
        conn.execute("PRAGMA busy_timeout=30000")
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    def _initialization_complete(self, conn: sqlite3.Connection) -> bool:
        try:
            return (
                self._meta(conn, "schema_version") == str(SCHEMA_VERSION)
                and self._meta(conn, "legacy_json_migrated") == "1"
            )
        except sqlite3.OperationalError as error:
            if "no such table" in str(error).lower():
                return False
            raise

    def _ready_without_init_lock(self) -> bool:
        """Return ready-state using a short, read-only probe.

        A fully initialized database is the common case. Avoid taking the
        cross-process init FileLock on every CRUD call; if the probe cannot
        prove readiness quickly, fall back to the locked initialization path.
        """
        if not self.db_path.is_file():
            return False
        try:
            with closing(
                sqlite3.connect(self.db_path, timeout=0.25, isolation_level=None)
            ) as conn:
                conn.row_factory = sqlite3.Row
                conn.execute("PRAGMA busy_timeout=250")
                mode = str(
                    conn.execute("PRAGMA journal_mode").fetchone()[0]
                ).lower()
                return mode == "wal" and self._initialization_complete(conn)
        except sqlite3.Error:
            return False

    def ensure_ready(self) -> None:
        # The steady-state path is read-only and lock-free across processes.
        # Only an uninitialized/uncertain store enters the persistent init lock.
        if self._ready_without_init_lock():
            return

        # WAL transition, schema bootstrap and legacy migration are persistent
        # database initialization. Keep them under one store-owned cross-process
        # lock; normal CRUD transactions remain independently concurrent.
        lock = FileLock(
            str(self.db_path.resolve()) + ".init.lock",
            timeout=_INIT_LOCK_TIMEOUT,
        )
        with lock:
            with closing(self._connect()) as conn:
                try:
                    mode = str(
                        conn.execute("PRAGMA journal_mode").fetchone()[0]
                    ).lower()
                    if mode == "wal" and self._initialization_complete(conn):
                        return
                    if mode != "wal":
                        mode = str(
                            conn.execute("PRAGMA journal_mode=WAL").fetchone()[0]
                        ).lower()
                    if mode != "wal":
                        raise RuntimeError(
                            f"algorithm store requires WAL mode, got {mode}"
                        )

                    self._ensure_schema(conn)
                    migrated = self._meta(conn, "legacy_json_migrated") == "1"
                    count = int(
                        conn.execute("SELECT COUNT(*) FROM algorithms").fetchone()[0]
                    )
                    if not migrated and count == 0 and self.json_path.exists():
                        legacy = self._read_legacy_json()
                        self._backup_legacy_json()
                        self._replace_all(
                            conn,
                            legacy,
                            allow_legacy_remote_fields=True,
                        )
                        self._set_meta(conn, "legacy_json_migrated", "1")
                        self._set_meta(
                            conn,
                            "legacy_json_sha256",
                            self._sha256_file(self.json_path),
                        )
                        self._set_meta(conn, "schema_version", str(SCHEMA_VERSION))
                    elif not migrated:
                        self._set_meta(conn, "legacy_json_migrated", "1")
                        self._set_meta(conn, "schema_version", str(SCHEMA_VERSION))
                    conn.commit()
                except Exception:
                    if conn.in_transaction:
                        conn.rollback()
                    raise

    def read_all(self) -> list[dict]:
        self.ensure_ready()
        with self._connect() as conn:
            algorithm_rows = conn.execute(
                "SELECT * FROM algorithms WHERE project_id=? ORDER BY sort_index ASC, created_at DESC, id ASC",
                (self.project_id,),
            ).fetchall()
            if not algorithm_rows:
                return []

            # Prefetch child rows once for the project instead of issuing two
            # extra SELECTs per algorithm. This keeps the algorithm-list read
            # path O(1) in SQL round-trips as the catalog grows.
            version_rows = conn.execute(
                """SELECT versions.*
                   FROM algorithm_versions AS versions
                   JOIN algorithms AS algorithms
                     ON algorithms.id=versions.algorithm_id
                   WHERE algorithms.project_id=?
                   ORDER BY versions.algorithm_id ASC,
                            versions.sort_index ASC,
                            versions.id ASC""",
                (self.project_id,),
            ).fetchall()
            analysis_rows = conn.execute(
                """SELECT analyses.*
                   FROM algorithm_external_analyses AS analyses
                   JOIN algorithms AS algorithms
                     ON algorithms.id=analyses.algorithm_id
                   WHERE algorithms.project_id=?
                   ORDER BY analyses.algorithm_id ASC,
                            analyses.sort_index ASC,
                            analyses.external_analysis_id ASC""",
                (self.project_id,),
            ).fetchall()
            versions_by_algorithm: dict[str, list[sqlite3.Row]] = {}
            for version_row in version_rows:
                versions_by_algorithm.setdefault(
                    str(version_row["algorithm_id"]), []
                ).append(version_row)
            analyses_by_algorithm: dict[str, list[sqlite3.Row]] = {}
            for analysis_row in analysis_rows:
                analyses_by_algorithm.setdefault(
                    str(analysis_row["algorithm_id"]), []
                ).append(analysis_row)

            result: list[dict] = []
            for row in algorithm_rows:
                algorithm_id = str(row["id"])
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
                if str(item.get("source_type") or "").upper() == "EXTERNAL":
                    item.setdefault("external_analysis_id", "")
                versions = versions_by_algorithm.get(algorithm_id, [])
                item["versions"] = [self._version_from_row(v) for v in versions]
                analyses = analyses_by_algorithm.get(algorithm_id, [])
                if analyses:
                    item["external_analyses"] = [self._analysis_from_row(a) for a in analyses]
                    item["external_analysis_ids"] = self._trainable_analysis_ids(item, analyses)
                elif str(item.get("source_type") or "").upper() == "EXTERNAL":
                    item.setdefault("external_analysis_ids", [])
                item.setdefault("version_operations", [])
                result.append(item)
            return result

    def replace_all(self, algorithms: Sequence[Mapping[str, Any]]) -> None:
        self.ensure_ready()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                preserved_legacy_remote_fields: dict[str, dict[str, Any]] = {}
                for row in conn.execute("SELECT * FROM algorithm_versions").fetchall():
                    current = self._version_from_row(row)
                    preserved_legacy_remote_fields[str(row["id"])] = {
                        field: current.get(field)
                        for field in _LEGACY_REMOTE_VERSION_FIELDS
                    }
                self._replace_all(
                    conn,
                    algorithms,
                    preserved_legacy_remote_fields=preserved_legacy_remote_fields,
                )
                self._set_meta(conn, "schema_version", str(SCHEMA_VERSION))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def read_one(self, algorithm_id: str) -> dict | None:
        self.ensure_ready()
        with self._connect() as conn:
            return self._read_one_conn(conn, str(algorithm_id))

    def create_algorithm(self, item: Mapping[str, Any]) -> dict:
        self.ensure_ready()
        value = dict(item)
        algorithm_id = str(value.get("id") or "").strip()
        name = str(value.get("name") or "").strip()
        if not algorithm_id or not name:
            raise PlatformError("ALGORITHM_ID_REQUIRED", "算法数据不完整", "创建算法需要稳定 ID 和名称。", "请刷新后重试。", 409)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                duplicate = conn.execute(
                    "SELECT id FROM algorithms WHERE project_id=? AND lower(trim(name))=lower(trim(?)) LIMIT 1",
                    (self.project_id, name),
                ).fetchone()
                if duplicate is not None:
                    raise PlatformError("ALGORITHM_NAME_EXISTS", "算法名称已存在", f"当前项目中已经存在名为“{name}”的算法。", "请使用不同名称，或编辑已有算法。", 409)
                sort_index = int(conn.execute(
                    "SELECT COALESCE(MIN(sort_index),0)-1 FROM algorithms WHERE project_id=?",
                    (self.project_id,),
                ).fetchone()[0])
                self._insert_algorithm_conn(conn, value, sort_index)
                self._replace_analyses_conn(conn, algorithm_id, value)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return value

    def patch_algorithm(self, algorithm_id: str, patch: Mapping[str, Any], *, replace_analyses: bool = False) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                existing = self._read_one_conn(conn, algorithm_id)
                if existing is None:
                    raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                merged = dict(existing)
                merged.update(dict(patch))
                proposed_name = str(merged.get("name") or "").strip()
                duplicate = conn.execute(
                    "SELECT id FROM algorithms WHERE project_id=? AND id<>? AND lower(trim(name))=lower(trim(?)) LIMIT 1",
                    (self.project_id, algorithm_id, proposed_name),
                ).fetchone()
                if duplicate is not None:
                    raise PlatformError("ALGORITHM_NAME_EXISTS", "算法名称已存在", f"算法名称“{proposed_name}”已被使用。", "请使用不同名称。", 409)
                self._update_algorithm_conn(conn, merged)
                if replace_analyses:
                    self._replace_analyses_conn(conn, algorithm_id, merged)
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return merged

    def delete_algorithm(self, algorithm_id: str) -> None:
        self.ensure_ready()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                cursor = conn.execute("DELETE FROM algorithms WHERE project_id=? AND id=?", (self.project_id, str(algorithm_id)))
                if cursor.rowcount != 1:
                    raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def attach_version(self, algorithm_id: str, version: Mapping[str, Any]) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        value = dict(version)
        version_id = str(value.get("id") or "").strip()
        if not version_id:
            raise PlatformError("ALGORITHM_VERSION_ID_REQUIRED", "算法版本缺少 ID", algorithm_id, "请重新归档训练版本。", 409)
        task_id = str(value.get("task_id") or value.get("job_id") or value.get("training_job_id") or "").strip()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                if conn.execute("SELECT 1 FROM algorithms WHERE project_id=? AND id=?", (self.project_id, algorithm_id)).fetchone() is None:
                    raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                if task_id:
                    duplicate = conn.execute(
                        "SELECT * FROM algorithm_versions WHERE algorithm_id=? AND training_job_id=? LIMIT 1",
                        (algorithm_id, task_id),
                    ).fetchone()
                    if duplicate is not None:
                        conn.rollback()
                        return self._version_from_row(duplicate)
                if conn.execute("SELECT 1 FROM algorithm_versions WHERE id=?", (version_id,)).fetchone() is not None:
                    raise PlatformError("ALGORITHM_VERSION_ID_DUPLICATED", "算法版本 ID 已存在", version_id, "请检查训练归档幂等状态。", 409)
                sort_index = int(conn.execute(
                    "SELECT COALESCE(MIN(sort_index),0)-1 FROM algorithm_versions WHERE algorithm_id=?",
                    (algorithm_id,),
                ).fetchone()[0])
                self._insert_version_conn(conn, algorithm_id, value, sort_index)
                updated_at = str(value.get("finished_at") or value.get("created_at") or "") or None
                conn.execute(
                    "UPDATE algorithms SET current_version_id=?, updated_at=COALESCE(?,updated_at) WHERE project_id=? AND id=?",
                    (version_id, updated_at, self.project_id, algorithm_id),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return value

    def patch_version(self, algorithm_id: str, version_id: str, patch: Mapping[str, Any], *, now: str) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        version_id = str(version_id)
        self._reject_legacy_remote_field_mutation(patch)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, version_id)).fetchone()
                if row is None:
                    if conn.execute("SELECT 1 FROM algorithms WHERE project_id=? AND id=?", (self.project_id, algorithm_id)).fetchone() is None:
                        raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                    raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {version_id}。", "请刷新版本列表后重试。", 404)
                value = self._version_from_row(row)
                value.update(dict(patch))
                value["updated_at"] = now
                self._update_version_conn(
                    conn,
                    algorithm_id,
                    value,
                    row["sort_index"],
                    preserved_legacy_remote_fields={
                        field: value.get(field)
                        for field in _LEGACY_REMOTE_VERSION_FIELDS
                    },
                )
                conn.execute("UPDATE algorithms SET updated_at=? WHERE project_id=? AND id=?", (now, self.project_id, algorithm_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return value

    def rollback_version(
        self,
        algorithm_id: str,
        target_version_id: str,
        *,
        expected_current_version_id: str,
        operation: Mapping[str, Any],
        now: str,
        delete_current_version: bool,
    ) -> dict | None:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        target_version_id = str(target_version_id)
        expected_current_version_id = str(expected_current_version_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                algorithm = self._read_one_conn(conn, algorithm_id)
                if algorithm is None:
                    raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                persisted_current = str(algorithm.get("current_version_id") or "")
                if persisted_current and persisted_current != expected_current_version_id:
                    raise PlatformError("ALGORITHM_VERSION_CONFLICT", "算法当前版本已经发生变化", f"请求基于 {expected_current_version_id}，当前实际版本为 {persisted_current}。", "请刷新算法版本列表后重新确认。", 409)
                target = conn.execute("SELECT 1 FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, target_version_id)).fetchone()
                if target is None:
                    raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {target_version_id}。", "请刷新版本列表后重试。", 404)
                current_row = conn.execute("SELECT * FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, expected_current_version_id)).fetchone()
                if current_row is None:
                    raise PlatformError("ALGORITHM_VERSION_CONFLICT", "当前版本记录已发生变化", expected_current_version_id, "请刷新后重试。", 409)
                removed = self._version_from_row(current_row) if delete_current_version else None
                payload = self._json_object(conn.execute("SELECT payload_json FROM algorithms WHERE id=?", (algorithm_id,)).fetchone()[0])
                operations = list(payload.get("version_operations") or [])
                operations.append(dict(operation))
                payload["version_operations"] = operations
                conn.execute(
                    "UPDATE algorithms SET current_version_id=?, updated_at=?, payload_json=? WHERE project_id=? AND id=?",
                    (target_version_id, now, self._dumps(payload), self.project_id, algorithm_id),
                )
                if delete_current_version:
                    conn.execute("DELETE FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, expected_current_version_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return removed

    def delete_version_with_operation(
        self,
        algorithm_id: str,
        version_id: str,
        *,
        expected_current_version_id: str | None,
        operation: Mapping[str, Any],
        now: str,
    ) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        version_id = str(version_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT * FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, version_id)).fetchone()
                if row is None:
                    raise PlatformError("ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {version_id}。", "请刷新版本列表后重试。", 404)
                current = conn.execute("SELECT current_version_id,payload_json FROM algorithms WHERE project_id=? AND id=?", (self.project_id, algorithm_id)).fetchone()
                if current is None:
                    raise PlatformError("ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。", "请刷新算法列表后重试。", 404)
                persisted_current = str(current["current_version_id"] or "")
                if persisted_current and expected_current_version_id is not None and persisted_current != str(expected_current_version_id):
                    raise PlatformError("ALGORITHM_VERSION_CONFLICT", "算法当前版本已经发生变化", f"请求基于 {expected_current_version_id}，当前实际版本为 {persisted_current}。", "请刷新后重试。", 409)
                if version_id == persisted_current:
                    raise PlatformError("ALGORITHM_CURRENT_VERSION_DELETE_FORBIDDEN", "不能直接删除当前版本", f"版本 {version_id} 当前正在作为算法默认版本。", "请先回退到另一个有效版本，再删除该版本。", 409)
                payload = self._json_object(current["payload_json"])
                operations = list(payload.get("version_operations") or [])
                operations.append(dict(operation))
                payload["version_operations"] = operations
                conn.execute("DELETE FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, version_id))
                conn.execute("UPDATE algorithms SET updated_at=?, payload_json=? WHERE project_id=? AND id=?", (now, self._dumps(payload), self.project_id, algorithm_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return self._version_from_row(row)

    def update_version_operation(self, algorithm_id: str, operation_id: str, patch: Mapping[str, Any]) -> None:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                row = conn.execute("SELECT payload_json FROM algorithms WHERE project_id=? AND id=?", (self.project_id, algorithm_id)).fetchone()
                if row is None:
                    raise PlatformError("ALGORITHM_CLEANUP_STATE_LOST", "清理状态无法保存", f"算法 {algorithm_id} 不存在。", "请检查版本操作审计。", 500)
                payload = self._json_object(row["payload_json"])
                operations = list(payload.get("version_operations") or [])
                operation = next((item for item in operations if str(item.get("id") or "") == str(operation_id)), None)
                if operation is None:
                    raise PlatformError("ALGORITHM_CLEANUP_STATE_LOST", "清理审计不存在", f"找不到操作记录 {operation_id}。", "请检查算法版本操作审计。", 500)
                operation.update(dict(patch))
                payload["version_operations"] = operations
                conn.execute("UPDATE algorithms SET payload_json=? WHERE project_id=? AND id=?", (self._dumps(payload), self.project_id, algorithm_id))
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def sync_external_algorithms(self, incoming: Mapping[str, Mapping[str, Any]], *, provider: str, synced_at: str) -> dict[str, int]:
        self.ensure_ready()
        provider = str(provider).upper()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            try:
                rows = conn.execute(
                    "SELECT id,external_product_id FROM algorithms WHERE project_id=? AND upper(COALESCE(source_type,''))='EXTERNAL' AND upper(COALESCE(provider_type,''))=?",
                    (self.project_id, provider),
                ).fetchall()
                existing = {str(row["external_product_id"] or ""): str(row["id"]) for row in rows if row["external_product_id"]}
                added = updated = unchanged = inactivated = 0
                for product_id, master_raw in incoming.items():
                    master = dict(master_raw)
                    algorithm_id = existing.get(str(product_id))
                    if not algorithm_id:
                        item = {**master, "current_version_id": None, "version_operations": [], "versions": [], "created_at": synced_at, "updated_at": synced_at}
                        sort_index = int(conn.execute("SELECT COALESCE(MIN(sort_index),0)-1 FROM algorithms WHERE project_id=?", (self.project_id,)).fetchone()[0])
                        self._insert_algorithm_conn(conn, item, sort_index)
                        self._replace_analyses_conn(conn, str(item["id"]), item)
                        added += 1
                        continue
                    current = self._read_one_conn(conn, algorithm_id)
                    if current is None:
                        continue
                    changed = any(current.get(key) != value for key, value in master.items())
                    merged = dict(current)
                    merged.update(master)
                    # external master data must never rewrite the platform's stable algorithm id
                    merged["id"] = algorithm_id
                    if changed:
                        merged["updated_at"] = synced_at
                        self._update_algorithm_conn(conn, merged)
                        self._replace_analyses_conn(conn, algorithm_id, merged)
                        updated += 1
                    else:
                        unchanged += 1
                incoming_ids = {str(key) for key in incoming}
                for row in rows:
                    pid = str(row["external_product_id"] or "")
                    if pid in incoming_ids:
                        continue
                    current = self._read_one_conn(conn, str(row["id"]))
                    if current is not None and current.get("external_active") is not False:
                        current["external_active"] = False
                        current["external_last_synced_at"] = synced_at
                        current["updated_at"] = synced_at
                        self._update_algorithm_conn(conn, current)
                        inactivated += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"added": added, "updated": updated, "unchanged": unchanged, "inactivated": inactivated, "total": len(incoming)}

    def _read_one_conn(self, conn: sqlite3.Connection, algorithm_id: str) -> dict | None:
        row = conn.execute("SELECT * FROM algorithms WHERE project_id=? AND id=?", (self.project_id, str(algorithm_id))).fetchone()
        if row is None:
            return None
        item = self._json_object(row["payload_json"])
        item.update({"id": row["id"], "name": row["name"], "remark": row["remark"] or "", "industry": row["industry"] or "", "algorithm_type": row["algorithm_type"] or "", "current_version_id": row["current_version_id"], "created_at": row["created_at"], "updated_at": row["updated_at"]})
        self._overlay_optional(item, row, ("source_type", "provider_type", "external_product_id", "external_product_code", "external_category_id", "external_analysis_id", "external_active", "master_data_readonly", "external_last_synced_at"))
        if str(item.get("source_type") or "").upper() == "EXTERNAL":
            item.setdefault("external_analysis_id", "")
        versions = conn.execute("SELECT * FROM algorithm_versions WHERE algorithm_id=? ORDER BY sort_index ASC, id ASC", (row["id"],)).fetchall()
        item["versions"] = [self._version_from_row(v) for v in versions]
        analyses = conn.execute("SELECT * FROM algorithm_external_analyses WHERE algorithm_id=? ORDER BY sort_index ASC, external_analysis_id ASC", (row["id"],)).fetchall()
        if analyses:
            item["external_analyses"] = [self._analysis_from_row(a) for a in analyses]
            item["external_analysis_ids"] = self._trainable_analysis_ids(item, analyses)
        elif str(item.get("source_type") or "").upper() == "EXTERNAL":
            item.setdefault("external_analysis_ids", [])
        item.setdefault("version_operations", [])
        return item

    def _algorithm_payload(self, item: Mapping[str, Any]) -> dict:
        payload = dict(item)
        payload.pop("versions", None)
        payload.pop("external_analyses", None)
        for key in ("id", "name", "remark", "industry", "algorithm_type", "current_version_id", "source_type", "provider_type", "external_product_id", "external_product_code", "external_category_id", "external_analysis_id", "external_active", "master_data_readonly", "external_last_synced_at", "created_at", "updated_at"):
            payload.pop(key, None)
        return payload

    def _insert_algorithm_conn(self, conn: sqlite3.Connection, item: Mapping[str, Any], sort_index: int) -> None:
        conn.execute(
            """INSERT INTO algorithms (id,project_id,name,remark,industry,algorithm_type,current_version_id,source_type,provider_type,external_product_id,external_product_code,external_category_id,external_analysis_id,external_active,master_data_readonly,external_last_synced_at,created_at,updated_at,sort_index,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(item.get("id")), self.project_id, str(item.get("name") or ""), str(item.get("remark") or ""), str(item.get("industry") or ""), str(item.get("algorithm_type") or ""), self._nullable_text(item.get("current_version_id")), self._nullable_text(item.get("source_type")), self._nullable_text(item.get("provider_type")), self._nullable_text(item.get("external_product_id")), self._nullable_text(item.get("external_product_code")), self._nullable_text(item.get("external_category_id")), self._nullable_text(item.get("external_analysis_id")), self._nullable_bool(item.get("external_active")), self._nullable_bool(item.get("master_data_readonly")), self._nullable_text(item.get("external_last_synced_at")), self._nullable_text(item.get("created_at")), self._nullable_text(item.get("updated_at")), int(sort_index), self._dumps(self._algorithm_payload(item))),
        )

    def _update_algorithm_conn(self, conn: sqlite3.Connection, item: Mapping[str, Any]) -> None:
        conn.execute(
            """UPDATE algorithms SET name=?,remark=?,industry=?,algorithm_type=?,current_version_id=?,source_type=?,provider_type=?,external_product_id=?,external_product_code=?,external_category_id=?,external_analysis_id=?,external_active=?,master_data_readonly=?,external_last_synced_at=?,created_at=?,updated_at=?,payload_json=? WHERE project_id=? AND id=?""",
            (str(item.get("name") or ""), str(item.get("remark") or ""), str(item.get("industry") or ""), str(item.get("algorithm_type") or ""), self._nullable_text(item.get("current_version_id")), self._nullable_text(item.get("source_type")), self._nullable_text(item.get("provider_type")), self._nullable_text(item.get("external_product_id")), self._nullable_text(item.get("external_product_code")), self._nullable_text(item.get("external_category_id")), self._nullable_text(item.get("external_analysis_id")), self._nullable_bool(item.get("external_active")), self._nullable_bool(item.get("master_data_readonly")), self._nullable_text(item.get("external_last_synced_at")), self._nullable_text(item.get("created_at")), self._nullable_text(item.get("updated_at")), self._dumps(self._algorithm_payload(item)), self.project_id, str(item.get("id"))),
        )

    @staticmethod
    def _reject_legacy_remote_field_mutation(version: Mapping[str, Any]) -> None:
        attempted = sorted(_LEGACY_REMOTE_VERSION_FIELDS.intersection(version.keys()))
        if attempted:
            raise PlatformError(
                "ALGORITHM_VERSION_LEGACY_REMOTE_FIELD_READ_ONLY",
                "旧外部发布字段为只读迁移数据",
                "、".join(attempted),
                "请通过 ExternalPublicationRepository 修改 provider-specific 发布状态；AlgorithmSqlStore 仅保留历史值供迁移读取。",
                409,
            )

    def _insert_version_conn(
        self,
        conn: sqlite3.Connection,
        algorithm_id: str,
        version: Mapping[str, Any],
        sort_index: int,
        *,
        allow_legacy_remote_fields: bool = False,
    ) -> None:
        if not allow_legacy_remote_fields:
            self._reject_legacy_remote_field_mutation(version)
        conn.execute(
            """INSERT INTO algorithm_versions (id,algorithm_id,version_name,version_no,training_job_id,framework,training_status,stored_path,model_name,artifact_verified,trainable,external_analysis_id,external_algo_version_id,external_publish_status,created_at,finished_at,sort_index,payload_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (str(version.get("id")), algorithm_id, self._nullable_text(version.get("version_name")), self._nullable_text(version.get("version_no")), self._nullable_text(version.get("task_id") or version.get("job_id") or version.get("training_job_id")), self._nullable_text(version.get("framework")), self._nullable_text(version.get("training_status") or version.get("status")), self._nullable_text(version.get("stored_path")), self._nullable_text(version.get("model_name")), self._nullable_bool(version.get("artifact_verified")), self._nullable_bool(version.get("trainable")), self._nullable_text(version.get("external_analysis_id")), self._nullable_text(version.get("external_algo_version_id")), self._nullable_text(version.get("external_publish_status")), self._nullable_text(version.get("created_at")), self._nullable_text(version.get("finished_at")), int(sort_index), self._dumps(dict(version))),
        )

    def _update_version_conn(
        self,
        conn: sqlite3.Connection,
        algorithm_id: str,
        version: Mapping[str, Any],
        sort_index: int,
        *,
        preserved_legacy_remote_fields: Mapping[str, Any],
    ) -> None:
        preserved = dict(version)
        for field in _LEGACY_REMOTE_VERSION_FIELDS:
            value = preserved_legacy_remote_fields.get(field)
            if value is None:
                preserved.pop(field, None)
            else:
                preserved[field] = value
        conn.execute("DELETE FROM algorithm_versions WHERE algorithm_id=? AND id=?", (algorithm_id, str(version.get("id"))))
        self._insert_version_conn(
            conn,
            algorithm_id,
            preserved,
            sort_index,
            allow_legacy_remote_fields=True,
        )

    def _replace_analyses_conn(self, conn: sqlite3.Connection, algorithm_id: str, item: Mapping[str, Any]) -> None:
        conn.execute("DELETE FROM algorithm_external_analyses WHERE algorithm_id=?", (algorithm_id,))
        analyses = [dict(a) for a in (item.get("external_analyses") or []) if isinstance(a, Mapping)]
        if not analyses:
            analyses = [{"analysis_id": str(value)} for value in (item.get("external_analysis_ids") or []) if str(value or "").strip()]
        default_analysis_id = str(item.get("external_analysis_id") or "")
        seen: set[str] = set()
        for index, analysis in enumerate(analyses):
            analysis_id = str(analysis.get("analysis_id") or analysis.get("analysisId") or "").strip()
            if not analysis_id or analysis_id in seen:
                continue
            seen.add(analysis_id)
            compute_platform_ids = analysis.get("compute_platform_ids") or analysis.get("computePlatformIds") or []
            conn.execute(
                """INSERT INTO algorithm_external_analyses (algorithm_id,external_analysis_id,analysis_name,analysis_type,is_default,active,compute_platform_ids_json,sort_index,payload_json) VALUES (?,?,?,?,?,?,?,?,?)""",
                (algorithm_id, analysis_id, self._nullable_text(analysis.get("analysis_name") or analysis.get("analysisName")), self._nullable_text(analysis.get("analysis_type") or analysis.get("analysisType")), 1 if analysis_id == default_analysis_id else 0, 1 if self._analysis_is_active(analysis) else 0, self._dumps(list(compute_platform_ids) if isinstance(compute_platform_ids, (list, tuple, set)) else []), index, self._dumps(analysis)),
            )

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
            CREATE INDEX IF NOT EXISTS idx_algorithms_project_sort
                ON algorithms(project_id, sort_index, created_at, id);
            CREATE INDEX IF NOT EXISTS idx_algorithms_source ON algorithms(project_id, source_type);
            CREATE INDEX IF NOT EXISTS idx_algorithms_external_product ON algorithms(provider_type, external_product_id);
            CREATE INDEX IF NOT EXISTS idx_algorithms_external_category ON algorithms(external_category_id);
            CREATE INDEX IF NOT EXISTS idx_versions_algorithm ON algorithm_versions(algorithm_id, sort_index);
            CREATE INDEX IF NOT EXISTS idx_versions_training_job ON algorithm_versions(training_job_id);
            CREATE INDEX IF NOT EXISTS idx_versions_external_id ON algorithm_versions(external_algo_version_id);
            CREATE INDEX IF NOT EXISTS idx_analyses_algorithm_sort
                ON algorithm_external_analyses(
                    algorithm_id, sort_index, external_analysis_id
                );
            """
        )
        self._set_meta(conn, "schema_version", str(SCHEMA_VERSION))

    def _replace_all(
        self,
        conn: sqlite3.Connection,
        algorithms: Sequence[Mapping[str, Any]],
        *,
        allow_legacy_remote_fields: bool = False,
        preserved_legacy_remote_fields: Mapping[str, Mapping[str, Any]] | None = None,
    ) -> None:
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
                if not allow_legacy_remote_fields:
                    current = dict((preserved_legacy_remote_fields or {}).get(version_id) or {})
                    for field in _LEGACY_REMOTE_VERSION_FIELDS:
                        value = current.get(field)
                        if value is None:
                            version.pop(field, None)
                        else:
                            version[field] = value
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
                        1 if self._analysis_is_active(analysis) else 0,
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

    @staticmethod
    def _analysis_is_active(analysis: Mapping[str, Any]) -> bool:
        # ChangLian contract is exact: only status=1 is enabled.
        # Missing/unknown status must fail closed.
        return str(analysis.get("status") or "").strip() == "1"

    @staticmethod
    def _trainable_analysis_ids(item: Mapping[str, Any], analyses: Sequence[sqlite3.Row]) -> list[str]:
        # A trainable analysis must be provable from persisted detail:
        # status=1 AND analysisType=1. Never trust a legacy ID list by itself.
        eligible: list[str] = []
        eligible_set: set[str] = set()
        for row in analyses:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                payload = {}
            if not isinstance(payload, dict):
                payload = {}
            status = str(payload.get("status") or "").strip()
            analysis_type = str(
                payload.get("analysis_type")
                or payload.get("analysisType")
                or row["analysis_type"]
                or ""
            ).strip()
            analysis_id = str(row["external_analysis_id"] or "").strip()
            if status == "1" and analysis_type == "1" and analysis_id and analysis_id not in eligible_set:
                eligible_set.add(analysis_id)
                eligible.append(analysis_id)

        if "external_analysis_ids" in item:
            values = item.get("external_analysis_ids")
            if not isinstance(values, (list, tuple, set)):
                return []
            result: list[str] = []
            seen: set[str] = set()
            for value in values:
                analysis_id = str(value or "").strip()
                if analysis_id in eligible_set and analysis_id not in seen:
                    seen.add(analysis_id)
                    result.append(analysis_id)
            return result

        # Legacy objects without the canonical subset may still be recovered,
        # but only from strict persisted detail satisfying both official fields.
        return eligible

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
