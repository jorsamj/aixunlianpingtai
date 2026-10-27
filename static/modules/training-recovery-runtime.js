import {canonicalTaskProgressPercent, canonicalTaskStatus, isCanonicalTaskActive} from './task-runtime-truth.js?v=422424';
import {formatTrainingDuration, trainingApiErrorMessage, trainingProgressView} from './training-task-runtime.js?v=422562';
import {trainingCharts, mountReportCharts, disposeReportViews} from './reports.js?v=20261022a';
import {withRequestDeadline} from './api.js?v=20261021s';

const RECOVERY_ACTION_REVALIDATE = 'revalidate_checkpoint';
const SUCCESS_TASK_STATUSES = new Set(['SUCCEEDED', 'PARTIAL_SUCCESS']);
const FAILED_TASK_STATUSES = new Set(['FAILED', 'BLOCKED_BY_ENVIRONMENT', 'BLOCKED_BY_HARDWARE']);
const WORKSPACE_BLOCKERS = {TASK_ACTIVE:'任务仍在执行', EXECUTION_LEASE_PRESENT:'执行租约尚未释放', PROCESS_PRESENT:'训练进程仍存在', ACTIVE_CONSUMER:'其他任务正在使用', OWNERSHIP_UNVERIFIED:'临时空间归属尚未验证', UNSAFE_PATH:'临时空间路径未通过安全校验', MODEL_EVIDENCE_UNVERIFIED:'模型归档尚未验证', RECOVERY_DEPENDENCY:'恢复训练仍依赖此临时空间'};

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

function patchTrainingDetailDom(current, next) {
  if (!current || !next || current.nodeType !== next.nodeType || current.nodeName !== next.nodeName) return false;
  if (current.nodeType === 3 || current.nodeType === 8) {
    if (current.nodeValue !== next.nodeValue) current.nodeValue = next.nodeValue;
    return true;
  }
  if(current.hasAttribute?.('data-report-chart')||next.hasAttribute?.('data-report-chart'))return current.getAttribute('data-report-chart')===next.getAttribute('data-report-chart');
  const currentAttributes = Array.from(current.attributes || []);
  const nextAttributes = Array.from(next.attributes || []);
  for (const attribute of currentAttributes) {
    if (attribute.name === 'data-identity-probe') continue;
    if (!next.hasAttribute?.(attribute.name)) current.removeAttribute?.(attribute.name);
  }
  for (const attribute of nextAttributes) {
    if (current.getAttribute?.(attribute.name) !== attribute.value) {
      current.setAttribute?.(attribute.name, attribute.value);
    }
  }
  const currentChildren = Array.from(current.childNodes || []);
  const nextChildren = Array.from(next.childNodes || []);
  const length = Math.max(currentChildren.length, nextChildren.length);
  for (let index = 0; index < length; index += 1) {
    const oldChild = currentChildren[index];
    const nextChild = nextChildren[index];
    if (!nextChild) oldChild?.remove?.();
    else if (!oldChild) current.appendChild?.(nextChild.cloneNode?.(true) || nextChild);
    else if (!patchTrainingDetailDom(oldChild, nextChild)) {
      oldChild.replaceWith?.(nextChild.cloneNode?.(true) || nextChild);
    }
  }
  return true;
}

