import {canonicalTaskPhase, canonicalTaskProgressPercent, canonicalTaskStatus, trainingDisplayStatus} from './task-runtime-truth.js';

const TRAINING_PAGE = '训练任务';
const ACTIVE_STATUSES = new Set([
  'queued', 'waiting', 'pending', 'starting', 'running',
  'pausing', 'paused', 'resuming', 'stopping', 'cancel_requested',
]);
const DONE_STATUSES = new Set(['done', 'finished', 'completed', 'succeeded', 'success', 'failed', 'stopped', 'cancelled', 'canceled']);
const REFRESH_DEDUP_WINDOW_MS = 120;

const STAGE_LABELS = Object.freeze({
  queued: '排队等待',
  resource_waiting: '等待训练资源',
  device_admission: '验证训练设备',
  preparing_materials: '校验训练素材',
  materializing: '准备训练数据',
  starting_trainer: '启动训练进程',
  trainer_startup: '初始化训练环境',
  training: '训练中',
  paused: '已暂停',
  cancelling: '正在停止训练',
  cleaning_training_process: '释放训练进程资源',
  finalizing: '校验训练产物',
  final_validation: '独立验证最佳模型',
  recovering_checkpoint: '恢复并验证 Checkpoint',
  process_cleanup_blocked: '等待训练进程安全退出',
  finalizing_commit: '归档训练结果',
  committed: '训练完成',
  blocked_by_environment: '训练环境不可用',
  blocked_by_hardware: '训练硬件不可用',
  failed: '训练失败',
  cancelled: '已取消',
});

const FAILURE_STAGE_LABELS = Object.freeze({
  training_process: '训练进程失败',
  post_training: '训练结束后处理失败',
  final_validation: '最终模型验证失败',
});

