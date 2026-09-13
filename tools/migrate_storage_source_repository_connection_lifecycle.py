from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "platform_core" / "storage" / "source_repository.py"
OLD = "with self._connect() as database:"
NEW = "with closing(self._connect()) as database:"
IMPORT_OLD = "import sqlite3\n"
IMPORT_NEW = "import sqlite3\nfrom contextlib import closing\n"
EXPECTED = 10


def main() -> None:
    text = TARGET.read_text(encoding="utf-8")
    count = text.count(OLD)
    if count != EXPECTED:
        raise RuntimeError(f"expected {EXPECTED} plain storage source SQLite contexts, found {count}")
    if "from contextlib import closing" not in text:
        if IMPORT_OLD not in text:
            raise RuntimeError("sqlite3 import anchor missing")
        text = text.replace(IMPORT_OLD, IMPORT_NEW, 1)
    text = text.replace(OLD, NEW)
    if OLD in text:
        raise RuntimeError("plain storage source SQLite contexts remain")
    TARGET.write_text(text, encoding="utf-8")
    print(f"STORAGE_SOURCE_CONNECTION_CONTEXTS_MIGRATED={count}")


if __name__ == "__main__":
    main()
