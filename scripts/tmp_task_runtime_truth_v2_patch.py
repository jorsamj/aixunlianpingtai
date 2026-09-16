from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected exactly one match, found {count}: {old[:120]!r}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


# Shared truth: a numeric queue position is presentationally exact only when the
# backend explicitly proves exactness.
truth = ROOT / "static/modules/task-runtime-truth.js"
text = truth.read_text(encoding="utf-8")
anchor = "export function trainingDisplayStatus(task = {}) {"
helper = '''export function exactTaskQueuePosition(task = {}) {
  const truth = taskRuntimeTruth(task);
  return truth.resource_queue_position_exact ? truth.resource_queue_position : null;
}

'''
if "export function exactTaskQueuePosition" not in text:
    if text.count(anchor) != 1:
        raise RuntimeError("task runtime truth anchor mismatch")
    text = text.replace(anchor, helper + anchor, 1)
truth.write_text(text, encoding="utf-8")

# Storage scan progress: canonical task_status/phase wins; only exact queue rank is shown.
storage = ROOT / "static/modules/storage-import-progress.js"
storage.write_text(r'''import {isTaskActive, taskProgress} from './task-poller.js?v=422001';
import {canonicalTaskPhase, canonicalTaskStatus, exactTaskQueuePosition} from './task-runtime-truth.js';

const POLL_KEY = 'storage-import-scan-v61';
const OWNER_PAGE = '素材存储配置';
const POLL_DELAY = 1200;

export function storageImportProgressText(task = {}) {
  const status = canonicalTaskStatus(task);
  const stage = (canonicalTaskPhase(task) || status || 'SCANNING').toUpperCase();
  const current = String(task.current_item || '').trim();
  const {percent} = taskProgress(task);
  const queuePosition = exactTaskQueuePosition(task);
  const priority = Number(task.priority || 0);
  const worker = String(task.worker_id || task.task_worker_id || '').trim();
  const waitReason = String(task.resource_wait_reason || '').trim();
  if (status === 'WAITING_RESOURCE') {
    return ['等待资源', queuePosition ? `队列第 ${queuePosition} 位` : '', waitReason].filter(Boolean).join(' · ');
  }
  if (status === 'QUEUED') {
    return ['排队中', queuePosition ? `队列第 ${queuePosition} 位` : '', priority > 0 ? `优先级 ${priority}` : ''].filter(Boolean).join(' · ');
  }
  if (stage === 'FINALIZING') return percent > 0 ? `正在整理扫描结果 · ${percent.toFixed(0)}%` : '正在整理扫描结果';
  const parts = [stage];
  if (percent > 0) parts.push(`${percent.toFixed(0)}%`);
  if (current) parts.push(current);
  if (worker) parts.push(`执行节点 ${worker}`);
  if (parts.length === 1) parts.push('正在扫描对象');
  return parts.join(' · ');
}

async function responseJson(response) {
  if (response.ok) return response.json();
  const text = await response.text();
  let body = {};
  try { body = JSON.parse(text); } catch (_error) { body = {detail: text}; }
  throw new Error(body.message || body.detail || `HTTP ${response.status}`);
}

export function installStorageImportProgressRuntime({pollRegistry, getState} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;
  if (window.StorageImportProgressRuntime?.build === 'storage-import-progress-422520') {
    return window.StorageImportProgressRuntime;
  }

  const registry = pollRegistry || window.PollRegistryRuntime;
  if (!registry?.startTimeout || !registry?.clear) return null;

  let trackedTaskId = '';
  let currentTask = null;
  let settle = null;
  let rejectCurrent = null;

  const state = () => getState?.() || {};

  function statusElement() {
    return document.getElementById('si61Status');
  }

  function render(task) {
    currentTask = task || currentTask;
    if (!currentTask) return;
    const status = statusElement();
    if (status) status.textContent = storageImportProgressText(currentTask);
    if (typeof window.renderStorageImportTask61 === 'function') {
      window.renderStorageImportTask61(currentTask);
    }
  }

  function finish(task) {
    const resolve = settle;
    settle = null;
    rejectCurrent = null;
    trackedTaskId = '';
    currentTask = task || currentTask;
    registry.clear(POLL_KEY);
    resolve?.(currentTask);
  }

  function fail(error) {
    const reject = rejectCurrent;
    settle = null;
    rejectCurrent = null;
    trackedTaskId = '';
    registry.clear(POLL_KEY);
    reject?.(error);
  }

  function schedule() {
    if (!trackedTaskId || !isTaskActive(currentTask)) return finish(currentTask);
    return registry.startTimeout(POLL_KEY, OWNER_PAGE, async () => {
      if (!trackedTaskId) return;
      const s = state();
      const projectId = String(s.project?.id || '');
      if (!projectId) return fail(new Error('当前项目不可用'));
      try {
        const task = await responseJson(await fetch(
          `/api/v62/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(trackedTaskId)}`,
        ));
        if (!trackedTaskId) return;
        render(task);
        if (isTaskActive(task)) schedule();
        else finish(task);
      } catch (error) {
        fail(error);
      }
    }, POLL_DELAY);
  }

  function stop() {
    registry.clear(POLL_KEY);
    trackedTaskId = '';
    const resolve = settle;
    settle = null;
    rejectCurrent = null;
    const last = currentTask;
    currentTask = null;
    resolve?.(last || null);
    return true;
  }

  function track(taskId, initialTask = null) {
    stop();
    trackedTaskId = String(taskId || '').trim();
    currentTask = initialTask || null;
    if (!trackedTaskId) return Promise.resolve(null);
    render(currentTask || {task_id: trackedTaskId, status: 'QUEUED'});
    const promise = new Promise((resolve, reject) => {
      settle = resolve;
      rejectCurrent = reject;
    });
    if (isTaskActive(currentTask || 'QUEUED')) schedule();
    else finish(currentTask);
    return promise;
  }

  const runtime = Object.freeze({
    build: 'storage-import-progress-422520',
    track,
    stop,
    current: () => currentTask,
  });
  window.StorageImportProgressRuntime = runtime;
  return runtime;
}
''', encoding="utf-8")

