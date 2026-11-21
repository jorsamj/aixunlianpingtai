"""One authoritative execution task for a sealed bulk formal annotation intent.

The C1 manifest stays in the original AI review task's artifact namespace.  A
new ``ANNOTATION_FORMAL_BULK`` task owns only an immutable binding written in
its own namespace; the binding names the original task and manifest ref that
the Worker is allowed to read.  This module never writes formal Ground Truth
from an HTTP request: it only registers the task, projects verified persisted
progress, and runs the existing protected batch kernel from a Worker.

Success semantics (D5): ``SUCCEEDED`` proves **this operation** durably
committed the frozen range with per-image GT receipts plus the candidate
journal. A later lawful GT edit (manual review, external correction) is a
separate GT change; it does not retroactively erase the historical execution
fact. ``committed_images`` therefore describes this operation's proven writes,
not "current GT still equals the receipt". The audit -> publish window is
expected under this semantics and is documented rather than closed with a new
global lock; the existing GT CAS still protects every individual write.
"""
from __future__ import annotations

import sqlite3

from fastapi import HTTPException

from .annotation_bulk_intents import _digest, _intent_identity, load_sealed_intent, read_sealed_pointer
from .task_runtime import TaskKind, TaskRecord, TaskStatus
from .task_runtime.payload_publications import EVIDENCE_REF, PayloadPublicationError
from .task_runtime.sqlite_busy import is_sqlite_busy

BATCH_SIZE = 100
BINDING_SCHEMA = 1
BINDING_MAX_BYTES = 256 * 1024
_EXECUTION_TASK_PREFIX = "fbulk-"
_EXECUTION_TASK_ID_LENGTH = 40
_CAPABILITY = "annotation.formal_bulk"
_RESOURCE_KEY = "annotation-formal-bulk"


def execution_task_id(operation_id: str) -> str:
    """Derive one stable task id from the sealed C1 operation."""
    if not isinstance(operation_id, str) or len(operation_id) != 64:
        raise ValueError("invalid bulk formal operation id")
    digest = _digest(["annotation-formal-bulk-task:v1", operation_id])
    return _EXECUTION_TASK_PREFIX + digest[:_EXECUTION_TASK_ID_LENGTH]


def batch_count(total_images: int) -> int:
    return (int(total_images) + BATCH_SIZE - 1) // BATCH_SIZE


def build_binding(project_id, actor, task_id, request_id, manifest, manifest_ref):
    operation = manifest["operation"]
    total = int(operation["count"])
    return {
        "schema": BINDING_SCHEMA,
        "kind": TaskKind.ANNOTATION_FORMAL_BULK.value,
        "execution_task_id": execution_task_id(operation["operation_id"]),
        "project_id": project_id,
        "actor": actor,
        "original_task_id": task_id,
        "request_id": request_id,
        "operation_id": operation["operation_id"],
        "manifest_ref": manifest_ref,
        "manifest_digest": EVIDENCE_REF.fullmatch(manifest_ref)["digest"],
        "total_images": total,
        "batch_size": BATCH_SIZE,
        "batch_count": batch_count(total),
    }


def validate_binding(document, *, task_id: str, project_id: str, manifest_ref: str | None = None):
    """Verify one binding document belongs to this exact execution task."""
    if not isinstance(document, dict) or document.get("schema") != BINDING_SCHEMA:
        raise ValueError("formal bulk execution binding is invalid")
    if (document.get("kind") != TaskKind.ANNOTATION_FORMAL_BULK.value
            or document.get("execution_task_id") != task_id
            or document.get("project_id") != project_id
            or not all(isinstance(document.get(key), str) and document[key]
                       for key in ("actor", "original_task_id", "request_id"))
            or not isinstance(document.get("operation_id"), str) or len(document["operation_id"]) != 64
            or not isinstance(document.get("manifest_ref"), str)
            or not EVIDENCE_REF.fullmatch(document["manifest_ref"])
            or document.get("manifest_digest") != EVIDENCE_REF.fullmatch(document["manifest_ref"])["digest"]
            or document.get("batch_size") != BATCH_SIZE
            or type(document.get("total_images")) is not int
            or not 1 <= document["total_images"] <= 50_000
            or document.get("batch_count") != batch_count(document["total_images"])):
        raise ValueError("formal bulk execution binding identity mismatch")
    if manifest_ref is not None and document["manifest_ref"] != manifest_ref:
        raise ValueError("formal bulk execution binding manifest mismatch")
    return document


