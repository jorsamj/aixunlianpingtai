from pathlib import Path

APP = Path('app.py')
ANNOTATION_VIEW = Path('static/modules/annotation-task-view.js')
MATERIAL_JS = Path('static/modules/material-batches.js')
MATERIAL_PY = Path('platform_core/material_batches.py')
STATIC_APP = Path('static/app.js')
MAIN = Path('static/main.mjs')
ANNOTATION_TEST = Path('tests/api/test_annotation_unified_task_truth.py')
MATERIAL_TEST = Path('tests/unit/test_material_batch_public_truth.py')
FRONT_TEST = Path('tests/frontend/phase2-task-truth.test.mjs')

# --- AI annotation business response: preserve business fields, add unified durable truth.
app = APP.read_text(encoding='utf-8')
start = app.index('def public_annotation_task(')
end = app.index('\ndef _annotation_summary(', start)
block = app[start:end]
old = '    progress_summary = summary or {}\n'
new = '    progress_summary = summary or {}\n    repository = shared_task_repository()\n    truth = task_to_public(task, repository)\n'
if block.count(old) != 1:
    raise SystemExit(f'annotation truth anchor count={block.count(old)}')
block = block.replace(old, new, 1)
old_fields = '''        "status": task.status.value,\n        "priority": task.priority,\n        "progress": task.progress,\n        "stage": task.stage,\n        "current_item": task.current_item,\n'''
new_fields = '''        "status": truth["status"],\n        "persisted_status": truth["persisted_status"],\n        "priority": truth["priority"],\n        "queue_rank": truth["queue_rank"],\n        "resource_queue_position": truth["resource_queue_position"],\n        "resource_wait_reason": truth["resource_wait_reason"],\n        "worker_id": truth["worker_id"],\n        "lease_expires_at": truth["lease_expires_at"],\n        "progress": truth["progress_percent"],\n        "progress_percent": truth["progress_percent"],\n        "stage": truth["phase"],\n        "phase": truth["phase"],\n        "current_item": truth["current_item"],\n'''
if block.count(old_fields) != 1:
    raise SystemExit(f'annotation field anchor count={block.count(old_fields)}')
block = block.replace(old_fields, new_fields, 1)
app = app[:start] + block + app[end:]
APP.write_text(app, encoding='utf-8')

# --- Annotation presentation understands effective WAITING_RESOURCE and runtime metadata.
view = ANNOTATION_VIEW.read_text(encoding='utf-8')
old = "  QUEUED: '排队中', RUNNING: 'AI标注中', CANCEL_REQUESTED: '正在取消',\n"
new = "  QUEUED: '排队中', WAITING_RESOURCE: '等待资源', RUNNING: 'AI标注中', CANCEL_REQUESTED: '正在取消',\n"
if view.count(old) != 1:
    raise SystemExit(f'annotation label anchor count={view.count(old)}')
view = view.replace(old, new, 1)
old = '''  const completed = progress.completed || Math.max(0, Number(summary.total) || 0);\n  return {\n'''
new = '''  const completed = progress.completed || Math.max(0, Number(summary.total) || 0);\n  const queuePosition = Math.max(0, Number(task.resource_queue_position) || 0);\n  const waitReason = String(task.resource_wait_reason || '').trim();\n  const workerId = String(task.worker_id || '').trim();\n  const queuedRuntime = queuePosition\n    ? `资源队列第 ${queuePosition} 位${waitReason ? ` · ${waitReason}` : ''}`\n    : (waitReason ? `等待资源 · ${waitReason}` : '');\n  const runtimeText = ['QUEUED', 'WAITING_RESOURCE'].includes(status)\n    ? queuedRuntime\n    : (workerId ? `Worker ${workerId}` : '');\n  return {\n'''
if view.count(old) != 1:
    raise SystemExit(f'annotation view anchor count={view.count(old)}')
view = view.replace(old, new, 1)
old = '''    progressText: `${completed} / ${total}`,\n    active: isTaskActive(status),\n'''
new = '''    progressText: `${completed} / ${total}`,\n    queuePosition,\n    waitReason,\n    workerId,\n    runtimeText,\n    active: isTaskActive(status),\n'''
if view.count(old) != 1:
    raise SystemExit(f'annotation runtime fields anchor count={view.count(old)}')
ANNOTATION_VIEW.write_text(view.replace(old, new, 1), encoding='utf-8')

