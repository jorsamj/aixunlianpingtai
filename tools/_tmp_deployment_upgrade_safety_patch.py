from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace(path, old, new):
    p = ROOT / path
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"missing patch anchor in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


(ROOT / "platform_core/build_identity.py").write_text(r'''from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_FINGERPRINT_FILES = (
    "app.py",
    "launcher.py",
    "task_worker.py",
    "train_worker.py",
    "platform_core/task_runtime/repository.py",
    "platform_core/training_tasks.py",
)


def _git_revision(base_dir: Path) -> str:
    if not (base_dir / ".git").exists():
        return ""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(base_dir),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    value = (completed.stdout or "").strip().lower()
    return value if completed.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else ""


def _source_fingerprint(base_dir: Path) -> str:
    digest = hashlib.sha256()
    count = 0
    for relative in _FINGERPRINT_FILES:
        path = base_dir / relative
        if not path.is_file():
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        count += 1
    return f"src-{digest.hexdigest()[:20]}" if count else "unknown"


def resolve_build_id(base_dir: str | Path) -> str:
    explicit = os.environ.get("MC_BUILD_REVISION", "").strip()
    if explicit:
        return explicit[:128]
    root = Path(base_dir).resolve()
    return _git_revision(root) or _source_fingerprint(root)


def service_matches_build(
    local_version: str,
    local_build_id: str,
    remote_version: str,
    remote_payload: dict[str, Any] | None,
) -> bool:
    remote_build_id = str((remote_payload or {}).get("build_id") or "").strip()
    return bool(
        remote_build_id
        and str(remote_version or "").strip() == str(local_version or "").strip()
        and remote_build_id == str(local_build_id or "").strip()
    )
''', encoding="utf-8")

(ROOT / "platform_core/upgrade_guard.py").write_text(r'''from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from typing import Any

_MARKER = Path("task_runtime") / "worker-build.json"
_ACTIVE_STATUSES = ("RUNNING", "CANCEL_REQUESTED")


def _marker_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / _MARKER


def read_worker_build_marker(data_dir: str | Path) -> dict[str, Any]:
    path = _marker_path(data_dir)
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_worker_build_marker(data_dir: str | Path, build_id: str) -> None:
    path = _marker_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps({"build_id": str(build_id)}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.replace(temporary, path)


def active_runtime_tasks(data_dir: str | Path, limit: int = 20) -> list[dict[str, Any]]:
    database_path = Path(data_dir) / "task_runtime" / "tasks.sqlite3"
    if not database_path.is_file():
        return []
    uri = database_path.resolve().as_uri() + "?mode=ro"
    try:
        database = sqlite3.connect(uri, uri=True, timeout=2)
    except sqlite3.Error as error:
        raise RuntimeError(f"无法读取任务数据库以执行升级保护：{error}") from error
    try:
        table = database.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        if table is None:
            return []
        columns = {str(row[1]) for row in database.execute("PRAGMA table_info(tasks)").fetchall()}
        required = {"task_id", "status"}
        if not required <= columns:
            return []
        optional = [name for name in ("kind", "stage", "updated_at") if name in columns]
        select_columns = ["task_id", "status", *optional]
        placeholders = ",".join("?" for _ in _ACTIVE_STATUSES)
        rows = database.execute(
            f"SELECT {','.join(select_columns)} FROM tasks "
            f"WHERE status IN ({placeholders}) ORDER BY task_id LIMIT ?",
            (*_ACTIVE_STATUSES, max(1, int(limit))),
        ).fetchall()
        return [dict(zip(select_columns, row)) for row in rows]
    except sqlite3.Error as error:
        raise RuntimeError(f"检查运行中任务失败：{error}") from error
    finally:
        database.close()


def ensure_worker_build_compatible(
    data_dir: str | Path,
    current_build_id: str,
    *,
    allow_active_upgrade: bool = False,
) -> dict[str, Any]:
    marker = read_worker_build_marker(data_dir)
    previous_build_id = str(marker.get("build_id") or "").strip()
    current = str(current_build_id or "").strip()
    active = active_runtime_tasks(data_dir)
    changed = previous_build_id != current
    if active and changed and not allow_active_upgrade:
        sample = ", ".join(
            f"{item.get('task_id')}({item.get('status')})" for item in active[:5]
        )
        previous = previous_build_id or "legacy/unknown"
        raise RuntimeError(
            "检测到跨 Build 启动且仍有运行中任务，已拒绝新版 Worker 接管，避免半途任务被重新执行。"
            f" previous={previous}; current={current}; active={sample}. "
            "请先用原 Build 让任务结束/取消；仅在明确接受恢复风险时设置 MC_ALLOW_ACTIVE_TASK_UPGRADE=1。"
        )
    return {
        "previous_build_id": previous_build_id,
        "current_build_id": current,
        "build_changed": changed,
        "active_tasks": active,
    }
''', encoding="utf-8")

