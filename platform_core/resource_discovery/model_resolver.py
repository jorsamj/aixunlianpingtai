"""Ordered, side-effect-free resolution of Ultralytics model references."""
from __future__ import annotations

import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .cache import DiscoveryCache


OFFICIAL_DOWNLOADABLE_MODELS = frozenset(
    {"yolo11n.pt", "yolo11s.pt", "yolo11m.pt"}
)


@dataclass(frozen=True)
class ModelResolution:
    status: str
    path: Path | None
    reference: str
    source: str
    downloadable: bool
    environment_status: str
    searched_locations: tuple[str, ...]

    @property
    def found(self) -> bool:
        return self.status == "FOUND" and self.path is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "model_status": self.status,
            "model_path": str(self.path) if self.path is not None else "",
            "model_reference": self.reference,
            "model_source": self.source,
            "downloadable": self.downloadable,
            "environment_status": self.environment_status,
            "searched_locations": list(self.searched_locations),
        }


def _path_text(value: object) -> str:
    if value is None:
        return ""
    try:
        return os.fspath(value).strip()
    except TypeError:
        return str(value).strip()


def _is_path_reference(value: str) -> bool:
    path = Path(value)
    return path.is_absolute() or "/" in value or "\\" in value


def _iter_paths(values: Iterable[object] | None) -> Iterable[Path]:
    for value in values or ():
        if isinstance(value, Mapping):
            value = value.get("path") or value.get("stored_path")
        text = _path_text(value)
        if text:
            yield Path(text).expanduser()


class ModelResolver:
    """Resolve model names in a deterministic order without downloading them."""

    def __init__(
        self,
        *,
        selected_environment: Mapping[str, Any] | None = None,
        discovery_cache: DiscoveryCache | None = None,
        project_model_dirs: Iterable[str | os.PathLike[str]] = (),
        project_models: Iterable[Mapping[str, Any] | str | os.PathLike[str]] = (),
        algorithm_versions: Iterable[Mapping[str, Any] | str | os.PathLike[str]] = (),
        platform_model_dirs: Iterable[str | os.PathLike[str]] = (),
        cwd: str | os.PathLike[str] | None = None,
        environment_status: str | None = None,
    ) -> None:
        self.environment = dict(selected_environment or {})
        self.discovery_cache = discovery_cache
        self.project_model_dirs = tuple(Path(value).expanduser() for value in project_model_dirs)
        self.project_models = tuple(project_models)
        self.algorithm_versions = tuple(algorithm_versions)
        self.platform_model_dirs = tuple(Path(value).expanduser() for value in platform_model_dirs)
        self.cwd = Path(cwd).expanduser() if cwd is not None else Path.cwd()
        self.environment_status = str(
            environment_status
            or self.environment.get("status")
            or ("AVAILABLE" if self.environment else "UNKNOWN")
        ).upper()

    @staticmethod
    def _existing_file(candidate: Path) -> Path | None:
        try:
            return candidate.resolve() if candidate.is_file() else None
        except OSError:
            return None

    @staticmethod
    def _unique_paths(paths: Iterable[Path]) -> Iterable[Path]:
        seen: set[str] = set()
        for path in paths:
            key = os.path.normcase(os.path.abspath(os.fspath(path)))
            if key not in seen:
                seen.add(key)
                yield path

    def _environment_candidates(self, name: str) -> Iterable[Path]:
        environment = self.environment
        direct_models = environment.get("models")
        if isinstance(direct_models, list):
            for path in _iter_paths(direct_models):
                if path.name.casefold() == name.casefold():
                    yield path

        directories: list[Path] = []
        model_dirs = environment.get("model_dirs")
        if isinstance(model_dirs, (list, tuple)):
            directories.extend(_iter_paths(model_dirs))
        root_text = _path_text(environment.get("root"))
        if root_text:
            root = Path(root_text).expanduser()
            directories.extend((root / "models", root))
        for directory in directories:
            yield directory / name

    def _weights_candidates(self, name: str) -> Iterable[Path]:
        value = _path_text(self.environment.get("weights_dir"))
        if not value:
            return
        weights_dir = Path(value).expanduser()
        if not weights_dir.is_absolute():
            root = _path_text(self.environment.get("root"))
            weights_dir = (Path(root) if root else self.cwd) / weights_dir
        yield weights_dir / name

    def _cache_candidates(self, name: str) -> Iterable[Path]:
        if self.discovery_cache is None:
            return
        try:
            rows = self.discovery_cache.find_models_by_name((name,))
        except (OSError, ValueError):
            return
        for path in _iter_paths(rows):
            yield path

    def _project_candidates(self, name: str) -> Iterable[Path]:
        for directory in self.project_model_dirs:
            yield directory / name
        for path in _iter_paths((*self.project_models, *self.algorithm_versions)):
            if path.name.casefold() == name.casefold():
                yield path

    def _platform_candidates(self, name: str) -> Iterable[Path]:
        for directory in self.platform_model_dirs:
            yield directory / name

        home = Path.home()
        config_root = _path_text(os.environ.get("YOLO_CONFIG_DIR"))
        if config_root:
            yield Path(config_root).expanduser() / "weights" / name
        for directory in (
            home / ".cache" / "ultralytics" / "weights",
            home / ".cache" / "ultralytics",
            home / ".cache" / "torch" / "hub" / "checkpoints",
            home / ".config" / "Ultralytics" / "weights",
            home / "AppData" / "Roaming" / "Ultralytics" / "weights",
        ):
            yield directory / name

    def resolve(self, model_reference: str, *, project_id: str | None = None) -> ModelResolution:
        del project_id  # The caller supplies project-specific directories and records.
        reference = _path_text(model_reference)
        if not reference:
            return ModelResolution(
                "MISSING", None, "", "empty", False,
                self.environment_status, (),
            )

        searched: list[str] = []
        if _is_path_reference(reference):
            candidate = Path(reference).expanduser()
            searched.append(str(candidate))
            found = self._existing_file(candidate)
            return ModelResolution(
                "FOUND" if found else "MISSING",
                found,
                reference,
                "explicit_path" if found else "missing_explicit_path",
                False,
                self.environment_status,
                tuple(searched),
            )

        name = Path(reference).name
        ordered_sources = (
            ("selected_environment", self._environment_candidates(name)),
            ("weights_dir", self._weights_candidates(name)),
            ("discovery_cache", self._cache_candidates(name)),
            ("project", self._project_candidates(name)),
            ("platform_cache", self._platform_candidates(name)),
            ("cwd_compatibility", (self.cwd / name,)),
        )
        for source, candidates in ordered_sources:
            for candidate in self._unique_paths(candidates):
                searched.append(str(candidate))
                found = self._existing_file(candidate)
                if found is not None:
                    return ModelResolution(
                        "FOUND", found, reference, source, False,
                        self.environment_status, tuple(searched),
                    )

        downloadable = name.casefold() in OFFICIAL_DOWNLOADABLE_MODELS
        return ModelResolution(
            "MISSING",
            None,
            reference,
            "official_downloadable" if downloadable else "not_found",
            downloadable,
            self.environment_status,
            tuple(searched),
        )

