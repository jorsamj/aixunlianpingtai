from pathlib import Path

PATH = Path("platform_core/task_runtime/repository.py")
OLD_SQL = '"UPDATE tasks SET stage=?, updated_at=? WHERE task_id=? AND status IN (\'RUNNING\',\'CANCEL_REQUESTED\')",'
NEW_SQL = '"UPDATE tasks SET stage=?, updated_at=? WHERE task_id=? AND status=\'RUNNING\'",'
OLD_ERROR = 'raise ValueError("only active tasks can change stage")'
NEW_ERROR = 'raise ValueError("only running tasks can change stage")'

source = PATH.read_text(encoding="utf-8")
if source.count(OLD_SQL) != 1:
    raise SystemExit(f"expected exactly one cancellable set_stage SQL owner, got {source.count(OLD_SQL)}")
if source.count(OLD_ERROR) != 1:
    raise SystemExit(f"expected exactly one set_stage error owner, got {source.count(OLD_ERROR)}")

source = source.replace(OLD_SQL, NEW_SQL, 1).replace(OLD_ERROR, NEW_ERROR, 1)
PATH.write_text(source, encoding="utf-8")
print("TASK_CANCEL_STAGE_FENCING_MIGRATED=1")
