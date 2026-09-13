from __future__ import annotations

from pathlib import Path


IMPORT_TASKS = Path("platform_core/storage/import_tasks.py")
REPOSITORY = Path("platform_core/task_runtime/repository.py")
FENCED_REPOSITORY = Path("platform_core/task_runtime/fenced_repository.py")
REPOSITORY_TEST = Path("tests/unit/task_runtime/test_repository.py")


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{label}: expected exactly one migration anchor, found {count}")
    return text.replace(old, new, 1)


def migrate_import_tasks() -> None:
    text = IMPORT_TASKS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''        context.repository.heartbeat(\n            context.task.task_id,\n            context.lease.lease_token,\n            progress=99,\n            stage="FINALIZING",\n''',
        '''        context.repository.heartbeat(\n            context.task.task_id,\n            context.lease.lease_token,\n            progress=50,\n            stage="FINALIZING",\n''',
        label="scan final progress",
    )
    text = replace_once(
        text,
        '''            context.save_checkpoint(checkpoint)\n            context.repository.heartbeat(\n                context.task.task_id,\n                context.lease.lease_token,\n                stage="indexing",\n                current_item=f"正在建立素材索引：已处理 {checkpoint['indexed_at_least']} / {selected_count}",\n            )\n''',
        '''            context.save_checkpoint(checkpoint)\n            indexing_progress = (\n                50.0\n                if selected_count <= 0\n                else min(99.0, 50.0 + 49.0 * indexed_at_least / selected_count)\n            )\n            context.repository.heartbeat(\n                context.task.task_id,\n                context.lease.lease_token,\n                progress=indexing_progress,\n                stage="indexing",\n                current_item=f"正在建立素材索引：已处理 {checkpoint['indexed_at_least']} / {selected_count}",\n            )\n''',
        label="indexing live progress",
    )
    IMPORT_TASKS.write_text(text, encoding="utf-8")


def migrate_repository(path: Path, *, fenced: bool) -> None:
    text = path.read_text(encoding="utf-8")
    text = replace_once(
        text,
        '''                UPDATE tasks SET status=?, result_ref=?, error=?, accepted=?, stage=?,\n                    progress=COALESCE(?, progress), finished_at=?, updated_at=?,\n''',
        '''                UPDATE tasks SET status=?, result_ref=?, error=?, accepted=?, stage=?,\n                    progress=CASE\n                        WHEN ?='AWAITING_CONFIRMATION' AND kind='MATERIAL_IMPORT'\n                            THEN MAX(progress, 50.0)\n                        ELSE COALESCE(?, progress)\n                    END,\n                    finished_at=?, updated_at=?,\n''',
        label=f"{path.name} material awaiting progress SQL",
    )
    text = replace_once(
        text,
        '''                    stage,\n                    progress,\n                    finished_at,\n''',
        '''                    stage,\n                    status.value,\n                    progress,\n                    finished_at,\n''',
        label=f"{path.name} material awaiting progress args",
    )
    if not fenced:
        text = replace_once(
            text,
            '''                    UPDATE tasks SET status='QUEUED', stage='indexing_queued', progress=0,\n''',
            '''                    UPDATE tasks SET status='QUEUED', stage='indexing_queued', progress=MAX(progress, 50.0),\n''',
            label="resume confirmation monotonic progress",
        )
    path.write_text(text, encoding="utf-8")


def migrate_existing_contract() -> None:
    text = REPOSITORY_TEST.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "    assert resumed.progress == 0\n",
        "    assert resumed.progress == 75\n",
        label="legacy confirmation progress contract",
    )
    REPOSITORY_TEST.write_text(text, encoding="utf-8")


def main() -> None:
    migrate_import_tasks()
    migrate_repository(REPOSITORY, fenced=False)
    migrate_repository(FENCED_REPOSITORY, fenced=True)
    migrate_existing_contract()


if __name__ == "__main__":
    main()
