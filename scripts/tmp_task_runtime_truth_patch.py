from pathlib import Path


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:100]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


ROOT = Path(__file__).resolve().parents[1]

# 1) Shared frontend single-source task truth contract.
(ROOT / "static/modules/task-runtime-truth.js").write_text(r'''const STATUS_ALIASES = Object.freeze({
  WAITING: 'WAITING_RESOURCE',
  PENDING: 'QUEUED',
  DONE: 'SUCCEEDED',
  FINISHED: 'SUCCEEDED',
  COMPLETED: 'SUCCEEDED',
  STOPPED: 'CANCELLED',
  CANCELED: 'CANCELLED',
  CANCELLING: 'CANCEL_REQUESTED',
});

const ACTIVE = new Set([
  'ACCEPTED', 'QUEUED', 'WAITING_RESOURCE', 'PREPARING', 'RUNNING',
  'PAUSING', 'PAUSED', 'RESUMING', 'CANCEL_REQUESTED', 'RETRYING',
]);

const TERMINAL = new Set([
  'AWAITING_CONFIRMATION', 'PARTIAL_SUCCESS', 'SUCCEEDED', 'CANCELLED',
  'FAILED', 'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE',
]);

function clampPercent(value) {
  const number = Number(value);
  if (!Number.isFinite(number)) return 0;
  return Math.max(0, Math.min(100, number));
}

export function canonicalTaskStatus(value) {
  const raw = value && typeof value === 'object'
    ? (value.task_status ?? value.status)
    : value;
  const normalized = String(raw || '').trim().toUpperCase();
  return STATUS_ALIASES[normalized] || normalized;
}

export function canonicalTaskPhase(task = {}) {
  return String(task?.phase ?? task?.task_stage ?? task?.stage ?? '').trim().toLowerCase();
}

export function canonicalTaskProgressPercent(task = {}) {
  if (task?.progress_percent !== null && task?.progress_percent !== undefined && task?.progress_percent !== '') {
    return clampPercent(task.progress_percent);
  }
  // Explicit compatibility only. Unified durable-task payloads must provide
  // progress_percent; never derive a percentage from item counts in the browser.
  if (task?.progress !== null && task?.progress !== undefined && task?.progress !== '') {
    return clampPercent(task.progress);
  }
  return 0;
}

export function isCanonicalTaskActive(value) {
  return ACTIVE.has(canonicalTaskStatus(value));
}

export function isCanonicalTaskTerminal(value) {
  const status = canonicalTaskStatus(value);
  return Boolean(status) && TERMINAL.has(status);
}

export function trainingDisplayStatus(task = {}) {
  const status = canonicalTaskStatus(task);
  if (status === 'WAITING_RESOURCE') return 'waiting';
  if (['ACCEPTED', 'QUEUED', 'PREPARING', 'RETRYING'].includes(status)) return 'queued';
  if (['RUNNING', 'PAUSING', 'RESUMING', 'CANCEL_REQUESTED'].includes(status)) return 'running';
  if (status === 'PAUSED') return 'paused';
  if (status === 'SUCCEEDED' || status === 'PARTIAL_SUCCESS') return 'completed';
  if (status === 'CANCELLED') return 'cancelled';
  if (['FAILED', 'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE'].includes(status)) return 'failed';
  if (status === 'AWAITING_CONFIRMATION') return 'pending';
  return String(task?.status ?? status ?? '').trim().toLowerCase();
}

export function taskRuntimeTruth(task = {}) {
  const position = Number(task?.resource_queue_position);
  return {
    task_id: String(task?.task_id ?? task?.id ?? ''),
    status: canonicalTaskStatus(task),
    persisted_status: String(task?.persisted_status ?? '').trim().toUpperCase(),
    phase: canonicalTaskPhase(task),
    progress_percent: canonicalTaskProgressPercent(task),
    current_item: String(task?.current_item ?? '').trim(),
    resource_queue_position: Number.isFinite(position) && position > 0 ? position : null,
    resource_queue_position_exact: task?.resource_queue_position_exact === true,
    resource_pool_key: String(task?.resource_pool_key ?? '').trim(),
    resource_pool_label: String(task?.resource_pool_label ?? '').trim(),
    resource_wait_reason: String(task?.resource_wait_reason ?? '').trim(),
    worker_id: String(task?.worker_id ?? task?.task_worker_id ?? '').trim(),
    error: String(task?.error ?? '').trim(),
  };
}
''', encoding="utf-8")

