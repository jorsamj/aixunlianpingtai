const ACTIVE_CLEAN = new Set(['queued', 'running']);

const CLEAN_STAGE_TEXT = {
  materializing: '正在读取素材',
  analyzing: '正在分析图片',
  evaluating: '正在判断清洗规则',
  duplicate_lookup: '正在检查重复图片',
  saving_clean_result: '正在保存清洗结果',
  saving_clean_error: '正在记录异常结果',
  cleaning: '正在清洗',
  REMOTE_CLEANING_FETCHING_SELECTION: '正在读取清洗范围',
  REMOTE_CLEANING_DOWNLOADING: '正在读取对象存储素材',
  REMOTE_CLEANING_ANALYZING: '正在远程分析图片',
  REMOTE_CLEANING_PREPARING_UPLOAD: '正在整理清洗结果',
  REMOTE_CLEANING_CONFIRMING_REVIEW: '正在校验清洗结果',
};

function cleanStatusFallback(status) {
  return ({
    queued: '排队中',
    running: '清洗中',
    awaiting_confirmation: '待确认',
    done: '已完成',
    failed: '失败',
    cancelled: '已停止',
    stopped: '已停止',
  })[status] || status || '-';
}

function finiteNumber(value, fallback = 0) {
  const number = Number(value);
  return Number.isFinite(number) ? number : fallback;
}

export function isActiveCleanTask(task) {
  const status = typeof task === 'string' ? task : task?.status;
  return ACTIVE_CLEAN.has(String(status || '').toLowerCase());
}

export function cleanTaskView(task = {}) {
  const status = String(task.status || '').toLowerCase();
  const statusText = String(task.status_text || cleanStatusFallback(status));
  const percent = Math.max(0, Math.min(100, finiteNumber(task.progress, 0)));
  const processed = Math.max(0, finiteNumber(task.processed_images, 0));
  const total = Math.max(0, finiteNumber(task.total_images, 0));
  const flagged = Math.max(0, finiteNumber(task.flagged_images, 0));
  const queuePosition = Math.max(0, Math.trunc(finiteNumber(task.resource_queue_position, 0)));
  const queuePositionExact = task.resource_queue_position_exact === true;
  const waitReason = String(task.resource_wait_reason || '').trim();
  const workerId = String(task.worker_id || '').trim();
  const stage = String(task.phase || task.task_stage || task.stage || '').trim();
  const currentItem = String(task.current_item || task.current_image_id || task.current || '').trim();

  let runtimeText = '';
  if (status === 'queued') {
    const parts = [];
    if (queuePositionExact && queuePosition > 0) parts.push(`资源队列第 ${queuePosition} 位`);
    if (waitReason) parts.push(waitReason);
    runtimeText = parts.join(' · ');
  } else if (status === 'running') {
    const parts = [];
    if (CLEAN_STAGE_TEXT[stage]) parts.push(CLEAN_STAGE_TEXT[stage]);
    if (currentItem) parts.push(`当前 ${currentItem}`);
    if (workerId) parts.push(`Worker ${workerId}`);
    runtimeText = parts.join(' · ');
  }

  return {
    ...task,
    status,
    statusText,
    percent,
    processed,
    total,
    flagged,
    stage,
    currentItem,
    progressText: `${processed}/${total}`,
    runtimeText,
    active: isActiveCleanTask(status),
    // v47 maps Durable PARTIAL_SUCCESS to failed; retry ownership stays with
    // the existing MaterialBatch runtime.
    canRetry: ['failed', 'cancelled', 'stopped', 'partial_success'].includes(status),
  };
}

export function applyCleanConfirmation(materials, result) {
  const deleted = new Set((result?.deleted_images || result?.deleted_ids || []).map(String));
  const processed = new Set((result?.processed_ids || []).map(String));
  return (materials || [])
    .filter(material => !deleted.has(String(material.id)))
    .map(material => processed.has(String(material.id))
      ? {...material, processing_status: 'processed', clean_skipped: false}
      : material);
}


const CLEAN_SCOPE_DEFINITIONS = Object.freeze({
  all: Object.freeze({
    value: 'all',
    label: '全部图片',
    detail: '扫描全部正式素材状态，仅给出质量建议，不自动删除。',
  }),
  selected: Object.freeze({
    value: 'selected',
    label: '当前选中图片',
    detail: '只处理当前明确选择的图片，不扩大到其他素材。',
  }),
  labels: Object.freeze({
    value: 'labels',
    label: '选定标签',
    detail: '命中任一已选正式标签即可纳入；多个标签之间为 OR。',
  }),
});

const CLEAN_SCOPE_ORDER = Object.freeze([
  'all', 'selected', 'labels',
]);

function normalizeCleanScope(value) {
  const scope = String(value || 'all').trim().toLowerCase();
  if (!Object.hasOwn(CLEAN_SCOPE_DEFINITIONS, scope)) {
    throw new Error('未知清洗范围，请重新选择');
  }
  return scope;
}

function uniqueCleanIds(values = []) {
  return [...new Set((values || []).map(value => String(value || '').trim()).filter(Boolean))];
}

export function cleanScopeChoices({selectedCount = 0, labelCount = 0, forcedSelected = false} = {}) {
  const count = Math.max(0, Number(selectedCount || 0));
  const labels = Math.max(0, Number(labelCount || 0));
  return CLEAN_SCOPE_ORDER.map(value => ({
    ...CLEAN_SCOPE_DEFINITIONS[value],
    available: forcedSelected
      ? value === 'selected'
      : value === 'labels' ? labels > 0 : true,
    selectedCount: value === 'selected' ? count : null,
    labelCount: value === 'labels' ? labels : null,
  }));
}

