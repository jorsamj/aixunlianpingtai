from __future__ import annotations

from pathlib import Path


PATH = Path("platform_core/storage/import_tasks.py")


def replace_once(text: str, old: str, new: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one migration anchor, found {count}: {old[:80]!r}")
    return text.replace(old, new, 1)


def main() -> None:
    text = PATH.read_text(encoding="utf-8")

    text = replace_once(
        text,
        '''        if not isinstance(confirmation, dict) or confirmation.get("accepted") is not True:\n            raise ValueError("material import confirmation is missing")\n        store = ImportCandidateStore(\n''',
        '''        if not isinstance(confirmation, dict) or confirmation.get("accepted") is not True:\n            raise ValueError("material import confirmation is missing")\n        if context.cancel_requested():\n            return TaskStatus.CANCELLED, None\n        store = ImportCandidateStore(\n''',
    )

    text = replace_once(
        text,
        '''        store.assign_image_ids(context.task.task_id, batch_size=BATCH_SIZE)\n        materials = MaterialRepository(\n''',
        '''        if context.cancel_requested():\n            return TaskStatus.CANCELLED, None\n        store.assign_image_ids(context.task.task_id, batch_size=BATCH_SIZE)\n        if context.cancel_requested():\n            return TaskStatus.CANCELLED, None\n        materials = MaterialRepository(\n''',
    )

    text = replace_once(
        text,
        '''            by_reference = materials.get_by_storage_references(\n                (row["storage_source_id"], row["object_key"]) for row in batch\n            )\n            existing_hashes = materials.find_existing_content_hashes(\n                row["content_sha256"] for row in batch\n            )\n''',
        '''            by_reference = materials.get_by_storage_references(\n                (row["storage_source_id"], row["object_key"]) for row in batch\n            )\n            if context.cancel_requested():\n                return TaskStatus.CANCELLED, None\n            existing_hashes = materials.find_existing_content_hashes(\n                row["content_sha256"] for row in batch\n            )\n            if context.cancel_requested():\n                return TaskStatus.CANCELLED, None\n''',
    )

    text = replace_once(
        text,
        '''                accepted_hashes.add(content_hash)\n                resolved.append(row)\n            store.bind_index_batch(resolved)\n            by_id = {r['id']: r for r in materials.get_many(row['image_id'] for row in resolved)}\n            imported_annotations = store.annotations_for_keys(row['object_key'] for row in resolved)\n            skipped = store.skipped_boxes_for_keys(row['object_key'] for row in resolved)\n''',
        '''                accepted_hashes.add(content_hash)\n                resolved.append(row)\n            if context.cancel_requested():\n                return TaskStatus.CANCELLED, None\n            store.bind_index_batch(resolved)\n            by_id = {r['id']: r for r in materials.get_many(row['image_id'] for row in resolved)}\n            imported_annotations = store.annotations_for_keys(row['object_key'] for row in resolved)\n            skipped = store.skipped_boxes_for_keys(row['object_key'] for row in resolved)\n            if context.cancel_requested():\n                return TaskStatus.CANCELLED, None\n''',
    )

    text = replace_once(
        text,
        '''            # Material identity is durable before annotation writes. Replaying the\n            # same deterministic boxes preserves annotation version/content digest.\n            materials.upsert_many(records)\n            annotations.upsert_many(annotation_rows)\n            store.record_annotation_outcomes(resolved)\n            store.mark_indexed(batch)\n''',
        '''            # Material identity is durable before annotation writes. Replaying the\n            # same deterministic boxes preserves annotation version/content digest.\n            if context.cancel_requested():\n                return TaskStatus.CANCELLED, None\n            materials.upsert_many(records)\n            if context.cancel_requested():\n                return TaskStatus.CANCELLED, None\n            annotations.upsert_many(annotation_rows)\n            if context.cancel_requested():\n                return TaskStatus.CANCELLED, None\n            store.record_annotation_outcomes(resolved)\n            if context.cancel_requested():\n                return TaskStatus.CANCELLED, None\n            store.mark_indexed(batch)\n''',
    )

    PATH.write_text(text, encoding="utf-8")


if __name__ == "__main__":
    main()
