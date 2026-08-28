import json
from pathlib import Path
from typing import Iterable, Optional


def _project_count(path: Path) -> int:
    try:
        value = json.loads((path / "projects.json").read_text(encoding="utf-8"))
        return len(value) if isinstance(value, list) else 0
    except (OSError, ValueError, TypeError):
        return 0


def choose_data_dir(explicit: Optional[Path], candidates: Iterable[Path]) -> Path:
    if explicit is not None:
        return explicit.expanduser().resolve()
    resolved = [Path(item).expanduser().resolve() for item in candidates]
    if not resolved:
        raise ValueError("至少需要一个数据目录候选项")
    populated = [item for item in resolved if _project_count(item) > 0]
    return max(populated, key=_project_count) if populated else resolved[0]

