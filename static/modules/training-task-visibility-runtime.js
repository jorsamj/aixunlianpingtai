import {formatTrainingDuration, trainingBatchActionEligible, trainingProgressView, trainingStageView} from './training-task-runtime.js?v=422561';
import {canonicalTaskProgressPercent, canonicalTaskStatus, trainingDisplayStatus} from './task-runtime-truth.js?v=422424';

const TRAINING_PAGE = '训练任务';
const ACTIVE_STATUSES = new Set([
  'queued',
  'waiting',
  'pending',
  'starting',
  'running',
  'pausing',
  'paused',
  'resuming',
  'stopping',
  'cancel_requested',
]);
const TERMINAL_STATUSES = new Set([
  'done',
  'finished',
  'completed',
  'succeeded',
  'success',
  'failed',
  'stopped',
  'cancelled',
  'canceled',
  'blocked_by_environment',
  'blocked_by_hardware',
]);
const FAILURE_STAGE_LABELS = Object.freeze({
  training_process: '训练进程失败',
  post_training: '训练结束后处理失败',
  final_validation: '最终模型验证失败',
});

function statusBucket(job) {
  const status = trainingDisplayStatus(job);
  if (['running', 'starting', 'pausing', 'paused', 'resuming', 'stopping', 'cancel_requested'].includes(status)) return 'running';
  if (['queued', 'waiting', 'pending'].includes(status)) return 'queued';
  if (['done', 'finished', 'completed', 'succeeded', 'success'].includes(status)) return 'completed';
  if (['failed', 'blocked_by_environment', 'blocked_by_hardware'].includes(status)) return 'failed';
  if (['stopped', 'cancelled', 'canceled'].includes(status)) return 'stopped';
  return TERMINAL_STATUSES.has(status) ? 'stopped' : 'queued';
}

export function trainingTaskStatusCounts(jobs = []) {
  const result = {all: 0, running: 0, queued: 0, completed: 0, failed: 0, stopped: 0};
  for (const job of Array.isArray(jobs) ? jobs : []) {
    result.all += 1;
    result[statusBucket(job)] += 1;
  }
  return result;
}

export function filterTrainingTaskJobs(jobs = [], {tab = 'all', query = '', algorithm = 'all', priority = 'all', status = 'all'} = {}) {
  const needle = String(query || '').trim().toLowerCase();
  return (Array.isArray(jobs) ? jobs : []).filter(job => {
    const bucket = statusBucket(job);
    if (tab === 'active' && !ACTIVE_STATUSES.has(trainingDisplayStatus(job))) return false;
    if (tab === 'history' && !TERMINAL_STATUSES.has(trainingDisplayStatus(job))) return false;
    if (!['all', 'active', 'history'].includes(tab) && bucket !== tab) return false;
    if (status !== 'all' && bucket !== status) return false;
    const algorithmName = String(job?.asset_algorithm_name || job?.algorithm_name || '未命名算法');
    const taskName = String(job?.task_name || job?.run_name || job?.auto_version_name || '训练任务');
    if (needle && !`${algorithmName} ${taskName}`.toLowerCase().includes(needle)) return false;
    if (algorithm !== 'all' && algorithmName !== algorithm) return false;
    const value = String(Number(job?.queue_priority ?? job?.priority ?? 50));
    return priority === 'all' || value === String(priority);
  }).map((job, index) => ({job, index})).sort((left, right) => {
    const a = left.job;
    const b = right.job;
    const aStatus = trainingDisplayStatus(a);
    const bStatus = trainingDisplayStatus(b);
    const rank = value => ['running', 'starting', 'pausing', 'resuming', 'stopping', 'cancel_requested'].includes(value) ? 0 : value === 'paused' ? 1 : value === 'waiting' ? 2 : ['queued', 'pending'].includes(value) ? 3 : 4;
    const rankDelta = rank(aStatus) - rank(bStatus);
    if (rankDelta) return rankDelta;
    if (['queued', 'waiting', 'pending'].includes(aStatus) && ['queued', 'waiting', 'pending'].includes(bStatus)) {
      const sameResource = String(a?.resource_key || '') === String(b?.resource_key || '');
      const aPosition = Number(a?.resource_queue_position);
      const bPosition = Number(b?.resource_queue_position);
      if (sameResource && a?.resource_queue_position_exact === true && b?.resource_queue_position_exact === true && aPosition > 0 && bPosition > 0 && aPosition !== bPosition) return aPosition - bPosition;
      const priorityDelta = priorityValue(a) - priorityValue(b);
      if (priorityDelta) return priorityDelta;
      const aRank = Number(a?.queue_rank);
      const bRank = Number(b?.queue_rank);
      if (Number.isFinite(aRank) && Number.isFinite(bRank) && (aRank || bRank) && aRank !== bRank) return bRank - aRank;
      const aLegacy = Number(a?.priority_tiebreaker);
      const bLegacy = Number(b?.priority_tiebreaker);
      if (Number.isFinite(aLegacy) && Number.isFinite(bLegacy) && (aLegacy || bLegacy) && aLegacy !== bLegacy) return aLegacy - bLegacy;
      const timeDelta = Date.parse(a?.queued_at || a?.created_at || '') - Date.parse(b?.queued_at || b?.created_at || '');
      return Number.isFinite(timeDelta) && timeDelta ? timeDelta : left.index - right.index;
    }
    return left.index - right.index;
  }).map(entry => entry.job);
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char]));
}