def _assert_record(record, binding, binding_ref):
    if (record is None or record.kind is not TaskKind.ANNOTATION_FORMAL_BULK
            or record.project_id != binding["project_id"]
            or record.payload_ref != binding_ref):
        raise HTTPException(409, detail="批量入库执行任务身份不一致，请核验原操作")


def start_execution(artifacts, repository, actor, project_id, task_id, request_id):
    """Register (or return) the only execution task for this sealed intent."""
    try:
        identity = _intent_identity(actor, project_id, task_id, request_id)
        pointer = read_sealed_pointer(artifacts, identity)
        manifest, manifest_ref = load_sealed_intent(artifacts, identity)
        if (manifest_ref != pointer["manifest_ref"]
                or manifest["operation"]["operation_id"] != pointer["operation_id"]):
            raise HTTPException(503, detail="批量入库意图的持久证据无法核验")
        binding = build_binding(project_id, actor, task_id, request_id, manifest, manifest_ref)
        task_id_out = binding["execution_task_id"]
        binding_ref = artifacts.write_evidence_json(task_id_out, binding)
        record = repository.get(task_id_out)
        if record is None:
            try:
                repository.create(TaskRecord.new(
                    task_id_out, project_id, TaskKind.ANNOTATION_FORMAL_BULK, binding_ref,
                    _RESOURCE_KEY, required_capabilities=(_CAPABILITY,),
                ), artifacts=artifacts)
            except sqlite3.IntegrityError:
                # A concurrent request published the same deterministic task.
                pass
            except sqlite3.OperationalError as error:
                if not is_sqlite_busy(error):
                    raise
            record = repository.get(task_id_out)
        _assert_record(record, binding, binding_ref)
        return record
    except sqlite3.OperationalError as error:
        raise HTTPException(503, detail="批量入库执行任务暂时繁忙，请稍后核对") from error
    except PayloadPublicationError as error:
        raise HTTPException(503, detail="批量入库执行任务未能完成持久化，请核验原操作") from error
    except ValueError as error:
        raise HTTPException(409, detail=str(error)) from error
    except OSError as error:
        raise HTTPException(503, detail="批量入库执行任务未能完成持久化，请核验原操作") from error


def _read_binding_document(artifacts, task_id, payload_ref):
    if not isinstance(payload_ref, str) or not EVIDENCE_REF.fullmatch(payload_ref):
        raise ValueError("formal bulk execution payload is not an immutable binding")
    return artifacts.payload_reader.read_evidence_json(task_id, payload_ref, max_bytes=BINDING_MAX_BYTES)


def load_binding(artifacts, task_id, project_id, payload_ref):
    return validate_binding(
        _read_binding_document(artifacts, task_id, payload_ref),
        task_id=task_id, project_id=project_id,
    )


def binding_identity(binding):
    return _intent_identity(
        binding["actor"], binding["project_id"], binding["original_task_id"], binding["request_id"],
    )


def assert_binding_matches_manifest(binding, manifest, manifest_ref):
    operation = manifest["operation"]
    identity = binding_identity(binding)
    if (manifest_ref != binding["manifest_ref"]
            or operation["operation_id"] != binding["operation_id"]
            or operation["identity"] != identity
            or operation["count"] != binding["total_images"]
            or operation["status"] != "accepted"):
        raise ValueError("formal bulk execution binding does not match the sealed intent")


