from __future__ import annotations

import hashlib
import os
import re
import subprocess
from pathlib import Path
from typing import Any

_FINGERPRINT_FILES = (
    "app.py",
    "launcher.py",
    "task_worker.py",
    "train_worker.py",
    "platform_core/task_runtime/repository.py",
    "platform_core/training_tasks.py",
)


_FORMAL_VERSION_PATTERN = re.compile(r"^(0|[1-9]\\d*)\\.(0|[1-9]\\d*)\\.(0|[1-9]\\d*)$")
_MINIMUM_FORMAL_VERSION = (42, 24, 1)


def parse_formal_version(value: object) -> tuple[int, int, int]:
    text = str(value or "").strip()
    match = _FORMAL_VERSION_PATTERN.fullmatch(text)
    if match is None:
        raise ValueError("formal platform version must be MAJOR.MINOR.PATCH")
    return tuple(int(part) for part in match.groups())


def validate_formal_version(
    value: object,
    *,
    minimum: tuple[int, int, int] = _MINIMUM_FORMAL_VERSION,
) -> str:
    text = str(value or "").strip()
    version = parse_formal_version(text)
    if version < tuple(int(part) for part in minimum):
        floor = ".".join(str(part) for part in minimum)
        raise ValueError(f"formal platform version must be >= {floor}")
    return text


def read_formal_version(path: str | Path) -> str:
    return validate_formal_version(
        Path(path).read_text(encoding="utf-8", errors="strict")
    )


def _git_revision(base_dir: Path) -> str:
    if not (base_dir / ".git").exists():
        return ""
    try:
        completed = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=str(base_dir),
            capture_output=True,
            text=True,
            errors="replace",
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    value = (completed.stdout or "").strip().lower()
    return value if completed.returncode == 0 and re.fullmatch(r"[0-9a-f]{40}", value) else ""


def _source_fingerprint(base_dir: Path) -> str:
    digest = hashlib.sha256()
    count = 0
    for relative in _FINGERPRINT_FILES:
        path = base_dir / relative
        if not path.is_file():
            continue
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        count += 1
    return f"src-{digest.hexdigest()[:20]}" if count else "unknown"


def resolve_build_id(base_dir: str | Path) -> str:
    explicit = os.environ.get("MC_BUILD_REVISION", "").strip()
    if explicit:
        return explicit[:128]
    root = Path(base_dir).resolve()
    return _git_revision(root) or _source_fingerprint(root)


def service_matches_build(
    local_version: str,
    local_build_id: str,
    remote_version: str,
    remote_payload: dict[str, Any] | None,
) -> bool:
    remote_build_id = str((remote_payload or {}).get("build_id") or "").strip()
    return bool(
        remote_build_id
        and str(remote_version or "").strip() == str(local_version or "").strip()
        and remote_build_id == str(local_build_id or "").strip()
    )


def _main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Validate the formal platform version contract")
    parser.add_argument("--check-version-file", metavar="PATH")
    args = parser.parse_args(argv)
    if not args.check_version_file:
        parser.error("--check-version-file is required")
    print(read_formal_version(args.check_version_file))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