function statusText(status) {
  return ({queued: '排队中', waiting: '等待资源', pending: '等待提交', starting: '启动中', running: '训练中', pausing: '暂停中', paused: '已暂停', resuming: '恢复中', stopping: '停止中', cancel_requested: '取消中', done: '已完成', finished: '已完成', completed: '已完成', succeeded: '已完成', success: '已完成', failed: '失败', stopped: '已停止', cancelled: '已取消', canceled: '已取消', blocked_by_environment: '环境阻断', blocked_by_hardware: '硬件阻断'})[status] || status || '未知';
}

function priorityValue(job) {
  const raw = Number(job?.queue_priority ?? 50);
  if (job?.priority_scheme === 'lower_number_first') return Math.max(1, Math.min(999, Number.isFinite(raw) ? raw : 50));
  const legacy = {100: 1, 80: 20, 50: 50};
  return legacy[raw] ?? Math.max(1, Math.min(999, 101 - (Number.isFinite(raw) ? raw : 50)));
}

function queueRuntimeMeta(job) {
  const status = trainingDisplayStatus(job);
  if (!['queued', 'waiting'].includes(status)) return '';
  const pool = String(job?.resource_pool_label || '').trim();
  const position = Number(job?.resource_queue_position || 0);
  const reason = String(job?.resource_wait_reason || '').trim();
  const parts = pool ? [pool] : [];
  if (status === 'waiting') {
    if (reason) parts.push(reason);
    return parts.join(' · ');
  }
  if (position > 0 && job?.resource_queue_position_exact === true) parts.push(`队列第 ${position} 位`);
  else {
    parts.push('排队中');
    if (position > 0) {
      const ahead = Math.max(0, position - 1);
      parts.push(ahead > 0 ? `前方约 ${ahead} 个候选任务（动态）` : '当前处于资源候选首位（动态）');
    }
  }
  return parts.join(' · ');
}

function completionRuntimeMeta(job, progress) {
  if (!['done', 'finished', 'completed', 'succeeded', 'success'].includes(trainingDisplayStatus(job))) return '';
  const completed = Number(progress?.epoch || 0);
  const requested = Number(progress?.totalEpochs || 0);
  if (!(completed > 0 && requested > 0 && completed < requested)) return '';
  const outcome = String(job?.training_outcome || '').trim();
  const reason = String(job?.completion_reason || '').trim();
  if (outcome === 'target_reached' || reason === 'quality_target_reached') return '达到质量目标，提前完成';
  if (outcome === 'needs_optimization' || reason === 'quality_gate_below_continue_threshold') return '提前结束（需继续优化）';
  if (reason === 'early_stopping') {
    const patience = Number(job?.early_stopping_patience || 0);
    return String(job?.early_stopping_reason || '') === 'patience' && patience > 0
      ? `连续 ${Math.round(patience)} Epoch 无提升，Early Stopping`
      : 'Early Stopping，提前完成';
  }
  return '提前完成';
}

function terminalRuntimeMeta(job, stage) {
  const status = trainingDisplayStatus(job);
  if (['done', 'finished', 'completed', 'succeeded', 'success'].includes(status) || !TERMINAL_STATUSES.has(status)) return '';
  const taskStatus = canonicalTaskStatus(job);
  const failureStage = String(job?.failure_stage || '').trim().toLowerCase();
  let label = '';
  if (taskStatus === 'BLOCKED_BY_ENVIRONMENT') label = '训练环境不可用';
  else if (taskStatus === 'BLOCKED_BY_HARDWARE') label = '训练硬件不可用';
  else if (['cancelled', 'canceled'].includes(status)) label = '已取消';
  else if (status === 'stopped') label = '已停止';
  else if (status === 'failed') label = FAILURE_STAGE_LABELS[failureStage] || stage.label || '训练失败';
  const reason = String(job?.current_item || job?.message || job?.error || '').trim();
  return reason && reason !== label ? `${label} · ${reason}` : label;
}

