from pathlib import Path

APP = Path('app.py')
JS = Path('static/app.js')
API_TEST = Path('tests/api/test_conversion_unified_task_truth.py')
FRONT_TEST = Path('tests/frontend/conversion-unified-task-truth.test.mjs')

app = APP.read_text(encoding='utf-8')
old = '''def _overlay_durable_deploy_job(job: Dict[str, Any]) -> Dict[str, Any]:\n    result = dict(job or {})\n    task_id = str(result.get("task_id") or "")\n    durable = shared_task_repository().get(task_id) if task_id else None\n    if not durable or durable.kind is not TaskKind.MODEL_CONVERSION:\n        return result\n    result["durable_status"] = durable.status.value\n    if durable.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:\n        result.update(status="queued" if durable.status is TaskStatus.QUEUED else "running", progress=durable.progress, stage=durable.stage)\n    elif durable.status is TaskStatus.BLOCKED_BY_HARDWARE:\n        result["status"] = "blocked_by_hardware"\n    elif durable.status is TaskStatus.BLOCKED_BY_ENVIRONMENT:\n        result["status"] = "blocked_by_environment"\n    elif durable.status is TaskStatus.CANCELLED:\n        result["status"] = "stopped"\n    elif durable.status is TaskStatus.FAILED:\n        result["status"] = "failed"\n    return result\n'''
new = '''def _overlay_durable_deploy_job(job: Dict[str, Any]) -> Dict[str, Any]:\n    result = dict(job or {})\n    task_id = str(result.get("task_id") or "")\n    repository = shared_task_repository()\n    durable = repository.get(task_id) if task_id else None\n    if not durable or durable.kind is not TaskKind.MODEL_CONVERSION:\n        return result\n    truth = task_to_public(durable, repository)\n    result.update(\n        durable_status=durable.status.value,\n        task_status=truth["status"],\n        progress=truth["progress_percent"],\n        stage=truth["phase"],\n        current_item=truth["current_item"],\n        priority=truth["priority"],\n        queue_rank=truth["queue_rank"],\n        resource_queue_position=truth["resource_queue_position"],\n        resource_wait_reason=truth["resource_wait_reason"],\n        worker_id=truth["worker_id"],\n        lease_expires_at=truth["lease_expires_at"],\n    )\n    if durable.status is TaskStatus.QUEUED:\n        result["status"] = "waiting_resource" if truth["status"] == "WAITING_RESOURCE" else "queued"\n    elif durable.status in {TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:\n        result["status"] = "running"\n    elif durable.status is TaskStatus.BLOCKED_BY_HARDWARE:\n        result["status"] = "blocked_by_hardware"\n    elif durable.status is TaskStatus.BLOCKED_BY_ENVIRONMENT:\n        result["status"] = "blocked_by_environment"\n    elif durable.status is TaskStatus.CANCELLED:\n        result["status"] = "stopped"\n    elif durable.status is TaskStatus.FAILED:\n        result["status"] = "failed"\n    return result\n'''
if app.count(old) != 1:
    raise SystemExit(f'deploy overlay anchor count={app.count(old)}')
APP.write_text(app.replace(old, new, 1), encoding='utf-8')

js = JS.read_text(encoding='utf-8')
old = "queued:'排队中',running:'转换中',done:'已完成',failed:'失败',stopped:'已停止'"
new = "queued:'排队中',waiting_resource:'等待资源',running:'转换中',done:'已完成',failed:'失败',stopped:'已停止',blocked_by_hardware:'硬件不足',blocked_by_environment:'环境不可用'"
if js.count(old) != 1:
    raise SystemExit(f'status pill anchor count={js.count(old)}')
js = js.replace(old, new, 1)
old = "function jobRow(j){const params=j.params||{};const chip=params.chip||params.soc_version||'';const isRun=['queued','running'].includes(j.status);return"
new = "function jobRow(j){const params=j.params||{};const chip=params.chip||params.soc_version||'';const isRun=['queued','waiting_resource','running'].includes(j.status);const queueMeta=j.status==='waiting_resource'?` · 资源队列第 ${Number(j.resource_queue_position||0)||'-'} 位 · ${esc(j.resource_wait_reason||'等待可用资源')}`:(j.worker_id?` · Worker ${esc(j.worker_id)}`:'');return"
if js.count(old) != 1:
    raise SystemExit(f'job row prefix anchor count={js.count(old)}')
