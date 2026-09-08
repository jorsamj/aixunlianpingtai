from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any

from .material_repository import MaterialRepository, normalize_material


_SQL_ID_BATCH = 500


def _unique_ids(values: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _chunks(values: list[str], size: int = _SQL_ID_BATCH):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _chunked_get_many(self: MaterialRepository, image_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Fetch arbitrarily large ID sets without depending on SQLite variable limits."""
    ids = _unique_ids(image_ids)
    if not ids:
        return []
    by_id: dict[str, dict[str, Any]] = {}
    with self._connect() as database:
        for batch in _chunks(ids):
            placeholders = ",".join("?" for _ in batch)
            rows = database.execute(
                f"SELECT id, payload_json FROM materials WHERE id IN ({placeholders})",
                batch,
            ).fetchall()
            by_id.update({str(row["id"]): self._row_payload(row) for row in rows})
    return [by_id[image_id] for image_id in ids if image_id in by_id]


def _chunked_remove(self: MaterialRepository, image_ids: Iterable[str]) -> list[dict[str, Any]]:
    """Delete very large selections in bounded SQL batches inside one transaction."""
    ids = _unique_ids(image_ids)
    if not ids:
        return []
    by_id: dict[str, dict[str, Any]] = {}
    with self._connect() as database:
        database.execute("BEGIN IMMEDIATE")
        try:
            for batch in _chunks(ids):
                placeholders = ",".join("?" for _ in batch)
                rows = database.execute(
                    f"SELECT id, payload_json FROM materials WHERE id IN ({placeholders})",
                    batch,
                ).fetchall()
                by_id.update({str(row["id"]): self._row_payload(row) for row in rows})
                if rows:
                    database.execute(
                        f"DELETE FROM materials WHERE id IN ({placeholders})",
                        [str(row["id"]) for row in rows],
                    )
            if by_id:
                self._bump_revision(database)
            database.execute("COMMIT")
        except Exception:
            database.execute("ROLLBACK")
            raise
    return [by_id[image_id] for image_id in ids if image_id in by_id]


def _chunked_mutate(self: MaterialRepository, fn):
    """Legacy mutate compatibility without full-table rewrite or unbounded DELETE IN clauses.

    The callback still receives all rows for legacy compatibility, so callers that scan every row
    should continue migrating to set-based APIs. Persisting changes is bounded and incremental.
    """
    with self._connect() as database:
        database.execute("BEGIN IMMEDIATE")
        try:
            stored = database.execute(
                "SELECT id, payload_json FROM materials ORDER BY created_at, id"
            ).fetchall()
            before_payload = {str(row["id"]): str(row["payload_json"]) for row in stored}
            rows = [self._row_payload(row) for row in stored]
            result = fn(rows)

            after: dict[str, dict[str, Any]] = {}
            after_payload: dict[str, str] = {}
            for value in rows:
                normalized = normalize_material(value)
                image_id = normalized["id"]
                if image_id in after:
                    raise ValueError(f"素材 id 重复：{image_id}")
                after[image_id] = normalized
                after_payload[image_id] = json.dumps(
                    normalized,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )

            deleted_ids = [image_id for image_id in before_payload if image_id not in after]
            changed_ids = [
                image_id
                for image_id, payload in after_payload.items()
                if before_payload.get(image_id) != payload
            ]

            for batch in _chunks(deleted_ids):
                placeholders = ",".join("?" for _ in batch)
                database.execute(
                    f"DELETE FROM materials WHERE id IN ({placeholders})",
                    batch,
                )
            for image_id in changed_ids:
                self._write_row(database, after[image_id])
            if deleted_ids or changed_ids:
                self._bump_revision(database)
            database.execute("COMMIT")
        except Exception:
            database.execute("ROLLBACK")
            raise
    return result


def install_material_repository_batch_guards() -> None:
    if getattr(MaterialRepository, "_large_id_guards_installed", False):
        return
    MaterialRepository.get_many = _chunked_get_many
    MaterialRepository.remove = _chunked_remove
    MaterialRepository.mutate = _chunked_mutate
    MaterialRepository._large_id_guards_installed = True


install_material_repository_batch_guards()