# Server-side material import is a native durable task response.
server = ROOT / "static/modules/server-material-import.js"
server.write_text(r'''import {
  canonicalTaskPhase,
  canonicalTaskStatus,
  exactTaskQueuePosition,
  isCanonicalTaskActive,
  isCanonicalTaskTerminal,
} from './task-runtime-truth.js';

function count(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

export function buildServerImportRequest(values = {}) {
  const mode = String(values.mode || 'directory_scan');
  const storageSourceId = String(values.storageSourceId || '').trim();
  if (!storageSourceId) throw new Error('请选择本地存储源');
  const importFormat = String(values.importFormat || 'auto');
  if (!['auto', 'images', 'yolo'].includes(importFormat)) throw new Error('暂不支持 COCO/VOC 服务器导入');
  const format = {import_format: importFormat};
  if (values.datasetYaml && importFormat !== 'images') format.dataset_yaml = String(values.datasetYaml).trim();

  if (mode === 'directory_scan') {
    return {
      mode,
      ...format,
      storage_source_id: storageSourceId,
      prefix: String(values.prefix || '').trim(),
      recursive: values.recursive !== false,
    };
  }
  if (mode === 'server_zip') {
    const zipPath = String(values.zipPath || '').trim();
    const targetPrefix = String(values.targetPrefix || '').trim();
    if (!zipPath) throw new Error('请选择服务器 ZIP');
    if (!targetPrefix) throw new Error('请填写 ZIP 解压目标目录');
    return {
      mode,
      ...format,
      storage_source_id: storageSourceId,
      zip_path: zipPath,
      target_prefix: targetPrefix,
      recursive: true,
    };
  }
  throw new Error(`不支持的导入方式：${mode}`);
}

export function buildImportConfirmation(rows = [], acceptQualityReport = false) {
  const label_mapping = {}, create_labels = [];
  for (const row of rows) {
    const code = String(row.code || '').trim();
    if (!code) throw new Error(`请选择外部类别 ${row.name || row.classId} 对应的平台标签`);
    label_mapping[String(row.classId)] = code;
    if (row.create) create_labels.push(code);
  }
  return {label_mapping, create_labels: [...new Set(create_labels)], accept_quality_report: Boolean(acceptQualityReport)};
}

export function serverImportView(task = {}) {
  const status = canonicalTaskStatus(task) || 'QUEUED';
  const stage = canonicalTaskPhase(task);
  const metrics = task.metrics || {};
  const current = String(metrics.current_file || task.current_item || '-');
  const queuePosition = exactTaskQueuePosition(task);
  const waitReason = String(task.resource_wait_reason || '').trim();
  let text;

  if (status === 'WAITING_RESOURCE') {
    text = ['等待 Storage Worker 资源', queuePosition ? `队列第 ${queuePosition} 位` : '', waitReason].filter(Boolean).join(' · ');
  } else if (stage === 'extracting') {
    text = `已解压 ${count(metrics.extracted_files)} 个文件 · ${count(metrics.extracted_bytes)} 字节 · 当前 ${current}`;
  } else if (stage === 'scanning') {
    text = `已扫描 ${count(metrics.scanned_files)} · 可导入 ${count(metrics.importable_images)} · 重复 ${count(metrics.duplicates)} · 失败 ${count(metrics.failed) + count(metrics.invalid_images)} · 当前 ${current}`;
  } else if (stage === 'indexing' || stage === 'indexing_queued') {
    text = `正在建立索引 ${count(metrics.indexed_at_least ?? metrics.indexed)} / ${count(metrics.selected)}`;
  } else if (status === 'AWAITING_CONFIRMATION') {
    text = '扫描完成，等待确认建立素材索引';
  } else if (status === 'QUEUED') {
    text = queuePosition ? `任务已进入 Storage Worker 队列 · 第 ${queuePosition} 位` : '任务已进入 Storage Worker 队列';
  } else if (status === 'SUCCEEDED') {
    text = `导入完成，共建立 ${count(task.result?.imported)} 条素材索引`;
  } else if (status === 'FAILED' || status === 'CANCELLED') {
    text = String(task.error || task.result?.error?.message || status);
  } else {
    text = stage || status;
  }

  return {
    status,
    stage,
    text,
    active: isCanonicalTaskActive(task),
    canConfirm: status === 'AWAITING_CONFIRMATION',
    showPercent: stage === 'extracting' && count(metrics.declared_bytes) > 0,
    terminal: isCanonicalTaskTerminal(task),
  };
}
''', encoding="utf-8")