# 2) Shared poller consumes the same canonical truth and never derives percent from counts.
(ROOT / "static/modules/task-poller.js").write_text(r'''import {
  canonicalTaskProgressPercent,
  canonicalTaskStatus,
  isCanonicalTaskActive,
} from './task-runtime-truth.js';

export function normalizeTaskStatus(value) {
  return canonicalTaskStatus(value);
}

export function isTaskActive(value) {
  return isCanonicalTaskActive(value);
}

export function taskProgress(task = {}) {
  return {
    percent: canonicalTaskProgressPercent(task),
    completed: Math.max(0, Number(task.completed_units ?? task.completed_count) || 0),
    total: Math.max(0, Number(task.total_units ?? task.total_count) || 0),
    failed: Math.max(0, Number(task.failed_units ?? task.failed_count) || 0)
  };
}

export function createTaskPoller({load, onUpdate, onError = () => {}, delay = 1600, schedule = setTimeout, cancelSchedule = clearTimeout}) {
  let stopped = false;
  let timer = null;
  let generation = 0;
  async function refresh() {
    if (stopped) return null;
    const token = ++generation;
    try {
      const task = await load();
      if (stopped || token !== generation) return null;
      onUpdate(task);
      if (isTaskActive(task)) timer = schedule(refresh, delay);
      return task;
    } catch (error) {
      if (!stopped && token === generation) onError(error);
      return null;
    }
  }
  return {
    refresh,
    start: refresh,
    stop() {
      stopped = true;
      generation += 1;
      if (timer != null) cancelSchedule(timer);
      timer = null;
    }
  };
}
''', encoding="utf-8")

# 3) AI annotation and material-batch views use the same status precedence.
annotation = ROOT / "static/modules/annotation-task-view.js"
replace_once(annotation,
             "  const status = normalizeTaskStatus(task.status);",
             "  const status = normalizeTaskStatus(task);")

material = ROOT / "static/modules/material-batches.js"
material_text = material.read_text(encoding="utf-8")
if not material_text.startswith("import {canonicalTaskStatus, isCanonicalTaskActive} from './task-runtime-truth.js';"):
    material_text = "import {canonicalTaskStatus, isCanonicalTaskActive} from './task-runtime-truth.js';\n\n" + material_text
material_text = material_text.replace(
    "const ACTIVE = new Set(['QUEUED', 'WAITING_RESOURCE', 'RUNNING', 'CANCEL_REQUESTED']);\n\nexport function isMaterialBatchActive(value) {\n  return ACTIVE.has(String(value || '').toUpperCase());\n}",
    "export function isMaterialBatchActive(value) {\n  return isCanonicalTaskActive(value);\n}\n",
)
material_text = material_text.replace(
    "  const status = String(task.status || '').toUpperCase();",
    "  const status = canonicalTaskStatus(task);",
)
material_text = material_text.replace("isMaterialBatchActive(task.status)", "isMaterialBatchActive(task)")
material.write_text(material_text, encoding="utf-8")

# 4) Training UI keeps its legacy display vocabulary, but canonical durable task truth wins.
training = ROOT / "static/modules/training-task-runtime.js"
training_text = training.read_text(encoding="utf-8")
if not training_text.startswith("import {canonicalTaskPhase"):
    training_text = "import {canonicalTaskPhase, canonicalTaskProgressPercent, canonicalTaskStatus, trainingDisplayStatus} from './task-runtime-truth.js';\n\n" + training_text