def _completed(ledger, total_batches):
    value = ledger.get("completed_batches")
    if type(value) is not int or not 0 <= value <= total_batches:
        return 0
    return value


def _evidence(binding, binding_ref, *, state, committed, completed, total_batches, current_batch,
              candidate_only=(), error_code=None, error_message=None, blocked_code=None,
              blocked_reason=None, blocked_at=None):
    candidate_only = list(candidate_only)
    return {
        "state": state,
        "binding_ref": binding_ref,
        "operation_id": binding["operation_id"],
        "manifest_ref": binding["manifest_ref"],
        "manifest_digest": binding["manifest_digest"],
        "total_images": binding["total_images"],
        "batch_size": BATCH_SIZE,
        "batch_count": total_batches,
        "completed_batches": completed,
        "committed_images": committed,
        "committed_images_proven": True,
        "candidate_adopted_images": sum(int(item["image_count"]) for item in candidate_only),
        "current_batch": current_batch,
        "candidate_only_batches": candidate_only,
        "candidate_only_uncommitted_images": sum(int(item["image_count"]) for item in candidate_only),
        "candidate_only_gt_changed_images": sum(int(item.get("gt_changed_images") or 0)
                                                for item in candidate_only),
        "last_error_code": error_code,
        "last_error_message": error_message,
        "blocked_code": blocked_code,
        "blocked_reason": blocked_reason,
        "blocked_at": blocked_at,
    }


def progress_view(task, binding, ledger, *, cancellation_requested=False):
    """Project verified persisted progress; never infer a GT count.

    ``committed_images`` is ``None`` whenever the ledger has no proven integer.
    Batch counts and candidate-adopted counts are reported separately so a
    caller can never mistake adopted candidates for durable formal GT.
    """
    total = int(binding["total_images"])
    total_batches = int(binding["batch_count"])
    completed = _completed(ledger, total_batches)
    candidate_only = ledger.get("candidate_only_batches")
    if not isinstance(candidate_only, list):
        candidate_only = []
    candidate_only = [item for item in candidate_only if isinstance(item, dict)]
    committed = ledger.get("committed_images")
    proven = type(committed) is int and 0 <= committed <= total
    if (not proven and not ledger and task.status is TaskStatus.QUEUED
            and int(getattr(task, "attempt", 0) or 0) == 0):
        # Never claimed and no journal yet: zero committed GT is structurally
        # provable (no worker ever ran this execution).
        committed, proven = 0, True
    current = ledger.get("current_batch")
    if type(current) is not int:
        current = completed - 1 if completed else None
    return {
        "operation_id": binding["operation_id"],
        "execution_task_id": task.task_id,
        "status": task.status.value,
        "stage": task.stage,
        "total_images": total,
        "committed_images": committed if proven else None,
        "committed_images_proven": proven,
        "pending_images": max(0, total - committed) if proven else None,
        "completed_batches": completed,
        "total_batches": total_batches,
        "current_batch": current,
        "candidate_adopted_images": sum(int(item.get("image_count") or 0) for item in candidate_only),
        "candidate_only_uncommitted_images": sum(int(item.get("image_count") or 0)
                                                 for item in candidate_only),
        "candidate_only_gt_changed_images": sum(int(item.get("gt_changed_images") or 0)
                                                for item in candidate_only),
        "uncommitted_gt_changed_images": ledger.get("uncommitted_gt_changed_images"),
        "cancellation_requested": bool(cancellation_requested),
        "blocked": ledger.get("state") == "blocked",
        "blocked_code": ledger.get("blocked_code"),
        "blocked_reason": ledger.get("blocked_reason"),
        "last_error_code": ledger.get("last_error_code"),
        "last_error_message": ledger.get("last_error_message"),
        "finished_at": task.finished_at,
    }