replace(
    "app.py",
    "from platform_core.runtime_paths import resolve_data_dir\n",
    "from platform_core.runtime_paths import resolve_data_dir\nfrom platform_core.build_identity import resolve_build_id\n",
)
replace(
    "app.py",
    "BASE_DIR = Path(__file__).resolve().parent\ndef _read_app_version() -> str:\n",
    "BASE_DIR = Path(__file__).resolve().parent\nBUILD_ID = resolve_build_id(BASE_DIR)\ndef _read_app_version() -> str:\n",
)
replace(
    "app.py",
    '        "version": APP_VERSION,\n        "name": "畅联云算法训练",\n',
    '        "version": APP_VERSION,\n        "build_id": BUILD_ID,\n        "name": "畅联云算法训练",\n',
)

replace(
    "launcher.py",
    "from platform_core.runtime_paths import resolve_data_dir\n",
    "from platform_core.runtime_paths import resolve_data_dir\nfrom platform_core.build_identity import resolve_build_id, service_matches_build\n",
)
replace(
    "launcher.py",
    "BASE_DIR = Path(__file__).resolve().parent\ndef _read_platform_version() -> str:\n",
    "BASE_DIR = Path(__file__).resolve().parent\nBUILD_ID = resolve_build_id(BASE_DIR)\ndef _read_platform_version() -> str:\n",
)
replace(
    "launcher.py",
    '    say(f"Changlian Cloud Algorithm Training v{VERSION}")\n    say("===============================================")\n',
    '    say(f"Changlian Cloud Algorithm Training v{VERSION}")\n    say(f"Build: {BUILD_ID[:16]}")\n    say("===============================================")\n',
)
replace(
    "launcher.py",
    '''    if port_open(PORT):
        ver, _ = get_version(url)
        if ver == VERSION:
            say(f"[INFO] v{VERSION} 已在运行：{url}")
            wait_bootstrap(url, proc=None)
            webbrowser.open(url + f"/?v={VERSION}")
            return 0
        if ver:
            say(f"[ERROR] 端口 {PORT} 正被旧平台 v{ver} 占用。")
            say("请关闭旧版启动窗口后重新运行本版本，避免浏览器看到旧界面。")
        else:
            say(f"[ERROR] 端口 {PORT} 已被其他程序占用。可设置 MC_PORT 后再启动。")
        return 4
''',
    '''    if port_open(PORT):
        ver, info = get_version(url)
        if service_matches_build(VERSION, BUILD_ID, ver, info):
            say(f"[INFO] v{VERSION} / Build {BUILD_ID[:16]} 已在运行：{url}")
            wait_bootstrap(url, proc=None)
            webbrowser.open(url + f"/?v={VERSION}-{BUILD_ID[:12]}")
            return 0
        if ver == VERSION:
            remote_build = str((info or {}).get("build_id") or "legacy/unknown")
            say(f"[ERROR] 端口 {PORT} 上虽然也是 v{VERSION}，但运行的是不同 Build：{remote_build[:32]}。")
            say("请先停止旧进程再启动当前代码，避免误以为新修复已经生效。")
        elif ver:
            say(f"[ERROR] 端口 {PORT} 正被旧平台 v{ver} 占用。")
            say("请关闭旧版启动窗口后重新运行本版本，避免浏览器看到旧界面。")
        else:
            say(f"[ERROR] 端口 {PORT} 已被其他程序占用。可设置 MC_PORT 后再启动。")
        return 4
''',
)
replace(
    "launcher.py",
    '    env["MC_PLATFORM_VERSION"] = VERSION\n\n    say(f"[4/5] 启动服务：{url}")\n',
    '    env["MC_PLATFORM_VERSION"] = VERSION\n    env["MC_BUILD_REVISION"] = BUILD_ID\n\n    say(f"[4/5] 启动服务：{url}")\n',
)
replace(
    "launcher.py",
    '''        while time.time() < deadline:
            ver, _ = get_version(url, timeout=1.0)
            if ver == VERSION:
                say(f"[OK] 服务已启动：{url}")
                wait_bootstrap(url, proc=proc)
                webbrowser.open(url + f"/?v={VERSION}")
                break
            if ver:
''',
    '''        while time.time() < deadline:
            ver, info = get_version(url, timeout=1.0)
            if service_matches_build(VERSION, BUILD_ID, ver, info):
                say(f"[OK] 服务已启动：{url} · Build {BUILD_ID[:16]}")
                wait_bootstrap(url, proc=proc)
                webbrowser.open(url + f"/?v={VERSION}-{BUILD_ID[:12]}")
                break
            if ver:
''',
)