# Video tasks: canonical durable status/progress plus exact queue truth.
video = ROOT / "static/modules/video-tasks.js"
video.write_text(r'''import {
  canonicalTaskProgressPercent,
  canonicalTaskStatus,
  exactTaskQueuePosition,
  isCanonicalTaskActive,
} from './task-runtime-truth.js';

const STATUS_TEXT = {
  ACCEPTED: '已受理',
  QUEUED: '排队中',
  WAITING_RESOURCE: '等待资源',
  PREPARING: '准备中',
  RUNNING: '处理中',
  PAUSING: '暂停中',
  PAUSED: '已暂停',
  RESUMING: '恢复中',
  RETRYING: '重试中',
  AWAITING_CONFIRMATION: '待确认',
  PARTIAL_SUCCESS: '部分成功',
  SUCCEEDED: '已完成',
  CANCEL_REQUESTED: '正在停止',
  CANCELLED: '已停止',
  FAILED: '失败',
  BLOCKED_BY_ENVIRONMENT: '缺少运行环境',
  BLOCKED_BY_HARDWARE: '缺少硬件',
};

function positive(value, field) {
  const number = Number(value);
  if (!Number.isFinite(number) || number <= 0) throw new Error(`${field} 必须大于 0`);
  return number;
}

export function videoTaskFormValues(mode, values = {}) {
  const payload = {mode};
  if (mode === 'interval_seconds') payload.interval_seconds = positive(values.intervalSeconds, '时间间隔');
  else if (mode === 'fps') payload.extract_fps = positive(values.extractFps, '抽帧率');
  else if (mode === 'fixed_count') payload.fixed_count = Math.trunc(positive(values.fixedCount, '固定帧数'));
  else throw new Error('不支持的切帧方式');
  if (Number(values.maxFrames) > 0) payload.max_frames = Math.trunc(Number(values.maxFrames));
  return payload;
}

export function isActiveVideoTask(task) {
  return isCanonicalTaskActive(task);
}

export function normalizeVideoTask(task = {}) {
  const status = canonicalTaskStatus(task);
  const progressPercent = canonicalTaskProgressPercent(task);
  let samplingText = '未知方式';
  if (task.mode === 'fixed_count') samplingText = `固定抽取 ${Number(task.fixed_count || 0)} 帧`;
  else if (task.mode === 'fps') samplingText = `每秒 ${Number(task.extract_fps || 0)} 帧`;
  else if (task.mode === 'interval_seconds') samplingText = `每 ${Number(task.interval_seconds || 0)} 秒 1 帧`;
  const queuePosition = exactTaskQueuePosition(task);
  const waitReason = String(task.resource_wait_reason || '').trim();
  const queuedRuntime = queuePosition
    ? `资源队列第 ${queuePosition} 位${waitReason ? ` · ${waitReason}` : ''}`
    : (waitReason ? `等待资源 · ${waitReason}` : '');
  const runtimeText = ['QUEUED', 'WAITING_RESOURCE'].includes(status) ? queuedRuntime : '';
  return {
    ...task,
    status,
    progress: progressPercent,
    progress_percent: progressPercent,
    statusText: STATUS_TEXT[status] || status,
    queuePosition,
    waitReason,
    runtimeText,
    samplingText,
    extractedFrames: Number(task.result?.extracted_frames ?? task.extracted_frames ?? 0),
  };
}
''', encoding="utf-8")

