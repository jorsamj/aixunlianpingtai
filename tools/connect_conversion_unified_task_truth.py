from pathlib import Path

APP = Path('app.py')
JS = Path('static/app.js')
API_TEST = Path('tests/api/test_conversion_unified_task_truth.py')
FRONT_TEST = Path('tests/frontend/conversion-unified-task-truth.test.mjs')

app = APP.read_text(encoding='utf-8')
old = '''def _overlay_durable_deploy_job(job: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(job or {})
    task_id = str(result.get("task_id") or "")
    durable = shared_task_repository().get(task_id) if task_id else None
    if not durable or durable.kind is not TaskKind.MODEL_CONVERSION:
        return result
    result["durable_status"] = durable.status.value
    if durable.status in {TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:
        result.update(status="queued" if durable.status is TaskStatus.QUEUED else "running", progress=durable.progress, stage=durable.stage)
    elif durable.status is TaskStatus.BLOCKED_BY_HARDWARE:
        result["status"] = "blocked_by_hardware"
    elif durable.status is TaskStatus.BLOCKED_BY_ENVIRONMENT:
        result["status"] = "blocked_by_environment"
    elif durable.status is TaskStatus.CANCELLED:
        result["status"] = "stopped"
    elif durable.status is TaskStatus.FAILED:
        result["status"] = "failed"
    return result
'''
new = '''def _overlay_durable_deploy_job(job: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(job or {})
    task_id = str(result.get("task_id") or "")
    repository = shared_task_repository()
    durable = repository.get(task_id) if task_id else None
    if not durable or durable.kind is not TaskKind.MODEL_CONVERSION:
        return result
    truth = task_to_public(durable, repository)
    result.update(
        durable_status=durable.status.value,
        task_status=truth["status"],
        progress=truth["progress_percent"],
        stage=truth["phase"],
        current_item=truth["current_item"],
        priority=truth["priority"],
        queue_rank=truth["queue_rank"],
        resource_queue_position=truth["resource_queue_position"],
        resource_wait_reason=truth["resource_wait_reason"],
        worker_id=truth["worker_id"],
        lease_expires_at=truth["lease_expires_at"],
    )
    if durable.status is TaskStatus.QUEUED:
        result["status"] = "waiting_resource" if truth["status"] == "WAITING_RESOURCE" else "queued"
    elif durable.status in {TaskStatus.RUNNING, TaskStatus.CANCEL_REQUESTED}:
        result["status"] = "running"
    elif durable.status is TaskStatus.BLOCKED_BY_HARDWARE:
        result["status"] = "blocked_by_hardware"
    elif durable.status is TaskStatus.BLOCKED_BY_ENVIRONMENT:
        result["status"] = "blocked_by_environment"
    elif durable.status is TaskStatus.CANCELLED:
        result["status"] = "stopped"
    elif durable.status is TaskStatus.FAILED:
        result["status"] = "failed"
    return result
'''
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
new = "${esc(j.resource?.name||'-')} · ${esc(j.stage||'')}${queueMeta}</div>"
if js.count(old) != 1:
    raise SystemExit(f'job row metadata anchor count={js.count(old)}')
js = js.replace(old, new, 1)
old = ".some(j=>['queued','running'].includes(j.status))"
new = ".some(j=>['queued','waiting_resource','running'].includes(j.status))"
if js.count(old) != 1:
    raise SystemExit(f'deploy polling active-set anchor count={js.count(old)}')
js = js.replace(old, new, 1)
JS.write_text(js, encoding='utf-8')

API_TEST.write_text('''from dataclasses import replace

import app as platform_app
from platform_core.task_runtime import TaskKind, TaskRecord, TaskStatus


class FakeRepository:
    def __init__(self, task):
        self.task = task

    def get(self, task_id):
        return self.task if task_id == self.task.task_id else None

    def resource_queue_position(self, task_id):
        assert task_id == self.task.task_id
        return 2


def test_conversion_overlay_projects_real_waiting_resource_truth(monkeypatch):
    task = replace(
        TaskRecord.new(
            'convert-waiting', 'project-1', TaskKind.MODEL_CONVERSION,
            'request.json', 'conversion:gpu:0', priority=20,
            required_capabilities=('conversion.tensorrt',),
        ),
        status=TaskStatus.QUEUED,
        stage='resource_waiting',
        progress=17.5,
        current_item='waiting for GPU memory',
        resource_wait_reason='GPU_MEMORY_BUSY',
        queue_rank=4,
    )
    repository = FakeRepository(task)
    monkeypatch.setattr(platform_app, 'shared_task_repository', lambda: repository)

    job = platform_app._overlay_durable_deploy_job({
        'id': task.task_id, 'task_id': task.task_id, 'status': 'queued',
        'target': 'tensorrt',
    })

    assert job['status'] == 'waiting_resource'
    assert job['task_status'] == 'WAITING_RESOURCE'
    assert job['durable_status'] == 'QUEUED'
    assert job['progress'] == 17.5
    assert job['stage'] == 'resource_waiting'
    assert job['priority'] == 20
    assert job['queue_rank'] == 4
    assert job['resource_queue_position'] == 2
    assert job['resource_wait_reason'] == 'GPU_MEMORY_BUSY'
    assert job['current_item'] == 'waiting for GPU memory'


def test_conversion_overlay_exposes_running_worker_and_lease(monkeypatch):
    task = replace(
        TaskRecord.new(
            'convert-running', 'project-1', TaskKind.MODEL_CONVERSION,
            'request.json', 'conversion:gpu:0', priority=10,
        ),
        status=TaskStatus.RUNNING, stage='converting', progress=62,
        worker_id='conversion-worker-a800',
        lease_expires_at='2026-09-13T01:00:00+00:00',
    )
    repository = FakeRepository(task)
    monkeypatch.setattr(platform_app, 'shared_task_repository', lambda: repository)
    job = platform_app._overlay_durable_deploy_job({
        'id': task.task_id, 'task_id': task.task_id, 'status': 'queued',
    })
    assert job['status'] == 'running'
    assert job['task_status'] == 'RUNNING'
    assert job['worker_id'] == 'conversion-worker-a800'
    assert job['lease_expires_at'] == '2026-09-13T01:00:00+00:00'
    assert job['progress'] == 62
''', encoding='utf-8')

FRONT_TEST.write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('deployment conversion UI keeps waiting-resource tasks live and visible', () => {
  assert.match(source, /waiting_resource:'等待资源'/);
  assert.match(source, /\['queued','waiting_resource','running'\]\.includes\(j\.status\)/);
  assert.match(source, /资源队列第 \$\{Number\(j\.resource_queue_position\|\|0\)\|\|'-'\} 位/);
  assert.match(source, /j\.resource_wait_reason\|\|'等待可用资源'/);
  assert.match(source, /j\.worker_id\?` · Worker/);
});
''', encoding='utf-8')

print('conversion unified task truth patch prepared')
