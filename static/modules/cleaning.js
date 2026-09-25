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
  annotated: Object.freeze({
    value: 'annotated',
    label: '已标注',
    detail: '仅 annotation_state=annotated；图片质量与正式标注分层处理。',
  }),
  unannotated: Object.freeze({
    value: 'unannotated',
    label: '未标注',
    detail: '只检查图片质量；没有标注框不是坏图，也不会被当作异常。',
  }),
  confirmed_empty: Object.freeze({
    value: 'confirmed_empty',
    label: '已确认无目标',
    detail: '合法负样本；图片质量通过后继续保留用于训练。',
  }),
  selected: Object.freeze({
    value: 'selected',
    label: '当前选中图片',
    detail: '只处理当前明确选择的图片，不扩大到其他素材。',
  }),
});

const CLEAN_SCOPE_ORDER = Object.freeze([
  'all', 'annotated', 'unannotated', 'confirmed_empty', 'selected',
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

export function cleanScopeChoices({selectedCount = 0, forcedSelected = false} = {}) {
  const count = Math.max(0, Number(selectedCount || 0));
  return CLEAN_SCOPE_ORDER.map(value => ({
    ...CLEAN_SCOPE_DEFINITIONS[value],
    available: forcedSelected ? value === 'selected' : value !== 'selected' || count > 0,
    selectedCount: value === 'selected' ? count : null,
  }));
}

export function cleanScopeSupportsAnnotationAudit(value = 'all') {
  const scope = normalizeCleanScope(value);
  return scope === 'all' || scope === 'annotated' || scope === 'selected';
}

export function cleanScopeRequest(value = 'all', selectedIds = [], {forcedSelected = false} = {}) {
  const scope = normalizeCleanScope(value);
  const ids = uniqueCleanIds(selectedIds);
  if (forcedSelected && scope !== 'selected') {
    throw new Error('本次入口已锁定为当前选中图片');
  }
  if (scope === 'selected') {
    if (!ids.length) throw new Error('当前没有选中的图片');
    return {clean_scope: 'selected', image_ids: ids};
  }
  return {clean_scope: scope, image_ids: []};
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
