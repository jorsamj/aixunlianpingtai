from __future__ import annotations

import os
from pathlib import Path

from .config import choose_data_dir


def resolve_data_dir(
    explicit: str | Path | None = None,
    *,
    base_dir: str | Path | None = None,
) -> Path:
    configured = explicit or os.environ.get("MC_TRAIN_DATA_DIR") or os.environ.get("MC_DATA_DIR")
    application_root = Path(base_dir or Path.cwd()).expanduser().resolve()
    if os.name == "nt":
        local_root = Path(
            os.environ.get("LOCALAPPDATA")
            or (Path.home() / "AppData" / "Local")
        )
        candidates = (
            local_root / "XJAlgo" / "data",
            local_root / "XiaojiangAlgorithmTrain" / "data",
            application_root / "data",
        )
    else:
        candidates = (application_root / "data",)
    return choose_data_dir(Path(configured) if configured else None, candidates)
