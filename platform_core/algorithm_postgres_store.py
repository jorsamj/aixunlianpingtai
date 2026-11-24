"""PostgreSQL implementation of the algorithm-domain repository contract (T8.1).

This is the only module (together with the SQLite store) allowed to contain
dialect-specific SQL.  It implements the same contract and the same public
error codes as :class:`AlgorithmSqlStore`; presentation-only projections are
declared unsupported and fail closed instead of silently reading SQLite.

The provider is never opened implicitly: the factory requires a cutover
admission record, and ``ensure_ready`` re-validates that admission against the
database before any read or write.
"""
from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any, Mapping, Sequence

from .algorithm_postgres_schema import require_current_schema
from .algorithm_repository import (
    CORE_OPERATIONS,
    PRESENTATION_OPERATIONS,
    PROVIDER_POSTGRESQL,
    AlgorithmAdmissionRequired,
    AlgorithmProviderUnsupported,
    AlgorithmRepositoryError,
)
from .algorithm_shadow import _digest, _snapshot_body
from .algorithm_sql_store import AlgorithmSqlStore
from .errors import PlatformError

ALGORITHM_COLUMNS = (
    "id, project_id, name, remark, industry, algorithm_type, current_version_id, "
    "source_type, provider_type, external_product_id, external_product_code, "
    "external_category_id, external_analysis_id, external_active::int AS external_active, "
    "master_data_readonly::int AS master_data_readonly, external_last_synced_at, "
    "created_at, updated_at, sort_index, payload::text AS payload_json"
)
VERSION_COLUMNS = (
    "id, algorithm_id, version_name, version_no, training_job_id, framework, "
    "training_status, stored_path, model_name, artifact_verified::int AS artifact_verified, "
    "trainable::int AS trainable, external_analysis_id, external_algo_version_id, "
    "external_publish_status, created_at, finished_at, sort_index, "
    "payload::text AS payload_json"
)
ANALYSIS_COLUMNS = (
    "algorithm_id, external_analysis_id, analysis_name, analysis_type, "
    "is_default::int AS is_default, active::int AS active, "
    "compute_platform_ids::text AS compute_platform_ids_json, sort_index, "
    "payload::text AS payload_json"
)
_LEGACY_REMOTE_VERSION_FIELDS = frozenset({
    "external_algo_version_id",
    "external_publish_status",
})
_UNSUPPORTED = tuple(PRESENTATION_OPERATIONS)
#: Declared capability gap of this provider (single source for the cutover tool).
UNSUPPORTED_OPERATIONS = _UNSUPPORTED


class _Projection:
    """Reuse the SQLite store's pure row projections on PostgreSQL rows.

    PostgreSQL rows are selected as ``payload::text`` plus ``::int`` casts for
    boolean columns, so they have exactly the SQLite column shape.  Reusing the
    projections guarantees the same public object shape without duplicating it.
    """

    _json_object = staticmethod(AlgorithmSqlStore._json_object)
    _json_list = staticmethod(AlgorithmSqlStore._json_list)
    _overlay_optional = staticmethod(AlgorithmSqlStore._overlay_optional)
    _version_from_row = AlgorithmSqlStore._version_from_row
    _analysis_from_row = AlgorithmSqlStore._analysis_from_row
    _trainable_analysis_ids = staticmethod(AlgorithmSqlStore._trainable_analysis_ids)


_PROJECTION = _Projection()
_dumps = AlgorithmSqlStore._dumps
_nullable_text = AlgorithmSqlStore._nullable_text
_nullable_bool = AlgorithmSqlStore._nullable_bool
_json_object = AlgorithmSqlStore._json_object
_canonical_training_version = AlgorithmSqlStore._canonical_training_version
_analysis_is_active = AlgorithmSqlStore._analysis_is_active


def _psycopg():
    try:
        import psycopg
    except ImportError as error:  # pragma: no cover - depends on environment
        raise AlgorithmRepositoryError(
            "ALGORITHM_POSTGRES_DRIVER_MISSING",
            "psycopg 3 is required for the PostgreSQL algorithm provider",
        ) from error
    return psycopg


def _qualified_columns(columns: str, prefix: str) -> str:
    """Qualify bare column references for joined SELECTs, keeping aliases/casts."""
    parts: list[str] = []
    for part in columns.split(","):
        part = part.strip()
        name = part.split("::")[0].split(" AS ")[0].strip()
        parts.append(part.replace(name, f"{prefix}{name}", 1))
    return ", ".join(parts)


def _pg_bool(value: Any) -> bool | None:
    if value is None:
        return None
    return bool(value)


