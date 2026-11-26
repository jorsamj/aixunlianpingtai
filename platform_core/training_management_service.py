"""Domain orchestration over the existing persistence, worker and receipt owners."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Mapping, Tuple
from fastapi import Request, HTTPException
from .training_management_contracts import V48TrainingBatchDeleteReq

import json
import asyncio
import shutil
import time
from datetime import datetime
from pathlib import Path
import requests
from fastapi.responses import StreamingResponse
from platform_core.training_job_projection import build_training_display_progress
from platform_core.task_runtime import ProcessController, TaskKind, TaskRecord, TaskRepository, TaskStatus, task_to_public

@dataclass(frozen=True)
class TrainingManagementDependencies:
    PROCESS_REGISTRY: Callable[..., Any]
    V56_PRIORITY_SCHEME: Callable[..., Any]
    _TRAINING_DURABLE_TERMINAL_STATUSES: Callable[..., Any]
    _TRAINING_LEGACY_TERMINAL_STATUSES: Callable[..., Any]
    _TRAINING_STREAM_ACTIVE_STATUSES: Callable[..., Any]
    _cancel_training_prepare_child: Callable[..., Any]
    _durable_process_identity: Callable[..., Any]
    _durable_training_task: Callable[..., Any]
    _parse_dt_value: Callable[..., Any]
    _pid_alive: Callable[..., Any]
    _terminate_pid_tree: Callable[..., Any]
    _v48_all_job_files: Callable[..., Any]
    _v48_archive_training_version: Callable[..., Any]
    _v48_dispatch_training_queues: Callable[..., Any]
    _v48_resource_key: Callable[..., Any]
    _v48_suspend_tree: Callable[..., Any]
    _v53_fast_jobs_summary: Callable[..., Any]
    _v53_job_summary: Callable[..., Any]
    _v56_normalize_priority: Callable[..., Any]
    _write_job_json: Callable[..., Any]
    enrich_job_runtime: Callable[..., Any]
    get_project: Callable[..., Any]
    now_iso: Callable[..., Any]
    project_dir: Callable[..., Any]
    read_json: Callable[..., Any]
    shared_task_artifacts: Callable[..., Any]
    shared_task_repository: Callable[..., Any]
    sync_jobs_index: Callable[..., Any]
    sync_remote_job: Callable[..., Any]


class TrainingManagementService:
    def __init__(self, dependencies: TrainingManagementDependencies):
        self.dependencies = dependencies

    def list_jobs(self, project_id: str, summary_only: bool = False):
        self.dependencies.get_project(project_id)
        if summary_only:
            # A card overview never needs to re-project every archived training
            # task. This path reads the last durable index and overlays recent +
            # live canonical task truth; the original full endpoint is unchanged.
            return self.dependencies._v53_fast_jobs_summary(project_id)
        # GET is a live projection, never a scheduling or legacy archival trigger.
        # Old queues are maintained independently by the startup maintenance owner.
        rows = self.dependencies.sync_jobs_index(project_id, read_only=True)
        if not isinstance(rows, list):
            rows = self.dependencies.read_json(self.dependencies.project_dir(project_id) / "jobs" / "index.json", [])
        # Algorithm list and similar overview consumers only need display metadata.
        # Preserve the complete default response for reports and legacy callers.
        return [self.dependencies._v53_job_summary(row) for row in rows] if summary_only else rows

    def _training_event_row(self, project_id: str, task: TaskRecord) -> Dict[str, Any]:
        """Build the same canonical training display truth used by HTTP reads."""
        runtime = task_to_public(task)
        job_file = self.dependencies.project_dir(project_id) / "jobs" / task.task_id / "job.json"
        worker_job = self.dependencies.read_json(job_file, {}) if job_file.exists() else {}
        display = build_training_display_progress(worker_job, runtime)
        row = dict(runtime)
        row.update(
            progress_percent=display["overall_progress"],
            current_item=display["message"] or runtime.get("current_item"),
            current_epoch=display["current_epoch"],
            total_epochs=display["total_epochs"],
            current_batch=display["current_batch"],
            total_batches=display["total_batches"],
            elapsed_seconds=display["elapsed_seconds"],
            eta_seconds=display["eta_seconds"],
            phase_progress=display["phase_progress"],
            telemetry_source=display["telemetry_source"],
            display_revision=display["revision"],
            training_display_progress=display,
        )
        if isinstance(worker_job.get("training_progress"), dict):
            row["training_progress"] = worker_job["training_progress"]
        return row

    def _training_event_rows(self,
        project_id: str,
        repository: Optional[TaskRepository] = None,
    ) -> List[Dict[str, Any]]:
        """Return canonical display truth for active Durable training tasks."""
        repo = repository or self.dependencies.shared_task_repository()
        page = repo.list(
            project_id=project_id,
            kinds=(TaskKind.TRAINING,),
            statuses=self.dependencies._TRAINING_STREAM_ACTIVE_STATUSES(),
            limit=100,
        )
        return [self._training_event_row(project_id, task) for task in page.items]

    def _training_event_signature(self, row: Mapping[str, Any]) -> Tuple[Any, ...]:
        return (
            row.get("status"),
            row.get("persisted_status"),
            row.get("phase"),
            row.get("progress_percent"),
            row.get("current_item"),
            row.get("worker_id"),
            row.get("resource_wait_reason"),
            row.get("updated_at"),
            row.get("finished_at"),
            row.get("error"),
            row.get("current_epoch"),
            row.get("total_epochs"),
            row.get("current_batch"),
            row.get("total_batches"),
            row.get("elapsed_seconds"),
            row.get("eta_seconds"),
            row.get("telemetry_source"),
        )

    async def v64_training_events(self, project_id: str, request: Request):
        self.dependencies.get_project(project_id)
        repository = self.dependencies.shared_task_repository()

        async def event_stream():
            signatures: Dict[str, Tuple[Any, ...]] = {}
            watched: set[str] = set()
            last_keepalive = time.monotonic()
            yield "retry: 2000\n\n"

            while True:
                if await request.is_disconnected():
                    return

                rows = self._training_event_rows(project_id, repository)
                active_ids = {str(row.get("task_id") or "") for row in rows}
                announced_ids = getattr(event_stream, "_announced_ids", None)
                if announced_ids != active_ids:
                    ready = json.dumps(
                        {"task_ids": sorted(active_ids), "interval_ms": 750},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    yield f"event: training.ready\ndata: {ready}\n\n"
                    event_stream._announced_ids = set(active_ids)
                for row in rows:
                    task_id = str(row.get("task_id") or "")
                    if not task_id:
                        continue
                    watched.add(task_id)
                    signature = self._training_event_signature(row)
                    if signatures.get(task_id) == signature:
                        continue
                    signatures[task_id] = signature
                    yield self._training_sse_message(row)

                # A task disappears from the active query exactly when it becomes
                # terminal. Read that task once so the browser receives its final
                # durable state before this stream stops watching it.
                for task_id in tuple(watched - active_ids):
                    task = repository.get(task_id)
                    if (
                        task is not None
                        and task.project_id == project_id
                        and task.kind is TaskKind.TRAINING
                    ):
                        row = self._training_event_row(project_id, task)
                        signature = self._training_event_signature(row)
                        if signatures.get(task_id) != signature:
                            signatures[task_id] = signature
                            yield self._training_sse_message(row)
                    watched.discard(task_id)

                now = time.monotonic()
                if now - last_keepalive >= 15:
                    yield ": keepalive\n\n"
                    last_keepalive = now
                await asyncio.sleep(0.75)

        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    def job_status(self, project_id: str, job_id: str, include_history: bool = False):
        if self.dependencies.shared_task_repository().is_deleted(job_id,project_id=project_id):
            raise HTTPException(status_code=404,detail="训练任务已删除，证据仅供审计")
        self.dependencies.get_project(project_id)
        job_file = self.dependencies.project_dir(project_id) / "jobs" / job_id / "job.json"
        if not job_file.exists():
            raise HTTPException(status_code=404, detail="训练任务不存在")
        job = self.dependencies.read_json(job_file, {})
        if job.get("target") == "remote" and job.get("status") in {"queued", "running"}:
            job = self.dependencies.sync_remote_job(project_id, job_id)
        job = self.dependencies.enrich_job_runtime(project_id, job, allow_version_archive=False)
        # Detail refresh is a single-task read projection. Do not dispatch queues or
        # rebuild the global jobs index from a 1.5s detail/log poll.
        # Return the enriched in-memory projection. Re-reading the worker-owned
        # job.json here would discard canonical task truth we just overlaid.
        response = dict(job)
        from platform_core.training_metrics import read_metrics
        task = self.dependencies._durable_training_task(project_id, job_id)
        metrics_path = (self.dependencies.shared_task_artifacts().artifact_path(job_id, "training-metrics.sqlite3")
                        if task else job_file.parent / "training-metrics.sqlite3")
        response["runtime_metrics"] = read_metrics(metrics_path, include_history=include_history)
        if task:
            artifacts = self.dependencies.shared_task_artifacts()
            response["resolved_resources"] = artifacts.read_json(
                job_id,
                "resolved-resources.json",
                default=response.get("resolved_resources") or {},
            )
            response["runtime_resources"] = artifacts.read_json(
                job_id,
                "runtime-resources.json",
                default=response.get("runtime_resources") or {},
            )
        return response

    def _tail_training_log_text(self, path: Path, max_chars: int = 120000) -> str:
        """Read only a bounded suffix of a potentially very large UTF-8 task log."""
        try:
            size = int(path.stat().st_size)
            if size <= 0:
                return ""
            # UTF-8 uses at most four bytes per code point. Reading this many bytes
            # is enough to recover max_chars from the suffix without scanning the
            # entire log. Starting inside a multibyte sequence can lose at most one
            # partial code point because decoding is intentionally best-effort.
            max_bytes = max(4096, int(max_chars) * 4 + 4)
            start = max(0, size - max_bytes)
            with path.open("rb") as stream:
                stream.seek(start)
                value = stream.read(max_bytes)
            return value.decode("utf-8", errors="ignore")[-int(max_chars):].strip()
        except (OSError, ValueError):
            return ""

    def job_log(self, project_id: str, job_id: str):
        if self.dependencies.shared_task_repository().is_deleted(job_id,project_id=project_id):
            raise HTTPException(status_code=404,detail="训练任务已删除，证据仅供审计")
        self.dependencies.get_project(project_id)
        job = self.dependencies.read_json(self.dependencies.project_dir(project_id) / "jobs" / job_id / "job.json", {})
        if job.get("target") == "remote" and job.get("status") in {"queued", "running"}:
            job = self.dependencies.sync_remote_job(project_id, job_id)

        sections: List[str] = []
        log_file = self.dependencies.project_dir(project_id) / "jobs" / job_id / "train.log"
        text = self._tail_training_log_text(log_file)
        if text:
            sections.append(text)

        # Durable task logs contain scheduler/worker/remote-execution lifecycle
        # evidence that train.log alone cannot provide. Merge them into the same
        # read-only endpoint so the frontend has one canonical log source.
        task = self.dependencies._durable_training_task(project_id, job_id)
        if task is not None and str(task.log_ref or "").strip():
            try:
                durable_log = self.dependencies.shared_task_artifacts().artifact_path(job_id, task.log_ref)
                text = self._tail_training_log_text(durable_log)
                if text and (not sections or text != sections[-1]):
                    sections.append("[任务运行日志]\n" + text)
            except (OSError, ValueError):
                pass

        if not sections:
            return "暂无日志"
        return "\n\n".join(sections)[-120000:]

    def stop_job(self, project_id: str, job_id: str):
        if self.dependencies.shared_task_repository().is_deleted(job_id,project_id=project_id):
            raise HTTPException(status_code=404,detail="训练任务已删除，证据仅供审计")
        self.dependencies.get_project(project_id)
        job_file = self.dependencies.project_dir(project_id) / "jobs" / job_id / "job.json"
        job = self.dependencies.read_json(job_file, {})
        if job.get("target") == "remote" and job.get("remote"):
            try:
                remote = job["remote"]
                headers = {"X-API-Key": remote.get("api_key", "")}
                requests.post(f"{remote['base_url'].rstrip('/')}/api/remote/jobs/{remote['job_id']}/stop", headers=headers, timeout=8)
            except Exception:
                pass
            job.update({"status": "stopped", "message": "用户手动停止远程训练", "updated_at": self.dependencies.now_iso()})
            self.dependencies._write_job_json(job_file, job); self.dependencies.sync_jobs_index(project_id)
            return {"ok": True}
        proc = self.dependencies.PROCESS_REGISTRY().get(job_id)
        if proc:
            proc.terminate(); time.sleep(1)
            if proc.poll() is None:
                proc.kill()
            self.dependencies.PROCESS_REGISTRY().pop(job_id, None)
        elif job.get("pid") and self.dependencies._pid_alive(job.get("pid")):
            if not self.dependencies._terminate_pid_tree(job.get("pid")):
                return {"ok": False, "message": "训练进程仍在运行，但平台无法停止它。请查看任务 PID 并手工结束。"}
        else:
            return {"ok": False, "message": "训练进程已经结束，当前没有可停止的进程"}
        job.update({"status": "stopped", "message": "用户手动停止", "finished_at": self.dependencies.now_iso(), "updated_at": self.dependencies.now_iso()})
        self.dependencies._write_job_json(job_file, job)
        self.dependencies.sync_jobs_index(project_id)
        return {"ok": True}

    def v48_promote_job(self, project_id: str, job_id: str):
        if self.dependencies.shared_task_repository().is_deleted(job_id,project_id=project_id):
            raise HTTPException(status_code=404,detail="训练任务已删除，证据仅供审计")
        jf=self.dependencies.project_dir(project_id)/"jobs"/job_id/"job.json"; job=self.dependencies.read_json(jf,{})
        if not job: raise HTTPException(status_code=404,detail="训练任务不存在")
        durable = self.dependencies._durable_training_task(project_id, job_id)
        if durable is not None:
            if durable.status is not TaskStatus.QUEUED:
                raise HTTPException(status_code=400, detail="只有排队中的任务可以插队")
            promoted = self.dependencies.shared_task_repository().promote(job_id)
            job.update(queue_priority=promoted.priority,priority_scheme=self.dependencies.V56_PRIORITY_SCHEME(),promoted_at=self.dependencies.now_iso(),message="已插队到当前资源队列最前",updated_at=self.dependencies.now_iso());self.dependencies._write_job_json(jf,job); self.dependencies.sync_jobs_index(project_id)
            return job
        if job.get("status")!="queued": raise HTTPException(status_code=400,detail="只有排队中的任务可以插队")
        peers=[self.dependencies.read_json(x,{}) for x in self.dependencies._v48_all_job_files(project_id)]
        queued_peers=[x for x in peers if x.get("status")=="queued" and self.dependencies._v48_resource_key(x)==self.dependencies._v48_resource_key(job)]
        minimum=min([self.dependencies._v56_normalize_priority(x) for x in queued_peers] or [50])
        job["queue_priority"]=max(1,minimum-1)
        job["priority_scheme"]=self.dependencies.V56_PRIORITY_SCHEME()
        if minimum==1:
            job["priority_tiebreaker"]=min([int(x.get("priority_tiebreaker") or 0) for x in queued_peers] or [0])-1
        job["promoted_at"]=self.dependencies.now_iso(); job["message"]="已插队到当前资源队列最前";self.dependencies._write_job_json(jf,job)
        self.dependencies._v48_dispatch_training_queues(project_id); self.dependencies.sync_jobs_index(project_id)
        return self.dependencies.read_json(jf,job)

    def v48_pause_job(self, project_id: str, job_id: str):
        if self.dependencies.shared_task_repository().is_deleted(job_id,project_id=project_id):
            raise HTTPException(status_code=404,detail="训练任务已删除，证据仅供审计")
        jf=self.dependencies.project_dir(project_id)/"jobs"/job_id/"job.json"; job=self.dependencies.read_json(jf,{})
        if not job: raise HTTPException(status_code=404,detail="训练任务不存在")
        durable = self.dependencies._durable_training_task(project_id, job_id)
        if durable is not None:
            if durable.status is not TaskStatus.RUNNING or durable.stage == "paused":
                raise HTTPException(status_code=400, detail="只有训练中的任务可以暂停")
            from platform_core.training_timing import update_job as update_timed_job, now_utc
            updates = {"status": "paused", "message": "训练已暂停"}
            def transition():
                ProcessController().suspend_tree(self.dependencies._durable_process_identity(durable))
                updates["paused_at"] = now_utc()
                self.dependencies.shared_task_repository().set_stage(job_id, "paused")
            try:
                # Acquire the shared state lock before suspending the child. A
                # suspended callback must never own the lock needed to finish pause.
                job = update_timed_job(jf, updates, before_update=transition)
            except (ProcessLookupError, PermissionError) as error:
                raise HTTPException(status_code=409, detail=f"训练进程身份校验失败：{error}") from error
            self.dependencies.sync_jobs_index(project_id)
            return job
        if job.get("status")!="running": raise HTTPException(status_code=400,detail="只有训练中的任务可以暂停")
        if job.get("target")=="remote":
            remote=job.get("remote") or {}; base=str(remote.get("base_url") or "").rstrip("/")
            if not base: raise HTTPException(status_code=400,detail="远程任务缺少服务地址")
            r=requests.post(f"{base}/api/remote/jobs/{remote.get('job_id')}/pause",headers={"X-API-Key":remote.get("api_key","")},timeout=10)
            if not r.ok: raise HTTPException(status_code=400,detail="远程服务器暂不支持暂停："+r.text[:300])
        else:
            if not job.get("pid") or not self.dependencies._pid_alive(job.get("pid")): raise HTTPException(status_code=400,detail="训练进程不存在")
            self.dependencies._v48_suspend_tree(job.get("pid"),False)
        job.update(status="paused",message="训练已暂停",paused_at=self.dependencies.now_iso(),updated_at=self.dependencies.now_iso());self.dependencies._write_job_json(jf,job); self.dependencies.sync_jobs_index(project_id)
        return job

    def v48_resume_job(self, project_id: str, job_id: str):
        if self.dependencies.shared_task_repository().is_deleted(job_id,project_id=project_id):
            raise HTTPException(status_code=404,detail="训练任务已删除，证据仅供审计")
        jf=self.dependencies.project_dir(project_id)/"jobs"/job_id/"job.json"; job=self.dependencies.read_json(jf,{})
        if not job: raise HTTPException(status_code=404,detail="训练任务不存在")
        durable = self.dependencies._durable_training_task(project_id, job_id)
        if durable is not None:
            if durable.status is not TaskStatus.RUNNING or durable.stage != "paused":
                raise HTTPException(status_code=400, detail="只有已暂停任务可以继续")
            from platform_core.training_timing import update_job as update_timed_job, now_utc
            updates = {"status": "running", "message": "训练已继续"}
            def transition():
                ProcessController().resume_tree(self.dependencies._durable_process_identity(durable))
                updates["resumed_at"] = now_utc()
                self.dependencies.shared_task_repository().set_stage(job_id, "training")
                updates["paused_at"] = ""
            try:
                # Acquire the shared state lock before suspending the child. A
                # suspended callback must never own the lock needed to finish pause.
                job = update_timed_job(jf, updates, before_update=transition)
            except (ProcessLookupError, PermissionError) as error:
                raise HTTPException(status_code=409, detail=f"训练进程身份校验失败：{error}") from error
            self.dependencies.sync_jobs_index(project_id)
            return job
        if job.get("status")!="paused": raise HTTPException(status_code=400,detail="只有已暂停任务可以继续")
        if job.get("target")=="remote":
            remote=job.get("remote") or {}; base=str(remote.get("base_url") or "").rstrip("/")
            r=requests.post(f"{base}/api/remote/jobs/{remote.get('job_id')}/resume",headers={"X-API-Key":remote.get("api_key","")},timeout=10)
            if not r.ok: raise HTTPException(status_code=400,detail="远程服务器继续失败："+r.text[:300])
        else:
            if not job.get("pid") or not self.dependencies._pid_alive(job.get("pid")): raise HTTPException(status_code=400,detail="训练进程不存在")
            self.dependencies._v48_suspend_tree(job.get("pid"),True)
        if job.get("paused_at"):
            pdt = self.dependencies._parse_dt_value(job.get("paused_at"))
            if pdt:
                job["paused_seconds"] = int(job.get("paused_seconds") or 0) + max(0, int((datetime.now() - pdt).total_seconds()))
        job.update(status="running",message="训练已继续",resumed_at=self.dependencies.now_iso(),paused_at="",updated_at=self.dependencies.now_iso());self.dependencies._write_job_json(jf,job); self.dependencies.sync_jobs_index(project_id)
        return job

    def v48_stop_job(self, project_id: str, job_id: str):
        if self.dependencies.shared_task_repository().is_deleted(job_id,project_id=project_id):
            raise HTTPException(status_code=404,detail="训练任务已删除，证据仅供审计")
        jf=self.dependencies.project_dir(project_id)/"jobs"/job_id/"job.json"; job=self.dependencies.read_json(jf,{})
        if not job: raise HTTPException(status_code=404,detail="训练任务不存在")
        durable = self.dependencies._durable_training_task(project_id, job_id)
        if durable is not None:
            if durable.status not in {
                TaskStatus.QUEUED,
                TaskStatus.RUNNING,
                TaskStatus.CANCEL_REQUESTED,
            }:
                raise HTTPException(status_code=409, detail="训练任务已经结束，不能再次停止")
            was_queued = durable.status is TaskStatus.QUEUED
            try:
                repository = self.dependencies.shared_task_repository()
                updated = repository.request_cancel(job_id)
                self.dependencies._cancel_training_prepare_child(repository, durable)
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error
            if not was_queued and updated.process_pid is not None:
                try:
                    ProcessController().terminate_tree(self.dependencies._durable_process_identity(updated))
                except ProcessLookupError:
                    pass
                except PermissionError as error:
                    raise HTTPException(status_code=409, detail=f"训练进程身份校验失败：{error}") from error
            job.update(status="stopped",message="用户取消排队" if was_queued else "用户手动停止",finished_at=self.dependencies.now_iso(),updated_at=self.dependencies.now_iso(),never_started=was_queued);self.dependencies._write_job_json(jf,job); self.dependencies.sync_jobs_index(project_id)
            return job
        legacy_status = str(job.get("status") or "").strip().lower()
        queued_like = legacy_status in {"queued", "waiting", "pending"}
        if queued_like:
            job.update(status="stopped",message="用户取消排队",finished_at=self.dependencies.now_iso(),updated_at=self.dependencies.now_iso(),never_started=True);self.dependencies._write_job_json(jf,job)
        elif legacy_status in {"running","paused"}:
            if job.get("target")=="remote":
                remote=job.get("remote") or {}
                base=str(remote.get("base_url") or "").rstrip("/")
                remote_job_id=str(remote.get("job_id") or "").strip()
                if not base or not remote_job_id:
                    raise HTTPException(status_code=409,detail="远程训练缺少可校验的停止地址或任务 ID，未修改本地状态")
                try:
                    response=requests.post(
                        f"{base}/api/remote/jobs/{remote_job_id}/stop",
                        headers={"X-API-Key":remote.get("api_key","")},
                        timeout=10,
                    )
                except requests.RequestException as error:
                    raise HTTPException(status_code=502,detail=f"远程训练停止请求失败，本地状态保持不变：{error}") from error
                if not response.ok:
                    detail=(response.text or "").strip()[:300]
                    raise HTTPException(
                        status_code=502,
                        detail=f"远程训练停止失败，本地状态保持不变：HTTP {response.status_code}{' · '+detail if detail else ''}",
                    )
            else:
                self.dependencies._terminate_pid_tree(job.get("pid")); self.dependencies.PROCESS_REGISTRY().pop(job_id,None)
            job.update(status="stopped",message="用户手动停止",finished_at=self.dependencies.now_iso(),updated_at=self.dependencies.now_iso());self.dependencies._write_job_json(jf,job)
        else:
            raise HTTPException(status_code=409, detail="训练任务已经结束或不处于可停止状态，未修改本地状态")
        # 只有真正开始过训练的任务才形成算法版本；排队/等待资源后取消不属于一次算法迭代。
        if not queued_like:
            self.dependencies._v48_archive_training_version(project_id,job)
        self.dependencies._v48_dispatch_training_queues(project_id); self.dependencies.sync_jobs_index(project_id)
        return self.dependencies.read_json(jf,job)

    def _purge_terminal_training_job_record(self, project_id: str, job_id: str) -> Dict[str, Any]:
        job_id = str(job_id or "").strip()
        if not job_id or job_id in {".", ".."} or "/" in job_id or "\\" in job_id:
            raise ValueError("训练任务 ID 不合法")
        job_dir = self.dependencies.project_dir(project_id) / "jobs" / job_id
        job = self.dependencies.read_json(job_dir / "job.json", {})
        durable = self.dependencies._durable_training_task(project_id, job_id)
        if durable is None and not job:
            return {"status": "missing", "job_id": job_id}

        if durable is not None:
            if durable.status not in self.dependencies._TRAINING_DURABLE_TERMINAL_STATUSES():
                return {"status": "active", "job_id": job_id}
        else:
            status = str(job.get("status") or "").strip().lower()
            if status not in self.dependencies._TRAINING_LEGACY_TERMINAL_STATUSES():
                return {"status": "active", "job_id": job_id}

        proc = self.dependencies.PROCESS_REGISTRY().get(job_id)
        if proc and proc.poll() is None:
            return {"status": "active", "job_id": job_id}

        repository=self.dependencies.shared_task_repository()
        artifacts=self.dependencies.shared_task_artifacts()
        retained=artifacts.retention_required(job_id) or bool(durable and durable.attempt>0) or bool(job.get('snapshot_id') or job.get('models'))
        retained=retained or any((artifacts.root/job_id/name).exists() for name in ('input-freeze.json','snapshot.json','dataset-revision.json'))
        if durable is not None:
            removed=repository.delete_terminal(job_id,project_id=project_id,kind=TaskKind.TRAINING)
            if not removed and not repository.is_deleted(job_id,project_id=project_id):
                raise ValueError('task changed during deletion')
        else:
            repository.record_legacy_deletion(job_id,project_id)
        if not retained:
            try:
                artifacts.delete_task(job_id)
                shutil.rmtree(job_dir)
            except FileNotFoundError:
                pass
            except (OSError, ValueError):
                retained=True  # Logical deletion committed; report deferred cleanup.
        self.dependencies.PROCESS_REGISTRY().pop(job_id,None)
        return {'status':'deleted','job_id':job_id,'artifacts_retained':retained}

    def v48_job_deletion_status(self, project_id: str, job_ids: str):
        """Read-only classification for records whose deletion result is unknown.

        It never deletes, retries or invents a receipt: it only reports whether the
        durable/legacy record still exists, whether the task is terminal, and
        whether the repository already records a deletion for this project.
        """
        self.dependencies.get_project(project_id)
        ids = list(dict.fromkeys(
            str(value or "").strip() for value in str(job_ids or "").split(",") if str(value or "").strip()
        ))
        if len(ids) > 200:
            raise HTTPException(status_code=400, detail="单次最多核对 200 条训练记录")
        repository = self.dependencies.shared_task_repository()
        items: List[Dict[str, str]] = []
        for job_id in ids:
            if job_id in {".", ".."} or "/" in job_id or "\\" in job_id:
                items.append({"job_id": job_id, "state": "invalid"})
                continue
            if repository.is_deleted(job_id, project_id=project_id):
                items.append({"job_id": job_id, "state": "deleted"})
                continue
            job = self.dependencies.read_json(self.dependencies.project_dir(project_id) / "jobs" / job_id / "job.json", {})
            durable = self.dependencies._durable_training_task(project_id, job_id)
            if durable is None and not job:
                items.append({"job_id": job_id, "state": "missing"})
                continue
            if durable is not None:
                terminal = durable.status in self.dependencies._TRAINING_DURABLE_TERMINAL_STATUSES()
            else:
                terminal = str(job.get("status") or "").strip().lower() in self.dependencies._TRAINING_LEGACY_TERMINAL_STATUSES()
            proc = self.dependencies.PROCESS_REGISTRY().get(job_id)
            running = bool(proc and proc.poll() is None)
            items.append({"job_id": job_id, "state": "terminal" if terminal and not running else "active"})
        counts = {state: sum(1 for row in items if row["state"] == state)
                  for state in ("deleted", "terminal", "active", "missing", "invalid")}
        return {"ok": True, "project_id": project_id, "items": items, "counts": counts}

    def v48_batch_delete_jobs(self, project_id: str, payload: V48TrainingBatchDeleteReq):
        self.dependencies.get_project(project_id)
        job_ids = list(dict.fromkeys(str(value or "").strip() for value in payload.job_ids if str(value or "").strip()))
        if not job_ids:
            raise HTTPException(status_code=400, detail="请选择需要删除的训练记录")
        if len(job_ids) > 200:
            raise HTTPException(status_code=400, detail="单次最多批量删除 200 条训练记录")

        deleted_ids: List[str] = []
        retained_ids: List[str] = []
        skipped_active_ids: List[str] = []
        missing_ids: List[str] = []
        failures: List[Dict[str, str]] = []
        for job_id in job_ids:
            try:
                result = self._purge_terminal_training_job_record(project_id, job_id)
                status = str(result.get("status") or "")
                if status == "deleted":
                    deleted_ids.append(job_id)
                    if result.get('artifacts_retained'):
                        retained_ids.append(job_id)
                elif status == "active":
                    skipped_active_ids.append(job_id)
                else:
                    missing_ids.append(job_id)
            except Exception as error:
                failures.append({"job_id": job_id, "message": str(error)})

        try:
            self.dependencies._v48_dispatch_training_queues(project_id)
        except Exception:
            pass
        self.dependencies.sync_jobs_index(project_id)
        return {
            "ok": not failures,
            "requested": len(job_ids),
            "deleted": len(deleted_ids),
            "deleted_ids": deleted_ids,
            "audit_retained_ids": retained_ids,
            "skipped_active": len(skipped_active_ids),
            "skipped_active_ids": skipped_active_ids,
            "missing": len(missing_ids),
            "missing_ids": missing_ids,
            "failed": len(failures),
            "failures": failures,
        }

    def v12_delete_job(self, project_id: str, job_id: str):
        self.dependencies.get_project(project_id)
        job_dir = self.dependencies.project_dir(project_id) / "jobs" / job_id
        job = self.dependencies.read_json(job_dir / "job.json", {})
        durable = self.dependencies._durable_training_task(project_id, job_id)

        # Durable truth is authoritative when present. A stale legacy job.json must
        # never make a finished durable task look active, nor may a cleanup request
        # erase live durable work without cancellation first.
        durable_active = durable is not None and durable.status in {
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
            TaskStatus.CANCEL_REQUESTED,
        }
        legacy_active = durable is None and str(job.get("status") or "").lower() in {
            "queued", "waiting", "pending", "running", "paused",
        }
        if durable_active or legacy_active:
            self.v48_stop_job(project_id, job_id)
            # Preserve durable task artifacts while cancellation/finalization may
            # still be completing. This keeps the existing single-record behavior.
            shutil.rmtree(job_dir, ignore_errors=True)
        else:
            try:
                self._purge_terminal_training_job_record(project_id, job_id)
            except ValueError as error:
                raise HTTPException(status_code=409, detail=str(error)) from error

        try:
            self.dependencies._v48_dispatch_training_queues(project_id)
        except Exception:
            pass
        self.dependencies.sync_jobs_index(project_id)
        return {"ok": True}

    def _training_sse_message(self, row: Mapping[str, Any]) -> str:
        payload = json.dumps(dict(row), ensure_ascii=False, separators=(",", ":"))
        return f"event: training.task\ndata: {payload}\n\n"
