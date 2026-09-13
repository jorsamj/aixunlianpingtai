from __future__ import annotations

from pathlib import Path


TARGET = Path("platform_core/task_runtime/worker_instances.py")
IMPORT_ANCHOR = "from __future__ import annotations\n\n"
IMPORT_LINE = "from contextlib import closing\n\n"
OLD = "with self.repository._connect() as database:"
NEW = "with closing(self.repository._connect()) as database:"


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    if NEW in source:
        raise SystemExit("worker instance connection lifecycle migration already applied")
    count = source.count(OLD)
    if count != 3:
        raise SystemExit(f"expected exactly 3 worker instance connection contexts, found {count}")
    if IMPORT_LINE.strip() in source:
        raise SystemExit("closing import already exists before migration")
    if source.count(IMPORT_ANCHOR) != 1:
        raise SystemExit("worker instance import anchor is not unique")
    migrated = source.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_LINE, 1)
    migrated = migrated.replace(OLD, NEW)
    TARGET.write_text(migrated, encoding="utf-8")
    print("WORKER_INSTANCE_CONNECTION_CONTEXTS_MIGRATED=3")


if __name__ == "__main__":
    main()
