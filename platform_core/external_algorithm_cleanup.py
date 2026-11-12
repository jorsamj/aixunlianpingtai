"""Confirmed product retirement using the existing SQL store and Durable Worker.

No provider absence heuristic is registered here. A trusted server adapter must
verify an explicit product-deletion contract before submitting evidence.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import sqlite3
import time
from contextlib import ExitStack, closing
from dataclasses import asdict, dataclass
from pathlib import Path

from filelock import FileLock

from .algorithm_sql_store import AlgorithmSqlStore
from .errors import PlatformError
from .task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository, TaskStatus
from .task_runtime.models import utc_now

logger = logging.getLogger(__name__)


NORMAL = "NORMAL"
SUSPECTED = "SUSPECTED_DELETED"
CONFIRMED = "CONFIRMED_DELETED"
PENDING = "CLEANUP_PENDING"
RUNNING = "CLEANUP_RUNNING"
FAILED = "CLEANUP_FAILED"
COMPLETED = "CLEANUP_COMPLETED"
_SCHEMA = """CREATE TABLE IF NOT EXISTS external_algorithm_cleanup (
    operation_id TEXT PRIMARY KEY, algorithm_id TEXT NOT NULL, product_id TEXT NOT NULL,
    state TEXT NOT NULL, payload_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
); CREATE UNIQUE INDEX IF NOT EXISTS external_algorithm_cleanup_identity
ON external_algorithm_cleanup(algorithm_id,product_id) WHERE state<>'CLEANUP_COMPLETED';"""


def _error(code, message):
    return PlatformError(code, message, "", "保留成果并核对删除证据或清理回执。", 409)


@dataclass(frozen=True)
class DeletionEvidence:
    provider: str
    product_id: str
    source: str
    contract_id: str
    evidence_id: str
    observed_at: str
    scope: str = "PRODUCT_DELETED"


@dataclass(frozen=True)
class VerifiedDeletionContract:
    """Server-only configuration, never accepted from API request payloads.

    The caller is responsible for verifying authenticity (e.g. signed event)
    under this contract before constructing DeletionEvidence. No contracts are
    enabled by default; ordinary 404/null responses have no registered meaning.
    """
    contract_id: str
    source: str
    provider: str = "CHANG_LIAN"


class CleanupRepository:
    def __init__(self, algorithms_path: Path, *, contracts=()):
        self.store = AlgorithmSqlStore(algorithms_path)
        self.contracts = tuple(contracts)
        self.store.ensure_ready()
        with closing(self.store._connect()) as db:
            db.executescript(_SCHEMA)

    @staticmethod
    def _value(row):
        return json.loads(row["payload_json"]) if row else None

    def get(self, operation_id):
        with closing(self.store._connect()) as db:
            return self._value(db.execute("SELECT * FROM external_algorithm_cleanup WHERE operation_id=?", (operation_id,)).fetchone())

    def list_operations(self):
        with closing(self.store._connect()) as db:
            return [self._value(row) for row in db.execute("SELECT * FROM external_algorithm_cleanup ORDER BY created_at,operation_id")]

    def confirm_deleted(self, algorithm_id, evidence: DeletionEvidence):
        if not isinstance(evidence, DeletionEvidence) or evidence.scope != "PRODUCT_DELETED":
            raise _error("EXTERNAL_DELETE_EVIDENCE_INVALID", "只接受明确的产品删除证据")
        if not any(c.contract_id == evidence.contract_id and c.source == evidence.source and
                   c.provider == evidence.provider for c in self.contracts):
            raise _error("EXTERNAL_DELETE_CONTRACT_UNVERIFIED", "未配置经过验证的产品删除契约")
        if (evidence.source not in {"authoritative_event", "verified_detail_absence", "verified_complete_snapshots", "event"}
                or not evidence.evidence_id or not evidence.observed_at or not evidence.product_id):
            raise _error("EXTERNAL_DELETE_EVIDENCE_INVALID", "产品删除证据不完整")
        identity = json.dumps([self.store.project_id, algorithm_id, evidence.product_id,
                               evidence.contract_id, evidence.evidence_id], separators=(",", ":"))
        operation_id = hashlib.sha256(identity.encode()).hexdigest()[:32]
        stamp = utc_now()
        with closing(self.store._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            old = self._value(db.execute("SELECT * FROM external_algorithm_cleanup WHERE operation_id=?", (operation_id,)).fetchone())
            if old:
                return old
            row = self.store._read_one_conn(db, algorithm_id)
            if (not row or row.get("source_type") != "EXTERNAL" or row.get("provider_type") != evidence.provider
                    or str(row.get("external_product_id")) != evidence.product_id):
                raise _error("EXTERNAL_DELETE_IDENTITY_CHANGED", "产品删除证据与算法身份不一致")
            active = self._value(db.execute("SELECT * FROM external_algorithm_cleanup WHERE algorithm_id=? AND product_id=? AND state<>?",
                                 (algorithm_id, evidence.product_id, COMPLETED)).fetchone())
            if active:
                if row.get("external_cleanup_operation_id") != active["operation_id"]:
                    raise _error("EXTERNAL_CLEANUP_GENERATION_CHANGED", "算法删除状态与清理意图不一致")
                return active
            operation = dict(operation_id=operation_id, task_id="external-cleanup-" + operation_id,
                             project_id=self.store.project_id, algorithm_id=algorithm_id,
                             name=str(row.get("name") or algorithm_id),
                             product_id=evidence.product_id, generation=operation_id,
                             state=CONFIRMED, phase="confirmed", evidence=asdict(evidence),
                             created_at=stamp, updated_at=stamp, error="", counts={},
                             history=[{"state": CONFIRMED, "phase": "confirmed", "observed_at": stamp}])
            row.update(external_active=False, external_delete_pending=True,
                       external_delete_pending_at=stamp, external_deletion_status=CONFIRMED,
                       external_deletion_since=stamp, external_deletion_reason="已取得可信产品删除证据，等待安全清理",
                       external_cleanup_operation_id=operation_id)
            self.store._update_algorithm_conn(db, row)
            self.store._bump_revision(db)
            db.execute("INSERT INTO external_algorithm_cleanup VALUES(?,?,?,?,?,?,?)",
                       (operation_id, algorithm_id, evidence.product_id, CONFIRMED,
                        json.dumps(operation, ensure_ascii=False), stamp, stamp))
            db.commit()
        return operation

    def update(self, operation_id, *, remove_algorithm=False, expected_states=None, **patch):
        with closing(self.store._connect()) as db:
            db.execute("BEGIN IMMEDIATE")
            op = self._value(db.execute("SELECT * FROM external_algorithm_cleanup WHERE operation_id=?", (operation_id,)).fetchone())
            if not op:
                raise _error("EXTERNAL_CLEANUP_OPERATION_MISSING", "清理记录不存在")
            row = self.store._read_one_conn(db, op["algorithm_id"])
            if op["state"] == COMPLETED:
                raise _error("EXTERNAL_CLEANUP_ALREADY_COMPLETED", "已完成清理回执不可重写")
            if expected_states is not None and op["state"] not in expected_states:
                raise _error("EXTERNAL_CLEANUP_STATE_CHANGED", "清理状态已变化，请刷新状态")
            if (not row or row.get("external_cleanup_operation_id") != operation_id
                    or not row.get("external_delete_pending") or str(row.get("external_product_id")) != op["product_id"]):
                raise _error("EXTERNAL_CLEANUP_GENERATION_CHANGED", "清理身份或归属已变化")
            stamp = utc_now()
            if any(patch.get(key, op.get(key)) != op.get(key) for key in ("state", "phase")):
                op.setdefault("history", []).append({"state": patch.get("state", op["state"]),
                    "phase": patch.get("phase", op["phase"]), "observed_at": stamp})
            op.update(patch, updated_at=stamp)
            if remove_algorithm:
                if op["state"] != COMPLETED:
                    raise _error("EXTERNAL_CLEANUP_NOT_COMPLETE", "清理未完成，不能移除算法")
                db.execute("DELETE FROM algorithms WHERE project_id=? AND id=?", (self.store.project_id, op["algorithm_id"]))
            elif row:
                if row.get("external_deletion_status") != op["state"]:
                    row.update(external_deletion_status=op["state"])
                    self.store._update_algorithm_conn(db, row)
                    self.store._bump_revision(db)
            db.execute("UPDATE external_algorithm_cleanup SET state=?,payload_json=?,updated_at=? WHERE operation_id=?",
                       (op["state"], json.dumps(op, ensure_ascii=False), op["updated_at"], operation_id))
            if remove_algorithm:
                self.store._bump_revision(db)
            db.commit()
        return op

    def dispatch(self, data_dir: Path, *, retry_failed=False, operation_id=None):
        """Outbox delivery only. No remote I/O or destructive work here."""
        tasks = TaskRepository(Path(data_dir) / "task_runtime" / "tasks.sqlite3")
        artifacts = ArtifactStore(Path(data_dir) / "task_runtime" / "artifacts")
        delivered = 0
        for op in self.list_operations():
            if operation_id is not None and op["operation_id"] != operation_id:
                continue
            if op["state"] not in {CONFIRMED, PENDING} and not (retry_failed and op["state"] == FAILED):
                continue
            # Serialize intent publishing across web processes/worker heartbeats.
            with FileLock(str(self.store.db_path) + ".cleanup-outbox.lock", timeout=0):
                current = self.get(op["operation_id"])
                if current["state"] not in {CONFIRMED, PENDING} and not (retry_failed and current["state"] == FAILED):
                    continue
                self.update(op["operation_id"], state=PENDING, phase="queued", error="",
                            expected_states={CONFIRMED, PENDING, FAILED} if retry_failed else {CONFIRMED, PENDING})
                task = tasks.get(op["task_id"])
                payload = {key: op[key] for key in ("operation_id", "project_id", "algorithm_id", "product_id", "generation")}
                if task:
                    existing = artifacts.read_json(task.task_id, task.payload_ref)
                    if task.kind != TaskKind.EXTERNAL_ALGORITHM_CLEANUP or task.project_id != op["project_id"] or existing != payload:
                        raise _error("EXTERNAL_CLEANUP_TASK_CONFLICT", "清理任务身份冲突")
                    if retry_failed and task.status in {TaskStatus.FAILED, TaskStatus.BLOCKED_BY_ENVIRONMENT,
                                                       TaskStatus.BLOCKED_BY_HARDWARE, TaskStatus.CANCELLED}:
                        tasks.retry(task.task_id)
                else:
                    artifacts.atomic_write_json(op["task_id"], "request.json", payload)
                    tasks.create(TaskRecord.new(op["task_id"], op["project_id"], TaskKind.EXTERNAL_ALGORITHM_CLEANUP,
                                 "request.json", f"external-cleanup:{op['project_id']}:{op['algorithm_id']}",
                                 required_capabilities=("external.cleanup",)), artifacts=artifacts)
                delivered += 1
        return delivered

    @staticmethod
    def _suspected(row):
        payload = json.loads(row["payload_json"])
        return dict(operation_id="suspect:" + row["id"], algorithm_id=row["id"],
            product_id=str(row["external_product_id"] or ""), name=row["name"],
            state=SUSPECTED, phase="verification_required",
            evidence={"source": "product_list_observation", "authoritative": False},
            created_at=payload.get("external_deletion_since"),
            updated_at=payload.get("external_deletion_checked_at") or payload.get("external_deletion_since"),
            current_item=payload.get("external_deletion_reason"), history=payload.get("external_deletion_history") or [],
            task_id="", error="", counts={})

    def summary(self):
        with closing(self.store._connect()) as db:
            result = {str(row[0]): int(row[1]) for row in db.execute(
                "SELECT state,COUNT(*) FROM external_algorithm_cleanup GROUP BY state")}
            result[SUSPECTED] = int(db.execute(
                "SELECT COUNT(*) FROM algorithms WHERE project_id=? AND json_extract(payload_json,'$.external_deletion_status')=?",
                (self.store.project_id, SUSPECTED)).fetchone()[0])
        return {state: result.get(state, 0) for state in (SUSPECTED, CONFIRMED, PENDING, RUNNING, FAILED, COMPLETED)}

    def public_operations(self, *, limit=25, offset=0):
        limit, offset = max(1, min(100, int(limit))), max(0, int(offset))
        with closing(self.store._connect()) as db:
            rows = db.execute("""
                SELECT operation_id,updated_at,'operation' AS kind,payload_json,'' AS id,'' AS name,'' AS external_product_id
                FROM external_algorithm_cleanup
                UNION ALL
                SELECT 'suspect:'||id,COALESCE(json_extract(payload_json,'$.external_deletion_checked_at'),json_extract(payload_json,'$.external_deletion_since')),'suspect',payload_json,id,name,external_product_id
                FROM algorithms WHERE project_id=? AND json_extract(payload_json,'$.external_deletion_status')=?
                ORDER BY updated_at DESC,operation_id DESC LIMIT ? OFFSET ?
                """, (self.store.project_id, SUSPECTED, limit, offset)).fetchall()
        return [self._suspected(row) if row["kind"] == "suspect" else self._value(row) for row in rows]

    def public_operation(self, operation_id):
        if not operation_id.startswith("suspect:"):
            return self.get(operation_id)
        with closing(self.store._connect()) as db:
            row = db.execute("SELECT id,name,external_product_id,payload_json FROM algorithms WHERE project_id=? AND id=? AND json_extract(payload_json,'$.external_deletion_status')=?",
                (self.store.project_id, operation_id[len("suspect:"):], SUSPECTED)).fetchone()
        return self._suspected(row) if row else None


def dispatch_cleanup_outboxes(data_dir: Path):
    """Called by the original storage heartbeat; failed delivery remains durable."""
    root = Path(data_dir) / "projects"
    count = 0
    for path in root.glob("*/algorithms.sqlite3") if root.is_dir() else ():
        # Do not create/migrate stores without cleanup intents during a heartbeat.
        with closing(sqlite3.connect(path)) as db:
            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='external_algorithm_cleanup'").fetchone()
        if exists:
            repository = CleanupRepository(path.parent / "algorithms.json")
            try:
                count += repository.dispatch(data_dir)
            except Exception as error:
                logger.exception("External cleanup outbox delivery failed for project %s", path.parent.name)
                # Preserve the committed intent and surface the dispatch failure;
                # other projects and the fixed master-data schedule continue.
                for operation in repository.list_operations():
                    if operation["state"] in {CONFIRMED, PENDING}:
                        repository.update(operation["operation_id"], phase="dispatch_failed",
                                          error=f"清理任务派送失败（{type(error).__name__}），等待原Worker重试")
    return count


def _safe_component(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", value) or value in {".", ".."}:
        raise _error("EXTERNAL_CLEANUP_PATH_INVALID", "清理对象路径身份非法")
    return value


def assert_safe_cleanup_path(path: Path, root: Path):
    """Reject traversal, links/junctions and Windows stream/device aliases."""
    path, root = Path(path), Path(root)
    try:
        relative = path.absolute().relative_to(root.absolute())
    except ValueError:
        raise _error("EXTERNAL_CLEANUP_PATH_UNSAFE", "清理路径超出可信范围")
    reserved = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
    for part in relative.parts:
        if part in {".", ".."} or ":" in part or part.rstrip(". ") != part or part.split(".")[0].upper() in reserved:
            raise _error("EXTERNAL_CLEANUP_PATH_UNSAFE", "清理路径包含非法文件名")
    for current in (root, *[path.parents[i] for i in range(len(relative.parts) - 1)], path):
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise _error("EXTERNAL_CLEANUP_PATH_UNSAFE", "清理路径包含链接或重解析目录")
    if path.resolve() != root.resolve() and root.resolve() not in path.resolve().parents:
        raise _error("EXTERNAL_CLEANUP_PATH_UNSAFE", "清理路径解析后越界")
    return path


class ExternalAlgorithmCleanupHandler:
    def __init__(self, data_dir: Path, *, model_service_factory=None, stop_timeout_seconds=60, stop_poll_seconds=1):
        self.data_dir = Path(data_dir)
        self.model_service_factory = model_service_factory
        self.stop_timeout_seconds = max(0.01, float(stop_timeout_seconds))
        self.stop_poll_seconds = max(0.01, float(stop_poll_seconds))

    def _models(self):
        if self.model_service_factory:
            return self.model_service_factory()
        from .external_algorithm_platform import ExternalAlgorithmLocalPurger
        from .secrets import KeyringSecretStore
        return ExternalAlgorithmLocalPurger(self.data_dir, lambda: KeyringSecretStore(
            encrypted_path=self.data_dir / "secure" / "secrets.enc.json")).model_service()

    @staticmethod
    def _check(context, repo, op):
        context.assert_current_execution()
        if context.cancel_requested():
            raise _error("EXTERNAL_CLEANUP_CANCELLED", "清理已暂停，已完成步骤仍保留回执")
        current = repo.get(op["operation_id"])
        if not current or current["generation"] != op["generation"] or current["state"] == COMPLETED:
            raise _error("EXTERNAL_CLEANUP_GENERATION_CHANGED", "清理执行归属已变化")
        # Also checks the current canonical algorithm marker before side effects.
        repo.update(op["operation_id"], phase=current["phase"])

    def _owned_tasks(self, project_id, algorithm_id, tasks, artifacts):
        from .external_algorithm_platform import ExternalAlgorithmLocalPurger
        project_root = self.data_dir / "projects" / project_id
        owned = {}
        cursor = None
        while True:
            page = tasks.list(project_id=project_id, limit=100, cursor=cursor)
            for task in page.items:
                if task.kind == TaskKind.EXTERNAL_ALGORITHM_CLEANUP:
                    continue
                payload = artifacts.read_json(task.task_id, task.payload_ref, default=None)
                if not isinstance(payload, dict):
                    if task.kind in {TaskKind.TRAINING, TaskKind.MODEL_CONVERSION, TaskKind.TRAINING_PREPARE, TaskKind.DEPLOYMENT_TEST}:
                        raise _error("EXTERNAL_CLEANUP_TASK_UNVERIFIED", "任务请求损坏，不能证明安全清理范围")
                    continue
                source = payload.get("source_meta") or payload.get("source_trace") or {}
                identity = payload.get("algorithm_asset_id") or payload.get("asset_algorithm_id") or payload.get("algorithm_id")
                if not identity and isinstance(source, dict):
                    identity = source.get("algorithm_id")
                if not identity and task.kind in {TaskKind.TRAINING, TaskKind.MODEL_CONVERSION}:
                    candidates = [project_root / "jobs" / task.task_id] if task.kind == TaskKind.TRAINING else [
                        project_root / "deploy/jobs" / task.task_id, project_root / "deployment/jobs" / task.task_id]
                    declared = payload.get("job_dir")
                    if declared and Path(str(declared)).resolve() not in {path.resolve() for path in candidates}:
                        raise _error("EXTERNAL_CLEANUP_TASK_UNVERIFIED", "历史任务目录与持久身份不一致")
                    job_paths = [path / "job.json" for path in candidates if (path / "job.json").is_file()]
                    if len(job_paths) != 1 or any(part.is_symlink() for part in [*job_paths[0].parents, job_paths[0]]):
                        raise _error("EXTERNAL_CLEANUP_TASK_UNVERIFIED", "历史任务缺少可信算法身份，暂缓清理")
                    try:
                        job = json.loads(job_paths[0].read_text(encoding="utf-8"))
                        if not isinstance(job, dict):
                            raise ValueError("invalid job")
                    except (OSError, ValueError):
                        raise _error("EXTERNAL_CLEANUP_TASK_UNVERIFIED", "历史任务记录损坏，暂缓清理")
                    identity = (ExternalAlgorithmLocalPurger._training_algorithm_id(job, payload)
                        if task.kind == TaskKind.TRAINING else ExternalAlgorithmLocalPurger._deploy_algorithm_id(job))
                if task.kind in {TaskKind.TRAINING, TaskKind.MODEL_CONVERSION} and str(identity or "") == algorithm_id:
                    owned[task.task_id] = task
            cursor = page.next_cursor
            if not cursor:
                break
        # Resolve linked prepare/test tasks from their immutable payloads.
        cursor = None
        while True:
            page = tasks.list(project_id=project_id, limit=100, cursor=cursor)
            for task in page.items:
                payload = artifacts.read_json(task.task_id, task.payload_ref, default={})
                if not isinstance(payload, dict):
                    continue
                parent = payload.get("training_task_id") if task.kind == TaskKind.TRAINING_PREPARE else payload.get("source_conversion_job_id") if task.kind == TaskKind.DEPLOYMENT_TEST else None
                if str(parent or "") in owned:
                    owned[task.task_id] = task
            cursor = page.next_cursor
            if not cursor:
                break
        # Legacy jobs have no durable cancellation owner. Keep live work intact
        # and fail closed; terminal owned jobs can join the same frozen plan.
        for suffix, resolver in (("jobs", ExternalAlgorithmLocalPurger._training_algorithm_id),
                                 ("deploy/jobs", ExternalAlgorithmLocalPurger._deploy_algorithm_id),
                                 ("deployment/jobs", ExternalAlgorithmLocalPurger._deploy_algorithm_id)):
            for path in (project_root / suffix).glob("*/job.json"):
                try:
                    job = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    raise _error("EXTERNAL_CLEANUP_TASK_UNVERIFIED", "任务记录损坏，暂缓清理")
                if not isinstance(job, dict):
                    raise _error("EXTERNAL_CLEANUP_TASK_UNVERIFIED", "任务记录格式异常，暂缓清理")
                if resolver(job) != algorithm_id:
                    continue
                task_id = str(job.get("task_id") or job.get("id") or path.parent.name)
                if task_id != path.parent.name:
                    raise _error("EXTERNAL_CLEANUP_TASK_UNVERIFIED", "任务目录与业务身份不一致")
                durable = tasks.get(task_id)
                if durable is None:
                    if str(job.get("status") or "").lower() not in {
                        "done", "finished", "completed", "success", "succeeded", "partial_success", "failed", "cancelled", "stopped", "blocked_by_environment", "blocked_by_hardware"}:
                        raise _error("EXTERNAL_CLEANUP_LEGACY_TASK_ACTIVE", "旧任务尚未安全停止，保留全部成果")
                    owned[task_id] = None
        return owned

    def _check_shared_paths(self, plan, models, project_root, *, preflight=False):
        from .algorithms import list_algorithms
        owned = set(plan["tasks"])
        roots = [project_root / suffix / task_id for suffix in ("jobs", "deploy/jobs", "deployment/jobs", "predictions")
                 for task_id in owned]
        roots.extend(self.data_dir / "task_runtime/artifacts" / task_id for task_id in owned)
        roots.append(project_root / "algorithm_versions" / plan["algorithm"]["id"])
        roots.extend(Path(str(row["source_path"])) for row in plan["artifacts"])
        normalized = tuple(str(root.resolve()).replace("\\", "/").rstrip("/").casefold() for root in roots)
        frozen_ids = {row["artifact_id"] for row in plan["artifacts"]}
        version_sources = {f"version::{plan['algorithm']['id']}::{v['id']}" for v in plan["algorithm"].get("versions") or []}

        def references(value, *, relative_roots=()):
            pending = [("", value)]
            while pending:
                field, item = pending.pop()
                if isinstance(item, dict):
                    pending.extend((str(key), child) for key, child in item.items())
                elif isinstance(item, (list, tuple)):
                    pending.extend((field, child) for child in item)
                elif isinstance(item, str) and item:
                    text = item.replace("\\", "/").rstrip("/").casefold()
                    texts = [text]
                    if "/" in text or field in {"stored_path", "best", "last", "checkpoint", "path", "source_path", "base_model_reference"}:
                        texts.extend(str((base / item).resolve()).replace("\\", "/").rstrip("/").casefold()
                                     for base in (*relative_roots, self.data_dir))
                    if any(text == root or text.startswith(root + "/") for root in normalized for text in texts):
                        return True
                    if item in version_sources or (field.endswith("artifact_id") and item in frozen_ids):
                        return True
                    if (field in {"task_id", "job_id"} or field.endswith("_task_id") or field.endswith("_job_id")) and item in owned:
                        return True
            return False

        for path in (self.data_dir / "projects").glob("*/algorithms.sqlite3"):
            for algorithm in list_algorithms(path.parent / "algorithms.json"):
                if path.parent == project_root and algorithm["id"] == plan["algorithm"]["id"]:
                    continue
                # The complete version payload includes historical stored_path,
                # best/last, checkpoint and recovery fields, even without an
                # Artifact index or training_job_id.
                if references(algorithm.get("versions") or [], relative_roots=(path.parent,)):
                    raise _error("EXTERNAL_CLEANUP_FILE_SHARED", "模型或任务目录仍被其他算法版本引用")
        with closing(models.repository._connect()) as db:
            for row in db.execute("SELECT artifact_id,source_path,project_id,algorithm_id FROM model_artifacts"):
                if row["artifact_id"] in frozen_ids:
                    continue
                if preflight and row["project_id"] == project_root.name and row["algorithm_id"] == plan["algorithm"]["id"]:
                    continue
                if references({"source_path": row["source_path"]}, relative_roots=(self.data_dir / "projects" / row["project_id"],)):
                    raise _error("EXTERNAL_CLEANUP_FILE_SHARED", "任务文件仍被其他模型成果引用")
        tasks = TaskRepository(self.data_dir / "task_runtime/tasks.sqlite3")
        artifacts = ArtifactStore(self.data_dir / "task_runtime/artifacts")
        cleanup_task_id = "external-cleanup-" + str(plan["algorithm"].get("external_cleanup_operation_id") or "")
        cursor = None
        while True:
            page = tasks.list(limit=100, cursor=cursor)
            for task in page.items:
                if task.task_id in owned or task.task_id == cleanup_task_id:
                    continue
                if task.kind == TaskKind.EXTERNAL_ALGORITHM_CLEANUP and task.status == TaskStatus.SUCCEEDED:
                    continue
                try:
                    payload = artifacts.read_json(task.task_id, task.payload_ref, default=None)
                    if not isinstance(payload, dict):
                        raise ValueError("unknown durable request")
                    documents = [payload]
                    declared = {str(payload[key]) for key in ("prepared_input_ref", "input_freeze_ref", "checkpoint_ref", "source_checkpoint_ref", "label_contract_ref")
                                if payload.get(key)}
                    optional = {"checkpoints/worker.json", "failure.json", "checkpoint.json", "cleanup/plan.json"}
                    if task.result_ref and str(task.result_ref).endswith(".json"):
                        optional.add(str(task.result_ref))
                    for ref in declared | optional:
                        path = artifacts.artifact_path(task.task_id, ref)
                        if path.exists():
                            document = artifacts.read_json(task.task_id, ref)
                            if not isinstance(document, (dict, list)):
                                raise ValueError("unknown durable reference")
                            documents.append(document)
                        elif ref in declared:
                            raise ValueError("missing durable reference")
                except (OSError, ValueError, TypeError, KeyError):
                    raise _error("EXTERNAL_CLEANUP_REFERENCE_UNVERIFIED", "其他任务的冻结引用不完整，暂缓清理")
                if any(references(document, relative_roots=(self.data_dir / "projects" / task.project_id,
                                                            artifacts.root / task.task_id)) for document in documents):
                    raise _error("EXTERNAL_CLEANUP_TASK_SHARED", "其他任务仍引用该算法的模型或检查点，保留文件和任务")
            cursor = page.next_cursor
            if not cursor:
                break

    @staticmethod
    def _quarantine(path: Path, root: Path, recovery: Path, *, before_move=None):
        # Exact per-task/per-algorithm directories only. Never follow links.
        if not path.exists() and not path.is_symlink():
            return
        assert_safe_cleanup_path(path, root)
        if path.is_dir():
            for item in path.rglob("*"):
                assert_safe_cleanup_path(item, root)
        destination = recovery / hashlib.sha256(str(path.relative_to(root)).encode()).hexdigest()[:20]
        recovery.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise _error("EXTERNAL_CLEANUP_RECOVERY_CONFLICT", "恢复目录已存在且源目录再次出现，停止清理")
        if before_move:
            before_move()
        path.rename(destination)

    def run(self, context):
        payload = context.artifacts.read_json(context.task.task_id, context.task.payload_ref)
        project_id = _safe_component(context.task.project_id)
        project_root = self.data_dir / "projects" / project_id
        assert_safe_cleanup_path(project_root, self.data_dir)
        repo = CleanupRepository(project_root / "algorithms.json")
        op = repo.get(payload["operation_id"])
        if not op or any(payload.get(key) != op.get(key) for key in ("project_id", "algorithm_id", "product_id", "generation")) or op["task_id"] != context.task.task_id:
            raise _error("EXTERNAL_CLEANUP_TASK_CONFLICT", "清理任务与持久删除意图不一致")
        if op["state"] == COMPLETED:
            return TaskStatus.SUCCEEDED, "cleanup/result.json"
        checkpoint = context.load_checkpoint()
        done = set(checkpoint.get("done") or [])
        recovery = self.data_dir / "external_cleanup_recovery" / op["operation_id"]
        assert_safe_cleanup_path(recovery, self.data_dir)
        tasks = TaskRepository(self.data_dir / "task_runtime" / "tasks.sqlite3")
        artifacts = ArtifactStore(self.data_dir / "task_runtime" / "artifacts")
        algorithm_id = _safe_component(op["algorithm_id"])
        def complete(step):
            done.add(step)
            context.save_checkpoint({"operation_id": op["operation_id"], "generation": op["generation"], "done": sorted(done)})
            context.heartbeat(stage=step, current_item="正在安全清理已确认删除的外部算法")
            repo.update(op["operation_id"], phase=step, current_item="正在安全清理已确认删除的外部算法",
                        counts={"processed": len(done), "total": len(plan["artifacts"]) * 2 + len(plan["tasks"]) + 2})
        try:
            with FileLock(str(repo.store.db_path) + ".cleanup-" + op["operation_id"] + ".lock", timeout=0), ExitStack() as fences:
                self._check(context, repo, op)
                repo.update(op["operation_id"], state=RUNNING, phase="waiting_for_tasks", error="")
                owned = self._owned_tasks(project_id, algorithm_id, tasks, artifacts)
                from .algorithms import list_algorithms
                row = next(row for row in list_algorithms(repo.store.json_path) if row["id"] == algorithm_id)
                models = self._models()
                existing_models = []
                offset = 0
                while True:
                    page = models.repository.list(project_id=project_id, algorithm_id=algorithm_id, limit=500, offset=offset)
                    existing_models.extend(page)
                    if len(page) < 500:
                        break
                    offset += len(page)
                self._check_shared_paths({"tasks": sorted(owned), "artifacts": existing_models, "algorithm": row}, models, project_root, preflight=True)
                waiting = []
                for task_id in owned:
                    self._check(context, repo, op)
                    task = tasks.get(task_id)
                    if task and task.status in {TaskStatus.RUNNING, TaskStatus.QUEUED, TaskStatus.AWAITING_CONFIRMATION, TaskStatus.CANCEL_REQUESTED}:
                        task = tasks.request_cancel(task_id)
                    if task and task.status in {TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:
                        waiting.append(task_id)
                deadline = time.monotonic() + self.stop_timeout_seconds
                while waiting:
                    self._check(context, repo, op)
                    context.heartbeat(stage="waiting_for_tasks", current_item=f"等待 {len(waiting)} 个关联任务安全退出")
                    repo.update(op["operation_id"], current_item=f"等待 {len(waiting)} 个关联任务安全退出")
                    waiting = [task_id for task_id in waiting if (tasks.get(task_id) is not None and
                        tasks.get(task_id).status in {TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED})]
                    if not waiting:
                        break
                    if time.monotonic() >= deadline:
                        raise _error("EXTERNAL_ALGORITHM_DELETE_STOP_TIMEOUT", "关联任务安全停止超时，保留成果并允许重试")
                    time.sleep(min(self.stop_poll_seconds, max(0, deadline - time.monotonic())))
                from .model_artifacts import model_delivery_version_fence
                row = next(row for row in list_algorithms(repo.store.json_path) if row["id"] == algorithm_id)
                for version in sorted(row.get("versions") or [], key=lambda v: v["id"]):
                    fences.enter_context(model_delivery_version_fence(self.data_dir, project_id, algorithm_id, version["id"]))
                plan = context.artifacts.read_json(context.task.task_id, "cleanup/plan.json", default=None)
                if plan is None:
                    model_rows = []
                    offset = 0
                    while True:
                        page = models.repository.list(project_id=project_id, algorithm_id=algorithm_id, limit=500, offset=offset)
                        model_rows.extend(page)
                        if len(page) < 500:
                            break
                        offset += len(page)
                    plan = {"operation_id": op["operation_id"], "generation": op["generation"],
                            "tasks": sorted(owned), "artifacts": model_rows, "algorithm": row}
                    plan["digest"] = hashlib.sha256(json.dumps(plan, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
                    context.artifacts.atomic_write_json(context.task.task_id, "cleanup/plan.json", plan)
                if plan.get("generation") != op["generation"] or plan.get("operation_id") != op["operation_id"]:
                    raise _error("EXTERNAL_CLEANUP_PLAN_CHANGED", "清理计划身份不一致")
                original = dict(plan)
                digest = original.pop("digest", None)
                if digest != hashlib.sha256(json.dumps(original, sort_keys=True, ensure_ascii=False).encode()).hexdigest():
                    raise _error("EXTERNAL_CLEANUP_PLAN_CHANGED", "清理计划摘要不一致")
                if set(owned) - set(plan["tasks"]):
                    raise _error("EXTERNAL_CLEANUP_PLAN_CHANGED", "冻结后出现新的关联任务，需核验清理计划")
                self._check_shared_paths(plan, models, project_root)
                def guard():
                    self._check(context, repo, op)
                    self._check_shared_paths(plan, models, project_root)
                for artifact in plan["artifacts"]:
                    step = "object:" + artifact["artifact_id"]
                    if step not in done:
                        guard()
                        models.purge_confirmed_artifact(artifact, recovery / "objects",
                            before_delete=guard)
                        complete(step)
                for artifact in plan["artifacts"]:
                    step = "source:" + artifact["artifact_id"]
                    if step in done:
                        continue
                    guard()
                    source = Path(str(artifact["source_path"]))
                    if source.exists() or source.is_symlink():
                        allowed = [project_root / "models", project_root / "algorithm_versions" / algorithm_id]
                        allowed.extend(project_root / suffix / task_id for suffix in ("jobs", "deploy/jobs", "deployment/jobs") for task_id in plan["tasks"])
                        if source.is_symlink() or not any(root.resolve() in source.resolve().parents for root in allowed):
                            raise _error("EXTERNAL_CLEANUP_FILE_UNVERIFIED", "模型源文件不在该算法的可清理范围内")
                        digest = hashlib.sha256()
                        with source.open("rb") as stream:
                            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                                digest.update(chunk)
                        if source.stat().st_size != int(artifact["size_bytes"]) or digest.hexdigest() != artifact["sha256"]:
                            raise _error("EXTERNAL_CLEANUP_FILE_CHANGED", "模型源文件内容已变化，保留文件")
                        self._quarantine(source, project_root, recovery / "local", before_move=guard)
                    complete(step)
                for task_id in plan["tasks"]:
                    step = "task:" + task_id
                    if step in done:
                        continue
                    _safe_component(task_id)
                    guard()
                    task = tasks.get(task_id)
                    if task and task.task_id not in owned:
                        raise _error("EXTERNAL_CLEANUP_TASK_CHANGED", "任务归属已变化")
                    if task and task.status not in {TaskStatus.SUCCEEDED, TaskStatus.PARTIAL_SUCCESS, TaskStatus.FAILED, TaskStatus.CANCELLED, TaskStatus.BLOCKED_BY_ENVIRONMENT, TaskStatus.BLOCKED_BY_HARDWARE}:
                        raise _error("EXTERNAL_CLEANUP_TASK_ACTIVE", "关联任务仍未终止")
                    for suffix in ("jobs", "deploy/jobs", "deployment/jobs", "predictions"):
                        self._quarantine(project_root / suffix / task_id, project_root, recovery / "local", before_move=guard)
                    if task:
                        tasks.delete_terminal(task_id, project_id=project_id, kind=task.kind)
                    self._quarantine(artifacts.root / task_id, artifacts.root, recovery / "task_artifacts", before_move=guard)
                    complete(step)
                if "versions" not in done:
                    guard()
                    self._quarantine(project_root / "algorithm_versions" / algorithm_id, project_root, recovery / "local", before_move=guard)
                    complete("versions")
                if "publications" not in done:
                    from .external_algorithm_publish import ExternalPublicationRepository
                    guard()
                    ExternalPublicationRepository(self.data_dir).delete_algorithm(project_id, algorithm_id)
                    complete("publications")
                guard()
                result = {"operation_id": op["operation_id"], "state": COMPLETED,
                          "processed": len(done), "total": len(plan["artifacts"]) * 2 + len(plan["tasks"]) + 2,
                          "tasks_deleted": len(plan["tasks"]), "artifacts_deleted": len(plan["artifacts"]),
                          "recovery_retained": True}
                context.artifacts.atomic_write_json(context.task.task_id, "cleanup/result.json", result)
                repo.update(op["operation_id"], state=COMPLETED, phase="completed", counts=result, remove_algorithm=True)
                return TaskStatus.SUCCEEDED, "cleanup/result.json"
        except Exception as error:
            # A failed/stale execution cannot change newer operation truth.
            context.assert_current_execution()
            logger.exception("External algorithm cleanup failed: operation %s", op["operation_id"])
            code = str(getattr(error, "code", type(error).__name__))
            message = str(getattr(error, "message", "清理步骤失败，已保留成果与恢复回执，可安全重试"))
            repo.update(op["operation_id"], state=FAILED, phase="failed", error=f"{code}: {message}", error_code=code)
            raise

    def recover(self, context):
        return self.run(context)
