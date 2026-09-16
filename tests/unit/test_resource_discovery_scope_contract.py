from pathlib import Path
from types import SimpleNamespace

import pytest

from platform_core.resource_discovery import request_scope, scanner, tasks


def test_directory_model_worker_requires_durable_explicit_roots():
    with pytest.raises(ValueError, match="requires at least one explicit root"):
        tasks._model_scan_roots("directory", [])


def test_full_model_worker_also_requires_durable_explicit_roots():
    with pytest.raises(ValueError, match="requires at least one explicit root"):
        tasks._model_scan_roots("full", [])


def test_full_model_worker_uses_roots_frozen_in_task_payload():
    roots = [Path("one"), Path("two")]
    assert tasks._model_scan_roots("full", roots) == roots


def test_full_environment_worker_rejects_missing_task_roots():
    with pytest.raises(ValueError, match="requires at least one explicit root"):
        tasks._environment_deep_scan_allowed("full", [], 0)


def test_full_request_scope_freezes_visible_local_roots(monkeypatch, tmp_path):
    first = tmp_path / "disk-one"
    second = tmp_path / "disk-two"
    monkeypatch.setattr(request_scope, "local_scan_roots", lambda: [first, second])

    roots = request_scope.resolve_discovery_request_roots("full", ["ignored"])

    assert roots == [str(first), str(second)]


def test_full_request_scope_fails_closed_when_no_local_roots(monkeypatch):
    monkeypatch.setattr(request_scope, "local_scan_roots", lambda: [])
    with pytest.raises(ValueError, match="本地磁盘根目录"):
        request_scope.resolve_discovery_request_roots("full", [])


def test_non_full_scope_preserves_only_explicit_roots(tmp_path):
    root = tmp_path / "models"
    assert request_scope.resolve_discovery_request_roots(
        "directory", [str(root), "", str(root)]
    ) == [str(root)]
    assert request_scope.resolve_discovery_request_roots("auto", None) == []


def test_api_freezes_full_scan_roots_before_both_durable_tasks():
    source = Path("app.py").read_text(encoding="utf-8")
    assert "roots = resolve_discovery_request_roots(payload.scope, payload.roots)" in source
    assert "roots = resolve_discovery_request_roots(scope, submitted_roots)" in source
    assert '_create_discovery_task("ultralytics_environment", payload.scope, roots)' in source
    assert '_create_discovery_task("local_models", scope, roots)' in source


def test_frontend_full_scan_actions_remain_explicit_user_actions():
    source = Path("static/modules/resource-discovery.js").read_text(encoding="utf-8")
    assert "runtime.detectEnvironment({scope: 'full'})" in source
    assert "runtime.scanModels({scope: 'full'})" in source


def test_worker_model_handler_never_uses_implicit_none_roots():
    import inspect

    source = inspect.getsource(tasks.ResourceDiscoveryHandler._models)
    assert "scan_roots = _model_scan_roots(scope, roots)" in source
    assert "scan_model_files(\n            scan_roots," in source
    assert '"scan_root_mode": "explicit"' in source



def test_windows_local_scan_roots_include_all_visible_local_drives(monkeypatch):
    partitions = [
        SimpleNamespace(device="C:\\", mountpoint="C:/", fstype="NTFS", opts="rw"),
        SimpleNamespace(device="D:\\", mountpoint="D:/", fstype="NTFS", opts="rw"),
        SimpleNamespace(device="F:\\", mountpoint="F:/", fstype="NTFS", opts="rw"),
    ]
    monkeypatch.setattr(scanner.psutil, "disk_partitions", lambda all=False: partitions)

    roots = scanner.local_scan_roots(platform="win32")

    assert [str(root).replace("\\", "/").rstrip("/") for root in roots] == ["C:", "D:", "F:"]


def test_linux_local_scan_roots_exclude_network_and_virtual_mounts(monkeypatch):
    partitions = [
        SimpleNamespace(device="/dev/sda1", mountpoint="/", fstype="ext4", opts="rw"),
        SimpleNamespace(device="/dev/sdb1", mountpoint="/data", fstype="xfs", opts="rw"),
        SimpleNamespace(device="server:/share", mountpoint="/mnt/nfs", fstype="nfs4", opts="rw,_netdev"),
        SimpleNamespace(device="//server/share", mountpoint="/mnt/smb", fstype="cifs", opts="rw"),
        SimpleNamespace(device="proc", mountpoint="/proc", fstype="proc", opts="rw"),
        SimpleNamespace(device="tmpfs", mountpoint="/run", fstype="tmpfs", opts="rw"),
    ]
    monkeypatch.setattr(scanner.psutil, "disk_partitions", lambda all=False: partitions)

    assert scanner.local_scan_roots(platform="linux") == [Path("/"), Path("/data")]


@pytest.mark.parametrize("fstype", ["nfs", "nfs4", "smb", "cifs", "sshfs", "proc", "sysfs", "tmpfs", "cgroup", "cgroup2"])
def test_full_scan_filesystem_fencing_keeps_network_and_virtual_types_excluded(fstype):
    assert scanner._is_excluded_filesystem("device", "/mnt/test", fstype, "rw") is True


def test_public_discovery_task_projects_frozen_request_scope_and_roots():
    source = Path("app.py").read_text(encoding="utf-8")
    assert '"request.json"' in source
    assert 'response["discovery_scope"]' in source
    assert 'response["scan_roots"] = scan_roots' in source
    assert 'response["scan_root_count"] = len(scan_roots)' in source
