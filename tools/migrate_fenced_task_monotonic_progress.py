from __future__ import annotations

from pathlib import Path


TARGET = Path("platform_core/task_runtime/fenced_repository.py")
OLD = '''        if progress is not None:\n            updates.append("progress=?")\n            parameters.append(max(0.0, min(100.0, float(progress))))\n'''
NEW = '''        if progress is not None:\n            updates.append("progress=MAX(progress, ?)")\n            parameters.append(max(0.0, min(100.0, float(progress))))\n'''


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    if NEW in source:
        raise SystemExit("fenced task heartbeat progress migration already applied")
    count = source.count(OLD)
    if count != 1:
        raise SystemExit(f"expected exactly one fenced heartbeat progress owner, found {count}")
    TARGET.write_text(source.replace(OLD, NEW, 1), encoding="utf-8")
    print("FENCED_TASK_HEARTBEAT_MONOTONIC_PROGRESS_MIGRATED=1")


if __name__ == "__main__":
    main()