# Deployment test tasks already use the poller, but must pass the whole task so
# canonical task_status can outrank a stale compatibility status.
deploy = ROOT / "static/modules/deployment-tests.js"
deploy.write_text(r'''import {isTaskActive, normalizeTaskStatus, taskProgress} from './task-poller.js';
import {canonicalTaskPhase, exactTaskQueuePosition} from './task-runtime-truth.js';

function statusFallback(status) {
  return ({
    ACCEPTED: '已受理',
    QUEUED: '排队中',
    WAITING_RESOURCE: '等待资源',
    PREPARING: '准备中',
    RUNNING: '测试中',
    PAUSING: '暂停中',
    PAUSED: '已暂停',
    RESUMING: '恢复中',
    CANCEL_REQUESTED: '取消中',
    RETRYING: '重试中',
    SUCCEEDED: '已完成',
    FAILED: '失败',
    CANCELLED: '已取消',
    BLOCKED_BY_ENVIRONMENT: '环境阻塞',
    BLOCKED_BY_HARDWARE: '硬件阻塞',
  })[status] || status || '-';
}

export function deploymentTaskView(task = {}) {
  const status = normalizeTaskStatus(task);
  const progress = taskProgress(task);
  const queuePosition = exactTaskQueuePosition(task);
  const waitReason = String(task.resource_wait_reason || '').trim();
  const workerId = String(task.worker_id || task.task_worker_id || '').trim();
  const phase = canonicalTaskPhase(task);
  const currentItem = String(task.current_item || '').trim();
  const runtime = [];

  if ((status === 'QUEUED' || status === 'WAITING_RESOURCE') && queuePosition) {
    runtime.push(`资源队列第 ${queuePosition} 位`);
  }
  if (status === 'WAITING_RESOURCE' && waitReason) runtime.push(waitReason);
  if (status === 'RUNNING' && workerId) runtime.push(`Worker ${workerId}`);
  if (currentItem) runtime.push(currentItem);

  return {
    ...task,
    status,
    statusText: String(task.status_text || statusFallback(status)),
    percent: progress.percent,
    phase,
    runtimeText: runtime.join(' · '),
    active: isTaskActive(task),
  };
}
''', encoding="utf-8")

