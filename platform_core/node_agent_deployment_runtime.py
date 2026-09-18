"""Database-free Agent-side runner for portable DEPLOYMENT_TEST tasks."""
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
from typing import Any, Callable, Mapping
from urllib.parse import urlparse

import requests

from .node_agent_executor_runtime import (
    AgentExecutionWorkdir,
    ExecutionLeaseMonitor,
    NodeExecutorHTTPError,
    RemoteExecutionFenced,
    RemoteExecutionLease,
)
from .resource_discovery import OFFICIAL_DOWNLOADABLE_MODELS
from .task_runtime.process_control import (
    ProcessController,
    ProcessIdentity,
    launch_process,
)


_TRANSFER_CHUNK_BYTES = 1024 * 1024
_MAX_REMOTE_LOG_FORWARD_BYTES = 60 * 1024
_SUPPORTED_ULTRALYTICS_SUFFIXES = {".pt", ".pth", ".onnx", ".engine"}
_SUPPORTED_PADDLE_SUFFIXES = {".pdparams", ".pdmodel", ".pdiparams"}
_BOARD_ONLY_SUFFIXES = {".rknn", ".om", ".bmodel"}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AgentDeploymentRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentDeploymentOutcome:
    task_id: str
    generation: int
    status: str
    result_ref: str = ""
    error: str = ""


