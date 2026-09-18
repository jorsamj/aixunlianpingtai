"""Agent-side portable MATERIAL_IMPORT ZIP review runtime."""
from __future__ import annotations

import hashlib
import os
import tempfile
import threading
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
from .remote_material_import import (
    build_material_review_archive,
    build_storage_scan_material_review_archive,
    build_yolo_material_review_archive,
)
from .storage.models import ObjectMetadata, StorageType
from .storage.zip_import import (
    ExtractionCancelled,
    ServerZipImportError,
    extract_server_zip,
    finalize_server_zip_publication,
)


_TRANSFER_CHUNK_BYTES = 1024 * 1024
_MAX_STORAGE_SCAN_OBJECTS = 250_000


class AgentMaterialImportRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True)
class AgentMaterialImportOutcome:
    task_id: str
    status: str
    result_ref: str | None = None
    error: str = ""


def _absolute_http_url(value: object, field: str) -> str:
    raw = str(value or "").strip()
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise AgentMaterialImportRuntimeError(f"{field} must be an absolute http(s) URL")
    if parsed.username or parsed.password:
        raise AgentMaterialImportRuntimeError(f"{field} must not contain userinfo")
    return raw


def _expected_evidence(contract: Mapping[str, Any]) -> tuple[int, str]:
    try:
        size = int(contract.get("size_bytes") or 0)
    except (TypeError, ValueError) as error:
        raise AgentMaterialImportRuntimeError("portable object size is invalid") from error
    digest = str(contract.get("sha256") or "").strip().lower()
    if (
        size <= 0
        or len(digest) != 64
        or any(char not in "0123456789abcdef" for char in digest)
    ):
        raise AgentMaterialImportRuntimeError("portable object evidence is incomplete")
    return size, digest


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
                    raise AgentMaterialImportRuntimeError(
                        "material review changed while uploading"
                    )
                yield chunk
        if sent != self.size_bytes:
            raise AgentMaterialImportRuntimeError(
                "material review size changed while uploading"
            )