export function cleanScopeSupportsAnnotationAudit(value = 'all', annotationState = 'all') {
  normalizeCleanScope(value);
  return !['unannotated', 'confirmed_empty'].includes(String(annotationState || 'all'));
}

function cleanFilters(filters = {}, annotationState = 'all') {
  const result = {};
  const query = String(filters.query || '').trim();
  const sources = uniqueCleanIds(filters.storage_source_ids || []);
  const processing = String(filters.processing_status || '').trim().toLowerCase();
  const split = String(filters.split || '').trim().toLowerCase();
  if (query) result.query = query;
  if (sources.length) result.storage_source_ids = sources;
  if (processing) result.processing_status = processing;
  if (split) result.split = split;
  if (annotationState && annotationState !== 'all') result.annotation_state = annotationState;
  return result;
}

export function cleanScopeRequest(value = 'all', selectedIds = [], {
  forcedSelected = false, labels = [], annotationState = 'all', filters = {}, selectionMode = 'explicit',
} = {}) {
  const scope = normalizeCleanScope(value);
  const ids = uniqueCleanIds(selectedIds);
  if (forcedSelected && scope !== 'selected') {
    throw new Error('本次入口已锁定为当前选中图片');
  }
  if (scope === 'selected') {
    if (selectionMode === 'filtered') {
      const normalizedFilters = cleanFilters(filters, annotationState);
      return {
        selection_mode: 'selected',
        clean_scope: annotationState === 'all' ? 'all' : annotationState,
        image_ids: [],
        selection_spec: {scope: 'FILTERED', filters: normalizedFilters},
      };
    }
    if (!ids.length) throw new Error('当前没有选中的图片');
    const selectedFilters = cleanFilters(filters, annotationState);
    const selectionSpec = {scope: 'SELECTED', image_ids: ids};
    if (Object.keys(selectedFilters).length) selectionSpec.filters = selectedFilters;
    return {selection_mode: 'selected', clean_scope: annotationState === 'all' ? 'selected' : annotationState, image_ids: ids, selection_spec: selectionSpec};
  }
  const normalizedLabels = uniqueCleanIds(labels);
  if (scope === 'labels' && !normalizedLabels.length) throw new Error('请至少选择一个标签');
  const normalizedFilters = cleanFilters(filters, annotationState);
  if (scope === 'labels') normalizedFilters.labels = normalizedLabels;
  return {
    selection_mode: scope,
    clean_scope: annotationState === 'all' ? 'all' : annotationState,
    image_ids: [],
    selection_spec: {scope: 'FILTERED', filters: normalizedFilters},
  };
}

export function cleanExecutionChoices(preflight = {}) {
  const nodes = Array.isArray(preflight.eligible_nodes) ? preflight.eligible_nodes : [];
  const agentAvailable = preflight.agent_available === true;
  const reason = String(preflight.reason || '').trim();
  return {
    defaultMode: 'local',
    local: {
      mode: 'local',
      available: true,
      label: '中央 Worker',
      detail: '使用平台当前清洗 Worker，兼容本地和对象存储素材',
    },
    agent: {
      mode: 'agent',
      available: agentAvailable,
      label: '远程清洗节点',
      detail: agentAvailable
        ? `已检测到 ${nodes.length} 个可用节点`
        : (reason || '当前没有满足条件的远程清洗节点'),
      nodes,
    },
  };
}

export function cleanExecutionMode(value, preflight = {}) {
  const mode = String(value || 'local').trim().toLowerCase();
  if (mode === 'local') return 'local';
  if (mode !== 'agent') throw new Error('不支持的清洗执行方式');
  const choices = cleanExecutionChoices(preflight);
  if (!choices.agent.available) throw new Error(choices.agent.detail);
  return 'agent';
}


export function cleanSchedulingRequest(
  {executionMode = 'local', schedulingMode = 'auto', nodeId = '', queuePolicy = 'normal'} = {},
  preflight = {},
) {
  const execution = String(executionMode || 'local').trim().toLowerCase();
  if (execution === 'local') {
    return {scheduling_mode: 'auto', target_node_id: '', queue_policy: 'normal'};
  }
  if (execution !== 'agent') throw new Error('不支持的清洗执行方式');
  if (preflight.agent_available !== true) {
    throw new Error(String(preflight.reason || '当前没有可用的远程清洗节点'));
  }
  const mode = String(schedulingMode || 'auto').trim().toLowerCase();
  const policy = String(queuePolicy || 'normal').trim().toLowerCase();
  const target = String(nodeId || '').trim();
  if (mode === 'auto') {
    return {scheduling_mode: 'auto', target_node_id: '', queue_policy: 'normal'};
  }
  if (mode !== 'node') throw new Error('未知清洗调度方式');
  const nodes = Array.isArray(preflight.eligible_nodes) ? preflight.eligible_nodes : [];
  const node = nodes.find(item => String(item?.node_id || '') === target);
  if (!node) throw new Error('请选择当前在线且已启用 cleaning 服务的节点');
  if (!['normal', 'front', 'preempt'].includes(policy)) throw new Error('未知节点队列策略');
  if (policy === 'preempt' && node.idle === true) {
    return {scheduling_mode: 'node', target_node_id: target, queue_policy: 'normal'};
  }
  if (policy === 'preempt' && node.idle === false && node.preemptible !== true) {
    throw new Error('该节点当前任务不支持安全抢占，请选择“队首等待”或其他节点');
  }
  return {scheduling_mode: 'node', target_node_id: target, queue_policy: policy};
}
