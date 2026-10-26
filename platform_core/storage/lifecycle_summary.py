"""Bounded observations for the existing storage page, never a new data owner."""
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from platform_core.material_repository import existing_sqlite_reader, MATERIAL_READ_SCHEMA_VERSIONS
from .cache import resolve_material_cache_location
from .material_cache_runtime import read_material_cache_snapshot


def storage_lifecycle_summary(data_dir, project_id):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', str(project_id)):
        raise ValueError('invalid project identity')
    project = Path(data_dir).resolve() / 'projects' / project_id
    scopes = {
        'original_index_logical_bytes':'项目当前素材索引逻辑量（不是底层独占量）',
        'gt_index_logical_bytes':'正式GT SQLite文件逻辑量（不含旧JSON）',
        'thumbnail_cache_logical_bytes':'配置缓存上次已索引缩略图逻辑量（失效指针孤立缓存不归属此项）',
        'shared_cache_logical_bytes':'配置素材缓存上次全部采样（可跨节点共享，不能直接算作节点独占）',
        'worker_workspace_logical_bytes':'需按节点及任务只读核验',
        'reclaimable_logical_bytes':'需逐任务资格预览，不按成功状态估算',
        'cleanup_pending_tasks':'未全量读取任务清理回执',
        'cleanup_failed_tasks':'未全量读取任务清理回执',
    }
    metrics = {key:{'value':None,'scope':scope} for key,scope in scopes.items()}
    try:
        with closing(existing_sqlite_reader(project / 'materials.sqlite3')) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] in MATERIAL_READ_SCHEMA_VERSIONS:
                count, size, missing = db.execute(
                    'SELECT COUNT(*),COALESCE(SUM(size_bytes),0),COALESCE(SUM(CASE WHEN size_bytes<=0 THEN 1 ELSE 0 END),0) FROM materials'
                ).fetchone()
                if not missing:
                    metrics['original_index_logical_bytes']['value'] = int(size)
    except (OSError, ValueError, sqlite3.Error):
        pass  # Unknown schema/index stays unknown; never initialize or repair it.
    try:
        path = project / 'annotations.sqlite3'
        with closing(existing_sqlite_reader(path)) as db:
            if db.execute('PRAGMA user_version').fetchone()[0] == 3:
                metrics['gt_index_logical_bytes']['value'] = sum(item.stat().st_size for item in
                    (path,Path(str(path)+'-wal')) if item.is_file())
    except (OSError, ValueError, sqlite3.Error):
        pass
    snapshot = read_material_cache_snapshot(resolve_material_cache_location(data_dir))
    if snapshot and snapshot.get('inventory_complete') is True:
        for field, metric in [('after_bytes','shared_cache_logical_bytes'),
                              ('thumbnail_logical_bytes','thumbnail_cache_logical_bytes')]:
            value = snapshot.get(field)
            if type(value) is int and value >= 0:
                metrics[metric]['value'] = value
    return {'project_id':project_id, 'metrics':metrics, 'sampled_at':(snapshot or {}).get('generated_at'),
            'cache_scope':(snapshot or {}).get('cache_scope'),
            'physical_space_released':None, 'scope':'readonly-index-and-existing-cache-observations'}
