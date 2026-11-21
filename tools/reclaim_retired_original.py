"""Explicit offline operator tool. Default is read-only; never initializes owners.

Production execution requires separate authorization. This tool is not invoked
by web startup, a Worker, cron, or the legacy compatibility migration tool.
"""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
from pathlib import Path
import sys
from contextlib import closing

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def batch_retirement_preview(service, data, project, retirement_task, *, after='', limit=20):
    """Bounded read-only batch around the single canonical physical-GC owner."""
    from platform_core.material_repository import existing_sqlite_reader

    project = service._identifier(project)
    retirement_task = service._identifier(retirement_task)
    if after:
        service._identifier(after)
    if type(limit) is not int or not 1 <= limit <= 50:
        raise ValueError('单次物理回收预览仅允许1至50条；请用游标分批执行')
    index = data / 'projects' / project / 'materials.sqlite3'
    with closing(existing_sqlite_reader(index)) as db:
        rows = db.execute(
            'SELECT image_id FROM material_retirements '
            'WHERE task_id=? AND image_id>? ORDER BY image_id LIMIT ?',
            (retirement_task, after, limit+1),
        ).fetchall()
    ids = [str(row[0]) for row in rows[:limit]]
    items = []
    for image_id in ids:
        try:
            preview = service.preview(project, retirement_task, image_id)
            items.append({'image_id':image_id, 'eligible':bool(preview['eligible']),
                'blockers':preview['blockers'], 'fingerprint':preview['fingerprint'],
                'source_identity':preview['source_identity']})
        except (OSError, ValueError, RuntimeError, KeyError) as error:
            items.append({'image_id':image_id, 'eligible':False,
                'blockers':[str(error)], 'fingerprint':None, 'source_identity':None})
    payload={'project_id':project, 'retirement_task_id':retirement_task,
        'after':after, 'items':items}
    digest=hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False,
        separators=(',',':')).encode('utf-8')).hexdigest()
    return {'digest':digest,'items':items,'count':len(ids),
        'eligible_count':sum(bool(item['eligible']) for item in items),
        'has_more':len(rows)>limit, 'next_cursor':ids[-1] if ids else None}


def main(argv=None):
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser(description="只读预览已退休原图；明确确认后仅允许离线受控本机回收")
    parser.add_argument('--data-dir', required=True)
    parser.add_argument('--project', required=True)
    parser.add_argument('--retirement-task', required=True)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument('--image-id', help='仅预览或回收一张已退休图片')
    selection.add_argument('--batch', action='store_true', help='按现有退休任务批量回收原图（仍须先预览）')
    parser.add_argument('--limit', type=int, default=20, help='批量每次1至50条，默认20条')
    parser.add_argument('--after', default='', help='批量游标：前一页的next_cursor')
    parser.add_argument('--controlled-local-writers', action='store_true', help='仅经现场核验的受控本机维护环境')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--expected-fingerprint')
    parser.add_argument('--expected-batch-digest', help='仅批量模式：必须与刚才的预览摘要完全一致')
    parser.add_argument('--operation-id', help='稳定操作身份，失败后保持不变')
    parser.add_argument('--confirm', help='必须精确输入 reclaim_retired_original:<project>:<image-id>')
    args = parser.parse_args(argv)
    from platform_core.local_material_reclamation import LocalMaterialReclamationService
    from platform_core.task_runtime import ArtifactStore, TaskRepository
    from platform_core.task_runtime.repository import _SCHEMA_VERSION
    from platform_core.material_repository import existing_sqlite_reader
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
        if args.batch:
            preview = batch_retirement_preview(service, data, args.project,
                args.retirement_task, after=args.after, limit=args.limit)
            confirm = (f"reclaim_retired_batch:{args.project}:{args.retirement_task}:"
                f"{preview['digest'][:16]}:{preview['eligible_count']}")
            if not args.apply:
                print(json.dumps({'ok':True, 'dry_run':True,
                    'expected_batch_digest':preview['digest'],
                    'required_confirmation':confirm, **preview},ensure_ascii=False,indent=2))
                return 0
            if (not args.operation_id or len(args.operation_id)>75
                    or not all(char.isascii() and (char.isalnum() or char in '_-') for char in args.operation_id)
                    or args.confirm!=confirm or args.expected_batch_digest!=preview['digest']):
                raise ValueError('批量预览已变化或确认信息不完整，禁止回收；请重新预览并使用相同操作身份')
            applied=[]
            failed=[]
            for item in preview['items']:
                if not item['eligible']:
                    continue
                image_id=item['image_id']
                operation_id=args.operation_id+'_'+hashlib.sha256(image_id.encode()).hexdigest()[:12]
                try:
                    result=service.apply(args.project,args.retirement_task,image_id,
                        expected_fingerprint=item['fingerprint'],operation_id=operation_id,
                        confirmed=True,actor=getpass.getuser())
                    applied.append({'image_id':image_id,'status':result['status'],
                        'deleted_logical_bytes':result.get('deleted_logical_bytes',0)})
                except (OSError,ValueError,RuntimeError,KeyError) as error:
                    failed.append({'image_id':image_id,'reason':str(error)})
            print(json.dumps({'ok':not failed,'dry_run':False,'preview_digest':preview['digest'],
                'selected_count':preview['count'],'eligible_count':preview['eligible_count'],
                'applied':applied,'failed':failed,'skipped_count':preview['count']-preview['eligible_count'],
                'has_more':preview['has_more'],'next_cursor':preview['next_cursor'],
                'physical_space_released':None},ensure_ascii=False,indent=2))
            return 0 if not failed else 2
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