# Resource discovery: keep environment/model cache status helpers, but durable
# task polling/rendering uses the shared task truth contract.
resource = ROOT / "static/modules/resource-discovery.js"
resource_text = resource.read_text(encoding="utf-8")
if not resource_text.startswith("import {"):
    resource_text = "import {canonicalTaskPhase, canonicalTaskStatus, isCanonicalTaskActive} from './task-runtime-truth.js';\n\n" + resource_text
resource_text = resource_text.replace("const ACTIVE_TASK_STATUSES = new Set(['QUEUED', 'RUNNING', 'CANCEL_REQUESTED']);\n", "")
resource_text = resource_text.replace("    const taskStatus = status(task.status);", "    const taskStatus = canonicalTaskStatus(task);")
resource_text = resource_text.replace("    const taskStatus = status(task.status);", "    const taskStatus = canonicalTaskStatus(task);")
resource_text = resource_text.replace("<b>${escapeHtml(task.stage || '等待 Worker 领取')}</b>", "<b>${escapeHtml(canonicalTaskPhase(task) || '等待 Worker 领取')}</b>")
resource_text = resource_text.replace("${ACTIVE_TASK_STATUSES.has(taskStatus) ? '<div class=\"rd-indeterminate\"><i></i></div>' : ''}", "${isCanonicalTaskActive(task) ? '<div class=\"rd-indeterminate\"><i></i></div>' : ''}")
resource_text = resource_text.replace("while (!controller.signal.aborted && ACTIVE_TASK_STATUSES.has(status(task.status)))", "while (!controller.signal.aborted && isCanonicalTaskActive(task))")
resource_text = resource_text.replace("if (SUCCESS_TASK_STATUSES.has(status(task.status)))", "if (SUCCESS_TASK_STATUSES.has(canonicalTaskStatus(task)))")
resource_text = resource_text.replace("} else if (status(task.status) === 'FAILED') {", "} else if (canonicalTaskStatus(task) === 'FAILED') {")
resource_text = resource_text.replace("} else if (status(task.status) === 'CANCELLED') {", "} else if (canonicalTaskStatus(task) === 'CANCELLED') {")
resource.write_text(resource_text, encoding="utf-8")

# ---- Tests ----
truth_test = ROOT / "tests/frontend/task-runtime-truth.test.mjs"
tt = truth_test.read_text(encoding="utf-8")
tt = tt.replace("  canonicalTaskStatus,\n", "  canonicalTaskStatus,\n  exactTaskQueuePosition,\n")
extra = r'''

test('exact queue position is presentationally usable only with explicit backend exactness', () => {
  assert.equal(exactTaskQueuePosition({resource_queue_position: 2, resource_queue_position_exact: true}), 2);
  assert.equal(exactTaskQueuePosition({resource_queue_position: 2, resource_queue_position_exact: false}), null);
  assert.equal(exactTaskQueuePosition({resource_queue_position: 2}), null);
});
'''
if "exact queue position is presentationally usable" not in tt:
    tt += extra
truth_test.write_text(tt, encoding="utf-8")

storage_test = ROOT / "tests/frontend/storage-import-progress.test.mjs"
st = storage_test.read_text(encoding="utf-8")
st = st.replace("{status: 'QUEUED', resource_queue_position: 3, priority: 1}", "{status: 'QUEUED', resource_queue_position: 3, resource_queue_position_exact: true, priority: 1}")
st = st.replace("{status: 'WAITING_RESOURCE', resource_queue_position: 2, resource_wait_reason: 'RESOURCE_BUSY'}", "{status: 'WAITING_RESOURCE', resource_queue_position: 2, resource_queue_position_exact: true, resource_wait_reason: 'RESOURCE_BUSY'}")
st = st.replace("resource_queue_position: 4, resource_wait_reason: 'STORAGE_WORKER_BUSY',", "resource_queue_position: 4, resource_queue_position_exact: true, resource_wait_reason: 'STORAGE_WORKER_BUSY',")
st_extra = r'''

test('storage import canonical task_status wins and inexact queue rank is never shown as position', () => {
  const text = storageImportProgressText({
    status: 'SUCCEEDED', task_status: 'WAITING_RESOURCE', phase: 'resource_waiting',
    resource_queue_position: 7, resource_queue_position_exact: false,
    resource_wait_reason: 'STORAGE_WORKER_BUSY',
  });
  assert.match(text, /等待资源/);
  assert.match(text, /STORAGE_WORKER_BUSY/);
  assert.doesNotMatch(text, /队列第 7 位/);
});
'''
if "storage import canonical task_status wins" not in st:
    st += st_extra
