"""Lease-fenced, content-addressed mother-model installation on an Agent.

No user-controlled target paths, shell commands, SQLite, unpickling or OSS
credentials. A successful receipt attests only to bytes and SHA256, never to
the model being runnable in the node's Python environment.
"""
from __future__ import annotations

import hashlib
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path

from .node_agent_executor_runtime import ExecutionLeaseMonitor, RemoteExecutionFenced


_ASSET = re.compile(r"^pt_[0-9a-f]{24}$")
_SHA = re.compile(r"^[0-9a-f]{64}$")
_CHUNK = 1024 * 1024
_MAX_BYTES = 1024 * 1024 * 1024


@dataclass(frozen=True)
class AgentModelInstallOutcome:
    status: str
    error: str = ""


class AgentModelInstallRunner:
    """Install to a node-local admin-configured directory, never one from HTTP."""

    def __init__(self, client, *, install_dir: str | Path, heartbeat_interval: float = 5.0):
        self.client = client
        self.install_dir = Path(install_dir).expanduser() if str(install_dir).strip() else None
        self.heartbeat_interval = max(1.0, float(heartbeat_interval))
        self._shutdown = threading.Event()
        self.recovery_error = "MODEL_INSTALL_DIRECTORY_NOT_CONFIGURED"
        self.ready = False
        if self.install_dir is not None:
            try:
                path = self.install_dir.resolve(strict=True)
                self.ready = (self.install_dir.is_dir() and not self.install_dir.is_symlink()
                              and os.access(path, os.W_OK))
                if self.ready:
                    self.install_dir = path
                    self.recovery_error = ""
                else:
                    self.recovery_error = "MODEL_INSTALL_DIRECTORY_NOT_WRITABLE"
            except (OSError, RuntimeError):
                self.recovery_error = "MODEL_INSTALL_DIRECTORY_NOT_AVAILABLE"

    def request_shutdown(self) -> None:
        self._shutdown.set()

    def _assert_active(self, monitor: ExecutionLeaseMonitor) -> None:
        if self._shutdown.is_set():
            raise RemoteExecutionFenced("Agent shutdown requested")
        monitor.assert_active()

    @staticmethod
    def _evidence(payload):
        if (payload.get("schema_version") != 1 or payload.get("task_kind") != "MODEL_INSTALL"
                or payload.get("transport") != "agent-artifact-v1"
                or not _ASSET.fullmatch(str(payload.get("asset_id") or ""))
                or not _SHA.fullmatch(str(payload.get("sha256") or ""))
                or type(payload.get("size_bytes")) is not int
                or not 1024 <= payload["size_bytes"] <= _MAX_BYTES):
            raise ValueError("MODEL_INSTALL_CONTRACT_INVALID")
        return str(payload["asset_id"]), str(payload["sha256"]), int(payload["size_bytes"])

    def run(self, lease):
        if not self.ready or self.install_dir is None or lease.kind != "MODEL_INSTALL":
            raise ValueError("MODEL_INSTALL_NOT_AVAILABLE")
        asset_id, sha, size = self._evidence(lease.payload)
        destination = self.install_dir / f"managed-{sha}.pt"
        temporary = self.install_dir / f".managed-{sha}.{lease.generation}.{lease.task_id}.part"
        monitor = ExecutionLeaseMonitor(self.client, lease, interval=self.heartbeat_interval)
        monitor.start()
        try:
            self._assert_active(monitor)
            monitor.beat(progress=3, stage="MODEL_INSTALL_PREPARING")
            if destination.is_symlink():
                raise ValueError("MODEL_INSTALL_SYMLINK_FORBIDDEN")
            existing_valid = False
            if destination.exists():
                if not destination.is_file() or destination.stat().st_size != size:
                    raise ValueError("MODEL_INSTALL_DESTINATION_CONFLICT")
                digest = hashlib.sha256()
                with destination.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(_CHUNK), b""):
                        self._assert_active(monitor)
                        digest.update(chunk)
                if digest.hexdigest() != sha:
                    raise ValueError("MODEL_INSTALL_DESTINATION_CONFLICT")
                existing_valid = True
            if not existing_valid:
                if temporary.exists() or temporary.is_symlink():
                    if temporary.is_symlink() or not temporary.is_file():
                        raise ValueError("MODEL_INSTALL_TEMPORARY_CONFLICT")
                    temporary.unlink()  # exact task-owned stale partial file
                response = self.client.open_model_install_source(lease)
                try:
                    if (str(response.headers.get("X-Content-SHA256") or "") != sha
                            or str(response.headers.get("Content-Length") or "") != str(size)):
                        raise ValueError("MODEL_INSTALL_SOURCE_HEADERS_CHANGED")
                    digest = hashlib.sha256()
                    total = 0
                    with temporary.open("xb") as output:
                        for chunk in response.iter_content(chunk_size=_CHUNK):
                            self._assert_active(monitor)
                            if not chunk:
                                continue
                            total += len(chunk)
                            if total > size:
                                raise ValueError("MODEL_INSTALL_SOURCE_OVERSIZE")
                            digest.update(chunk)
                            output.write(chunk)
                        output.flush()
                        os.fsync(output.fileno())
                    if total != size or digest.hexdigest() != sha:
                        raise ValueError("MODEL_INSTALL_HASH_MISMATCH")
                finally:
                    response.close()
                self._assert_active(monitor)
                monitor.beat(progress=92, stage="MODEL_INSTALL_VALIDATING")
                if destination.exists() or destination.is_symlink():
                    raise ValueError("MODEL_INSTALL_DESTINATION_CONFLICT")
                os.replace(temporary, destination)
            self._assert_active(monitor)
            receipt = {"asset_id": asset_id, "sha256": sha,
                       "size_bytes": size, "path": str(destination)}
            confirmed = self.client.confirm_model_install(lease, receipt)
            if confirmed.get("accepted") is not True:
                raise ValueError("MODEL_INSTALL_RECEIPT_REJECTED")
            monitor.beat(progress=100, stage="MODEL_INSTALL_FINISHING")
            self._assert_active(monitor)
            self.client.begin_finalization(lease)
            self.client.finish(lease, "SUCCEEDED")
            return AgentModelInstallOutcome("SUCCEEDED")
        except InterruptedError:
            self.client.finish(lease, "CANCELLED", error="model installation cancelled")
            return AgentModelInstallOutcome("CANCELLED")
        except RemoteExecutionFenced:
            raise
        except Exception as error:
            message = f"{type(error).__name__}: {error}"[:1500]
            try:
                self.client.finish(lease, "FAILED", error=message)
            except Exception:
                pass
            return AgentModelInstallOutcome("FAILED", message)
        finally:
            monitor.stop()
            if temporary.exists() and not temporary.is_symlink():
                temporary.unlink(missing_ok=True)
