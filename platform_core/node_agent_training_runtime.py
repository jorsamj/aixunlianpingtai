"""Agent-side portable Ultralytics TRAINING runner.

The runner is deliberately database-free. It consumes only the fenced HTTP
execution lease payload, task-local files and short-lived object-storage URLs.
It reuses the platform's train_worker.py so local and remote training share one
training implementation and one artifact-verification contract.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
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
from .remote_training_results import create_training_result_archive
from .remote_training_transport import (
    RemoteTrainingTransportError,
    extract_training_bundle_archive,
)
from .resource_discovery import OFFICIAL_DOWNLOADABLE_MODELS
from .task_runtime.process_control import (
    ProcessController,
    ProcessIdentity,
    launch_process,
)
from .training_devices import normalize_training_device


_TRANSFER_CHUNK_BYTES = 1024 * 1024
_MAX_REMOTE_LOG_FORWARD_BYTES = 60 * 1024
_MAX_PROGRESS_HEARTBEAT_SECONDS = 1.0
_SHA256 = re.compile(r"^[0-9a-f]{64}$")


class AgentTrainingRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentTrainingOutcome:
    task_id: str
    generation: int
    status: str
    result_ref: str = ""
    error: str = ""


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
                    raise AgentTrainingRuntimeError(
                        "training result changed while uploading"
                    )
                yield chunk
        if sent != self.size_bytes:
            raise AgentTrainingRuntimeError(
                "training result size changed while uploading"
            )


def _absolute_http_url(value: object, field: str) -> str:
    url = str(value or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentTrainingRuntimeError(f"{field} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise AgentTrainingRuntimeError(f"{field} must not contain userinfo")
    return url


def _safe_filename(value: object, fallback: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raw = fallback
    if (
        "/" in raw
        or "\\" in raw
        or raw in {".", ".."}
        or Path(raw).name != raw
    ):
        raise AgentTrainingRuntimeError("portable file_name must be a basename")
    return raw[:240]


def _expected_evidence(contract: Mapping[str, Any]) -> tuple[int, str]:
    try:
        size = int(contract.get("size_bytes"))
    except (TypeError, ValueError) as error:
        raise AgentTrainingRuntimeError("download size_bytes is invalid") from error
    digest = str(contract.get("sha256") or "").strip().lower()
    if size <= 0 or not _SHA256.fullmatch(digest):
        raise AgentTrainingRuntimeError("download content evidence is incomplete")
    return size, digest


def _sha256_file(path: Path) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(_TRANSFER_CHUNK_BYTES), b""):
            size += len(chunk)
            digest.update(chunk)
    return size, digest.hexdigest()


def _read_json(path: Path, default: Any) -> Any:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default
    return value


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
    )
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as stream:
            descriptor = -1
            json.dump(dict(value), stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary.unlink(missing_ok=True)


def _primitive(value: object, default: Any) -> Any:
    return value if value is None or isinstance(value, (str, int, float, bool)) else default


class AgentTrainingRunner:
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

    def _active_process(
        self,
    ) -> tuple[RemoteExecutionLease | None, ProcessIdentity | None]:
        with self._identity_lock:
            return self._active_lease, self._active_identity

    def _recover_persisted_processes(self) -> bool:
        try:
            records = self.workdirs.list_process_identities()
        except (OSError, ValueError) as error:
            self._recovery_error = (
                f"persisted training process identity is unsafe or unreadable: {error}"
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
                    "stale training process cleanup could not be verified: "
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
                    "stale training process identity cleanup could not be persisted: "
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
            if strict:
                raise RemoteExecutionFenced(
                    "training process cleanup could not be verified: "
                    f"{type(error).__name__}: {error}"
                ) from error
            return False
        if lease is not None:
            try:
                self.workdirs.clear_process_identity(lease)
            except (OSError, ValueError) as error:
                if strict:
                    raise RemoteExecutionFenced(
                        "training process identity cleanup could not be persisted: "
                        f"{type(error).__name__}: {error}"
                    ) from error
                return False
        self._clear_active_process()
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
            encoded = encoded[-_MAX_REMOTE_LOG_FORWARD_BYTES:]
            value = encoded.decode("utf-8", errors="replace")
        try:
            self.client.append_log(lease, value)
        except Exception:
            # Execution ownership is fenced by heartbeat, not log delivery.
            pass

    def _forward_log_delta(
        self,
        lease: RemoteExecutionLease,
        path: Path,
        offset: int,
        *,
        max_chunks: int = 4,
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
                for _ in range(max(1, int(max_chunks))):
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
            raise AgentTrainingRuntimeError("portable download method must be GET")
        url = _absolute_http_url(contract.get("url"), "download.url")
        headers = contract.get("headers")
        if headers is None:
            headers = {}
        if not isinstance(headers, Mapping):
            raise AgentTrainingRuntimeError("download headers must be an object")
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
            raise AgentTrainingRuntimeError(
                f"portable download failed: {type(error).__name__}: {error}"
            ) from error
        try:
            if not (200 <= int(response.status_code) < 300):
                raise AgentTrainingRuntimeError(
                    f"portable download returned HTTP {response.status_code}"
                )
            digest = hashlib.sha256()
            written = 0
            with temporary.open("xb") as stream:
                for chunk in response.iter_content(chunk_size=_TRANSFER_CHUNK_BYTES):
                    self._assert_active(monitor)
                    if not chunk:
                        continue
                    written += len(chunk)
                    if written > expected_size:
                        raise AgentTrainingRuntimeError(
                            "download exceeded expected size"
                        )
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if written != expected_size:
                raise AgentTrainingRuntimeError(
                    "download size does not match durable evidence"
                )
            if digest.hexdigest() != expected_sha:
                raise AgentTrainingRuntimeError(
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

    def _model_argument(
        self,
        payload: Mapping[str, Any],
        workdir: Path,
        monitor: ExecutionLeaseMonitor,
    ) -> str:
        model = payload.get("model")
        if not isinstance(model, Mapping):
            raise AgentTrainingRuntimeError(
                "portable training model contract is missing"
            )
        model_type = str(model.get("type") or "").strip()
        if model_type == "official":
            reference = str(model.get("reference") or "").strip()
            canonical = next(
                (
                    item
                    for item in OFFICIAL_DOWNLOADABLE_MODELS
                    if str(item).casefold() == reference.casefold()
                ),
                None,
            )
            if (
                canonical is None
                or Path(reference).is_absolute()
                or "/" in reference
                or "\\" in reference
            ):
                raise AgentTrainingRuntimeError(
                    "official training model reference is not allow-listed"
                )
            return str(canonical)
        if model_type != "object":
            raise AgentTrainingRuntimeError(
                "portable training model type is unsupported"
            )
        download = model.get("download")
        if not isinstance(download, Mapping):
            raise AgentTrainingRuntimeError(
                "portable training model download contract is missing"
            )
        file_name = _safe_filename(download.get("file_name"), "base-model.pt")
        if Path(file_name).suffix.lower() != ".pt":
            raise AgentTrainingRuntimeError(
                "portable Ultralytics base model must be a .pt file"
            )
        return str(
            self._download(
                download,
                workdir / "model" / file_name,
                monitor,
            )
        )

    @staticmethod
    def _parameter(payload: Mapping[str, Any], key: str, default: Any) -> Any:
        params = payload.get("params")
        if not isinstance(params, Mapping):
            return default
        return _primitive(params.get(key), default)

    def _prepare_project(
        self,
        lease: RemoteExecutionLease,
        payload: Mapping[str, Any],
        workdir: Path,
        *,
        data_yaml: Path,
        model_argument: str,
    ) -> tuple[Path, Path, Path, list[str]]:
        if not self.ultralytics_python.is_file():
            raise AgentTrainingRuntimeError(
                "node-local Ultralytics Python runtime is unavailable"
            )
        worker = (self.runtime_root / "train_worker.py").resolve()
        if (
            not worker.is_file()
            or worker.is_symlink()
            or worker.parent != self.runtime_root
        ):
            raise AgentTrainingRuntimeError(
                "node-local train_worker.py is unavailable"
            )

        selected_device = normalize_training_device(
            payload.get("selected_device") or ""
        )
        requested_device = normalize_training_device(
            payload.get("requested_device") or "auto"
        )
        if selected_device == "auto":
            raise AgentTrainingRuntimeError(
                "remote training requires a concrete selected device"
            )
        if requested_device != "auto" and requested_device != selected_device:
            raise AgentTrainingRuntimeError(
                "remote training requested/selected device mismatch"
            )

        project = (workdir / "project").resolve()
        job_dir = project / "jobs" / lease.task_id
        for directory in (
            project,
            job_dir,
            project / "models",
            project / "runs",
        ):
            directory.mkdir(parents=True, exist_ok=True)

        selected_gpu = payload.get("selected_gpu")
        gpu = dict(selected_gpu) if isinstance(selected_gpu, Mapping) else {}
        if selected_device.startswith("cuda:") and not gpu:
            raise AgentTrainingRuntimeError(
                "CUDA training assignment is missing selected GPU evidence"
            )
        if gpu and str(gpu.get("id") or "") not in {"", selected_device}:
            raise AgentTrainingRuntimeError(
                "selected GPU identity does not match selected device"
            )

        download = ((payload.get("bundle") or {}).get("download"))
        dataset_bytes = 0
        if isinstance(download, Mapping):
            try:
                dataset_bytes = max(
                    0,
                    int(download.get("uncompressed_size_bytes") or 0),
                )
            except (TypeError, ValueError):
                dataset_bytes = 0
        resource_context = {
            "concurrent_reservations": 1,
            "dataset_bytes": dataset_bytes,
            "decoded_dataset_bytes": None,
            "remote_cache_ready": True,
            "gpu_uuid": str(gpu.get("uuid") or "") or None,
            "gpu_name": str(gpu.get("name") or "") or None,
            "gpu_index": gpu.get("index"),
            "gpu_free_bytes": int(gpu.get("memory_free_bytes") or 0),
            "gpu_total_bytes": int(gpu.get("memory_total_bytes") or 0),
        }
        resource_context_path = job_dir / "resource-context.json"
        _atomic_write_json(resource_context_path, resource_context)

        epochs = max(1, int(self._parameter(payload, "epochs", 30)))
        imgsz = max(128, int(self._parameter(payload, "imgsz", 640)))
        batch = int(self._parameter(payload, "batch", 4))
        workers = max(0, int(self._parameter(payload, "workers", 0)))
        run_name = f"remote_{lease.task_id}_{lease.generation}"
        if (
            bool(self._parameter(payload, "auto_supplement", False))
            or int(self._parameter(payload, "supplement_count", 0) or 0) > 0
            or bool(self._parameter(payload, "ai_intervention_enabled", False))
        ):
            raise AgentTrainingRuntimeError(
                "remote training auto-supplement/AI intervention is not portable yet"
            )

        _atomic_write_json(
            job_dir / "job.json",
            {
                "id": lease.task_id,
                "status": "running",
                "target": "remote",
                "framework": "ultralytics",
                "algorithm_id": str(payload.get("algorithm_id") or ""),
                "snapshot_id": str(payload.get("snapshot_id") or ""),
                "execution_generation": int(lease.generation),
                "requested_device": requested_device,
                "assigned_device": selected_device,
                "selected_gpu": gpu,
                "total_epochs": epochs,
                "progress_percent": 0,
                "message": "Agent 已接收远程训练任务",
            },
        )

        command = [
            str(self.ultralytics_python),
            str(worker),
            "--project-dir",
            str(project),
            "--data",
            str(data_yaml),
            "--model",
            str(model_argument),
            "--epochs",
            str(epochs),
            "--imgsz",
            str(imgsz),
            "--batch",
            str(batch),
            "--device",
            selected_device,
            "--assigned-device",
            selected_device,
            "--requested-device",
            requested_device,
            "--job-id",
            lease.task_id,
            "--run-name",
            run_name,
            "--patience",
            str(max(0, int(self._parameter(payload, "patience", 100)))),
            "--workers",
            str(workers),
            "--optimizer",
            str(self._parameter(payload, "optimizer", "auto") or "auto"),
            "--lr0",
            str(float(self._parameter(payload, "lr0", 0.01))),
            "--lrf",
            str(float(self._parameter(payload, "lrf", 0.01))),
            "--weight-decay",
            str(float(self._parameter(payload, "weight_decay", 0.0005))),
            "--close-mosaic",
            str(max(0, int(self._parameter(payload, "close_mosaic", 10)))),
            "--mosaic",
            str(float(self._parameter(payload, "mosaic", 1.0))),
            "--cache",
            str(self._parameter(payload, "cache", False)),
            "--resource-strategy",
            str(self._parameter(payload, "resource_strategy", "auto") or "auto"),
            "--resource-context",
            str(resource_context_path),
            "--resource-resolution",
            str(job_dir / "resolved-resources.json"),
            "--metrics-db",
            str(job_dir / "training-metrics.sqlite3"),
            "--single-cls",
            str(bool(self._parameter(payload, "single_cls", False))).lower(),
            "--pretrained",
            str(bool(self._parameter(payload, "pretrained", True))).lower(),
            "--rect",
            str(bool(self._parameter(payload, "rect", False))).lower(),
            "--amp",
            str(bool(self._parameter(payload, "amp", True))).lower(),
            "--cos-lr",
            str(bool(self._parameter(payload, "cos_lr", False))).lower(),
            "--freeze",
            str(max(0, int(self._parameter(payload, "freeze", 0)))),
            "--momentum",
            str(float(self._parameter(payload, "momentum", 0.937))),
            "--warmup-epochs",
            str(float(self._parameter(payload, "warmup_epochs", 3.0))),
            "--save-period",
            str(int(self._parameter(payload, "save_period", -1))),
            "--seed",
            str(int(self._parameter(payload, "seed", 0))),
            "--deterministic",
            str(bool(self._parameter(payload, "deterministic", True))).lower(),
            "--multi-scale",
            str(float(self._parameter(payload, "multi_scale", 0.0))),
            "--hsv-h",
            str(float(self._parameter(payload, "hsv_h", 0.015))),
            "--hsv-s",
            str(float(self._parameter(payload, "hsv_s", 0.7))),
            "--hsv-v",
            str(float(self._parameter(payload, "hsv_v", 0.4))),
            "--degrees",
            str(float(self._parameter(payload, "degrees", 0.0))),
            "--translate",
            str(float(self._parameter(payload, "translate", 0.1))),
            "--scale",
            str(float(self._parameter(payload, "scale", 0.5))),
            "--shear",
            str(float(self._parameter(payload, "shear", 0.0))),
            "--perspective",
            str(float(self._parameter(payload, "perspective", 0.0))),
            "--flipud",
            str(float(self._parameter(payload, "flipud", 0.0))),
            "--fliplr",
            str(float(self._parameter(payload, "fliplr", 0.5))),
            "--mixup",
            str(float(self._parameter(payload, "mixup", 0.0))),
            "--val-max-samples",
            str(max(0, int(self._parameter(payload, "val_max_samples", 0)))),
            "--eval-interval",
            str(max(0, int(self._parameter(payload, "eval_interval", 0)))),
            "--eval-metric",
            str(self._parameter(payload, "eval_metric", "map50") or "map50"),
            "--continue-threshold",
            str(float(self._parameter(payload, "continue_threshold", 0.0))),
            "--stop-threshold",
            str(float(self._parameter(payload, "stop_threshold", 0.0))),
            # Supplemental material/AI configuration is control-plane state and
            # is not portable yet. Never fake it on an Agent.
            "--auto-supplement",
            "false",
            "--supplement-count",
            "0",
            "--ai-intervention",
            "false",
        ]
        return project, job_dir / "job.json", worker, command

    def _upload_result(
        self,
        upload: Mapping[str, Any],
        result_path: Path,
        monitor: ExecutionLeaseMonitor,
        *,
        size_bytes: int,
        sha256: str,
    ) -> None:
        if str(upload.get("method") or "").upper() != "PUT":
            raise AgentTrainingRuntimeError(
                "portable training result upload method must be PUT"
            )
        url = _absolute_http_url(upload.get("url"), "upload.url")
        headers = upload.get("headers")
        if not isinstance(headers, Mapping):
            raise AgentTrainingRuntimeError(
                "training result upload headers must be an object"
            )
        normalized_headers = {
            str(key): str(value)
            for key, value in headers.items()
        }
        lowered = {
            key.lower(): value
            for key, value in normalized_headers.items()
        }
        if lowered.get("content-length") != str(int(size_bytes)):
            raise AgentTrainingRuntimeError(
                "training result upload contract does not bind Content-Length"
            )
        metadata_hashes = {
            lowered.get("x-amz-meta-sha256"),
            lowered.get("x-oss-meta-sha256"),
        }
        if sha256 not in metadata_hashes:
            raise AgentTrainingRuntimeError(
                "training result upload contract does not bind sha256 metadata"
            )
        if (
            lowered.get("if-none-match") != "*"
            and lowered.get("x-oss-forbid-overwrite", "").lower() != "true"
        ):
            raise AgentTrainingRuntimeError(
                "training result upload contract does not prevent overwrite"
            )

        body = _MonitoredUploadBody(
            result_path,
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
            raise AgentTrainingRuntimeError(
                f"portable training result upload failed: "
                f"{type(error).__name__}: {error}"
            ) from error
        try:
            if not (200 <= int(response.status_code) < 300):
                raise AgentTrainingRuntimeError(
                    f"portable training result upload returned HTTP "
                    f"{response.status_code}"
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

    def _runtime_result(self, job: Mapping[str, Any]) -> dict[str, Any]:
        keys = (
            "training_outcome",
            "completion_reason",
            "early_stopping_reason",
            "early_stopping_patience",
            "best_epoch",
            "completed_epochs",
            "requested_epochs",
            "requested_device",
            "assigned_device",
            "actual_device",
            "progress_percent",
            "finished_at",
        )
        return {
            key: job.get(key)
            for key in keys
            if job.get(key) is not None
        }

    def run(self, lease: RemoteExecutionLease) -> AgentTrainingOutcome:
        if not self._recover_persisted_processes():
            raise RemoteExecutionFenced(
                self._recovery_error
                or "stale training process cleanup could not be verified"
            )
        if self._shutdown_event.is_set():
            raise RemoteExecutionFenced("Agent process shutdown requested")
        if lease.kind != "TRAINING":
            raise AgentTrainingRuntimeError(
                "AgentTrainingRunner only accepts TRAINING"
            )
        payload = lease.payload
        if (
            int(payload.get("schema_version") or 0) != 1
            or str(payload.get("task_kind") or "") != "TRAINING"
            or str(payload.get("transport") or "") != "object-storage-v1"
            or str(payload.get("framework") or "") != "ultralytics"
        ):
            raise AgentTrainingRuntimeError(
                "portable training start payload is invalid"
            )
        snapshot_id = str(payload.get("snapshot_id") or "").strip()
        if not snapshot_id:
            raise AgentTrainingRuntimeError(
                "portable training snapshot identity is missing"
            )

        workdir = self.workdirs.prepare(lease)
        monitor = ExecutionLeaseMonitor(
            self.client,
            lease,
            interval=self.heartbeat_interval,
            on_fenced=self._terminate_active,
        )
        monitor.start()
        log_offset = 0
        try:
            self._heartbeat(
                monitor,
                progress=2,
                stage="REMOTE_TRAINING_DOWNLOADING_BUNDLE",
            )
            bundle = payload.get("bundle")
            if (
                not isinstance(bundle, Mapping)
                or str(bundle.get("type") or "") != "object"
                or not isinstance(bundle.get("download"), Mapping)
            ):
                raise AgentTrainingRuntimeError(
                    "portable training bundle download is missing"
                )
            bundle_download = bundle["download"]
            archive = self._download(
                bundle_download,
                workdir / "input" / "training-bundle.zip",
                monitor,
            )

            self._heartbeat(
                monitor,
                progress=7,
                stage="REMOTE_TRAINING_VERIFYING_BUNDLE",
            )
            try:
                verified_bundle = extract_training_bundle_archive(
                    archive,
                    workdir / "input" / "bundle",
                    bundle_download,
                )
            except RemoteTrainingTransportError as error:
                raise AgentTrainingRuntimeError(
                    f"{error.code}: {error}"
                ) from error
            if verified_bundle.snapshot_id != snapshot_id:
                raise AgentTrainingRuntimeError(
                    "portable training bundle snapshot changed"
                )

            self._heartbeat(
                monitor,
                progress=12,
                stage="REMOTE_TRAINING_PREPARING_MODEL",
            )
            model_argument = self._model_argument(
                payload,
                workdir,
                monitor,
            )
            project, job_file, _worker, command = self._prepare_project(
                lease,
                payload,
                workdir,
                data_yaml=verified_bundle.data_yaml,
                model_argument=model_argument,
            )

            runtime_log = workdir / "runtime.log"
            self._append_log(
                lease,
                f"[agent] starting training worker "
                f"generation={lease.generation} snapshot={snapshot_id}\n",
            )
            self._heartbeat(
                monitor,
                progress=15,
                stage="REMOTE_TRAINING_STARTING_WORKER",
            )

            env = {
                **os.environ,
                "PYTHONUTF8": "1",
                "PYTHONIOENCODING": "utf-8",
            }
            with runtime_log.open("ab") as log:
                launched = launch_process(
                    command,
                    cwd=self.runtime_root,
                    env=env,
                    stdout=log,
                    stderr=subprocess.STDOUT,
                )
                self._set_active_process(lease, launched.identity)
                try:
                    self.workdirs.persist_process_identity(
                        lease,
                        launched.identity,
                    )
                except Exception:
                    # A launched process without durable exact identity would
                    # be unrecoverable after an Agent crash. Kill it before
                    # allowing execution to continue.
                    self._terminate_active(strict=True)
                    raise
                next_projection = 0.0
                try:
                    while launched.process.poll() is None:
                        self._assert_active(monitor)
                        now = time.monotonic()
                        if now >= next_projection:
                            job = _read_json(job_file, {})
                            raw_progress = float(
                                job.get("progress_percent") or 0.0
                            ) if isinstance(job, Mapping) else 0.0
                            progress = 15.0 + (
                                max(0.0, min(100.0, raw_progress)) * 0.67
                            )
                            stage = (
                                str(job.get("startup_stage") or "")
                                if isinstance(job, Mapping)
                                else ""
                            ) or "REMOTE_TRAINING_RUNNING"
                            current_item = (
                                str(
                                    job.get("current_item")
                                    or job.get("message")
                                    or ""
                                )
                                if isinstance(job, Mapping)
                                else ""
                            )
                            self._heartbeat(
                                monitor,
                                progress=progress,
                                stage=stage,
                                current_item=current_item,
                            )
                            log_offset = self._forward_log_delta(
                                lease,
                                runtime_log,
                                log_offset,
                            )
                            next_projection = now + _MAX_PROGRESS_HEARTBEAT_SECONDS
                        time.sleep(self.process_poll_interval)
                except (InterruptedError, RemoteExecutionFenced):
                    self._terminate_active(strict=True)
                    raise

            # Even a normally exited training leader may have left DataLoader
            # descendants behind. Exact process-group cleanup must be proven
            # before any model/result publication or terminal task mutation.
            self._terminate_active(strict=True)
            self._assert_active(monitor)
            log_offset = self._forward_log_delta(
                lease,
                runtime_log,
                log_offset,
                max_chunks=16,
            )
            job = _read_json(job_file, {})
            if not isinstance(job, Mapping):
                raise AgentTrainingRuntimeError(
                    "training worker produced no durable job result"
                )
            if launched.process.returncode != 0:
                error = str(job.get("message") or "").strip()
                if not error:
                    try:
                        error = runtime_log.read_text(
                            encoding="utf-8",
                            errors="replace",
                        )[-6000:]
                    except OSError:
                        error = ""
                raise AgentTrainingRuntimeError(
                    error
                    or f"training worker exited with code "
                    f"{launched.process.returncode}"
                )
            if (
                str(job.get("status") or "").lower() != "done"
                or job.get("artifact_verified") is not True
            ):
                raise AgentTrainingRuntimeError(
                    "training worker did not produce verified model artifacts"
                )

            self._heartbeat(
                monitor,
                progress=84,
                stage="REMOTE_TRAINING_PREPARING_MODEL_ARTIFACTS",
            )
            verified_source_paths = set()
            for value in job.get("verified_models") or ():
                if isinstance(value, Mapping):
                    value = (
                        value.get("path")
                        or value.get("stored_path")
                        or value.get("source")
                    )
                raw = str(value or "").strip()
                if raw:
                    verified_source_paths.add(str(Path(raw).expanduser().resolve()))

            publish_paths: list[str] = []
            role_paths: dict[str, Path] = {}
            for role, key in (("best", "best_path"), ("last", "last_path")):
                raw = str(job.get(key) or "").strip()
                if not raw:
                    continue
                path = Path(raw).expanduser().resolve()
                if (
                    str(path) not in verified_source_paths
                    or not path.is_file()
                    or path.stat().st_size <= 0
                ):
                    raise AgentTrainingRuntimeError(
                        f"training worker {role} model is not in verified_models"
                    )
                if str(path) not in publish_paths:
                    publish_paths.append(str(path))
                role_paths[role] = path
            if not publish_paths:
                raise AgentTrainingRuntimeError(
                    "training worker produced no verified best/last model"
                )

            publish_job = dict(job)
            publish_job["verified_models"] = publish_paths
            result_archive = create_training_result_archive(
                project_dir=project,
                job=publish_job,
                task_id=lease.task_id,
                execution_generation=lease.generation,
                snapshot_id=snapshot_id,
                destination=workdir / "output" / "training-result.zip",
                include_model_bytes=False,
            )
            model_evidence: list[dict[str, Any]] = []
            local_model_by_role: dict[str, Path] = {}
            for item in result_archive.models:
                role = str(item.get("role") or "").strip().lower()
                source = role_paths.get(role)
                if source is None:
                    raise AgentTrainingRuntimeError(
                        f"training result declared unexpected model role {role or '<empty>'}"
                    )
                size_bytes, digest = _sha256_file(source)
                if (
                    int(item.get("size_bytes") or 0) != size_bytes
                    or str(item.get("sha256") or "") != digest
                ):
                    raise AgentTrainingRuntimeError(
                        f"training {role} model changed before publication"
                    )
                evidence = {
                    "role": role,
                    "file_name": str(item.get("file_name") or f"{role}.pt"),
                    "sha256": digest,
                    "size_bytes": size_bytes,
                }
                model_evidence.append(evidence)
                local_model_by_role[role] = source

            self._assert_active(monitor)
            prepared_models = self.client.prepare_training_model_uploads(
                lease,
                model_evidence,
            )
            prepared_items = prepared_models.get("items")
            if not isinstance(prepared_items, list) or len(prepared_items) != len(model_evidence):
                raise AgentTrainingRuntimeError(
                    "control plane returned invalid training model upload contracts"
                )
            prepared_by_role = {
                str(item.get("role") or "").strip().lower(): item
                for item in prepared_items
                if isinstance(item, Mapping)
            }
            if set(prepared_by_role) != set(local_model_by_role):
                raise AgentTrainingRuntimeError(
                    "control plane changed training model roles"
                )

            self._heartbeat(
                monitor,
                progress=88,
                stage="REMOTE_TRAINING_UPLOADING_MODELS",
            )
            for evidence in model_evidence:
                role = str(evidence["role"])
                prepared_item = prepared_by_role[role]
                if (
                    str(prepared_item.get("sha256") or "") != str(evidence["sha256"])
                    or int(prepared_item.get("size_bytes") or 0) != int(evidence["size_bytes"])
                    or str(prepared_item.get("file_name") or "") != str(evidence["file_name"])
                ):
                    raise AgentTrainingRuntimeError(
                        f"control plane changed {role} model evidence"
                    )
                if bool(prepared_item.get("already_uploaded")):
                    continue
                upload = prepared_item.get("upload")
                if not isinstance(upload, Mapping):
                    raise AgentTrainingRuntimeError(
                        f"control plane returned no {role} model upload contract"
                    )
                try:
                    self._upload_result(
                        upload,
                        local_model_by_role[role],
                        monitor,
                        size_bytes=int(evidence["size_bytes"]),
                        sha256=str(evidence["sha256"]),
                    )
                except AgentTrainingRuntimeError:
                    self._assert_active(monitor)
                    recovered = self.client.prepare_training_model_uploads(
                        lease,
                        model_evidence,
                    )
                    retry_items = recovered.get("items")
                    retry_by_role = {
                        str(item.get("role") or "").strip().lower(): item
                        for item in retry_items or ()
                        if isinstance(item, Mapping)
                    }
                    retry_item = retry_by_role.get(role)
                    if retry_item is None:
                        raise
                    if not bool(retry_item.get("already_uploaded")):
                        retry_upload = retry_item.get("upload")
                        if not isinstance(retry_upload, Mapping):
                            raise
                        self._upload_result(
                            retry_upload,
                            local_model_by_role[role],
                            monitor,
                            size_bytes=int(evidence["size_bytes"]),
                            sha256=str(evidence["sha256"]),
                        )

            confirmed_models = self.client.confirm_training_model_uploads(lease)
            if not bool(confirmed_models.get("confirmed")):
                raise AgentTrainingRuntimeError(
                    "control plane did not confirm training model artifacts"
                )

            self._heartbeat(
                monitor,
                progress=92,
                stage="REMOTE_TRAINING_UPLOADING_RESULT_MANIFEST",
            )
            result_contract = payload.get("result")
            if (
                not isinstance(result_contract, Mapping)
                or str(result_contract.get("type") or "") != "object"
                or str(result_contract.get("upload_protocol") or "")
                != "prepare-after-local-hash-v1"
            ):
                raise AgentTrainingRuntimeError(
                    "portable training result contract is invalid"
                )
            prepared = self.client.prepare_result_upload(
                lease,
                sha256=result_archive.sha256,
                size_bytes=result_archive.size_bytes,
            )
            if (
                str(prepared.get("sha256") or "")
                != result_archive.sha256
                or int(prepared.get("size_bytes") or 0)
                != result_archive.size_bytes
            ):
                raise AgentTrainingRuntimeError(
                    "control plane changed training result content evidence"
                )
            if not bool(prepared.get("already_uploaded")):
                upload = prepared.get("upload")
                if not isinstance(upload, Mapping):
                    raise AgentTrainingRuntimeError(
                        "control plane returned no training result upload contract"
                    )
                try:
                    self._upload_result(
                        upload,
                        result_archive.path,
                        monitor,
                        size_bytes=result_archive.size_bytes,
                        sha256=result_archive.sha256,
                    )
                except AgentTrainingRuntimeError:
                    self._assert_active(monitor)
                    recovered = self.client.prepare_result_upload(
                        lease,
                        sha256=result_archive.sha256,
                        size_bytes=result_archive.size_bytes,
                    )
                    if not bool(recovered.get("already_uploaded")):
                        retry_upload = recovered.get("upload")
                        if not isinstance(retry_upload, Mapping):
                            raise
                        self._upload_result(
                            retry_upload,
                            result_archive.path,
                            monitor,
                            size_bytes=result_archive.size_bytes,
                            sha256=result_archive.sha256,
                        )

            self._heartbeat(
                monitor,
                progress=97,
                stage="REMOTE_TRAINING_CONFIRMING_RESULT",
            )
            confirmed = self.client.confirm_result_upload(
                lease,
                runtime_result=self._runtime_result(job),
            )
            if not bool(confirmed.get("confirmed")):
                raise AgentTrainingRuntimeError(
                    "control plane did not confirm training result"
                )
            result_ref = str(confirmed.get("result_ref") or "")
            if not result_ref:
                raise AgentTrainingRuntimeError(
                    "confirmed training result has no result_ref"
                )

            # confirm_result_upload already crossed the atomic finalization gate
            # and committed the verified model/version. Keep the explicit call
            # for protocol idempotency and observability.
            self.client.begin_finalization(lease)
            report = job.get("training_report")
            report = report if isinstance(report, Mapping) else {}
            test_result = report.get("test_result")
            partial = (
                isinstance(test_result, Mapping)
                and str(test_result.get("status") or "").strip().lower() == "failed"
            )
            terminal_status = "PARTIAL_SUCCESS" if partial else "SUCCEEDED"
            finished = self.client.finish(
                lease,
                terminal_status,
                result_ref=result_ref,
            )
            status = str((finished.get("task") or {}).get("status") or "")
            if status != terminal_status:
                raise AgentTrainingRuntimeError(
                    "control plane returned unexpected training terminal "
                    f"status: {status or '<empty>'}"
                )
            return AgentTrainingOutcome(
                lease.task_id,
                lease.generation,
                terminal_status,
                result_ref=result_ref,
            )
        except InterruptedError as error:
            self._terminate_active(strict=True)
            self._append_log(
                lease,
                f"[agent] training cancelled: {error}\n",
            )
            self._finish_best_effort(
                lease,
                "CANCELLED",
                error=str(error),
            )
            return AgentTrainingOutcome(
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
                    f"[agent] training cancelled: {message}\n",
                )
                self._finish_best_effort(
                    lease,
                    "CANCELLED",
                    error=message,
                )
                return AgentTrainingOutcome(
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
                f"[agent] training failed: {message}\n",
            )
            finished = self._finish_best_effort(
                lease,
                "FAILED",
                error=message,
            )
            if finished is None:
                raise RemoteExecutionFenced(
                    "could not publish FAILED terminal state for current "
                    "training execution"
                ) from error
            return AgentTrainingOutcome(
                lease.task_id,
                lease.generation,
                "FAILED",
                error=message,
            )
        finally:
            monitor.stop()
            _active_lease, active_identity = self._active_process()
            if active_identity is None:
                self.workdirs.cleanup(lease)
            # If exact process cleanup could not be proven, preserve both the
            # in-memory identity and generation workdir for retry/restart
            # recovery. Never erase the only evidence of a possibly live GPU
            # process.


__all__ = [
    "AgentTrainingOutcome",
    "AgentTrainingRunner",
    "AgentTrainingRuntimeError",
]
