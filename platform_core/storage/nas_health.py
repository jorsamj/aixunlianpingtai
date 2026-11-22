"""Read-only NAS mount and object-evidence probe.

The probe never mounts, unmounts, creates directories, or mutates source files.
A local directory is not accepted as NAS unless the storage source declares and
matches an expected mount point / filesystem identity.
"""
from __future__ import annotations

import hashlib
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from .factory import StorageProviderFactory
from .local import LocalStorageProvider
from .models import StorageHealth
from .source_repository import StorageSource


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mountinfo_path() -> Path:
    return Path("/proc/self/mountinfo")


def _unescape_mount(value: str) -> str:
    # mountinfo escapes space, tab, newline and backslash as \040, \011, \012, \134
    return (value.replace("\\040", " ").replace("\\011", "\t")
            .replace("\\012", "\n").replace("\\134", "\\"))


def read_mount_info(path: str | Path) -> dict[str, Any] | None:
    """Return the longest mount point containing ``path``, or None if unknown."""
    info_path = _mountinfo_path()
    try:
        lines = info_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    target = Path(path).resolve()
    best: dict[str, Any] | None = None
    best_len = -1
    for line in lines:
        if " - " not in line:
            continue
        before, after = line.split(" - ", 1)
        fields = before.split(" ")
        tail = after.split(" ")
        if len(fields) < 5 or not tail:
            continue
        try:
            mount_point = Path(_unescape_mount(fields[4])).resolve()
        except OSError:
            continue
        if target != mount_point and mount_point not in target.parents:
            continue
        if len(str(mount_point)) <= best_len:
            continue
        best_len = len(str(mount_point))
        best = {
            "mount_point": str(mount_point),
            "fs_type": tail[0],
            "mount_source": _unescape_mount(tail[1]) if len(tail) > 1 else "",
            "major_minor": fields[2],
            "options": fields[5] if len(fields) > 5 else "",
        }
    return best


def _expectations(source: StorageSource) -> dict[str, Any]:
    raw = source.config.get("nas") if isinstance(source.config, Mapping) else None
    return dict(raw) if isinstance(raw, Mapping) else {}


def _expected_sources(expected: Mapping[str, Any]) -> list[str]:
    value = expected.get("expected_mount_sources", expected.get("expected_mount_source", []))
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, (list, tuple)):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _source_key(value: str, fs_type: str) -> str:
    raw = str(value or "").strip()
    if fs_type.lower() in {"cifs", "smb3", "smbfs"}:
        return raw.replace("\\", "/").rstrip("/").casefold()
    return raw.rstrip("/")


