from __future__ import annotations

from pathlib import Path
from typing import Mapping


def build_paddle_command(
    *,
    python: str | Path,
    script: str | Path,
    config: str | Path,
    overrides: Mapping[str, str | int | float | bool],
) -> list[str]:
    """Build a PaddleDetection command without shell parsing.

    Every path is a distinct argv token, so spaces and platform-specific path
    separators are handled by the operating system rather than string parsing.
    """

    command = [str(Path(python)), "-u", str(Path(script)), "-c", str(Path(config))]
    for key, value in sorted(overrides.items()):
        if not isinstance(value, (str, int, float, bool)):
            raise TypeError("Paddle override values must be scalar")
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        command.extend(["-o", f"{key}={rendered}"])
    return command