storage_test.write_text(st, encoding="utf-8")

server_test = ROOT / "tests/frontend/server-material-import.test.mjs"
svt = server_test.read_text(encoding="utf-8")
svt = svt.replace("    resource_queue_position: 2,\n    resource_wait_reason", "    resource_queue_position: 2,\n    resource_queue_position_exact: true,\n    resource_wait_reason")
sv_extra = r'''

test('server import canonical task status wins and candidate queue rank is not presented as exact', () => {
  const waiting = serverImportView({
    status: 'SUCCEEDED', task_status: 'WAITING_RESOURCE', phase: 'resource_waiting',
    resource_queue_position: 9, resource_queue_position_exact: false,
    resource_wait_reason: 'STORAGE_WORKER_BUSY',
  });
  assert.equal(waiting.status, 'WAITING_RESOURCE');
  assert.equal(waiting.active, true);
  assert.match(waiting.text, /等待 Storage Worker 资源/);
  assert.match(waiting.text, /STORAGE_WORKER_BUSY/);
  assert.doesNotMatch(waiting.text, /队列第 9 位/);
});
'''
if "server import canonical task status wins" not in svt:
    svt += sv_extra
server_test.write_text(svt, encoding="utf-8")

video_test = ROOT / "tests/frontend/video-tasks.test.mjs"
vt = video_test.read_text(encoding="utf-8")
vt = vt.replace("    resource_queue_position: 3,\n", "    resource_queue_position: 3, resource_queue_position_exact: true,\n")
vt = vt.replace("    resource_queue_position: 2,\n    resource_wait_reason", "    resource_queue_position: 2, resource_queue_position_exact: true,\n    resource_wait_reason")
vt_extra = r'''

test('video task canonical task_status wins and inexact rank is not rendered as queue position', () => {
  const task = normalizeVideoTask({
    id: 'vq3', status: 'SUCCEEDED', task_status: 'WAITING_RESOURCE',
    progress: 88, progress_percent: 14,
    video_name: 'waiting.mp4', mode: 'fixed_count', fixed_count: 12,
    resource_queue_position: 6, resource_queue_position_exact: false,
    resource_wait_reason: 'VIDEO_WORKER_BUSY',
  });
  assert.equal(task.status, 'WAITING_RESOURCE');
  assert.equal(task.progress_percent, 14);
  assert.equal(isActiveVideoTask(task), true);
  assert.match(task.runtimeText, /VIDEO_WORKER_BUSY/);
  assert.doesNotMatch(task.runtimeText, /资源队列第 6 位/);
});
'''
if "video task canonical task_status wins" not in vt:
    vt += vt_extra
video_test.write_text(vt, encoding="utf-8")

deploy_test = ROOT / "tests/frontend/deployment-task-view.test.mjs"
dt = deploy_test.read_text(encoding="utf-8")
dt = dt.replace("    resource_queue_position: 3,\n    resource_wait_reason", "    resource_queue_position: 3,\n    resource_queue_position_exact: true,\n    resource_wait_reason")
dt_extra = r'''

test('deployment canonical task_status wins and non-exact queue rank is not shown as exact', () => {
  const view = deploymentTaskView({
    status: 'SUCCEEDED', task_status: 'WAITING_RESOURCE',
    progress: 90, progress_percent: 21, phase: 'resource_waiting',
    resource_queue_position: 5, resource_queue_position_exact: false,
    resource_wait_reason: 'DEPLOYMENT_RUNTIME_BUSY',
  });
  assert.equal(view.status, 'WAITING_RESOURCE');
  assert.equal(view.percent, 21);
  assert.equal(view.active, true);
  assert.match(view.runtimeText, /DEPLOYMENT_RUNTIME_BUSY/);
  assert.doesNotMatch(view.runtimeText, /资源队列第 5 位/);
});
'''
if "deployment canonical task_status wins" not in dt:
    dt += dt_extra
