const RECOVERY_ACTION_REVALIDATE = 'revalidate_checkpoint';
const SUCCESS_STATUSES = new Set(['done', 'finished', 'completed']);
const FAILED_STATUSES = new Set(['failed']);

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
  return {
    taskId: String(job?.id || recovery?.task_id || ''),
    status: String(job?.status || recovery?.task_status || ''),
    failureStage: recovery?.failure_stage || job?.failure_stage || '',
    failureReason: recovery?.failure_reason || job?.current_item || job?.message || job?.error || '',
    completedEpochs,
    requestedEpochs,
    trainingLoopCompleted: recovery?.training_loop_completed === true,
    checkpointAvailable: recovery?.checkpoint_available === true,
    checkpoint: recovery?.checkpoint || null,
    recoverable: canRecoverTrainingTask(recovery),
    action: recovery?.recovery_action || null,
    processReturncode: recovery?.process_returncode ?? job?.process_returncode ?? null,
    processSignal: recovery?.process_signal ?? job?.process_signal ?? null,
    attempt: numberOrNull(recovery?.attempt) ?? numberOrNull(job?.task_attempt) ?? 0,
    retryOf: recovery?.retry_of || job?.retry_of || null,
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

function detailHtml(job, recovery) {
  const model = trainingRecoveryDetailModel(job, recovery);
  const failed = FAILED_STATUSES.has(model.status);
  const statusTitle = model.recoverable
    ? '训练已完成 · 模型验证失败'
    : (failed ? '训练失败' : (SUCCESS_STATUSES.has(model.status) ? '训练已完成' : '训练任务详情'));
  const checkpoint = model.checkpoint;
  const epochText = model.requestedEpochs ? `${model.completedEpochs} / ${model.requestedEpochs}` : (model.completedEpochs || '-');
  const actionHtml = model.recoverable ? `
    <button class="btn primary" data-training-recovery-action="${RECOVERY_ACTION_REVALIDATE}" data-task-id="${esc(model.taskId)}">重新验证 Checkpoint</button>` : '';
  const reasonHtml = model.failureReason ? `<div class="training-recovery-reason"><b>失败原因</b><p>${esc(model.failureReason)}</p></div>` : '';
  return `
    <div class="training-recovery-overlay" data-training-recovery-overlay>
      <div class="training-recovery-dialog" role="dialog" aria-modal="true" aria-label="训练任务详情">
        <div class="training-recovery-head"><div><h3>${esc(statusTitle)}</h3><span>${esc(model.taskId)}</span></div><button class="btn mini" data-training-recovery-close>关闭</button></div>
        <div class="training-recovery-body">
          <section class="training-recovery-summary ${model.recoverable ? 'recoverable' : ''}">
            <div><small>失败阶段</small><b>${esc(model.failureStage ? failureStageLabel(model.failureStage) : '-')}</b></div>
            <div><small>训练轮次</small><b>${esc(epochText)}</b></div>
            <div><small>训练主体</small><b>${model.trainingLoopCompleted ? '已完成' : '未确认完成'}</b></div>
            <div><small>Checkpoint</small><b>${model.checkpointAvailable ? '可用' : '不可用'}</b></div>
            <div><small>是否可恢复</small><b>${model.recoverable ? '是' : '否'}</b></div>
            <div><small>执行尝试</small><b>${esc(model.attempt || '-')}</b></div>
          </section>
          ${reasonHtml}
          <section class="training-recovery-evidence">
            <h4>运行证据</h4>
            <div class="training-recovery-kv"><span>Checkpoint 文件</span><b>${esc(checkpoint?.filename || '-')}</b></div>
            <div class="training-recovery-kv"><span>Checkpoint 大小</span><b>${esc(checkpoint ? bytesText(checkpoint.size_bytes) : '-')}</b></div>
            <div class="training-recovery-kv"><span>Process Signal</span><b>${esc(model.processSignal || '-')}</b></div>
            <div class="training-recovery-kv"><span>Return Code</span><b>${esc(model.processReturncode ?? '-')}</b></div>
          </section>
          <section><h4>执行阶段</h4>${timelineHtml(model.timeline)}</section>
          ${model.recoverable ? '<div class="training-recovery-callout">当前训练主体和可信 Checkpoint 已保留，可直接重新执行独立模型验证，无需重新训练全部 Epoch。</div>' : ''}
        </div>
        <div class="training-recovery-actions">
          <button class="btn" data-training-log-task="${esc(model.taskId)}">查看训练日志</button>
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
    .training-recovery-dialog{width:min(760px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow:auto;background:#fff;border-radius:14px;box-shadow:0 24px 70px rgba(15,23,42,.28)}
    .training-recovery-head{display:flex;align-items:flex-start;justify-content:space-between;padding:20px 22px;border-bottom:1px solid #e5e7eb}.training-recovery-head h3{margin:0 0 5px;font-size:20px}.training-recovery-head span{font-size:12px;color:#64748b}
    .training-recovery-body{padding:18px 22px;display:grid;gap:18px}.training-recovery-summary{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.training-recovery-summary>div{padding:12px;border:1px solid #e5e7eb;border-radius:10px;background:#f8fafc}.training-recovery-summary small{display:block;color:#64748b;margin-bottom:5px}.training-recovery-summary.recoverable{border-left:3px solid #f59e0b;padding-left:12px}
    .training-recovery-reason{padding:14px;border-radius:10px;background:#fff7ed;border:1px solid #fed7aa}.training-recovery-reason p{margin:7px 0 0;white-space:pre-wrap;word-break:break-word}
    .training-recovery-evidence h4,.training-recovery-body section h4{margin:0 0 10px}.training-recovery-kv{display:flex;justify-content:space-between;gap:16px;padding:8px 0;border-bottom:1px dashed #e5e7eb}.training-recovery-kv span{color:#64748b}
    .training-recovery-timeline{display:grid;gap:7px}.training-recovery-step{display:flex;gap:10px;align-items:center;padding:8px 10px;border-radius:8px;background:#f8fafc}.training-recovery-step.done .training-recovery-step-icon{color:#16a34a}.training-recovery-step.failed{background:#fef2f2}.training-recovery-step.failed .training-recovery-step-icon{color:#dc2626}.training-recovery-step.active{background:#eff6ff}.training-recovery-step.active .training-recovery-step-icon{color:#2563eb}.training-recovery-step.pending{color:#94a3b8}
    .training-recovery-callout{padding:12px 14px;border-radius:10px;background:#fffbeb;border:1px solid #fde68a;color:#92400e}.training-recovery-actions{display:flex;justify-content:flex-end;gap:10px;flex-wrap:wrap;padding:16px 22px;border-top:1px solid #e5e7eb}
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
  };
  const locks = new Set();

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

  function closeDetail() {
    doc?.querySelector?.('[data-training-recovery-overlay]')?.remove?.();
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

  async function openDetail(taskId) {
    const job = (state().jobs || []).find(item => String(item.id) === String(taskId));
    if (!job) {
      notify?.('训练任务不存在或列表尚未刷新');
      return false;
    }
    try {
      const recovery = await readRecovery(taskId);
      closeDetail();
      const host = doc?.createElement?.('div');
      if (!host) return false;
      host.innerHTML = detailHtml(job, recovery);
      const overlay = host.firstElementChild;
      if (!overlay) return false;
      doc.body?.appendChild(overlay);
      return true;
    } catch (error) {
      notify?.(error?.message || error);
      return false;
    }
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
    const log = event.target?.closest?.('[data-training-log-task]');
    if (log) {
      closeDetail();
      window.showTrainLog423?.(log.dataset.trainingLogTask);
      return;
    }
    const report = event.target?.closest?.('[data-training-report-task]');
    if (report) {
      closeDetail();
      window.trainingReport425?.(report.dataset.trainingReportTask);
    }
  };
  doc?.addEventListener?.('click', onClick);

  window.openTrainingRecoveryDetail = openDetail;
  window.revalidateTrainingCheckpoint = recover;

  const runtime = {
    build: 'training-recovery-runtime-422506',
    hydrateJobs,
    openDetail,
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