training_text = training_text.replace(
    "function queueRuntimeMeta(job) {\n  const status = String(job?.status || '');",
    "function queueRuntimeMeta(job) {\n  const status = trainingDisplayStatus(job);",
)
training_text = training_text.replace(
    "export function trainingStageView(job = {}) {\n  const status = String(job?.status || '').trim().toLowerCase();\n  const stage = String(job?.task_stage || job?.stage || '').trim().toLowerCase();",
    "export function trainingStageView(job = {}) {\n  const status = trainingDisplayStatus(job);\n  const stage = canonicalTaskPhase(job);",
)
training_text = training_text.replace(
    "function terminalRuntimeMeta(job, stage) {\n  const status = String(job?.status || '').trim().toLowerCase();",
    "function terminalRuntimeMeta(job, stage) {\n  const status = trainingDisplayStatus(job);",
)
training_text = training_text.replace(
    "  const taskStatus = String(job?.task_status || '').trim().toUpperCase();",
    "  const taskStatus = canonicalTaskStatus(job);",
)
old_actions = '''function actions(job) {
  const id = esc(job.id);
  const detail = `<button class="btn mini" onclick="openTrainingRecoveryDetail('${id}')">详情</button>`;
  if (job.status === 'queued' || job.status === 'waiting') return `${detail}<button class="btn mini" onclick="promoteTrain428('${id}')">插队</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  if (job.status === 'running') return `${detail}<button class="btn mini" onclick="showTrainLog423('${id}')">日志</button><button class="btn mini" onclick="pauseTrain428('${id}')">暂停</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  if (job.status === 'paused') return `${detail}<button class="btn mini" onclick="showTrainLog423('${id}')">日志</button><button class="btn mini primary" onclick="resumeTrain428('${id}')">继续</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  return `${detail}<button class="btn mini" onclick="showTrainLog423('${id}')">日志</button>${job.auto_version_id ? `<button class="btn mini primary" onclick="trainingReport425('${id}')">训练报告</button>` : ''}<button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
}
'''
new_actions = '''function actions(job) {
  const id = esc(job.id);
  const status = trainingDisplayStatus(job);
  const detail = `<button class="btn mini" onclick="openTrainingRecoveryDetail('${id}')">详情</button>`;
  if (status === 'queued' || status === 'waiting') return `${detail}<button class="btn mini" onclick="promoteTrain428('${id}')">插队</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  if (status === 'running') return `${detail}<button class="btn mini" onclick="showTrainLog423('${id}')">日志</button><button class="btn mini" onclick="pauseTrain428('${id}')">暂停</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  if (status === 'paused') return `${detail}<button class="btn mini" onclick="showTrainLog423('${id}')">日志</button><button class="btn mini primary" onclick="resumeTrain428('${id}')">继续</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  return `${detail}<button class="btn mini" onclick="showTrainLog423('${id}')">日志</button>${job.auto_version_id ? `<button class="btn mini primary" onclick="trainingReport425('${id}')">训练报告</button>` : ''}<button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
}
'''
if training_text.count(old_actions) != 1:
    raise RuntimeError("training actions block did not match exactly")
training_text = training_text.replace(old_actions, new_actions, 1)
training_text = training_text.replace(
    "export function trainingTaskRow(job) {\n  const percent = Math.max(0, Math.min(100, Number(job?.progress_percent || 0)));",
    "export function trainingTaskRow(job) {\n  const status = trainingDisplayStatus(job);\n  const percent = canonicalTaskProgressPercent(job);",
)
training_text = training_text.replace(
    "  const done = DONE_STATUSES.has(String(job?.status || ''));\n  const successful = ['done', 'finished', 'completed'].includes(String(job?.status || ''));",
    "  const done = DONE_STATUSES.has(status);\n  const successful = ['done', 'finished', 'completed'].includes(status);",
)
training_text = training_text.replace(
    "<span class=\"pill ${statusClass(job.status)}\">${esc(statusText(job.status))}</span>",
    "<span class=\"pill ${statusClass(status)}\">${esc(statusText(status))}</span>",
)
old_visible = '''export function visibleTrainingJobs(jobs, tab = 'active') {
  const rows = Array.isArray(jobs) ? jobs : [];
  const filtered = tab === 'history'
    ? rows.filter(job => DONE_STATUSES.has(job.status) || !ACTIVE_STATUSES.has(job.status))
    : rows.filter(job => ACTIVE_STATUSES.has(job.status));
  const rank = status => status === 'running' ? 0 : status === 'paused' ? 1 : status === 'waiting' ? 2 : status === 'queued' ? 3 : 4;
  return [...filtered].sort((a, b) => {
    const ar = rank(a.status), br = rank(b.status);
    if (ar !== br) return ar - br;
    if (['queued', 'waiting'].includes(String(a.status))) return priorityValue(a) - priorityValue(b);
    return String(b.started_at || b.created_at || '').localeCompare(String(a.started_at || a.created_at || ''));
  });
}
'''
new_visible = '''export function visibleTrainingJobs(jobs, tab = 'active') {
  const rows = Array.isArray(jobs) ? jobs : [];
  const filtered = tab === 'history'
    ? rows.filter(job => {
        const status = trainingDisplayStatus(job);
        return DONE_STATUSES.has(status) || !ACTIVE_STATUSES.has(status);
      })
    : rows.filter(job => ACTIVE_STATUSES.has(trainingDisplayStatus(job)));
  const rank = status => status === 'running' ? 0 : status === 'paused' ? 1 : status === 'waiting' ? 2 : status === 'queued' ? 3 : 4;
  return [...filtered].sort((a, b) => {
    const aStatus = trainingDisplayStatus(a), bStatus = trainingDisplayStatus(b);
    const ar = rank(aStatus), br = rank(bStatus);
    if (ar !== br) return ar - br;
    if (['queued', 'waiting'].includes(aStatus)) return priorityValue(a) - priorityValue(b);
    return String(b.started_at || b.created_at || '').localeCompare(String(a.started_at || a.created_at || ''));
  });
}
'''
if training_text.count(old_visible) != 1:
    raise RuntimeError("visibleTrainingJobs block did not match exactly")
