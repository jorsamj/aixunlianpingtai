from __future__ import annotations

from pathlib import Path


TARGETS = (
    Path("platform_core/task_runtime/repository.py"),
    Path("platform_core/task_runtime/fenced_repository.py"),
)
OLD = "with self._connect() as database:"
NEW = "with closing(self._connect()) as database:"
IMPORT_ANCHOR = "from __future__ import annotations\n\n"
IMPORT_LINE = "from contextlib import closing\n"


def migrate(path: Path) -> int:
    source = path.read_text(encoding="utf-8")
    if NEW in source and OLD not in source:
        raise SystemExit(f"connection lifecycle migration already applied: {path}")
    count = source.count(OLD)
    if count < 1:
        raise SystemExit(f"expected at least one task repository connection owner: {path}")
    if IMPORT_LINE not in source:
        if IMPORT_ANCHOR not in source:
            raise SystemExit(f"future import anchor not found: {path}")
        source = source.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_LINE + "\n", 1)
    source = source.replace(OLD, NEW)
    if OLD in source:
        raise SystemExit(f"plain connection context remains after migration: {path}")
    path.write_text(source, encoding="utf-8")
    return count


def main() -> None:
    counts = {str(path): migrate(path) for path in TARGETS}
    print("TASK_RUNTIME_CONNECTION_CONTEXTS_MIGRATED=" + repr(counts))


if __name__ == "__main__":
    main()
