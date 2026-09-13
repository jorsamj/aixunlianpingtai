from __future__ import annotations

from pathlib import Path


TARGETS = (
    Path("platform_core/task_runtime/repository.py"),
    Path("platform_core/task_runtime/fenced_repository.py"),
)
OLD = '''        if stage is not None:\n            updates.append("stage=?")\n            parameters.append(str(stage))\n'''
NEW = '''        if stage is not None:\n            stage_value = str(stage)\n            updates.append(\n                "stage=CASE WHEN stage IN ('paused','cancelling') AND stage<>? "\n                "THEN stage ELSE ? END"\n            )\n            parameters.extend([stage_value, stage_value])\n'''


def main() -> None:
    migrated = 0
    for target in TARGETS:
        source = target.read_text(encoding="utf-8")
        count = source.count(OLD)
        if count != 1:
            raise SystemExit(f"expected exactly one heartbeat stage owner in {target}, found {count}")
        if NEW in source:
            raise SystemExit(f"control-stage heartbeat migration already applied in {target}")
        target.write_text(source.replace(OLD, NEW, 1), encoding="utf-8")
        migrated += 1
    print(f"CONTROL_STAGE_HEARTBEAT_OWNERS_MIGRATED={migrated}")


if __name__ == "__main__":
    main()