def _publish(context, binding, binding_ref, *, state, committed, completed, total_batches,
             current_batch, candidate_only=(), status=None, error_code=None, error_message=None,
             blocked_code=None, blocked_reason=None, blocked_at=None):
    repository = context.repository
    _, anchor = repository.formal_bulk_cancel_state(context.lease, context.execution_generation)
    evidence = _evidence(
        binding, binding_ref, state=state, committed=committed, completed=completed,
        total_batches=total_batches, current_batch=current_batch, candidate_only=candidate_only,
        error_code=error_code, error_message=error_message,
        blocked_code=blocked_code, blocked_reason=blocked_reason, blocked_at=blocked_at,
    )
    repository.publish_formal_bulk_progress(
        context.lease, context.execution_generation, anchor, evidence, status=status,
    )
    return evidence


def _reconcile(context):
    from .annotation_bulk_commit import reconcile_worker_bulk_formal_cancel
    from .task_runtime.worker import ExecutionFencedError

    if reconcile_worker_bulk_formal_cancel(context, context.artifacts):
        return TaskStatus.CANCELLED, None
    raise ExecutionFencedError("formal bulk cancellation was not reconciled")


def _block(context, binding, binding_ref, audit, *, stage="formal_bulk_blocked",
           code="FORMAL_BULK_EVIDENCE_UNPROVEN"):
    """Persist a durable block and keep the task recoverable but not claimable.

    Returning ``RUNNING`` alone would let the lease expire and the task be
    requeued forever. The block marker in ``formal_bulk_execution.reconciliation``
    makes the reaper skip automatic requeue; only an explicit, re-verified
    operator resume may release it.
    """
    from .task_runtime.models import utc_now

    reason = str(audit.get("detail") or "持久证据尚不能证明执行结果")
    context.heartbeat(stage=stage, current_item=reason[:200])
    batch = audit.get("batch")
    _publish(
        context, binding, binding_ref, state="blocked",
        committed=int(audit.get("committed") or 0), completed=int(audit.get("completed") or 0),
        total_batches=binding["batch_count"],
        current_batch=(batch - 1) if isinstance(batch, int) and batch > 0 else None,
        candidate_only=audit.get("candidate_only") or (),
        error_code=code, error_message=reason[:500],
        blocked_code=code, blocked_reason=reason[:500], blocked_at=utc_now(),
    )
    return TaskStatus.RUNNING, None


def _settle(context, binding, binding_ref, audit):
    """Publish a terminal state only when durable evidence proves it."""
    cancelled, _ = context.repository.formal_bulk_cancel_state(
        context.lease, context.execution_generation,
    )
    if cancelled:
        return _reconcile(context)
    if audit["state"] == "journal_pending":
        # GT is durable but the candidate journal lags. This is recoverable by
        # the next attempt (repair from receipts), so never block it.
        batch = audit.get("batch")
        context.heartbeat(stage="formal_bulk_journal_pending",
                          current_item="正式 GT 已提交，候选日志待补齐")
        _publish(
            context, binding, binding_ref, state="journal_pending",
            committed=int(audit.get("committed") or 0), completed=int(audit.get("completed") or 0),
            total_batches=binding["batch_count"],
            current_batch=(batch - 1) if isinstance(batch, int) and batch > 0 else None,
        )
        return TaskStatus.RUNNING, None
    if audit["state"] == "complete":
        if audit["committed"] != binding["total_images"]:
            return _block(context, binding, binding_ref,
                          {**audit, "detail": "完成图片数与冻结总数不一致"})
        try:
            _publish(
                context, binding, binding_ref, state=TaskStatus.SUCCEEDED.value.lower(),
                committed=audit["committed"], completed=audit["completed"],
                total_batches=binding["batch_count"], current_batch=binding["batch_count"] - 1,
                status=TaskStatus.SUCCEEDED,
            )
        except InterruptedError:
            return _reconcile(context)
        return TaskStatus.SUCCEEDED, None
    if audit["state"] == "pending":
        committed = int(audit.get("committed") or 0)
        status = TaskStatus.PARTIAL_SUCCESS if committed else TaskStatus.FAILED
        batch = int(audit.get("batch") or 0)
        try:
            _publish(
                context, binding, binding_ref, state=status.value.lower(),
                committed=committed, completed=audit["completed"],
                total_batches=binding["batch_count"],
                current_batch=(batch - 1) if batch > 0 else None,
                candidate_only=audit.get("candidate_only") or (),
                status=status, error_code="FORMAL_BULK_CONFLICT",
                error_message=str(audit.get("detail") or "正式入库批次未能继续")[:500],
            )
        except InterruptedError:
            return _reconcile(context)
        return status, None
    return _block(context, binding, binding_ref, audit)