function taskActions(job) {
  const id = esc(job?.id || job?.task_id || '');
  const status = trainingDisplayStatus(job);
  const detail = `<button onclick="openTrainingRecoveryDetail('${id}')">详情</button>`;
  const log = `<button onclick="showTrainLog423('${id}')">日志</button>`;
  if (['starting', 'pausing', 'resuming', 'stopping', 'cancel_requested'].includes(status)) return `${detail}${log}<span class="train428-action-lock">状态切换中</span>`;
  if (['queued', 'waiting', 'pending'].includes(status)) return `${detail}${log}<button onclick="promoteTrain428('${id}')">插队</button><details class="entity-more"><summary>•••</summary><div><button onclick="stopTrain428('${id}')">停止</button><button class="danger" onclick="deleteTrain428('${id}')">删除</button></div></details>`;
  if (status === 'running') return `${detail}${log}<button onclick="pauseTrain428('${id}')">暂停</button><details class="entity-more"><summary>•••</summary><div><button onclick="stopTrain428('${id}')">停止</button><button class="danger" onclick="deleteTrain428('${id}')">删除</button></div></details>`;
  if (status === 'paused') return `${detail}${log}<button class="primary-link" onclick="resumeTrain428('${id}')">继续</button><details class="entity-more"><summary>•••</summary><div><button onclick="stopTrain428('${id}')">停止</button><button class="danger" onclick="deleteTrain428('${id}')">删除</button></div></details>`;
  return `${detail}${log}${job?.auto_version_id ? `<button onclick="trainingReport425('${id}')">训练报告</button>` : ''}<details class="entity-more"><summary>•••</summary><div><button class="danger" onclick="deleteTrain428('${id}')">删除</button></div></details>`;
}

export function trainingTaskPresentationRow(job, {batchMode = false, selected = false} = {}) {
  const id = String(job?.id || job?.task_id || '');
  const status = trainingDisplayStatus(job);
  const progress = trainingProgressView(job);
  const percent = canonicalTaskProgressPercent(job);
  const stage = trainingStageView(job);
  const algorithmName = job?.asset_algorithm_name || job?.algorithm_name || '未命名算法';
  const taskName = job?.task_name || job?.run_name || job?.auto_version_name || '训练任务';
  const elapsed = progress.elapsedSeconds == null ? '' : Math.max(0, Number(progress.elapsedSeconds) || 0);
  const eta = progress.etaSeconds == null ? '' : Math.max(0, Number(progress.etaSeconds) || 0);
  const active = ['starting', 'running', 'pausing', 'resuming', 'stopping', 'cancel_requested'].includes(status);
  const checkbox = batchMode ? `<label class="train428-select"><input type="checkbox" data-training-batch-select="${esc(id)}" ${selected ? 'checked' : ''} aria-label="选择训练任务 ${esc(taskName)}"><span></span></label>` : '';
  const started = String(job?.started_at || job?.created_at || '').replace('T', ' ').replace('Z', '').slice(0, 19) || '-';
  const progressMeta = [];
  const completion = completionRuntimeMeta(job, progress);
  if (completion) progressMeta.push(completion);
  if (Number(progress.epoch || 0) > 0) {
    progressMeta.push(`Epoch ${progress.epoch}/${progress.totalEpochs ?? '-'}`);
    if (progress.currentBatch != null && progress.totalBatches) progressMeta.push(`Batch ${progress.currentBatch}/${progress.totalBatches}`);
  }
  else if (!TERMINAL_STATUSES.has(status)) progressMeta.push(stage.label);
  const terminal = terminalRuntimeMeta(job, stage);
  if (terminal && !progressMeta.includes(terminal)) progressMeta.push(terminal);
  const stageDetails = [stage.detail, queueRuntimeMeta(job), job?.task_worker_id ? `执行节点 ${job.task_worker_id}` : '', job?.recovery?.available === true ? 'Checkpoint 已保留' : ''].filter(Boolean).join(' · ');
  return `<tr data-job-id="${esc(id)}" data-clock-active="${active ? '1' : '0'}" class="${batchMode ? 'is-batch-mode' : ''}${selected ? ' is-selected' : ''}"><td><div class="train428-algorithm-cell">${checkbox}<div class="train428-taskname"><b title="${esc(algorithmName)}">${esc(algorithmName)}</b></div></div></td><td><div class="train428-taskname"><b title="${esc(taskName)}">${esc(taskName)}</b>${job?.auto_version_name && taskName !== job.auto_version_name ? `<em>版本 ${esc(job.auto_version_name)}</em>` : ''}</div></td><td><span class="entity-status ${statusBucket(job)}">${esc(statusText(status))}</span></td><td><span class="train428-priority-number">${priorityValue(job)}</span></td><td><div class="train428-progress-main"><div class="progress424"><i data-progress="${percent.toFixed(2)}" style="transform:scaleX(${(Math.max(0, Math.min(100, percent)) / 100).toFixed(4)})"></i></div><b>${percent.toFixed(0)}%</b></div><span class="train428-progress-txt">${esc(progressMeta.join(' · ') || stage.label)}</span></td><td><span class="train428-clock" data-training-clock="elapsed" data-seconds="${elapsed}">${esc(formatTrainingDuration(progress.elapsedSeconds))}</span></td><td><span class="train428-clock" data-training-clock="eta" data-seconds="${eta}">${esc(formatTrainingDuration(progress.etaSeconds))}</span></td><td><div class="train428-stage"><b>${esc(stage.label)}</b>${stageDetails ? `<small title="${esc(stageDetails)}">${esc(stageDetails)}</small>` : ''}</div></td><td><span class="train428-started">${esc(started)}</span></td><td><div class="entity-row-actions train428-actions-cell">${taskActions(job)}</div></td></tr>`;
}

