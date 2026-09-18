"""Database-free Agent-side runner for portable MODEL_CONVERSION tasks."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse

import requests

from .node_agent_executor_runtime import (
    AgentExecutionWorkdir,
    ExecutionLeaseMonitor,
    NodeExecutorHTTPError,
    RemoteExecutionFenced,
    RemoteExecutionLease,
)
from .task_runtime.process_control import (
    ProcessController,
    ProcessIdentity,
    launch_process,
)


_TRANSFER_CHUNK_BYTES = 1024 * 1024
_MAX_REMOTE_LOG_FORWARD_BYTES = 60 * 1024
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SUPPORTED_SOURCE_SUFFIXES = {".pt", ".pth", ".onnx"}


class AgentConversionRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentConversionOutcome:
    task_id: str
    generation: int
    status: str
    result_ref: str = ""
    error: str = ""


def _absolute_http_url(value: object, field: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentConversionRuntimeError(f"{field} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise AgentConversionRuntimeError(f"{field} must not contain userinfo")
    return url


def _safe_filename(value: object, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return fallback
    if "/" in raw or "\\" in raw:
        raise AgentConversionRuntimeError("portable file_name must be a basename")
    name = Path(raw).name
    if not name or name in {".", ".."}:
        raise AgentConversionRuntimeError("portable file_name must be a basename")
    return name[:240]


def _expected_evidence(contract: Mapping[str, Any]) -> tuple[int, str]:
    try:
        size = int(contract.get("size_bytes"))
    except (TypeError, ValueError) as error:
        raise AgentConversionRuntimeError("download size_bytes is invalid") from error
    digest = str(contract.get("sha256") or "").strip().lower()
    if size <= 0 or not _SHA256.fullmatch(digest):
        raise AgentConversionRuntimeError("download content evidence is incomplete")
    return size, digest


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(_TRANSFER_CHUNK_BYTES), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


class _MonitoredUploadBody:
    def __init__(
        self,
        path: Path,
        assert_active,
        size_bytes: int,
    ) -> None:
        self.path = Path(path)
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
                    raise AgentConversionRuntimeError(
                        "conversion result changed while uploading"
                    )
                yield chunk
        if sent != self.size_bytes:
            raise AgentConversionRuntimeError(
                "conversion result size changed while uploading"
            )


class AgentConversionRunner:
    def __init__(
        self,
        client,
        workdirs: AgentExecutionWorkdir,
        *,
        runtime_root: str | Path,
        ultralytics_python: str | Path | None = None,
        transfer_session: requests.Session | None = None,
        heartbeat_interval: float = 5.0,
        transfer_timeout: float = 600.0,
        process_poll_interval: float = 0.2,
    ) -> None:
        self.client = client
        self.workdirs = workdirs
        self.runtime_root = Path(runtime_root).expanduser().resolve()
        self.ultralytics_python = Path(
            ultralytics_python or sys.executable
        ).expanduser().resolve()
        self.transfer_session = transfer_session or requests.Session()
        self.heartbeat_interval = max(1.0, float(heartbeat_interval))
        self.transfer_timeout = max(30.0, float(transfer_timeout))
        self.process_poll_interval = max(0.05, float(process_poll_interval))
        self.controller = ProcessController()
        self._identity_lock = threading.Lock()
        self._active_identity: ProcessIdentity | None = None
        self._active_lease: RemoteExecutionLease | None = None
        self._shutdown_event = threading.Event()
        self._recovery_error = ""
        self._recover_persisted_processes()

    @property
    def ready(self) -> bool:
        return not bool(self._recovery_error)

    @property
    def recovery_error(self) -> str:
        return str(self._recovery_error or "")

    def _active_process(
        self,
    ) -> tuple[RemoteExecutionLease | None, ProcessIdentity | None]:
        with self._identity_lock:
            return self._active_lease, self._active_identity

    def _set_active_process(
        self,
        lease: RemoteExecutionLease,
        identity: ProcessIdentity,
    ) -> None:
        with self._identity_lock:
            self._active_lease = lease
            self._active_identity = identity

    def _clear_active_process(self) -> None:
        with self._identity_lock:
            self._active_lease = None
            self._active_identity = None

    def _recover_persisted_processes(self) -> bool:
        try:
            records = self.workdirs.list_process_identities()
        except (OSError, ValueError) as error:
            self._recovery_error = (
                f"persisted conversion process identity is unsafe or unreadable: {error}"
            )
            return False
        for record in records:
            identity = ProcessIdentity(
                pid=int(record["pid"]),
                create_time=float(record["create_time"]),
                command_hash=str(record["command_hash"]),
            )
            try:
                self.controller.terminate_tree(identity, timeout=8.0)
            except ProcessLookupError:
                pass
            except PermissionError as error:
                self._recovery_error = (
                    "stale conversion process cleanup could not be verified: "
                    f"{type(error).__name__}: {error}"
                )
                return False
            try:
                self.workdirs.clear_process_identity_record(
                    str(record["task_id"]),
                    int(record["generation"]),
                )
            except (OSError, ValueError) as error:
                self._recovery_error = (
                    "stale conversion process identity cleanup could not be persisted: "
                    f"{type(error).__name__}: {error}"
                )
                return False
        self._recovery_error = ""
        return True

    def _terminate_active(self, *, strict: bool = False) -> bool:
        lease, identity = self._active_process()
        if identity is None:
            return True
        try:
            self.controller.terminate_tree(identity, timeout=8.0)
        except ProcessLookupError:
            pass
        except PermissionError as error:
            self._recovery_error = (
                "conversion process cleanup could not be verified: "
                f"{type(error).__name__}: {error}"
            )
            if strict:
                raise RemoteExecutionFenced(self._recovery_error) from error
            return False
        if lease is not None:
            try:
                self.workdirs.clear_process_identity(lease)
            except (OSError, ValueError) as error:
                self._recovery_error = (
                    "conversion process identity cleanup could not be persisted: "
                    f"{type(error).__name__}: {error}"
                )
                if strict:
                    raise RemoteExecutionFenced(self._recovery_error) from error
                return False
        self._clear_active_process()
        self._recovery_error = ""
        return True

    def request_shutdown(self) -> None:
        self._shutdown_event.set()
        self._terminate_active()

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
        current_item: str = "",
    ) -> None:
        monitor.beat(
            progress=max(0.0, min(100.0, float(progress))),
            stage=str(stage),
            current_item=current_item or None,
        )
        self._assert_active(monitor)

    def _append_log(self, lease: RemoteExecutionLease, text: str) -> None:
        value = str(text or "")
        if not value:
            return
        encoded = value.encode("utf-8", errors="replace")
        if len(encoded) > _MAX_REMOTE_LOG_FORWARD_BYTES:
            value = encoded[-_MAX_REMOTE_LOG_FORWARD_BYTES:].decode(
                "utf-8",
                errors="replace",
            )
        try:
            self.client.append_log(lease, value)
        except Exception:
            pass

    def _forward_log_delta(
        self,
        lease: RemoteExecutionLease,
        path: Path,
        offset: int,
    ) -> int:
        try:
            size = int(path.stat().st_size)
        except OSError:
            return offset
        if size <= offset:
            return size if size < offset else offset
        current = offset
        try:
            with path.open("rb") as stream:
                stream.seek(offset)
                for _ in range(4):
                    chunk = stream.read(_MAX_REMOTE_LOG_FORWARD_BYTES)
                    if not chunk:
                        break
                    current += len(chunk)
                    self._append_log(
                        lease,
                        chunk.decode("utf-8", errors="replace"),
                    )
        except OSError:
            return offset
        return current

    def _download(
        self,
        contract: Mapping[str, Any],
        destination: Path,
        monitor: ExecutionLeaseMonitor,
    ) -> Path:
        if str(contract.get("method") or "GET").upper() != "GET":
            raise AgentConversionRuntimeError("portable download method must be GET")
        url = _absolute_http_url(contract.get("url"), "download.url")
        headers = contract.get("headers")
        if headers is None:
            headers = {}
        if not isinstance(headers, Mapping):
            raise AgentConversionRuntimeError("download headers must be an object")
        expected_size, expected_sha = _expected_evidence(contract)
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
            raise AgentConversionRuntimeError(
                f"portable download failed: {type(error).__name__}: {error}"
            ) from error
        try:
            if not (200 <= int(response.status_code) < 300):
                raise AgentConversionRuntimeError(
                    f"portable download returned HTTP {response.status_code}"
                )
            header_size = str(
                getattr(response, "headers", {}).get("Content-Length") or ""
            ).strip()
            if header_size:
                try:
                    if int(header_size) != expected_size:
                        raise AgentConversionRuntimeError(
                            "download Content-Length does not match durable evidence"
                        )
                except ValueError as error:
                    raise AgentConversionRuntimeError(
                        "download Content-Length is invalid"
                    ) from error
            digest = hashlib.sha256()
            written = 0
            with temporary.open("xb") as stream:
                for chunk in response.iter_content(chunk_size=_TRANSFER_CHUNK_BYTES):
                    self._assert_active(monitor)
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > expected_size:
                        raise AgentConversionRuntimeError(
                            "download exceeded expected size"
                        )
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if written != expected_size:
                raise AgentConversionRuntimeError(
                    "download size does not match durable evidence"
                )
            if digest.hexdigest() != expected_sha:
                raise AgentConversionRuntimeError(
                    "download sha256 does not match durable evidence"
                )
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
            raise AgentConversionRuntimeError(
                "portable result upload method must be PUT"
            )
        url = _absolute_http_url(upload.get("url"), "upload.url")
        headers = upload.get("headers")
        if not isinstance(headers, Mapping):
            raise AgentConversionRuntimeError(
                "result upload headers must be an object"
            )
        normalized = {str(key): str(value) for key, value in headers.items()}
        lowered = {key.lower(): value for key, value in normalized.items()}
        if lowered.get("content-length") != str(int(size_bytes)):
            raise AgentConversionRuntimeError(
                "result upload contract does not bind Content-Length"
            )
        if sha256 not in {
            lowered.get("x-amz-meta-sha256"),
            lowered.get("x-oss-meta-sha256"),
        }:
            raise AgentConversionRuntimeError(
                "result upload contract does not bind sha256 metadata"
            )
        if (
            lowered.get("if-none-match") != "*"
            and lowered.get("x-oss-forbid-overwrite", "").lower() != "true"
        ):
            raise AgentConversionRuntimeError(
                "result upload contract does not prevent overwrite"
            )
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
            raise AgentConversionRuntimeError(
                f"portable result upload failed: {type(error).__name__}: {error}"
            ) from error
        try:
            if not (200 <= int(response.status_code) < 300):
                raise AgentConversionRuntimeError(
                    f"portable result upload returned HTTP {response.status_code}"
                )
        finally:
            try:
                response.close()
            except Exception:
                pass

    def _finish_best_effort(
        self,
        lease: RemoteExecutionLease,
        status: str,
        *,
        result_ref: str | None = None,
        error: str | None = None,
    ) -> dict[str, Any] | None:
        try:
            return self.client.finish(
                lease,
                status,
                result_ref=result_ref,
                error=error,
            )
        except (NodeExecutorHTTPError, OSError, requests.RequestException):
            return None

    def _prepare_job(
        self,
        lease: RemoteExecutionLease,
        payload: Mapping[str, Any],
        workdir: Path,
        source_path: Path,
    ) -> tuple[Path, Path, list[str]]:
        if not self.ultralytics_python.is_file():
            raise AgentConversionRuntimeError(
                "node-local Ultralytics Python runtime is unavailable"
            )
        worker = (self.runtime_root / "deployment_worker.py").resolve()
        if (
            not worker.is_file()
            or worker.is_symlink()
            or worker.parent != self.runtime_root
        ):
            raise AgentConversionRuntimeError(
                "node-local deployment_worker.py is unavailable"
            )
        params = payload.get("params")
        if not isinstance(params, Mapping):
            raise AgentConversionRuntimeError(
                "portable conversion parameters are missing"
            )
        safe_params = {
            key: params.get(key)
            for key in ("input_size", "batch", "opset", "dynamic", "simplify")
        }
        job_dir = workdir / "conversion"
        artifacts = job_dir / "artifacts"
        artifacts.mkdir(parents=True, exist_ok=True)
        job_file = job_dir / "job.json"
        job = {
            "id": lease.task_id,
            "status": "queued",
            "stage": "等待启动",
            "progress": 0,
            "source_path": str(source_path),
            "source_name": source_path.name,
            "source_trace": dict(payload.get("source_trace") or {})
            if isinstance(payload.get("source_trace"), Mapping)
            else {},
            "target": "onnx",
            "resource": {
                "id": "agent-onnx",
                "name": "Agent ONNX Runtime",
                "kind": "onnx",
                "mode": "local",
                "ultralytics_python": str(self.ultralytics_python),
                "python_path": str(self.ultralytics_python),
            },
            "params": safe_params,
            "outputs": [],
        }
        job_file.write_text(
            json.dumps(job, ensure_ascii=False, sort_keys=True),
            encoding="utf-8",
        )
        command = [
            str(self.ultralytics_python),
            str(worker),
            "--job-dir",
            str(job_dir),
        ]
        return job_dir, job_file, command

    @staticmethod
    def _read_job(path: Path) -> dict[str, Any]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _verified_onnx(job_dir: Path, job: Mapping[str, Any]) -> Path:
        if str(job.get("status") or "").strip().lower() != "done":
            raise AgentConversionRuntimeError(
                "conversion worker did not reach done state"
            )
        if (
            job.get("runtime_verified") is not True
            or str(job.get("validation_status") or "") != "runtime_verified"
        ):
            raise AgentConversionRuntimeError(
                "conversion worker did not runtime-verify ONNX"
            )
        manifest_path = job_dir / "artifacts" / "manifest.json"
        if not manifest_path.is_file():
            raise AgentConversionRuntimeError(
                "conversion worker produced no manifest.json"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AgentConversionRuntimeError(
                "conversion manifest is unreadable"
            ) from error
        if (
            not isinstance(manifest, Mapping)
            or str(manifest.get("status") or "") != "runtime_verified"
            or manifest.get("runtime_verified") is not True
            or str((manifest.get("target") or {}).get("kind") or "") != "onnx"
        ):
            raise AgentConversionRuntimeError(
                "conversion manifest is not a runtime-verified ONNX result"
            )
        candidates = sorted(
            (
                path
                for path in (job_dir / "artifacts").glob("*.onnx")
                if path.is_file() and not path.is_symlink() and path.stat().st_size > 0
            ),
            key=lambda path: path.name,
        )
        if len(candidates) != 1:
            raise AgentConversionRuntimeError(
                "conversion worker must produce exactly one ONNX artifact"
            )
        return candidates[0]

    def run(self, lease: RemoteExecutionLease) -> AgentConversionOutcome:
        if not self._recover_persisted_processes():
            raise RemoteExecutionFenced(
                self._recovery_error
                or "stale conversion process cleanup could not be verified"
            )
        if self._shutdown_event.is_set():
            raise RemoteExecutionFenced("Agent process shutdown requested")
        if lease.kind != "MODEL_CONVERSION":
            raise AgentConversionRuntimeError(
                "AgentConversionRunner only accepts MODEL_CONVERSION"
            )
        payload = lease.payload
        if (
            int(payload.get("schema_version") or 0) != 1
            or str(payload.get("task_kind") or "") != "MODEL_CONVERSION"
            or str(payload.get("transport") or "") != "object-storage-v1"
            or str(payload.get("target") or "").strip().lower() != "onnx"
        ):
            raise AgentConversionRuntimeError(
                "portable conversion start payload is invalid"
            )
        source = payload.get("source")
        if (
            not isinstance(source, Mapping)
            or str(source.get("type") or "") != "object"
            or not isinstance(source.get("download"), Mapping)
        ):
            raise AgentConversionRuntimeError(
                "portable conversion source download is missing"
            )
        output = payload.get("output")
        if (
            not isinstance(output, Mapping)
            or str(output.get("type") or "") != "object"
            or str(output.get("upload_protocol") or "")
            != "prepare-after-local-hash-v1"
            or not isinstance(output.get("storage_ref"), Mapping)
        ):
            raise AgentConversionRuntimeError(
                "portable conversion output contract is invalid"
            )

        workdir = self.workdirs.prepare(lease)
        monitor = ExecutionLeaseMonitor(
            self.client,
            lease,
            interval=self.heartbeat_interval,
            on_fenced=lambda: self._terminate_active(strict=False),
        )
        monitor.start()
        log_offset = 0
        try:
            download = source["download"]
            source_name = _safe_filename(download.get("file_name"), "source.pt")
            suffix = Path(source_name).suffix.lower()
            if suffix not in _SUPPORTED_SOURCE_SUFFIXES:
                raise AgentConversionRuntimeError(
                    f"portable ONNX conversion does not support source format {suffix or '<none>'}"
                )
            self._heartbeat(
                monitor,
                progress=4,
                stage="REMOTE_CONVERSION_DOWNLOADING_SOURCE",
                current_item=source_name,
            )
            source_path = self._download(
                download,
                workdir / "input" / source_name,
                monitor,
            )
            job_dir, job_file, command = self._prepare_job(
                lease,
                payload,
                workdir,
                source_path,
            )
            runtime_log = workdir / "runtime.log"
            self._append_log(
                lease,
                f"[agent] starting ONNX conversion generation={lease.generation}\n",
            )
            self._heartbeat(
                monitor,
                progress=15,
                stage="REMOTE_CONVERSION_STARTING_WORKER",
                current_item=source_name,
            )
            with runtime_log.open("ab") as log:
                launched = launch_process(
                    command,
                    cwd=self.runtime_root,
                    env={
                        **os.environ,
                        "PYTHONUTF8": "1",
                        "PYTHONIOENCODING": "utf-8",
                    },
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                self._set_active_process(lease, launched.identity)
                try:
                    self.workdirs.persist_process_identity(
                        lease,
                        launched.identity,
                    )
                except (OSError, ValueError) as error:
                    self.controller.terminate_tree(
                        launched.identity,
                        timeout=8.0,
                    )
                    self._clear_active_process()
                    raise RemoteExecutionFenced(
                        "conversion process identity could not be persisted"
                    ) from error
                try:
                    while launched.process.poll() is None:
                        self._assert_active(monitor)
                        job = self._read_job(job_file)
                        try:
                            worker_progress = float(job.get("progress") or 0)
                        except (TypeError, ValueError):
                            worker_progress = 0.0
                        progress = 15 + max(0.0, min(100.0, worker_progress)) * 0.65
                        self._heartbeat(
                            monitor,
                            progress=progress,
                            stage="REMOTE_CONVERSION_RUNNING",
                            current_item=str(job.get("stage") or source_name),
                        )
                        log_offset = self._forward_log_delta(
                            lease,
                            runtime_log,
                            log_offset,
                        )
                        time.sleep(self.process_poll_interval)
                except (InterruptedError, RemoteExecutionFenced):
                    self._terminate_active(strict=True)
                    raise
                finally:
                    if launched.process.poll() is not None:
                        try:
                            self.workdirs.clear_process_identity(lease)
                        except (OSError, ValueError) as error:
                            self._recovery_error = (
                                "conversion process identity cleanup could not be persisted: "
                                f"{type(error).__name__}: {error}"
                            )
                            raise RemoteExecutionFenced(
                                self._recovery_error
                            ) from error
                        self._clear_active_process()

            self._assert_active(monitor)
            log_offset = self._forward_log_delta(
                lease,
                runtime_log,
                log_offset,
            )
            convert_log = job_dir / "convert.log"
            self._forward_log_delta(lease, convert_log, 0)
            if launched.process.returncode != 0:
                tail = runtime_log.read_text(
                    encoding="utf-8",
                    errors="ignore",
                )[-4000:]
                raise AgentConversionRuntimeError(
                    tail
                    or f"conversion worker exited with code {launched.process.returncode}"
                )
            job = self._read_job(job_file)
            output_path = self._verified_onnx(job_dir, job)

            self._heartbeat(
                monitor,
                progress=83,
                stage="REMOTE_CONVERSION_VERIFYING_RESULT",
                current_item=output_path.name,
            )
            size_bytes, output_sha = _sha256_file(output_path)
            prepared = self.client.prepare_result_upload(
                lease,
                sha256=output_sha,
                size_bytes=size_bytes,
            )
            if (
                str(prepared.get("sha256") or "") != output_sha
                or int(prepared.get("size_bytes") or 0) != size_bytes
            ):
                raise AgentConversionRuntimeError(
                    "control plane changed conversion result evidence"
                )

            self._heartbeat(
                monitor,
                progress=91,
                stage="REMOTE_CONVERSION_UPLOADING_RESULT",
                current_item=output_path.name,
            )
            if not bool(prepared.get("already_uploaded")):
                upload = prepared.get("upload")
                if not isinstance(upload, Mapping):
                    raise AgentConversionRuntimeError(
                        "control plane returned no conversion result upload contract"
                    )
                try:
                    self._upload_result(
                        upload,
                        output_path,
                        monitor,
                        size_bytes=size_bytes,
                        sha256=output_sha,
                    )
                except AgentConversionRuntimeError:
                    self._assert_active(monitor)
                    recovered = self.client.prepare_result_upload(
                        lease,
                        sha256=output_sha,
                        size_bytes=size_bytes,
                    )
                    if not bool(recovered.get("already_uploaded")):
                        retry = recovered.get("upload")
                        if not isinstance(retry, Mapping):
                            raise
                        self._upload_result(
                            retry,
                            output_path,
                            monitor,
                            size_bytes=size_bytes,
                            sha256=output_sha,
                        )

            self._heartbeat(
                monitor,
                progress=97,
                stage="REMOTE_CONVERSION_CONFIRMING_RESULT",
                current_item=output_path.name,
            )
            confirmed = self.client.confirm_result_upload(
                lease,
                runtime_result={
                    "ok": True,
                    "engine": "onnxruntime",
                    "model": output_path.name,
                    "note": "runtime_verified",
                },
            )
            if not bool(confirmed.get("confirmed")):
                raise AgentConversionRuntimeError(
                    "control plane did not confirm conversion result"
                )
            result_ref = str(confirmed.get("result_ref") or "")
            if not result_ref:
                raise AgentConversionRuntimeError(
                    "confirmed conversion result has no result_ref"
                )

            self.client.begin_finalization(lease)
            finished = self.client.finish(
                lease,
                "SUCCEEDED",
                result_ref=result_ref,
            )
            status = str((finished.get("task") or {}).get("status") or "")
            if status != "SUCCEEDED":
                raise AgentConversionRuntimeError(
                    f"control plane returned unexpected conversion terminal status: {status or '<empty>'}"
                )
            return AgentConversionOutcome(
                lease.task_id,
                lease.generation,
                "SUCCEEDED",
                result_ref=result_ref,
            )
        except InterruptedError as error:
            self._terminate_active(strict=True)
            self._append_log(
                lease,
                f"[agent] conversion cancelled: {error}\n",
            )
            self._finish_best_effort(
                lease,
                "CANCELLED",
                error=str(error),
            )
            return AgentConversionOutcome(
                lease.task_id,
                lease.generation,
                "CANCELLED",
                error=str(error),
            )
        except RemoteExecutionFenced:
            self._terminate_active(strict=True)
            raise
        except Exception as error:
            self._terminate_active(strict=True)
            try:
                self._assert_active(monitor)
            except InterruptedError as cancelled:
                message = str(cancelled)
                self._append_log(
                    lease,
                    f"[agent] conversion cancelled: {message}\n",
                )
                self._finish_best_effort(
                    lease,
                    "CANCELLED",
                    error=message,
                )
                return AgentConversionOutcome(
                    lease.task_id,
                    lease.generation,
                    "CANCELLED",
                    error=message,
                )
            except RemoteExecutionFenced:
                raise
            message = f"{type(error).__name__}: {error}"
            self._append_log(
                lease,
                f"[agent] conversion failed: {message}\n",
            )
            finished = self._finish_best_effort(
                lease,
                "FAILED",
                error=message,
            )
            if finished is None:
                raise RemoteExecutionFenced(
                    "could not publish FAILED terminal state for current conversion execution"
                ) from error
            return AgentConversionOutcome(
                lease.task_id,
                lease.generation,
                "FAILED",
                error=message,
            )
        finally:
            monitor.stop()
            _lease, identity = self._active_process()
            if identity is None:
                self.workdirs.cleanup(lease)


__all__ = [
    "AgentConversionOutcome",
    "AgentConversionRunner",
    "AgentConversionRuntimeError",
]