training_text = training_text.replace(old_visible, new_visible, 1)
training_text = training_text.replace(
    "    const active = jobs.filter(job => ACTIVE_STATUSES.has(job.status));\n    const history = jobs.filter(job => DONE_STATUSES.has(job.status) || !ACTIVE_STATUSES.has(job.status));",
    "    const active = jobs.filter(job => ACTIVE_STATUSES.has(trainingDisplayStatus(job)));\n    const history = jobs.filter(job => {\n      const status = trainingDisplayStatus(job);\n      return DONE_STATUSES.has(status) || !ACTIVE_STATUSES.has(status);\n    });",
)
training_text = training_text.replace(
    "      if (job && ['running', 'paused', 'queued', 'waiting'].includes(job.status)) {",
    "      if (job && ['running', 'paused', 'queued', 'waiting'].includes(trainingDisplayStatus(job))) {",
)
training.write_text(training_text, encoding="utf-8")

# 5) Backend bridge: canonical durable task truth is projected once; legacy status remains compatibility only.
(ROOT / "platform_core/training_job_projection.py").write_text(r'''from __future__ import annotations

from typing import Any, Mapping, MutableMapping


def _clamp_percent(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(100.0, number))


def apply_training_task_truth(
    job: MutableMapping[str, Any],
    public_runtime: Mapping[str, Any],
    *,
    legacy_status: str,
) -> MutableMapping[str, Any]:
    """Project durable task truth onto the legacy training-job response.

    `status` and `task_stage` remain compatibility aliases. New frontend runtime
    code must prefer `task_status`, `phase`, `progress_percent`, and resource_*.
    """
    phase = str(public_runtime.get("phase") or "")
    job.update(
        status=str(legacy_status or ""),
        task_status=str(public_runtime.get("status") or ""),
        persisted_status=str(public_runtime.get("persisted_status") or ""),
        phase=phase,
        task_stage=phase,
        progress_percent=_clamp_percent(public_runtime.get("progress_percent")),
        current_item=public_runtime.get("current_item"),
        resource_queue_position=public_runtime.get("resource_queue_position"),
        resource_queue_position_exact=public_runtime.get("resource_queue_position_exact") is True,
        resource_pool_key=public_runtime.get("resource_pool_key"),
        resource_pool_label=str(public_runtime.get("resource_pool_label") or "训练资源"),
        resource_wait_reason=public_runtime.get("resource_wait_reason"),
        task_worker_id=public_runtime.get("worker_id"),
        task_lease_expires_at=public_runtime.get("lease_expires_at"),
    )
    return job
''', encoding="utf-8")

app = ROOT / "app.py"
app_text = app.read_text(encoding="utf-8")
import_anchor = "from platform_core.task_runtime import ("
if "from platform_core.training_job_projection import apply_training_task_truth" not in app_text:
    if app_text.count(import_anchor) != 1:
        raise RuntimeError("app task_runtime import anchor mismatch")
    app_text = app_text.replace(import_anchor, "from platform_core.training_job_projection import apply_training_task_truth\n" + import_anchor, 1)
old_projection = '''        job.update(
            status=mapped,
            progress_percent=float(durable.progress),
            task_stage=durable.stage,
            task_status=public_runtime["status"],
            current_item=durable.current_item,
            result_ref=durable.result_ref or job.get("result_ref"),
            queue_priority=int(durable.priority),
            priority_scheme="lower_number_first",
            resource_queue_position=public_runtime["resource_queue_position"],
            resource_wait_reason=public_runtime["resource_wait_reason"],
            resource_queue_position_exact=public_runtime.get("resource_queue_position_exact", False),
            resource_pool_key=public_runtime.get("resource_pool_key", durable.resource_key),
            resource_pool_label=public_runtime.get("resource_pool_label", "训练资源"),
            task_worker_id=public_runtime["worker_id"],
            task_lease_expires_at=public_runtime["lease_expires_at"],
        )
'''
new_projection = '''        apply_training_task_truth(job, public_runtime, legacy_status=mapped)
        job.update(
            result_ref=durable.result_ref or job.get("result_ref"),
            queue_priority=int(durable.priority),
            priority_scheme="lower_number_first",
        )
'''
if app_text.count(old_projection) != 1:
    raise RuntimeError(f"app legacy projection block mismatch: {app_text.count(old_projection)}")
