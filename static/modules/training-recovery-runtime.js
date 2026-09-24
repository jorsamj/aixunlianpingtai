import {canonicalTaskProgressPercent, canonicalTaskStatus, isCanonicalTaskActive} from './task-runtime-truth.js?v=422424';
import {formatTrainingDuration, trainingApiErrorMessage, trainingProgressView} from './training-task-runtime.js?v=422562';

const RECOVERY_ACTION_REVALIDATE = 'revalidate_checkpoint';
const SUCCESS_TASK_STATUSES = new Set(['SUCCEEDED', 'PARTIAL_SUCCESS']);
const FAILED_TASK_STATUSES = new Set(['FAILED', 'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE']);

function taskStatusFlags(job = {}) {
  const canonical = canonicalTaskStatus(job);
  return {
    canonical,
    partial: canonical === 'PARTIAL_SUCCESS',
    success: SUCCESS_TASK_STATUSES.has(canonical),
    failed: FAILED_TASK_STATUSES.has(canonical),
    active: isCanonicalTaskActive(job),
  };
}

function resourceProfileLabel(value) {
  return ({balanced: '智能推荐', performance: '性能优先', stability: '稳定优先'})[
    String(value || '').trim().toLowerCase()
  ] || String(value || '-');
}

function uniqueText(values = []) {
  return [...new Set(values.map(value => String(value ?? '').trim()).filter(Boolean))];
}

function artifactNames(job = {}) {
  const rows = [];
  for (const value of job?.models || job?.verified_models || []) {
    const raw = typeof value === 'object' ? (value?.file_name || value?.path || value?.stored_path) : value;
    const text = String(raw || '').trim();
    if (text) rows.push(text.split(/[\\/]/).pop());
  }
  for (const value of [job?.best_path, job?.last_path]) {
    const text = String(value || '').trim();
    if (text) rows.push(text.split(/[\\/]/).pop());
  }
  return uniqueText(rows);
}

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

function failedEvidence(job = {}, recovery = {}) {
  return uniqueText([
    job?.root_cause,
    recovery?.root_cause,
    recovery?.failure_reason,
    job?.error,
    job?.failure_reason,
    job?.runtime_error,
    job?.process_error,
    job?.task_error,
    job?.message,
    job?.current_item,
  ]);
}

function failureRootCause(job = {}, recovery = {}) {
  const values = failedEvidence(job, recovery);
  const coded = values.find(value => /\b[A-Z][A-Z0-9]+(?:_[A-Z0-9]+)+\b/.test(value));
  if (coded) return coded;
  const specific = values.find(value => {
    const text = String(value || '').trim().toLowerCase();
    return text
      && !text.startsWith('training process exited with returncode=')
      && text !== 'job status is not done'
      && !text.startsWith('completion_handshake=');
  });
  return specific || values[0] || '';
}

function completionHandshakeText(job = {}, recovery = {}) {
  const explicit = String(
    recovery?.completion_handshake
    || job?.completion_handshake
    || job?.completion_error
    || ''
  ).trim();
  if (explicit) return explicit;
  for (const value of failedEvidence(job, recovery)) {
    const match = String(value || '').match(/completion_handshake=([^;]+)/i);
    if (match?.[1]) return match[1].trim();
  }
  return '';
}

export function canRecoverTrainingTask(recovery = {}) {
  return recovery?.available === true
    && recovery?.recoverable === true
    && recovery?.checkpoint_available === true
    && recovery?.recovery_action === RECOVERY_ACTION_REVALIDATE;
}