def _absolute_http_url(value: object, field: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentDeploymentRuntimeError(f"{field} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise AgentDeploymentRuntimeError(f"{field} must not contain userinfo")
    return url


def _safe_filename(value: object, fallback: str) -> str:
    name = Path(str(value or "")).name
    if not name or name in {".", ".."} or name != str(value or name):
        # Windows separators are not interpreted by PosixPath on Linux.
        raw = str(value or "")
        if "/" in raw or "\\" in raw:
            raise AgentDeploymentRuntimeError("portable file_name must be a basename")
        name = raw or fallback
    if "/" in name or "\\" in name or name in {".", ".."}:
        raise AgentDeploymentRuntimeError("portable file_name must be a basename")
    return name[:240] or fallback


def _expected_evidence(contract: Mapping[str, Any]) -> tuple[int, str]:
    try:
        size = int(contract.get("size_bytes"))
    except (TypeError, ValueError) as error:
        raise AgentDeploymentRuntimeError("download size_bytes is invalid") from error
    digest = str(contract.get("sha256") or "").strip().lower()
    if size <= 0 or not _SHA256.fullmatch(digest):
        raise AgentDeploymentRuntimeError("download content evidence is incomplete")
    return size, digest


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_TRANSFER_CHUNK_BYTES), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _last_json_line(text: str) -> dict[str, Any]:
    for line in reversed(str(text or "").splitlines()):
        value = line.strip()
        if not (value.startswith("{") and value.endswith("}")):
            continue
        try:
            body = json.loads(value)
        except json.JSONDecodeError:
            continue
        if isinstance(body, dict):
            return body
    raise AgentDeploymentRuntimeError("deployment runner returned no structured JSON result")


class _MonitoredUploadBody:
    def __init__(
        self,
        path: Path,
        assert_active: Callable[[], None],
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
                    raise AgentDeploymentRuntimeError("result file changed while uploading")
                yield chunk
        if sent != self.size_bytes:
            raise AgentDeploymentRuntimeError("result file size changed while uploading")


class AgentDeploymentRunner:
    def __init__(
        self,
        client,
        workdirs: AgentExecutionWorkdir,
        *,
        runtime_root: str | Path,
        transfer_session: requests.Session | None = None,
        python_by_framework: Mapping[str, str | Path] | None = None,
        heartbeat_interval: float = 5.0,
        transfer_timeout: float = 120.0,
        process_poll_interval: float = 0.2,
    ) -> None:
        self.client = client
        self.workdirs = workdirs
        self.runtime_root = Path(runtime_root).expanduser().resolve()
        self.transfer_session = transfer_session or requests.Session()
        defaults = {
            "ultralytics": str(Path(sys.executable).resolve()),
            "paddle": str(Path(sys.executable).resolve()),
        }
        defaults.update({
            str(key).strip().lower(): str(Path(value).expanduser().resolve())
            for key, value in dict(python_by_framework or {}).items()
        })
        self.python_by_framework = defaults
        self.heartbeat_interval = max(1.0, float(heartbeat_interval))
        self.transfer_timeout = max(5.0, float(transfer_timeout))
        self.process_poll_interval = max(0.05, float(process_poll_interval))
        self.controller = ProcessController()
        self._identity_lock = threading.Lock()
        self._active_identity: ProcessIdentity | None = None
        self._shutdown_event = threading.Event()

    def _terminate_active(self) -> None:
        with self._identity_lock:
            identity = self._active_identity
        if identity is None:
            return
        try:
            self.controller.terminate_tree(identity, timeout=5.0)
        except (ProcessLookupError, PermissionError):
            # A missing process is already stopped. Permission/identity failures
            # are surfaced by the execution monitor or the main runner path.
            return

    def _set_identity(self, identity: ProcessIdentity | None) -> None:
        with self._identity_lock:
            self._active_identity = identity

    def request_shutdown(self) -> None:
        """Stop local work without publishing a false terminal task state."""
        self._shutdown_event.set()
        self._terminate_active()

    def _assert_active(self, monitor: ExecutionLeaseMonitor) -> None:
        if self._shutdown_event.is_set():
            raise RemoteExecutionFenced("Agent process shutdown requested")
        self._assert_active(monitor)

    def _heartbeat(
        self,
        monitor: ExecutionLeaseMonitor,
        *,
        progress: float,
        stage: str,
        current_item: str = "",
    ) -> None:
        monitor.beat(
            progress=progress,
            stage=stage,
            current_item=current_item or None,
        )
        self._assert_active(monitor)

    def _download(
        self,
        contract: Mapping[str, Any],
        destination: Path,
        monitor: ExecutionLeaseMonitor,
    ) -> Path:
        method = str(contract.get("method") or "GET").upper()
        if method != "GET":
            raise AgentDeploymentRuntimeError("portable download method must be GET")
        url = _absolute_http_url(contract.get("url"), "download.url")
        headers = contract.get("headers")
        if headers is None:
            headers = {}
        if not isinstance(headers, Mapping):
            raise AgentDeploymentRuntimeError("download headers must be an object")
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
            raise AgentDeploymentRuntimeError(
                f"portable download failed: {type(error).__name__}: {error}"
            ) from error
        if not (200 <= int(response.status_code) < 300):
            raise AgentDeploymentRuntimeError(
                f"portable download returned HTTP {response.status_code}"
            )
        header_size = str(getattr(response, "headers", {}).get("Content-Length") or "").strip()
        if header_size:
            try:
                if int(header_size) != expected_size:
                    raise AgentDeploymentRuntimeError("download Content-Length does not match durable evidence")
            except ValueError as error:
                raise AgentDeploymentRuntimeError("download Content-Length is invalid") from error

        digest = hashlib.sha256()
        written = 0
        try:
            with temporary.open("wb") as stream:
                for chunk in response.iter_content(chunk_size=_TRANSFER_CHUNK_BYTES):
                    self._assert_active(monitor)
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > expected_size:
                        raise AgentDeploymentRuntimeError("download exceeded expected size")
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if written != expected_size:
                raise AgentDeploymentRuntimeError("download size does not match durable evidence")
            if digest.hexdigest() != expected_sha:
                raise AgentDeploymentRuntimeError("download sha256 does not match durable evidence")
            os.replace(temporary, destination)
            return destination
        finally:
            temporary.unlink(missing_ok=True)
            try:
                response.close()
            except Exception:
                pass

    def _model_argument(
        self,
        payload: Mapping[str, Any],
        workdir: Path,
        monitor: ExecutionLeaseMonitor,
    ) -> str:
        model = payload.get("model")
        if not isinstance(model, Mapping):
            raise AgentDeploymentRuntimeError("portable deployment model contract is missing")
        model_type = str(model.get("type") or "")
        if model_type == "official":
            reference = str(model.get("reference") or "").strip()
            if (
                not reference
                or "/" in reference
                or "\\" in reference
                or reference.casefold() not in OFFICIAL_DOWNLOADABLE_MODELS
            ):
                raise AgentDeploymentRuntimeError("official model reference is not allow-listed")
            return reference
        if model_type != "object":
            raise AgentDeploymentRuntimeError("portable deployment model type is unsupported")
        download = model.get("download")
        if not isinstance(download, Mapping):
            raise AgentDeploymentRuntimeError("portable model download contract is missing")
        file_name = _safe_filename(download.get("file_name"), "model.bin")
        return str(self._download(download, workdir / "model" / file_name, monitor))

    def _runner_command(
        self,
        payload: Mapping[str, Any],
        *,
        model_argument: str,
        input_path: Path,
        output_path: Path,
    ) -> list[str]:
        framework = str(payload.get("framework") or "ultralytics").strip().lower()
        if framework not in {"ultralytics", "paddle"}:
            raise AgentDeploymentRuntimeError(f"unsupported deployment framework: {framework}")
        python_path = Path(self.python_by_framework.get(framework) or "").expanduser().resolve()
        if not python_path.is_file():
            raise AgentDeploymentRuntimeError(f"node-local {framework} Python runtime is unavailable")

        runner_name = "predict_paddle_runner.py" if framework == "paddle" else "predict_ultralytics_runner.py"
        runner = (self.runtime_root / runner_name).resolve()
        if (
            not runner.is_file()
            or runner.is_symlink()
            or runner.parent != self.runtime_root
        ):
            raise AgentDeploymentRuntimeError(f"node-local deployment runner is unavailable: {runner_name}")

        suffix = Path(model_argument).suffix.lower()
        if suffix in _BOARD_ONLY_SUFFIXES:
            raise AgentDeploymentRuntimeError(f"portable deployment runner does not support board-only format {suffix}")
        supported = _SUPPORTED_PADDLE_SUFFIXES if framework == "paddle" else _SUPPORTED_ULTRALYTICS_SUFFIXES
        if suffix not in supported:
            raise AgentDeploymentRuntimeError(f"{framework} runner does not support model format {suffix or '<none>'}")

        try:
            confidence = float(payload.get("confidence") or 0.25)
        except (TypeError, ValueError) as error:
            raise AgentDeploymentRuntimeError("deployment confidence is invalid") from error
        confidence = max(0.0, min(1.0, confidence))
        command = [
            str(python_path),
            str(runner),
            "--model",
            model_argument,
            "--input",
            str(input_path),
            "--output",
            str(output_path),
            "--conf",
            str(confidence),
        ]
        selected_device = str(payload.get("selected_device") or "").strip()
        if framework == "ultralytics" and selected_device:
            command.extend(["--device", selected_device])
        return command

    def _upload_result(
        self,
        upload: Mapping[str, Any],
        output_path: Path,
        monitor: ExecutionLeaseMonitor,
        *,
        size_bytes: int,
        sha256: str,
    ) -> None:
        if str(upload.get("method") or "").upper() != "PUT":
            raise AgentDeploymentRuntimeError("portable result upload method must be PUT")
        url = _absolute_http_url(upload.get("url"), "upload.url")
        headers = upload.get("headers")
        if not isinstance(headers, Mapping):
            raise AgentDeploymentRuntimeError("result upload headers must be an object")
        normalized_headers = {str(key): str(value) for key, value in headers.items()}
        lowered = {key.lower(): value for key, value in normalized_headers.items()}
        if lowered.get("content-length") != str(int(size_bytes)):
            raise AgentDeploymentRuntimeError("result upload contract does not bind Content-Length")
        metadata_hashes = {
            lowered.get("x-amz-meta-sha256"),
            lowered.get("x-oss-meta-sha256"),
        }
        if sha256 not in metadata_hashes:
            raise AgentDeploymentRuntimeError("result upload contract does not bind sha256 metadata")
        if (
            lowered.get("if-none-match") != "*"
            and lowered.get("x-oss-forbid-overwrite", "").lower() != "true"
        ):
            raise AgentDeploymentRuntimeError("result upload contract does not prevent overwrite")

        body = _MonitoredUploadBody(
            output_path,
            lambda: self._assert_active(monitor),
            size_bytes,
        )
        try:
            response = self.transfer_session.put(
                url,
                headers=normalized_headers,
                data=body,
                timeout=self.transfer_timeout,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise AgentDeploymentRuntimeError(
                f"portable result upload failed: {type(error).__name__}: {error}"
            ) from error
        try:
            if not (200 <= int(response.status_code) < 300):
                raise AgentDeploymentRuntimeError(
                    f"portable result upload returned HTTP {response.status_code}"
                )
        finally:
            try:
                response.close()
            except Exception:
                pass

    def _append_log(self, lease: RemoteExecutionLease, text: str) -> None:
        value = str(text or "")
        if not value:
            return
        encoded = value.encode("utf-8", errors="replace")
        if len(encoded) > _MAX_REMOTE_LOG_FORWARD_BYTES:
            encoded = encoded[-_MAX_REMOTE_LOG_FORWARD_BYTES:]
            value = encoded.decode("utf-8", errors="replace")
        try:
            self.client.append_log(lease, value)
        except Exception:
            # Heartbeat is the execution-ownership channel. Logging must never
            # block process cleanup or turn a successful inference into a retry.
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

    def run(self, lease: RemoteExecutionLease) -> AgentDeploymentOutcome:
        if self._shutdown_event.is_set():
            raise RemoteExecutionFenced("Agent process shutdown requested")
        if lease.kind != "DEPLOYMENT_TEST":
            raise AgentDeploymentRuntimeError("AgentDeploymentRunner only accepts DEPLOYMENT_TEST")
        payload = lease.payload
        if (
            int(payload.get("schema_version") or 0) != 1
            or str(payload.get("task_kind") or "") != "DEPLOYMENT_TEST"
            or str(payload.get("transport") or "") != "object-storage-v1"
        ):
            raise AgentDeploymentRuntimeError("portable deployment start payload is invalid")

        workdir = self.workdirs.prepare(lease)
        monitor = ExecutionLeaseMonitor(
            self.client,
            lease,
            interval=self.heartbeat_interval,
            on_fenced=self._terminate_active,
        )
        monitor.start()
        try:
            self._heartbeat(monitor, progress=3, stage="REMOTE_DOWNLOADING_INPUT")
            input_contract = payload.get("input")
            if not isinstance(input_contract, Mapping) or str(input_contract.get("type") or "") != "object":
                raise AgentDeploymentRuntimeError("portable deployment input contract is missing")
            download = input_contract.get("download")
            if not isinstance(download, Mapping):
                raise AgentDeploymentRuntimeError("portable deployment input download is missing")
            input_name = _safe_filename(download.get("file_name"), "input.bin")
            input_path = self._download(download, workdir / "input" / input_name, monitor)

            self._heartbeat(
                monitor,
                progress=20,
                stage="REMOTE_PREPARING_MODEL",
                current_item=input_name,
            )
            model_argument = self._model_argument(payload, workdir, monitor)

            output_contract = payload.get("output")
            if (
                not isinstance(output_contract, Mapping)
                or str(output_contract.get("type") or "") != "object"
                or str(output_contract.get("upload_protocol") or "") != "prepare-after-local-hash-v1"
            ):
                raise AgentDeploymentRuntimeError("portable deployment output contract is invalid")
            storage_ref = output_contract.get("storage_ref")
            if not isinstance(storage_ref, Mapping):
                raise AgentDeploymentRuntimeError("portable deployment output storage ref is missing")
            output_name = _safe_filename(storage_ref.get("file_name"), "result.jpg")
            output_path = workdir / "output" / output_name
            output_path.parent.mkdir(parents=True, exist_ok=True)

            command = self._runner_command(
                payload,
                model_argument=model_argument,
                input_path=input_path,
                output_path=output_path,
            )
            runtime_log = workdir / "runtime.log"
            self._append_log(lease, f"[agent] starting deployment runner generation={lease.generation}\n")
            self._heartbeat(
                monitor,
                progress=35,
                stage="REMOTE_LOADING_RUNTIME",
                current_item=input_name,
            )
            started_at = time.perf_counter()
            with runtime_log.open("w", encoding="utf-8", errors="ignore") as log:
                launched = launch_process(
                    command,
                    cwd=self.runtime_root,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="ignore",
                )
                self._set_identity(launched.identity)
                try:
                    while launched.process.poll() is None:
                        self._assert_active(monitor)
                        time.sleep(self.process_poll_interval)
                except (InterruptedError, RemoteExecutionFenced):
                    self.controller.terminate_tree(launched.identity, timeout=5.0)
                    raise
                finally:
                    self._set_identity(None)

            self._assert_active(monitor)
            runtime_text = runtime_log.read_text(encoding="utf-8", errors="ignore")
            self._append_log(lease, runtime_text)
            if launched.process.returncode != 0:
                raise AgentDeploymentRuntimeError(
                    runtime_text[-4000:] or f"deployment runner exited with code {launched.process.returncode}"
                )
            runtime_result = _last_json_line(runtime_text)
            if runtime_result.get("ok") is False:
                raise AgentDeploymentRuntimeError("deployment runner reported failure")
            if not output_path.is_file() or output_path.stat().st_size <= 0:
                raise AgentDeploymentRuntimeError("deployment runner produced no result image")
            runtime_result["total_elapsed_ms"] = round(
                (time.perf_counter() - started_at) * 1000,
                2,
            )

            self._heartbeat(
                monitor,
                progress=82,
                stage="REMOTE_VERIFYING_RESULT",
                current_item=output_name,
            )
            size_bytes, output_sha = _sha256_file(output_path)
            self._assert_active(monitor)
            prepared = self.client.prepare_result_upload(
                lease,
                sha256=output_sha,
                size_bytes=size_bytes,
            )
            if (
                str(prepared.get("sha256") or "") != output_sha
                or int(prepared.get("size_bytes") or 0) != size_bytes
            ):
                raise AgentDeploymentRuntimeError("control plane changed result content evidence")

            self._heartbeat(
                monitor,
                progress=90,
                stage="REMOTE_UPLOADING_RESULT",
                current_item=output_name,
            )
            if not bool(prepared.get("already_uploaded")):
                upload = prepared.get("upload")
                if not isinstance(upload, Mapping):
                    raise AgentDeploymentRuntimeError("control plane returned no result upload contract")
                try:
                    self._upload_result(
                        upload,
                        output_path,
                        monitor,
                        size_bytes=size_bytes,
                        sha256=output_sha,
                    )
                except AgentDeploymentRuntimeError:
                    self._assert_active(monitor)
                    # If the PUT response was lost after the object was accepted,
                    # prepare is idempotent. If the old signature merely expired,
                    # the same evidence may receive one fresh upload contract.
                    recovered = self.client.prepare_result_upload(
                        lease,
                        sha256=output_sha,
                        size_bytes=size_bytes,
                    )
                    if not bool(recovered.get("already_uploaded")):
                        retry_upload = recovered.get("upload")
                        if not isinstance(retry_upload, Mapping):
                            raise
                        self._upload_result(
                            retry_upload,
                            output_path,
                            monitor,
                            size_bytes=size_bytes,
                            sha256=output_sha,
                        )

            self._assert_active(monitor)
            confirmed = self.client.confirm_result_upload(
                lease,
                runtime_result=runtime_result,
            )
            if not bool(confirmed.get("confirmed")):
                raise AgentDeploymentRuntimeError("control plane did not confirm remote result")
            result_ref = str(confirmed.get("result_ref") or "")
            if not result_ref:
                raise AgentDeploymentRuntimeError("confirmed remote result has no result_ref")

            # confirm_result_upload already passed the control-plane atomic
            # cancellation-vs-finalization gate. begin_finalization remains an
            # idempotent protocol check for compatibility and observability.
            self.client.begin_finalization(lease)
            finished = self.client.finish(
                lease,
                "SUCCEEDED",
                result_ref=result_ref,
            )
            status = str((finished.get("task") or {}).get("status") or "")
            if status != "SUCCEEDED":
                raise AgentDeploymentRuntimeError(
                    f"control plane returned unexpected terminal status: {status or '<empty>'}"
                )
            return AgentDeploymentOutcome(
                lease.task_id,
                lease.generation,
                "SUCCEEDED",
                result_ref=result_ref,
            )
        except InterruptedError as error:
            self._terminate_active()
            self._append_log(lease, f"[agent] deployment cancelled: {error}\n")
            self._finish_best_effort(lease, "CANCELLED", error=str(error))
            return AgentDeploymentOutcome(
                lease.task_id,
                lease.generation,
                "CANCELLED",
                error=str(error),
            )
        except RemoteExecutionFenced:
            self._terminate_active()
            raise
        except Exception as error:
            self._terminate_active()
            try:
                self._assert_active(monitor)
            except InterruptedError as cancelled:
                message = str(cancelled)
                self._append_log(lease, f"[agent] deployment cancelled: {message}\n")
                self._finish_best_effort(lease, "CANCELLED", error=message)
                return AgentDeploymentOutcome(
                    lease.task_id,
                    lease.generation,
                    "CANCELLED",
                    error=message,
                )
            except RemoteExecutionFenced:
                raise

            message = f"{type(error).__name__}: {error}"
            self._append_log(lease, f"[agent] deployment failed: {message}\n")
            finished = self._finish_best_effort(lease, "FAILED", error=message)
            if finished is None:
                raise RemoteExecutionFenced(
                    "could not publish FAILED terminal state for current execution"
                ) from error
            return AgentDeploymentOutcome(
                lease.task_id,
                lease.generation,
                "FAILED",
                error=message,
            )
        finally:
            monitor.stop()
            self._set_identity(None)
            self.workdirs.cleanup(lease)


__all__ = [
    "AgentDeploymentOutcome",
    "AgentDeploymentRunner",
    "AgentDeploymentRuntimeError",
]
