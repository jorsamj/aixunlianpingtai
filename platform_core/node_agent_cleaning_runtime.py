"""Database-free Agent runner for portable MATERIAL_BATCH/CLEAN tasks."""
from __future__ import annotations

import hashlib
import json
import os
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

from .cleaning import ImageDecodeError, clean_options
from .cleaning_analysis_runtime import CleaningAnalysisRuntime
from .node_agent_executor_runtime import (
    AgentExecutionWorkdir,
    ExecutionLeaseMonitor,
    RemoteExecutionFenced,
    RemoteExecutionLease,
)

_TRANSFER_CHUNK_BYTES = 1024 * 1024
_MAX_REMOTE_CLEAN_ITEMS = 250_000


class AgentCleaningRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentCleaningOutcome:
    task_id: str
    status: str
    result_ref: str | None = None
    error: str = ""


def _absolute_http_url(value: object, field: str) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentCleaningRuntimeError(f"{field} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise AgentCleaningRuntimeError(f"{field} must not contain userinfo")
    return raw


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_TRANSFER_CHUNK_BYTES), b""):
            digest.update(chunk)
    return digest.hexdigest()


class _MonitoredUploadBody:
    def __init__(self, path: Path, assert_active, size_bytes: int):
        self.path = path
        self.assert_active = assert_active
        self.size_bytes = int(size_bytes)

    def __len__(self) -> int:
        return self.size_bytes

    def __iter__(self):
        sent = 0
        with self.path.open("rb") as stream:
            while True:
                self.assert_active()
                chunk = stream.read(_TRANSFER_CHUNK_BYTES)
                if not chunk:
                    break
                sent += len(chunk)
                if sent > self.size_bytes:
                    raise AgentCleaningRuntimeError("cleaning review changed while uploading")
                yield chunk
        if sent != self.size_bytes:
            raise AgentCleaningRuntimeError("cleaning review size changed while uploading")