def _redact_mount_source(value: str) -> str:
    raw = str(value or "")
    if "@" not in raw:
        return raw
    head, tail = raw.split("@", 1)
    return "***@" + tail


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_nas_source(
    source: StorageSource,
    *,
    node_id: str,
    data_dir: str | Path,
    project_dir: str | Path,
    object_key: str = "",
    expected_sha256: str = "",
    expected_size: int | None = None,
) -> StorageHealth:
    """Fail-closed, read-only NAS reachability check for one node.

    ``object_key`` is always relative to the configured source root.  The
    source root and expected mount identity come from StorageSource config, not
    from a task payload or caller-supplied absolute path.
    """
    details: dict[str, Any] = {
        "source_id": source.id, "node_id": str(node_id or ""),
        "checked_at": _now(), "read_only": True,
        "evidence": "MOUNT_HEALTH_UNVERIFIED",
    }
    if not source.enabled:
        details["reason"] = "SOURCE_DISABLED"
        return StorageHealth.unavailable("存储源已停用", details=details)
    if str(source.type or "").strip().lower() != "local":
        details["reason"] = "NOT_LOCAL_PROVIDER"
        return StorageHealth.unavailable("该存储源不是本地/NAS Provider", details=details)

    expected = _expectations(source)
    expected_types = {str(value).strip().lower() for value in (expected.get("expected_fs_types") or [])}
    expected_mount = str(expected.get("mount_point") or "").strip()
    expected_sources = _expected_sources(expected)
    allowed_nodes = {str(value) for value in (expected.get("node_ids") or [])}
    details["expected_fs_types"] = sorted(expected_types)
    details["expected_mount_point"] = expected_mount
    details["expected_mount_sources"] = [_redact_mount_source(value) for value in expected_sources]
    if not expected_types or not expected_mount:
        details["reason"] = "MOUNT_EXPECTATION_MISSING"
        details["evidence"] = "MOUNT_HEALTH_UNVERIFIED"
        return StorageHealth.unavailable(
            "存储源未声明预期挂载点/文件系统类型，无法证明这是 NAS 挂载",
            details=details,
        )
    if not expected_sources:
        details["reason"] = "MOUNT_SOURCE_EXPECTATION_MISSING"
        details["evidence"] = "MOUNT_HEALTH_UNVERIFIED"
        return StorageHealth.unavailable(
            "存储源未声明预期挂载来源，无法证明挂载身份",
            details=details,
        )
    if allowed_nodes and str(node_id) not in allowed_nodes:
        details["reason"] = "NODE_NOT_ALLOWED"
        details["evidence"] = "MOUNT_HEALTH_UNVERIFIED"
        return StorageHealth.unavailable("当前节点不在该 NAS 存储源的允许节点中", details=details)

    try:
        provider = StorageProviderFactory(
            data_dir=data_dir, project_dir=project_dir,
        ).create(source)
    except Exception as error:  # noqa: BLE001 - provider config is external input
        details["reason"] = "PROVIDER_CONFIG_INVALID"
        details["error"] = str(error)
        return StorageHealth.unavailable("NAS 存储源配置无法解析", details=details)
    if not isinstance(provider, LocalStorageProvider):
        details["reason"] = "NOT_LOCAL_PROVIDER"
        return StorageHealth.unavailable("该存储源不是本地/NAS Provider", details=details)

    root = provider.root
    details["root"] = str(root)
    try:
        if not root.is_dir():
            details["reason"] = "ROOT_MISSING"
            details["retryable"] = False
            return StorageHealth.unavailable("配置的 NAS 根路径不存在或不是目录", details=details)
        with os.scandir(root) as entries:
            next(entries, None)
    except PermissionError:
        details["reason"] = "READ_PERMISSION_DENIED"
        details["retryable"] = False
        return StorageHealth.unavailable("当前节点没有 NAS 根目录读取权限", details=details)
    except OSError as error:
        details["reason"] = "ROOT_IO_UNAVAILABLE"
        details["retryable"] = True
        details["error"] = str(error)
        return StorageHealth.unavailable("NAS 根目录暂时不可达", details=details)

    try:
        mount = read_mount_info(root)
    except OSError as error:
        details["reason"] = "MOUNT_INFO_UNAVAILABLE"
        details["retryable"] = True
        details["error"] = str(error)
        return StorageHealth.unavailable("无法读取挂载信息", details=details)
    if not mount:
        details["reason"] = "MOUNT_INFO_UNAVAILABLE"
        details["retryable"] = True
        return StorageHealth.unavailable("无法确认 NAS 挂载身份", details=details)
    details.update({key: mount.get(key) for key in
                    ("mount_point", "fs_type", "major_minor")})
    details["mount_source"] = _redact_mount_source(str(mount.get("mount_source") or ""))
    actual_mount = str(mount.get("mount_point") or "")
    actual_type = str(mount.get("fs_type") or "").lower()
    if Path(actual_mount) != Path(expected_mount).resolve():
        details["reason"] = "MOUNT_POINT_MISMATCH"
        details["retryable"] = False
        details["evidence"] = "MOUNT_HEALTH_UNVERIFIED"
        return StorageHealth.unavailable("实际挂载点与配置预期不一致", details=details)
    if actual_type not in expected_types:
        details["reason"] = "FS_TYPE_MISMATCH"
        details["retryable"] = False
        details["evidence"] = "MOUNT_HEALTH_UNVERIFIED"
        return StorageHealth.unavailable("实际文件系统类型与配置预期不一致", details=details)
    actual_source = str(mount.get("mount_source") or "")
    allowed_sources = {_source_key(value, actual_type) for value in expected_sources}
    if _source_key(actual_source, actual_type) not in allowed_sources:
        details["reason"] = "MOUNT_SOURCE_MISMATCH"
        details["retryable"] = False
        details["evidence"] = "MOUNT_HEALTH_UNVERIFIED"
        return StorageHealth.unavailable("实际挂载来源与配置预期不一致", details=details)

    try:
        usage = shutil.disk_usage(root)
        details["free_bytes"] = int(usage.free)
        details["total_bytes"] = int(usage.total)
    except OSError as error:
        details["reason"] = "CAPACITY_UNAVAILABLE"
        details["retryable"] = True
        details["error"] = str(error)
        return StorageHealth.unavailable("无法读取 NAS 可用空间", details=details)

    if object_key:
        details["test_object"] = object_key
        details["object_evidence"] = "OBJECT_EVIDENCE_UNVERIFIED"
        if not expected_sha256 or expected_size is None:
            details["reason"] = "TEST_OBJECT_EVIDENCE_MISSING"
            return StorageHealth.unavailable(
                "提供了测试对象但没有声明预期 SHA256/大小，不能证明数据身份",
                details=details,
            )
        try:
            object_path = provider._path(object_key)
        except Exception as error:  # noqa: BLE001 - path validation is intentional
            details["reason"] = "INVALID_OBJECT_KEY"
            details["error"] = str(error)
            return StorageHealth.unavailable("测试对象路径越界或无效", details=details)
        details["test_object_path"] = str(object_path)
        try:
            if not object_path.is_file():
                details["reason"] = "TEST_OBJECT_MISSING"
                details["retryable"] = True
                return StorageHealth.unavailable("NAS 测试对象暂时不可读", details=details)
            actual_size = object_path.stat().st_size
            actual_sha = _hash_file(object_path).lower()
            details["test_object_size"] = int(actual_size)
            details["test_object_sha256"] = actual_sha
            if int(actual_size) != int(expected_size):
                details["reason"] = "TEST_OBJECT_SIZE_MISMATCH"
                return StorageHealth.unavailable("NAS 测试对象大小与预期不一致", details=details)
            if actual_sha != str(expected_sha256).strip().lower():
                details["reason"] = "TEST_OBJECT_SHA_MISMATCH"
                return StorageHealth.unavailable("NAS 测试对象 SHA256 与预期不一致", details=details)
        except PermissionError:
            details["reason"] = "READ_PERMISSION_DENIED"
            details["retryable"] = False
            return StorageHealth.unavailable("当前节点没有 NAS 测试对象读取权限", details=details)
        except OSError as error:
            details["reason"] = "TEST_OBJECT_IO_UNAVAILABLE"
            details["retryable"] = True
            details["error"] = str(error)
            return StorageHealth.unavailable("NAS 测试对象暂时不可达", details=details)

    details["reason"] = "OK"
    details["retryable"] = False
    if object_key:
        details["evidence"] = "OBJECT_EVIDENCE_VERIFIED"
        details["object_evidence"] = "OBJECT_EVIDENCE_VERIFIED"
        return StorageHealth.available("NAS 挂载、读取权限和指定对象数据身份验证通过", details=details)
    details["evidence"] = "MOUNT_HEALTH_VERIFIED"
    details["object_evidence"] = "NOT_CHECKED"
    return StorageHealth.available("NAS 挂载与读取权限验证通过（未验证对象）", details=details)