app_text = app_text.replace(old_projection, new_projection, 1)
app.write_text(app_text, encoding="utf-8")

# 6) Permanent tests: backend bridge and frontend shared truth.
(ROOT / "tests/unit/test_training_job_projection.py").write_text(r'''from platform_core.training_job_projection import apply_training_task_truth


def test_training_job_projection_keeps_legacy_aliases_but_exposes_canonical_truth():
    job = {"id": "job-1", "status": "queued", "task_stage": "queued"}
    runtime = {
        "status": "WAITING_RESOURCE",
        "persisted_status": "QUEUED",
        "phase": "resource_waiting",
        "progress_percent": 37.5,
        "current_item": "等待 GPU",
        "resource_queue_position": 2,
        "resource_queue_position_exact": False,
        "resource_pool_key": "gpu:auto",
        "resource_pool_label": "GPU 自动",
        "resource_wait_reason": "GPU_MEMORY_BUSY",
        "worker_id": None,
        "lease_expires_at": None,
    }

    apply_training_task_truth(job, runtime, legacy_status="waiting")

    assert job["status"] == "waiting"
    assert job["task_status"] == "WAITING_RESOURCE"
    assert job["persisted_status"] == "QUEUED"
    assert job["phase"] == "resource_waiting"
    assert job["task_stage"] == "resource_waiting"
    assert job["progress_percent"] == 37.5
    assert job["current_item"] == "等待 GPU"
    assert job["resource_queue_position"] == 2
    assert job["resource_queue_position_exact"] is False
    assert job["resource_pool_key"] == "gpu:auto"
    assert job["resource_pool_label"] == "GPU 自动"
    assert job["resource_wait_reason"] == "GPU_MEMORY_BUSY"


def test_training_job_projection_clamps_progress_and_never_invents_queue_exactness():
    job = {}
    runtime = {
        "status": "RUNNING",
        "persisted_status": "RUNNING",
        "phase": "training",
        "progress_percent": 180,
        "current_item": "Epoch 1/10",
        "resource_queue_position": None,
        "worker_id": "worker-a",
        "lease_expires_at": "2026-09-16T00:00:00Z",
    }
    apply_training_task_truth(job, runtime, legacy_status="running")

    assert job["progress_percent"] == 100.0
    assert job["resource_queue_position_exact"] is False
    assert job["task_worker_id"] == "worker-a"
''', encoding="utf-8")

(ROOT / "tests/frontend/task-runtime-truth.test.mjs").write_text(r'''import test from 'node:test';
import assert from 'node:assert/strict';

import {
  canonicalTaskPhase,
  canonicalTaskProgressPercent,
  canonicalTaskStatus,
  isCanonicalTaskActive,
  taskRuntimeTruth,
  trainingDisplayStatus,
} from '../../static/modules/task-runtime-truth.js';

test('canonical durable task fields win over stale legacy aliases', () => {
  const task = {
    status: 'completed',
    task_status: 'WAITING_RESOURCE',
    stage: 'committed',
    task_stage: 'queued',
    phase: 'resource_waiting',
    progress: 99,
    progress_percent: 17,
  };
  assert.equal(canonicalTaskStatus(task), 'WAITING_RESOURCE');
  assert.equal(canonicalTaskPhase(task), 'resource_waiting');
  assert.equal(canonicalTaskProgressPercent(task), 17);
  assert.equal(trainingDisplayStatus(task), 'waiting');
  assert.equal(isCanonicalTaskActive(task), true);
});

test('browser never invents durable task percentage from item counts', () => {
  assert.equal(canonicalTaskProgressPercent({completed_count: 50, total_count: 100}), 0);
  assert.equal(canonicalTaskProgressPercent({progress: 41, completed_count: 99, total_count: 100}), 41);
  assert.equal(canonicalTaskProgressPercent({progress: 41, progress_percent: 23}), 23);
});

test('runtime truth preserves backend queue exactness instead of promoting a candidate rank', () => {
  const truth = taskRuntimeTruth({
    task_id: 'train-1',
    status: 'QUEUED',
    phase: 'resource_waiting',
    progress_percent: 8,
    resource_queue_position: 3,
    resource_queue_position_exact: false,
    resource_pool_label: 'GPU 自动',
  });
  assert.equal(truth.status, 'QUEUED');
  assert.equal(truth.resource_queue_position, 3);
  assert.equal(truth.resource_queue_position_exact, false);
});
''', encoding="utf-8")

