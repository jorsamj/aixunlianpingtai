from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from platform_core.storage import nas_health
from platform_core.storage.manager import StorageManager
from platform_core.storage.nas_health import check_nas_source, read_mount_info
from platform_core.storage.source_repository import StorageSource, StorageSourceRepository


def source(root: Path, **nas):
    return StorageSource(
        id="nas-a", name="NAS A", type="local",
        config={"root": str(root), "nas": {
            "mount_point": str(root.parent), "expected_fs_types": ["nfs4"],
            "node_ids": ["node-a"], **nas,
        }},
    )


def mount(root: Path, *, point: Path | None = None, fs: str = "nfs4"):
    return {
        "mount_point": str(point or root.parent), "fs_type": fs,
        "mount_source": "nas.example:/train", "major_minor": "0:44",
    }


def probe(tmp_path, root, **kwargs):
    return check_nas_source(
        kwargs.pop("source", source(root)), node_id=kwargs.pop("node_id", "node-a"),
        data_dir=tmp_path, project_dir=tmp_path / "project", **kwargs,
    )


def test_nas_probe_accepts_matching_mount_and_sha(tmp_path, monkeypatch):
    root = tmp_path / "mnt" / "nas"
    root.mkdir(parents=True)
    payload = b"immutable nas probe"
    (root / "checks" / "probe.bin").parent.mkdir()
    (root / "checks" / "probe.bin").write_bytes(payload)
    monkeypatch.setattr(nas_health, "read_mount_info", lambda _path: mount(root))
    result = probe(tmp_path, root, object_key="checks/probe.bin",
                   expected_sha256=hashlib.sha256(payload).hexdigest(),
                   expected_size=len(payload))
    assert result.ok is True
    assert result.details["reason"] == "OK"
    assert result.details["fs_type"] == "nfs4"
    assert result.details["test_object_sha256"] == hashlib.sha256(payload).hexdigest()
    assert result.details["free_bytes"] >= 0


def test_plain_local_directory_is_rejected_without_mount_expectation(tmp_path, monkeypatch):
    root = tmp_path / "plain"
    root.mkdir()
    monkeypatch.setattr(nas_health, "read_mount_info", lambda _path: mount(root))
    item = StorageSource(id="nas-a", name="NAS A", type="local", config={"root": str(root)})
    result = probe(tmp_path, root, source=item)
    assert result.ok is False
    assert result.details["reason"] == "MOUNT_EXPECTATION_MISSING"


def test_nas_probe_rejects_wrong_filesystem(tmp_path, monkeypatch):
    root = tmp_path / "mnt" / "nas"
    root.mkdir(parents=True)
    monkeypatch.setattr(nas_health, "read_mount_info", lambda _path: mount(root, fs="ext4"))
    result = probe(tmp_path, root)
    assert result.ok is False
    assert result.details["reason"] == "FS_TYPE_MISMATCH"


def test_nas_probe_rejects_wrong_mount_point(tmp_path, monkeypatch):
    root = tmp_path / "mnt" / "nas"
    root.mkdir(parents=True)
    monkeypatch.setattr(nas_health, "read_mount_info",
                        lambda _path: mount(root, point=tmp_path / "other"))
    result = probe(tmp_path, root)
    assert result.ok is False
    assert result.details["reason"] == "MOUNT_POINT_MISMATCH"


def test_nas_probe_fails_closed_on_permission_and_transient_io(tmp_path, monkeypatch):
    root = tmp_path / "mnt" / "nas"
    root.mkdir(parents=True)
    monkeypatch.setattr(nas_health, "read_mount_info", lambda _path: mount(root))

    def denied(_path):
        raise PermissionError("denied")

    monkeypatch.setattr(nas_health.os, "scandir", denied)
    result = probe(tmp_path, root)
    assert result.ok is False
    assert result.details["reason"] == "READ_PERMISSION_DENIED"
    assert result.details["retryable"] is False


def test_nas_probe_does_not_turn_temporary_io_into_permanent_absence(tmp_path, monkeypatch):
    root = tmp_path / "mnt" / "nas"
    root.mkdir(parents=True)

    def unavailable(_path):
        raise OSError("stale NFS handle")

    monkeypatch.setattr(nas_health.os, "scandir", unavailable)
    result = probe(tmp_path, root)
    assert result.ok is False
    assert result.details["reason"] == "ROOT_IO_UNAVAILABLE"
    assert result.details["retryable"] is True


def test_nas_probe_rejects_sha_mismatch_and_path_traversal(tmp_path, monkeypatch):
    root = tmp_path / "mnt" / "nas"
    root.mkdir(parents=True)
    (root / "probe.bin").write_bytes(b"expected")
    monkeypatch.setattr(nas_health, "read_mount_info", lambda _path: mount(root))
    mismatch = probe(tmp_path, root, object_key="probe.bin",
                     expected_sha256="0" * 64, expected_size=8)
    assert mismatch.ok is False
    assert mismatch.details["reason"] == "TEST_OBJECT_SHA_MISMATCH"
    traversal = probe(tmp_path, root, object_key="../outside.bin",
                      expected_sha256="0" * 64, expected_size=1)
    assert traversal.ok is False
    assert traversal.details["reason"] == "INVALID_OBJECT_KEY"


def test_storage_manager_exposes_nas_probe_without_new_source_owner(tmp_path, monkeypatch):
    root = tmp_path / "mnt" / "nas"
    root.mkdir(parents=True)
    payload = b"manager probe"
    (root / "probe.bin").write_bytes(payload)
    monkeypatch.setattr(nas_health, "read_mount_info", lambda _path: mount(root))
    sources = StorageSourceRepository(tmp_path / "storage" / "storage_sources.sqlite3")
    sources.create({
        "id": "nas-a", "name": "NAS A", "type": "local",
        "config": {"root": str(root), "nas": {
            "mount_point": str(root.parent), "expected_fs_types": ["nfs4"],
        }},
    })
    manager = StorageManager(data_dir=tmp_path, project_id="project", sources=sources)
    result = manager.check_nas_source(
        "nas-a", node_id="node-a", object_key="probe.bin",
        expected_sha256=hashlib.sha256(payload).hexdigest(), expected_size=len(payload),
    )
    assert result.ok is True
    assert result.details["source_id"] == "nas-a"


@pytest.mark.skipif(os.name == "nt", reason="mountinfo is Linux-only")
def test_mountinfo_parser_uses_longest_matching_mount(tmp_path, monkeypatch):
    mountinfo = tmp_path / "mountinfo"
    root = tmp_path / "mnt" / "nas"
    root.mkdir(parents=True)
    mountinfo.write_text(
        f"1 0 0:1 / / rw - ext4 /dev/sda1 rw\n"
        f"2 1 0:44 / /mnt rw - nfs4 nas:/export rw\n"
        f"3 2 0:45 / /{_mount_escape(root)} rw - nfs4 nas:/train rw\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(nas_health, "_mountinfo_path", lambda: mountinfo)
    found = read_mount_info(root)
    assert found["mount_point"] == str(root)
    assert found["fs_type"] == "nfs4"


def _mount_escape(path: Path) -> str:
    return str(path).replace("\\", "\\134").replace(" ", "\\040").lstrip("/")
