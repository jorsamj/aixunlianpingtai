from __future__ import annotations

import os
from pathlib import Path


def resolve_data_dir(explicit: str | Path | None = None) -> Path:
    configured = (
        explicit
        or os.environ.get("MC_TRAIN_DATA_DIR")
        or os.environ.get("MC_DATA_DIR")
        or "data"
    )
    return Path(configured).expanduser().resolve()