training_test = ROOT / "tests/frontend/training-task-runtime.test.mjs"
training_test_text = training_test.read_text(encoding="utf-8")
append_test = r'''

test('training list and row use canonical task_status over stale legacy status', async () => {
  const {trainingTaskRow, visibleTrainingJobs} = await import('../../static/modules/training-task-runtime.js');
  const task = {
    id: 'truth-1',
    status: 'completed',
    task_status: 'WAITING_RESOURCE',
    persisted_status: 'QUEUED',
    phase: 'resource_waiting',
    task_stage: 'committed',
    progress_percent: 12,
    resource_pool_label: 'GPU 自动',
    resource_wait_reason: 'GPU_MEMORY_BUSY',
    resource_queue_position: 4,
    resource_queue_position_exact: false,
    framework: 'ultralytics',
    total_epochs: 30,
  };

  assert.equal(visibleTrainingJobs([task], 'active').length, 1);
  assert.equal(visibleTrainingJobs([task], 'history').length, 0);
  const html = trainingTaskRow(task);
  assert.match(html, /等待资源/);
  assert.match(html, /GPU 自动/);
  assert.match(html, /GPU_MEMORY_BUSY/);
  assert.match(html, /12%/);
  assert.doesNotMatch(html, /队列第 4 位/);
});
'''
if "training list and row use canonical task_status over stale legacy status" not in training_test_text:
    training_test.write_text(training_test_text + append_test, encoding="utf-8")

# Strengthen the existing poller test with canonical precedence.
poller_test = ROOT / "tests/frontend/task-poller.test.mjs"
poller_text = poller_test.read_text(encoding="utf-8")
extra = r'''

test('poller uses task_status and progress_percent as canonical backend truth', () => {
  assert.equal(isTaskActive({status: 'completed', task_status: 'RUNNING'}), true);
  assert.deepEqual(taskProgress({progress: 81, progress_percent: 19, completed_count: 90, total_count: 100}), {
    percent: 19, completed: 90, total: 100, failed: 0
  });
});
'''
if "poller uses task_status and progress_percent as canonical backend truth" not in poller_text:
    poller_test.write_text(poller_text + extra, encoding="utf-8")

# Handoff for the next agent/session.
(ROOT / "docs/CODEX_HANDOFF_2026-09-16_TASK_RUNTIME_TRUTH_V1.md").write_text(r'''# Task Runtime Truth v1 handoff — 2026-09-16

## Scope

This batch closes the first frontend/backend consistency layer for real queue and live progress.
It does not replace the legacy training jobs endpoints. Instead, durable task truth is projected
onto them explicitly while compatibility aliases remain available.

## Canonical backend fields

Frontend runtime truth is now based on:

- `task_status` (or `status` on native durable-task responses)
- `persisted_status`
- `phase`
- `progress_percent`
- `current_item`
- `resource_queue_position`
- `resource_queue_position_exact`
- `resource_pool_key`
- `resource_pool_label`
- `resource_wait_reason`
- worker / error fields

For `/api/projects/{project_id}/jobs`, `status` and `task_stage` remain compatibility aliases.
`task_status` and `phase` are authoritative when both old and new fields exist.

## Frontend contract

`static/modules/task-runtime-truth.js` is the shared adapter. Training, AI annotation,
material batches, and the shared task poller must not invent independent status semantics.
`progress_percent` wins over legacy `progress`; item counts are display data only and are
never used to fabricate a durable task percentage.

Training keeps its old UI vocabulary (`waiting`, `queued`, `running`, etc.) only through
`trainingDisplayStatus()`, which derives that vocabulary from canonical task status.

## Queue correctness

`resource_queue_position_exact` remains the sole proof that a numeric queue position may be
presented as exact. `queue_rank`, priority, and candidate order are not substitutes.

## Validation boundary

Focused Python and Node tests cover the projection contract and frontend precedence.
Windows + Ubuntu CI is the permanent gate. Production-host behavior (real Windows drive set,
real Linux/A800 workers, and true concurrent load) remains a separate acceptance layer.
''', encoding="utf-8")

print("Task Runtime Truth v1 patch applied")