# --- Make the existing annotation task row/modal actually surface runtimeText.
static_app = STATIC_APP.read_text(encoding='utf-8')
old = "const current=imageById(task.current_item);set('ai60Current',current?.filename||task.current_item||'等待 Worker 处理');"
new = "const current=imageById(task.current_item);set('ai60Current',current?.filename||task.current_item||view.runtimeText||'等待 Worker 处理');"
if static_app.count(old) != 1:
    raise SystemExit(f'annotation modal runtime anchor count={static_app.count(old)}')
static_app = static_app.replace(old, new, 1)
old = '''<td><span class="pill ${view.active?'run':view.status==='AWAITING_CONFIRMATION'?'warn':view.status==='SUCCEEDED'?'ok':view.status==='FAILED'?'err':''}">${esc(view.statusText)}</span></td>'''
new = '''<td><span class="pill ${view.active?'run':view.status==='AWAITING_CONFIRMATION'?'warn':view.status==='SUCCEEDED'?'ok':view.status==='FAILED'?'err':''}">${esc(view.statusText)}</span>${view.runtimeText?`<div class="muted-line">${esc(view.runtimeText)}</div>`:''}</td>'''
if static_app.count(old) != 1:
    raise SystemExit(f'annotation row runtime anchor count={static_app.count(old)}')
STATIC_APP.write_text(static_app.replace(old, new, 1), encoding='utf-8')

# --- Material batch business response uses the same truth projection without a second HTTP request.
material_py = MATERIAL_PY.read_text(encoding='utf-8')
old = 'from .task_runtime import TaskKind, TaskRecord, TaskStatus\n'
new = 'from .task_runtime import TaskKind, TaskRecord, TaskStatus, task_to_public\n'
if material_py.count(old) != 1:
    raise SystemExit(f'material import anchor count={material_py.count(old)}')
material_py = material_py.replace(old, new, 1)
old = '''def public_batch(task, artifacts):\n    checkpoint = artifacts.read_json(task.task_id, CHECKPOINT_REF, default={})\n    request = artifacts.read_json(task.task_id, task.payload_ref, default={})\n'''
new = '''def public_batch(task, artifacts, repository=None):\n    checkpoint = artifacts.read_json(task.task_id, CHECKPOINT_REF, default={})\n    request = artifacts.read_json(task.task_id, task.payload_ref, default={})\n    truth = task_to_public(task, repository) if repository is not None else None\n'''
if material_py.count(old) != 1:
    raise SystemExit(f'public_batch anchor count={material_py.count(old)}')
material_py = material_py.replace(old, new, 1)
old = '''    return {"id": task.task_id, "task_id": task.task_id, "project_id": task.project_id,\n            "kind": task.kind.value, "operation": request.get("operation"), "status": task.status.value,\n            "stage": task.stage, "total": checkpoint.get("total") if frozen else None,\n'''
new = '''    return {"id": task.task_id, "task_id": task.task_id, "project_id": task.project_id,\n            "kind": task.kind.value, "operation": request.get("operation"),\n            "status": truth["status"] if truth else task.status.value,\n            "persisted_status": truth["persisted_status"] if truth else task.status.value,\n            "priority": truth["priority"] if truth else task.priority,\n            "queue_rank": truth["queue_rank"] if truth else task.queue_rank,\n            "resource_queue_position": truth["resource_queue_position"] if truth else None,\n            "resource_wait_reason": truth["resource_wait_reason"] if truth else task.resource_wait_reason,\n            "worker_id": truth["worker_id"] if truth else task.worker_id,\n            "lease_expires_at": truth["lease_expires_at"] if truth else task.lease_expires_at,\n            "progress_percent": truth["progress_percent"] if truth else task.progress,\n            "stage": truth["phase"] if truth else task.stage,\n            "phase": truth["phase"] if truth else task.stage,\n            "current_item": truth["current_item"] if truth else task.current_item,\n            "total": checkpoint.get("total") if frozen else None,\n'''
if material_py.count(old) != 1:
    raise SystemExit(f'public_batch return anchor count={material_py.count(old)}')
material_py = material_py.replace(old, new, 1)
for old_call, new_call in [
    ('return public_batch(task, task_artifacts())', 'return public_batch(task, task_artifacts(), task_repository())'),
    ('return public_batch(require_task(project_id, task_id), task_artifacts())', 'return public_batch(require_task(project_id, task_id), task_artifacts(), task_repository())'),
    ('return public_batch(task_repository().request_cancel(task_id), task_artifacts())', 'return public_batch(task_repository().request_cancel(task_id), task_artifacts(), task_repository())'),
    ('return public_batch(task_repository().retry(task_id), task_artifacts())', 'return public_batch(task_repository().retry(task_id), task_artifacts(), task_repository())'),
]:
    if material_py.count(old_call) != 1:
        raise SystemExit(f'material router call anchor count={material_py.count(old_call)}: {old_call}')
    material_py = material_py.replace(old_call, new_call, 1)