def _block_unbound(context, error):
    """Durably block an execution whose immutable binding cannot be proven."""
    from .task_runtime.models import utc_now

    reason = str(error)[:500]
    context.heartbeat(stage="formal_bulk_blocked", current_item=reason[:200])
    repository = context.repository
    _, anchor = repository.formal_bulk_cancel_state(context.lease, context.execution_generation)
    repository.publish_formal_bulk_progress(
        context.lease, context.execution_generation, anchor,
        {"state": "blocked", "committed_images_proven": False,
         "blocked_code": "FORMAL_BULK_BINDING_UNPROVEN",
         "blocked_reason": reason, "blocked_at": utc_now(),
         "last_error_code": "FORMAL_BULK_BINDING_UNPROVEN", "last_error_message": reason},
    )
    return TaskStatus.RUNNING, None


BLOCKED_STAGES = frozenset({"formal_bulk_blocked", "formal_bulk_attempt_limit"})


def resume_blocked_execution(artifacts, repository, actor, project_id, task_id, request_id):
    """Release a durable block only after re-proving the persisted facts.

    Never publishes a terminal state and never writes GT: it only requeues the
    execution so the normal Worker re-audits the same operation identity.
    """
    identity = _intent_identity(actor, project_id, task_id, request_id)
    pointer = read_sealed_pointer(artifacts, identity)
    execution_id = execution_task_id(pointer["operation_id"])
    record = repository.get(execution_id)
    if (record is None or record.kind is not TaskKind.ANNOTATION_FORMAL_BULK
            or record.project_id != project_id):
        raise HTTPException(404, detail="后台正式入库任务不存在")
    binding = load_binding(artifacts, execution_id, project_id, record.payload_ref)
    if (binding["original_task_id"] != task_id or binding["request_id"] != request_id
            or binding["actor"] != actor or binding["operation_id"] != pointer["operation_id"]
            or binding["manifest_ref"] != pointer["manifest_ref"]):
        raise HTTPException(404, detail="后台正式入库任务身份不一致")
    if record.status is not TaskStatus.RUNNING or str(record.stage) not in BLOCKED_STAGES:
        raise HTTPException(409, detail={"code": "FORMAL_BULK_NOT_BLOCKED",
                                         "message": "任务当前不处于阻断状态"})
    manifest, manifest_ref = load_sealed_intent(artifacts, identity)
    assert_binding_matches_manifest(binding, manifest, manifest_ref)

    from app import _v50_annotation_repository

    from .annotation_bulk_commit import audit_formal_bulk_execution
    from .annotation_candidates import CandidateStore

    store = CandidateStore(artifacts, task_id=identity["task_id"])
    annotations = _v50_annotation_repository(project_id)
    try:
        audit = audit_formal_bulk_execution(store, annotations, manifest, manifest_ref)
    except ValueError as error:
        raise HTTPException(409, detail={"code": "FORMAL_BULK_NOT_RECOVERABLE",
                                         "message": "持久证据互相矛盾，不能恢复",
                                         "detail": str(error)[:300]}) from error
    if audit["state"] not in {"complete", "journal_pending"}:
        raise HTTPException(409, detail={"code": "FORMAL_BULK_NOT_RECOVERABLE",
                                         "message": "持久证据仍不能证明可安全恢复",
                                         "detail": str(audit.get("detail") or "")[:300]})
    try:
        repository.resume_blocked_formal_bulk(execution_id, record.attempt)
    except PermissionError as error:
        raise HTTPException(409, detail={"code": "FORMAL_BULK_NOT_BLOCKED",
                                         "message": "任务阻断状态已变化，请刷新后再试"}) from error
    return audit["state"]