deploy_test.write_text(dt, encoding="utf-8")

resource_test = ROOT / "tests/frontend/resource-discovery-runtime-truth.test.mjs"
rt = resource_test.read_text(encoding="utf-8")
rt = rt.replace("assert.match(source, /taskStatus === 'CANCELLED'/);", "assert.match(source, /taskStatus === 'CANCELLED'/);")
old_success = "assert.match(source, /if \\(SUCCESS_TASK_STATUSES\\.has\\(status\\(task\\.status\\)\\)\\) \\{\\s*await refreshCache\\(true\\)/);"
new_success = "assert.match(source, /if \\(SUCCESS_TASK_STATUSES\\.has\\(canonicalTaskStatus\\(task\\)\\)\\) \\{\\s*await refreshCache\\(true\\)/);"
if old_success in rt:
    rt = rt.replace(old_success, new_success)
else:
    # exact source line replacement is simpler if regex string representation differs
    rt = rt.replace("assert.match(source, /if \\(SUCCESS_TASK_STATUSES\\.has\\(status\\(task\\.status\\)\\)\\) \\{\\s*await refreshCache\\(true\\)/);", new_success)
rt_extra = r'''

test('resource discovery durable task polling uses shared canonical runtime truth', () => {
  assert.match(source, /from '.\/task-runtime-truth\.js'/);
  assert.match(source, /canonicalTaskStatus\(task\)/);
  assert.match(source, /canonicalTaskPhase\(task\)/);
  assert.match(source, /isCanonicalTaskActive\(task\)/);
  assert.doesNotMatch(source, /ACTIVE_TASK_STATUSES/);
  assert.doesNotMatch(source, /ACTIVE_TASK_STATUSES\.has\(status\(task\.status\)\)/);
});
'''
if "resource discovery durable task polling uses shared canonical runtime truth" not in rt:
    rt += rt_extra
resource_test.write_text(rt, encoding="utf-8")

# Handoff
(ROOT / "docs/CODEX_HANDOFF_2026-09-16_TASK_RUNTIME_TRUTH_V2.md").write_text(r'''# Task Runtime Truth v2 handoff — 2026-09-16

## Scope

Extends the shared durable-task frontend contract from training/annotation/material batches to:

- storage scan/import progress
- server material import
- resource discovery
- video processing tasks
- deployment test tasks

Cleaning remains intentionally outside this batch because its page consumes a legacy compatibility
business object. It must be migrated together with its backend compatibility projection rather than
by changing frontend status casing in isolation.

## Queue truth rule

A numeric `resource_queue_position` is allowed to render as “队列第 N 位” only when
`resource_queue_position_exact === true` from the backend. A candidate rank, priority order, or a
numeric position without exactness proof is not presented as a real Worker/hardware queue position.

`exactTaskQueuePosition()` in `static/modules/task-runtime-truth.js` is the single frontend helper.

## Status / phase / progress rule

For durable task payloads:

- `task_status` wins over stale compatibility `status`
- `phase` wins over `task_stage` / `stage`
- `progress_percent` wins over legacy `progress`
- item counts and domain metrics remain useful detail but are not converted into a fabricated durable percentage

Resource discovery keeps its frozen-root/scope/permission UX and cache refresh behavior. Server
material import keeps backend scan/extract/index counters. This batch changes task truth semantics,
not domain-specific diagnostics.

## Validation boundary

Focused Node tests cover canonical precedence and exact queue presentation. The permanent Task
Runtime Truth workflow runs the expanded frontend suite on Ubuntu and Windows. Existing Frontend
Runtime / Navigation Real Chrome gates must remain green. Production-host concurrency and real
worker queue contention remain separate acceptance work.
''', encoding="utf-8")

print("Task Runtime Truth v2 patch applied")