function rowsFrom(body) {
  if (Array.isArray(body)) return body;
  return Array.isArray(body?.items) ? body.items : [];
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

function duration(value) {
  const total = Math.max(0, Number(value || 0));
  if (!Number.isFinite(total) || total <= 0) return '-';
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const seconds = Math.floor(total % 60);
  if (hours) return `${hours}h ${minutes}m`;
  if (minutes) return `${minutes}m ${seconds}s`;
  return `${seconds}s`;
}

function finiteNumber(value) {
  if (value === null || value === undefined || value === '') return null;
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function metricValue(values, aliases) {
  if (!values || typeof values !== 'object') return null;
  const normalized = new Map(Object.entries(values).map(([key, value]) => [String(key).toLowerCase().replace(/\s+/g, ''), value]));
  for (const alias of aliases) {
    const value = finiteNumber(normalized.get(String(alias).toLowerCase().replace(/\s+/g, '')));
    if (value !== null) return value;
  }
  return null;
}

function metricText(value, digits = 3) {
  return value === null ? '' : Number(value).toFixed(digits);
}

export function trainingProgressView(job = {}) {
  const progress = job.training_progress && typeof job.training_progress === 'object' ? job.training_progress : {};
  const epoch = finiteNumber(progress.epoch) ?? finiteNumber(job.current_epoch) ?? 0;
  const totalEpochs = finiteNumber(progress.total_epochs) ?? finiteNumber(job.total_epochs) ?? finiteNumber(job.epochs);
  const currentBatch = finiteNumber(progress.current_batch) ?? finiteNumber(job.current_batch);
  const totalBatches = finiteNumber(progress.total_batches) ?? finiteNumber(job.total_batches);
  const elapsedSeconds = finiteNumber(progress.elapsed_seconds) ?? finiteNumber(job.elapsed_seconds);
  const etaSeconds = finiteNumber(progress.eta_seconds) ?? finiteNumber(job.eta_seconds);
  const throughput = finiteNumber(progress.images_per_second);
  const losses = progress.losses || {};
  const metrics = progress.metrics || {};
  const learningRates = progress.learning_rates || {};
  const boxLoss = metricValue(losses, ['box_loss', 'train/box_loss']);
  const clsLoss = metricValue(losses, ['cls_loss', 'train/cls_loss']);
  const dflLoss = metricValue(losses, ['dfl_loss', 'train/dfl_loss']);
  const map50 = metricValue(metrics, ['metrics/map50(b)', 'metrics/map50', 'map50']);
  const map5095 = metricValue(metrics, ['metrics/map50-95(b)', 'metrics/map50-95', 'map50-95', 'map']);
  const precision = metricValue(metrics, ['metrics/precision(b)', 'precision']);
  const recall = metricValue(metrics, ['metrics/recall(b)', 'recall']);
  const primaryLr = Object.values(learningRates).map(finiteNumber).find(value => value !== null) ?? null;
  const parts = [];
  if (precision !== null) parts.push(`Precision ${metricText(precision)}`);
  if (recall !== null) parts.push(`Recall ${metricText(recall)}`);
  if (map50 !== null) parts.push(`mAP50 ${metricText(map50)}`);
  if (map5095 !== null) parts.push(`mAP50-95 ${metricText(map5095)}`);
  if (boxLoss !== null) parts.push(`box loss ${metricText(boxLoss, 4)}`);
  if (clsLoss !== null) parts.push(`cls loss ${metricText(clsLoss, 4)}`);
  if (dflLoss !== null) parts.push(`dfl loss ${metricText(dflLoss, 4)}`);
  if (throughput !== null) parts.push(`${metricText(throughput, 1)} img/s`);
  if (primaryLr !== null) parts.push(`LR ${Number(primaryLr).toPrecision(3)}`);
  return {epoch, totalEpochs, currentBatch, totalBatches, elapsedSeconds, etaSeconds, metricLine: parts.join(' · ')};
}

function dateText(value) {
  if (!value) return '-';
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 19);
}

function statusText(status) {
  return ({
    queued: '排队中', waiting: '等待资源', pending: '等待中', starting: '启动中',
    running: '训练中', pausing: '暂停中', paused: '已暂停', resuming: '恢复中',
    stopping: '停止中', cancel_requested: '取消中',
    done: '已完成', finished: '已完成', completed: '已完成', succeeded: '已完成', success: '已完成',
    failed: '失败', stopped: '已停止', cancelled: '已取消', canceled: '已取消',
  })[status] || status || '-';
}

function statusClass(status) {
  if (['done', 'finished', 'completed', 'succeeded', 'success'].includes(status)) return 'ok';
  if (['failed', 'stopped', 'cancelled', 'canceled'].includes(status)) return 'err';
  if (['running', 'queued', 'waiting', 'pending', 'starting', 'pausing', 'paused', 'resuming', 'stopping', 'cancel_requested'].includes(status)) return 'warn';
  return '';
}

function resourceName(job) {
  return job?.execution_resource?.name
    || job?.resource_name
    || job?.server_name
    || job?.resource_key
    || '-';
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
  if (position > 0 && job?.resource_queue_position_exact === true) {
    parts.push(`队列第 ${position} 位`);
  } else {
    parts.push('排队中');
    if (position > 0) {
      const ahead = Math.max(0, position - 1);
      parts.push(ahead > 0 ? `前方约 ${ahead} 个候选任务（动态）` : '当前处于资源候选首位（动态）');
    }
  }
  return parts.join(' · ');
}

function workerRuntimeMeta(job) {
  const worker = String(job?.task_worker_id || '').trim();
  return worker ? `执行节点 ${worker}` : '';
}

export function trainingStageView(job = {}) {
  const status = trainingDisplayStatus(job);
  const stage = canonicalTaskPhase(job);
  const currentItem = String(job?.current_item || '').trim();
  const message = String(job?.message || '').trim();
  let label = STAGE_LABELS[stage] || '';
  let detail = currentItem;

  if (status === 'waiting') label = '等待训练资源';
  else if (status === 'queued' && !label) label = '排队等待';
  else if (status === 'paused') label = '已暂停';

  if (stage === 'trainer_startup') {
    const actualDevice = String(job?.actual_device || '').trim();
    const resolved = job?.resolved_resources && typeof job.resolved_resources === 'object';
    if (!actualDevice) label = '验证训练设备';
    else if (!resolved) label = '加载训练模型';
    else label = '初始化训练器与数据加载器';
    if (message && !/^训练中\b/.test(message)) detail = message;
  }

  if (!label) {
    if (status === 'running') label = '运行中';
    else if (status === 'pending') label = '等待中';
    else label = statusText(status);
  }

  if (detail === label) detail = '';
  return {stage, label, detail};
}

function completionRuntimeMeta(job, progress) {
  if (!['done', 'finished', 'completed', 'succeeded', 'success'].includes(String(job?.status || '').toLowerCase())) return '';
  const completed = finiteNumber(progress?.epoch);
  const requested = finiteNumber(progress?.totalEpochs);
  if (!(completed > 0 && requested > 0 && completed < requested)) return '';
  const outcome = String(job?.training_outcome || '').trim();
  const reason = String(job?.completion_reason || '').trim();
  if (outcome === 'target_reached' || reason === 'quality_target_reached') return '达到质量目标，提前完成';
  if (outcome === 'needs_optimization' || reason === 'quality_gate_below_continue_threshold') return '提前结束（需继续优化）';
  if (reason === 'early_stopping') {
    const patience = finiteNumber(job?.early_stopping_patience);
    if (String(job?.early_stopping_reason || '') === 'patience' && patience !== null && patience > 0) {
      return `连续 ${Math.round(patience)} Epoch 无提升，Early Stopping`;
    }
    return 'Early Stopping，提前完成';
  }
  return '提前完成';
}

function terminalRuntimeMeta(job, stage) {
  const status = trainingDisplayStatus(job);
  if (['done', 'finished', 'completed', 'succeeded', 'success'].includes(status)) return '';
  if (!DONE_STATUSES.has(status)) return '';

  const taskStatus = canonicalTaskStatus(job);
  const failureStage = String(job?.failure_stage || '').trim().toLowerCase();
  let label = '';
  if (taskStatus === 'BLOCKED_BY_ENVIRONMENT') label = '训练环境不可用';
  else if (taskStatus === 'BLOCKED_BY_HARDWARE') label = '训练硬件不可用';
  else if (status === 'cancelled' || status === 'canceled') label = '已取消';
  else if (status === 'stopped') label = '已停止';
  else if (status === 'failed') label = FAILURE_STAGE_LABELS[failureStage] || stage.label || '训练失败';
  else label = stage.label || statusText(status);

  const reason = String(job?.current_item || job?.message || job?.error || '').trim();
  if (!reason || reason === label) return label;
  return `${label} · ${reason}`;
}

function actions(job) {
  const id = esc(job.id);
  const status = trainingDisplayStatus(job);
  const detail = `<button class="btn mini" onclick="openTrainingRecoveryDetail('${id}')">详情</button>`;
  const log = `<button class="btn mini" onclick="showTrainLog423('${id}')">日志</button>`;
  if (['starting', 'pausing', 'resuming', 'stopping', 'cancel_requested'].includes(status)) return `${detail}${log}<span class="train428-action-lock">状态切换中</span>`;
  if (status === 'queued' || status === 'waiting' || status === 'pending') return `${detail}${log}<button class="btn mini" onclick="promoteTrain428('${id}')">插队</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  if (status === 'running') return `${detail}${log}<button class="btn mini" onclick="pauseTrain428('${id}')">暂停</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  if (status === 'paused') return `${detail}${log}<button class="btn mini primary" onclick="resumeTrain428('${id}')">继续</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  return `${detail}${log}${job.auto_version_id ? `<button class="btn mini primary" onclick="trainingReport425('${id}')">训练报告</button>` : ''}<button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
}

export function trainingTaskRow(job) {
  const status = trainingDisplayStatus(job);
  const percent = canonicalTaskProgressPercent(job);
  const progress = trainingProgressView(job);
  const totalEpochs = progress.totalEpochs ?? '-';
  const queueMeta = queueRuntimeMeta(job);
  const workerMeta = workerRuntimeMeta(job);
  const completionMeta = completionRuntimeMeta(job, progress);
  const stage = trainingStageView(job);
  const done = DONE_STATUSES.has(status);
  const successful = ['done', 'finished', 'completed', 'succeeded', 'success'].includes(status);
  const terminalMeta = terminalRuntimeMeta(job, stage);
  const epochStarted = Number(progress.epoch || 0) > 0;
  const recoveryMeta = job?.recovery?.available === true ? '可恢复 · Checkpoint 已保留' : '';
  const progressParts = [];

  if (completionMeta) progressParts.push(completionMeta);
  if (done && !successful) {
    if (terminalMeta) progressParts.push(terminalMeta);
    if (epochStarted) {
      progressParts.push(`Epoch ${progress.epoch}/${totalEpochs}`);
      if (progress.currentBatch !== null && progress.currentBatch !== undefined && progress.totalBatches) {
        progressParts.push(`Batch ${progress.currentBatch}/${progress.totalBatches}`);
      }
    }
    progressParts.push(`${percent.toFixed(0)}%`);
  } else if (epochStarted) {
    progressParts.push(`Epoch ${progress.epoch}/${totalEpochs}`);
    if (progress.currentBatch !== null && progress.currentBatch !== undefined && progress.totalBatches) {
      progressParts.push(`Batch ${progress.currentBatch}/${progress.totalBatches}`);
    }
    progressParts.push(`${percent.toFixed(0)}%`);
    const item = String(job?.current_item || '').trim();
    if (item && item !== String(progress.epoch) && !item.includes(`Epoch ${progress.epoch}/${totalEpochs}`)) progressParts.push(item);
  } else if (done) {
    progressParts.push(`${percent.toFixed(0)}%`);
  } else {
    progressParts.push(stage.label);
    progressParts.push(`${percent.toFixed(0)}%`);
    if (stage.detail) progressParts.push(stage.detail);
  }

  const algorithmName = job.asset_algorithm_name || job.algorithm_name || job.asset_algorithm_id || job.algorithm_asset_id || '-';
  const taskName = job.task_name || job.run_name || job.auto_version_name || job.id;
  const framework = job.framework === 'paddle' ? 'PaddleDetection' : 'Ultralytics / YOLO';
  const priorityMeta = [`优先级 ${priorityValue(job)}`, queueMeta, recoveryMeta].filter(Boolean).join(' · ');
  const stageMeta = [stage.label, stage.detail].filter(Boolean).filter((value, index, values) => values.indexOf(value) === index).join(' · ');
  const progressScale = Math.max(0, Math.min(100, percent)) / 100;
  return `<tr data-job-id="${esc(job.id)}"><td><div class="train428-taskname"><b>${esc(algorithmName)}</b><span>${esc(job.asset_algorithm_id || job.algorithm_asset_id || '')}</span></div></td><td><div class="train428-taskname"><b>${esc(taskName)}</b><span>${esc(job.id)}</span>${job.auto_version_name && taskName !== job.auto_version_name ? `<em>版本 ${esc(job.auto_version_name)}</em>` : ''}</div></td><td><span class="pill ${statusClass(status)}">${esc(statusText(status))}</span></td><td><div class="train428-priority"><b>${priorityValue(job)}</b><small>${esc(priorityMeta)}</small></div></td><td><div class="train428-resource"><b>${esc(framework)}</b><span>${esc(resourceName(job))}</span>${workerMeta ? `<span>${esc(workerMeta)}</span>` : ''}</div></td><td><div class="progress424"><i data-progress="${percent.toFixed(2)}" style="transform:scaleX(${progressScale.toFixed(4)})"></i></div><span class="train428-progress-txt">${esc(progressParts.join(' · '))}</span>${progress.metricLine ? `<small class="train428-metrics">${esc(progress.metricLine)}</small>` : ''}</td><td>${esc(duration(progress.elapsedSeconds))}</td><td>${esc(duration(progress.etaSeconds))}</td><td><div class="train428-stage"><b>${esc(stage.label)}</b>${stageMeta && stageMeta !== stage.label ? `<small>${esc(stageMeta)}</small>` : ''}${terminalMeta && !successful ? `<small class="err">${esc(terminalMeta)}</small>` : ''}</div></td><td>${esc(dateText(job.started_at || job.created_at))}</td><td><div class="row wrap train428-actions-cell">${actions(job)}</div></td></tr>`;
}

export function visibleTrainingJobs(jobs, tab = 'active') {
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
    if (['queued', 'waiting'].includes(aStatus)) {
      const sameResource = String(a?.resource_key || '') === String(b?.resource_key || '');
      const aPosition = Number(a?.resource_queue_position), bPosition = Number(b?.resource_queue_position);
      const hasExactPosition = sameResource
        && a?.resource_queue_position_exact === true
        && b?.resource_queue_position_exact === true
        && Number.isFinite(aPosition) && aPosition > 0
        && Number.isFinite(bPosition) && bPosition > 0;
      if (hasExactPosition && aPosition !== bPosition) return aPosition - bPosition;
      const priority = priorityValue(a) - priorityValue(b);
      if (priority) return priority;
      const aRank = Number(a?.queue_rank), bRank = Number(b?.queue_rank);
      const hasDurableRank = Number.isFinite(aRank) && Number.isFinite(bRank) && (aRank !== 0 || bRank !== 0);
      if (hasDurableRank && aRank !== bRank) return bRank - aRank;
      const aLegacy = Number(a?.priority_tiebreaker), bLegacy = Number(b?.priority_tiebreaker);
      const hasLegacyTie = Number.isFinite(aLegacy) && Number.isFinite(bLegacy) && (aLegacy !== 0 || bLegacy !== 0);
      if (hasLegacyTie && aLegacy !== bLegacy) return aLegacy - bLegacy;
      const aTime = Date.parse(a?.queued_at || a?.created_at || '');
      const bTime = Date.parse(b?.queued_at || b?.created_at || '');
      if (Number.isFinite(aTime) && Number.isFinite(bTime) && aTime !== bTime) return aTime - bTime;
      return String(a?.queued_at || a?.created_at || '').localeCompare(String(b?.queued_at || b?.created_at || ''))
        || String(a?.id || '').localeCompare(String(b?.id || ''));
    }
    return String(b.started_at || b.created_at || '').localeCompare(String(a.started_at || a.created_at || ''));
  });
}

