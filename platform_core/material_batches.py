"""Durable material operations with selections frozen before queue publication."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import closing
from dataclasses import asdict, replace
from enum import Enum
from pathlib import Path

from filelock import FileLock

from .material_repository import MaterialRepository
from .material_repository_batch import _transform_many
from .material_selection import MaterialSelectionSpec, SelectionScope
from .materials import mark_ready
from .storage.errors import redact_storage_error
from .storage.import_tasks import _provider
from .storage.source_repository import StorageSource, StorageSourceRepository
from .task_runtime import TaskKind, TaskRecord, TaskStatus
from .task_runtime.models import utc_now
from .task_runtime.task_logs import append_task_log

BATCH_SIZE = 500
SELECTION_REF = "selection.sqlite3"
CHECKPOINT_REF = "checkpoints/worker.json"
RESULT_REF = "result.json"


class BatchOperation(str, Enum):
    MARK_CLEAN_SKIPPED = "MARK_CLEAN_SKIPPED"
    CLEAN = "CLEAN"
    DELETE_INDEX = "DELETE_INDEX"
    DELETE_SOURCE = "DELETE_SOURCE"
    ADD_LABELS = "ADD_LABELS"
    REMOVE_LABELS = "REMOVE_LABELS"
    AI_ANNOTATE = "AI_ANNOTATE"


NOT_READY = {BatchOperation.CLEAN, BatchOperation.AI_ANNOTATE}


class BatchRequestError(ValueError):
    def __init__(self, code, message, status_code=422):
        super().__init__(message)
        self.code, self.status_code = code, status_code


def parse_request(payload):
    if not isinstance(payload, dict):
        raise ValueError("material batch request must be an object")
    operation = BatchOperation(str(payload.get("operation") or "").upper())
    selection = MaterialSelectionSpec.from_mapping(payload.get("selection_spec"))
    if len(selection.image_ids) > BATCH_SIZE:
        raise ValueError("explicit selection is limited to 500 IDs; use FILTERED for larger selections")
    if len(selection.filters.labels) > BATCH_SIZE or len(selection.filters.storage_source_ids) > BATCH_SIZE:
        raise ValueError("filter arrays are limited to 500 values")
    options = payload.get("options", {})
    if not isinstance(options, dict):
        raise ValueError("options must be an object")
    options = dict(options)
    if operation in {BatchOperation.ADD_LABELS, BatchOperation.REMOVE_LABELS}:
        labels = options.get("labels")
        if not isinstance(labels, list) or not labels or len(labels) > BATCH_SIZE:
            raise ValueError("options.labels must contain between 1 and 500 labels")
        if any(not isinstance(label, str) or not label.strip() for label in labels):
            raise ValueError("labels must be nonempty strings")
        options["labels"] = list(dict.fromkeys(label.strip() for label in labels))
    return operation, selection, options


def _predicate(materials, selection):
    if selection.scope is SelectionScope.FILTERED:
        return materials._filters(selection.filters)
    return ["m.id IN (" + ",".join("?" for _ in selection.image_ids) + ")"], list(selection.image_ids)


def _confirmation_token(project_id, operation, selection, options):
    body = [project_id, operation.value, selection.as_dict(),
            {key: value for key, value in options.items() if key != "confirmation_token"}]
    digest = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return "DELETE_SOURCE:" + digest


def estimate_batch(project_id, materials, payload):
    operation, selection, options = parse_request(payload)
    clauses, params = _predicate(materials, selection)
    where = " WHERE " + " AND ".join(clauses) if clauses else ""
    with closing(materials._connect()) as database:
        database.execute("BEGIN")
        revision = materials._revision(database)
        count = int(database.execute("SELECT COUNT(*) FROM materials m" + where, params).fetchone()[0])
    confirmed_selection = replace(selection, repository_revision=revision)
    result = {"operation": operation.value, "count": count, "total": count,
              "repository_revision": revision, "revision": revision,
              "selection_spec": confirmed_selection.as_dict(), "supported": operation not in NOT_READY}
    if operation in NOT_READY:
        result["error_code"] = "BATCH_OPERATION_NOT_READY"
    if operation is BatchOperation.DELETE_SOURCE:
        result["confirmation_token"] = _confirmation_token(project_id, operation, confirmed_selection, options)
    return result


def create_batch(project_id, materials, repository, artifacts, payload):
    operation, selection, options = parse_request(payload)
    if operation in NOT_READY:
        raise BatchRequestError("BATCH_OPERATION_NOT_READY", f"{operation.value} has no bounded durable adapter yet")
    if selection.repository_revision is None:
        raise BatchRequestError("BATCH_ESTIMATE_REQUIRED", "estimate and provide selection_spec.repository_revision first", 409)
    if operation is BatchOperation.DELETE_SOURCE and options.get("confirmation_token") != _confirmation_token(
        project_id, operation, selection, options,
    ):
        raise BatchRequestError("DELETE_SOURCE_CONFIRMATION_REQUIRED", "confirm source deletion using the estimate confirmation_token", 409)
    task_id = uuid.uuid4().hex
    try:
        selection_path = artifacts.artifact_path(task_id, SELECTION_REF)
        # Prepare the schema before taking the material lock. No task exists yet.
        with closing(BatchSelection(selection_path)):
            pass
        clauses, params = _predicate(materials, selection)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with closing(materials._connect()) as database:
            database.execute("ATTACH DATABASE ? AS batch_selection", (str(selection_path),))
            database.execute("PRAGMA batch_selection.synchronous=FULL")
            database.execute("BEGIN IMMEDIATE")
            if materials._revision(database) != selection.repository_revision:
                raise BatchRequestError("MATERIAL_REVISION_CHANGED", "material repository changed; re-estimate before confirming", 409)
            # Revision and membership use this single consistent transaction.
            # Only the attached manifest is written, so correctness does not
            # depend on cross-database atomic commits (unsupported with WAL).
            inserted = database.execute(
                "INSERT INTO batch_selection.selection(image_id) SELECT m.id FROM main.materials m" + where,
                params,
            ).rowcount
            if selection.scope is not SelectionScope.FILTERED and inserted != len(selection.image_ids):
                raise BatchRequestError("MATERIAL_SELECTION_CHANGED", "selected materials are missing; re-estimate before confirming", 409)
            database.executemany(
                "INSERT INTO batch_selection.meta(key,value) VALUES (?,?)",
                (("frozen", utc_now()), ("repository_revision", str(selection.repository_revision))),
            )
            database.commit()
        # Every prerequisite is durable before publishing the executable row.
        # A failure here leaves only unqueued artifacts, never a partial task.
        artifacts.atomic_write_json(task_id, "request.json", {
            "operation": operation.value, "selection_spec": selection.as_dict(), "options": options,
        })
        with closing(BatchSelection(selection_path)) as manifest:
            artifacts.atomic_write_json(task_id, CHECKPOINT_REF, manifest.summary())
        return repository.create(TaskRecord.new(
            task_id, project_id, TaskKind.MATERIAL_BATCH, "request.json",
            f"materials:{project_id}", required_capabilities=("materials.batch",),
        ), artifacts=artifacts)
    except Exception as error:
        try:
            artifacts.atomic_write_json(task_id, "creation_failure.json", {
                "task_id": task_id, "status": "CREATION_FAILED", "error": redact_storage_error(error),
            })
        except Exception:
            pass  # An unavailable artifact volume must not hide the submit error.
        if isinstance(error, BatchRequestError):
            raise
        raise BatchRequestError("BATCH_CREATION_FAILED", f"material batch creation failed: {redact_storage_error(error)}", 500) from error


_SCHEMA = """
CREATE TABLE IF NOT EXISTS selection (
    image_id TEXT PRIMARY KEY,
    state TEXT NOT NULL DEFAULT 'pending' CHECK(state IN ('pending','running','succeeded','failed')),
    error TEXT, tombstone_json TEXT, source_deleted INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS ix_selection_state ON selection(state,image_id);
CREATE TABLE IF NOT EXISTS counters(state TEXT PRIMARY KEY, count INTEGER NOT NULL);
INSERT OR IGNORE INTO counters VALUES ('pending',0),('running',0),('succeeded',0),('failed',0);
CREATE TRIGGER IF NOT EXISTS selection_insert AFTER INSERT ON selection BEGIN
    UPDATE counters SET count=count+1 WHERE state=NEW.state;
END;
CREATE TRIGGER IF NOT EXISTS selection_update AFTER UPDATE OF state ON selection WHEN OLD.state <> NEW.state BEGIN
    UPDATE counters SET count=count-1 WHERE state=OLD.state;
    UPDATE counters SET count=count+1 WHERE state=NEW.state;
END;
CREATE TRIGGER IF NOT EXISTS selection_delete AFTER DELETE ON selection BEGIN
    UPDATE counters SET count=count-1 WHERE state=OLD.state;
END;
CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
"""


class BatchSelection:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.database = sqlite3.connect(self.path, timeout=5, isolation_level=None)
        self.database.row_factory = sqlite3.Row
        self.database.execute("PRAGMA journal_mode=WAL")
        self.database.execute("PRAGMA synchronous=FULL")
        self.database.executescript(_SCHEMA)

    def close(self):
        self.database.close()

    def frozen(self):
        return self.database.execute("SELECT 1 FROM meta WHERE key='frozen'").fetchone() is not None

    def rows(self, states=("pending", "running")):
        return self.database.execute(
            "SELECT * FROM selection WHERE state IN (" + ",".join("?" for _ in states) + ") ORDER BY image_id LIMIT ?",
            (*states, BATCH_SIZE),
        ).fetchall()

    def transition(self, ids, state, error=None):
        if len(ids) > BATCH_SIZE:
            raise ValueError("selection updates are limited to 500")
        with self.transaction():
            self.database.executemany(
                "UPDATE selection SET state=?, error=?, attempts=attempts+? WHERE image_id=?",
                ((state, error, int(state == "running"), image_id) for image_id in ids),
            )

    def transaction(self):
        from contextlib import contextmanager

        @contextmanager
        def commit():
            self.database.execute("BEGIN IMMEDIATE")
            try:
                yield
                self.database.commit()
            except BaseException:
                self.database.rollback()
                raise
        return commit()

    def summary(self, current=None):
        counts = dict(self.database.execute("SELECT state,count FROM counters"))
        errors = [{"image_id": row[0], "error": row[1], "retryable": True} for row in self.database.execute(
            "SELECT image_id,error FROM selection WHERE state='failed' ORDER BY image_id LIMIT 10",
        )]
        return {"total": sum(counts.values()), "processed": counts["succeeded"] + counts["failed"],
                "succeeded": counts["succeeded"], "failed": counts["failed"], "current_image_id": current,
                "current": current, "errors": errors, "error_examples": errors,
                "selection_frozen": self.frozen()}


def _check_active(context, stage="processing", current=None):
    current_task = context.repository.heartbeat(
        context.task.task_id, context.lease.lease_token, stage=stage, current_item=current,
    )
    if current_task.status is TaskStatus.CANCEL_REQUESTED:
        raise InterruptedError("material batch cancelled")


def _object_missing(error):
    """Recognize structured provider not-found errors, including wrapped SDK errors."""
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if isinstance(error, FileNotFoundError):
            return True
        if str(getattr(error, "code", "")) in {"STORAGE_OBJECT_NOT_FOUND", "NoSuchKey", "NotFound", "404"}:
            return True
        response = getattr(error, "response", None)
        if isinstance(response, dict):
            if str((response.get("Error") or {}).get("Code", "")) in {"NoSuchKey", "NotFound", "404"}:
                return True
        elif getattr(response, "status_code", None) == 404:
            return True
        if getattr(error, "status", None) == 404:
            return True
        error = error.__cause__
    return False


class MaterialBatchHandler:
    def __init__(self, data_dir):
        self.data_dir = Path(data_dir).resolve()

    def run(self, context):
        selection_path = context.artifacts.artifact_path(context.task.task_id, SELECTION_REF)
        selection_path.parent.mkdir(parents=True, exist_ok=True)
        # A recovering owner must not run alongside a still-exiting stale owner.
        with FileLock(str(selection_path) + ".lock", timeout=60):
            with closing(BatchSelection(selection_path)) as manifest:
                try:
                    return self._run(context, manifest)
                except BaseException as error:
                    append_task_log(context, "error", f"{type(error).__name__}: {error}")
                    # A stale worker must not overwrite a replacement's checkpoint.
                    if not isinstance(error, PermissionError):
                        context.save_checkpoint(manifest.summary())
                    raise

    def _run(self, context, manifest):
        payload = context.artifacts.read_json(context.task.task_id, context.task.payload_ref)
        operation, selection, options = parse_request(payload)
        if operation in NOT_READY:
            raise BatchRequestError("BATCH_OPERATION_NOT_READY", f"{operation.value} has no bounded durable adapter yet")
        project = context.artifacts._validate_task_id(context.task.project_id)
        materials = MaterialRepository(self.data_dir / "projects" / project)
        confirmed_revision = manifest.database.execute("SELECT value FROM meta WHERE key='repository_revision'").fetchone()
        if not manifest.frozen() or confirmed_revision is None or confirmed_revision[0] != str(selection.repository_revision):
            raise BatchRequestError("BATCH_SELECTION_NOT_FROZEN", "batch has no confirmed immutable selection; create and confirm a new batch", 409)
        if context.task.retry_of:
            # Failed rows are replayed only by explicit retry, never in a tight loop.
            while batch := manifest.rows(("failed",)):
                _check_active(context)
                manifest.transition([row["image_id"] for row in batch], "pending")
        append_task_log(context, "processing", f"operation={operation.value} total={manifest.summary()['total']}")
        sources = StorageSourceRepository(self.data_dir / "storage" / "storage_sources.sqlite3") if operation is BatchOperation.DELETE_SOURCE else None
        source_cache, providers = {}, {}
        while batch := manifest.rows():
            _check_active(context)
            ids = [row["image_id"] for row in batch]
            manifest.transition(ids, "running")
            current = ids[0]
            context.save_checkpoint(manifest.summary(current))
            if operation is BatchOperation.DELETE_SOURCE:
                self._delete_sources(context, manifest, materials, batch, sources, source_cache, providers)
            else:
                try:
                    existing = {row["id"] for row in materials.get_many(ids)}
                    found = [image_id for image_id in ids if image_id in existing]
                    missing = [image_id for image_id in ids if image_id not in existing]
                    if operation is BatchOperation.MARK_CLEAN_SKIPPED:
                        decided_at = context.task.created_at
                        _transform_many(materials, found, lambda row: mark_ready(row, decided_at), batch_size=BATCH_SIZE)
                    elif operation is BatchOperation.ADD_LABELS:
                        materials.add_labels_many(found, options["labels"], batch_size=BATCH_SIZE)
                    elif operation is BatchOperation.REMOVE_LABELS:
                        materials.remove_labels_many(found, options["labels"], batch_size=BATCH_SIZE)
                    elif operation is BatchOperation.DELETE_INDEX:
                        materials.remove_many(found, batch_size=BATCH_SIZE)
                    else:
                        raise BatchRequestError("BATCH_OPERATION_NOT_READY", operation.value)
                    manifest.transition(found, "succeeded")
                    # Index deletion is idempotent after a crash between deletion and checkpoint.
                    manifest.transition(missing, "succeeded" if operation is BatchOperation.DELETE_INDEX else "failed",
                                        None if operation is BatchOperation.DELETE_INDEX else "MATERIAL_NOT_FOUND")
                except (PermissionError, InterruptedError):
                    raise
                except Exception as error:
                    public_error = redact_storage_error(error)
                    manifest.transition(ids, "failed", public_error)
                    append_task_log(context, "batch_error", public_error)
            _check_active(context)
            checkpoint = manifest.summary()
            context.save_checkpoint(checkpoint)
            append_task_log(context, "checkpoint", f"processed={checkpoint['processed']} succeeded={checkpoint['succeeded']} failed={checkpoint['failed']}")
        summary = manifest.summary()
        context.save_checkpoint(summary)
        context.artifacts.atomic_write_json(context.task.task_id, RESULT_REF, summary)
        status = (TaskStatus.PARTIAL_SUCCESS if summary["succeeded"] else TaskStatus.FAILED) if summary["failed"] else TaskStatus.SUCCEEDED
        append_task_log(context, "finished", status.value)
        return status, RESULT_REF

    def _delete_sources(self, context, manifest, materials, batch, sources, source_cache, providers):
        ids = [row["image_id"] for row in batch]
        indexed = {row["id"]: row for row in materials.get_many(ids)}
        deletable = []
        for item in batch:
            image_id = item["image_id"]
            _check_active(context, "deleting_source", image_id)
            context.save_checkpoint(manifest.summary(image_id))
            try:
                tombstone = json.loads(item["tombstone_json"]) if item["tombstone_json"] else None
                if tombstone is None:
                    material = indexed.get(image_id)
                    if material is None:
                        raise ValueError("MATERIAL_NOT_FOUND: no durable source reference exists")
                    source_id = material["storage_source_id"]
                    if source_id not in source_cache:
                        source_cache[source_id] = sources.get(source_id)
                    source = source_cache[source_id]
                    # Retain the full material reference even when source config is missing.
                    tombstone = {"material": material, "source": asdict(source) if source else None, "created_at": utc_now()}
                    manifest.database.execute("UPDATE selection SET tombstone_json=? WHERE image_id=?",
                                              (json.dumps(tombstone, ensure_ascii=False), image_id))
                if not item["source_deleted"]:
                    source_data = tombstone.get("source")
                    if not source_data:
                        source_id = tombstone["material"]["storage_source_id"]
                        if source_id not in source_cache:
                            source_cache[source_id] = sources.get(source_id)
                        restored = source_cache[source_id]
                        if restored is None:
                            raise ValueError("STORAGE_SOURCE_NOT_FOUND: restore the source configuration before retrying")
                        source_data = asdict(restored)
                        tombstone["source"] = source_data
                        manifest.database.execute("UPDATE selection SET tombstone_json=? WHERE image_id=?",
                                                  (json.dumps(tombstone, ensure_ascii=False), image_id))
                    source = StorageSource(**source_data)
                    if source.id not in source_cache:
                        source_cache[source.id] = sources.get(source.id)
                    live_source = source_cache[source.id]
                    if live_source is None or not live_source.enabled:
                        raise ValueError("STORAGE_SOURCE_DISABLED: restore and enable the source before retrying")
                    # The captured location remains immutable, while enabling a
                    # source or rotating its credential reference permits retry.
                    source = replace(source, enabled=True, secret_ref=live_source.secret_ref)
                    cache_key = json.dumps(source_data, sort_keys=True)
                    if cache_key not in providers:
                        providers[cache_key] = _provider(self.data_dir, context.task.project_id, source)
                    material = tombstone["material"]
                    provider = providers[cache_key]
                    object_key = str(material["object_key"])
                    previously_attempted = bool(tombstone.get("delete_attempted_at"))
                    if not previously_attempted:
                        tombstone["delete_attempted_at"] = utc_now()
                        # Commit intent before the external side effect so a
                        # crash after deletion can recover without losing index cleanup.
                        manifest.database.execute("UPDATE selection SET tombstone_json=? WHERE image_id=?",
                                                  (json.dumps(tombstone, ensure_ascii=False), image_id))
                    try:
                        provider.delete(object_key)
                    except Exception as error:
                        if not previously_attempted or not _object_missing(error):
                            raise
                        if provider.exists(object_key) is not False:
                            raise
                        append_task_log(context, "source_already_deleted", f"image_id={image_id}")
                    manifest.database.execute("UPDATE selection SET source_deleted=1 WHERE image_id=?", (image_id,))
                deletable.append(image_id)
            except Exception as error:
                public_error = redact_storage_error(error)
                manifest.transition([image_id], "failed", public_error)
                append_task_log(context, "source_delete_error", f"image_id={image_id} {public_error}")
        # Never remove an index until that row's source deletion is durably recorded.
        if deletable:
            _check_active(context, "deleting_index")
            try:
                materials.remove_many(deletable, batch_size=BATCH_SIZE)
                manifest.transition(deletable, "succeeded")
            except Exception as error:
                manifest.transition(deletable, "failed", redact_storage_error(error))
                append_task_log(context, "index_delete_error", str(error))

    def recover(self, context):
        return self.run(context)


def public_batch(task, artifacts):
    checkpoint = artifacts.read_json(task.task_id, CHECKPOINT_REF, default={})
    request = artifacts.read_json(task.task_id, task.payload_ref, default={})
    frozen = bool(checkpoint.get("selection_frozen"))
    error_examples = checkpoint.get("error_examples", [])[:10]
    if task.error and not error_examples:
        error_examples = [{"error": redact_storage_error(task.error)}]
    available = artifacts.artifact_path(task.task_id, task.log_ref).is_file()
    return {"id": task.task_id, "task_id": task.task_id, "project_id": task.project_id,
            "kind": task.kind.value, "operation": request.get("operation"), "status": task.status.value,
            "stage": task.stage, "total": checkpoint.get("total") if frozen else None,
            "processed": checkpoint.get("processed", 0), "succeeded": checkpoint.get("succeeded", 0),
            "failed": checkpoint.get("failed", 0), "current_image_id": checkpoint.get("current_image_id"),
            "error_examples": error_examples, "selection_frozen": frozen,
            "log_available": available, "log_ref": task.log_ref if available else None,
            "created_at": task.created_at, "updated_at": task.updated_at, "finished_at": task.finished_at}


def material_batch_router(get_project, material_store, task_repository, task_artifacts):
    from fastapi import APIRouter, Body, HTTPException
    from fastapi.responses import FileResponse

    router = APIRouter(prefix="/api/v62/projects/{project_id}/material-batches")

    def invoke(function, *args):
        try:
            return function(*args)
        except BatchRequestError as error:
            raise HTTPException(error.status_code, detail={"code": error.code, "message": str(error)}) from error
        except (ValueError, TypeError) as error:
            raise HTTPException(422, detail={"code": "INVALID_BATCH_REQUEST", "message": str(error)}) from error

    def require_task(project_id, task_id):
        get_project(project_id)
        task = task_repository().get(task_id)
        if task is None or task.project_id != project_id or task.kind is not TaskKind.MATERIAL_BATCH:
            raise HTTPException(404, detail="material batch not found")
        return task

    @router.post("/estimate")
    def estimate(project_id: str, payload: dict = Body(...)):
        get_project(project_id)
        return invoke(estimate_batch, project_id, material_store(project_id), payload)

    @router.post("", status_code=202)
    def create(project_id: str, payload: dict = Body(...)):
        get_project(project_id)
        task = invoke(create_batch, project_id, material_store(project_id), task_repository(), task_artifacts(), payload)
        return public_batch(task, task_artifacts())

    @router.get("/{task_id}")
    def get(project_id: str, task_id: str):
        return public_batch(require_task(project_id, task_id), task_artifacts())

    @router.post("/{task_id}/cancel")
    def cancel(project_id: str, task_id: str):
        require_task(project_id, task_id)
        return public_batch(task_repository().request_cancel(task_id), task_artifacts())

    @router.post("/{task_id}/retry", status_code=202)
    def retry(project_id: str, task_id: str):
        task = require_task(project_id, task_id)
        if task.status not in {TaskStatus.FAILED, TaskStatus.PARTIAL_SUCCESS, TaskStatus.CANCELLED,
                               TaskStatus.BLOCKED_BY_ENVIRONMENT, TaskStatus.BLOCKED_BY_HARDWARE}:
            raise HTTPException(409, detail="only incomplete terminal batches can be retried")
        return public_batch(task_repository().retry(task_id), task_artifacts())

    @router.get("/{task_id}/log")
    def log(project_id: str, task_id: str):
        task = require_task(project_id, task_id)
        path = task_artifacts().artifact_path(task_id, task.log_ref)
        if not path.is_file():
            raise HTTPException(404, detail="task log unavailable")
        return FileResponse(path, media_type="text/plain", filename=f"{task_id}.log")

    return router


def worker_registration(data_dir):
    return {"handlers": {TaskKind.MATERIAL_BATCH: MaterialBatchHandler(data_dir)}, "capabilities": {"materials.batch"}}
