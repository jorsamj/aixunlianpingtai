from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "platform_core" / "algorithms.py"
text = TARGET.read_text(encoding="utf-8")

old_import = "from .annotations import atomic_write_json\nfrom .errors import PlatformError\n"
new_import = "from .algorithm_sql_store import AlgorithmSqlStore\nfrom .errors import PlatformError\n"
if old_import not in text:
    raise SystemExit("expected algorithms.py storage import block not found")
text = text.replace(old_import, new_import, 1)

old_store = '''def list_algorithms(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PlatformError(
            code="ALGORITHM_STORE_INVALID",
            message="算法资产文件无法读取",
            detail=str(error),
            solution="请恢复 algorithms.json 备份，或检查文件是否为有效 JSON。",
            status_code=500,
        ) from error
    if not isinstance(value, list):
        raise PlatformError(
            code="ALGORITHM_STORE_INVALID",
            message="算法资产文件格式不正确",
            detail="algorithms.json 的根节点必须是数组。",
            solution="请恢复有效的算法资产文件。",
            status_code=500,
        )
    return value


def save_algorithms(path: Path, algorithms: Sequence[Mapping[str, Any]]) -> None:
    atomic_write_json(path, list(algorithms))
'''
new_store = '''def list_algorithms(path: Path) -> list[dict]:
    """Return algorithms in the legacy API shape, backed by SQL storage.

    The first read migrates an existing algorithms.json into algorithms.sqlite3
    without changing algorithm/version IDs. The JSON file is retained as a
    read-only migration source and backed up before SQL becomes authoritative.
    """
    return AlgorithmSqlStore(Path(path)).read_all()


def save_algorithms(path: Path, algorithms: Sequence[Mapping[str, Any]]) -> None:
    """Persist the full algorithm graph transactionally in SQL."""
    AlgorithmSqlStore(Path(path)).replace_all(algorithms)


def algorithm_store_status(path: Path) -> dict[str, Any]:
    """Expose migration/storage diagnostics without changing frontend payloads."""
    return AlgorithmSqlStore(Path(path)).migration_status()
'''
if old_store not in text:
    raise SystemExit("expected algorithms.py JSON list/save block not found")
text = text.replace(old_store, new_store, 1)
text = text.replace("import json\n", "", 1)
TARGET.write_text(text, encoding="utf-8")

STORE = ROOT / "platform_core" / "algorithm_sql_store.py"
store_text = STORE.read_text(encoding="utf-8")
old_analysis = '''    def _analysis_from_row(self, row: sqlite3.Row) -> dict:
        value = self._json_object(row["payload_json"])
        value["analysis_id"] = row["external_analysis_id"]
        if row["analysis_name"] is not None:
            value["analysis_name"] = row["analysis_name"]
        if row["analysis_type"] is not None:
            value["analysis_type"] = row["analysis_type"]
        value["compute_platform_ids"] = self._json_list(row["compute_platform_ids_json"])
        value["active"] = bool(row["active"])
        return value
'''
new_analysis = '''    def _analysis_from_row(self, row: sqlite3.Row) -> dict:
        value = self._json_object(row["payload_json"])
        value["analysis_id"] = row["external_analysis_id"]
        if row["analysis_name"] is not None:
            value["analysis_name"] = row["analysis_name"]
        if row["analysis_type"] is not None:
            value["analysis_type"] = row["analysis_type"]
        compute_platform_ids = self._json_list(row["compute_platform_ids_json"])
        if "compute_platform_ids" in value or compute_platform_ids:
            value["compute_platform_ids"] = compute_platform_ids
        if "active" in value or not bool(row["active"]):
            value["active"] = bool(row["active"])
        return value
'''
if old_analysis not in store_text:
    raise SystemExit("expected SQL analysis projection block not found")
STORE.write_text(store_text.replace(old_analysis, new_analysis, 1), encoding="utf-8")

print("algorithm store switched to SQL adapter with legacy API compatibility")
