from __future__ import annotations

from pathlib import Path


TARGET = Path("platform_core/gpu_resources.py")
IMPORT_ANCHOR = "from __future__ import annotations\n\n"
IMPORT_LINE = "from contextlib import closing\n\n"
OLD_DIRECT = "with repository._connect() as database:"
NEW_DIRECT = "with closing(repository._connect()) as database:"
OLD_OWNER = "with self.repository._connect() as database:"
NEW_OWNER = "with closing(self.repository._connect()) as database:"


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    if NEW_DIRECT in source or NEW_OWNER in source:
        raise SystemExit("GPU resource connection lifecycle migration already applied")
    direct_count = source.count(OLD_DIRECT)
    owner_count = source.count(OLD_OWNER)
    if direct_count != 1 or owner_count != 3:
        raise SystemExit(
            f"expected 1 direct and 3 owned GPU DB contexts, found direct={direct_count}, owned={owner_count}"
        )
    if IMPORT_LINE.strip() in source:
        raise SystemExit("closing import already exists before migration")
    if source.count(IMPORT_ANCHOR) != 1:
        raise SystemExit("GPU resource import anchor is not unique")

    migrated = source.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + IMPORT_LINE, 1)
    migrated = migrated.replace(OLD_DIRECT, NEW_DIRECT)
    migrated = migrated.replace(OLD_OWNER, NEW_OWNER)
    TARGET.write_text(migrated, encoding="utf-8")
    print("GPU_RESOURCE_CONNECTION_CONTEXTS_MIGRATED=4")


if __name__ == "__main__":
    main()