def run_formal_bulk(context, data_dir=None):
    """CPU Worker entry: prove the durable position, then consume sealed batches."""
    from app import _v50_annotation_repository

    from .annotation_bulk_commit import audit_formal_bulk_execution, execute_worker_bulk_formal_batch
    from .annotation_candidates import CandidateStore
    from .annotation_repository import AnnotationConflictError
    from .task_runtime.worker import ExecutionFencedError

    artifacts = context.artifacts
    task = context.task
    repository = context.repository
    binding_ref = task.payload_ref
    binding = store = annotations = manifest = manifest_ref = None
    audit = None
    try:
        context.assert_current_execution()
        binding = load_binding(artifacts, task.task_id, task.project_id, binding_ref)
        identity = binding_identity(binding)
        manifest, manifest_ref = load_sealed_intent(artifacts, identity)
        assert_binding_matches_manifest(binding, manifest, manifest_ref)
        store = CandidateStore(artifacts, task_id=identity["task_id"])
        annotations = _v50_annotation_repository(binding["project_id"])
        total_batches = binding["batch_count"]
        audit = audit_formal_bulk_execution(store, annotations, manifest, manifest_ref)
        if audit["state"] == "complete":
            return _settle(context, binding, binding_ref, audit)
        if audit["state"] == "unproven":
            return _block(context, binding, binding_ref, audit)

        committed = int(audit["committed"])
        for number in range(audit["batch"], total_batches):
            cancelled, _ = repository.formal_bulk_cancel_state(
                context.lease, context.execution_generation,
            )
            if cancelled:
                return _reconcile(context)
            context.heartbeat(
                progress=min(99.0, 100.0 * number / max(1, total_batches)),
                stage="FORMAL_BULK_COMMIT",
                current_item=f"正在提交正式 GT 第 {number + 1}/{total_batches} 批",
            )
            execute_worker_bulk_formal_batch(
                context, artifacts, identity, binding["operation_id"], manifest_ref, number,
                binding_ref=binding_ref, sealed=(manifest, manifest_ref),
            )
            committed += min(BATCH_SIZE, binding["total_images"] - number * BATCH_SIZE)
            _publish(
                context, binding, binding_ref, state="running", committed=committed,
                completed=number + 1, total_batches=total_batches, current_batch=number,
            )
        audit = audit_formal_bulk_execution(store, annotations, manifest, manifest_ref)
        return _settle(context, binding, binding_ref, audit)
    except ExecutionFencedError:
        raise
    except (ValueError, AnnotationConflictError) as error:
        if binding is None or audit is None or store is None or annotations is None:
            return _block_unbound(context, error)
        try:
            audit = audit_formal_bulk_execution(store, annotations, manifest, manifest_ref)
        except ValueError as again:
            return _block(context, binding, binding_ref,
                          {"detail": f"{type(error).__name__}: {error}; re-audit: {again}"})
        return _settle(context, binding, binding_ref, audit)


class FormalBulkAnnotationHandler:
    """Dedicated CPU handler; no provider inference and no GPU capability."""

    def __init__(self, data_dir=None):
        self.data_dir = data_dir

    def run(self, context):
        return run_formal_bulk(context, self.data_dir)

    def recover(self, context):
        return run_formal_bulk(context, self.data_dir)


def worker_registration(data_dir):
    return {
        "handlers": {
            TaskKind.ANNOTATION_FORMAL_BULK: FormalBulkAnnotationHandler(data_dir),
        },
        "capabilities": {_CAPABILITY},
    }