MATERIAL_PY.write_text(material_py, encoding='utf-8')

# --- Material batch polling/display remains on its business endpoint but understands unified status.
material_js = MATERIAL_JS.read_text(encoding='utf-8')
old = "const ACTIVE = new Set(['QUEUED', 'RUNNING', 'CANCEL_REQUESTED']);\n"
new = "const ACTIVE = new Set(['QUEUED', 'WAITING_RESOURCE', 'RUNNING', 'CANCEL_REQUESTED']);\n\nexport function isMaterialBatchActive(value) {\n  return ACTIVE.has(String(value || '').toUpperCase());\n}\n\nexport function materialBatchTaskText(task = {}) {\n  const status = String(task.status || '').toUpperCase();\n  const label = ({QUEUED:'排队中', WAITING_RESOURCE:'等待资源', RUNNING:'处理中', CANCEL_REQUESTED:'正在取消', AWAITING_CONFIRMATION:'等待确认', PARTIAL_SUCCESS:'部分成功', SUCCEEDED:'已完成', CANCELLED:'已取消', FAILED:'失败', BLOCKED_BY_ENVIRONMENT:'环境不可用', BLOCKED_BY_HARDWARE:'硬件不可用'})[status] || status || '未知';\n  const queuePosition = Math.max(0, Number(task.resource_queue_position) || 0);\n  const waitReason = String(task.resource_wait_reason || '').trim();\n  const workerId = String(task.worker_id || '').trim();\n  const runtime = ['QUEUED', 'WAITING_RESOURCE'].includes(status)\n    ? (queuePosition ? ` · 资源队列第 ${queuePosition} 位${waitReason ? ` · ${waitReason}` : ''}` : (waitReason ? ` · ${waitReason}` : ''))\n    : (workerId ? ` · Worker ${workerId}` : '');\n  return `${label}${runtime}`;\n}\n"
if material_js.count(old) != 1:
    raise SystemExit(f'material active anchor count={material_js.count(old)}')
material_js = material_js.replace(old, new, 1)
material_js = material_js.replace("ACTIVE.has(String(task.status || '').toUpperCase())", "isMaterialBatchActive(task.status)")
old = "    tell(`${task.operation || '批量任务'}：${task.status} ${processed}/${total}${failed ? `，失败 ${failed}` : ''}${cleaning}`);\n"
new = "    tell(`${task.operation || '批量任务'}：${materialBatchTaskText(task)} ${processed}/${total}${failed ? `，失败 ${failed}` : ''}${cleaning}`);\n"
if material_js.count(old) != 1:
    raise SystemExit(f'material announce anchor count={material_js.count(old)}')
material_js = material_js.replace(old, new, 1)
if "ACTIVE.has(String(task.status || '').toUpperCase())" in material_js:
    raise SystemExit('material active call remained after replacement')
MATERIAL_JS.write_text(material_js, encoding='utf-8')

# Cache-bust the two modified ES modules.
main = MAIN.read_text(encoding='utf-8')
for old, new in [
    ("./modules/annotation-task-view.js?v=422000", "./modules/annotation-task-view.js?v=422001"),
    ("./modules/material-batches.js?v=422400", "./modules/material-batches.js?v=422401"),
]:
    if main.count(old) != 1:
        raise SystemExit(f'main cache anchor count={main.count(old)}: {old}')
    main = main.replace(old, new, 1)
MAIN.write_text(main, encoding='utf-8')

