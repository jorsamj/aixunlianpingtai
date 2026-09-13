from __future__ import annotations

from pathlib import Path


TARGET = Path("app.py")
OLD = '''@app.post("/api/v62/projects/{project_id}/tasks/{task_id}/cancel")\ndef cancel_unified_runtime_task(project_id: str, task_id: str):\n    _runtime_task_for_project(project_id, task_id)\n    repository = shared_task_repository()\n    try:\n        task = repository.request_cancel(task_id)\n    except ValueError as error:\n        raise HTTPException(status_code=409, detail=str(error)) from error\n    return task_to_public(task, repository)\n'''
NEW = '''@app.post("/api/v62/projects/{project_id}/tasks/{task_id}/cancel")\ndef cancel_unified_runtime_task(project_id: str, task_id: str):\n    current = _runtime_task_for_project(project_id, task_id)\n    repository = shared_task_repository()\n    try:\n        task = repository.request_cancel(task_id)\n    except ValueError as error:\n        raise HTTPException(status_code=409, detail=str(error)) from error\n    if (\n        current.status is TaskStatus.RUNNING\n        and current.process_pid is not None\n        and current.process_create_time is not None\n        and str(current.process_command_hash or "").strip()\n    ):\n        identity = ProcessIdentity(\n            pid=int(current.process_pid),\n            create_time=float(current.process_create_time),\n            command_hash=str(current.process_command_hash),\n        )\n        try:\n            ProcessController().terminate_tree(identity)\n        except PermissionError as error:\n            raise HTTPException(\n                status_code=409,\n                detail=f"取消请求已记录，但任务进程无法安全终止：{error}",\n            ) from error\n    return task_to_public(task, repository)\n'''


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    if NEW in source:
        raise SystemExit("unified cancel process termination migration already applied")
    count = source.count(OLD)
    if count != 1:
        raise SystemExit(f"expected exactly one unified cancel endpoint owner, found {count}")
    TARGET.write_text(source.replace(OLD, NEW, 1), encoding="utf-8")
    print("UNIFIED_CANCEL_BOUND_PROCESS_TERMINATION_MIGRATED=1")


if __name__ == "__main__":
    main()
