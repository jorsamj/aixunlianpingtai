from pathlib import Path

path = Path('static/app.js')
text = path.read_text(encoding='utf-8')
old = "const queueMeta=j.status==='waiting_resource'?` · 资源队列第 ${Number(j.resource_queue_position||0)||'-'} 位 · ${esc(j.resource_wait_reason||'等待可用资源')}`:(j.worker_id?` · Worker ${esc(j.worker_id)}`:'');"
new = "const queueMeta=['queued','waiting_resource'].includes(j.status)?` · 资源队列第 ${Number(j.resource_queue_position||0)||'-'} 位${j.status==='waiting_resource'&&j.resource_wait_reason?` · ${esc(j.resource_wait_reason)}`:''}`:(j.worker_id?` · Worker ${esc(j.worker_id)}`:'');"
if old not in text:
    raise SystemExit('DEPLOYMENT_QUEUED_POSITION_MIGRATION_TARGET_NOT_FOUND')
if text.count(old) != 1:
    raise SystemExit(f'DEPLOYMENT_QUEUED_POSITION_MIGRATION_TARGET_COUNT={text.count(old)}')
path.write_text(text.replace(old, new, 1), encoding='utf-8')
print('DEPLOYMENT_QUEUED_POSITION_MIGRATED')