class AgentCleaningRunner:
    def __init__(
        self,
        client,
        workdirs: AgentExecutionWorkdir,
        *,
        transfer_session: requests.Session | None = None,
        heartbeat_interval: float = 5.0,
        transfer_timeout: float = 1800.0,
    ) -> None:
        self.client = client
        self.workdirs = workdirs
        self.transfer_session = transfer_session or requests.Session()
        self.heartbeat_interval = max(1.0, float(heartbeat_interval))
        self.transfer_timeout = max(30.0, float(transfer_timeout))
        self._shutdown_event = threading.Event()
        self._ready = True
        self._recovery_error = ""
        try:
            import PIL  # noqa: F401
            import cv2  # noqa: F401
            import numpy  # noqa: F401
        except Exception as error:
            self._ready = False
            self._recovery_error = (
                "CLEANING_RUNTIME_UNAVAILABLE: "
                f"{type(error).__name__}: {error}"
            )

    @property
    def ready(self) -> bool:
        return self._ready

    @property
    def recovery_error(self) -> str:
        return self._recovery_error

    def request_shutdown(self) -> None:
        self._shutdown_event.set()

    def _assert_active(self, monitor: ExecutionLeaseMonitor) -> None:
        if self._shutdown_event.is_set():
            raise RemoteExecutionFenced("Agent process shutdown requested")
        monitor.assert_active()

    def _heartbeat(
        self,
        monitor: ExecutionLeaseMonitor,
        *,
        progress: float,
        stage: str,
        current_item: str,
    ) -> None:
        self._assert_active(monitor)
        monitor.beat(progress=progress, stage=stage, current_item=current_item)

    def _download(
        self,
        contract: Mapping[str, Any],
        destination: Path,
        monitor: ExecutionLeaseMonitor,
    ) -> Path:
        if str(contract.get("method") or "GET").upper() != "GET":
            raise AgentCleaningRuntimeError("cleaning download method must be GET")
        url = _absolute_http_url(contract.get("url"), "cleaning.download.url")
        headers = contract.get("headers") or {}
        if not isinstance(headers, Mapping):
            raise AgentCleaningRuntimeError("cleaning download headers must be an object")
        try:
            expected_size = int(contract.get("size_bytes") or 0)
        except (TypeError, ValueError) as error:
            raise AgentCleaningRuntimeError("cleaning source size is invalid") from error
        expected_sha = str(contract.get("sha256") or "").strip().lower()
        if (
            expected_size <= 0
            or len(expected_sha) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha)
        ):
            raise AgentCleaningRuntimeError("cleaning source evidence is incomplete")
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.download")
        temporary.unlink(missing_ok=True)
        try:
            response = self.transfer_session.get(
                url,
                headers={str(key): str(value) for key, value in headers.items()},
                stream=True,
                timeout=self.transfer_timeout,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise AgentCleaningRuntimeError(
                f"cleaning source download failed: {type(error).__name__}: {error}"
            ) from error
        try:
            if not (200 <= int(response.status_code) < 300):
                raise AgentCleaningRuntimeError(
                    f"cleaning source download returned HTTP {response.status_code}"
                )
            header_size = str(getattr(response, "headers", {}).get("Content-Length") or "").strip()
            if header_size and int(header_size) != expected_size:
                raise AgentCleaningRuntimeError("cleaning source Content-Length changed")
            digest = hashlib.sha256()
            written = 0
            with temporary.open("xb") as stream:
                for chunk in response.iter_content(chunk_size=_TRANSFER_CHUNK_BYTES):
                    self._assert_active(monitor)
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > expected_size:
                        raise AgentCleaningRuntimeError("cleaning source exceeded expected size")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if written != expected_size or digest.hexdigest() != expected_sha:
                raise AgentCleaningRuntimeError("cleaning source bytes changed after task freeze")
            os.replace(temporary, destination)
            return destination
        finally:
            temporary.unlink(missing_ok=True)
            try:
                response.close()
            except Exception:
                pass

    def _upload_result(
        self,
        upload: Mapping[str, Any],
        path: Path,
        monitor: ExecutionLeaseMonitor,
        *,
        size_bytes: int,
        sha256: str,
    ) -> None:
        if str(upload.get("method") or "").upper() != "PUT":
            raise AgentCleaningRuntimeError("cleaning review upload method must be PUT")
        url = _absolute_http_url(upload.get("url"), "cleaning.output.url")
        headers = upload.get("headers")
        if not isinstance(headers, Mapping):
            raise AgentCleaningRuntimeError("cleaning review upload headers must be an object")
        normalized = {str(key): str(value) for key, value in headers.items()}
        lowered = {key.lower(): value for key, value in normalized.items()}
        if lowered.get("content-length") != str(int(size_bytes)):
            raise AgentCleaningRuntimeError("cleaning review upload does not bind Content-Length")
        if sha256 not in {
            lowered.get("x-amz-meta-sha256"),
            lowered.get("x-oss-meta-sha256"),
        }:
            raise AgentCleaningRuntimeError("cleaning review upload does not bind SHA256")
        if (
            lowered.get("if-none-match") != "*"
            and lowered.get("x-oss-forbid-overwrite", "").lower() != "true"
        ):
            raise AgentCleaningRuntimeError("cleaning review upload does not prevent overwrite")
        try:
            response = self.transfer_session.put(
                url,
                headers=normalized,
                data=_MonitoredUploadBody(
                    path,
                    lambda: self._assert_active(monitor),
                    size_bytes,
                ),
                timeout=self.transfer_timeout,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise AgentCleaningRuntimeError(
                f"cleaning review upload failed: {type(error).__name__}: {error}"
            ) from error
        try:
            if not (200 <= int(response.status_code) < 300):
                raise AgentCleaningRuntimeError(
                    f"cleaning review upload returned HTTP {response.status_code}"
                )
        finally:
            try:
                response.close()
            except Exception:
                pass

    def run(self, lease: RemoteExecutionLease) -> AgentCleaningOutcome:
        if self._shutdown_event.is_set():
            raise RemoteExecutionFenced("Agent process shutdown requested")
        if not self.ready:
            raise AgentCleaningRuntimeError(self.recovery_error)
        if lease.kind != "MATERIAL_BATCH":
            raise AgentCleaningRuntimeError("AgentCleaningRunner only accepts MATERIAL_BATCH")
        payload = lease.payload
        if (
            int(payload.get("schema_version") or 0) != 1
            or str(payload.get("task_kind") or "") != "MATERIAL_BATCH"
            or str(payload.get("transport") or "") != "object-storage-v1"
            or str(payload.get("operation") or "") != "CLEAN"
        ):
            raise AgentCleaningRuntimeError("portable cleaning start payload is invalid")
        selection = payload.get("selection")
        output = payload.get("output")
        options = clean_options(payload.get("options") or {})
        if (
            not isinstance(selection, Mapping)
            or str(selection.get("protocol") or "") != "exact-material-selection-v1"
            or not isinstance(output, Mapping)
            or str(output.get("type") or "") != "object"
            or str(output.get("upload_protocol") or "") != "prepare-after-local-hash-v1"
            or not isinstance(output.get("storage_ref"), Mapping)
        ):
            raise AgentCleaningRuntimeError("portable cleaning contracts are incomplete")

        workdir = self.workdirs.prepare(lease)
        monitor = ExecutionLeaseMonitor(self.client, lease, interval=self.heartbeat_interval)
        monitor.start()
        analysis = CleaningAnalysisRuntime()
        try:
            review_path = workdir / "output" / "cleaning-review.jsonl"
            review_path.parent.mkdir(parents=True, exist_ok=True)
            cursor = None
            processed = succeeded = failed = 0
            header_written = False
            total = None
            seen_cursors: set[str] = set()
            with review_path.open("w", encoding="utf-8", newline="\n") as review:
                while True:
                    self._heartbeat(
                        monitor,
                        progress=5 if total is None else 5 + 80 * processed / max(1, total),
                        stage="REMOTE_CLEANING_FETCHING_SELECTION",
                        current_item="读取冻结清洗范围",
                    )
                    page = self.client.clean_selection_page(lease, cursor=cursor, limit=100)
                    items = page.get("items")
                    if not isinstance(items, list):
                        raise AgentCleaningRuntimeError("cleaning selection broker returned invalid items")
                    page_total = int(page.get("total") or 0)
                    if total is None:
                        total = page_total
                        if total < 0 or total > _MAX_REMOTE_CLEAN_ITEMS:
                            raise AgentCleaningRuntimeError("cleaning selection exceeds the 250000 item safety limit")
                        review.write(json.dumps({
                            "schema_version": 1,
                            "task_id": lease.task_id,
                            "project_id": lease.project_id,
                            "execution_generation": lease.generation,
                            "operation": "CLEAN",
                            "total": total,
                        }, ensure_ascii=False, separators=(",", ":")) + "\n")
                        header_written = True
                    elif page_total != total:
                        raise AgentCleaningRuntimeError("cleaning selection total changed during execution")

                    for item in items:
                        self._assert_active(monitor)
                        if not isinstance(item, Mapping):
                            raise AgentCleaningRuntimeError("cleaning selection returned an invalid item")
                        image_id = str(item.get("image_id") or "").strip()
                        source_sha = str(item.get("sha256") or "").strip().lower()
                        source_size = int(item.get("size_bytes") or 0)
                        if (
                            not image_id
                            or source_size <= 0
                            or len(source_sha) != 64
                        ):
                            raise AgentCleaningRuntimeError("cleaning selection item lacks durable source evidence")
                        read = self.client.clean_selection_read(lease, image_id)
                        source = read.get("source")
                        download = read.get("download")
                        if (
                            not isinstance(source, Mapping)
                            or not isinstance(download, Mapping)
                            or str(source.get("image_id") or "") != image_id
                            or str(source.get("sha256") or "").strip().lower() != source_sha
                            or int(source.get("size_bytes") or 0) != source_size
                        ):
                            raise AgentCleaningRuntimeError("cleaning read contract changed selected material identity")
                        suffix = Path(str(source.get("file_name") or "image.bin")).suffix.lower()
                        if not suffix or len(suffix) > 12:
                            suffix = ".bin"
                        local = workdir / "input" / f"current{suffix}"
                        local.unlink(missing_ok=True)
                        status = "analyzed"
                        metrics = None
                        error_text = ""
                        try:
                            self._heartbeat(
                                monitor,
                                progress=5 + 80 * processed / max(1, total),
                                stage="REMOTE_CLEANING_DOWNLOADING",
                                current_item=image_id,
                            )
                            self._download(download, local, monitor)
                            self._heartbeat(
                                monitor,
                                progress=5 + 80 * processed / max(1, total),
                                stage="REMOTE_CLEANING_ANALYZING",
                                current_item=image_id,
                            )
                            metrics = analysis.analyze(
                                local,
                                require_blur=bool(options["blur_check"]),
                                content_sha256=source_sha,
                                check_active=lambda: self._assert_active(monitor),
                            )
                            succeeded += 1
                        except ImageDecodeError as error:
                            status = "corrupt"
                            error_text = str(error)[:1000]
                            if options["corrupt_check"]:
                                succeeded += 1
                            else:
                                failed += 1
                        except RemoteExecutionFenced:
                            raise
                        except Exception as error:
                            status = "failed"
                            error_text = f"{type(error).__name__}: {error}"[:1000]
                            failed += 1
                        finally:
                            local.unlink(missing_ok=True)
                        review.write(json.dumps({
                            "image_id": image_id,
                            "source_sha256": source_sha,
                            "source_size_bytes": source_size,
                            "status": status,
                            "metrics": metrics,
                            "error": error_text,
                        }, ensure_ascii=False, separators=(",", ":")) + "\n")
                        processed += 1

                    next_cursor = str(page.get("next_cursor") or "")
                    if not next_cursor:
                        break
                    if next_cursor in seen_cursors:
                        raise AgentCleaningRuntimeError("cleaning selection broker returned a repeated cursor")
                    seen_cursors.add(next_cursor)
                    cursor = next_cursor

                if not header_written:
                    raise AgentCleaningRuntimeError("cleaning selection broker returned no header truth")
                if processed != int(total or 0):
                    raise AgentCleaningRuntimeError("cleaning selection ended before all frozen items were analyzed")
                review.flush()
                os.fsync(review.fileno())

            review_sha = _sha256_file(review_path)
            review_size = int(review_path.stat().st_size)
            self._heartbeat(
                monitor,
                progress=90,
                stage="REMOTE_CLEANING_PREPARING_UPLOAD",
                current_item="准备清洗分析结果",
            )
            prepared = self.client.prepare_result_upload(
                lease,
                sha256=review_sha,
                size_bytes=review_size,
            )
            if not bool(prepared.get("already_uploaded")):
                upload = prepared.get("upload")
                if not isinstance(upload, Mapping):
                    raise AgentCleaningRuntimeError("control plane returned no cleaning review upload contract")
                self._upload_result(
                    upload,
                    review_path,
                    monitor,
                    size_bytes=review_size,
                    sha256=review_sha,
                )
            self._heartbeat(
                monitor,
                progress=96,
                stage="REMOTE_CLEANING_CONFIRMING_REVIEW",
                current_item="中央校验并提交清洗结果",
            )
            confirmed = self.client.confirm_result_upload(
                lease,
                runtime_result={
                    "ok": True,
                    "engine": "material-cleaning",
                    "processed": processed,
                    "succeeded": succeeded,
                    "failed": failed,
                },
            )
            result_ref = str(confirmed.get("result_ref") or "")
            if not result_ref:
                raise AgentCleaningRuntimeError("control plane did not confirm cleaning result")
            self._assert_active(monitor)
            final_status = "SUCCEEDED" if failed == 0 else ("PARTIAL_SUCCESS" if succeeded else "FAILED")
            finished = self.client.finish(lease, final_status, result_ref=result_ref)
            task = finished.get("task")
            if not isinstance(task, Mapping) or str(task.get("status") or "") != final_status:
                raise AgentCleaningRuntimeError("control plane did not persist cleaning terminal status")
            return AgentCleaningOutcome(
                task_id=lease.task_id,
                status=final_status,
                result_ref=result_ref,
            )
        except RemoteExecutionFenced:
            raise
        except InterruptedError as error:
            try:
                self.client.finish(lease, "CANCELLED", error=str(error))
            except Exception:
                pass
            return AgentCleaningOutcome(lease.task_id, "CANCELLED", error=str(error))
        except Exception as error:
            try:
                self.client.finish(
                    lease,
                    "FAILED",
                    error=f"{type(error).__name__}: {error}",
                )
            except Exception:
                pass
            return AgentCleaningOutcome(
                lease.task_id,
                "FAILED",
                error=f"{type(error).__name__}: {error}",
            )
        finally:
            analysis.close()
            monitor.stop()
            self.workdirs.cleanup(lease)


__all__ = [
    "AgentCleaningOutcome",
    "AgentCleaningRunner",
    "AgentCleaningRuntimeError",
]