export function tickTrainingClockRows(root, stepSeconds = 1) {
  const step = Math.max(1, Math.floor(Number(stepSeconds) || 1));
  const rows = root?.querySelectorAll?.('tr[data-clock-active="1"]') || [];
  let changed = 0;
  for (const row of rows) {
    const elapsed = row.querySelector?.('[data-training-clock="elapsed"]');
    const eta = row.querySelector?.('[data-training-clock="eta"]');

    if (elapsed && elapsed.dataset?.seconds !== '') {
      const current = Number(elapsed.dataset.seconds);
      if (Number.isFinite(current)) {
        const next = Math.max(0, current + step);
        elapsed.dataset.seconds = String(next);
        elapsed.textContent = formatTrainingDuration(next);
        changed += 1;
      }
    }

    if (eta && eta.dataset?.seconds !== '') {
      const current = Number(eta.dataset.seconds);
      if (Number.isFinite(current)) {
        const next = Math.max(0, current - step);
        eta.dataset.seconds = String(next);
        eta.textContent = formatTrainingDuration(next);
        changed += 1;
      }
    }
  }
  return changed;
}

export function installTrainingTaskVisibilityRuntime({
  getState,
  trainingTaskRuntime,
  pollRegistry,
  notify,
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingTaskVisibilityRuntimeInstalled) {
    return window.TrainingTaskVisibilityRuntime;
  }

  const doc = typeof document !== 'undefined' ? document : null;
  const state = () => getState?.() || {};
  const runtime = trainingTaskRuntime || window.TrainingTaskRuntime;
  if (!runtime || typeof runtime.refresh !== 'function' || typeof runtime.setViewAdapter !== 'function') return null;

  const previous = {
    renderTraining423: window.renderTraining423,
    renderTraining424: window.renderTraining424,
    renderTraining425: window.renderTraining425,
    setTrainTab428: window.setTrainTab428,
  };

  let destroyed = false;
  let batchMode = false;
  let batchBusy = false;
  const selectedIds = new Set();
  const renderedRows = new Map();
  const taskView = {
    tab: 'all',
    query: '',
    status: 'all',
    algorithm: 'all',
    priority: 'all',
    page: 1,
    pageSize: 10,
  };

  function trainingShellHtml() {
    return `<section class="train428-page train428-page-v2 entity-page training-task-page" data-training-task-shell="canonical">
      <header class="entity-page-header"><div><span class="entity-breadcrumb">算法生产 / 训练任务</span><h1>训练任务</h1><p>统一查看、管理和调度训练任务</p></div><button type="button" class="btn primary entity-create" data-training-create>＋ 新建训练任务</button></header>
      <nav class="training-status-tabs" role="tablist" aria-label="训练任务状态">
        ${[['all','全部'],['running','进行中'],['queued','排队中'],['completed','已完成'],['failed','失败'],['stopped','已停止']].map(([key, label]) => `<button type="button" data-training-tab="${key}" class="${key === taskView.tab ? 'on' : ''}">${label}<span data-training-count="${key}">0</span></button>`).join('')}
      </nav>
      <section class="entity-query-surface"><div class="training-query-grid">
        <label class="entity-search"><span>⌕</span><input type="search" data-training-query placeholder="搜索任务名称 / 训练任务" value="${esc(taskView.query)}"></label>
        <label><span>状态</span><select data-training-status><option value="all">全部状态</option><option value="running">进行中</option><option value="queued">排队中</option><option value="completed">已完成</option><option value="failed">失败</option><option value="stopped">已停止</option></select></label>
        <label><span>所属算法</span><select data-training-algorithm><option value="all">全部算法</option></select></label>
        <label><span>优先级</span><select data-training-priority><option value="all">全部优先级</option><option value="1">1</option><option value="20">20</option><option value="30">30</option><option value="40">40</option><option value="50">50</option><option value="70">70</option></select></label>
        <button type="button" class="btn primary" data-training-query-apply>查询</button><button type="button" class="btn" data-training-query-reset>重置</button><button type="button" class="btn" data-training-batch-toggle>批量操作</button>
      </div><div class="train428-batchbar" data-training-batchbar hidden>
          <span data-training-batch-count>已选 0 项</span>
          <button type="button" class="btn mini" data-training-batch-select-action="all-visible">全选当前页</button>
          <button type="button" class="btn mini" data-training-batch-select-action="deletable-visible">仅选可删除</button>
          <button type="button" class="btn mini" data-training-batch-select-action="clear">清空选择</button>
          <button type="button" class="btn mini" data-training-batch-action="pause">暂停</button>
          <button type="button" class="btn mini" data-training-batch-action="resume">继续</button>
          <button type="button" class="btn mini danger" data-training-batch-action="stop">停止</button>
          <button type="button" class="btn mini danger" data-training-batch-action="delete">删除记录</button>
        </div></section>
      <section class="entity-table-surface training-table-surface"><div class="table-wrap"><table class="table train428-table entity-table">
        <thead><tr><th>所属算法</th><th>训练任务</th><th>状态</th><th>优先级</th><th>进度</th><th>已用时间</th><th>剩余时间</th><th>当前阶段</th><th>开始时间</th><th>操作</th></tr></thead>
        <tbody></tbody>
      </table></div><footer class="entity-pagination"><span data-training-total>共 0 条</span><div>
        <select data-training-page-size><option value="10">10 条/页</option><option value="20">20 条/页</option><option value="50">50 条/页</option></select>
        <button type="button" data-training-page-prev aria-label="上一页">‹</button><span data-training-page-label>1 / 1</span><button type="button" data-training-page-next aria-label="下一页">›</button>
      </div></footer></section>
    </section>`;
  }

  function ensureShell() {
    if (!doc || String(state().page || '') !== TRAINING_PAGE) return null;
    let root = doc.querySelector?.('.train428-page[data-training-task-shell="canonical"]');
    if (root) return root;
    const view = doc.getElementById?.('view');
    if (!view) return null;
    view.innerHTML = trainingShellHtml();
    const created = view.querySelector?.('.train428-page[data-training-task-shell="canonical"]') || null;
    bindBatchControls(created);
    return created;
  }

  function rowHtml(job) {
    const id = String(job?.id || job?.task_id || '');
    return trainingTaskPresentationRow(job, {batchMode, selected: selectedIds.has(id)});
  }

  function eligibleSelectedCount(action) {
    const jobs = Array.isArray(state().jobs) ? state().jobs : [];
    return jobs.filter(job => selectedIds.has(String(job?.id || job?.task_id || ''))
      && trainingBatchActionEligible(job, action)).length;
  }

  function syncBatchToolbar(root) {
    if (!root) return;
    root.classList.toggle('is-batch-mode', batchMode);
    const bar = root.querySelector?.('[data-training-batchbar]');
    const toggle = root.querySelector?.('[data-training-batch-toggle]');
    const count = root.querySelector?.('[data-training-batch-count]');
    if (bar) bar.hidden = !batchMode;
    if (toggle) {
      toggle.textContent = batchMode ? '退出批量' : '批量操作';
      toggle.classList.toggle('primary', batchMode);
      toggle.disabled = batchBusy;
    }
    if (count) count.textContent = `已选 ${selectedIds.size} 项`;
    for (const action of ['pause', 'resume', 'stop', 'delete']) {
      const button = root.querySelector?.(`[data-training-batch-action="${action}"]`);
      if (button) button.disabled = batchBusy || eligibleSelectedCount(action) <= 0;
    }
  }

  async function runBatchAction(action, root) {
    if (batchBusy || !selectedIds.size || typeof runtime.batchAction !== 'function') return;
    batchBusy = true;
    syncBatchToolbar(root);
    try {
      const result = await runtime.batchAction(action, [...selectedIds]);
      if (!result?.cancelled && (result?.succeeded || 0) > 0) {
        selectedIds.clear();
        batchMode = false;
      }
    } finally {
      batchBusy = false;
      renderOwned();
    }
  }

  function bindBatchControls(root) {
    if (!root || root.dataset.trainingBatchBound === '1') return;
    root.dataset.trainingBatchBound = '1';
    root.addEventListener('click', event => {
      const tab = event.target.closest?.('[data-training-tab]');
      if (tab) {
        taskView.tab = String(tab.dataset.trainingTab || 'all');
        taskView.page = 1;
        batchMode = false;
        selectedIds.clear();
        renderOwned();
        return;
      }
      if (event.target.closest?.('[data-training-create]')) {
        const algorithmId = String(state().algorithms?.[0]?.id || '');
        if (algorithmId) void window.openTrainingCreateCanonical429?.(algorithmId);
        return;
      }
      if (event.target.closest?.('[data-training-query-apply]')) {
        taskView.query = String(root.querySelector?.('[data-training-query]')?.value || '').trim();
        taskView.status = String(root.querySelector?.('[data-training-status]')?.value || 'all');
        taskView.algorithm = String(root.querySelector?.('[data-training-algorithm]')?.value || 'all');
        taskView.priority = String(root.querySelector?.('[data-training-priority]')?.value || 'all');
        taskView.page = 1;
        renderOwned();
        return;
      }
      if (event.target.closest?.('[data-training-query-reset]')) {
        Object.assign(taskView, {query: '', status: 'all', algorithm: 'all', priority: 'all', page: 1});
        renderOwned();
        return;
      }
      if (event.target.closest?.('[data-training-page-prev]')) {
        taskView.page = Math.max(1, taskView.page - 1);
        renderOwned();
        return;
      }
      if (event.target.closest?.('[data-training-page-next]')) {
        taskView.page += 1;
        renderOwned();
        return;
      }
      const toggle = event.target.closest?.('[data-training-batch-toggle]');
      if (toggle) {
        batchMode = !batchMode;
        if (!batchMode) selectedIds.clear();
        renderOwned();
        return;
      }
      const selectionButton = event.target.closest?.('[data-training-batch-select-action]');
      if (selectionButton) {
        const action = String(selectionButton.dataset.trainingBatchSelectAction || '');
        const filtered = filterTrainingTaskJobs(Array.isArray(state().jobs) ? state().jobs : [], taskView);
        const start = (Math.max(1, taskView.page) - 1) * taskView.pageSize;
        const visible = filtered.slice(start, start + taskView.pageSize);
        if (action === 'clear') selectedIds.clear();
        else {
          if (action === 'deletable-visible') selectedIds.clear();
          for (const job of visible) {
            const id = String(job?.id || job?.task_id || '');
            if (!id) continue;
            if (action === 'all-visible' || (action === 'deletable-visible' && trainingBatchActionEligible(job, 'delete'))) {
              selectedIds.add(id);
            }
          }
        }
        renderOwned();
        return;
      }
      const actionButton = event.target.closest?.('[data-training-batch-action]');
      if (actionButton) {
        void runBatchAction(String(actionButton.dataset.trainingBatchAction || ''), root);
      }
    });
    root.addEventListener('change', event => {
      const pageSize = event.target.closest?.('[data-training-page-size]');
      if (pageSize) {
        taskView.pageSize = Math.max(1, Number(pageSize.value) || 10);
        taskView.page = 1;
        renderOwned();
        return;
      }
      const checkbox = event.target.closest?.('[data-training-batch-select]');
      if (!checkbox) return;
      const id = String(checkbox.dataset.trainingBatchSelect || '');
      if (!id) return;
      if (checkbox.checked) selectedIds.add(id);
      else selectedIds.delete(id);
      renderOwned();
    });
  }

  function createTrainingRow(html) {
    if (!doc?.createElement) return null;
    const holder = doc.createElement('tbody');
    holder.innerHTML = String(html || '').trim();
    return holder.firstElementChild || null;
  }

  function patchProgressCell(currentCell, nextCell) {
    const currentTrack = currentCell?.querySelector?.('.progress424');
    const nextTrack = nextCell?.querySelector?.('.progress424');
    const currentBar = currentTrack?.querySelector?.('i');
    const nextBar = nextTrack?.querySelector?.('i');
    const currentText = currentCell?.querySelector?.('.train428-progress-txt');
    const nextText = nextCell?.querySelector?.('.train428-progress-txt');
    const currentPercent = currentCell?.querySelector?.('.train428-progress-main > b');
    const nextPercent = nextCell?.querySelector?.('.train428-progress-main > b');
    if (!currentTrack || !nextTrack || !currentBar || !nextBar || !currentText || !nextText) {
      currentCell.innerHTML = nextCell.innerHTML;
      return;
    }

    currentBar.dataset.progress = nextBar.dataset.progress || '';
    currentBar.style.transform = nextBar.style.transform;
    if (currentPercent && nextPercent) currentPercent.textContent = nextPercent.textContent;
    currentText.textContent = nextText.textContent;

    const currentMetrics = currentCell.querySelector?.('.train428-metrics');
    const nextMetrics = nextCell.querySelector?.('.train428-metrics');
    if (currentMetrics && nextMetrics) {
      currentMetrics.textContent = nextMetrics.textContent;
    } else if (currentMetrics && !nextMetrics) {
      currentMetrics.remove();
    } else if (!currentMetrics && nextMetrics) {
      currentCell.appendChild(nextMetrics.cloneNode(true));
    }
  }

  function patchTrainingRow(currentRow, nextRow) {
    if (!currentRow || !nextRow || currentRow.cells?.length !== nextRow.cells?.length) return nextRow;
    currentRow.dataset.clockActive = nextRow.dataset.clockActive || '0';
    for (let index = 0; index < nextRow.cells.length; index += 1) {
      const currentCell = currentRow.cells[index];
      const nextCell = nextRow.cells[index];
      if (index === 4) {
        patchProgressCell(currentCell, nextCell);
      } else if (currentCell.innerHTML !== nextCell.innerHTML) {
        currentCell.innerHTML = nextCell.innerHTML;
      }
    }
    return currentRow;
  }

  function patchRows(body, visible) {
    const canPatch = Boolean(
      doc?.createElement
      && typeof body?.querySelectorAll === 'function'
      && typeof body?.insertBefore === 'function'
      && body?.children,
    );
    if (!canPatch) {
      body.innerHTML = visible.map(rowHtml).join('')
        || '<tr><td colspan="10" class="empty-row">暂无记录</td></tr>';
      renderedRows.clear();
      for (const job of visible) renderedRows.set(String(job?.id || ''), rowHtml(job));
      return;
    }

    if (!visible.length) {
      if (!body.querySelector?.('.empty-row')) {
        body.innerHTML = '<tr><td colspan="10" class="empty-row">暂无记录</td></tr>';
      }
      renderedRows.clear();
      return;
    }

    body.querySelector?.('.empty-row')?.remove?.();
    const existingRows = new Map(
      [...body.querySelectorAll('tr[data-job-id]')]
        .map(row => [String(row.dataset?.jobId || ''), row]),
    );
    const wanted = new Set();

    visible.forEach((job, index) => {
      const id = String(job?.id || '');
      const html = rowHtml(job);
      wanted.add(id);
      let row = existingRows.get(id) || null;
      if (!row) {
        row = createTrainingRow(html);
        if (!row) return;
      } else if (renderedRows.get(id) !== html) {
        const nextRow = createTrainingRow(html);
        if (nextRow) row = patchTrainingRow(row, nextRow);
      }

      const reference = body.children[index] || null;
      if (row && reference !== row) body.insertBefore(row, reference);
      renderedRows.set(id, html);
    });

    for (const [id, row] of existingRows) {
      if (!wanted.has(id)) row.remove?.();
    }
    for (const id of [...renderedRows.keys()]) {
      if (!wanted.has(id)) renderedRows.delete(id);
    }
  }

  function renderOwned() {
    if (destroyed || !doc || String(state().page || '') !== TRAINING_PAGE) return false;
    const root = ensureShell();
    bindBatchControls(root);
    const body = root?.querySelector?.('.train428-table tbody');
    if (!root || !body) return false;

    const jobs = Array.isArray(state().jobs) ? state().jobs : [];
    const createButton = root.querySelector?.('[data-training-create]');
    if (createButton) {
      createButton.disabled = !state().algorithms?.length;
      createButton.title = createButton.disabled ? '请先创建算法' : '';
    }
    const summary = trainingTaskStatusCounts(jobs);
    for (const [key, count] of Object.entries(summary)) {
      const target = root.querySelector?.(`[data-training-count="${key}"]`);
      if (target) target.textContent = String(count);
    }
    for (const button of root.querySelectorAll?.('[data-training-tab]') || []) {
      button.classList?.toggle?.('on', String(button.dataset?.trainingTab || '') === taskView.tab);
    }
    const algorithmSelect = root.querySelector?.('[data-training-algorithm]');
    if (algorithmSelect) {
      const names = [...new Set(jobs.map(job => String(job?.asset_algorithm_name || job?.algorithm_name || '未命名算法')))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
      const options = `<option value="all">全部算法</option>${names.map(name => `<option value="${esc(name)}">${esc(name)}</option>`).join('')}`;
      if (algorithmSelect.innerHTML !== options) algorithmSelect.innerHTML = options;
      algorithmSelect.value = names.includes(taskView.algorithm) ? taskView.algorithm : 'all';
      if (algorithmSelect.value === 'all') taskView.algorithm = 'all';
    }
    const statusSelect = root.querySelector?.('[data-training-status]');
    const prioritySelect = root.querySelector?.('[data-training-priority]');
    const queryInput = root.querySelector?.('[data-training-query]');
    if (statusSelect) statusSelect.value = taskView.status;
    if (prioritySelect) prioritySelect.value = taskView.priority;
    if (queryInput && queryInput.value !== taskView.query) queryInput.value = taskView.query;

    const filtered = filterTrainingTaskJobs(jobs, taskView);
    const pages = Math.max(1, Math.ceil(filtered.length / taskView.pageSize));
    taskView.page = Math.min(Math.max(1, taskView.page), pages);
    const start = (taskView.page - 1) * taskView.pageSize;
    const visible = filtered.slice(start, start + taskView.pageSize);
    const visibleIds = new Set(visible.map(job => String(job?.id || job?.task_id || '')));
    for (const id of [...selectedIds]) {
      if (!visibleIds.has(id)) selectedIds.delete(id);
    }
    patchRows(body, visible);
    const total = root.querySelector?.('[data-training-total]');
    const pageLabel = root.querySelector?.('[data-training-page-label]');
    const prev = root.querySelector?.('[data-training-page-prev]');
    const next = root.querySelector?.('[data-training-page-next]');
    const pageSize = root.querySelector?.('[data-training-page-size]');
    if (total) total.textContent = `共 ${filtered.length} 条`;
    if (pageLabel) pageLabel.textContent = `${taskView.page} / ${pages}`;
    if (prev) prev.disabled = taskView.page <= 1;
    if (next) next.disabled = taskView.page >= pages;
    if (pageSize) pageSize.value = String(taskView.pageSize);
    syncBatchToolbar(root);
    pollRegistry?.syncTrainingClockTimer?.();
    return true;
  }

  function tickClock(stepSeconds = 1) {
    if (destroyed || !doc || String(state().page || '') !== TRAINING_PAGE) return 0;
    const root = doc.querySelector?.('.train428-page');
    return tickTrainingClockRows(root, stepSeconds);
  }

  const viewAdapter = {
    render: renderOwned,
    afterRefresh(result, options = {}) {
      if (destroyed || result?.stale) return;
      if (String(options.source || '') !== 'poll') {
        pollRegistry?.replaceTrainingJobTimer?.();
      }
    },
  };
  const detachViewAdapter = runtime.setViewAdapter(viewAdapter);

  const onPageRefreshClick = event => {
    const button = event?.target?.closest?.('#refreshBtn');
    if (!button || destroyed || String(state().page || '') !== TRAINING_PAGE) return;
    event.preventDefault?.();
    event.stopImmediatePropagation?.();
    if (button.disabled || runtime.state?.().inflight) return;
    button.disabled = true;
    const previousText = button.textContent;
    button.textContent = '刷新中';
    void runtime.refresh({render: true, source: 'manual'}).then(
      result => { if (!result?.stale) notify?.('训练任务已刷新'); },
      error => notify?.(error?.message || error),
    ).finally(() => {
      if (button?.isConnected !== false) {
        button.disabled = false;
        button.textContent = previousText || '刷新';
      }
      pollRegistry?.replaceTrainingJobTimer?.();
    });
  };
  doc?.addEventListener?.('click', onPageRefreshClick, true);

  async function refreshOwned(options = {}) {
    return runtime.refresh(options);
  }

  const renderTraining = () => {
    const rendered = renderOwned();
    pollRegistry?.replaceTrainingJobTimer?.();
    return rendered;
  };
  renderTraining.__trainingTaskVisibilityRuntime = true;
  window.renderTraining423 = renderTraining;
  window.renderTraining424 = renderTraining;
  window.renderTraining425 = renderTraining;

  window.setTrainTab428 = tab => {
    taskView.tab = ['all', 'running', 'queued', 'completed', 'failed', 'stopped', 'active', 'history'].includes(tab) ? tab : 'all';
    taskView.page = 1;
    batchMode = false;
    selectedIds.clear();
    renderOwned();
    pollRegistry?.replaceTrainingJobTimer?.();
  };

  const visibilityRuntime = {
    build: 'training-task-visibility-422526',
    activeStatuses: Object.freeze([...ACTIVE_STATUSES]),
    terminalStatuses: Object.freeze([...TERMINAL_STATUSES]),
    render: renderOwned,
    tickClock,
    refresh: refreshOwned,
    state() {
      return {
        batchMode,
        batchBusy,
        selectedIds: [...selectedIds],
        filters: {...taskView},
        page: String(state().page || ''),
      };
    },
    destroy() {
      destroyed = true;
      renderedRows.clear();
      selectedIds.clear();
      batchMode = false;
      batchBusy = false;
      detachViewAdapter?.();
      doc?.removeEventListener?.('click', onPageRefreshClick, true);
      for (const [name, fn] of Object.entries(previous)) {
        if (fn === undefined) delete window[name];
        else window[name] = fn;
      }
      if (window.TrainingTaskVisibilityRuntime === visibilityRuntime) {
        window.TrainingTaskVisibilityRuntime = null;
      }
      window.__trainingTaskVisibilityRuntimeInstalled = false;
    },
  };

  window.TrainingTaskVisibilityRuntime = visibilityRuntime;
  window.__trainingTaskVisibilityRuntimeInstalled = true;
  window.NavigationStability?.rebindOwners?.();
  if (window.PlatformCore?.runtime) {
    window.PlatformCore.runtime.trainingTaskVisibilityRuntime = visibilityRuntime;
  }
  pollRegistry?.syncTrainingClockTimer?.();

  if (String(state().page || '') === TRAINING_PAGE) {
    renderOwned();
    void refreshOwned({render: true, force: true, source: 'install'}).catch(error => {
      notify?.(error?.message || error);
    });
  }

  return visibilityRuntime;
}

if (typeof window !== 'undefined') {
  installTrainingTaskVisibilityRuntime({
    getState: () => state,
    trainingTaskRuntime: window.PlatformCore?.runtime?.trainingTaskRuntime || window.TrainingTaskRuntime,
    pollRegistry: window.PollRegistryRuntime,
    notify: message => window.toast?.(message),
  });
}