function failureStageLabel(stage) {
  return ({
    admission: '任务受理',
    training_input: '训练输入准备',
    data_integrity: '素材完整性核验',
    label_contract: '标签合同核验',
    resource_validation: '资源核验',
    worker_process: 'Worker 进程',
    trainer: '训练器',
    training_process: '训练进程',
    post_training: '训练结束后处理',
    final_validation: '最终模型验证',
    archive: '训练结果归档',
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
  const diagnosis = recovery?.diagnosis && typeof recovery.diagnosis === 'object'
    ? {
        code: String(recovery.diagnosis.code || '').trim(),
        certainty: String(recovery.diagnosis.certainty || 'unknown').trim().toLowerCase(),
        title: String(recovery.diagnosis.title || '').trim(),
        summary: String(recovery.diagnosis.summary || '').trim(),
        evidence: Array.isArray(recovery.diagnosis.evidence) ? recovery.diagnosis.evidence.map(String).filter(Boolean) : [],
        possible_causes: Array.isArray(recovery.diagnosis.possible_causes) ? recovery.diagnosis.possible_causes.map(String).filter(Boolean) : [],
        suggestions: Array.isArray(recovery.diagnosis.suggestions) ? recovery.diagnosis.suggestions.map(String).filter(Boolean) : [],
        checkpoint_message: String(recovery.diagnosis.checkpoint_message || '').trim(),
      }
    : null;
  const backendPrimary = String(recovery?.primary_message || '').trim();
  const rootCause = flags.failed ? (backendPrimary || failureRootCause(job, recovery)) : '';
  const backendDiagnostics = Array.isArray(recovery?.secondary_diagnostics)
    ? recovery.secondary_diagnostics.map(String)
    : [];
  const errors = flags.failed ? uniqueText(backendDiagnostics.length ? backendDiagnostics : [
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
  const requestedContract = job?.requested_resources && typeof job.requested_resources === 'object' ? job.requested_resources : {};
  const requestedTrainParams = job?.requested_train_params && typeof job.requested_train_params === 'object' ? job.requested_train_params : {};
  const requested = {...requestedContract, ...requestedTrainParams};
  const resourceStrategy = String(
    resolved.resource_strategy
    || requested.resource_strategy
    || requested.strategy
    || job?.resource_strategy
    || ''
  ).trim().toLowerCase();
  const selectedGpu = job?.selected_gpu && typeof job.selected_gpu === 'object'
    ? job.selected_gpu
    : (resolved?.selected_gpu && typeof resolved.selected_gpu === 'object' ? resolved.selected_gpu : {});
  const counts = job?.dataset_counts && typeof job.dataset_counts === 'object'
    ? job.dataset_counts
    : (job?.counts && typeof job.counts === 'object' ? job.counts : {});
  const resourceProfile = String(
    actual.resource_profile
    || resolved.resource_profile
    || job?.resource_profile
    || requested.resource_profile
    || requested.profile
    || ''
  ).trim();
  const ampPreflight = job?.amp_preflight && typeof job.amp_preflight === 'object' ? job.amp_preflight : {};
  const ampCheckMethod = String(job?.amp_check_method || ampPreflight.method || '').trim();
  const ampCheckResult = String(job?.amp_check_result || ampPreflight.result || '').trim();
  const precisionFallbackReason = String(job?.precision_fallback_reason || '').trim();
  const requestedPrecision = String(requested.precision || job?.precision || '').trim().toLowerCase();
  const resolvedPrecision = String(
    resolved.resolved_precision
    || job?.resolved_precision
    || resolved.precision
    || ''
  ).trim().toLowerCase();
  const runtimePrecision = String(
    runtime.actual_precision
    || runtime.runtime_precision
    || actual.effective_precision
    || ((job?.training_started === true || ['done','completed','succeeded'].includes(String(job?.status || '').toLowerCase())) ? actual.precision : '')
    || ''
  ).trim().toLowerCase();
  const requestedBatchValue = requested.batch ?? job?.batch ?? null;
  const runtimeMetrics = job?.runtime_metrics && typeof job.runtime_metrics === 'object' ? job.runtime_metrics : {};
  const metricNumber = value => {
    if (value === null || value === undefined || value === '') return null;
    const number = Number(value);
    return Number.isFinite(number) ? number : null;
  };
  const epochHistory = Array.isArray(runtimeMetrics.epochs) ? runtimeMetrics.epochs : [];
  const epochMap50 = row => metricNumber(row?.map50 ?? row?.metrics?.['metrics/mAP50(B)']);
  const recordedMap50 = epochHistory
    .map(row => ({epoch: numberOrNull(row?.epoch), value: epochMap50(row)}))
    .filter(row => row.epoch !== null && row.value !== null);
  const latestMap50 = recordedMap50.at(-1) || null;
  const bestMap50 = recordedMap50.reduce((best, row) => !best || row.value > best.value ? row : best, null);
  const observedMetricLine = latestMap50 ? `mAP50 ${(latestMap50.value * 100).toFixed(1)}% · Epoch ${latestMap50.epoch}` : '';
  const intervalStart = Date.parse(job.started_at || '');
  const intervalEnd = Date.parse(job.finished_at || '');
  const terminal = !flags.active;
  const intervalSamples = Array.isArray(runtimeMetrics.samples) && Number.isFinite(intervalStart) && (!terminal || Number.isFinite(intervalEnd))
    ? runtimeMetrics.samples.filter(sample=>{const at=Date.parse(sample.sampled_at||'');return Number.isFinite(at)&&at>=intervalStart&&(!Number.isFinite(intervalEnd)||at<=intervalEnd);}) : [];
  const latestRuntime = terminal ? Object.fromEntries(['gpu_utilization','gpu_memory_percent','cpu_percent','memory_percent','io_wait_percent','process_tree_memory_bytes','process_tree_peak_memory_bytes','process_tree_count'].map(key=>{
    const values=intervalSamples.map(sample=>metricNumber(sample[key])).filter(value=>value!==null);
    if (!values.length) return [key, null];
    if (key === 'process_tree_peak_memory_bytes') return [key, Math.max(...values)];
    if (key === 'process_tree_count') return [key, values.at(-1)];
    return [key,values.reduce((sum,value)=>sum+value,0)/values.length];
  })) : runtimeMetrics?.latest && typeof runtimeMetrics.latest === 'object' ? runtimeMetrics.latest : {};
  return {
    taskId: String(job?.id || job?.task_id || recovery?.task_id || ''),
    canonicalStatus: flags.canonical,
    status: String(job?.status || '').trim().toLowerCase(),
    taskStatus: String(job?.task_status || recovery?.task_status || flags.canonical || '').trim().toUpperCase(),
    statusKind: flags.success ? (flags.partial ? 'partial' : 'success') : recoverable ? 'recoverable' : flags.failed ? 'failed' : 'active',
    statusMessage: String(job?.message || job?.current_item || '').trim(),
    primaryErrorCode: String(recovery?.primary_error_code || '').trim(),
    diagnosis,
    diagnosisCertaintyLabel: ({confirmed: '已确认', suspected: '疑似', unknown: '原因未明'})[diagnosis?.certainty] || '原因未明',
    failureStage: recovery?.primary_stage || recovery?.failure_stage || job?.failure_stage || '',
    failureStageLabel: failureStageLabel(recovery?.primary_stage || recovery?.failure_stage || job?.failure_stage || ''),
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
    activeTrainingText: formatTrainingDuration(job?.training_display_progress?.active_training_seconds),
    activeTrainingComplete: job?.training_display_progress?.active_training_seconds_complete === true,
    attemptElapsedText: formatTrainingDuration(job?.training_display_progress?.attempt_elapsed_seconds),
    firstStartedAt: job?.training_display_progress?.first_started_at || '未知',
    wallFinishedAt: job?.training_display_progress?.wall_finished_at || '未完成或证据缺失',
    etaText: flags.success ? '-' : formatTrainingDuration(progressView.etaSeconds),
    metricLine: progressView.metricLine || observedMetricLine,
    bestEpoch: bestMap50?.epoch ?? null,
    bestMetricLine: bestMap50 ? `最佳 mAP50 ${(bestMap50.value * 100).toFixed(1)}%` : '',
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
    gpuName: String(selectedGpu?.name || resolved.gpu_name || '').trim(),
    gpuUuid: String(selectedGpu?.uuid || resolved.gpu_uuid || '').trim(),
    resourceStrategy: String(
      actual.resource_strategy
      || resolved.resource_strategy
      || job?.resource_strategy
      || requested.resource_strategy
      || requested.strategy
      || ''
    ).trim(),
    resourceProfile,
    resourceProfileLabel: resourceProfileLabel(resourceProfile),
    gpuPolicy: String(actual.gpu_policy || resolved.gpu_policy || job?.gpu_policy || requested.gpu_policy || '').trim(),
    precision: runtimePrecision || resolvedPrecision,
    requestedPrecision,
    requestedPrecisionText: requestedPrecision === 'auto' ? '自动' : (requestedPrecision || '-'),
    resolvedPrecision,
    runtimePrecision,
    ampCheckMethod,
    ampCheckResult,
    precisionFallbackReason,
    requestedBatch: requestedBatchValue,
    requestedBatchText: resourceStrategy === 'auto' && requestedBatchValue != null
      ? '偏好 ' + requestedBatchValue
      : requestedBatchValue,
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
    datasetCountsGenerated: ['train', 'training', 'train_images', 'validation', 'val', 'validation_images', 'test', 'test_images']
      .some((key) => Object.prototype.hasOwnProperty.call(counts, key) && counts[key] != null),
    datasetCounts: {
      train: numberOrNull(counts.train ?? counts.training ?? counts.train_images),
      validation: numberOrNull(counts.validation ?? counts.val ?? counts.validation_images),
      test: numberOrNull(counts.test ?? counts.test_images),
    },
    artifacts: artifactNames(job),
    snapshotId: String(job?.snapshot_id || '').trim(),
    datasetRevisionId: String(job?.dataset_revision_id || '').trim(),
    trainingOutcome: String(job?.training_outcome || '').trim(),
    completionReason: String(job?.completion_reason || '').trim(),
    diagnosticCode: String(runtimeMetrics?.diagnostic?.code || '').trim(),
    resourceSampleCount: intervalSamples.length,
    resourceSamples: intervalSamples,
    resourceTimeBasis: terminal ? '训练区间内已保留采样均值' : '最新运行采样',
    gpuUtilization: metricNumber(latestRuntime.gpu_utilization),
    gpuMemoryPercent: metricNumber(latestRuntime.gpu_memory_percent),
    cpuPercent: metricNumber(latestRuntime.cpu_percent),
    memoryPercent: metricNumber(latestRuntime.memory_percent),
    ioWaitPercent: metricNumber(latestRuntime.io_wait_percent),
    processTreeMemory: metricNumber(latestRuntime.process_tree_memory_bytes),
    processTreePeakMemory: metricNumber(latestRuntime.process_tree_peak_memory_bytes),
    processTreeCount: metricNumber(latestRuntime.process_tree_count),
    processTreeMemoryMeasure: String(runtimeMetrics?.latest?.process_tree_memory_measure || '').trim(),
    imagesPerSecond: metricNumber(runtimeMetrics.images_per_second) ?? metricNumber(progress.images_per_second),
    latestEpochDuration: metricNumber(runtimeMetrics.epoch_duration_seconds),
    resourceReasons: Array.isArray(resolved?.reasons) ? resolved.reasons.map(String) : [],
    resourceAdjustments: Array.isArray(resolved?.adjustments) ? resolved.adjustments.map(String) : [],
    hostMemorySource: String(resolved.host_memory_source || '').trim(),
    hostMemoryAvailable: numberOrNull(resolved.available_ram_bytes),
    hostMemoryBudget: numberOrNull(resolved.host_memory_budget_bytes),
    hostMemoryEstimate: numberOrNull(resolved.estimated_host_memory_bytes),
    cgroupMemoryLimit: numberOrNull(resolved.cgroup_memory_limit_bytes),
    prefetchFactor: numberOrNull(resolved.host_memory_prefetch_factor),
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

function inputIssuesHtml(inputIssues) {
  if (!inputIssues || !Number(inputIssues.issue_count || 0)) return '';
  const items = Array.isArray(inputIssues.items) ? inputIssues.items : [];
  const page = Math.max(1, Number(inputIssues.page || 1));
  const totalPages = Math.max(1, Number(inputIssues.total_pages || 1));
  const limit = Math.max(1, Number(inputIssues.limit || 100));
  const start = items.length ? (page - 1) * limit + 1 : 0;
  const end = start ? start + items.length - 1 : 0;
  return `<section class="training-recovery-panel" data-training-input-issues><header><h4>训练输入标签适配问题</h4><span>${Number(inputIssues.issue_count)} 张 · ${start}-${end}</span></header><div class="training-compatibility-list">${items.map(item => `<article class="training-compatibility-item">${item.thumbnail_url ? `<img src="${esc(item.thumbnail_url)}" loading="lazy" alt="">` : ''}<div><b>${esc(item.filename || item.image_id || '-')}</b><p>已审核：${esc((item.annotation_scope || []).join('、') || '无')}</p><p>本次要求：${esc((item.required_label_codes || []).join('、') || '无')}</p><p class="warn">缺失：${esc((item.missing_label_codes || []).join('、') || '无')}</p>${item.image_id ? `<div class="row"><button class="btn mini primary" data-training-input-review="${esc(item.image_id)}">去补审</button><button class="btn mini" data-training-input-exclude="${esc(item.image_id)}">排除本次训练</button></div>` : ''}</div></article>`).join('')}</div><div data-training-input-pagination></div></section>`;
}

export function trainingWorkspaceView(value = {}, project = '', task = '') {
  const truth = value.truth;
  const blockers = Array.isArray(truth?.blockers) ? truth.blockers : [];
  const reasons = WORKSPACE_BLOCKERS;
  const identity = truth?.project_id === project && truth?.task_id === task && Number.isInteger(truth?.attempt) && truth.attempt >= 0 && Boolean(truth?.snapshot_id);
  const released = ['deleted','already_clean'].includes(truth?.status);
  const canRelease = identity && truth.eligible === true && Array.isArray(truth.blockers) && blockers.length === 0 && !value.busy && !value.loading && !released;
  const message = value.busy ? '正在释放临时空间…' : value.loading ? '正在核验临时空间…' : released ? '临时训练空间已释放' : !truth || !identity ? `临时空间资格未知${value.error ? '：' + value.error : '，请重新核验'}` : canRelease ? '可安全清理本任务临时训练空间' : blockers.length ? `暂不能清理：${blockers.map(code=>reasons[code] || `未知阻塞原因（${code}）`).join('；')}` : '临时空间资格未知，请重新核验';
  return {canRelease, message, released};
}

function workspaceHtml(value, project, task) {
  const model = trainingWorkspaceView(value, project, task);
  return `<section class="training-recovery-callout" data-training-workspace aria-live="polite" aria-busy="${Boolean(value?.loading || value?.busy)}"><b>临时训练空间</b><p>${value?.loading || value?.busy ? '<i class="loading-spinner" aria-hidden="true"></i> ' : ''}${esc(model.message)}</p><p>临时文件逻辑大小：${value?.truth?.temporary_logical_bytes == null ? '未知' : esc(bytesText(value.truth.temporary_logical_bytes))} · 实际释放磁盘空间：未知</p><button class="btn" data-training-workspace-refresh ${value?.busy || value?.loading ? 'disabled' : ''}>重新核验</button> <button class="btn" data-training-workspace-cleanup ${model.canRelease ? '' : 'disabled'}>${value?.busy ? '正在释放…' : '释放临时空间'}</button></section>`;
}

function detailHtml(job, recovery, log = '', inputIssues = null, activeTab = 'curves', workspace = null, project = '') {
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
  const completed = model.statusKind === 'success' || model.statusKind === 'partial';
  const epochSummary = completed && model.bestEpoch != null ? `${epochText} · 最佳 Epoch ${model.bestEpoch}` : `${epochText} · ${batchText}`;
  const metricSummary = completed ? (model.bestMetricLine || model.metricLine || '指标未记录') : (model.metricLine || '等待训练指标');
  const actionHtml = model.recoverable ? `<button class="btn primary" data-training-recovery-action="${RECOVERY_ACTION_REVALIDATE}" data-task-id="${esc(model.taskId)}">重新验证 Checkpoint</button>` : '';
  const inputConflict = failed && /duplicate_annotation_conflict|content_hash_leakage|content hash leakage/i.test([model.primaryErrorCode,model.rootCause,...model.errors].join(' '));
  const conflictHtml = inputConflict ? `<section class="training-recovery-panel" data-training-duplicate-conflict><header><h4>训练输入检查失败，训练尚未开始或未完成输入准备</h4></header><p>重复素材的正式标注冲突或数据角色泄漏不是 Checkpoint 故障。请检查真实图片及标注，安全修复当前 GT 或调整新训练输入，再重新预检创建任务；原任务与冻结历史保持不变。</p><button class="btn primary" onclick="TrainingMaterialSummaryRuntime.openTaskDiagnosis('${esc(model.taskId)}')">查看并处理冲突</button></section>` : '';
  const checkpointRecoveryState = model.checkpointAvailable
    ? (model.recoverable ? 'Checkpoint 已保留 · 可重新验证' : 'Checkpoint 已保留 · 当前不可自动恢复')
    : '无可用 Checkpoint · 不可恢复';
  const checkpointMessage = model.diagnosis?.checkpoint_message || (model.recoverable
    ? '存在可信训练断点，可按当前恢复合同重新验证 Checkpoint。'
    : '当前没有可恢复的训练断点，需要重新创建训练任务。');
  const diagnosisList = (title, values, attribute) => values?.length ? `<div class="training-diagnosis-group" ${attribute}>
    <b>${esc(title)}</b><ul>${values.map(value => `<li>${esc(value)}</li>`).join('')}</ul>
  </div>` : '';
  const failureSummaryHtml = failed && model.diagnosis ? `<section class="training-recovery-panel training-failure-diagnosis ${esc(model.diagnosis.certainty)}" data-training-failure-summary data-training-failure-diagnosis>
    <header><h4>失败原因</h4><span>${esc(model.failureStageLabel || model.failureStage || '训练任务')}</span></header>
    <div class="training-diagnosis-heading"><div><b>${esc(model.diagnosis.title || model.rootCause || '训练任务失败')}</b><p>${esc(model.diagnosis.summary || '')}</p></div><span class="training-diagnosis-certainty ${esc(model.diagnosis.certainty)}">${esc(model.diagnosisCertaintyLabel)}</span></div>
    ${diagnosisList('诊断依据', model.diagnosis.evidence, 'data-training-diagnosis-evidence')}
    ${diagnosisList('可能原因', model.diagnosis.possible_causes, 'data-training-diagnosis-possible-causes')}
    ${diagnosisList('建议处理', model.diagnosis.suggestions, 'data-training-diagnosis-suggestions')}
    <div class="training-diagnosis-checkpoint ${model.recoverable ? 'recoverable' : 'unavailable'}">${esc(checkpointMessage)}</div>
  </section>` : failed ? `<section class="training-recovery-panel" data-training-failure-summary>
    <header><h4>失败原因</h4><span>${esc(model.failureStageLabel || model.failureStage || '训练任务')}</span></header>
    <div class="training-recovery-message"><b>${esc(model.rootCause || '训练任务失败')}</b><p>${esc(checkpointMessage)}</p></div>
  </section>` : '';
  const technicalFailureHtml = failed ? `<details class="training-recovery-log" data-training-failure-technical><summary>查看技术详情</summary>
    <div class="training-recovery-kv"><span>Error code</span><b>${esc(model.primaryErrorCode || model.errorType || '-')}</b></div>
    <div class="training-recovery-kv"><span>Failure stage</span><b>${esc(model.failureStage || '-')}</b></div>
    <div class="training-recovery-kv"><span>Process return code</span><b>${esc(model.processReturncode ?? '-')}</b></div>
    <div class="training-recovery-kv"><span>Completion handshake</span><b>${esc(model.completionHandshake || '-')}</b></div>
    <div class="training-recovery-kv"><span>Checkpoint / Recovery</span><b>${esc(checkpointRecoveryState)}</b></div>
    ${model.errors.map(value => `<p>${esc(value)}</p>`).join('')}
  </details>` : '';
  const warningHtml = model.warnings.length ? `<section class="training-recovery-warning"><header><b>警告 / 非致命异常</b><span>不会覆盖成功终态</span></header>${model.warnings.map(value => `<p>${esc(value)}</p>`).join('')}</section>` : '';
  const statusHtml = !failed && model.statusMessage ? `<div class="training-recovery-message"><b>当前信息</b><p>${esc(model.statusMessage)}</p></div>` : '';
  const artifacts = model.artifacts.length ? model.artifacts.join('、') : '-';
  const logHtml = `<details class="training-recovery-log" data-training-tech-log><summary><span>工程师技术日志</span><em>运行中自动刷新 · ${String(log || '').length.toLocaleString()} 字符</em></summary><pre>${esc(log || '暂无技术日志')}</pre></details>`;
  return `
    <div class="training-recovery-overlay" data-training-recovery-overlay>
      <div class="training-recovery-dialog" role="dialog" aria-modal="true" aria-label="训练任务详情">
        <div class="training-recovery-head">
          <div class="training-recovery-title"><span class="training-recovery-status ${esc(model.statusKind)}">${esc(model.statusKind === 'success' ? '成功' : model.statusKind === 'partial' ? '完成 / 警告' : model.statusKind === 'recoverable' ? '可恢复失败' : model.statusKind === 'failed' ? '失败' : '运行中')}</span><div><h3>${esc(statusTitle)}</h3><span>${esc(model.algorithmName)} · ${esc(model.taskName)}</span><small>任务 ID ${esc(model.taskId)} · ${esc(model.startedAt ? `开始 ${model.startedAt}` : model.createdAt ? `创建 ${model.createdAt}` : '时间未上报')}</small></div><button class="btn mini training-recovery-copy" data-training-copy-task="${esc(model.taskId)}" aria-label="复制任务 ID">复制 ID</button></div>
          <button class="btn mini" data-training-recovery-close>关闭</button>
        </div>
        <div class="training-recovery-body">
          <nav class="quality-tabs" role="tablist" aria-label="训练详情视图">${[['curves','训练曲线'],['resources','训练资源'],['data','数据与配置'],['diagnostics','日志与诊断']].map(([key,label])=>`<button id="training-tab-${key}" class="btn" role="tab" data-training-tab="${key}" aria-controls="training-panel-${key}" aria-selected="${key===activeTab}" tabindex="${key===activeTab?'0':'-1'}">${label}</button>`).join('')}</nav>
          <span class="training-tabs-scroll-hint" aria-hidden="true">← 横向滚动查看更多 →</span>
          <section class="training-recovery-summary ${esc(model.statusKind)}">
            <div><small>整体进度</small><b>${model.progressPercent.toFixed(0)}%</b><i><span style="transform:scaleX(${(model.progressPercent / 100).toFixed(4)})"></span></i></div>
            <div><small>${completed ? '训练进度 / 最佳指标' : 'Epoch / Batch'}</small><b>${esc(epochSummary)}</b><span>${esc(metricSummary)}</span></div>
            <div><small>总历时 / 预计剩余</small><b>${esc(model.elapsedText)} / ${esc(model.etaText)}</b><span>${esc(model.stage || model.statusMessage || '-')}</span></div>
            <div><small>实际设备</small><b>${esc(model.actualDevice || model.assignedDevice || model.requestedDevice || '-')}</b><span>${esc(model.gpuName || model.workerId || '-')}</span></div>
            <div><small>资源档位</small><b>${esc(model.resourceProfileLabel)}</b><span>${esc(`${model.resourceStrategy || 'auto'} · ${model.gpuPolicy || 'auto'}`)}</span></div>
            <div><small>实际 Batch / Workers / Cache</small><b>${esc(`${model.batch ?? '-'} / ${model.workers ?? '-'} / ${model.cache ?? '-'}`)}</b><span>${esc(model.runtimePrecision || '尚未启动 Trainer')}</span></div>
          </section>
          ${statusHtml}${conflictHtml}${failureSummaryHtml}${workspace ? workspaceHtml(workspace, project, model.taskId) : ''}${inputIssuesHtml(inputIssues)}${technicalFailureHtml}${warningHtml}
          <section id="training-panel-curves" data-training-panel="curves" role="tabpanel" aria-labelledby="training-tab-curves">${trainingCharts(job?.runtime_metrics?.epochs || job?.training_report?.history || [], model.resourceSamples || [])}</section>
          <div class="training-recovery-columns">
            <section id="training-panel-data" class="training-recovery-panel" data-training-panel="data" role="tabpanel" aria-labelledby="training-tab-data">
              <header><h4>训练配置</h4><span>实际运行值优先</span></header>
              <div class="training-recovery-kv"><span>基础模型</span><b>${esc(model.model || '-')}</b></div>
              <div class="training-recovery-kv"><span>图片尺寸</span><b>${esc(model.imgsz ?? '-')}</b></div>
              <div class="training-recovery-kv"><span>Optimizer / lr0</span><b>${esc(`${model.optimizer || '-'} / ${model.lr0 ?? '-'}`)}</b></div>
              <div class="training-recovery-kv"><span>最大训练时长</span><b>${esc(model.timeLimit ? `${model.timeLimit} h` : '不限')}</b></div>
              <div class="training-recovery-kv"><span>用户请求资源</span><b>${esc('Batch ' + (model.requestedBatchText ?? '-') + ' · Workers ' + (model.requestedWorkersText ?? '-') + ' · Precision ' + (model.requestedPrecisionText ?? '-') + ' · Cache ' + (model.requestedCacheText ?? '-'))}</b></div>
              <div class="training-recovery-kv"><span>${model.resourceStrategy === 'manual' ? '资源核验' : '自动资源决议'}</span><b>${esc('Batch ' + (model.resolvedBatch ?? '-') + ' · Workers ' + (model.resolvedWorkers ?? '-') + ' · Precision ' + (model.resolvedPrecision || '-') + ' · Cache ' + (model.resolvedCache ?? '-'))}</b></div>
              <div class="training-recovery-kv"><span>实际 Runtime</span><b>${esc('Batch ' + (model.runtimeBatch ?? '-') + ' · Workers ' + (model.runtimeWorkers ?? '-') + ' · Precision ' + (model.runtimePrecision || '-') + ' · Cache ' + (model.runtimeCache ?? '-'))}</b></div>
              <div class="training-recovery-kv"><span>AMP 检查</span><b>${esc((model.ampCheckMethod || "未记录") + " · " + (model.ampCheckResult || "未验证"))}</b></div>
              ${model.precisionFallbackReason ? `<div class="training-recovery-kv"><span>精度回退原因</span><b>${esc(model.precisionFallbackReason)}</b></div>` : ""}
              <div class="training-recovery-kv"><span>数据量</span><b>${esc(model.datasetCountsGenerated?`训练 ${model.datasetCounts.train} · 验证 ${model.datasetCounts.validation} · 评测 ${model.datasetCounts.test}`:'未生成')}</b></div>
              <div class="training-recovery-kv"><span>成果模型</span><b title="${esc(artifacts)}">${esc(artifacts)}</b></div>
            </section>
            <section id="training-panel-resources" class="training-recovery-panel" data-training-panel="resources" role="tabpanel" aria-labelledby="training-tab-resources">
              <header><h4>运行证据</h4><span>${esc(model.resourceTimeBasis)} · ${model.resourceSampleCount} 个区间采样</span></header>
              <div class="training-recovery-kv"><span>Task Status</span><b>${esc(model.canonicalStatus || model.taskStatus || '-')}</b></div>
              <div class="training-recovery-kv"><span>累计实际训练</span><b>${esc(model.activeTrainingText)}${model.activeTrainingComplete ? '' : '（已记录片段，非完整累计）'}</b></div>
              <div class="training-recovery-kv"><span>本次执行历时</span><b>${esc(model.attemptElapsedText)}</b></div>
              <div class="training-recovery-kv"><span>首次训练 / 最终完成（UTC）</span><b>${esc(model.firstStartedAt)} / ${esc(model.wallFinishedAt)}</b></div>
              <div class="training-recovery-kv"><span>执行节点</span><b>${esc(model.workerId || '未上报')}</b></div>
              <div class="training-recovery-kv"><span>GPU UUID</span><b title="${esc(model.gpuUuid || '')}">${esc(model.gpuUuid || '未上报')}</b></div>
              <div class="training-recovery-kv"><span>训练结果</span><b>${esc(model.trainingOutcome || '-')}</b></div>
              <div class="training-recovery-kv"><span>完成原因</span><b>${esc(model.completionReason || '-')}</b></div>
              <div class="training-recovery-kv"><span>运行诊断</span><b>${esc(model.diagnosticCode || '-')}</b></div>
              <div class="training-recovery-kv"><span>GPU 利用率 / 显存</span><b>${esc(`${model.gpuUtilization == null ? '未上报' : model.gpuUtilization.toFixed(1) + '%'} / ${model.gpuMemoryPercent == null ? '未上报' : model.gpuMemoryPercent.toFixed(1) + '%'}`)}</b></div>
              <div class="training-recovery-kv"><span>CPU / 系统内存 / I/O Wait</span><b>${esc(`${model.cpuPercent == null ? '未上报' : model.cpuPercent.toFixed(1) + '%'} / ${model.memoryPercent == null ? '未上报' : model.memoryPercent.toFixed(1) + '%'} / ${model.ioWaitPercent == null ? '未上报' : model.ioWaitPercent.toFixed(1) + '%'}`)}</b></div>
              <div class="training-recovery-kv"><span>宿主内存决议</span><b>${esc(model.hostMemoryBudget == null ? '未上报' : `${bytesText(model.hostMemoryEstimate)} / ${bytesText(model.hostMemoryBudget)} · ${model.hostMemorySource || 'host'} · Prefetch ${model.prefetchFactor ?? '-'}`)}</b></div>
              <div class="training-recovery-kv"><span>cgroup 限额</span><b>${esc(model.cgroupMemoryLimit == null ? '未上报' : bytesText(model.cgroupMemoryLimit))}</b></div>
              <div class="training-recovery-kv"><span>训练进程树内存</span><b>${esc(model.processTreeMemory == null ? '未上报' : `${bytesText(model.processTreeMemory)} · 峰值 ${bytesText(model.processTreePeakMemory)} · ${model.processTreeCount ?? '-'} 进程 · ${model.processTreeMemoryMeasure || '已去重口径'}`)}</b></div>
              <div class="training-recovery-kv"><span>实时吞吐 / Epoch</span><b>${esc(`${model.imagesPerSecond == null ? '-' : model.imagesPerSecond.toFixed(1) + ' img/s'} / ${model.latestEpochDuration == null ? '-' : model.latestEpochDuration.toFixed(1) + 's'}`)}</b></div>
              <div class="training-recovery-kv"><span>错误类型</span><b>${esc(model.errorType || '-')}</b></div>
            </section>
          </div>
          <section id="training-panel-data-trace" class="training-recovery-panel" data-training-panel="data" role="tabpanel" aria-labelledby="training-tab-data">
            <header><h4>数据与资源追踪</h4><span>用于复现本次训练</span></header>
            <div class="training-recovery-kv"><span>数据版本</span><b title="${esc(model.datasetRevisionId)}">${esc(model.datasetRevisionId || '-')}</b></div>
            <div class="training-recovery-kv"><span>训练快照</span><b title="${esc(model.snapshotId)}">${esc(model.snapshotId || '-')}</b></div>
            <div class="training-recovery-kv"><span>Checkpoint</span><b>${esc(checkpoint ? `${checkpoint.filename || '-'} · ${bytesText(checkpoint.size_bytes)}` : '-')}</b></div>
            <div class="training-recovery-kv"><span>Process</span><b>${esc(`Signal ${model.processSignal || '-'} · Return Code ${model.processReturncode ?? '-'} · Attempt ${model.attempt || '-'}`)}</b></div>
            <div class="training-recovery-kv"><span>创建 / 开始 / 完成</span><b>${esc(`${model.createdAt || '-'} / ${model.startedAt || '-'} / ${model.finishedAt || '-'}`)}</b></div>
            ${model.resourceAdjustments.length ? `<div class="training-recovery-kv"><span>资源自动调整</span><b>${esc(model.resourceAdjustments.join('；'))}</b></div>` : ''}
            ${model.resourceReasons.length ? `<div class="training-recovery-kv"><span>资源决策依据</span><b>${esc(model.resourceReasons.join('；'))}</b></div>` : ''}
          </section>
          <section id="training-panel-diagnostics" class="training-recovery-panel" data-training-panel="diagnostics" role="tabpanel" aria-labelledby="training-tab-diagnostics"><header><h4>执行阶段</h4><span>任务生命周期</span></header>${timelineHtml(model.timeline)}${logHtml}</section>
          ${model.recoverable ? '<div class="training-recovery-callout">训练主体与可信 Checkpoint 已保留，可只重新执行最终模型验证，不需要重跑全部 Epoch。</div>' : ''}
        </div>
        <div class="training-recovery-actions">
          <span>${completed ? '任务已结束 · 不再进行高频轮询' : '运行中每 1.5 秒同步精简详情；历史曲线按需加载'}</span>
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
  let openProjectId = '';
  let activeTab = 'curves';
  let openFocus = 'overview';
  let openSnapshot = null;
  let detailRefreshPromise = null;
  let detailSession = 0;
  let workspace = null;
  let workspaceReadPromise = null;
  let workspaceHistory = null;
  const detailHistoryCache = new Map();
  const detailHistoryLoaded = new Set();
  let detailHistoryProjectId = '';
  let previouslyFocusedElement = null;
  let detailCloseTimer = null;
  const DETAIL_POLL_KEY = 'training-task-detail';
  const DETAIL_HISTORY_LIMIT = 8;

  async function json(response, fallback) {
    const raw = await response.text();
    let body = {};
    try { body = raw ? JSON.parse(raw) : {}; } catch (_) { body = {detail: raw}; }
    if (!response.ok) throw Object.assign(new Error(trainingApiErrorMessage(body, fallback, response?.status)), {detail:body?.detail});
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

  function closeDetail({immediate = false} = {}) {
    detailSession++;
    workspace = null;
    workspaceReadPromise = null;
    stopDetailTimer();
    const overlay = doc?.querySelector?.('[data-training-recovery-overlay]');
    disposeReportViews(overlay);
    const restoreFocus = () => {
      if (previouslyFocusedElement?.isConnected !== false) previouslyFocusedElement?.focus?.();
      previouslyFocusedElement = null;
    };
    if (detailCloseTimer !== null) {
      window.clearTimeout?.(detailCloseTimer);
      detailCloseTimer = null;
    }
    if (overlay && !immediate && !window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches) {
      overlay.classList?.add?.('is-closing');
      detailCloseTimer = window.setTimeout?.(() => {
        detailCloseTimer = null;
        overlay.remove?.();
        restoreFocus();
      }, 190);
    } else {
      overlay?.remove?.();
      restoreFocus();
    }
    openTaskId = '';
    openProjectId = '';
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

  function detailHistoryKey(pid, taskId) {
    return `${String(pid || '')}:${String(taskId || '')}`;
  }

  function rememberDetailHistory(key, metrics) {
    const value = {
      epochs: Array.isArray(metrics?.epochs) ? metrics.epochs.slice(-1000) : [],
      samples: Array.isArray(metrics?.samples) ? metrics.samples.slice(-720) : [],
    };
    detailHistoryCache.delete(key);
    detailHistoryCache.set(key, value);
    detailHistoryLoaded.add(key);
    while (detailHistoryCache.size > DETAIL_HISTORY_LIMIT) {
      const oldest = detailHistoryCache.keys().next().value;
      detailHistoryCache.delete(oldest);
      detailHistoryLoaded.delete(oldest);
    }
    return value;
  }

  function mergeDetailHistory(job, pid, taskId, historyRequested = false) {
    const key = detailHistoryKey(pid, taskId);
    const metrics = job?.runtime_metrics && typeof job.runtime_metrics === 'object' ? job.runtime_metrics : {};
    const previous = detailHistoryCache.get(key) || {epochs: [], samples: []};
    const epochs = Array.isArray(metrics.epochs) ? [...metrics.epochs] : [...previous.epochs];
    const samples = Array.isArray(metrics.samples) ? [...metrics.samples] : [...previous.samples];
    const latestEpoch = metrics.latest_epoch;
    if (latestEpoch && latestEpoch.epoch != null) {
      const index = epochs.findIndex(row => Number(row?.epoch) === Number(latestEpoch.epoch));
      if (index >= 0) epochs[index] = latestEpoch;
      else epochs.push(latestEpoch);
    }
    const latestSample = metrics.latest;
    if (latestSample?.sampled_at) {
      const index = samples.findIndex(row => String(row?.sampled_at || '') === String(latestSample.sampled_at));
      if (index >= 0) samples[index] = latestSample;
      else samples.push(latestSample);
    }
    if (historyRequested || detailHistoryLoaded.has(key)) rememberDetailHistory(key, {epochs, samples});
    return {...job, runtime_metrics: {...metrics, epochs: epochs.slice(-1000), samples: samples.slice(-720)}};
  }

  async function readJob(taskId, {includeHistory = false} = {}) {
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目不可用');
    const query = includeHistory ? '?include_history=true' : '';
    const response = await nativeFetch(`/api/projects/${encodeURIComponent(pid)}/jobs/${encodeURIComponent(taskId)}${query}`, {headers: {'Accept': 'application/json'}});
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

  async function readInputIssues(taskId, page = 1) {
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目不可用');
    const boundedPage = Math.max(1, Number(page || 1));
    const response = await nativeFetch(`/api/v62/projects/${encodeURIComponent(pid)}/training-tasks/${encodeURIComponent(taskId)}/input-issues?page=${encodeURIComponent(boundedPage)}&limit=100`, {
      headers: {'Accept': 'application/json'},
    });
    if (response.status === 404) return null;
    return json(response, '读取训练输入异常证据失败');
  }

  async function loadInputIssuePage(page) {
    const taskId = openTaskId;
    if (!taskId) return false;
    const inputIssues = await readInputIssues(taskId, page);
    if (!openSnapshot || String(openTaskId) !== String(taskId)) return false;
    openSnapshot = {...openSnapshot, inputIssues};
    renderOpenDetail(openSnapshot.job, openSnapshot.recovery, openSnapshot.log || '');
    return true;
  }

  function activateTrainingTab(key, {focus = false, root = null} = {}) {
    const overlay = root || doc?.querySelector?.('[data-training-recovery-overlay]');
    if (!overlay || !['curves', 'resources', 'data', 'diagnostics'].includes(key)) return false;
    activeTab = key;
    openFocus = key === 'diagnostics' ? openFocus : 'overview';
    overlay.querySelectorAll?.('[data-training-panel]').forEach(node => {
      node.hidden = node.dataset.trainingPanel !== activeTab;
    });
    overlay.querySelectorAll?.('[data-training-tab]').forEach(node => {
      const selected = node.dataset.trainingTab === activeTab;
      node.setAttribute('aria-selected', String(selected));
      node.setAttribute('tabindex', selected ? '0' : '-1');
      if (selected && focus) node.focus?.();
    });
    const historyKey = detailHistoryKey(openProjectId, openTaskId);
    if ((key === 'curves' || key === 'resources') && !detailHistoryLoaded.has(historyKey)) {
      void refreshOpenDetail().catch(error => notify?.(`训练详情刷新失败：${error?.message || error}`));
    }
    return true;
  }

  function renderOpenDetail(job, recovery = {}, log = '', focus = openFocus) {
    if (!openTaskId || String(job?.id || job?.task_id || '') !== String(openTaskId)) return false;
    if (String(projectId?.() || '') !== openProjectId) { closeDetail(); return false; }
    const old = doc?.querySelector?.('[data-training-recovery-overlay]');
    const oldDialog = old?.querySelector?.('.training-recovery-dialog');
    const scrollTop = Number(oldDialog?.scrollTop || 0);
    const logOpen = old?.querySelector?.('[data-training-tech-log]')?.open === true || focus === 'log';
    const focusedTab = old?.querySelector?.('[data-training-tab]:focus')?.dataset?.trainingTab || '';
    const host = doc?.createElement?.('div');
    if (!host) return false;
    host.innerHTML = detailHtml(job, recovery, log, openSnapshot?.inputIssues || null, activeTab, workspace, openProjectId);
    const nextOverlay = host.firstElementChild;
    if (!nextOverlay) return false;
    const nextDialog = nextOverlay.querySelector?.('.training-recovery-dialog');
    let overlay = nextOverlay;
    let dialog = nextDialog;
    if (old && oldDialog && nextDialog) {
      if (!patchTrainingDetailDom(oldDialog, nextDialog)) oldDialog.innerHTML = nextDialog.innerHTML;
      overlay = old;
      dialog = oldDialog;
    } else {
      old?.remove?.();
      doc.body?.appendChild(nextOverlay);
      nextOverlay.classList?.add?.('is-opening');
      window.requestAnimationFrame?.(() => nextOverlay.classList?.remove?.('is-opening'));
    }
    void mountReportCharts(overlay,job?.runtime_metrics?.epochs||job?.training_report?.history||[],trainingRecoveryDetailModel(job,recovery).resourceSamples||[]);
    if (dialog) dialog.scrollTop = scrollTop;
    const logs = overlay.querySelector?.('[data-training-tech-log]');
    if (logs) logs.open = logOpen;
    if (focus === 'log') activeTab = 'diagnostics';
    activateTrainingTab(activeTab, {focus: Boolean(focusedTab), root: overlay});
    const inputIssues = openSnapshot?.inputIssues;
    const paginationRoot = overlay.querySelector?.('[data-training-input-pagination]');
    if (paginationRoot && inputIssues) {
      window.PlatformCore?.pagination?.mountPagination?.(
        paginationRoot,
        {
          page: Number(inputIssues.page || 1),
          pageSize: Number(inputIssues.limit || 100),
          total: Number(inputIssues.issue_count || 0),
          totalPages: Number(inputIssues.total_pages || 1),
        },
        {
          label: '训练输入标签适配问题分页',
          onPageChange: loadInputIssuePage,
        },
      );
    }
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
    const requestedProject = openProjectId;
    if (!taskId) return false;
    if (detailRefreshPromise) return detailRefreshPromise;
    detailRefreshPromise = (async () => {
      const cached = (state().jobs || []).find(item => String(item?.id || item?.task_id || '') === String(taskId)) || openSnapshot?.job || {};
      const historyKey = detailHistoryKey(requestedProject, taskId);
      const includeHistory = (activeTab === 'curves' || activeTab === 'resources') && !detailHistoryLoaded.has(historyKey);
      const recoveryPromise = includeRecovery
        ? readRecovery(taskId)
        : Promise.resolve(openSnapshot?.recovery || cached?.recovery || {});
      const inputIssuesPromise = FAILED_TASK_STATUSES.has(canonicalTaskStatus(cached))
        ? readInputIssues(taskId, openSnapshot?.inputIssues?.page || 1).catch(() => openSnapshot?.inputIssues || null)
        : Promise.resolve(null);
      const [rawJob, recovery, log, inputIssues] = await Promise.all([
        readJob(taskId, {includeHistory}).catch(() => cached),
        recoveryPromise.catch(() => openSnapshot?.recovery || cached?.recovery || {}),
        readLog(taskId).catch(() => openSnapshot?.log || ''),
        inputIssuesPromise,
      ]);
      if (String(openTaskId) !== String(taskId) || requestedProject !== openProjectId || String(projectId?.() || '') !== requestedProject) return false;
      const job = mergeDetailHistory(rawJob, requestedProject, taskId, includeHistory);
      const flags = taskStatusFlags(job);
      const effectiveRecovery = flags.success ? {} : recovery;
      openSnapshot = {job, recovery: effectiveRecovery, log, inputIssues};
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
    if (detailCloseTimer !== null) {
      window.clearTimeout?.(detailCloseTimer);
      detailCloseTimer = null;
      doc?.querySelector?.('[data-training-recovery-overlay]')?.classList?.remove?.('is-closing');
    }
    if (!openTaskId && !previouslyFocusedElement) previouslyFocusedElement = doc?.activeElement || null;
    openTaskId = String(taskId);
    detailSession++;
    workspaceReadPromise = null;
    workspace = !isCanonicalTaskActive(job) ? {loading:true} : null;
    openProjectId = String(projectId?.() || '');
    if (detailHistoryProjectId && detailHistoryProjectId !== openProjectId) {
      detailHistoryCache.clear();
      detailHistoryLoaded.clear();
    }
    detailHistoryProjectId = openProjectId;
    activeTab = options?.focus === 'log' ? 'diagnostics' : 'curves';
    openFocus = options?.focus === 'log' ? 'log' : 'overview';
    const hydratedJob = mergeDetailHistory(job, openProjectId, openTaskId, false);
    openSnapshot = {job: hydratedJob, recovery: job?.recovery || {}, log: '', inputIssues: null};
    renderOpenDetail(hydratedJob, openSnapshot.recovery, '', openFocus);
    doc?.querySelector?.('[data-training-recovery-close]')?.focus?.({preventScroll: true});
    try {
      await Promise.all([refreshOpenDetail({includeRecovery: FAILED_TASK_STATUSES.has(canonicalTaskStatus(job))}), refreshWorkspace()]);
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

  function workspaceContext() {
    const project = openProjectId, task = openTaskId, session = detailSession;
    return {project, task, current:()=>Boolean(task) && project === openProjectId && task === openTaskId && session === detailSession && project === String(projectId?.() || '')};
  }

  function renderWorkspace() {
    if (openSnapshot) renderOpenDetail(openSnapshot.job, openSnapshot.recovery, openSnapshot.log);
  }

  async function refreshWorkspace() {
    if (!workspace || !openTaskId) return false;
    if (workspace.busy) return false;
    if (locks.has(`workspace:${openProjectId}:${openTaskId}`)) {
      workspace = {error:'释放请求仍在处理，请稍后重新核验'}; renderWorkspace(); return false;
    }
    if (workspaceReadPromise) return workspaceReadPromise;
    const context = workspaceContext();
    workspace = {...workspace, loading:true, error:''}; renderWorkspace();
    const promise = (async()=>{
      try {
        const body = await withRequestDeadline(async signal=>json(await nativeFetch(`/api/v62/projects/${encodeURIComponent(context.project)}/training-tasks/${encodeURIComponent(context.task)}/workspace`, {signal,headers:{Accept:'application/json'}}), '读取临时空间资格失败'), {label:'临时空间核验'});
        if (!context.current()) return false;
        workspace = {truth:body.workspace};
        return true;
      } catch (error) {
        if (context.current()) workspace = {error:String(error.message || error)};
        return false;
      } finally {
        if (context.current()) {workspaceReadPromise = null; renderWorkspace();}
      }
    })();
    workspaceReadPromise = promise;
    return promise;
  }

  async function cleanupWorkspace() {
    const context = workspaceContext(), key = `workspace:${context.project}:${context.task}`;
    if (!context.current() || locks.has(key) || !trainingWorkspaceView(workspace || {}, context.project, context.task).canRelease) return false;
    const preview = workspace.truth;
    if (!window.confirm?.(`确认释放本任务临时训练空间（${bytesText(preview.temporary_logical_bytes)}）？已归档模型和报告证据会保留；释放后本次临时数据不能用于恢复。`)) return false;
    locks.add(key); workspace = {...workspace,busy:true}; renderWorkspace();
    try {
      const body = await withRequestDeadline(async signal=>json(await nativeFetch(`/api/v62/projects/${encodeURIComponent(context.project)}/training-tasks/${encodeURIComponent(context.task)}/workspace/cleanup`, {
        method:'POST',signal,headers:{'Content-Type':'application/json',Accept:'application/json'},body:JSON.stringify({confirm:'release_training_workspace',attempt:preview.attempt,snapshot_id:preview.snapshot_id}),
      }), '释放临时空间失败'), {label:'释放临时空间'});
      if (!context.current()) return false;
      if (!['deleted','already_clean'].includes(body?.workspace?.status)) throw new Error('未取得临时空间释放凭据');
      workspace = {truth:{...preview,...body.workspace}};
      notify?.('临时训练空间已释放；实际释放磁盘空间未知');
      return true;
    } catch (error) {
      if (context.current()) {
        workspace = Array.isArray(error?.detail?.blockers)
          ? {truth:{...preview,eligible:false,blockers:error.detail.blockers}}
          : {error:`释放结果尚未确认，请重新核验：${error.message || error}`};
        notify?.(trainingWorkspaceView(workspace, context.project, context.task).message);
      }
      return false;
    } finally {
      locks.delete(key);
      if (context.current()) renderWorkspace();
    }
  }

  async function openWorkspaceHistory() {
    if (!projectId?.() || typeof window.modal !== 'function') return false;
    closeDetail({immediate:true});
    window.modal('历史临时空间只读检查', '<div data-training-workspace-history aria-live="polite">正在读取…</div>', true);
    const root = [...(doc?.querySelectorAll?.('[data-training-workspace-history]') || [])].at(-1);
    if (!root) return false;
    workspaceHistory = {root, project:String(projectId()), sequence:0, loading:false, cursor:'', next:''};
    return loadWorkspaceHistoryPage('');
  }

  async function loadWorkspaceHistoryPage(after = '') {
    const history = workspaceHistory;
    if (!history || history.loading || !history.root.isConnected || history.project !== String(projectId?.() || '')) return false;
    history.loading = true;
    history.cursor = String(after);
    const sequence = ++history.sequence;
    const current = ()=>workspaceHistory === history && history.sequence === sequence && history.root.isConnected && history.project === String(projectId?.() || '');
    history.root.innerHTML = '<p>只读检查，不会删除任何文件；释放请查看对应任务详情。</p><p role="status"><i class="loading-spinner" aria-hidden="true"></i> 正在读取当前页…</p>';
    try {
      const params = new URLSearchParams({limit:'20'});
      if (after) params.set('after',after);
      const body = await withRequestDeadline(async signal=>json(await nativeFetch(`/api/v62/projects/${encodeURIComponent(history.project)}/training-tasks/workspace-history?${params}`, {signal,headers:{Accept:'application/json'}}), '读取历史临时空间失败'), {label:'历史临时空间检查'});
      if (!current()) return false;
      const rows = Array.isArray(body.items) ? body.items.slice(0,20) : [];
      history.next = String(body.next_cursor || '');
      history.root.innerHTML = `<p>只读检查，不会删除任何文件；释放请查看对应任务详情。以下为临时文件逻辑大小，实际可释放磁盘空间未知。</p><div class="table-wrap"><table class="table"><thead><tr><th>任务</th><th>状态</th><th>临时文件逻辑大小</th><th>清理资格</th></tr></thead><tbody>${rows.map(row=>{
        const blockers = Array.isArray(row.blockers) ? row.blockers : [];
        const message = row.eligible === true && Array.isArray(row.blockers) && !blockers.length ? '服务端允许清理，请进入任务详情重新核验' : blockers.length ? blockers.map(code=>WORKSPACE_BLOCKERS[code] || `未知阻塞原因（${code}）`).join('；') : '清理资格未知';
        return `<tr><td>${esc(row.task_id || '-')}</td><td>${esc(row.status || '-')}</td><td>${row.temporary_logical_bytes == null ? '未知' : esc(bytesText(row.temporary_logical_bytes))}</td><td>${esc(message)}</td></tr>`;
      }).join('') || '<tr><td colspan="4">当前页没有可核验的任务记录</td></tr>'}</tbody></table></div><div class="row end"><button class="btn" data-training-workspace-history-page="">回到首页</button><button class="btn" data-training-workspace-history-page="${esc(history.next)}" ${history.next ? '' : 'disabled'}>下一页</button></div>`;
      return true;
    } catch (error) {
      if (current()) history.root.innerHTML = `<p>只读检查结果未知：${esc(error.message || error)}</p><button class="btn" data-training-workspace-history-page="${esc(history.cursor)}">重试当前页</button>`;
      return false;
    } finally {
      if (current()) history.loading = false;
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
    const historyPage = event.target?.closest?.('[data-training-workspace-history-page]');
    if (historyPage) {event.preventDefault(); void loadWorkspaceHistoryPage(historyPage.dataset.trainingWorkspaceHistoryPage); return;}
    if (event.target?.closest?.('[data-training-workspace-history-open]')) {event.preventDefault(); void openWorkspaceHistory(); return;}
    if (event.target?.closest?.('[data-training-workspace-cleanup]')) {event.preventDefault(); void cleanupWorkspace(); return;}
    if (event.target?.closest?.('[data-training-workspace-refresh]')) {event.preventDefault(); void refreshWorkspace(); return;}
    const copyTask = event.target?.closest?.('[data-training-copy-task]');
    if (copyTask) {
      event.preventDefault();
      const value = String(copyTask.dataset.trainingCopyTask || '');
      void window.navigator?.clipboard?.writeText?.(value).then?.(
        () => notify?.('任务 ID 已复制'),
        () => notify?.(`任务 ID：${value}`),
      );
      return;
    }
    const tab = event.target?.closest?.('[data-training-tab]');
    if (tab && openSnapshot) {
      activateTrainingTab(tab.dataset.trainingTab);
      return;
    }
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
      return;
    }
    const review = event.target?.closest?.('[data-training-input-review]');
    if (review) {
      const imageId = String(review.dataset.trainingInputReview || '');
      const item = (openSnapshot?.inputIssues?.items || []).find(row => String(row?.image_id || '') === imageId);
      const s = state();
      if (item) {
        s.trainingAnnotationReviewContext = {
          imageId,
          requiredLabelCodes: [...(item.required_label_codes || [])],
          missingLabelCodes: [...(item.missing_label_codes || [])],
        };
        if (!(s.images || []).some(row => String(row?.id || '') === imageId)) {
          s.images = [...(s.images || []), {
            id: imageId,
            filename: item.filename || imageId,
            dataset_id: item.dataset_id || '',
            url: item.content_url || item.thumbnail_url || '',
            content_sha256: item.content_sha256 || '',
          }];
        }
      }
      closeDetail();
      window.openAnnotation?.(imageId);
      return;
    }
    const exclude = event.target?.closest?.('[data-training-input-exclude]');
    if (exclude) {
      const imageId = String(exclude.dataset.trainingInputExclude || '');
      window.TrainingMaterialSummaryRuntime?.excludeFromDraft?.(imageId);
      notify?.('已从当前训练草稿排除该素材');
    }
  };
  const onKeydown = event => {
    if (event.key === 'Escape' && openTaskId) {
      event.preventDefault();
      closeDetail();
      return;
    }
    const tab = event.target?.closest?.('[data-training-tab]');
    if (!tab) return;
    const tabs = Array.from(tab.closest?.('[role="tablist"]')?.querySelectorAll?.('[data-training-tab]') || []);
    const current = tabs.indexOf(tab);
    let next = current;
    if (event.key === 'ArrowRight') next = (current + 1) % tabs.length;
    else if (event.key === 'ArrowLeft') next = (current - 1 + tabs.length) % tabs.length;
    else if (event.key==='Home') next = 0;
    else if (event.key==='End') next = tabs.length - 1;
    else return;
    event.preventDefault();
    activateTrainingTab(tabs[next]?.dataset?.trainingTab, {focus: true});
  };
  doc?.addEventListener?.('click', onClick);
  doc?.addEventListener?.('keydown', onKeydown);

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
    build: 'training-recovery-runtime-4226390',
    hydrateJobs,
    openDetail,
    refreshOpenDetail,
    acceptLiveTask,
    recover,
    refreshWorkspace,
    cleanupWorkspace,
    openWorkspaceHistory,
    loadWorkspaceHistoryPage,
    closeDetail,
    destroy() {
      workspaceHistory = null;
      closeDetail({immediate: true});
      detailHistoryCache.clear();
      detailHistoryLoaded.clear();
      doc?.removeEventListener?.('click', onClick);
      doc?.removeEventListener?.('keydown', onKeydown);
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
