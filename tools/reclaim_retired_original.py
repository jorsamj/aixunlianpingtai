"""Explicit offline operator tool. Default is read-only; never initializes owners.

Production execution requires separate authorization. This tool is not invoked
by web startup, a Worker, cron, or the legacy compatibility migration tool.
"""
from __future__ import annotations

import argparse
import getpass
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="只读预览已退休原图；明确确认后仅允许离线受控本机回收")
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--retirement-task', required=True)
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--controlled-local-writers', action='store_true', help='仅经现场核验的受控本机维护环境')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-fingerprint')
    parser.add_argument('--operation-id', help='稳定操作身份，失败后保持不变')
    parser.add_argument('--confirm', help='必须精确输入 reclaim_retired_original:<project>:<image-id>')
    args = parser.parse_args(argv)
    from platform_core.local_material_reclamation import LocalMaterialReclamationService
    from platform_core.task_runtime import ArtifactStore, TaskRepository
    from platform_core.task_runtime.repository import _SCHEMA_VERSION
    from platform_core.material_repository import existing_sqlite_reader
    from contextlib import closing
    data = Path(args.data_dir).expanduser().resolve()
    try:
        # Deliberately avoid constructors that create/migrate SQLite or artifacts.
        tasks = object.__new__(TaskRepository)
        tasks.path = data / 'task_runtime/tasks.sqlite3'
        with closing(existing_sqlite_reader(tasks.path)) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] != _SCHEMA_VERSION:
                raise ValueError('任务索引版本未知，禁止隐式迁移')
        artifacts = object.__new__(ArtifactStore)
        artifacts.root = data / 'task_runtime/artifacts'
        if not artifacts.root.is_dir() or artifacts.root.is_symlink():
            raise ValueError('已有任务归档不存在或路径不安全')
        service = LocalMaterialReclamationService(data, tasks, artifacts,
            controlled_local_writers=args.controlled_local_writers)
        if args.apply:
            expected = f'reclaim_retired_original:{args.project}:{args.image_id}'
            if args.confirm != expected or not args.expected_fingerprint or not args.operation_id:
                raise ValueError('必须先预览并提供准确指纹、稳定操作身份及明确确认文字')
            result = service.apply(args.project, args.retirement_task, args.image_id,
                expected_fingerprint=args.expected_fingerprint, operation_id=args.operation_id,
                confirmed=True, actor=getpass.getuser())
        else:
            result = service.preview(args.project, args.retirement_task, args.image_id)
        result = {key:value for key,value in result.items() if not key.startswith('_')}
        print(json.dumps({'ok':True, 'dry_run':not args.apply, **result}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        print(json.dumps({'ok':False, 'reason':str(error),
                          'next_step':'保留操作身份并只读核验回执；不会自动重复删除'}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
