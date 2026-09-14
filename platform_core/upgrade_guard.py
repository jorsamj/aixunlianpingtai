from __future__ import annotations

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