replace(
    "task_worker.py",
    "import argparse\nimport json\nimport socket\nimport sys\nimport uuid\n",
    "import argparse\nimport json\nimport os\nimport socket\nimport sys\nimport uuid\nfrom pathlib import Path\n",
)
replace(
    "task_worker.py",
    "from platform_core.runtime_paths import resolve_data_dir\n",
    "from platform_core.runtime_paths import resolve_data_dir\nfrom platform_core.build_identity import resolve_build_id\nfrom platform_core.upgrade_guard import ensure_worker_build_compatible, write_worker_build_marker\n",
)
replace(
    "task_worker.py",
    '''    args = build_parser().parse_args(argv)
    data_dir = resolve_data_dir(args.data_dir)
    runtime_dir = data_dir / "task_runtime"
    repository = FencedTaskRepository(runtime_dir / "tasks.sqlite3")
''',
    '''    args = build_parser().parse_args(argv)
    data_dir = resolve_data_dir(args.data_dir)
    build_id = resolve_build_id(Path(__file__).resolve().parent)
    if not args.check:
        try:
            ensure_worker_build_compatible(
                data_dir,
                build_id,
                allow_active_upgrade=os.environ.get("MC_ALLOW_ACTIVE_TASK_UPGRADE", "").strip() == "1",
            )
        except RuntimeError as error:
            print(f"Worker 启动被升级保护拒绝：{error}", file=sys.stderr)
            return 4
    runtime_dir = data_dir / "task_runtime"
    repository = FencedTaskRepository(runtime_dir / "tasks.sqlite3")
''',
)
replace(
    "task_worker.py",
    '                    "execution_fencing": True,\n',
    '                    "execution_fencing": True,\n                    "build_id": build_id,\n',
)
replace(
    "task_worker.py",
    '''    try:
        scheduler = Scheduler(
''',
    '''    try:
        write_worker_build_marker(data_dir, build_id)
        scheduler = Scheduler(
''',
)

replace(
    "platform_core/training_devices.py",
    '''def training_python(data_dir: str | Path) -> str:
''',
    '''def resolve_direct_training_assignment(
    value: Any,
    *,
    cuda_available: bool,
    cuda_devices: int,
) -> tuple[str, str]:
    """Resolve a direct/legacy training request into the explicit worker device contract."""
    requested = normalize_training_device(value)
    count = max(0, int(cuda_devices or 0))
    if requested == "auto":
        assigned = "cuda:0" if bool(cuda_available) and count > 0 else "cpu"
    else:
        assigned = requested
    if assigned.startswith("cuda:"):
        index = int(assigned[5:])
        if not bool(cuda_available) or index >= count:
            raise ValueError(f"requested CUDA device is unavailable: {assigned}")
    return requested, assigned


def training_python(data_dir: str | Path) -> str:
''',
)

replace(
    "remote_train_server.py",
    "from pydantic import BaseModel\n",
    "from pydantic import BaseModel\n\nfrom platform_core.training_devices import resolve_direct_training_assignment\n",
)
replace(
    "remote_train_server.py",
    '''    rt = training_runtime_info()
    if not rt.get("ok"):
        raise HTTPException(status_code=400, detail="远程训练 Python 不可用：" + str(rt.get("error") or "未知错误"))
''',
    '''    rt = training_runtime_info()
    if not rt.get("ok"):
        raise HTTPException(status_code=400, detail="远程训练 Python 不可用：" + str(rt.get("error") or "未知错误"))
    try:
        requested_device, assigned_device = resolve_direct_training_assignment(
            device,
            cuda_available=bool(rt.get("cuda")),
            cuda_devices=int(rt.get("cuda_devices") or 0),
        )
    except (TypeError, ValueError) as error:
        raise HTTPException(status_code=400, detail=f"训练设备不可用：{error}") from error
''',
)
replace(
    "remote_train_server.py",
    '''        "device": device,
        "run_name": run_name,
''',
    '''        "device": assigned_device,
        "requested_device": requested_device,
        "assigned_device": assigned_device,
        "run_name": run_name,
''',
)
replace(
    "remote_train_server.py",
    '''        "--batch", str(int(batch)),
        "--device", device,
        "--job-id", job_id, "--run-name", run_name,
''',
    '''        "--batch", str(int(batch)),
        "--device", assigned_device,
        "--assigned-device", assigned_device,
        "--requested-device", requested_device,
        "--job-id", job_id, "--run-name", run_name,
''',
)

