const RESUME_MODE = 'training_checkpoint_resume';
const ACTIVE_STATUSES = new Set(['queued', 'waiting', 'pending', 'running', 'paused']);
const SUCCESS_STATUSES = new Set(['done', 'finished', 'completed']);

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

function numberOrNull(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function fileName(path) {
  const value = String(path || '').replace(/\\/g, '/');
  return value.split('/').filter(Boolean).pop() || '-';
}

export function isCheckpointResumeJob(job = {}) {
  return String(job?.recovery_mode || '').trim() === RESUME_MODE;
}

export function checkpointResumeView(job = {}) {
  const progress = job?.training_progress && typeof job.training_progress === 'object'
    ? job.training_progress
    : {};
  const fromEpoch = numberOrNull(job?.resume_from_epoch) ?? numberOrNull(progress?.resume_from_epoch) ?? 0;
  const currentEpoch = numberOrNull(progress?.epoch) ?? numberOrNull(job?.current_epoch) ?? fromEpoch;
  const totalEpochs = numberOrNull(progress?.total_epochs)
    ?? numberOrNull(job?.requested_epochs)
    ?? numberOrNull(job?.total_epochs)
    ?? numberOrNull(job?.epochs);
  const status = String(job?.task_status || job?.status || '').toLowerCase();
  const phase = String(job?.phase || job?.task_stage || '').toLowerCase();
  const recoveryState = String(job?.recovery_state || '').toLowerCase();
  const active = ACTIVE_STATUSES.has(String(job?.status || '').toLowerCase())
    || ['running', 'queued', 'leased'].includes(status);
  const complete = SUCCESS_STATUSES.has(String(job?.status || '').toLowerCase())
    || recoveryState === 'completed';
  const failed = recoveryState === 'failed' || String(job?.status || '').toLowerCase() === 'failed';
  const validationActive = ['cleaning_training_process', 'final_validation', 'recovering_checkpoint'].includes(phase);
  const archiveActive = ['finalizing', 'finalizing_commit'].includes(phase);
  return {
    active,
    complete,
    failed,
    fromEpoch,
    currentEpoch,
    totalEpochs,
    recoveryState,
    phase,
    checkpointName: fileName(job?.resume_checkpoint),
    checkpointSha256: String(job?.resume_checkpoint_sha256 || ''),
    assignedDevice: String(job?.assigned_device || job?.actual_device || '-'),
    workerId: String(job?.task_worker_id || '-'),
    currentItem: String(job?.current_item || job?.message || ''),
    validationActive,
    archiveActive,
  };
}

export function checkpointResumeBadge(job = {}) {
  if (!isCheckpointResumeJob(job)) return '';
  const view = checkpointResumeView(job);
  if (view.failed) return '断点续训失败';
  if (view.complete) return `已从 Epoch ${view.fromEpoch} 恢复`;
  if (view.validationActive) return `续训完成 · 正在模型验证`;
  if (view.archiveActive) return `续训完成 · 正在归档`;
  return `断点续训 · 从 Epoch ${view.fromEpoch}`;
}

export function checkpointResumeTimeline(job = {}) {
  const view = checkpointResumeView(job);
  const trainingState = view.failed ? 'failed' : (view.complete || view.validationActive || view.archiveActive ? 'done' : 'active');
  const validationState = view.complete
    ? 'done'
    : (view.validationActive ? 'active' : (view.failed && view.phase === 'final_validation' ? 'failed' : 'pending'));
  const archiveState = view.complete ? 'done' : (view.archiveActive ? 'active' : 'pending');
  return [
    {label: '任务重新接管', state: 'done'},
    {label: `校验 last.pt · Epoch ${view.fromEpoch}`, state: 'done'},
    {
      label: view.totalEpochs
        ? `断点续训 · ${view.currentEpoch}/${view.totalEpochs} Epoch`
        : `断点续训 · Epoch ${view.currentEpoch}`,
      state: trainingState,
    },
    {label: '独立验证最佳模型', state: validationState},
    {label: '版本与结果归档', state: archiveState},
  ];
}

function ensureStyles(doc) {
  if (!doc || doc.getElementById('training-checkpoint-resume-ui-style')) return;
  const style = doc.createElement('style');
  style.id = 'training-checkpoint-resume-ui-style';
  style.textContent = `
    .checkpoint-resume-badge{display:inline-flex;align-items:center;gap:5px;margin-top:6px;padding:3px 8px;border-radius:999px;background:#eef6ff;border:1px solid #bfdbfe;color:#1d4ed8;font-size:11px;font-weight:650;line-height:1.4}
    .checkpoint-resume-badge:before{content:'↻';font-size:12px}
    .checkpoint-resume-overlay{position:fixed;inset:0;z-index:10120;background:rgba(15,23,42,.48);display:flex;align-items:center;justify-content:center;padding:24px}
    .checkpoint-resume-dialog{width:min(760px,calc(100vw - 32px));max-height:calc(100vh - 48px);overflow:auto;background:#fff;border-radius:16px;box-shadow:0 24px 72px rgba(15,23,42,.26)}
    .checkpoint-resume-head{display:flex;align-items:flex-start;justify-content:space-between;gap:16px;padding:20px 22px;border-bottom:1px solid #e5e7eb}.checkpoint-resume-head h3{margin:0 0 5px;font-size:20px;color:#0f172a}.checkpoint-resume-head p{margin:0;color:#64748b;font-size:12px}
    .checkpoint-resume-body{padding:18px 22px 22px;display:grid;gap:16px}.checkpoint-resume-hero{display:flex;align-items:center;justify-content:space-between;gap:16px;padding:15px 16px;border:1px solid #bfdbfe;border-radius:12px;background:linear-gradient(135deg,#eff6ff,#f8fbff)}.checkpoint-resume-hero b{display:block;color:#1d4ed8;font-size:16px}.checkpoint-resume-hero span{display:block;margin-top:4px;color:#475569;font-size:13px}.checkpoint-resume-percent{font-size:26px;font-weight:750;color:#0f172a;white-space:nowrap}
    .checkpoint-resume-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}.checkpoint-resume-grid>div{padding:12px;border:1px solid #e5e7eb;border-radius:10px;background:#f8fafc}.checkpoint-resume-grid small{display:block;color:#64748b;margin-bottom:5px}.checkpoint-resume-grid b{display:block;color:#0f172a;overflow-wrap:anywhere}
    .checkpoint-resume-section h4{margin:0 0 10px;color:#0f172a}.checkpoint-resume-timeline{display:grid;gap:7px}.checkpoint-resume-step{display:flex;align-items:center;gap:10px;padding:9px 11px;border-radius:9px;background:#f8fafc;color:#334155}.checkpoint-resume-step i{display:inline-grid;place-items:center;width:21px;height:21px;border-radius:50%;font-style:normal;background:#e2e8f0;color:#64748b}.checkpoint-resume-step.done i{background:#dcfce7;color:#15803d}.checkpoint-resume-step.active{background:#eff6ff;color:#1d4ed8}.checkpoint-resume-step.active i{background:#dbeafe;color:#2563eb}.checkpoint-resume-step.failed{background:#fef2f2;color:#b91c1c}.checkpoint-resume-step.failed i{background:#fee2e2;color:#dc2626}
    .checkpoint-resume-note{padding:12px 14px;border-radius:10px;background:#f8fafc;border:1px solid #e2e8f0;color:#475569;line-height:1.65}.checkpoint-resume-actions{display:flex;justify-content:flex-end;gap:10px;padding:15px 22px;border-top:1px solid #e5e7eb}
    @media(max-width:680px){.checkpoint-resume-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.checkpoint-resume-overlay{padding:10px}.checkpoint-resume-hero{align-items:flex-start;flex-direction:column}}
  `;
  doc.head?.appendChild(style);
}

function timelineHtml(job) {
  const icon = state => ({done: '✓', active: '●', failed: '×', pending: '○'})[state] || '○';
  return `<div class="checkpoint-resume-timeline">${checkpointResumeTimeline(job).map(step => `
    <div class="checkpoint-resume-step ${esc(step.state)}"><i>${icon(step.state)}</i><span>${esc(step.label)}</span></div>
  `).join('')}</div>`;
}

function detailHtml(job) {
  const view = checkpointResumeView(job);
  const total = view.totalEpochs || '-';
  const percent = view.totalEpochs ? Math.max(0, Math.min(100, 100 * view.currentEpoch / view.totalEpochs)) : 0;
  const title = view.failed ? '断点续训失败' : (view.complete ? '断点续训已完成' : '正在从 Checkpoint 恢复训练');
  return `
    <div class="checkpoint-resume-overlay" data-checkpoint-resume-overlay>
      <div class="checkpoint-resume-dialog" role="dialog" aria-modal="true" aria-label="训练断点恢复详情">
        <div class="checkpoint-resume-head"><div><h3>${esc(title)}</h3><p>${esc(job.id || '')}</p></div><button class="btn mini" data-checkpoint-resume-close>关闭</button></div>
        <div class="checkpoint-resume-body">
          <div class="checkpoint-resume-hero"><div><b>${esc(checkpointResumeBadge(job))}</b><span>${esc(view.currentItem || '后台 Worker 正在执行恢复流程')}</span></div><div class="checkpoint-resume-percent">${Math.round(percent)}%</div></div>
          <section class="checkpoint-resume-grid">
            <div><small>恢复起点</small><b>Epoch ${esc(view.fromEpoch)}</b></div>
            <div><small>当前轮次</small><b>${esc(view.currentEpoch)} / ${esc(total)}</b></div>
            <div><small>Checkpoint</small><b>${esc(view.checkpointName)}</b></div>
            <div><small>恢复状态</small><b>${esc(view.recoveryState || 'running')}</b></div>
            <div><small>训练设备</small><b>${esc(view.assignedDevice)}</b></div>
            <div><small>执行 Worker</small><b>${esc(view.workerId)}</b></div>
          </section>
          <section class="checkpoint-resume-section"><h4>恢复流程</h4>${timelineHtml(job)}</section>
          <div class="checkpoint-resume-note">系统只会在同一训练任务、同一 Snapshot、同一 run 目录且 task-local last.pt 通过完整性校验时自动续训；如果这些条件不成立，后台不会把普通重跑伪装成断点续训。</div>
        </div>
        <div class="checkpoint-resume-actions"><button class="btn" data-checkpoint-resume-log="${esc(job.id || '')}">查看训练日志</button><button class="btn primary" data-checkpoint-resume-close>关闭</button></div>
      </div>
    </div>`;
}

export function installTrainingCheckpointResumeUI({getState, notify} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;
  if (window.__trainingCheckpointResumeUIInstalled) return window.TrainingCheckpointResumeUI;
  const doc = document;
  const state = () => getState?.() || {};
  ensureStyles(doc);
  const originalOpenDetail = window.openTrainingRecoveryDetail;

  function jobsById() {
    return new Map((state().jobs || []).map(job => [String(job?.id || ''), job]));
  }

  function decorate() {
    const jobs = jobsById();
    for (const row of doc.querySelectorAll('tr[data-job-id]')) {
      const job = jobs.get(String(row.dataset.jobId || ''));
      const cell = row.children?.[1];
      const previous = cell?.querySelector?.('.checkpoint-resume-badge');
      if (!job || !isCheckpointResumeJob(job)) {
        previous?.remove?.();
        continue;
      }
      const text = checkpointResumeBadge(job);
      if (previous) previous.textContent = text;
      else if (cell) cell.insertAdjacentHTML('beforeend', `<span class="checkpoint-resume-badge">${esc(text)}</span>`);
    }
  }

  function close() {
    doc.querySelector('[data-checkpoint-resume-overlay]')?.remove?.();
  }

  function open(taskId) {
    const job = jobsById().get(String(taskId || ''));
    if (!job || !isCheckpointResumeJob(job)) {
      return typeof originalOpenDetail === 'function' ? originalOpenDetail(taskId) : false;
    }
    close();
    doc.body.insertAdjacentHTML('beforeend', detailHtml(job));
    return true;
  }

  window.openTrainingRecoveryDetail = open;
  const observer = new MutationObserver(() => decorate());
  observer.observe(doc.getElementById('view') || doc.body, {subtree: true, childList: true});
  doc.addEventListener('click', event => {
    if (event.target.closest('[data-checkpoint-resume-close]')) {
      event.preventDefault();
      close();
      return;
    }
    const log = event.target.closest('[data-checkpoint-resume-log]');
    if (log) {
      event.preventDefault();
      close();
      if (typeof window.showTrainLog423 === 'function') window.showTrainLog423(log.dataset.checkpointResumeLog);
      else notify?.('训练日志功能尚未加载');
    }
  });
  decorate();

  const runtime = {
    decorate,
    open,
    destroy() {
      observer.disconnect();
      close();
      if (window.openTrainingRecoveryDetail === open) window.openTrainingRecoveryDetail = originalOpenDetail;
      window.__trainingCheckpointResumeUIInstalled = false;
      if (window.TrainingCheckpointResumeUI === runtime) window.TrainingCheckpointResumeUI = null;
    },
  };
  window.TrainingCheckpointResumeUI = runtime;
  window.__trainingCheckpointResumeUIInstalled = true;
  return runtime;
}