js = js.replace(old, new, 1)
old = "${esc(j.resource?.name||'-')} · ${esc(j.stage||'')}</div>"
new = "${esc(j.resource?.name||'-')} · ${esc(j.stage||' )}${queueMeta}</div>"
if js.count(old) != 1:
    raise SystemExit(f'job row metadata anchor count={js.count(old)}')
js = js.replace(old, new, 1)
old = ".some(j=>['queued','running'].includes(j.status))"
new = ".some(j=>['queued','waiting_resource','running'].includes(j.status))"
if js.count(old) != 1:
    raise SystemExit(f'deploy polling active-set anchor count={js.count(old)}')
js = js.replace(old, new, 1)
JS.write_text(js, encoding='utf-8')

API_TEST.write_text('''from dataclasses import replace\n\nimport app as platform_app\nfrom platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus\n\n\nclass FakeRepository:\n    def __init__(self, task):\n        self.task = task\n\n    def get(self, task_id):\n        return self.task if task_id == self.task.task_id else None\n\n    def resource_queue_position(self, task_id):\n        assert task_id == self.task.task_id\n        return 2\n\n\ndef test_conversion_overlay_projects_real_waiting_resource_truth(monkeypatch):\n    task = replace(\n        TaskRecord.new(\n            'convert-waiting', 'project-1', TaskKind.MODEL_CONVERSION,\n            'request.json', 'conversion:gpu:0', priority=20,\n            required_capabilities=('conversion.tensorrt',),\n        ),\n        status=TaskStatus.QUEUED,\n        stage='resource_waiting',\n        progress=17.5,\n        current_item='waiting for GPU memory',\n        resource_wait_reason='GPU_MEMORY_BUSY',\n        queue_rank=4,\n    )\n    repository = FakeRepository(task)\n    monkeypatch.setattr(platform_app, 'shared_task_repository', lambda: repository)\n\n    job = platform_app._overlay_durable_deploy_job({\n        'id': task.task_id, 'task_id': task.task_id, 'status': 'queued',\n        'target': 'tensorrt',\n    })\n\n    assert job['status'] == 'waiting_resource'\n    assert job['task_status'] == 'WAITING_RESOURCE'\n    assert job['durable_status'] == 'QUEUED'\n    assert job['progress'] == 17.5\n    assert job['stage'] == 'resource_waiting'\n    assert job['priority'] == 20\n    assert job['queue_rank'] == 4\n    assert job['resource_queue_position'] == 2\n    assert job['resource_wait_reason'] == 'GPU_MEMORY_BUSY'\n    assert job['current_item'] == 'waiting for GPU memory'\n\n\ndef test_conversion_overlay_exposes_running_worker_and_lease(monkeypatch):\n    task = replace(\n        TaskRecord.new(\n            'convert-running', 'project-1', TaskKind.MODEL_CONVERSION,\n            'request.json', 'conversion:gpu:0', priority=10,\n        ),\n        status=TaskStatus.RUNNING, stage='converting', progress=62,\n        worker_id='conversion-worker-a800',\n        lease_expires_at='2026-09-13T01:00:00+00:00',\n    )\n    repository = FakeRepository(task)\n    monkeypatch.setattr(platform_app, 'shared_task_repository', lambda: repository)\n    job = platform_app._overlay_durable_deploy_job({\n        'id': task.task_id, 'task_id': task.task_id, 'status': 'queued',\n    })\n    assert job['status'] == 'running'\n    assert job['task_status'] == 'RUNNING'\n    assert job['worker_id'] == 'conversion-worker-a800'\n    assert job['lease_expires_at'] == '2026-09-13T01:00:00+00:00'\n    assert job['progress'] == 62\n''', encoding='utf-8')

FRONT_TEST.write_text('''import test from 'node:test';\nimport assert from 'node:assert/strict';\nimport fs from 'node:fs';\n\nconst source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');\n\ntest('deployment conversion UI keeps waiting-resource tasks live and visible', () => {\n  assert.match(source, /waiting_resource:'等待资源'/);\n  assert.match(source, /\['queued','waiting_resource','running'\]\.includes\(j\.status\)/);\n  assert.match(source, /资源队列第 \$\{Number\(j\.resource_queue_position\|\|0\)\|\|'-'\} 位/);\n  assert.match(source, /j\.resource_wait_reason\|\|'等待可用资源'/);\n  assert.match(source, /j\.worker_id\?` · Worker/);\n});\n''', encoding='utf-8')

print('conversion unified task truth patch prepared')
