"""Bounded discovery of local Python interpreter candidates.

This module only finds executable paths.  It deliberately does not import or
probe Python packages; :mod:`platform_core.resource_discovery.probe` owns that
separate, potentially expensive step.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


CONDA_DISCOVERY_TIMEOUT_SECONDS = 10.0
_MAX_DIRECTORY_ENTRIES = 16_384
_MAX_CONDA_ENVIRONMENTS = 4_096
_PYTHON_NAME = re.compile(r"^python(?:3(?:\.\d+)*)?(?:\.exe)?$", re.IGNORECASE)


@dataclass(frozen=True)
class PythonCandidate:
    """One executable path together with every bounded discovery source."""

    path: Path
    sources: tuple[str, ...]


@dataclass(frozen=True)
class DiscoveryContext:
    """Inputs for a deterministic fast-discovery pass.

    Production callers normally use :meth:`from_system`.  Explicit fields make
    the discovery policy usable by workers and independently testable without
    mutating global process state.
    """

    project_root: Path
    saved_environment: Mapping[str, Any] = field(default_factory=dict)
    environment: Mapping[str, str] = field(default_factory=lambda: dict(os.environ))
    system_python: Path = field(default_factory=lambda: Path(sys.executable))
    home: Path = field(default_factory=Path.home)
    platform: str = field(default_factory=lambda: sys.platform)
    path_entries: tuple[Path, ...] | None = None
    ultralytics_roots: tuple[Path, ...] = ()
    conda_executable: str | os.PathLike[str] | None = None
    command_runner: Callable[..., Any] | None = field(
        default=None, repr=False, compare=False
    )

    @classmethod
    def from_system(
        cls,
        project_root: str | os.PathLike[str] | None = None,
        *,
        saved_environment: Mapping[str, Any] | None = None,
    ) -> "DiscoveryContext":
        return cls(
            project_root=Path(project_root or Path.cwd()),
            saved_environment=dict(saved_environment or {}),
        )


def _absolute_path(path: str | os.PathLike[str]) -> Path | None:
    try:
        raw = os.fspath(path).strip()
        if not raw or "\x00" in raw:
            return None
        return Path(os.path.abspath(os.path.expanduser(raw)))
    except (OSError, TypeError, ValueError):
        return None


def _identity(path: Path) -> str:
    # Do not resolve symlinks here: invoking a venv symlink is semantically
    # different from invoking its base interpreter even if both point to the
    # same inode.
    return os.path.normcase(os.path.normpath(os.fspath(path)))


def _is_python_file(path: Path) -> bool:
    try:
        if not _PYTHON_NAME.fullmatch(path.name) or not path.is_file():
            return False
        return os.name == "nt" or os.access(path, os.X_OK)
    except OSError:
        return False


def _iter_directory(directory: Path) -> tuple[Path, ...]:
    """Return one bounded directory level, swallowing inaccessible paths."""

    rows: list[Path] = []
    try:
        with os.scandir(directory) as entries:
            for index, entry in enumerate(entries):
                if index >= _MAX_DIRECTORY_ENTRIES:
                    break
                rows.append(Path(entry.path))
    except (OSError, ValueError):
        return ()
    return tuple(rows)


def _prefix_python_paths(prefix: Path) -> tuple[Path, ...]:
    """Check executable layouts immediately beneath one environment prefix."""

    if _is_python_file(prefix):
        return (prefix,)
    names = (
        prefix / "python.exe",
        prefix / "python3.exe",
        prefix / "python",
        prefix / "python3",
        prefix / "Scripts" / "python.exe",
        prefix / "Scripts" / "python3.exe",
        prefix / "bin" / "python",
        prefix / "bin" / "python3",
    )
    return tuple(path for path in names if _is_python_file(path))


def _environment_children(root: Path) -> tuple[Path, ...]:
    """Find interpreters in immediate child environment/install directories."""

    found: list[Path] = []
    found.extend(_prefix_python_paths(root))
    for child in _iter_directory(root):
        try:
            if child.is_dir():
                found.extend(_prefix_python_paths(child))
        except OSError:
            continue
    return tuple(found)


def _path_directories(context: DiscoveryContext) -> tuple[Path, ...]:
    if context.path_entries is not None:
        raw_entries: Sequence[str | os.PathLike[str]] = context.path_entries
    else:
        raw_entries = tuple(
            part
            for part in str(context.environment.get("PATH", "")).split(os.pathsep)
            if part
        )
    result: list[Path] = []
    for raw in raw_entries:
        path = _absolute_path(raw)
        if path is not None:
            result.append(path)
    return tuple(result)


def _configured_roots(context: DiscoveryContext) -> tuple[Path, ...]:
    roots: list[Path] = []
    roots.extend(context.ultralytics_roots)
    configured = str(context.environment.get("MC_ULTRALYTICS_ROOTS", ""))
    roots.extend(
        Path(part.strip()) for part in configured.split(os.pathsep) if part.strip()
    )
    return tuple(roots)


def _conda_command(context: DiscoveryContext) -> str | None:
    if context.conda_executable:
        path = _absolute_path(context.conda_executable)
        return os.fspath(path) if path is not None and path.is_file() else None
    return shutil.which("conda", path=str(context.environment.get("PATH", "")))


def _conda_prefixes(context: DiscoveryContext) -> tuple[Path, ...]:
    command = _conda_command(context)
    if not command:
        return ()
    runner = context.command_runner or subprocess.run
    try:
        completed = runner(
            [command, "env", "list", "--json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=CONDA_DISCOVERY_TIMEOUT_SECONDS,
            check=False,
            shell=False,
        )
        if int(getattr(completed, "returncode", 1)) != 0:
            return ()
        payload = json.loads(str(getattr(completed, "stdout", "") or ""))
    except (OSError, subprocess.SubprocessError, TypeError, ValueError, json.JSONDecodeError):
        return ()
    envs = payload.get("envs") if isinstance(payload, Mapping) else None
    if not isinstance(envs, Sequence) or isinstance(envs, (str, bytes, bytearray)):
        return ()
    result: list[Path] = []
    for value in envs[:_MAX_CONDA_ENVIRONMENTS]:
        if isinstance(value, (str, os.PathLike)):
            path = _absolute_path(value)
            if path is not None:
                result.append(path)
    return tuple(result)


def discover_fast_python_candidates(
    context: DiscoveryContext | None = None,
) -> list[PythonCandidate]:
    """Discover likely Python executables without recursive whole-disk scans.

    Every returned path exists and is a file.  Discovery sources are merged for
    duplicate paths so later UI and audit layers can explain every match.
    No interpreter is executed here except the bounded ``conda env list`` query;
    package validation remains a separate probe step.
    """

    ctx = context or DiscoveryContext.from_system()
    candidates: dict[str, tuple[Path, list[str]]] = {}

    def add(path_value: str | os.PathLike[str], source: str) -> None:
        path = _absolute_path(path_value)
        if path is None or not _is_python_file(path):
            return
        key = _identity(path)
        current = candidates.get(key)
        if current is None:
            candidates[key] = (path, [source])
        elif source not in current[1]:
            current[1].append(source)

    def add_prefix(prefix_value: str | os.PathLike[str], source: str) -> None:
        prefix = _absolute_path(prefix_value)
        if prefix is None:
            return
        for path in _prefix_python_paths(prefix):
            add(path, source)

    def add_children(root_value: str | os.PathLike[str], source: str) -> None:
        root = _absolute_path(root_value)
        if root is None:
            return
        for path in _environment_children(root):
            add(path, source)

    add(ctx.system_python, "system_executable")

    saved = ctx.saved_environment
    saved_python = saved.get("python_path") if isinstance(saved, Mapping) else None
    if isinstance(saved_python, (str, os.PathLike)):
        add(saved_python, "saved_environment")

    for path_directory in _path_directories(ctx):
        for entry in _iter_directory(path_directory):
            if _is_python_file(entry):
                add(entry, "path")

    virtual_env = ctx.environment.get("VIRTUAL_ENV", "")
    if virtual_env:
        add_prefix(virtual_env, "virtual_env")
    conda_prefix = ctx.environment.get("CONDA_PREFIX", "")
    if conda_prefix:
        add_prefix(conda_prefix, "conda_prefix")

    project = _absolute_path(ctx.project_root)
    if project is not None:
        add_prefix(project / ".venv", "project_venv")
        add_prefix(project / "venv", "project_venv")

    for prefix in _conda_prefixes(ctx):
        add_prefix(prefix, "conda_env_list")

    home = _absolute_path(ctx.home)
    if home is not None:
        add_children(home / ".conda" / "envs", "user_conda")
        add_prefix(home / "anaconda3", "user_conda")
        add_prefix(home / "miniconda3", "user_conda")
        add_children(home / ".pyenv" / "versions", "user_python")
        add_children(home / ".local" / "bin", "user_python")

    if ctx.platform.startswith("win"):
        local_appdata = ctx.environment.get("LOCALAPPDATA", "")
        appdata = ctx.environment.get("APPDATA", "")
        if home is not None:
            local_appdata = local_appdata or os.fspath(home / "AppData" / "Local")
            appdata = appdata or os.fspath(home / "AppData" / "Roaming")
        for base_value in (local_appdata, appdata):
            if not base_value:
                continue
            base = _absolute_path(base_value)
            if base is None:
                continue
            add_children(base / "Programs" / "Python", "appdata_python")
            add_prefix(base / "Programs" / "Python", "appdata_python")
            add_prefix(base / "anaconda3", "appdata_conda")
            add_prefix(base / "miniconda3", "appdata_conda")
            add_children(base / ".conda" / "envs", "appdata_conda")

        program_roots = {
            value
            for name in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432")
            if (value := str(ctx.environment.get(name, "")).strip())
        }
        for base_value in sorted(program_roots, key=os.path.normcase):
            base = _absolute_path(base_value)
            if base is None:
                continue
            # One level is sufficient for Python311, Anaconda3, Miniconda3,
            # and similarly shaped installs without traversing Program Files.
            add_children(base, "program_files")

    for key in ("root", "weights_dir"):
        value = saved.get(key) if isinstance(saved, Mapping) else None
        if not isinstance(value, (str, os.PathLike)) or not value:
            continue
        hint = _absolute_path(value)
        if hint is None:
            continue
        add_prefix(hint, "ultralytics_hint")
        add_prefix(hint / ".venv", "ultralytics_hint")
        add_prefix(hint / "venv", "ultralytics_hint")
        # A weights directory is commonly adjacent to the project venv.
        add_prefix(hint.parent / ".venv", "ultralytics_hint")
        add_prefix(hint.parent / "venv", "ultralytics_hint")

    for root in _configured_roots(ctx):
        hint = _absolute_path(root)
        if hint is None:
            continue
        add_prefix(hint, "configured_root")
        add_prefix(hint / ".venv", "configured_root")
        add_prefix(hint / "venv", "configured_root")

    return [
        PythonCandidate(path=path, sources=tuple(sources))
        for path, sources in sorted(
            candidates.values(), key=lambda item: _identity(item[0])
        )
    ]