ANNOTATION_TEST.write_text('''from dataclasses import replace\n\nimport app as platform_app\nfrom platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository\n\n\ndef test_annotation_business_projection_exposes_waiting_resource_truth(tmp_path, monkeypatch):\n    repository = TaskRepository(tmp_path / "tasks.sqlite3")\n    artifacts = ArtifactStore(tmp_path / "artifacts")\n    monkeypatch.setattr(platform_app, "_SHARED_TASK_REPOSITORY", repository)\n    monkeypatch.setattr(platform_app, "_SHARED_TASK_ARTIFACTS", artifacts)\n    task_id = "annotation-waiting"\n    artifacts.atomic_write_json(task_id, "request.json", {\n        "image_ids": ["a", "b"], "labels": ["fire"], "task_name": "烟火标注",\n    })\n    queued = replace(\n        TaskRecord.new(task_id, "project-1", TaskKind.AI_ANNOTATION, "request.json", "vision:model-a", priority=12),\n        stage="resource_waiting", resource_wait_reason="VISION_CAPACITY_BUSY", queue_rank=3,\n    )\n    task = repository.create(queued, artifacts=artifacts)\n    body = platform_app.public_annotation_task(task)\n    assert body["status"] == "WAITING_RESOURCE"\n    assert body["persisted_status"] == "QUEUED"\n    assert body["priority"] == 12\n    assert body["queue_rank"] == 3\n    assert body["resource_queue_position"] == 1\n    assert body["resource_wait_reason"] == "VISION_CAPACITY_BUSY"\n    assert body["progress_percent"] == 0\n    assert body["phase"] == "resource_waiting"\n    assert body["total_count"] == 2\n''', encoding='utf-8')

MATERIAL_TEST.parent.mkdir(parents=True, exist_ok=True)
MATERIAL_TEST.write_text('''from dataclasses import replace\n\nfrom platform_core.material_batches import public_batch\nfrom platform_core.task_runtime import ArtifactStore, TaskKind, TaskRecord, TaskRepository\n\n\ndef test_material_batch_projection_exposes_waiting_resource_truth(tmp_path):\n    repository = TaskRepository(tmp_path / "tasks.sqlite3")\n    artifacts = ArtifactStore(tmp_path / "artifacts")\n    task_id = "clean-waiting"\n    artifacts.atomic_write_json(task_id, "request.json", {"operation": "CLEAN", "options": {}})\n    queued = replace(\n        TaskRecord.new(task_id, "project-1", TaskKind.MATERIAL_BATCH, "request.json", "materials:project-1", priority=18),\n        stage="resource_waiting", resource_wait_reason="MATERIAL_WORKER_BUSY", queue_rank=2,\n    )\n    task = repository.create(queued, artifacts=artifacts)\n    body = public_batch(task, artifacts, repository)\n    assert body["operation"] == "CLEAN"\n    assert body["status"] == "WAITING_RESOURCE"\n    assert body["persisted_status"] == "QUEUED"\n    assert body["priority"] == 18\n    assert body["queue_rank"] == 2\n    assert body["resource_queue_position"] == 1\n    assert body["resource_wait_reason"] == "MATERIAL_WORKER_BUSY"\n    assert body["progress_percent"] == 0\n    assert body["phase"] == "resource_waiting"\n    assert body["scan_only"] is True\n''', encoding='utf-8')

FRONT_TEST.write_text('''import test from 'node:test';\nimport assert from 'node:assert/strict';\nimport fs from 'node:fs';\n\nimport {annotationTaskView} from '../../static/modules/annotation-task-view.js';\nimport {isMaterialBatchActive, materialBatchTaskText} from '../../static/modules/material-batches.js';\n\ntest('AI annotation waiting-resource state stays active and shows real queue metadata', () => {\n  const view = annotationTaskView({\n    status: 'WAITING_RESOURCE', progress_percent: 12.5, completed_count: 5, total_count: 40,\n    resource_queue_position: 2, resource_wait_reason: 'VISION_CAPACITY_BUSY',\n  });\n  assert.equal(view.active, true);\n  assert.equal(view.statusText, '等待资源');\n  assert.equal(view.percent, 12.5);\n  assert.equal(view.runtimeText, '资源队列第 2 位 · VISION_CAPACITY_BUSY');\n});\n\ntest('material batch waiting-resource state remains pollable and human-readable', () => {\n  assert.equal(isMaterialBatchActive('WAITING_RESOURCE'), true);\n  assert.equal(\n    materialBatchTaskText({status:'WAITING_RESOURCE', resource_queue_position:3, resource_wait_reason:'MATERIAL_WORKER_BUSY'}),\n    '等待资源 · 资源队列第 3 位 · MATERIAL_WORKER_BUSY',\n  );\n  assert.equal(materialBatchTaskText({status:'RUNNING', worker_id:'materials-worker-01'}), '处理中 · Worker materials-worker-01');\n});\n\ntest('live annotation table/modal consumes runtimeText instead of hiding it', () => {\n  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');\n  assert.match(source, /task\.current_item\|\|view\.runtimeText\|\|'等待 Worker 处理'/);\n  assert.match(source, /view\.runtimeText\?`<div class="muted-line">/);\n});\n''', encoding='utf-8')

print('annotation + material unified task truth patch prepared')
