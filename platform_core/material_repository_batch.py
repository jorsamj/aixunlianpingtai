from __future__ import annotations

import json
from collections.abc import Iterable
from typing import Any, Mapping

from .material_repository import MaterialRepository, normalize_material
from .material_selection import MaterialFilters


_SQL_ID_BATCH = 500
MUTABLE_MATERIAL_FIELDS = frozenset({
    "filename", "processing_status", "split", "labels", "label_counts",
    "box_count", "annotated", "annotation_state", "annotation_status",
    "annotation_preview", "annotation_summary_at", "negative_sample",
    "cleaned_at", "updated_at", "width", "height", "dataset_id",
})


def _unique_ids(values: Iterable[object]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values if str(value)))


def _chunks(values: list[str], size: int = _SQL_ID_BATCH):
    for index in range(0, len(values), size):
        yield values[index : index + size]


def _bounded_batch_size(value: int) -> int:
    size = int(value)
    if size < 1 or size > _SQL_ID_BATCH:
        raise ValueError(f"batch_size must be between 1 and {_SQL_ID_BATCH}")
    return size


def _id_batches(values: Iterable[object], batch_size: int):
    size = _bounded_batch_size(batch_size)
    seen: set[str] = set()
    batch: list[str] = []
    for value in values:
        image_id = str(value or "").strip()
        if not image_id or image_id in seen:
            continue
        seen.add(image_id)
        batch.append(image_id)
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _validate_patch(patch: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(patch, Mapping):
        raise TypeError("material patch must be an object")
    unknown = sorted(set(patch) - MUTABLE_MATERIAL_FIELDS)
    if unknown:
        raise ValueError(f"material fields are not mutable: {', '.join(unknown)}")
    return dict(patch)


def _persist_batch(database, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    payloads = []
    label_rows = []
    for row in rows:
        payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        payloads.append((
            row["filename"], row["storage_source_id"], row["storage_type"],
            row["object_key"], row["content_sha256"], row["size_bytes"], row["etag"],
            row["processing_status"], row["box_count"], int(row["annotated"]),
            row["created_at"], row["updated_at"], payload, row["id"],
        ))
        label_rows.extend((row["id"], label) for label in row["labels"])
    database.executemany(
        "UPDATE materials SET filename=?, storage_source_id=?, storage_type=?, object_key=?, "
        "content_sha256=?, size_bytes=?, etag=?, processing_status=?, box_count=?, annotated=?, "
        "created_at=?, updated_at=?, payload_json=? WHERE id=?",
        payloads,
    )
    ids = [row["id"] for row in rows]
    placeholders = ",".join("?" for _ in ids)
    database.execute(f"DELETE FROM material_labels WHERE material_id IN ({placeholders})", ids)
    if label_rows:
        database.executemany(
            "INSERT INTO material_labels(material_id, label_code) VALUES (?, ?)", label_rows,
        )


def _transform_many(
    self: MaterialRepository, image_ids: Iterable[object], transform, *, batch_size: int,
) -> int:
    changed_count = 0
    for batch in _id_batches(image_ids, batch_size):
        placeholders = ",".join("?" for _ in batch)
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                stored = database.execute(
                    f"SELECT id, payload_json FROM materials WHERE id IN ({placeholders})", batch,
                ).fetchall()
                changed = []
                for stored_row in stored:
                    before = self._row_payload(stored_row)
                    candidate = transform(dict(before))
                    normalized = normalize_material(candidate)
                    before_json = json.dumps(
                        normalize_material(before), ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    )
                    after_json = json.dumps(
                        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    )
                    if before_json != after_json:
                        changed.append(normalized)
                _persist_batch(database, changed)
                if changed:
                    self._bump_revision(database)
                database.execute("COMMIT")
                changed_count += len(changed)
            except Exception:
                database.execute("ROLLBACK")
                raise
    return changed_count


def _patch_many(
    self: MaterialRepository, image_ids: Iterable[object], patch: Mapping[str, Any],
    batch_size: int = _SQL_ID_BATCH,
) -> int:
    values = _validate_patch(patch)

    def apply(row):
        row.update(values)
        return row

    return _transform_many(self, image_ids, apply, batch_size=batch_size)


def _patch_filtered(
    self: MaterialRepository, filters: MaterialFilters | Mapping[str, Any] | None,
    patch: Mapping[str, Any], expected_revision: int | None = None,
    batch_size: int = _SQL_ID_BATCH,
) -> int:
    selected = MaterialFilters.from_mapping(filters)
    if expected_revision is not None and self.current_revision() != int(expected_revision):
        raise ValueError("material repository revision changed; re-estimate before confirming")
    changed = 0
    cursor = None
    while True:
        page = self.iter_filtered_ids(
            selected, cursor=cursor, limit=_bounded_batch_size(batch_size), include_total=False,
        )
        if not page.items:
            break
        changed += self.patch_many(page.items, patch, batch_size=batch_size)
        cursor = page.next_cursor
        if not cursor:
            break
    return changed


def _add_labels_many(
    self: MaterialRepository, image_ids: Iterable[object], labels: Iterable[object],
    batch_size: int = _SQL_ID_BATCH,
) -> int:
    additions = {str(label or "").strip() for label in labels}
    additions.discard("")
    if not additions:
        return 0
    return _transform_many(
        self, image_ids,
        lambda row: {**row, "labels": sorted({*row.get("labels", ()), *additions})},
        batch_size=batch_size,
    )


def _remove_labels_many(
    self: MaterialRepository, image_ids: Iterable[object], labels: Iterable[object],
    batch_size: int = _SQL_ID_BATCH,
) -> int:
    removals = {str(label or "").strip() for label in labels}
    removals.discard("")
    if not removals:
        return 0
    return _transform_many(
        self, image_ids,
        lambda row: {**row, "labels": [label for label in row.get("labels", ()) if label not in removals]},
        batch_size=batch_size,
    )


def _remove_many(
    self: MaterialRepository, image_ids: Iterable[object], batch_size: int = _SQL_ID_BATCH,
) -> int:
    removed = 0
    for batch in _id_batches(image_ids, batch_size):
        placeholders = ",".join("?" for _ in batch)
        with self._connect() as database:
            database.execute("BEGIN IMMEDIATE")
            try:
                cursor = database.execute(
                    f"DELETE FROM materials WHERE id IN ({placeholders})", batch,
                )
                count = max(0, int(cursor.rowcount))
                if count:
                    self._bump_revision(database)
                database.execute("COMMIT")
                removed += count
            except Exception:
                database.execute("ROLLBACK")
                raise
    return removed


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
    MaterialRepository.patch_many = _patch_many
    MaterialRepository.patch_filtered = _patch_filtered
    MaterialRepository.add_labels_many = _add_labels_many
    MaterialRepository.remove_labels_many = _remove_labels_many
    MaterialRepository.remove_many = _remove_many
    MaterialRepository._large_id_guards_installed = True


install_material_repository_batch_guards()