class _BrokeredMaterialProvider:
    """Read-only object-store view backed by execution-fenced control-plane APIs."""

    def __init__(
        self,
        client,
        lease: RemoteExecutionLease,
        monitor: ExecutionLeaseMonitor,
        session: requests.Session,
        *,
        source: Mapping[str, Any],
        timeout: float,
    ) -> None:
        self.client = client
        self.lease = lease
        self.monitor = monitor
        self.session = session
        self.timeout = max(30.0, float(timeout))
        self.source_id = str(source.get("storage_source_id") or "").strip()
        try:
            self.storage_type = StorageType.parse(source.get("storage_type"))
        except ValueError as error:
            raise AgentMaterialImportRuntimeError(
                "brokered storage_scan source type is invalid"
            ) from error
        self.scope_prefix = str(source.get("prefix") or "").replace("\\", "/").strip("/")
        self.scope_recursive = bool(source.get("recursive", True))
        if not self.source_id or not self.scope_prefix:
            raise AgentMaterialImportRuntimeError(
                "brokered storage_scan source identity is incomplete"
            )
        self._listed: dict[str, ObjectMetadata] = {}
        self._listed_count = 0

    @staticmethod
    def _etag(value: object) -> str:
        return str(value or "").strip().strip('"')

    def _in_scope(self, key: str) -> bool:
        return key == self.scope_prefix or key.startswith(self.scope_prefix + "/")

    @staticmethod
    def _matches_request(key: str, prefix: str, recursive: bool) -> bool:
        requested = str(prefix or "").replace("\\", "/").strip("/")
        if requested and not (key == requested or key.startswith(requested + "/")):
            return False
        if not recursive and requested:
            relative = key[len(requested):].lstrip("/")
            return "/" not in relative
        return True

    def iter_objects(self, prefix: str = "", *, recursive: bool = True):
        requested = str(prefix or "").replace("\\", "/").strip("/")
        if requested and not self._in_scope(requested):
            raise AgentMaterialImportRuntimeError(
                "storage_scan requested a prefix outside the durable task scope"
            )
        cursor = None
        seen_cursors: set[str] = set()
        while True:
            self.monitor.assert_active()
            page = self.client.material_scan_page(
                self.lease,
                cursor=cursor,
                limit=100,
            )
            items = page.get("items")
            if not isinstance(items, list):
                raise AgentMaterialImportRuntimeError(
                    "material scan broker returned invalid items"
                )
            for raw in items:
                if not isinstance(raw, Mapping):
                    raise AgentMaterialImportRuntimeError(
                        "material scan broker returned an invalid object"
                    )
                key = str(raw.get("key") or "").replace("\\", "/").lstrip("/")
                if not self._in_scope(key):
                    raise AgentMaterialImportRuntimeError(
                        "material scan broker returned an out-of-scope object"
                    )
                if key not in self._listed:
                    self._listed_count += 1
                    if self._listed_count > _MAX_STORAGE_SCAN_OBJECTS:
                        raise AgentMaterialImportRuntimeError(
                            "material scan exceeds the 250000 object safety limit"
                        )
                metadata = ObjectMetadata(
                    key=key,
                    size_bytes=max(0, int(raw.get("size_bytes") or 0)),
                    etag=str(raw.get("etag") or ""),
                    content_type=str(raw.get("content_type") or "application/octet-stream"),
                    sha256=str(raw.get("sha256") or "").strip().lower(),
                    last_modified=str(raw.get("last_modified") or ""),
                )
                self._listed[key] = metadata
                if self._matches_request(key, requested, bool(recursive)):
                    yield metadata
            next_cursor = str(page.get("next_cursor") or "")
            if not next_cursor:
                return
            if next_cursor in seen_cursors:
                raise AgentMaterialImportRuntimeError(
                    "material scan broker returned a repeated cursor"
                )
            seen_cursors.add(next_cursor)
            cursor = next_cursor

    def exists(self, object_key: str) -> bool:
        key = str(object_key or "").replace("\\", "/").lstrip("/")
        if not self._in_scope(key):
            return False
        if key in self._listed:
            return True
        try:
            self.client.material_scan_read(self.lease, key)
            return True
        except NodeExecutorHTTPError as error:
            if error.status_code == 404:
                return False
            raise

    def open_reader(self, object_key: str):
        key = str(object_key or "").replace("\\", "/").lstrip("/")
        if not self._in_scope(key):
            raise AgentMaterialImportRuntimeError(
                "brokered material read escaped the durable scan prefix"
            )
        self.monitor.assert_active()
        contract = self.client.material_scan_read(self.lease, key)
        if str(contract.get("method") or "GET").upper() != "GET":
            raise AgentMaterialImportRuntimeError(
                "brokered material read method must be GET"
            )
        if str(contract.get("key") or "") != key:
            raise AgentMaterialImportRuntimeError(
                "brokered material read contract changed object identity"
            )
        url = _absolute_http_url(contract.get("url"), "material_scan.read.url")
        try:
            expected_size = int(contract.get("size_bytes"))
        except (TypeError, ValueError) as error:
            raise AgentMaterialImportRuntimeError(
                "brokered material read size is invalid"
            ) from error
        if expected_size < 0:
            raise AgentMaterialImportRuntimeError(
                "brokered material read size cannot be negative"
            )
        expected_etag = self._etag(contract.get("etag"))
        if not expected_etag:
            raise AgentMaterialImportRuntimeError(
                "brokered material read ETag evidence is missing"
            )
        expected_sha = str(contract.get("sha256") or "").strip().lower()
        if expected_sha and (
            len(expected_sha) != 64
            or any(char not in "0123456789abcdef" for char in expected_sha)
        ):
            raise AgentMaterialImportRuntimeError(
                "brokered material read SHA256 evidence is invalid"
            )
        listed = self._listed.get(key)
        if listed is not None and (
            int(listed.size_bytes) != expected_size
            or self._etag(listed.etag) != expected_etag
        ):
            raise AgentMaterialImportRuntimeError(
                "storage object changed between listing and signed read"
            )
        headers = contract.get("headers") or {}
        if not isinstance(headers, Mapping):
            raise AgentMaterialImportRuntimeError(
                "brokered material read headers must be an object"
            )
        try:
            response = self.session.get(
                url,
                headers={str(name): str(value) for name, value in headers.items()},
                stream=True,
                timeout=self.timeout,
                allow_redirects=False,
            )
        except requests.RequestException as error:
            raise AgentMaterialImportRuntimeError(
                f"brokered material read failed: {type(error).__name__}: {error}"
            ) from error
        spool = tempfile.SpooledTemporaryFile(max_size=8 * 1024 * 1024, mode="w+b")
        try:
            if not (200 <= int(response.status_code) < 300):
                raise AgentMaterialImportRuntimeError(
                    f"brokered material read returned HTTP {response.status_code}"
                )
            header_size = str(
                getattr(response, "headers", {}).get("Content-Length") or ""
            ).strip()
            if header_size and int(header_size) != expected_size:
                raise AgentMaterialImportRuntimeError(
                    "brokered material Content-Length changed after stat"
                )
            response_etag = self._etag(
                getattr(response, "headers", {}).get("ETag")
            )
            if not response_etag or response_etag != expected_etag:
                raise AgentMaterialImportRuntimeError(
                    "brokered material ETag changed during read"
                )
            digest = hashlib.sha256()
            written = 0
            for chunk in response.iter_content(chunk_size=_TRANSFER_CHUNK_BYTES):
                self.monitor.assert_active()
                if not chunk:
                    continue
                written += len(chunk)
                if written > expected_size:
                    raise AgentMaterialImportRuntimeError(
                        "brokered material read exceeded expected size"
                    )
                digest.update(chunk)
                spool.write(chunk)
            actual_sha = digest.hexdigest()
            if written != expected_size or (
                expected_sha and expected_sha != actual_sha
            ):
                raise AgentMaterialImportRuntimeError(
                    "brokered material bytes changed during read"
                )
            spool.seek(0)
            self._listed[key] = ObjectMetadata(
                key=key,
                size_bytes=written,
                etag=str(contract.get("etag") or ""),
                content_type=str(
                    contract.get("content_type") or "application/octet-stream"
                ),
                sha256=actual_sha,
                last_modified=str(contract.get("last_modified") or ""),
            )
            return spool
        except BaseException:
            spool.close()
            raise
        finally:
            try:
                response.close()
            except Exception:
                pass


