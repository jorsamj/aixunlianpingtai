const RECOVERY_ACTION_REVALIDATE = 'revalidate_checkpoint';
const SUCCESS_STATUSES = new Set(['done', 'finished', 'completed', 'succeeded', 'success']);
const FAILED_STATUSES = new Set(['failed', 'blocked_by_environment', 'blocked_by_hardware']);
const ACTIVE_STATUSES = new Set(['queued', 'waiting', 'pending', 'starting', 'running', 'pausing', 'paused', 'resuming', 'stopping', 'cancel_requested']);

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function bytesText(value) {
  const bytes = Math.max(0, Number(value || 0));
  if (!bytes) return '-';
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(2)} GB`;
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(2)} MB`;
  if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${bytes} B`;
}

function failureStageLabel(stage) {
  return ({
    training_process: '训练进程',
    post_training: '训练结束后处理',
    final_validation: '最终模型验证',
  })[String(stage || '').toLowerCase()] || String(stage || '未知阶段');
}

export function canRecoverTrainingTask(recovery = {}) {
  return recovery?.available === true
    && recovery?.recoverable === true
    && recovery?.checkpoint_available === true
    && recovery?.recovery_action === RECOVERY_ACTION_REVALIDATE;
}

export function trainingRecoveryTimeline(job = {}, recovery = {}) {
  const status = String(job?.status || '').toLowerCase();
  const stage = String(job?.task_stage || job?.stage || '').toLowerCase();
  const failedStage = String(recovery?.failure_stage || job?.failure_stage || '').toLowerCase();
  const epoch = numberOrNull(job?.training_progress?.epoch) ?? numberOrNull(job?.current_epoch) ?? 0;
  const completedEpochs = Math.max(numberOrNull(recovery?.completed_epochs) || 0, epoch || 0);
  const trainingCompleted = recovery?.training_loop_completed === true || SUCCESS_STATUSES.has(status);
  const checkpointReady = recovery?.checkpoint_available === true || SUCCESS_STATUSES.has(status);
  const recovering = ['queued', 'waiting', 'running', 'pending'].includes(status)
    && Boolean(recovery?.retry_of || job?.retry_of);
  const succeeded = SUCCESS_STATUSES.has(status);

  const steps = [
    {key: 'queue', label: '排队与资源分配', state: 'done'},
    {key: 'prepare', label: '准备训练数据', state: trainingCompleted || completedEpochs > 0 ? 'done' : (stage.includes('prepar') || stage === 'materializing' ? 'active' : 'pending')},
    {key: 'training', label: completedEpochs > 0 ? `模型训练${recovery?.requested_epochs ? ` · ${completedEpochs}/${recovery.requested_epochs} Epoch` : ''}` : '模型训练', state: trainingCompleted ? 'done' : (failedStage === 'training_process' ? 'failed' : (stage === 'training' ? 'active' : 'pending'))},
    {key: 'checkpoint', label: '保存 Checkpoint', state: checkpointReady ? 'done' : (trainingCompleted ? 'failed' : 'pending')},
    {key: 'validation', label: recovering ? '重新验证 Checkpoint' : '最终模型验证', state: succeeded ? 'done' : (recovering && (stage === 'recovering_checkpoint' || stage === 'final_validation') ? 'active' : (failedStage === 'final_validation' || failedStage === 'post_training' ? 'failed' : 'pending'))},
    {key: 'archive', label: '归档训练结果', state: succeeded ? 'done' : (stage === 'finalizing_commit' ? 'active' : 'pending')},
  ];
  return steps;
}

export function trainingRecoveryDetailModel(job = {}, recovery = {}) {
  const progress = job?.training_progress || {};
  const completedEpochs = numberOrNull(recovery?.completed_epochs) ?? numberOrNull(progress.epoch) ?? numberOrNull(job.current_epoch) ?? 0;
  const requestedEpochs = numberOrNull(recovery?.requested_epochs) ?? numberOrNull(progress.total_epochs) ?? numberOrNull(job.total_epochs) ?? numberOrNull(job.epochs);
  const status = String(job?.status || recovery?.task_status || '').trim().toLowerCase();
  const taskStatus = String(job?.task_status || recovery?.task_status || '').trim().toUpperCase();
  const recoverable = canRecoverTrainingTask(recovery);
  const partial = taskStatus === 'PARTIAL_SUCCESS';
  const success = SUCCESS_STATUSES.has(status) || taskStatus === 'SUCCEEDED' || partial;
  const failed = FAILED_STATUSES.has(status) || ['FAILED', 'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE'].includes(taskStatus);
  const errors = (failed || recoverable) ? [...new Set([
    recovery?.failure_reason || '',
    job?.error || '',
    job?.training_report?.test_result?.error || '',
    job?.version_archive_error || '',
    failed ? (job?.message || '') : '',
    failed ? (job?.current_item || '') : '',
  ].map(value => String(value || '').trim()).filter(Boolean))] : [];
  const failureReason = errors[0] || '';
  const warnings = [...new Set([
    partial ? (job?.warning_message || job?.error || job?.training_report?.test_result?.error || '') : '',
    job?.version_archive_error || '',
  ].map(value => String(value || '').trim()).filter(Boolean))];
  const resolved = job?.resolved_resources && typeof job.resolved_resources === 'object' ? job.resolved_resources : {};
  const actual = job?.actual_train_params && typeof job.actual_train_params === 'object' ? job.actual_train_params : {};
  return {
    taskId: String(job?.id || job?.task_id || recovery?.task_id || ''),
    status,
    taskStatus,
    statusKind: recoverable ? 'recoverable' : failed ? 'failed' : partial ? 'partial' : success ? 'success' : 'active',
    statusMessage: String(job?.message || job?.current_item || '').trim(),
    failureStage: recovery?.failure_stage || job?.failure_stage || '',
    failureReason,
    errors,
    warnings,
    completedEpochs,
    requestedEpochs,
    progressPercent: Math.max(0, Math.min(100, numberOrNull(job?.progress_percent) ?? 0)),
    elapsedSeconds: numberOrNull(progress.elapsed_seconds) ?? numberOrNull(job?.elapsed_seconds),
    etaSeconds: numberOrNull(progress.eta_seconds) ?? numberOrNull(job?.eta_seconds),
    trainingLoopCompleted: recovery?.training_loop_completed === true || success,
    checkpointAvailable: recovery?.checkpoint_available === true || success,
    checkpoint: recovery?.checkpoint || null,
    recoverable,
    action: recovery?.recovery_action || null,
    processReturncode: recovery?.process_returncode ?? job?.process_returncode ?? null,
    processSignal: recovery?.process_signal ?? job?.process_signal ?? null,
    attempt: numberOrNull(recovery?.attempt) ?? numberOrNull(job?.task_attempt) ?? 0,
    retryOf: recovery?.retry_of || job?.retry_of || null,
    algorithmName: String(job?.asset_algorithm_name || job?.algorithm_name || job?.asset_algorithm_id || '-'),
    taskName: String(job?.task_name || job?.run_name || job?.auto_version_name || job?.id || '-'),
    stage: String(job?.phase || job?.task_stage || job?.stage || '').trim(),
    workerId: String(job?.task_worker_id || job?.worker_id || '').trim(),
    requestedDevice: String(job?.requested_device || '').trim(),
    assignedDevice: String(job?.assigned_device || '').trim(),
    actualDevice: String(job?.actual_device || '').trim(),
    resourceProfile: String(actual.resource_profile || resolved.resource_profile || job?.resource_profile || '').trim(),
    precision: String(actual.effective_precision || actual.precision || resolved.precision || job?.precision || '').trim(),
    batch: actual.batch ?? resolved.resolved_batch ?? job?.batch ?? null,
    workers: actual.workers ?? resolved.resolved_workers ?? job?.workers ?? null,
    cache: actual.cache ?? resolved.resolved_cache ?? job?.cache ?? null,
    snapshotId: String(job?.snapshot_id || '').trim(),
    datasetRevisionId: String(job?.dataset_revision_id || '').trim(),
    trainingOutcome: String(job?.training_outcome || '').trim(),
    completionReason: String(job?.completion_reason || '').trim(),
    diagnosticCode: String(job?.runtime_metrics?.diagnostic?.code || '').trim(),
    resourceReasons: Array.isArray(resolved?.reasons) ? resolved.reasons.map(String) : [],
    resourceAdjustments: Array.isArray(resolved?.adjustments) ? resolved.adjustments.map(String) : [],
    createdAt: job?.created_at || null,
    startedAt: job?.started_at || null,
    finishedAt: job?.finished_at || null,
    timeline: trainingRecoveryTimeline(job, recovery),
  };
}

function timelineHtml(steps) {
  const icon = state => ({done: '✓', failed: '×', active: '●', pending: '○'})[state] || '○';
  return `<div class="training-recovery-timeline">${steps.map(step => `
    <div class="training-recovery-step ${esc(step.state)}">
      <span class="training-recovery-step-icon">${icon(step.state)}</span>
      <span>${esc(step.label)}</span>
    </div>`).join('')}</div>`;
}

function detailHtml(job, recovery, log = '') {
  const model = trainingRecoveryDetailModel(job, recovery);
  const failed = model.statusKind === 'failed';
  const statusTitle = model.recoverable
    ? '训练已完成 · 模型验证失败'
    : model.statusKind === 'failed'
      ? '训练失败'
      : model.statusKind === 'partial'
        ? '训练主体已完成 · 后处理有警告'
        : model.statusKind === 'success'
          ? '训练已完成'
          : '训练任务详情';
  const checkpoint = model.checkpoint;
  const epochText = model.requestedEpochs ? `${model.completedEpochs} / ${model.requestedEpochs}` : (model.completedEpochs || '-');
  const actionHtml = model.recoverable ? `
    <button class="btn primary" data-training-recovery-action="${RECOVERY_ACTION_REVALIDATE}" data-task-id="${esc(model.taskId)}">重新验证 Checkpoint</button>` : '';
  const reasonHtml = model.errors.length ? `<div class="training-recovery-reason"><b>失败证据</b>${model.errors.map(value => `<p>${esc(value)}</p>`).join('')}</div>` : '';
  const warningHtml = model.warnings.length ? `<div class="training-recovery-warning"><b>警告 / 非致命异常</b>${model.warnings.map(value => `<p>${esc(value)}</p>`).join('')}</div>` : '';
  const statusHtml = !failed && !model.recoverable && model.statusMessage ? `<div class="training-recovery-message"><b>当前信息</b><p>${esc(model.statusMessage)}</p></div>` : '';
  const logHtml = `<details class="training-recovery-log" data-training-tech-log><summary>工程师技术日志 <span>运行中自动刷新</span></summary><pre>${esc(log || '暂无技术日志')}</pre></details>`;
  return `
    <div class="training-recovery-overlay" data-training-recovery-overlay>
      <div class="training-recovery-dialog" role="dialog" aria-modal="true" aria-label="训练任务详情">
        <div class="training-recovery-head"><div><h3>${esc(statusTitle)}</h3><span>${esc(model.taskId)}</span></div><button class="btn mini" data-training-recovery-close>关闭</button></div>
        <div class="training-recovery-body">
          <section class="training-recovery-summary ${model.recoverable ? 'recoverable' : ''}">
            <div><small>${failed || model.recoverable ? '失败阶段' : '当前阶段'}</small><b>${esc(model.failureStage ? failureStageLabel(model.failureStage) : (model.stage || '-'))}</b></div>
            <div><small>训练轮次</small><b>${esc(epochText)}</b></div>
            <div><small>整体进度</small><b>${model.progressPercent.toFixed(0)}%</b></div>
            <div><small>训练主体</small><b>${model.trainingLoopCompleted ? '已完成' : '进行中 / 未完成'}</b></div>
            <div><small>实际设备</small><b>${esc(model.actualDevice || model.assignedDevice || model.requestedDevice || '-')}</b></div>
            <div><small>执行节点</small><b>${esc(model.workerId || '-')}</b></div>
            <div><small>Batch / Workers</small><b>${esc(`${model.batch ?? '-'} / ${model.workers ?? '-'}`)}</b></div>
            <div><small>Cache / 精度</small><b>${esc(`${model.cache ?? '-'} / ${model.precision || '-'}`)}</b></div>
            <div><small>执行尝试</small><b>${esc(model.attempt || '-')}</b></div>
          </section>
          ${statusHtml}
          ${reasonHtml}
          ${warningHtml}
          <section class="training-recovery-evidence">
            <h4>运行证据</h4>
            <div class="training-recovery-kv"><span>所属算法</span><b>${esc(model.algorithmName)}</b></div>
            <div class="training-recovery-kv"><span>任务名称</span><b>${esc(model.taskName)}</b></div>
            <div class="training-recovery-kv"><span>数据版本</span><b>${esc(model.datasetRevisionId ? model.datasetRevisionId.slice(0, 16) : '-')}</b></div>
            <div class="training-recovery-kv"><span>训练快照</span><b>${esc(model.snapshotId ? model.snapshotId.slice(0, 16) : '-')}</b></div>
            <div class="training-recovery-kv"><span>资源档位</span><b>${esc(model.resourceProfile || '-')}</b></div>
            <div class="training-recovery-kv"><span>训练结果</span><b>${esc(model.trainingOutcome || model.taskStatus || model.status || '-')}</b></div>
            <div class="training-recovery-kv"><span>完成原因</span><b>${esc(model.completionReason || '-')}</b></div>
            <div class="training-recovery-kv"><span>运行诊断</span><b>${esc(model.diagnosticCode || '-')}</b></div>
            <div class="training-recovery-kv"><span>Checkpoint 文件</span><b>${esc(checkpoint?.filename || '-')}</b></div>
            <div class="training-recovery-kv"><span>Checkpoint 大小</span><b>${esc(checkpoint ? bytesText(checkpoint.size_bytes) : '-')}</b></div>
            <div class="training-recovery-kv"><span>Process Signal</span><b>${esc(model.processSignal || '-')}</b></div>
            <div class="training-recovery-kv"><span>Return Code</span><b>${esc(model.processReturncode ?? '-')}</b></div>
            <div class="training-recovery-kv"><span>创建时间</span><b>${esc(model.createdAt || '-')}</b></div>
            <div class="training-recovery-kv"><span>开始时间</span><b>${esc(model.startedAt || '-')}</b></div>
            <div class="training-recovery-kv"><span>完成时间</span><b>${esc(model.finishedAt || '-')}</b></div>
            ${model.resourceAdjustments.length ? `<div class="training-recovery-kv"><span>资源自动调整</span><b>${esc(model.resourceAdjustments.join('；'))}</b></div>` : ''}
            ${model.resourceReasons.length ? `<div class="training-recovery-kv"><span>资源决策依据</span><b>${esc(model.resourceReasons.join('；'))}</b></div>` : ''}
          </section>
          <section><h4>执行阶段</h4>${timelineHtml(model.timeline)}</section>
          ${logHtml}
          ${model.recoverable ? '<div class="training-recovery-callout">当前训练主体和可信 Checkpoint 已保留，可直接重新执行独立模型验证，无需重新训练全部 Epoch。</div>' : ''}
        </div>
        <div class="training-recovery-actions">
          <button class="btn" data-training-detail-refresh="${esc(model.taskId)}">立即刷新</button>
          ${job?.auto_version_id ? `<button class="btn" data-training-report-task="${esc(model.taskId)}">查看训练报告</button>` : ''}
          ${actionHtml}
        </div>
      </div>
    </div>`;
}

function ensureStyles(doc) {
  if (!doc || doc.getElementById('training-recovery-runtime-style')) return;
  const style = doc.createElement('style');
  style.id = 'training-recovery-runtime-style';
  style.textContent = `
    .training-recovery-overlay{position:fixed;inset:0;z-index:10080;background:rgba(15,23,42,.48);display:flex;align-items:center;justify-content:center;padding:24px}
    .training-recovery-dialog{width:min(960px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow:auto;background:#fff;border-radius:16px;box-shadow:0 24px 70px rgba(15,23,42,.28)}
    .training-recovery-head{display:flex;align-items:flex-start;justify-content:space-between;padding:20px 22px;border-bottom:1px solid #e5e7eb}.training-recovery-head h3{margin:0 0 5px;font-size:20px}.training-recovery-head span{font-size:12px;color:#64748b}
    .training-recovery-body{padding:18px 22px;display:grid;gap:18px}.training-recovery-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.training-recovery-summary>div{padding:12px;border:1px solid #e5e7eb;border-radius:10px;background:#f8fafc}.training-recovery-summary small{display:block;color:#64748b;margin-bottom:5px}.training-recovery-summary.recoverable{border-left:3px solid #f59e0b;padding-left:12px}
    .training-recovery-message,.training-recovery-warning,.training-recovery-reason{padding:14px;border-radius:10px}.training-recovery-message{background:#eff6ff;border:1px solid #bfdbfe}.training-recovery-warning{background:#fffbeb;border:1px solid #fde68a}.training-recovery-reason{background:#fef2f2;border:1px solid #fecaca}.training-recovery-message p,.training-recovery-warning p,.training-recovery-reason p{margin:7px 0 0;white-space:pre-wrap;word-break:break-word}.training-recovery-warning p+ p{margin-top:5px}
    .training-recovery-evidence h4,.training-recovery-body section h4{margin:0 0 10px}.training-recovery-kv{display:flex;justify-content:space-between;gap:16px;padding:8px 0;border-bottom:1px dashed #e5e7eb}.training-recovery-kv span{color:#64748b}
    .training-recovery-timeline{display:grid;gap:7px}.training-recovery-step{display:flex;gap:10px;align-items:center;padding:8px 10px;border-radius:8px;background:#f8fafc}.training-recovery-step.done .training-recovery-step-icon{color:#16a34a}.training-recovery-step.failed{background:#fef2f2}.training-recovery-step.failed .training-recovery-step-icon{color:#dc2626}.training-recovery-step.active{background:#eff6ff}.training-recovery-step.active .training-recovery-step-icon{color:#2563eb}.training-recovery-step.pending{color:#94a3b8}
    .training-recovery-log{border:1px solid #e5e7eb;border-radius:12px;background:#0f172a;color:#e2e8f0;overflow:hidden}.training-recovery-log summary{cursor:pointer;padding:12px 14px;background:#111827;font-weight:700}.training-recovery-log summary span{float:right;color:#94a3b8;font-size:12px}.training-recovery-log pre{margin:0;max-height:360px;overflow:auto;padding:14px;white-space:pre-wrap;word-break:break-word;font-size:12px;line-height:1.55}.training-recovery-callout{padding:12px 14px;border-radius:10px;background:#fffbeb;border:1px solid #fde68a;color:#92400e}.training-recovery-actions{position:sticky;bottom:0;background:#fff;display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap;padding:16px 22px;border-top:1px solid #e5e7eb}
    @media(max-width:680px){.training-recovery-summary{grid-template-columns:repeat(2,minmax(0,1fr))}.training-recovery-overlay{padding:10px}}
  `;
  doc.head?.appendChild(style);
}

export function installTrainingRecoveryRuntime({getState, projectId, notify, fetchImpl} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingRecoveryRuntimeInstalled) return window.TrainingRecoveryRuntime;
  const doc = typeof document !== 'undefined' ? document : null;
  const state = () => getState?.() || {};
  const nativeFetch = fetchImpl
    || window.fetch?.__pageRequestScopeOriginal
    || (typeof window.fetch === 'function' ? window.fetch.bind(window) : null);
  if (typeof nativeFetch !== 'function') return null;
  ensureStyles(doc);

  const previous = {
    openTrainingRecoveryDetail: window.openTrainingRecoveryDetail,
    revalidateTrainingCheckpoint: window.revalidateTrainingCheckpoint,
    showTrainLog423: window.showTrainLog423,
    refreshTrainRunCenter429: window.refreshTrainRunCenter429,
  };
  const locks = new Set();
  let openTaskId = '';
  let openFocus = 'overview';
  let openSnapshot = null;
  let detailRefreshPromise = null;
  const DETAIL_POLL_KEY = 'training-task-detail';

  async function json(response, fallback) {
    const raw = await response.text();
    let body = {};
    try { body = raw ? JSON.parse(raw) : {}; } catch (_) { body = {detail: raw}; }
    if (!response.ok) throw new Error(String(body?.detail?.message || body?.detail || body?.message || fallback));
    return body;
  }

  async function hydrateJobs(jobs = []) {
    const pid = projectId?.();
    if (!pid) return jobs;
    const ids = jobs.filter(job => String(job?.status || '') === 'failed').map(job => String(job.id)).filter(Boolean);
    if (!ids.length) return jobs;
    try {
      const response = await nativeFetch(`/api/v62/projects/${encodeURIComponent(pid)}/training-tasks/recovery-query`, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body: JSON.stringify({task_ids: ids}),
      });
      const body = await json(response, '读取训练恢复状态失败');
      const items = body?.items || {};
      return jobs.map(job => items[job.id] ? {...job, recovery: items[job.id]} : job);
    } catch (_) {
      return jobs;
    }
  }

  function stopDetailTimer() {
    window.PollRegistryRuntime?.clear?.(DETAIL_POLL_KEY);
  }

  function closeDetail() {
    stopDetailTimer();
    doc?.querySelector?.('[data-training-recovery-overlay]')?.remove?.();
    openTaskId = '';
    openFocus = 'overview';
    openSnapshot = null;
    detailRefreshPromise = null;
  }

  async function readRecovery(taskId) {
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目不可用');
    const response = await nativeFetch(`/api/v62/projects/${encodeURIComponent(pid)}/training-tasks/${encodeURIComponent(taskId)}/recovery`, {
      headers: {'Accept': 'application/json'},
    });
    const body = await json(response, '读取训练任务详情失败');
    return body?.recovery || {};
  }

  async function readJob(taskId) {
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目不可用');
    const response = await nativeFetch(`/api/projects/${encodeURIComponent(pid)}/jobs/${encodeURIComponent(taskId)}`, {headers: {'Accept': 'application/json'}});
    return json(response, '读取训练任务详情失败');
  }

  async function readLog(taskId) {
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目不可用');
    const response = await nativeFetch(`/api/projects/${encodeURIComponent(pid)}/jobs/${encodeURIComponent(taskId)}/log`, {headers: {'Accept': 'text/plain'}});
    const raw = await response.text();
    if (!response.ok) {
      let body = {};
      try { body = raw ? JSON.parse(raw) : {}; } catch (_) { body = {detail: raw}; }
      throw new Error(String(body?.detail || body?.message || '读取训练日志失败'));
    }
    return raw;
  }

  function renderOpenDetail(job, recovery = {}, log = '', focus = openFocus) {
    if (!openTaskId || String(job?.id || job?.task_id || '') !== String(openTaskId)) return false;
    const old = doc?.querySelector?.('[data-training-recovery-overlay]');
    const oldDialog = old?.querySelector?.('.training-recovery-dialog');
    const scrollTop = Number(oldDialog?.scrollTop || 0);
    const logOpen = old?.querySelector?.('[data-training-tech-log]')?.open === true || focus === 'log';
    const host = doc?.createElement?.('div');
    if (!host) return false;
    host.innerHTML = detailHtml(job, recovery, log);
    const overlay = host.firstElementChild;
    if (!overlay) return false;
    old?.remove?.();
    doc.body?.appendChild(overlay);
    const dialog = overlay.querySelector?.('.training-recovery-dialog');
    if (dialog) dialog.scrollTop = scrollTop;
    const logs = overlay.querySelector?.('[data-training-tech-log]');
    if (logs) logs.open = logOpen;
    if (focus === 'log' && logs) queueMicrotask(() => logs.scrollIntoView?.({block: 'nearest'}));
    return true;
  }

  function updateStateJob(job) {
    const jobs = Array.isArray(state().jobs) ? state().jobs : [];
    const id = String(job?.id || job?.task_id || '');
    const index = jobs.findIndex(item => String(item?.id || item?.task_id || '') === id);
    if (index < 0) return;
    const copy = [...jobs];
    copy[index] = {...jobs[index], ...job};
    state().jobs = copy;
  }

  function scheduleDetailRefresh(job) {
    stopDetailTimer();
    const status = String(job?.status || '').trim().toLowerCase();
    const taskStatus = String(job?.task_status || '').trim().toUpperCase();
    const active = ACTIVE_STATUSES.has(status) || ['ACCEPTED','QUEUED','WAITING_RESOURCE','PREPARING','RUNNING','PAUSING','PAUSED','RESUMING','STOPPING','CANCEL_REQUESTED','RETRYING'].includes(taskStatus);
    if (!active || !openTaskId) return;
    window.PollRegistryRuntime?.startTimeout?.(
      DETAIL_POLL_KEY,
      '训练任务',
      () => { void refreshOpenDetail({includeRecovery: false}); },
      1500,
    );
  }

  async function refreshOpenDetail({includeRecovery = false} = {}) {
    const taskId = openTaskId;
    if (!taskId) return false;
    if (detailRefreshPromise) return detailRefreshPromise;
    detailRefreshPromise = (async () => {
      const cached = (state().jobs || []).find(item => String(item?.id || item?.task_id || '') === String(taskId)) || openSnapshot?.job || {};
      const recoveryPromise = includeRecovery
        ? readRecovery(taskId)
        : Promise.resolve(openSnapshot?.recovery || cached?.recovery || {});
      const [job, recovery, log] = await Promise.all([
        readJob(taskId).catch(() => cached),
        recoveryPromise.catch(() => openSnapshot?.recovery || cached?.recovery || {}),
        readLog(taskId).catch(() => openSnapshot?.log || ''),
      ]);
      if (String(openTaskId) !== String(taskId)) return false;
      openSnapshot = {job, recovery, log};
      updateStateJob(job);
      renderOpenDetail(job, recovery, log);
      scheduleDetailRefresh(job);
      return true;
    })().finally(() => { detailRefreshPromise = null; });
    return detailRefreshPromise;
  }

  async function openDetail(taskId, options = {}) {
    const job = (state().jobs || []).find(item => String(item?.id || item?.task_id || '') === String(taskId));
    if (!job) {
      notify?.('训练任务不存在或列表尚未刷新');
      return false;
    }
    openTaskId = String(taskId);
    openFocus = options?.focus === 'log' ? 'log' : 'overview';
    openSnapshot = {job, recovery: job?.recovery || {}, log: ''};
    renderOpenDetail(job, openSnapshot.recovery, '', openFocus);
    try {
      await refreshOpenDetail({includeRecovery: true});
      return true;
    } catch (error) {
      notify?.(`训练详情刷新失败，已显示当前缓存：${error?.message || error}`);
      scheduleDetailRefresh(job);
      return true;
    }
  }

  function acceptLiveTask(job) {
    const taskId = String(job?.id || job?.task_id || '');
    if (!openTaskId || taskId !== String(openTaskId)) return false;
    const current = openSnapshot?.job || {};
    const merged = {...current, ...job};
    openSnapshot = {...(openSnapshot || {}), job: merged};
    renderOpenDetail(merged, openSnapshot.recovery || {}, openSnapshot.log || '');
    scheduleDetailRefresh(merged);
    return true;
  }

  async function recover(taskId, action = RECOVERY_ACTION_REVALIDATE) {
    const key = `${taskId}:${action}`;
    if (locks.has(key)) return false;
    locks.add(key);
    try {
      const recovery = await readRecovery(taskId);
      if (!canRecoverTrainingTask(recovery) || recovery.recovery_action !== action) {
        throw new Error('该训练任务当前没有可执行的 Checkpoint 恢复动作');
      }
      if (typeof window.confirm === 'function' && !window.confirm('确认使用已保留的 Checkpoint 重新执行最终模型验证？不会重新训练全部 Epoch。')) return false;
      const pid = projectId?.();
      const response = await nativeFetch(`/api/v62/projects/${encodeURIComponent(pid)}/training-tasks/${encodeURIComponent(taskId)}/recovery`, {
        method: 'POST', headers: {'Content-Type': 'application/json', 'Accept': 'application/json'},
        body: JSON.stringify({action}),
      });
      await json(response, '提交恢复任务失败');
      closeDetail();
      let refreshError = null;
      try { await window.TrainingTaskRuntime?.refresh?.({render: true, force: true, source: 'mutation'}); } catch (error) { refreshError = error; }
      notify?.(refreshError ? `已进入重新验证队列，但列表刷新失败：${refreshError.message || refreshError}` : '已进入 Checkpoint 重新验证队列');
      window.PollRegistryRuntime?.replaceTrainingJobTimer?.();
      return true;
    } catch (error) {
      notify?.(error?.message || error);
      return false;
    } finally {
      locks.delete(key);
    }
  }

  const onClick = event => {
    const close = event.target?.closest?.('[data-training-recovery-close]');
    if (close || event.target?.matches?.('[data-training-recovery-overlay]')) {
      closeDetail();
      return;
    }
    const action = event.target?.closest?.('[data-training-recovery-action]');
    if (action) {
      event.preventDefault();
      void recover(action.dataset.taskId, action.dataset.trainingRecoveryAction);
      return;
    }
    const refresh = event.target?.closest?.('[data-training-detail-refresh]');
    if (refresh) {
      event.preventDefault();
      void refreshOpenDetail({includeRecovery: true}).catch(error => notify?.(error?.message || error));
      return;
    }
    const log = event.target?.closest?.('[data-training-log-task]');
    if (log) {
      event.preventDefault();
      void openDetail(log.dataset.trainingLogTask, {focus: 'log'});
      return;
    }
    const report = event.target?.closest?.('[data-training-report-task]');
    if (report) {
      closeDetail();
      window.trainingReport425?.(report.dataset.trainingReportTask);
    }
  };
  doc?.addEventListener?.('click', onClick);

  window.openTrainingRecoveryDetail = taskId => openDetail(taskId, {focus: 'overview'});
  window.revalidateTrainingCheckpoint = recover;
  window.showTrainLog423 = taskId => openDetail(taskId, {focus: 'log'});
  window.refreshTrainRunCenter429 = taskId => {
    if (String(openTaskId) !== String(taskId)) return openDetail(taskId, {focus: 'log'});
    return refreshOpenDetail({includeRecovery: true});
  };

  const runtime = {
    build: 'training-recovery-runtime-422506',
    hydrateJobs,
    openDetail,
    refreshOpenDetail,
    acceptLiveTask,
    recover,
    closeDetail,
    destroy() {
      closeDetail();
      doc?.removeEventListener?.('click', onClick);
      for (const [name, value] of Object.entries(previous)) {
        if (value === undefined) delete window[name];
        else window[name] = value;
      }
      if (window.TrainingRecoveryRuntime === runtime) window.TrainingRecoveryRuntime = null;
      window.__trainingRecoveryRuntimeInstalled = false;
    },
  };
  window.TrainingRecoveryRuntime = runtime;
  window.__trainingRecoveryRuntimeInstalled = true;
  return runtime;
}
