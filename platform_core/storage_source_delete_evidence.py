"""Cross-domain delete evidence for a storage source (U2 / A3).

Deleting a configured storage source is not a configuration-only action: the
materials that reference it, the model artifacts that record it and the physical
objects that live behind it must all be proven released first. A zero reference
count alone is *not* proof that objects were retired.

This module builds the evidence the PostgreSQL storage-source provider requires
(:meth:`PostgresStorageSourceRepository.delete`). It implements the material side
for real (indexed per-project counts, bounded by the caller's project list) and
requires the other domains to supply their own proofs:

* ``artifact_reference_counter(source)`` - owned by the model-artifact domain;
* ``physical_retirement_probe(source)`` - owned by the storage/NAS/OSS/S3
  retirement procedure, returning ``{"status": "RETIRED", "proof": <digest>}``.

An owner that is unavailable (callback missing, raising, or returning an
unexpected shape) makes the evidence incomplete, and the delete must be refused.
Neither callback is implemented by this batch, so a production delete still has
no end-to-end evidence path - that limitation is reported, not hidden.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from .material_repository import MaterialRepository
from .storage.source_repository import (
    DEFAULT_SCOPE,
    StorageSource,
    storage_source_config_digest,
)


class DeleteEvidenceError(RuntimeError):
    """The evidence needed to authorise deleting a source is unavailable."""

    def __init__(self, code: str, message: str, *, detail: str = ""):
        super().__init__(message)
        self.code = str(code)
        self.detail = str(detail or "")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def collect_delete_evidence(
    source: StorageSource,
    *,
    projects_root: str | Path | None = None,
    project_ids: Iterable[str] | None = None,
    scope: str = DEFAULT_SCOPE,
    material_count: Callable[[str, str], int] | None = None,
    artifact_reference_counter: Callable[[StorageSource], int] | None = None,
    physical_retirement_probe: Callable[[StorageSource], Mapping[str, Any]] | None = None,
    max_projects: int = 500,
) -> dict[str, Any]:
    """Build the delete evidence for one source, or refuse to guess.

    ``material_count(project_id, source_id)`` defaults to the indexed
    ``MaterialRepository.reference_count`` read of each project; passing it
    explicitly keeps the function usable from a caller that already batching the
    project scan. ``project_ids`` bounds the scan; a projects root without an
    explicit id list is enumerated in a bounded way and refused beyond
    ``max_projects`` instead of scanning an unbounded directory.
    """
    source_id = str(source.id)
    project_list = [str(value) for value in (project_ids or [])]
    if not project_list and projects_root is not None:
        root = Path(projects_root)
        if root.is_dir():
            children = [child.name for child in sorted(root.iterdir()) if child.is_dir()]
            if len(children) > int(max_projects):
                raise DeleteEvidenceError(
                    "STORAGE_SOURCE_DELETE_EVIDENCE_INCOMPLETE",
                    "the project scan is unbounded",
                    detail=f"projects={len(children)} limit={int(max_projects)}",
                )
            project_list = children
    if material_count is None:
        if projects_root is None or not project_list:
            raise DeleteEvidenceError(
                "STORAGE_SOURCE_DELETE_EVIDENCE_INCOMPLETE",
                "the material project scope could not be established",
                detail=(
                    "an empty or unproven project list is not zero references; "
                    "pass projects_root or an explicit complete project_ids list"
                ),
            )
        missing = [
            project_id
            for project_id in project_list
            if not (Path(projects_root) / project_id).is_dir()
        ]
        if missing:
            raise DeleteEvidenceError(
                "STORAGE_SOURCE_DELETE_EVIDENCE_INCOMPLETE",
                "the material project scope is incomplete",
                detail=f"missing_projects={missing}",
            )
    materials = 0
    for project_id in project_list:
        if material_count is not None:
            materials += int(material_count(project_id, source_id))
            continue
        repository = MaterialRepository(Path(projects_root) / project_id)
        materials += int(repository.reference_count(source_id))

    if artifact_reference_counter is None:
        raise DeleteEvidenceError(
            "STORAGE_SOURCE_DELETE_EVIDENCE_OWNER_UNAVAILABLE",
            "the model-artifact owner is unavailable for this delete",
            detail="artifact_reference_counter is required",
        )
    try:
        artifacts = int(artifact_reference_counter(source))
    except DeleteEvidenceError:
        raise
    except Exception as error:  # noqa: BLE001 - an unavailable owner is not "zero"
        raise DeleteEvidenceError(
            "STORAGE_SOURCE_DELETE_EVIDENCE_OWNER_UNAVAILABLE",
            "the model-artifact owner could not answer",
            detail=str(error),
        ) from error

    if physical_retirement_probe is None:
        raise DeleteEvidenceError(
            "STORAGE_SOURCE_DELETE_EVIDENCE_OWNER_UNAVAILABLE",
            "the storage retirement procedure is unavailable for this delete",
            detail="physical_retirement_probe is required",
        )
    try:
        retirement = dict(physical_retirement_probe(source) or {})
    except Exception as error:  # noqa: BLE001 - an unavailable owner is not "retired"
        raise DeleteEvidenceError(
            "STORAGE_SOURCE_DELETE_EVIDENCE_OWNER_UNAVAILABLE",
            "the storage retirement procedure could not answer",
            detail=str(error),
        ) from error
    if str(retirement.get("status") or "").upper() != "RETIRED" or not str(
        retirement.get("proof") or ""
    ).strip():
        raise DeleteEvidenceError(
            "STORAGE_SOURCE_DELETE_RETIREMENT_UNPROVEN",
            "the physical objects are not proven retired",
            detail=f"status={retirement.get('status')!r}",
        )

    return {
        "scope": str(scope),
        "source_id": source_id,
        "config_digest": storage_source_config_digest(source),
        "operation_id": str(uuid.uuid4().hex),
        "source_revision": int(source.runtime_revision),
        "material_references": materials,
        "artifact_references": artifacts,
        "physical_retirement": {
            "status": "RETIRED",
            "proof": str(retirement["proof"]),
        },
        "checked_at": _now(),
        "projects_scanned": len(project_list),
    }
