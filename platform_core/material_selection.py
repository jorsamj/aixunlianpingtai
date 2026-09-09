from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Mapping, Sequence


MAX_EXPLICIT_MATERIAL_IDS = 1000
MAX_EXPLICIT_SELECTION_IDS = MAX_EXPLICIT_MATERIAL_IDS


def _normalized_values(values: Sequence[object] | None) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)):
        raise TypeError("multi-value material fields must be arrays")
    return tuple(dict.fromkeys(text for value in values or () if (text := str(value or "").strip())))


class SelectionScope(str, Enum):
    CURRENT_PAGE = "CURRENT_PAGE"
    SELECTED = "SELECTED"
    FILTERED = "FILTERED"


@dataclass(frozen=True)
class MaterialFilters:
    """Validated material-list filters shared by estimates, pages and workers."""

    query: str = ""
    name: str = ""
    storage_source_ids: tuple[str, ...] = ()
    processing_status: str | None = None
    split: str | None = None
    labels: tuple[str, ...] = ()
    annotated: bool | None = None
    annotation_state: str | None = None

    def __post_init__(self) -> None:
        query = str(self.query or "").strip()
        name = str(self.name or "").strip()
        if query and name and query != name:
            raise ValueError("query and name filters must match when both are provided")
        if self.annotated is not None and not isinstance(self.annotated, bool):
            raise TypeError("annotated must be a boolean or null")
        object.__setattr__(self, "query", query or name)
        object.__setattr__(self, "name", name)
        object.__setattr__(self, "storage_source_ids", _normalized_values(self.storage_source_ids))
        object.__setattr__(self, "labels", _normalized_values(self.labels))
        for field_name in ("processing_status", "split", "annotation_state"):
            value = getattr(self, field_name)
            object.__setattr__(self, field_name, str(value).strip().lower() if value is not None and str(value).strip() else None)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any] | None) -> "MaterialFilters":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("material filters must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown material filter fields: {', '.join(unknown)}")
        return cls(**dict(value))

    def as_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "storage_source_ids": list(self.storage_source_ids),
            "processing_status": self.processing_status,
            "split": self.split,
            "labels": list(self.labels),
            "annotated": self.annotated,
            "annotation_state": self.annotation_state,
        }


@dataclass(frozen=True)
class MaterialSelectionSpec:
    scope: SelectionScope
    filters: MaterialFilters = MaterialFilters()
    image_ids: tuple[str, ...] = ()
    repository_revision: int | None = None

    def __post_init__(self) -> None:
        try:
            scope = self.scope if isinstance(self.scope, SelectionScope) else SelectionScope(str(self.scope).strip().upper())
        except ValueError as error:
            raise ValueError("invalid material selection scope") from error
        filters = MaterialFilters.from_mapping(self.filters)
        image_ids = _normalized_values(self.image_ids)
        if len(image_ids) > MAX_EXPLICIT_MATERIAL_IDS:
            raise ValueError(f"explicit material selection is limited to {MAX_EXPLICIT_MATERIAL_IDS} ids")
        if scope is SelectionScope.FILTERED and image_ids:
            raise ValueError("FILTERED selection must not include explicit image ids")
        if scope is not SelectionScope.FILTERED and not image_ids:
            raise ValueError(f"{scope.value} selection requires image ids")
        revision = self.repository_revision
        if revision is not None:
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 0:
                raise ValueError("repository_revision must be a non-negative integer or null")
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "filters", filters)
        object.__setattr__(self, "image_ids", image_ids)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MaterialSelectionSpec":
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise TypeError("material selection must be an object")
        allowed = set(cls.__dataclass_fields__)
        unknown = sorted(set(value) - allowed)
        if unknown:
            raise ValueError(f"unknown material selection fields: {', '.join(unknown)}")
        return cls(**dict(value))

    def as_dict(self) -> dict[str, Any]:
        return {
            "scope": self.scope.value,
            "filters": self.filters.as_dict(),
            "image_ids": list(self.image_ids),
            "repository_revision": self.repository_revision,
        }