class PostgresAlgorithmRepository:
    """Algorithm repository backed by the ``w5_algorithm`` PostgreSQL schema."""

    provider_name = PROVIDER_POSTGRESQL

    def __init__(self, dsn: str, project_id: str, *, admission: Mapping[str, Any] | None = None):
        self._dsn = str(dsn)
        self.project_id = str(project_id)
        self._admission = dict(admission) if admission else None
        self._ready = False

    # -- provider metadata -------------------------------------------------
    def capabilities(self) -> frozenset[str]:
        return frozenset(CORE_OPERATIONS)

    def unsupported_operations(self) -> tuple[str, ...]:
        return _UNSUPPORTED

    def __repr__(self) -> str:  # never render the DSN
        return f"PostgresAlgorithmRepository(project_id={self.project_id!r})"

    # -- connection plumbing ----------------------------------------------
    def _connect(self):
        psycopg = _psycopg()
        from psycopg.rows import dict_row

        return psycopg.connect(self._dsn, row_factory=dict_row)

    @contextmanager
    def _read(self):
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                yield cursor
        finally:
            connection.close()

    @contextmanager
    def _write(self):
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                # The ownership verdict and the write must be one transaction:
                # a separate ``ensure_ready`` connection let a cutover or
                # rollback commit a different authority between the check and
                # the write (TOCTOU). Locking the cutover row FOR UPDATE makes
                # the switch wait for this write, and this write wait for an
                # in-flight switch.
                self._require_write_authority(cursor)
                yield cursor
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    #: Transition phases during which neither provider may accept writes.
    _WRITABLE_PHASES = frozenset({"steady", "switched"})

    def _require_write_authority(self, cursor) -> None:
        """Verify admission and writer generation inside the write transaction."""
        record = self._admission
        if not record:
            raise AlgorithmAdmissionRequired(
                "ALGORITHM_POSTGRES_WRITE_ADMISSION_REQUIRED",
                "PostgreSQL writes require an explicit cutover admission",
                detail="this provider instance has no admission record",
            )
        cursor.execute(
            "SELECT authoritative_provider,admission_id,writer_generation,revoked_at,evidence "
            "FROM w5_algorithm.cutover_state WHERE project_id=%s FOR UPDATE",
            (self.project_id,),
        )
        row = cursor.fetchone()
        stale_reason = ""
        if row is None:
            stale_reason = "no cutover state for this project"
        elif str(row["authoritative_provider"]) != PROVIDER_POSTGRESQL:
            stale_reason = f"authoritative provider is {row['authoritative_provider']}"
        elif str(row["admission_id"]) != str(record.get("admission_id") or ""):
            stale_reason = "admission id does not match the database"
        elif int(row["writer_generation"]) != int(record.get("writer_generation") or 0):
            stale_reason = "writer generation advanced; re-admit before using PostgreSQL"
        elif row["revoked_at"] is not None:
            stale_reason = "admission was revoked"
        else:
            evidence = row.get("evidence")
            phase = ""
            if isinstance(evidence, Mapping):
                phase = str(evidence.get("phase") or "").strip()
            if phase and phase not in self._WRITABLE_PHASES:
                stale_reason = f"cutover transition is in phase {phase!r}"
        if stale_reason:
            raise AlgorithmAdmissionRequired(
                "ALGORITHM_POSTGRES_ADMISSION_STALE",
                "PostgreSQL admission is no longer valid",
                detail=stale_reason,
            )

    # -- schema and admission ---------------------------------------------
    def ensure_ready(self) -> None:
        connection = self._connect()
        try:
            require_current_schema(connection)
            self._require_admission(connection)
        finally:
            connection.close()
        self._ready = True

    def _require_admission(self, connection) -> None:
        record = self._admission
        if not record:
            return
        from psycopg.rows import dict_row

        with connection.cursor(row_factory=dict_row) as cursor:
            cursor.execute(
                "SELECT authoritative_provider,admission_id,writer_generation,revoked_at "
                "FROM w5_algorithm.cutover_state WHERE project_id=%s",
                (self.project_id,),
            )
            row = cursor.fetchone()
        stale_reason = ""
        if row is None:
            stale_reason = "no cutover state for this project"
        elif str(row["authoritative_provider"]) != PROVIDER_POSTGRESQL:
            stale_reason = f"authoritative provider is {row['authoritative_provider']}"
        elif str(row["admission_id"]) != str(record.get("admission_id") or ""):
            stale_reason = "admission id does not match the database"
        elif int(row["writer_generation"]) != int(record.get("writer_generation") or 0):
            stale_reason = "writer generation advanced; re-admit before using PostgreSQL"
        elif row["revoked_at"] is not None:
            stale_reason = "admission was revoked"
        if stale_reason:
            raise AlgorithmAdmissionRequired(
                "ALGORITHM_POSTGRES_ADMISSION_STALE",
                "PostgreSQL admission is no longer valid",
                detail=stale_reason,
            )

    def _check_operation(self, name: str) -> None:
        if name in _UNSUPPORTED:
            raise AlgorithmProviderUnsupported(
                "ALGORITHM_PROVIDER_OPERATION_UNSUPPORTED",
                f"operation {name} is not implemented by the PostgreSQL provider",
                detail=(
                    "presentation projections remain served by the SQLite provider until "
                    "they are ported; no silent fallback is performed"
                ),
            )

    # -- meta --------------------------------------------------------------
    def revision(self) -> int:
        with self._read() as cursor:
            return self._revision(cursor)

    def _revision(self, cursor) -> int:
        cursor.execute(
            "SELECT algorithm_revision FROM w5_algorithm.store_revision WHERE project_id=%s",
            (self.project_id,),
        )
        row = cursor.fetchone()
        return max(0, int(row["algorithm_revision"])) if row else 0

    def _bump_revision(self, cursor) -> int:
        cursor.execute(
            "INSERT INTO w5_algorithm.store_revision(project_id,algorithm_revision,updated_at) "
            "VALUES(%s,1,now()) ON CONFLICT(project_id) DO UPDATE "
            "SET algorithm_revision=w5_algorithm.store_revision.algorithm_revision+1,"
            "updated_at=now() RETURNING algorithm_revision",
            (self.project_id,),
        )
        return int(cursor.fetchone()["algorithm_revision"])

    def migration_status(self) -> dict[str, Any]:
        with self._read() as cursor:
            cursor.execute(
                "SELECT "
                "(SELECT COUNT(*) FROM w5_algorithm.algorithm WHERE project_id=%s) AS algorithms,"
                "(SELECT COUNT(*) FROM w5_algorithm.algorithm_version "
                " WHERE project_id=%s) AS versions,"
                "(SELECT COUNT(*) FROM w5_algorithm.algorithm_external_analysis "
                " WHERE project_id=%s) AS analyses",
                (self.project_id, self.project_id, self.project_id),
            )
            counts = cursor.fetchone()
            revision = self._revision(cursor)
        return {
            "backend": PROVIDER_POSTGRESQL,
            "project_id": self.project_id,
            "algorithm_count": int(counts["algorithms"]),
            "version_count": int(counts["versions"]),
            "external_analysis_count": int(counts["analyses"]),
            "algorithm_revision": revision,
        }

    # -- reads -------------------------------------------------------------
    def read_all(self, *, summary_only: bool = False) -> list[dict]:
        self.ensure_ready()
        with self._read() as cursor:
            algorithms = self._read_all_rows(cursor, summary_only=summary_only)
        return algorithms

    def _read_all_rows(self, cursor, *, summary_only: bool) -> list[dict]:
        cursor.execute(
            f"SELECT {ALGORITHM_COLUMNS} FROM w5_algorithm.algorithm "
            "WHERE project_id=%s ORDER BY sort_index ASC, created_at DESC NULLS LAST, id ASC",
            (self.project_id,),
        )
        algorithm_rows = cursor.fetchall()
        if not algorithm_rows:
            return []
        cursor.execute(
            f"SELECT {_qualified_columns(VERSION_COLUMNS, 'versions.')} "
            "FROM w5_algorithm.algorithm_version AS versions "
            "WHERE versions.project_id=%s "
            "ORDER BY versions.algorithm_id ASC, versions.sort_index ASC, versions.id ASC",
            (self.project_id,),
        )
        version_rows = cursor.fetchall()
        cursor.execute(
            f"SELECT {_qualified_columns(ANALYSIS_COLUMNS, 'analyses.')} "
            "FROM w5_algorithm.algorithm_external_analysis AS analyses "
            "WHERE analyses.project_id=%s "
            "ORDER BY analyses.algorithm_id ASC, analyses.sort_index ASC, "
            "analyses.external_analysis_id ASC",
            (self.project_id,),
        )
        analysis_rows = cursor.fetchall()
        versions_by_algorithm: dict[str, list[dict]] = {}
        for version_row in version_rows:
            row = dict(version_row)
            if summary_only:
                row = _summary_version_row(row)
            versions_by_algorithm.setdefault(str(row["algorithm_id"]), []).append(row)
        analyses_by_algorithm: dict[str, list[dict]] = {}
        for analysis_row in analysis_rows:
            row = dict(analysis_row)
            analyses_by_algorithm.setdefault(str(row["algorithm_id"]), []).append(row)
        result: list[dict] = []
        for raw in algorithm_rows:
            row = dict(raw)
            algorithm_id = str(row["id"])
            item = _json_object(row["payload_json"])
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
            _PROJECTION._overlay_optional(item, row, (
                "source_type", "provider_type", "external_product_id", "external_product_code",
                "external_category_id", "external_analysis_id", "external_active",
                "master_data_readonly", "external_last_synced_at",
            ))
            if str(item.get("source_type") or "").upper() == "EXTERNAL":
                item.setdefault("external_analysis_id", "")
            item["versions"] = [
                _PROJECTION._version_from_row(value)
                for value in versions_by_algorithm.get(algorithm_id, [])
            ]
            if summary_only:
                item["versions_compact"] = True
            analyses = analyses_by_algorithm.get(algorithm_id, [])
            if analyses:
                item["external_analyses"] = [
                    _PROJECTION._analysis_from_row(value) for value in analyses
                ]
                item["external_analysis_ids"] = _PROJECTION._trainable_analysis_ids(item, analyses)
            elif str(item.get("source_type") or "").upper() == "EXTERNAL":
                item.setdefault("external_analysis_ids", [])
            item.setdefault("version_operations", [])
            result.append(item)
        return result

    def read_one(self, algorithm_id: str) -> dict | None:
        self.ensure_ready()
        with self._read() as cursor:
            return self._read_one(cursor, algorithm_id)

    def _read_one(self, cursor, algorithm_id: str) -> dict | None:
        cursor.execute(
            f"SELECT {ALGORITHM_COLUMNS} FROM w5_algorithm.algorithm "
            "WHERE project_id=%s AND id=%s",
            (self.project_id, str(algorithm_id)),
        )
        raw = cursor.fetchone()
        if raw is None:
            return None
        row = dict(raw)
        item = _json_object(row["payload_json"])
        item.update({
            "id": row["id"], "name": row["name"], "remark": row["remark"] or "",
            "industry": row["industry"] or "", "algorithm_type": row["algorithm_type"] or "",
            "current_version_id": row["current_version_id"], "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        })
        _PROJECTION._overlay_optional(item, row, (
            "source_type", "provider_type", "external_product_id", "external_product_code",
            "external_category_id", "external_analysis_id", "external_active",
            "master_data_readonly", "external_last_synced_at",
        ))
        if str(item.get("source_type") or "").upper() == "EXTERNAL":
            item.setdefault("external_analysis_id", "")
        cursor.execute(
            f"SELECT {VERSION_COLUMNS} FROM w5_algorithm.algorithm_version "
            "WHERE project_id=%s AND algorithm_id=%s ORDER BY sort_index ASC, id ASC",
            (self.project_id, str(algorithm_id)),
        )
        versions = [dict(value) for value in cursor.fetchall()]
        item["versions"] = [_PROJECTION._version_from_row(value) for value in versions]
        cursor.execute(
            f"SELECT {ANALYSIS_COLUMNS} FROM w5_algorithm.algorithm_external_analysis "
            "WHERE project_id=%s AND algorithm_id=%s "
            "ORDER BY sort_index ASC, external_analysis_id ASC",
            (self.project_id, str(algorithm_id)),
        )
        analyses = [dict(value) for value in cursor.fetchall()]
        if analyses:
            item["external_analyses"] = [
                _PROJECTION._analysis_from_row(value) for value in analyses
            ]
            item["external_analysis_ids"] = _PROJECTION._trainable_analysis_ids(item, analyses)
        elif str(item.get("source_type") or "").upper() == "EXTERNAL":
            item.setdefault("external_analysis_ids", [])
        item.setdefault("version_operations", [])
        return item

    def exists(self, algorithm_id: str) -> bool:
        self.ensure_ready()
        with self._read() as cursor:
            cursor.execute(
                "SELECT 1 FROM w5_algorithm.algorithm WHERE project_id=%s AND id=%s",
                (self.project_id, str(algorithm_id)),
            )
            return cursor.fetchone() is not None

    def training_version_refs(self, task_id: str) -> list[tuple[str, str]]:
        self.ensure_ready()
        with self._read() as cursor:
            cursor.execute(
                "SELECT versions.algorithm_id, versions.id "
                "FROM w5_algorithm.algorithm_version AS versions "
                "WHERE versions.project_id=%s AND versions.training_job_id=%s "
                "ORDER BY versions.algorithm_id, versions.id",
                (self.project_id, str(task_id)),
            )
            return [(str(row["algorithm_id"]), str(row["id"])) for row in cursor.fetchall()]

    # -- write helpers -----------------------------------------------------
    @staticmethod
    def _algorithm_payload(item: Mapping[str, Any]) -> dict:
        payload = dict(item)
        payload.pop("versions", None)
        payload.pop("external_analyses", None)
        for key in (
            "id", "name", "remark", "industry", "algorithm_type", "current_version_id",
            "source_type", "provider_type", "external_product_id", "external_product_code",
            "external_category_id", "external_analysis_id", "external_active",
            "master_data_readonly", "external_last_synced_at", "created_at", "updated_at",
        ):
            payload.pop(key, None)
        return payload

    def _insert_algorithm(self, cursor, item: Mapping[str, Any], sort_index: int) -> None:
        cursor.execute(
            "INSERT INTO w5_algorithm.algorithm (id,project_id,name,remark,industry,"
            "algorithm_type,current_version_id,source_type,provider_type,external_product_id,"
            "external_product_code,external_category_id,external_analysis_id,external_active,"
            "master_data_readonly,external_last_synced_at,created_at,updated_at,sort_index,payload)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            (
                str(item.get("id")), self.project_id, str(item.get("name") or ""),
                str(item.get("remark") or ""), str(item.get("industry") or ""),
                str(item.get("algorithm_type") or ""), _nullable_text(item.get("current_version_id")),
                _nullable_text(item.get("source_type")), _nullable_text(item.get("provider_type")),
                _nullable_text(item.get("external_product_id")),
                _nullable_text(item.get("external_product_code")),
                _nullable_text(item.get("external_category_id")),
                _nullable_text(item.get("external_analysis_id")),
                _pg_bool(_nullable_bool(item.get("external_active"))),
                _pg_bool(_nullable_bool(item.get("master_data_readonly"))),
                _nullable_text(item.get("external_last_synced_at")),
                _nullable_text(item.get("created_at")), _nullable_text(item.get("updated_at")),
                int(sort_index), _dumps(self._algorithm_payload(item)),
            ),
        )

    def _update_algorithm(self, cursor, item: Mapping[str, Any]) -> None:
        cursor.execute(
            "UPDATE w5_algorithm.algorithm SET name=%s,remark=%s,industry=%s,algorithm_type=%s,"
            "current_version_id=%s,source_type=%s,provider_type=%s,external_product_id=%s,"
            "external_product_code=%s,external_category_id=%s,external_analysis_id=%s,"
            "external_active=%s,master_data_readonly=%s,external_last_synced_at=%s,created_at=%s,"
            "updated_at=%s,payload=%s::jsonb WHERE project_id=%s AND id=%s",
            (
                str(item.get("name") or ""), str(item.get("remark") or ""),
                str(item.get("industry") or ""), str(item.get("algorithm_type") or ""),
                _nullable_text(item.get("current_version_id")),
                _nullable_text(item.get("source_type")), _nullable_text(item.get("provider_type")),
                _nullable_text(item.get("external_product_id")),
                _nullable_text(item.get("external_product_code")),
                _nullable_text(item.get("external_category_id")),
                _nullable_text(item.get("external_analysis_id")),
                _pg_bool(_nullable_bool(item.get("external_active"))),
                _pg_bool(_nullable_bool(item.get("master_data_readonly"))),
                _nullable_text(item.get("external_last_synced_at")),
                _nullable_text(item.get("created_at")), _nullable_text(item.get("updated_at")),
                _dumps(self._algorithm_payload(item)), self.project_id, str(item.get("id")),
            ),
        )

    def _insert_version(
        self,
        cursor,
        algorithm_id: str,
        version: Mapping[str, Any],
        sort_index: int,
        *,
        allow_legacy_remote_fields: bool = False,
    ) -> None:
        version = _canonical_training_version(version)
        if not allow_legacy_remote_fields:
            AlgorithmSqlStore._reject_legacy_remote_field_mutation(version)
        cursor.execute(
            "INSERT INTO w5_algorithm.algorithm_version (project_id,id,algorithm_id,"
            "version_name,version_no,training_job_id,framework,training_status,stored_path,"
            "model_name,artifact_verified,trainable,external_analysis_id,external_algo_version_id,"
            "external_publish_status,created_at,finished_at,sort_index,payload)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            (
                self.project_id, str(version.get("id")), algorithm_id,
                _nullable_text(version.get("version_name")),
                _nullable_text(version.get("version_no")),
                _nullable_text(version.get("task_id") or version.get("job_id") or version.get("training_job_id")),
                _nullable_text(version.get("framework")),
                _nullable_text(version.get("training_status") or version.get("status")),
                _nullable_text(version.get("stored_path")),
                _nullable_text(version.get("model_name")),
                _pg_bool(_nullable_bool(version.get("artifact_verified"))),
                _pg_bool(_nullable_bool(version.get("trainable"))),
                _nullable_text(version.get("external_analysis_id")),
                _nullable_text(version.get("external_algo_version_id")),
                _nullable_text(version.get("external_publish_status")),
                _nullable_text(version.get("created_at")),
                _nullable_text(version.get("finished_at")),
                int(sort_index), _dumps(dict(version)),
            ),
        )

    def _update_version(
        self,
        cursor,
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
        cursor.execute(
            "DELETE FROM w5_algorithm.algorithm_version "
            "WHERE project_id=%s AND algorithm_id=%s AND id=%s",
            (self.project_id, algorithm_id, str(version.get("id"))),
        )
        self._insert_version(
            cursor, algorithm_id, preserved, sort_index, allow_legacy_remote_fields=True
        )

    def _replace_analyses(self, cursor, algorithm_id: str, item: Mapping[str, Any]) -> None:
        cursor.execute(
            "DELETE FROM w5_algorithm.algorithm_external_analysis "
            "WHERE project_id=%s AND algorithm_id=%s",
            (self.project_id, algorithm_id),
        )
        analyses = [dict(a) for a in (item.get("external_analyses") or []) if isinstance(a, Mapping)]
        if not analyses:
            analyses = [
                {"analysis_id": str(value)}
                for value in (item.get("external_analysis_ids") or [])
                if str(value or "").strip()
            ]
        default_analysis_id = str(item.get("external_analysis_id") or "")
        seen: set[str] = set()
        for index, analysis in enumerate(analyses):
            analysis_id = str(analysis.get("analysis_id") or analysis.get("analysisId") or "").strip()
            if not analysis_id or analysis_id in seen:
                continue
            seen.add(analysis_id)
            compute_platform_ids = (
                analysis.get("compute_platform_ids") or analysis.get("computePlatformIds") or []
            )
            cursor.execute(
                "INSERT INTO w5_algorithm.algorithm_external_analysis "
                "(project_id,algorithm_id,external_analysis_id,analysis_name,analysis_type,"
                "is_default,active,compute_platform_ids,sort_index,payload)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,%s::jsonb)",
                (
                    self.project_id, algorithm_id, analysis_id,
                    _nullable_text(analysis.get("analysis_name") or analysis.get("analysisName")),
                    _nullable_text(analysis.get("analysis_type") or analysis.get("analysisType")),
                    analysis_id == default_analysis_id,
                    _analysis_is_active(analysis),
                    _dumps(list(compute_platform_ids)
                           if isinstance(compute_platform_ids, (list, tuple, set)) else []),
                    index, _dumps(analysis),
                ),
            )

    # -- writes ------------------------------------------------------------
    def replace_all(self, algorithms: Sequence[Mapping[str, Any]]) -> None:
        self.ensure_ready()
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
        with self._write() as cursor:
            cursor.execute(
                "SELECT id,external_algo_version_id,external_publish_status "
                "FROM w5_algorithm.algorithm_version WHERE project_id=%s",
                (self.project_id,),
            )
            preserved = {
                str(row["id"]): {
                    field: row[field] for field in _LEGACY_REMOTE_VERSION_FIELDS
                }
                for row in cursor.fetchall()
            }
            self._delete_graph(cursor)
            version_ids: set[str] = set()
            for index, item in enumerate(rows):
                algorithm_id = str(item["id"])
                versions = [
                    _canonical_training_version(value)
                    for value in (item.get("versions") or [])
                    if isinstance(value, Mapping)
                ]
                analyses = [
                    dict(value) for value in (item.get("external_analyses") or [])
                    if isinstance(value, Mapping)
                ]
                payload = dict(item)
                payload.pop("versions", None)
                payload.pop("external_analyses", None)
                self._insert_algorithm_row(cursor, item, payload, index)
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
                    current = preserved.get(version_id) or {}
                    for field in _LEGACY_REMOTE_VERSION_FIELDS:
                        value = current.get(field)
                        if value is None:
                            version.pop(field, None)
                        else:
                            version[field] = value
                    self._insert_version(
                        cursor, algorithm_id, version, version_index,
                        allow_legacy_remote_fields=True,
                    )
                self._replace_analyses(
                    cursor, algorithm_id, {**item, "external_analyses": analyses}
                )
            self._bump_revision(cursor)

    def _insert_algorithm_row(
        self, cursor, item: Mapping[str, Any], payload: Mapping[str, Any], sort_index: int
    ) -> None:
        cursor.execute(
            "INSERT INTO w5_algorithm.algorithm (id,project_id,name,remark,industry,"
            "algorithm_type,current_version_id,source_type,provider_type,external_product_id,"
            "external_product_code,external_category_id,external_analysis_id,external_active,"
            "master_data_readonly,external_last_synced_at,created_at,updated_at,sort_index,payload)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
            (
                str(item["id"]), self.project_id, str(item.get("name") or ""),
                str(item.get("remark") or ""), str(item.get("industry") or ""),
                str(item.get("algorithm_type") or ""), _nullable_text(item.get("current_version_id")),
                _nullable_text(item.get("source_type")), _nullable_text(item.get("provider_type")),
                _nullable_text(item.get("external_product_id")),
                _nullable_text(item.get("external_product_code")),
                _nullable_text(item.get("external_category_id")),
                _nullable_text(item.get("external_analysis_id")),
                _pg_bool(_nullable_bool(item.get("external_active"))),
                _pg_bool(_nullable_bool(item.get("master_data_readonly"))),
                _nullable_text(item.get("external_last_synced_at")),
                _nullable_text(item.get("created_at")), _nullable_text(item.get("updated_at")),
                int(sort_index), _dumps(dict(payload)),
            ),
        )

    def _delete_graph(self, cursor) -> None:
        cursor.execute(
            "DELETE FROM w5_algorithm.algorithm_version WHERE project_id=%s",
            (self.project_id,),
        )
        cursor.execute(
            "DELETE FROM w5_algorithm.algorithm_external_analysis WHERE project_id=%s",
            (self.project_id,),
        )
        cursor.execute(
            "DELETE FROM w5_algorithm.algorithm WHERE project_id=%s", (self.project_id,)
        )

    def create_algorithm(self, item: Mapping[str, Any]) -> dict:
        self.ensure_ready()
        value = dict(item)
        algorithm_id = str(value.get("id") or "").strip()
        name = str(value.get("name") or "").strip()
        if not algorithm_id or not name:
            raise PlatformError(
                "ALGORITHM_ID_REQUIRED", "算法数据不完整",
                "创建算法需要稳定 ID 和名称。", "请刷新后重试。", 409,
            )
        with self._write() as cursor:
            cursor.execute(
                "SELECT id FROM w5_algorithm.algorithm WHERE project_id=%s "
                "AND lower(trim(name))=lower(trim(%s)) LIMIT 1",
                (self.project_id, name),
            )
            if cursor.fetchone() is not None:
                raise PlatformError(
                    "ALGORITHM_NAME_EXISTS", "算法名称已存在",
                    f"当前项目中已经存在名为“{name}”的算法。",
                    "请使用不同名称，或编辑已有算法。", 409,
                )
            cursor.execute(
                "SELECT COALESCE(MIN(sort_index),0)-1 AS next FROM w5_algorithm.algorithm "
                "WHERE project_id=%s",
                (self.project_id,),
            )
            sort_index = int(cursor.fetchone()["next"])
            self._insert_algorithm(cursor, value, sort_index)
            self._replace_analyses(cursor, algorithm_id, value)
            self._bump_revision(cursor)
        return value

    def patch_algorithm(
        self, algorithm_id: str, patch: Mapping[str, Any], *, replace_analyses: bool = False
    ) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        with self._write() as cursor:
            existing = self._read_one(cursor, algorithm_id)
            if existing is None:
                raise PlatformError(
                    "ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。",
                    "请刷新算法列表后重试。", 404,
                )
            merged = dict(existing)
            merged.update(dict(patch))
            proposed_name = str(merged.get("name") or "").strip()
            cursor.execute(
                "SELECT id FROM w5_algorithm.algorithm WHERE project_id=%s AND id<>%s "
                "AND lower(trim(name))=lower(trim(%s)) LIMIT 1",
                (self.project_id, algorithm_id, proposed_name),
            )
            if cursor.fetchone() is not None:
                raise PlatformError(
                    "ALGORITHM_NAME_EXISTS", "算法名称已存在",
                    f"算法名称“{proposed_name}”已被使用。", "请使用不同名称。", 409,
                )
            self._update_algorithm(cursor, merged)
            if replace_analyses:
                self._replace_analyses(cursor, algorithm_id, merged)
            self._bump_revision(cursor)
        return merged

    def delete_algorithm(self, algorithm_id: str) -> None:
        self.ensure_ready()
        with self._write() as cursor:
            cursor.execute(
                "DELETE FROM w5_algorithm.algorithm WHERE project_id=%s AND id=%s",
                (self.project_id, str(algorithm_id)),
            )
            if cursor.rowcount != 1:
                raise PlatformError(
                    "ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。",
                    "请刷新算法列表后重试。", 404,
                )
            self._bump_revision(cursor)

    def attach_version(self, algorithm_id: str, version: Mapping[str, Any]) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        value = dict(version)
        version_id = str(value.get("id") or "").strip()
        if not version_id:
            raise PlatformError(
                "ALGORITHM_VERSION_ID_REQUIRED", "算法版本缺少 ID", algorithm_id,
                "请重新归档训练版本。", 409,
            )
        task_id = str(
            value.get("task_id") or value.get("job_id") or value.get("training_job_id") or ""
        ).strip()
        with self._write() as cursor:
            cursor.execute(
                "SELECT 1 FROM w5_algorithm.algorithm WHERE project_id=%s AND id=%s",
                (self.project_id, algorithm_id),
            )
            if cursor.fetchone() is None:
                raise PlatformError(
                    "ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。",
                    "请刷新算法列表后重试。", 404,
                )
            if task_id:
                cursor.execute(
                    "SELECT " + VERSION_COLUMNS + " FROM w5_algorithm.algorithm_version "
                    "WHERE project_id=%s AND algorithm_id=%s AND training_job_id=%s LIMIT 1",
                    (self.project_id, algorithm_id, task_id),
                )
                duplicate = cursor.fetchone()
                if duplicate is not None:
                    return _PROJECTION._version_from_row(dict(duplicate))
            cursor.execute(
                "SELECT 1 FROM w5_algorithm.algorithm_version "
                "WHERE project_id=%s AND id=%s",
                (self.project_id, version_id),
            )
            if cursor.fetchone() is not None:
                raise PlatformError(
                    "ALGORITHM_VERSION_ID_DUPLICATED", "算法版本 ID 已存在", version_id,
                    "请检查训练归档幂等状态。", 409,
                )
            cursor.execute(
                "SELECT COALESCE(MIN(sort_index),0)-1 AS next "
                "FROM w5_algorithm.algorithm_version "
                "WHERE project_id=%s AND algorithm_id=%s",
                (self.project_id, algorithm_id),
            )
            sort_index = int(cursor.fetchone()["next"])
            self._insert_version(cursor, algorithm_id, value, sort_index)
            updated_at = str(value.get("finished_at") or value.get("created_at") or "") or None
            cursor.execute(
                "UPDATE w5_algorithm.algorithm SET current_version_id=%s,"
                "updated_at=COALESCE(%s,updated_at) WHERE project_id=%s AND id=%s",
                (version_id, updated_at, self.project_id, algorithm_id),
            )
            self._bump_revision(cursor)
        return value

    def attach_version_if_current(
        self,
        algorithm_id: str,
        version: Mapping[str, Any],
        *,
        expected_current_version_id: str | None,
    ) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        value = dict(version)
        version_id = str(value.get("id") or "").strip()
        if not version_id:
            raise PlatformError(
                "ALGORITHM_VERSION_ID_REQUIRED", "算法版本缺少 ID", algorithm_id,
                "请重新归档训练版本。", 409,
            )
        task_id = str(
            value.get("task_id") or value.get("job_id") or value.get("training_job_id") or ""
        ).strip()
        expected = str(expected_current_version_id or "").strip()
        with self._write() as cursor:
            cursor.execute(
                "SELECT current_version_id FROM w5_algorithm.algorithm "
                "WHERE project_id=%s AND id=%s",
                (self.project_id, algorithm_id),
            )
            algorithm_row = cursor.fetchone()
            if algorithm_row is None:
                raise PlatformError(
                    "ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。",
                    "请刷新算法列表后重试。", 404,
                )
            if task_id:
                cursor.execute(
                    "SELECT " + VERSION_COLUMNS + " FROM w5_algorithm.algorithm_version "
                    "WHERE project_id=%s AND algorithm_id=%s AND training_job_id=%s LIMIT 1",
                    (self.project_id, algorithm_id, task_id),
                )
                duplicate = cursor.fetchone()
                if duplicate is not None:
                    return _PROJECTION._version_from_row(dict(duplicate))
            persisted_current = str(algorithm_row["current_version_id"] or "").strip()
            if expected:
                if persisted_current and persisted_current != expected:
                    raise PlatformError(
                        "ALGORITHM_VERSION_CONFLICT", "算法当前版本已经发生变化",
                        f"训练任务基于 {expected}，当前实际版本为 {persisted_current}。",
                        "请保留该任务结果用于审计，并基于当前版本重新发起迭代训练。", 409,
                    )
                if not persisted_current:
                    cursor.execute(
                        "SELECT 1 FROM w5_algorithm.algorithm_version "
                        "WHERE project_id=%s AND algorithm_id=%s AND id=%s",
                        (self.project_id, algorithm_id, expected),
                    )
                    if cursor.fetchone() is None:
                        raise PlatformError(
                            "ALGORITHM_VERSION_CONFLICT", "训练基础版本已经不存在",
                            f"训练任务基于 {expected}，但该版本已被删除或回退清理。",
                            "请基于当前有效版本重新发起训练。", 409,
                        )
            else:
                cursor.execute(
                    "SELECT 1 FROM w5_algorithm.algorithm_version "
                    "WHERE project_id=%s AND algorithm_id=%s LIMIT 1",
                    (self.project_id, algorithm_id),
                )
                if persisted_current or cursor.fetchone() is not None:
                    actual = persisted_current or "<legacy-inferred>"
                    raise PlatformError(
                        "ALGORITHM_VERSION_CONFLICT", "首训任务的算法版本状态已经变化",
                        f"任务创建时没有基础版本，当前已存在版本 {actual}。",
                        "请按迭代训练重新提交任务，不能让旧首训覆盖当前版本。", 409,
                    )
            cursor.execute(
                "SELECT 1 FROM w5_algorithm.algorithm_version "
                "WHERE project_id=%s AND id=%s",
                (self.project_id, version_id),
            )
            if cursor.fetchone() is not None:
                raise PlatformError(
                    "ALGORITHM_VERSION_ID_DUPLICATED", "算法版本 ID 已存在", version_id,
                    "请检查训练归档幂等状态。", 409,
                )
            cursor.execute(
                "SELECT COALESCE(MIN(sort_index),0)-1 AS next "
                "FROM w5_algorithm.algorithm_version "
                "WHERE project_id=%s AND algorithm_id=%s",
                (self.project_id, algorithm_id),
            )
            sort_index = int(cursor.fetchone()["next"])
            self._insert_version(cursor, algorithm_id, value, sort_index)
            updated_at = str(value.get("finished_at") or value.get("created_at") or "") or None
            cursor.execute(
                "UPDATE w5_algorithm.algorithm SET current_version_id=%s,"
                "updated_at=COALESCE(%s,updated_at) WHERE project_id=%s AND id=%s",
                (version_id, updated_at, self.project_id, algorithm_id),
            )
            self._bump_revision(cursor)
        return value

    def patch_version(
        self, algorithm_id: str, version_id: str, patch: Mapping[str, Any], *, now: str
    ) -> dict:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        version_id = str(version_id)
        AlgorithmSqlStore._reject_legacy_remote_field_mutation(patch)
        with self._write() as cursor:
            cursor.execute(
                "SELECT " + VERSION_COLUMNS + " FROM w5_algorithm.algorithm_version "
                "WHERE algorithm_id=%s AND id=%s",
                (algorithm_id, version_id),
            )
            raw = cursor.fetchone()
            if raw is None:
                cursor.execute(
                    "SELECT 1 FROM w5_algorithm.algorithm WHERE project_id=%s AND id=%s",
                    (self.project_id, algorithm_id),
                )
                if cursor.fetchone() is None:
                    raise PlatformError(
                        "ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。",
                        "请刷新算法列表后重试。", 404,
                    )
                raise PlatformError(
                    "ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {version_id}。",
                    "请刷新版本列表后重试。", 404,
                )
            row = dict(raw)
            value = _PROJECTION._version_from_row(row)
            value.update(dict(patch))
            value["updated_at"] = now
            self._update_version(
                cursor, algorithm_id, value, int(row["sort_index"]),
                preserved_legacy_remote_fields={
                    field: value.get(field) for field in _LEGACY_REMOTE_VERSION_FIELDS
                },
            )
            cursor.execute(
                "UPDATE w5_algorithm.algorithm SET updated_at=%s WHERE project_id=%s AND id=%s",
                (now, self.project_id, algorithm_id),
            )
            self._bump_revision(cursor)
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
        with self._write() as cursor:
            algorithm = self._read_one(cursor, algorithm_id)
            if algorithm is None:
                raise PlatformError(
                    "ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。",
                    "请刷新算法列表后重试。", 404,
                )
            persisted_current = str(algorithm.get("current_version_id") or "")
            if persisted_current and persisted_current != expected_current_version_id:
                raise PlatformError(
                    "ALGORITHM_VERSION_CONFLICT", "算法当前版本已经发生变化",
                    f"请求基于 {expected_current_version_id}，当前实际版本为 {persisted_current}。",
                    "请刷新算法版本列表后重新确认。", 409,
                )
            cursor.execute(
                "SELECT 1 FROM w5_algorithm.algorithm_version "
                "WHERE project_id=%s AND algorithm_id=%s AND id=%s",
                (self.project_id, algorithm_id, target_version_id),
            )
            if cursor.fetchone() is None:
                raise PlatformError(
                    "ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在",
                    f"找不到版本 {target_version_id}。", "请刷新版本列表后重试。", 404,
                )
            cursor.execute(
                "SELECT " + VERSION_COLUMNS + " FROM w5_algorithm.algorithm_version "
                "WHERE project_id=%s AND algorithm_id=%s AND id=%s",
                (self.project_id, algorithm_id, expected_current_version_id),
            )
            current_row = cursor.fetchone()
            if current_row is None:
                raise PlatformError(
                    "ALGORITHM_VERSION_CONFLICT", "当前版本记录已发生变化",
                    expected_current_version_id, "请刷新后重试。", 409,
                )
            removed = (
                _PROJECTION._version_from_row(dict(current_row))
                if delete_current_version else None
            )
            cursor.execute(
                "SELECT payload::text AS payload_json FROM w5_algorithm.algorithm "
                "WHERE project_id=%s AND id=%s",
                (self.project_id, algorithm_id),
            )
            payload = _json_object(cursor.fetchone()["payload_json"])
            operations = list(payload.get("version_operations") or [])
            operations.append(dict(operation))
            payload["version_operations"] = operations
            cursor.execute(
                "UPDATE w5_algorithm.algorithm SET current_version_id=%s,updated_at=%s,"
                "payload=%s::jsonb WHERE project_id=%s AND id=%s",
                (target_version_id, now, _dumps(payload), self.project_id, algorithm_id),
            )
            if delete_current_version:
                cursor.execute(
                    "DELETE FROM w5_algorithm.algorithm_version "
                    "WHERE project_id=%s AND algorithm_id=%s AND id=%s",
                    (self.project_id, algorithm_id, expected_current_version_id),
                )
            self._bump_revision(cursor)
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
        with self._write() as cursor:
            cursor.execute(
                "SELECT " + VERSION_COLUMNS + " FROM w5_algorithm.algorithm_version "
                "WHERE project_id=%s AND algorithm_id=%s AND id=%s",
                (self.project_id, algorithm_id, version_id),
            )
            raw = cursor.fetchone()
            if raw is None:
                raise PlatformError(
                    "ALGORITHM_VERSION_NOT_FOUND", "算法版本不存在", f"找不到版本 {version_id}。",
                    "请刷新版本列表后重试。", 404,
                )
            row = dict(raw)
            cursor.execute(
                "SELECT current_version_id,payload::text AS payload_json "
                "FROM w5_algorithm.algorithm WHERE project_id=%s AND id=%s",
                (self.project_id, algorithm_id),
            )
            current = cursor.fetchone()
            if current is None:
                raise PlatformError(
                    "ALGORITHM_NOT_FOUND", "算法不存在", f"找不到算法 {algorithm_id}。",
                    "请刷新算法列表后重试。", 404,
                )
            persisted_current = str(current["current_version_id"] or "")
            if (
                persisted_current
                and expected_current_version_id is not None
                and persisted_current != str(expected_current_version_id)
            ):
                raise PlatformError(
                    "ALGORITHM_VERSION_CONFLICT", "算法当前版本已经发生变化",
                    f"请求基于 {expected_current_version_id}，当前实际版本为 {persisted_current}。",
                    "请刷新后重试。", 409,
                )
            if version_id == persisted_current:
                raise PlatformError(
                    "ALGORITHM_CURRENT_VERSION_DELETE_FORBIDDEN", "不能直接删除当前版本",
                    f"版本 {version_id} 当前正在作为算法默认版本。",
                    "请先回退到另一个有效版本，再删除该版本。", 409,
                )
            payload = _json_object(current["payload_json"])
            operations = list(payload.get("version_operations") or [])
            operations.append(dict(operation))
            payload["version_operations"] = operations
            cursor.execute(
                "DELETE FROM w5_algorithm.algorithm_version "
                "WHERE project_id=%s AND algorithm_id=%s AND id=%s",
                (self.project_id, algorithm_id, version_id),
            )
            cursor.execute(
                "UPDATE w5_algorithm.algorithm SET updated_at=%s,payload=%s::jsonb "
                "WHERE project_id=%s AND id=%s",
                (now, _dumps(payload), self.project_id, algorithm_id),
            )
            self._bump_revision(cursor)
        return _PROJECTION._version_from_row(row)

    def update_version_operation(
        self, algorithm_id: str, operation_id: str, patch: Mapping[str, Any]
    ) -> None:
        self.ensure_ready()
        algorithm_id = str(algorithm_id)
        with self._write() as cursor:
            cursor.execute(
                "SELECT payload::text AS payload_json FROM w5_algorithm.algorithm "
                "WHERE project_id=%s AND id=%s",
                (self.project_id, algorithm_id),
            )
            raw = cursor.fetchone()
            if raw is None:
                raise PlatformError(
                    "ALGORITHM_CLEANUP_STATE_LOST", "清理状态无法保存",
                    f"算法 {algorithm_id} 不存在。", "请检查版本操作审计。", 500,
                )
            payload = _json_object(raw["payload_json"])
            operations = list(payload.get("version_operations") or [])
            operation = next(
                (item for item in operations if str(item.get("id") or "") == str(operation_id)),
                None,
            )
            if operation is None:
                raise PlatformError(
                    "ALGORITHM_CLEANUP_STATE_LOST", "清理审计不存在",
                    f"找不到操作记录 {operation_id}。", "请检查算法版本操作审计。", 500,
                )
            operation.update(dict(patch))
            payload["version_operations"] = operations
            cursor.execute(
                "UPDATE w5_algorithm.algorithm SET payload=%s::jsonb "
                "WHERE project_id=%s AND id=%s",
                (_dumps(payload), self.project_id, algorithm_id),
            )
            self._bump_revision(cursor)

    def sync_external_algorithms(
        self, incoming: Mapping[str, Mapping[str, Any]], *, provider: str, synced_at: str
    ) -> dict[str, int]:
        self.ensure_ready()
        provider = str(provider).upper()
        with self._write() as cursor:
            cursor.execute(
                "SELECT id,external_product_id FROM w5_algorithm.algorithm "
                "WHERE project_id=%s AND upper(COALESCE(source_type,''))='EXTERNAL' "
                "AND upper(COALESCE(provider_type,''))=%s",
                (self.project_id, provider),
            )
            rows = [dict(row) for row in cursor.fetchall()]
            existing = {
                str(row["external_product_id"] or ""): str(row["id"])
                for row in rows if row["external_product_id"]
            }
            added = updated = unchanged = 0
            for product_id, master_raw in incoming.items():
                master = dict(master_raw)
                master.update(
                    external_deletion_status="NORMAL", external_deletion_since="",
                    external_deletion_reason="", external_cleanup_operation_id="",
                )
                algorithm_id = existing.get(str(product_id))
                if not algorithm_id:
                    item = {
                        **master,
                        "current_version_id": None,
                        "version_operations": [],
                        "versions": [],
                        "external_last_synced_at": synced_at,
                        "created_at": synced_at,
                        "updated_at": synced_at,
                    }
                    cursor.execute(
                        "SELECT COALESCE(MIN(sort_index),0)-1 AS next "
                        "FROM w5_algorithm.algorithm WHERE project_id=%s",
                        (self.project_id,),
                    )
                    sort_index = int(cursor.fetchone()["next"])
                    self._insert_algorithm(cursor, item, sort_index)
                    self._replace_analyses(cursor, str(item["id"]), item)
                    added += 1
                    continue
                current = self._read_one(cursor, algorithm_id)
                if current is None:
                    continue
                if current.get("external_delete_pending") is True:
                    unchanged += 1
                    continue
                if current.get("external_deletion_status") == "SUSPECTED_DELETED":
                    master["external_deletion_history"] = [
                        *(current.get("external_deletion_history") or []),
                        {"state": "NORMAL", "observed_at": synced_at, "source": "product_reappeared"},
                    ]
                compare_ignored = {
                    "id", "current_version_id", "versions", "version_operations",
                    "created_at", "updated_at", "external_last_synced_at",
                }
                list_fields = {
                    "external_analyses", "external_analysis_ids", "external_compute_platform_ids",
                }

                def comparable(key: str, value: Any) -> Any:
                    if key == "external_analyses":
                        values = [
                            dict(row) for row in (value or []) if isinstance(row, Mapping)
                        ]
                        return sorted(
                            values,
                            key=lambda row: (
                                str(row.get("analysis_id") or row.get("analysisId") or ""),
                                _dumps(row),
                            ),
                        )
                    if key in list_fields:
                        return sorted(str(item) for item in (value or []))
                    return value

                changed = any(
                    comparable(key, current.get(key)) != comparable(key, value)
                    for key, value in master.items()
                    if key not in compare_ignored
                )
                merged = dict(current)
                merged.update(master)
                merged["id"] = algorithm_id
                merged["external_last_synced_at"] = synced_at
                if changed:
                    merged["updated_at"] = synced_at
                    self._update_algorithm(cursor, merged)
                    self._replace_analyses(cursor, algorithm_id, merged)
                    updated += 1
                else:
                    cursor.execute(
                        "UPDATE w5_algorithm.algorithm SET external_last_synced_at=%s "
                        "WHERE project_id=%s AND id=%s",
                        (synced_at, self.project_id, algorithm_id),
                    )
                    unchanged += 1
            incoming_ids = {str(key) for key in incoming}
            suspected = 0
            new_suspicions = 0
            for row in rows:
                product_id = str(row["external_product_id"] or "")
                if product_id in incoming_ids:
                    continue
                current = self._read_one(cursor, str(row["id"]))
                if current is None or current.get("external_delete_pending") is True:
                    continue
                if current.get("external_deletion_status") != "SUSPECTED_DELETED":
                    new_suspicions += 1
                    current.update(
                        external_deletion_status="SUSPECTED_DELETED",
                        external_deletion_since=synced_at,
                        external_deletion_reason=(
                            "本次产品列表未包含该产品；缺少权威删除证据，保留全部成果"
                        ),
                    )
                    current["external_deletion_history"] = [
                        *(current.get("external_deletion_history") or []),
                        {
                            "state": "SUSPECTED_DELETED", "observed_at": synced_at,
                            "source": "product_list_observation", "authoritative": False,
                        },
                    ]
                current["external_deletion_checked_at"] = synced_at
                self._update_algorithm(cursor, current)
                suspected += 1
            if added or updated or new_suspicions:
                self._bump_revision(cursor)
        return {
            "added": added,
            "updated": updated,
            "unchanged": unchanged,
            "suspected_deleted": suspected,
            "deleted": 0,
            "inactivated": 0,
            "total": len(incoming),
        }

    # -- presentation projections are intentionally not ported -------------
    def library_algorithms(self, **_kwargs):
        self._check_operation("library_algorithms")

    def asset_algorithms(self, **_kwargs):
        self._check_operation("asset_algorithms")

    def asset_algorithm_basic(self, *_args, **_kwargs):
        self._check_operation("asset_algorithm_basic")

    def asset_versions(self, *_args, **_kwargs):
        self._check_operation("asset_versions")

    def asset_version(self, *_args, **_kwargs):
        self._check_operation("asset_version")

    def bootstrap_summary(self, *_args, **_kwargs):
        self._check_operation("bootstrap_summary")

    def training_display_refs(self, *_args, **_kwargs):
        self._check_operation("training_display_refs")


def _summary_version_row(row: dict[str, Any]) -> dict[str, Any]:
    """Same compact payload the SQLite ``summary_only`` projection extracts."""
    payload = _json_object(row["payload_json"])
    evaluation = payload.get("evaluation")
    compact = {
        "metrics": payload.get("metrics"),
        "map50": payload.get("map50"),
        "mAP50": payload.get("mAP50"),
        "training_lineage": payload.get("training_lineage"),
        "iteration_decision": payload.get("iteration_decision"),
        "confirmed_iteration_action": payload.get("confirmed_iteration_action"),
        "metric_credibility": payload.get("metric_credibility"),
        "evaluation": None,
    }
    if isinstance(evaluation, dict):
        compact["evaluation"] = {
            "status": evaluation.get("status"),
            "evaluation_id": evaluation.get("evaluation_id"),
            "metrics": evaluation.get("metrics"),
        }
    value = dict(row)
    value["payload_json"] = _dumps(compact)
    return value


def _decode_json(text: Any, *, expect: type) -> Any:
    try:
        value = json.loads(text or ("{}" if expect is dict else "[]"))
    except (TypeError, ValueError) as error:
        raise AlgorithmRepositoryError(
            "ALGORITHM_PG_JSON_INVALID",
            "PostgreSQL algorithm JSON field is not valid JSON",
            detail=str(error),
        ) from error
    if not isinstance(value, expect):
        raise AlgorithmRepositoryError(
            "ALGORITHM_PG_JSON_TYPE_INVALID",
            "PostgreSQL algorithm JSON field has an unexpected type",
            detail=f"expected={expect.__name__} actual={type(value).__name__}",
        )
    return value


def export_target_snapshot(connection, project_id: str) -> dict[str, Any] | None:
    """Read one consistent PostgreSQL project snapshot in the U1 contract shape.

    Payloads are returned as parsed JSON (not JSONB text) so source and target
    content digests compare structurally, independent of JSONB key ordering.
    """
    from psycopg.rows import dict_row

    project_id = str(project_id)
    with connection.cursor(row_factory=dict_row) as cursor:
        cursor.execute(
            "SELECT algorithm_revision FROM w5_algorithm.store_revision WHERE project_id=%s",
            (project_id,),
        )
        meta = cursor.fetchone()
        if meta is None:
            return None
        revision = int(meta["algorithm_revision"])
        cursor.execute(
            f"SELECT {ALGORITHM_COLUMNS} FROM w5_algorithm.algorithm "
            "WHERE project_id=%s ORDER BY project_id, id",
            (project_id,),
        )
        algorithms = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            f"SELECT {_qualified_columns(VERSION_COLUMNS, 'versions.')} "
            "FROM w5_algorithm.algorithm_version AS versions "
            "WHERE versions.project_id=%s ORDER BY versions.algorithm_id, versions.id",
            (project_id,),
        )
        versions = [dict(row) for row in cursor.fetchall()]
        cursor.execute(
            f"SELECT {_qualified_columns(ANALYSIS_COLUMNS, 'analyses.')} "
            "FROM w5_algorithm.algorithm_external_analysis AS analyses "
            "WHERE analyses.project_id=%s "
            "ORDER BY analyses.algorithm_id, analyses.external_analysis_id",
            (project_id,),
        )
        analyses = [dict(row) for row in cursor.fetchall()]
    for row in algorithms:
        row["payload_json"] = _decode_json(row["payload_json"], expect=dict)
    for row in versions:
        row["payload_json"] = _decode_json(row["payload_json"], expect=dict)
    for row in analyses:
        row["payload_json"] = _decode_json(row["payload_json"], expect=dict)
        row["compute_platform_ids_json"] = _decode_json(
            row["compute_platform_ids_json"], expect=list
        )
    tables = {"algorithms": algorithms, "versions": versions, "analyses": analyses}
    body = _snapshot_body(project_id, revision, tables)
    body["snapshot_digest"] = _digest(body)
    from datetime import datetime, timezone

    body["captured_at"] = datetime.now(timezone.utc).isoformat()
    return body