(ROOT / "tests/unit/test_deployment_upgrade_safety.py").write_text(r'''from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from platform_core.build_identity import resolve_build_id, service_matches_build
from platform_core.training_devices import resolve_direct_training_assignment
from platform_core.upgrade_guard import ensure_worker_build_compatible, write_worker_build_marker

ROOT = Path(__file__).resolve().parents[2]


def _active_task_database(data_dir: Path, status: str = "RUNNING") -> None:
    runtime = data_dir / "task_runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    database = sqlite3.connect(runtime / "tasks.sqlite3")
    database.execute(
        "CREATE TABLE tasks (task_id TEXT, kind TEXT, status TEXT, stage TEXT, updated_at TEXT)"
    )
    database.execute(
        "INSERT INTO tasks VALUES (?,?,?,?,?)",
        ("task-1", "TRAINING", status, "running", "2026-09-14T00:00:00+00:00"),
    )
    database.commit()
    database.close()


def test_same_version_requires_same_build_identity(monkeypatch, tmp_path):
    monkeypatch.setenv("MC_BUILD_REVISION", "build-current")
    assert resolve_build_id(tmp_path) == "build-current"
    assert service_matches_build("42.24.0", "build-current", "42.24.0", {"build_id": "build-current"})
    assert not service_matches_build("42.24.0", "build-current", "42.24.0", {"build_id": "build-old"})
    assert not service_matches_build("42.24.0", "build-current", "42.24.0", {})


def test_cross_build_worker_refuses_to_take_over_active_task(tmp_path):
    _active_task_database(tmp_path)
    write_worker_build_marker(tmp_path, "build-old")
    with pytest.raises(RuntimeError, match="跨 Build"):
        ensure_worker_build_compatible(tmp_path, "build-new")


def test_same_build_keeps_crash_recovery_available(tmp_path):
    _active_task_database(tmp_path)
    write_worker_build_marker(tmp_path, "build-current")
    state = ensure_worker_build_compatible(tmp_path, "build-current")
    assert state["build_changed"] is False
    assert state["active_tasks"][0]["task_id"] == "task-1"


def test_explicit_override_is_required_for_cross_build_active_recovery(tmp_path):
    _active_task_database(tmp_path)
    write_worker_build_marker(tmp_path, "build-old")
    state = ensure_worker_build_compatible(tmp_path, "build-new", allow_active_upgrade=True)
    assert state["build_changed"] is True
    assert len(state["active_tasks"]) == 1


def test_direct_remote_training_assignment_matches_new_worker_contract():
    assert resolve_direct_training_assignment("0", cuda_available=True, cuda_devices=2) == ("cuda:0", "cuda:0")
    assert resolve_direct_training_assignment("auto", cuda_available=True, cuda_devices=1) == ("auto", "cuda:0")
    assert resolve_direct_training_assignment("auto", cuda_available=False, cuda_devices=0) == ("auto", "cpu")
    with pytest.raises(ValueError, match="unavailable"):
        resolve_direct_training_assignment("cuda:2", cuda_available=True, cuda_devices=1)


def test_product_wiring_exposes_build_and_passes_remote_device_contract():
    app = (ROOT / "app.py").read_text(encoding="utf-8")
    launcher = (ROOT / "launcher.py").read_text(encoding="utf-8")
    worker = (ROOT / "task_worker.py").read_text(encoding="utf-8")
    remote = (ROOT / "remote_train_server.py").read_text(encoding="utf-8")
    assert '"build_id": BUILD_ID' in app
    assert "service_matches_build(VERSION, BUILD_ID" in launcher
    assert "ensure_worker_build_compatible" in worker
    assert '"--assigned-device", assigned_device' in remote
    assert '"--requested-device", requested_device' in remote
''', encoding="utf-8")

print("deployment upgrade safety patch applied")