export function trainingRecoveryTimeline(job = {}, recovery = {}) {
  const flags = taskStatusFlags(job);
  const stage = String(job?.phase || job?.task_stage || job?.stage || '').toLowerCase();
  const failedStage = String(recovery?.failure_stage || job?.failure_stage || '').toLowerCase();
  const epoch = numberOrNull(job?.training_progress?.epoch) ?? numberOrNull(job?.current_epoch) ?? 0;
  const completedEpochs = Math.max(numberOrNull(recovery?.completed_epochs) || 0, epoch || 0);
  const trainingCompleted = recovery?.training_loop_completed === true || flags.success;
  const checkpointReady = recovery?.checkpoint_available === true || flags.success;
  const recovering = flags.active && Boolean(recovery?.retry_of || job?.retry_of);

  return [
    {key: 'queue', label: '排队与资源分配', state: 'done'},
    {key: 'prepare', label: '准备训练数据', state: trainingCompleted || completedEpochs > 0 ? 'done' : (stage.includes('prepar') || stage === 'materializing' ? 'active' : 'pending')},
    {key: 'training', label: completedEpochs > 0 ? `模型训练${recovery?.requested_epochs ? ` · ${completedEpochs}/${recovery.requested_epochs} Epoch` : ''}` : '模型训练', state: trainingCompleted ? 'done' : (failedStage === 'training_process' ? 'failed' : (stage === 'training' ? 'active' : 'pending'))},
    {key: 'checkpoint', label: '保存 Checkpoint', state: checkpointReady ? 'done' : (trainingCompleted ? 'failed' : 'pending')},
    {key: 'validation', label: recovering ? '重新验证 Checkpoint' : '最终模型验证', state: flags.success ? 'done' : (recovering && (stage === 'recovering_checkpoint' || stage === 'final_validation') ? 'active' : (failedStage === 'final_validation' || failedStage === 'post_training' ? 'failed' : 'pending'))},
    {key: 'archive', label: '归档训练结果', state: flags.success ? 'done' : (stage === 'finalizing_commit' ? 'active' : 'pending')},
  ];
}
export function trainingRecoveryDetailModel(job = {}, recovery = {}) {
  const flags = taskStatusFlags(job);
  const progress = job?.training_progress && typeof job.training_progress === 'object' ? job.training_progress : {};
  const progressView = trainingProgressView(job);
  const report = job?.training_report && typeof job.training_report === 'object' ? job.training_report : {};
  const testResult = report?.test_result && typeof report.test_result === 'object' ? report.test_result : {};
  const completedEpochs = numberOrNull(recovery?.completed_epochs) ?? numberOrNull(progress.epoch) ?? numberOrNull(job.current_epoch) ?? 0;
  const requestedEpochs = numberOrNull(recovery?.requested_epochs) ?? numberOrNull(progress.total_epochs) ?? numberOrNull(job.total_epochs) ?? numberOrNull(job.epochs);
  const recoverable = flags.failed && canRecoverTrainingTask(recovery);
  const rootCause = flags.failed ? failureRootCause(job, recovery) : '';
  const errors = flags.failed ? uniqueText([
    rootCause,
    ...failedEvidence(job, recovery),
    report?.validation_error,
    testResult?.error,
    job?.ai_intervention_last?.action === 'error' ? job?.ai_intervention_last?.reason : '',
    job?.version_archive_error,
  ]) : [];
  const warnings = uniqueText([
    job?.warning_message,
    flags.partial ? testResult?.error : '',
    flags.partial ? report?.validation_error : '',
    !flags.failed ? job?.version_archive_error : '',
    report?.error_analysis_error,
    report?.test_note,
  ]);
  const resolved = job?.resolved_resources && typeof job.resolved_resources === 'object' ? job.resolved_resources : {};
  const runtime = job?.runtime_resources && typeof job.runtime_resources === 'object' ? job.runtime_resources : {};
  const actual = job?.actual_train_params && typeof job.actual_train_params === 'object' ? job.actual_train_params : {};
  const requested = job?.requested_train_params && typeof job.requested_train_params === 'object' ? job.requested_train_params : {};
  const resourceStrategy = String(resolved.resource_strategy || requested.resource_strategy || job?.resource_strategy || '').trim().toLowerCase();
  const selectedGpu = job?.selected_gpu && typeof job.selected_gpu === 'object'
    ? job.selected_gpu
    : (resolved?.selected_gpu && typeof resolved.selected_gpu === 'object' ? resolved.selected_gpu : {});
  const counts = job?.dataset_counts && typeof job.dataset_counts === 'object'
    ? job.dataset_counts
    : (job?.counts && typeof job.counts === 'object' ? job.counts : {});
  const resourceProfile = String(actual.resource_profile || resolved.resource_profile || job?.resource_profile || requested.resource_profile || '').trim();
  const runtimeMetrics = job?.runtime_metrics && typeof job.runtime_metrics === 'object' ? job.runtime_metrics : {};
  const latestRuntime = runtimeMetrics?.latest && typeof runtimeMetrics.latest === 'object' ? runtimeMetrics.latest : {};
  const metricNumber = value => {
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  };
  return {
    taskId: String(job?.id || job?.task_id || recovery?.task_id || ''),
    canonicalStatus: flags.canonical,
    status: String(job?.status || '').trim().toLowerCase(),
    taskStatus: String(job?.task_status || recovery?.task_status || flags.canonical || '').trim().toUpperCase(),
    statusKind: flags.success ? (flags.partial ? 'partial' : 'success') : recoverable ? 'recoverable' : flags.failed ? 'failed' : 'active',
    statusMessage: String(job?.message || job?.current_item || '').trim(),
    failureStage: recovery?.failure_stage || job?.failure_stage || '',
    failureStageLabel: failureStageLabel(recovery?.failure_stage || job?.failure_stage || ''),
    rootCause,
    failureReason: rootCause || errors[0] || '',
    completionHandshake: completionHandshakeText(job, recovery),
    errorType: String(job?.error_type || '').trim(),
    errors,
    warnings,
    completedEpochs,
    requestedEpochs,
    currentBatch: progressView.currentBatch,
    totalBatches: progressView.totalBatches,
    progressPercent: flags.success ? 100 : canonicalTaskProgressPercent(job),
    elapsedSeconds: progressView.elapsedSeconds,
    etaSeconds: progressView.etaSeconds,
    elapsedText: formatTrainingDuration(progressView.elapsedSeconds),
    etaText: flags.success ? '-' : formatTrainingDuration(progressView.etaSeconds),
    metricLine: progressView.metricLine,
    trainingLoopCompleted: recovery?.training_loop_completed === true || flags.success,
    checkpointAvailable: recovery?.checkpoint_available === true || flags.success,
    checkpoint: recovery?.checkpoint || null,
    recoverable,
    action: recoverable ? recovery?.recovery_action || null : null,
    processReturncode: recovery?.process_returncode ?? job?.process_returncode ?? null,
    processSignal: recovery?.process_signal ?? job?.process_signal ?? null,
    attempt: numberOrNull(recovery?.attempt) ?? numberOrNull(job?.task_attempt) ?? 0,
    retryOf: recovery?.retry_of || job?.retry_of || null,
    algorithmName: String(job?.asset_algorithm_name || job?.algorithm_name || job?.asset_algorithm_id || '-'),
    taskName: String(job?.task_name || job?.run_name || job?.auto_version_name || job?.id || '-'),
    stage: String(job?.phase || job?.task_stage || job?.stage || '').trim(),
    workerId: String(job?.task_worker_id || job?.worker_id || '').trim(),
    requestedDevice: String(job?.requested_device || requested.device || '').trim(),
    assignedDevice: String(job?.assigned_device || '').trim(),
    actualDevice: String(job?.actual_device || '').trim(),
    gpuName: String(selectedGpu?.name || '').trim(),
    gpuUuid: String(selectedGpu?.uuid || '').trim(),
    resourceStrategy: String(actual.resource_strategy || resolved.resource_strategy || job?.resource_strategy || requested.resource_strategy || '').trim(),
    resourceProfile,
    resourceProfileLabel: resourceProfileLabel(resourceProfile),
    gpuPolicy: String(actual.gpu_policy || resolved.gpu_policy || job?.gpu_policy || requested.gpu_policy || '').trim(),
    precision: String(actual.effective_precision || actual.precision || resolved.precision || job?.precision || requested.precision || '').trim(),
    requestedBatch: requested.batch ?? job?.batch ?? null,
    resolvedBatch: resolved.resolved_batch ?? null,
    runtimeBatch: runtime.runtime_batch ?? actual.batch ?? null,
    requestedWorkers: requested.workers ?? job?.workers ?? null,
    requestedWorkersText: resourceStrategy === 'auto' ? '自动' : (requested.workers ?? job?.workers ?? null),
    resolvedWorkers: resolved.resolved_workers ?? null,
    runtimeWorkers: runtime.runtime_workers ?? actual.workers ?? null,
    requestedCache: requested.cache ?? job?.cache ?? null,
    requestedCacheText: (requested.cache ?? job?.cache ?? null) === false ? '关闭' : (requested.cache ?? job?.cache ?? null),
    resolvedCache: resolved.resolved_cache ?? null,
    runtimeCache: runtime.runtime_cache ?? actual.cache ?? null,
    batch: runtime.runtime_batch ?? actual.batch ?? resolved.resolved_batch ?? job?.batch ?? requested.batch ?? null,
    workers: runtime.runtime_workers ?? actual.workers ?? resolved.resolved_workers ?? job?.workers ?? requested.workers ?? null,
    cache: runtime.runtime_cache ?? actual.cache ?? resolved.resolved_cache ?? job?.cache ?? requested.cache ?? null,
    model: String(actual.model || job?.model || requested.model || '').split(/[\\/]/).pop(),
    imgsz: actual.imgsz ?? job?.imgsz ?? requested.imgsz ?? null,
    optimizer: String(actual.optimizer || job?.optimizer || requested.optimizer || '').trim(),
    lr0: actual.lr0 ?? job?.lr0 ?? requested.lr0 ?? null,
    timeLimit: actual.time ?? job?.time ?? requested.time ?? null,
    datasetCounts: {
      train: numberOrNull(counts.train ?? counts.training ?? counts.train_images) ?? 0,
      validation: numberOrNull(counts.validation ?? counts.val ?? counts.validation_images) ?? 0,
      test: numberOrNull(counts.test ?? counts.test_images) ?? 0,
    },
    artifacts: artifactNames(job),
    snapshotId: String(job?.snapshot_id || '').trim(),
    datasetRevisionId: String(job?.dataset_revision_id || '').trim(),
    trainingOutcome: String(job?.training_outcome || '').trim(),
    completionReason: String(job?.completion_reason || '').trim(),
    diagnosticCode: String(runtimeMetrics?.diagnostic?.code || '').trim(),
    gpuUtilization: metricNumber(latestRuntime.gpu_utilization),
    gpuMemoryPercent: metricNumber(latestRuntime.gpu_memory_percent),
    cpuPercent: metricNumber(latestRuntime.cpu_percent),
    ioWaitPercent: metricNumber(latestRuntime.io_wait_percent),
    imagesPerSecond: metricNumber(runtimeMetrics.images_per_second) ?? metricNumber(progress.images_per_second),
    latestEpochDuration: metricNumber(runtimeMetrics.epoch_duration_seconds),
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
  const failed = model.statusKind === 'failed' || model.statusKind === 'recoverable';
  const statusTitle = model.statusKind === 'recoverable'
    ? '训练主体已完成 · 模型验证失败'
    : model.statusKind === 'failed'
      ? '训练失败'
      : model.statusKind === 'partial'
        ? '训练已完成 · 存在非致命警告'
        : model.statusKind === 'success'
          ? '训练已完成'
          : '训练任务详情';
  const checkpoint = model.checkpoint;
  const epochText = model.requestedEpochs ? `${model.completedEpochs} / ${model.requestedEpochs}` : (model.completedEpochs || '-');
  const batchText = model.totalBatches ? `${model.currentBatch ?? '-'} / ${model.totalBatches}` : '-';
  const actionHtml = model.recoverable ? `<button class="btn primary" data-training-recovery-action="${RECOVERY_ACTION_REVALIDATE}" data-task-id="${esc(model.taskId)}">重新验证 Checkpoint</button>` : '';
  const checkpointRecoveryState = model.checkpointAvailable
    ? (model.recoverable ? 'Checkpoint 已保留 · 可重新验证' : 'Checkpoint 已保留 · 当前不可自动恢复')
    : '无可用 Checkpoint · 不可恢复';
  const failureSummaryHtml = failed ? `<section class="training-recovery-panel" data-training-failure-summary>
    <header><h4>失败主因与运行证据</h4><span>按诊断优先级展示，不改写后端事实</span></header>
    <div class="training-recovery-kv" data-failure-rank="1"><span>1. Root cause</span><b>${esc(model.rootCause || '-')}</b></div>
    <div class="training-recovery-kv" data-failure-rank="2"><span>2. Failure stage</span><b>${esc(model.failureStageLabel || model.failureStage || '-')}</b></div>
    <div class="training-recovery-kv" data-failure-rank="3"><span>3. Process return code</span><b>${esc(model.processReturncode ?? '-')}</b></div>
    <div class="training-recovery-kv" data-failure-rank="4"><span>4. Completion handshake</span><b>${esc(model.completionHandshake || '-')}</b></div>
    <div class="training-recovery-kv" data-failure-rank="5"><span>5. Checkpoint / Recovery</span><b>${esc(checkpointRecoveryState)}</b></div>
  </section>` : '';
  const reasonHtml = model.errors.length ? `<section class="training-recovery-reason"><header><b>其他错误与失败证据</b><span>任务 / Worker / 验证 / 归档</span></header>${model.errors.filter(value => value !== model.rootCause).map(value => `<p>${esc(value)}</p>`).join('')}</section>` : '';
  const warningHtml = model.warnings.length ? `<section class="training-recovery-warning"><header><b>警告 / 非致命异常</b><span>不会覆盖成功终态</span></header>${model.warnings.map(value => `<p>${esc(value)}</p>`).join('')}</section>` : '';
  const statusHtml = !failed && model.statusMessage ? `<div class="training-recovery-message"><b>当前信息</b><p>${esc(model.statusMessage)}</p></div>` : '';
  const artifacts = model.artifacts.length ? model.artifacts.join('、') : '-';
  const logHtml = `<details class="training-recovery-log" data-training-tech-log><summary><span>工程师技术日志</span><em>运行中自动刷新 · ${String(log || '').length.toLocaleString()} 字符</em></summary><pre>${esc(log || '暂无技术日志')}</pre></details>`;
  return `
    <div class="training-recovery-overlay" data-training-recovery-overlay>
      <div class="training-recovery-dialog" role="dialog" aria-modal="true" aria-label="训练任务详情">
        <div class="training-recovery-head">
          <div class="training-recovery-title"><span class="training-recovery-status ${esc(model.statusKind)}">${esc(model.statusKind === 'success' ? '成功' : model.statusKind === 'partial' ? '完成 / 警告' : model.statusKind === 'recoverable' ? '可恢复失败' : model.statusKind === 'failed' ? '失败' : '运行中')}</span><div><h3>${esc(statusTitle)}</h3><span>${esc(model.algorithmName)} · ${esc(model.taskName)} · ${esc(model.taskId)}</span></div></div>
          <button class="btn mini" data-training-recovery-close>关闭</button>
        </div>
        <div class="training-recovery-body">
          <section class="training-recovery-summary ${esc(model.statusKind)}">
            <div><small>整体进度</small><b>${model.progressPercent.toFixed(0)}%</b><i><span style="transform:scaleX(${(model.progressPercent / 100).toFixed(4)})"></span></i></div>
            <div><small>Epoch / Batch</small><b>${esc(epochText)} · ${esc(batchText)}</b><span>${esc(model.metricLine || '等待训练指标')}</span></div>
            <div><small>已用 / 剩余</small><b>${esc(model.elapsedText)} / ${esc(model.etaText)}</b><span>${esc(model.stage || model.statusMessage || '-')}</span></div>
            <div><small>实际设备</small><b>${esc(model.actualDevice || model.assignedDevice || model.requestedDevice || '-')}</b><span>${esc(model.gpuName || model.workerId || '-')}</span></div>
            <div><small>资源档位</small><b>${esc(model.resourceProfileLabel)}</b><span>${esc(`${model.resourceStrategy || 'auto'} · ${model.gpuPolicy || 'auto'}`)}</span></div>
            <div><small>实际 Batch / Workers / Cache</small><b>${esc(`${model.batch ?? '-'} / ${model.workers ?? '-'} / ${model.cache ?? '-'}`)}</b><span>${esc(model.precision || '-')}</span></div>
          </section>
          ${statusHtml}${failureSummaryHtml}${reasonHtml}${warningHtml}
          <div class="training-recovery-columns">
            <section class="training-recovery-panel">
              <header><h4>训练配置</h4><span>实际运行值优先</span></header>
              <div class="training-recovery-kv"><span>基础模型</span><b>${esc(model.model || '-')}</b></div>
              <div class="training-recovery-kv"><span>图片尺寸</span><b>${esc(model.imgsz ?? '-')}</b></div>
              <div class="training-recovery-kv"><span>Optimizer / lr0</span><b>${esc(`${model.optimizer || '-'} / ${model.lr0 ?? '-'}`)}</b></div>
              <div class="training-recovery-kv"><span>最大训练时长</span><b>${esc(model.timeLimit ? `${model.timeLimit} h` : '不限')}</b></div>
              <div class="training-recovery-kv"><span>用户请求资源</span><b>${esc(`Batch ${model.requestedBatch ?? '-'} · Workers ${model.requestedWorkersText ?? '-'} · Cache ${model.requestedCacheText ?? '-'}`)}</b></div>
              <div class="training-recovery-kv"><span>自动资源决议</span><b>${esc(`Batch ${model.resolvedBatch ?? '-'} · Workers ${model.resolvedWorkers ?? '-'} · Cache ${model.resolvedCache ?? '-'}`)}</b></div>
              <div class="training-recovery-kv"><span>实际 Runtime</span><b>${esc(`Batch ${model.runtimeBatch ?? '-'} · Workers ${model.runtimeWorkers ?? '-'} · Cache ${model.runtimeCache ?? '-'}`)}</b></div>
              <div class="training-recovery-kv"><span>数据量</span><b>${esc(`训练 ${model.datasetCounts.train} · 验证 ${model.datasetCounts.validation} · 评测 ${model.datasetCounts.test}`)}</b></div>
              <div class="training-recovery-kv"><span>成果模型</span><b title="${esc(artifacts)}">${esc(artifacts)}</b></div>
            </section>
            <section class="training-recovery-panel">
              <header><h4>运行证据</h4><span>后端真实状态</span></header>
              <div class="training-recovery-kv"><span>Task Status</span><b>${esc(model.canonicalStatus || model.taskStatus || '-')}</b></div>
              <div class="training-recovery-kv"><span>执行节点</span><b>${esc(model.workerId || '-')}</b></div>
              <div class="training-recovery-kv"><span>GPU UUID</span><b title="${esc(model.gpuUuid || '')}">${esc(model.gpuUuid || '-')}</b></div>
              <div class="training-recovery-kv"><span>训练结果</span><b>${esc(model.trainingOutcome || '-')}</b></div>
              <div class="training-recovery-kv"><span>完成原因</span><b>${esc(model.completionReason || '-')}</b></div>
              <div class="training-recovery-kv"><span>运行诊断</span><b>${esc(model.diagnosticCode || '-')}</b></div>
              <div class="training-recovery-kv"><span>GPU 利用率 / 显存</span><b>${esc(`${model.gpuUtilization == null ? '-' : model.gpuUtilization.toFixed(1) + '%'} / ${model.gpuMemoryPercent == null ? '-' : model.gpuMemoryPercent.toFixed(1) + '%'}`)}</b></div>
              <div class="training-recovery-kv"><span>CPU / I/O Wait</span><b>${esc(`${model.cpuPercent == null ? '-' : model.cpuPercent.toFixed(1) + '%'} / ${model.ioWaitPercent == null ? '-' : model.ioWaitPercent.toFixed(1) + '%'}`)}</b></div>
              <div class="training-recovery-kv"><span>实时吞吐 / Epoch</span><b>${esc(`${model.imagesPerSecond == null ? '-' : model.imagesPerSecond.toFixed(1) + ' img/s'} / ${model.latestEpochDuration == null ? '-' : model.latestEpochDuration.toFixed(1) + 's'}`)}</b></div>
              <div class="training-recovery-kv"><span>错误类型</span><b>${esc(model.errorType || '-')}</b></div>
            </section>
          </div>
          <section class="training-recovery-panel">
            <header><h4>数据与资源追踪</h4><span>用于复现本次训练</span></header>
            <div class="training-recovery-kv"><span>数据版本</span><b title="${esc(model.datasetRevisionId)}">${esc(model.datasetRevisionId || '-')}</b></div>
            <div class="training-recovery-kv"><span>训练快照</span><b title="${esc(model.snapshotId)}">${esc(model.snapshotId || '-')}</b></div>
            <div class="training-recovery-kv"><span>Checkpoint</span><b>${esc(checkpoint ? `${checkpoint.filename || '-'} · ${bytesText(checkpoint.size_bytes)}` : '-')}</b></div>
            <div class="training-recovery-kv"><span>Process</span><b>${esc(`Signal ${model.processSignal || '-'} · Return Code ${model.processReturncode ?? '-'} · Attempt ${model.attempt || '-'}`)}</b></div>
            <div class="training-recovery-kv"><span>创建 / 开始 / 完成</span><b>${esc(`${model.createdAt || '-'} / ${model.startedAt || '-'} / ${model.finishedAt || '-'}`)}</b></div>
            ${model.resourceAdjustments.length ? `<div class="training-recovery-kv"><span>资源自动调整</span><b>${esc(model.resourceAdjustments.join('；'))}</b></div>` : ''}
            ${model.resourceReasons.length ? `<div class="training-recovery-kv"><span>资源决策依据</span><b>${esc(model.resourceReasons.join('；'))}</b></div>` : ''}
          </section>
          <section class="training-recovery-panel"><header><h4>执行阶段</h4><span>任务生命周期</span></header>${timelineHtml(model.timeline)}</section>
          ${logHtml}
          ${model.recoverable ? '<div class="training-recovery-callout">训练主体与可信 Checkpoint 已保留，可只重新执行最终模型验证，不需要重跑全部 Epoch。</div>' : ''}
        </div>
        <div class="training-recovery-actions">
          <span>运行中每 1.5 秒同步详情；列表同时接收实时任务事件</span>
          <button class="btn" data-training-detail-refresh="${esc(model.taskId)}">立即刷新</button>
          ${job?.auto_version_id ? `<button class="btn" data-training-report-task="${esc(model.taskId)}">查看训练报告</button>` : ''}
          ${actionHtml}
        </div>
      </div>
    </div>`;
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

  const previous = {
    openTrainingRecoveryDetail: window.openTrainingRecoveryDetail,
    revalidateTrainingCheckpoint: window.revalidateTrainingCheckpoint,
    showTrainLog423: window.showTrainLog423,
    showTrainLog424: window.showTrainLog424,
    openTrainDetail423: window.openTrainDetail423,
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
    if (!response.ok) throw new Error(trainingApiErrorMessage(body, fallback, response?.status));
    return body;
  }

  async function hydrateJobs(jobs = []) {
    const pid = projectId?.();
    if (!pid) return jobs;
    const ids = jobs.filter(job => FAILED_TASK_STATUSES.has(canonicalTaskStatus(job))).map(job => String(job.id || job.task_id || '')).filter(Boolean);
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
      throw new Error(trainingApiErrorMessage(body, '读取训练日志失败', response?.status));
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
    const nextOverlay = host.firstElementChild;
    if (!nextOverlay) return false;
    const nextDialog = nextOverlay.querySelector?.('.training-recovery-dialog');
    let overlay = nextOverlay;
    let dialog = nextDialog;
    if (old && oldDialog && nextDialog) {
      oldDialog.replaceChildren(...Array.from(nextDialog.childNodes));
      overlay = old;
      dialog = oldDialog;
    } else {
      old?.remove?.();
      doc.body?.appendChild(nextOverlay);
    }
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
    if (!isCanonicalTaskActive(job) || !openTaskId) return;
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
      const flags = taskStatusFlags(job);
      const effectiveRecovery = flags.success ? {} : recovery;
      openSnapshot = {job, recovery: effectiveRecovery, log};
      updateStateJob(flags.success ? {...job, recovery: undefined} : job);
      renderOpenDetail(job, effectiveRecovery, log);
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
      await refreshOpenDetail({includeRecovery: FAILED_TASK_STATUSES.has(canonicalTaskStatus(job))});
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
    // Live durable truth must outrank a stale task_status kept in the open
    // detail snapshot. Some event producers expose the canonical state as
    // persisted_status/status rather than task_status; normalize only the
    // incoming payload before merging so RUNNING can never mask SUCCEEDED,
    // PARTIAL_SUCCESS, FAILED, or another newer terminal state.
    const incomingStatusSource = job?.task_status ?? job?.persisted_status ?? job?.status;
    const incomingTaskStatus = canonicalTaskStatus(incomingStatusSource);
    const merged = {
      ...current,
      ...job,
      ...(incomingTaskStatus ? {task_status: incomingTaskStatus} : {}),
    };
    const flags = taskStatusFlags(merged);
    const recovery = flags.success ? {} : (openSnapshot?.recovery || {});
    if (flags.success) merged.recovery = undefined;
    openSnapshot = {...(openSnapshot || {}), job: merged, recovery};
    renderOpenDetail(merged, recovery, openSnapshot.log || '');
    if (flags.active) {
      scheduleDetailRefresh(merged);
    } else {
      stopDetailTimer();
      queueMicrotask(() => {
        if (String(openTaskId) !== taskId) return;
        void refreshOpenDetail({includeRecovery: flags.failed}).catch(error => {
          notify?.(`训练终态对账失败，已保留最后实时状态：${error?.message || error}`);
        });
      });
    }
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
  window.showTrainLog424 = taskId => openDetail(taskId, {focus: 'log'});
  window.openTrainDetail423 = taskId => openDetail(taskId, {focus: 'overview'});
  window.refreshTrainRunCenter429 = taskId => {
    if (String(openTaskId) !== String(taskId)) return openDetail(taskId, {focus: 'log'});
    return refreshOpenDetail({includeRecovery: true});
  };

  const runtime = {
    build: 'training-recovery-runtime-422508',
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