class AgentMaterialImportRunner:
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

    @property
    def ready(self) -> bool:
        return True

    @property
    def recovery_error(self) -> str:
        return ""

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
        monitor.beat(
            progress=progress,
            stage=stage,
            current_item=current_item,
        )

    def _download(
        self,
        contract: Mapping[str, Any],
        destination: Path,
        monitor: ExecutionLeaseMonitor,
    ) -> Path:
        if str(contract.get("method") or "GET").upper() != "GET":
            raise AgentMaterialImportRuntimeError("portable material download method must be GET")
        url = _absolute_http_url(contract.get("url"), "input.download.url")
        headers = contract.get("headers") or {}
        if not isinstance(headers, Mapping):
            raise AgentMaterialImportRuntimeError("portable material download headers must be an object")
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
            raise AgentMaterialImportRuntimeError(
                f"material ZIP download failed: {type(error).__name__}: {error}"
            ) from error
        try:
            if not (200 <= int(response.status_code) < 300):
                raise AgentMaterialImportRuntimeError(
                    f"material ZIP download returned HTTP {response.status_code}"
                )
            header_size = str(getattr(response, "headers", {}).get("Content-Length") or "").strip()
            if header_size and int(header_size) != expected_size:
                raise AgentMaterialImportRuntimeError(
                    "material ZIP Content-Length does not match durable evidence"
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
                        raise AgentMaterialImportRuntimeError(
                            "material ZIP download exceeded expected size"
                        )
                    digest.update(chunk)
                    stream.write(chunk)
                stream.flush()
                os.fsync(stream.fileno())
            if written != expected_size or digest.hexdigest() != expected_sha:
                raise AgentMaterialImportRuntimeError(
                    "material ZIP download does not match durable size/SHA256 evidence"
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
            raise AgentMaterialImportRuntimeError("material review upload method must be PUT")
        url = _absolute_http_url(upload.get("url"), "output.upload.url")
        headers = upload.get("headers")
        if not isinstance(headers, Mapping):
            raise AgentMaterialImportRuntimeError("material review upload headers must be an object")
        normalized = {str(key): str(value) for key, value in headers.items()}
        lowered = {key.lower(): value for key, value in normalized.items()}
        if lowered.get("content-length") != str(int(size_bytes)):
            raise AgentMaterialImportRuntimeError(
                "material review upload contract does not bind Content-Length"
            )
        if sha256 not in {
            lowered.get("x-amz-meta-sha256"),
            lowered.get("x-oss-meta-sha256"),
        }:
            raise AgentMaterialImportRuntimeError(
                "material review upload contract does not bind SHA256 metadata"
            )
        if (
            lowered.get("if-none-match") != "*"
            and lowered.get("x-oss-forbid-overwrite", "").lower() != "true"
        ):
            raise AgentMaterialImportRuntimeError(
                "material review upload contract does not prevent overwrite"
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
            raise AgentMaterialImportRuntimeError(
                f"material review upload failed: {type(error).__name__}: {error}"
            ) from error
        try:
            if not (200 <= int(response.status_code) < 300):
                raise AgentMaterialImportRuntimeError(
                    f"material review upload returned HTTP {response.status_code}"
                )
        finally:
            try:
                response.close()
            except Exception:
                pass

    def run(self, lease: RemoteExecutionLease) -> AgentMaterialImportOutcome:
        if self._shutdown_event.is_set():
            raise RemoteExecutionFenced("Agent process shutdown requested")
        if lease.kind != "MATERIAL_IMPORT":
            raise AgentMaterialImportRuntimeError(
                "AgentMaterialImportRunner only accepts MATERIAL_IMPORT"
            )
        payload = lease.payload
        if (
            int(payload.get("schema_version") or 0) != 1
            or str(payload.get("task_kind") or "") != "MATERIAL_IMPORT"
            or str(payload.get("transport") or "") != "object-storage-v1"
            or str(payload.get("mode") or "") not in {"zip_scan", "storage_scan"}
            or str(payload.get("import_format") or "") not in {"images", "yolo"}
        ):
            raise AgentMaterialImportRuntimeError(
                "portable material import start payload is invalid"
            )
        mode = str(payload.get("mode") or "")
        target = payload.get("target")
        input_contract = payload.get("input")
        source_contract = payload.get("source")
        output = payload.get("output")
        if (
            not isinstance(target, Mapping)
            or not isinstance(output, Mapping)
            or str(output.get("type") or "") != "object"
            or str(output.get("upload_protocol") or "") != "prepare-after-local-hash-v1"
            or not isinstance(output.get("storage_ref"), Mapping)
        ):
            raise AgentMaterialImportRuntimeError(
                "portable material import object contracts are incomplete"
            )
        if mode == "zip_scan" and (
            not isinstance(input_contract, Mapping)
            or str(input_contract.get("type") or "") != "object"
            or not isinstance(input_contract.get("download"), Mapping)
        ):
            raise AgentMaterialImportRuntimeError(
                "portable ZIP material input contract is incomplete"
            )
        if mode == "storage_scan" and not isinstance(source_contract, Mapping):
            raise AgentMaterialImportRuntimeError(
                "portable storage_scan source contract is incomplete"
            )

        workdir = self.workdirs.prepare(lease)
        monitor = ExecutionLeaseMonitor(
            self.client,
            lease,
            interval=self.heartbeat_interval,
        )
        monitor.start()
        try:
            broker_provider = None
            source_root = None
            if mode == "storage_scan":
                self._heartbeat(
                    monitor,
                    progress=8,
                    stage="REMOTE_MATERIAL_SCANNING",
                    current_item="扫描对象存储目录",
                )
                broker_provider = _BrokeredMaterialProvider(
                    self.client,
                    lease,
                    monitor,
                    self.transfer_session,
                    source=source_contract,
                    timeout=self.transfer_timeout,
                )
            else:
                self._heartbeat(
                    monitor,
                    progress=3,
                    stage="REMOTE_MATERIAL_DOWNLOADING",
                    current_item="下载素材 ZIP",
                )
                archive = self._download(
                    input_contract["download"],
                    workdir / "input" / "materials.zip",
                    monitor,
                )
                extract_root = workdir / "extracted"
                self._heartbeat(
                    monitor,
                    progress=12,
                    stage="REMOTE_MATERIAL_EXTRACTING",
                    current_item="安全解包素材 ZIP",
                )

                def extraction_progress(value):
                    self._assert_active(monitor)
                    declared = max(1, int(value.declared_bytes or 0))
                    percent = 12 + min(
                        33.0,
                        33.0 * int(value.extracted_bytes or 0) / declared,
                    )
                    monitor.beat(
                        progress=percent,
                        stage="REMOTE_MATERIAL_EXTRACTING",
                        current_item=str(value.current_member or ""),
                    )
                    return True

                try:
                    extract_server_zip(
                        archive,
                        extract_root,
                        "source",
                        task_id=f"material-{lease.generation}",
                        on_progress=extraction_progress,
                    )
                    finalize_server_zip_publication(
                        extract_root,
                        "source",
                        task_id=f"material-{lease.generation}",
                    )
                except ExtractionCancelled as error:
                    raise InterruptedError(
                        "material ZIP extraction cancelled"
                    ) from error
                except ServerZipImportError as error:
                    raise AgentMaterialImportRuntimeError(
                        f"material ZIP safety validation failed: {error.code}"
                    ) from error
                source_root = extract_root / "source"

            review_path = workdir / "output" / "material-review.zip"
            review_path.parent.mkdir(parents=True, exist_ok=True)
            self._heartbeat(
                monitor,
                progress=48,
                stage="REMOTE_MATERIAL_REVIEWING",
                current_item="检查素材内容",
            )

            def review_progress(completed: int, total: int, current: str):
                self._assert_active(monitor)
                percent = (
                    48 + (32.0 * completed / max(1, total))
                    if total > 0
                    else 48
                )
                monitor.beat(
                    progress=percent,
                    stage="REMOTE_MATERIAL_REVIEWING",
                    current_item=current,
                )

            review_kwargs = {
                "task_id": lease.task_id,
                "project_id": lease.project_id,
                "execution_generation": lease.generation,
                "storage_source_id": str(target.get("storage_source_id") or ""),
                "storage_type": str(target.get("storage_type") or ""),
                "cancelled": lambda: (
                    self._shutdown_event.is_set()
                    or monitor.cancel_requested.is_set()
                    or monitor.fenced.is_set()
                ),
                "progress": review_progress,
            }
            if mode == "storage_scan":
                review = build_storage_scan_material_review_archive(
                    broker_provider,
                    review_path,
                    prefix=str(source_contract.get("prefix") or ""),
                    recursive=bool(source_contract.get("recursive", True)),
                    import_format=str(payload.get("import_format") or ""),
                    dataset_yaml=str(payload.get("dataset_yaml") or ""),
                    **review_kwargs,
                )
            else:
                review_builder = (
                    build_yolo_material_review_archive
                    if str(payload.get("import_format") or "") == "yolo"
                    else build_material_review_archive
                )
                review_kwargs["target_prefix"] = str(
                    target.get("target_prefix") or ""
                )
                if str(payload.get("import_format") or "") == "yolo":
                    review_kwargs["dataset_yaml"] = str(
                        payload.get("dataset_yaml") or ""
                    )
                review = review_builder(
                    source_root,
                    review_path,
                    **review_kwargs,
                )
            self._assert_active(monitor)
            review_sha = str(review["sha256"])
            review_size = int(review["size_bytes"])
            self._heartbeat(
                monitor,
                progress=82,
                stage="REMOTE_MATERIAL_PREPARING_UPLOAD",
                current_item="准备审查结果上传",
            )
            prepared = self.client.prepare_result_upload(
                lease,
                sha256=review_sha,
                size_bytes=review_size,
            )
            if not bool(prepared.get("already_uploaded")):
                upload = prepared.get("upload")
                if not isinstance(upload, Mapping):
                    raise AgentMaterialImportRuntimeError(
                        "control plane returned no material review upload contract"
                    )
                self._upload_result(
                    upload,
                    review_path,
                    monitor,
                    size_bytes=review_size,
                    sha256=review_sha,
                )
            self._assert_active(monitor)
            self._heartbeat(
                monitor,
                progress=94,
                stage="REMOTE_MATERIAL_CONFIRMING_REVIEW",
                current_item="校验审查结果",
            )
            confirmed = self.client.confirm_result_upload(
                lease,
                runtime_result={
                    "ok": True,
                    "engine": "material-import",
                    "note": "review_bundle_verified",
                },
            )
            result_ref = str(confirmed.get("result_ref") or "")
            if not result_ref:
                raise AgentMaterialImportRuntimeError(
                    "control plane did not confirm material review result"
                )
            self._assert_active(monitor)
            finished = self.client.finish(
                lease,
                "AWAITING_CONFIRMATION",
                result_ref=result_ref,
            )
            task = finished.get("task")
            if not isinstance(task, Mapping) or str(task.get("status") or "") != "AWAITING_CONFIRMATION":
                raise AgentMaterialImportRuntimeError(
                    "control plane did not transition material import to awaiting confirmation"
                )
            return AgentMaterialImportOutcome(
                task_id=lease.task_id,
                status="AWAITING_CONFIRMATION",
                result_ref=result_ref,
            )
        except RemoteExecutionFenced:
            raise
        except InterruptedError as error:
            try:
                self.client.finish(
                    lease,
                    "CANCELLED",
                    error=str(error),
                )
            except Exception:
                pass
            return AgentMaterialImportOutcome(
                task_id=lease.task_id,
                status="CANCELLED",
                error=str(error),
            )
        except Exception as error:
            try:
                self.client.finish(
                    lease,
                    "FAILED",
                    error=f"{type(error).__name__}: {error}",
                )
            except Exception:
                pass
            return AgentMaterialImportOutcome(
                task_id=lease.task_id,
                status="FAILED",
                error=f"{type(error).__name__}: {error}",
            )
        finally:
            monitor.stop()
            self.workdirs.cleanup(lease)


__all__ = [
    "AgentMaterialImportOutcome",
    "AgentMaterialImportRunner",
    "AgentMaterialImportRuntimeError",
]