async function responseError(response, fallback = '操作失败') {
  if (response?.ok) return null;
  const raw = await response?.text?.() || '';
  let body = {};
  try { body = JSON.parse(raw); } catch (_) { body = {detail: raw}; }
  return new Error(String(body.message || body.detail || `${fallback}（HTTP ${response?.status || '-'}）`));
}

async function jsonResponse(response) {
  const error = await responseError(response, '刷新失败');
  if (error) throw error;
  return response.json();
}

export function installTrainingTaskRuntime({getState, projectId, notify, fetchImpl, recoveryRuntime} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingTaskRuntimeInstalled) return window.TrainingTaskRuntime;

  const doc = typeof document !== 'undefined' ? document : null;
  const state = () => getState?.() || {};
  const nativeFetch = fetchImpl
    || window.fetch?.__pageRequestScopeOriginal
    || (typeof window.fetch === 'function' ? window.fetch.bind(window) : null);
  if (typeof nativeFetch !== 'function') return null;

  const previous = {
    refreshJobsOnly: window.refreshJobsOnly,
    refreshTrainPage428: window.refreshTrainPage428,
    refreshTrain423: window.refreshTrain423,
    promoteTrain428: window.promoteTrain428,
    pauseTrain428: window.pauseTrain428,
    resumeTrain428: window.resumeTrain428,
    stopTrain428: window.stopTrain428,
    deleteTrain428: window.deleteTrain428,
  };
  const mutationLocks = new Set();
  let inflight = null;
  let destroyed = false;
  let lastRefreshAt = 0;
  let lastRefreshSource = '';

  function isCurrent(startPage, startEpoch) {
    const s = state();
    return !destroyed
      && String(s.page || '') === startPage
      && Number(s.__navigationEpoch || 0) === startEpoch;
  }

  function patchFinalTrainingTable() {
    if (!doc || String(state().page || '') !== TRAINING_PAGE) return false;
    const root = doc.querySelector?.('.train428-page');
    const body = root?.querySelector?.('.train428-table tbody');
    if (!root || !body) {
      if (typeof window.updateTrainingJobTable === 'function') {
        window.updateTrainingJobTable();
        return true;
      }
      return false;
    }
    const jobs = state().jobs || [];
    const active = jobs.filter(job => ACTIVE_STATUSES.has(trainingDisplayStatus(job)));
    const history = jobs.filter(job => {
      const status = trainingDisplayStatus(job);
      return DONE_STATUSES.has(status) || !ACTIVE_STATUSES.has(status);
    });
    const buttons = root.querySelectorAll?.('.train428-tabs button') || [];
    const activeCount = buttons[0]?.querySelector?.('span');
    const historyCount = buttons[1]?.querySelector?.('span');
    if (activeCount) activeCount.textContent = String(active.length);
    if (historyCount) historyCount.textContent = String(history.length);
    const visible = visibleTrainingJobs(jobs, state().train428Tab || 'active');
    body.innerHTML = visible.map(trainingTaskRow).join('') || '<tr><td colspan="11" class="empty-row">暂无记录</td></tr>';
    return true;
  }

  function acceptCreatedTask(task, {algorithmId = '', framework = '', queuePriority = 50} = {}) {
    const taskId = String(task?.task_id || '').trim();
    if (!taskId) throw new Error('训练任务响应缺少 task_id');
    const status = String(task?.status || task?.persisted_status || 'QUEUED').trim().toLowerCase();
    const row = {
      ...task,
      id: taskId,
      task_id: taskId,
      status,
      task_status: String(task?.status || '').trim().toUpperCase(),
      asset_algorithm_id: String(algorithmId || task?.asset_algorithm_id || ''),
      algorithm_asset_id: String(algorithmId || task?.algorithm_asset_id || ''),
      framework: String(framework || task?.framework || ''),
      queue_priority: Number(task?.priority ?? queuePriority ?? 50),
      priority_scheme: 'lower_number_first',
      created_at: task?.created_at || new Date().toISOString(),
      updated_at: task?.updated_at || task?.created_at || new Date().toISOString(),
    };
    const current = Array.isArray(state().jobs) ? state().jobs : [];
    state().jobs = [row, ...current.filter(item => String(item?.id || item?.task_id || '') !== taskId)];
    if (String(state().page || '') === TRAINING_PAGE) patchFinalTrainingTable();
    return row;
  }

  async function refresh({render = true, force = false, source = 'direct'} = {}) {
    if (destroyed) throw new Error('训练任务模块已销毁');
    if (inflight) return inflight;
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目不可用，请刷新页面后重试');

    const startPage = String(state().page || '');
    const startEpoch = Number(state().__navigationEpoch || 0);
    const age = Date.now() - lastRefreshAt;
    const crossSourceDuplicate = (source === 'manual' && lastRefreshSource === 'poll')
      || (source === 'poll' && lastRefreshSource === 'manual');
    if (!force
        && startPage === TRAINING_PAGE
        && lastRefreshAt > 0
        && age >= 0
        && age <= REFRESH_DEDUP_WINDOW_MS
        && crossSourceDuplicate) {
      if (render) patchFinalTrainingTable();
      return {stale: false, jobs: state().jobs || [], reused: true};
    }
    const encoded = encodeURIComponent(pid);

    inflight = (async () => {
      const response = await nativeFetch(`/api/projects/${encoded}/jobs`, {
        headers: {'Accept': 'application/json'},
      });
      const body = await jsonResponse(response);
      let jobs = rowsFrom(body);
      if (recoveryRuntime?.hydrateJobs) jobs = await recoveryRuntime.hydrateJobs(jobs);
      if (!isCurrent(startPage, startEpoch) || startPage !== TRAINING_PAGE) {
        return {stale: true, jobs: state().jobs || []};
      }
      state().jobs = jobs;
      lastRefreshAt = Date.now();
      lastRefreshSource = String(source || 'direct');
      if (render) patchFinalTrainingTable();
      return {stale: false, jobs};
    })();

    try {
      return await inflight;
    } finally {
      inflight = null;
    }
  }

  async function refreshAfterMutation() {
    if (inflight) {
      try { await inflight; } catch (_) {}
    }
    if (String(state().page || '') !== TRAINING_PAGE) return {stale: true, jobs: state().jobs || []};
    return refresh({render: true, force: true, source: 'mutation'});
  }

  async function mutate(key, path, {method = 'POST', successMessage = '操作成功'} = {}) {
    if (mutationLocks.has(key)) return false;
    mutationLocks.add(key);
    try {
      const response = await nativeFetch(path, {method});
      const error = await responseError(response);
      if (error) throw error;
      let refreshError = null;
      try { await refreshAfterMutation(); } catch (errorAfterMutation) { refreshError = errorAfterMutation; }
      notify?.(refreshError ? `${successMessage}，但列表刷新失败：${refreshError.message || refreshError}` : successMessage);
      return true;
    } catch (error) {
      notify?.(error?.message || error);
      return false;
    } finally {
      mutationLocks.delete(key);
    }
  }

  const focusedRefresh = () => refresh({render: true, source: 'poll'});
  focusedRefresh.__trainingTaskRuntime = true;
  window.refreshJobsOnly = focusedRefresh;
  window.refreshTrainPage428 = focusedRefresh;
  window.refreshTrain423 = focusedRefresh;

  window.promoteTrain428 = id => mutate(
    `promote:${id}`,
    `/api/v48/projects/${encodeURIComponent(projectId?.() || '')}/jobs/${encodeURIComponent(id)}/promote`,
    {successMessage: '任务已插到当前资源队列最前'},
  );
  window.pauseTrain428 = id => mutate(
    `pause:${id}`,
    `/api/v48/projects/${encodeURIComponent(projectId?.() || '')}/jobs/${encodeURIComponent(id)}/pause`,
    {successMessage: '训练已暂停'},
  );
  window.resumeTrain428 = id => mutate(
    `resume:${id}`,
    `/api/v48/projects/${encodeURIComponent(projectId?.() || '')}/jobs/${encodeURIComponent(id)}/resume`,
    {successMessage: '训练已继续'},
  );
  window.stopTrain428 = async id => {
    if (typeof window.confirm === 'function' && !window.confirm('确认停止这个训练任务？排队任务会直接取消；已开始任务仅在存在可校验训练成果时归档算法版本。')) return false;
    return mutate(
      `stop:${id}`,
      `/api/v48/projects/${encodeURIComponent(projectId?.() || '')}/jobs/${encodeURIComponent(id)}/stop`,
      {successMessage: '训练已停止'},
    );
  };
  window.deleteTrain428 = async id => {
    if (typeof window.confirm === 'function' && !window.confirm('确认删除这条训练任务记录？已经生成的算法版本不会删除。')) return false;
    const key = `delete:${id}`;
    if (mutationLocks.has(key)) return false;
    mutationLocks.add(key);
    try {
      const pid = encodeURIComponent(projectId?.() || '');
      const encodedId = encodeURIComponent(id);
      const job = (state().jobs || []).find(item => String(item.id) === String(id));
      if (job && ['running', 'paused', 'queued', 'waiting'].includes(trainingDisplayStatus(job))) {
        const stopResponse = await nativeFetch(`/api/v48/projects/${pid}/jobs/${encodedId}/stop`, {method: 'POST'});
        const stopError = await responseError(stopResponse, '停止训练失败');
        if (stopError) throw stopError;
      }
      const deleteResponse = await nativeFetch(`/api/v12/projects/${pid}/jobs/${encodedId}`, {method: 'DELETE'});
      const deleteError = await responseError(deleteResponse, '删除任务失败');
      if (deleteError) throw deleteError;
      let refreshError = null;
      try { await refreshAfterMutation(); } catch (errorAfterMutation) { refreshError = errorAfterMutation; }
      notify?.(refreshError ? `任务记录已删除，但列表刷新失败：${refreshError.message || refreshError}` : '任务记录已删除');
      return true;
    } catch (error) {
      notify?.(error?.message || error);
      return false;
    } finally {
      mutationLocks.delete(key);
    }
  };

  for (const name of ['promoteTrain428', 'pauseTrain428', 'resumeTrain428', 'stopTrain428', 'deleteTrain428']) {
    if (typeof window[name] === 'function') window[name].__trainingTaskRuntime = true;
  }

  function isOwnedRefreshButton(button) {
    if (!button || String(state().page || '') !== TRAINING_PAGE) return false;
    if (button.id === 'refreshBtn') return true;
    if (!button.closest?.('#view')) return false;
    const label = String(button.textContent || '').trim();
    return label === '刷新状态' || label === '完整刷新' || label === '刷新';
  }

  const onClickCapture = event => {
    const button = event?.target?.closest?.('button');
    if (!isOwnedRefreshButton(button)) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (button.disabled || inflight) return;
    button.disabled = true;
    void refresh({render: true, source: 'manual'}).then(
      result => { if (!result?.stale) notify?.('训练任务已刷新'); },
      error => notify?.(error?.message || error),
    ).finally(() => {
      if (button?.isConnected !== false) button.disabled = false;
      window.PollRegistryRuntime?.replaceTrainingJobTimer?.();
    });
  };
  doc?.addEventListener?.('click', onClickCapture, true);

  const runtime = {
    build: 'training-task-runtime-422506',
    refresh,
    acceptCreatedTask,
    patch: patchFinalTrainingTable,
    state() {
      return {inflight: Boolean(inflight), lastRefreshAt, lastRefreshSource, mutations: mutationLocks.size};
    },
    destroy() {
      destroyed = true;
      doc?.removeEventListener?.('click', onClickCapture, true);
      for (const [name, fn] of Object.entries(previous)) {
        if (fn === undefined) delete window[name];
        else window[name] = fn;
      }
      if (window.TrainingTaskRuntime === runtime) window.TrainingTaskRuntime = null;
      window.__trainingTaskRuntimeInstalled = false;
    },
  };

  window.TrainingTaskRuntime = runtime;
  window.__trainingTaskRuntimeInstalled = true;
  return runtime;
}
