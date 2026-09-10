const STORAGE_KEY = 'aixunlian.material-batches.v62';
const ACTIVE = new Set(['QUEUED', 'RUNNING', 'CANCEL_REQUESTED']);

async function json(response) {
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch (_error) { body = {detail: text}; }
  if (response.ok) return body;
  const detail = body?.detail;
  const message = detail?.message || body?.message || (typeof detail === 'string' ? detail : '') || `HTTP ${response.status}`;
  const error = new Error(message);
  error.code = detail?.code || body?.code || `HTTP_${response.status}`;
  throw error;
}

function saved() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch (_error) { return {}; }
}

function save(items) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

export function installMaterialBatchRuntime({projectId, currentPageIds, selectedIds, filteredSpec, notify, refresh} = {}) {
  if (typeof window === 'undefined' || window.__materialBatchRuntime62Installed) return false;
  window.__materialBatchRuntime62Installed = true;
  const timers = new Map();

  const pid = () => String(projectId?.() || '');
  const base = () => `/api/v62/projects/${encodeURIComponent(pid())}/material-batches`;
  const tell = message => (notify || window.toast || console.info)(message);

  function remember(task) {
    const items = saved();
    if (ACTIVE.has(String(task.status || '').toUpperCase()) || task.review_required) items[task.task_id] = {project_id: pid()};
    else delete items[task.task_id];
    save(items);
  }

  async function get(taskId) {
    return json(await fetch(`${base()}/${encodeURIComponent(taskId)}`));
  }

  function announce(task) {
    const total = Number(task.total || 0);
    const processed = Number(task.processed || 0);
    const failed = Number(task.failed || 0);
    const cleaning = task.operation === 'CLEAN' ? `，发现问题 ${Number(task.flagged || 0)} 张（仅检查，待复核）` : '';
    tell(`${task.operation || '批量任务'}：${task.status} ${processed}/${total}${failed ? `，失败 ${failed}` : ''}${cleaning}`);
  }

  function poll(taskId) {
    clearTimeout(timers.get(taskId));
    const tick = async () => {
      try {
        const task = await get(taskId);
        remember(task);
        announce(task);
        if (ACTIVE.has(String(task.status || '').toUpperCase())) {
          timers.set(taskId, setTimeout(tick, 1500));
        } else {
          timers.delete(taskId);
          await refresh?.();
          if (task.review_required && typeof window.reviewAiLabel427 === 'function') {
            await window.reviewAiLabel427(task.task_id);
          }
        }
      } catch (error) {
        timers.delete(taskId);
        tell(error.message || String(error));
      }
    };
    tick();
  }

  function selection(scope) {
    if (scope === 'CURRENT_PAGE') return {scope, image_ids: (currentPageIds?.() || []).map(String)};
    if (scope === 'SELECTED') return {scope, image_ids: (selectedIds?.() || []).map(String)};
    return {scope: 'FILTERED', filters: filteredSpec?.() || {}};
  }

  async function run(operation, {scope, options = {}} = {}) {
    if (!pid()) throw new Error('请先选择项目');
    const chosen = scope || window.prompt('处理范围：CURRENT_PAGE 当前页 / FILTERED 全部筛选结果 / SELECTED 当前已选', 'CURRENT_PAGE');
    if (!['CURRENT_PAGE', 'FILTERED', 'SELECTED'].includes(chosen)) return null;
    if (operation === 'AI_ANNOTATE' && !options.labels?.length && !options.labels_text && !options.reference_image_ids?.length) {
      const labels = window.prompt('请输入标签库中的标签编码（逗号分隔）；使用默认 AI 模型生成待确认候选', '');
      if (!labels?.trim()) return null;
      options = {...options, labels_text: labels};
    }
    const payload = {operation, selection_spec: selection(chosen), options};
    const estimate = await json(await fetch(`${base()}/estimate`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    }));
    if (!estimate.supported) throw new Error(estimate.message || (estimate.error_code === 'BATCH_OPERATION_NOT_READY' ? '该批量操作尚未具备安全后台执行链路' : '当前操作不可用'));
    if (!Number(estimate.count || 0)) throw new Error('当前范围没有可处理素材');
    const cleanNote = operation === 'CLEAN' ? '清洗将检查并记录问题，不自动删除或确认素材。\n' : '';
    if (!window.confirm(`${cleanNote}本次将处理 ${estimate.count} 张素材（${chosen === 'CURRENT_PAGE' ? '当前页' : chosen === 'SELECTED' ? '当前已选' : '全部筛选结果'}），确认继续？`)) return null;
    payload.selection_spec = estimate.selection_spec;
    if (operation === 'DELETE_SOURCE') payload.options.confirmation_token = estimate.confirmation_token;
    const task = await json(await fetch(base(), {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    }));
    remember(task);
    announce(task);
    poll(task.task_id);
    return task;
  }

  window.runMaterialBatch62 = (operation, config) => run(operation, config).catch(error => tell(error.message || String(error)));
  window.reviewMaterialBatch62 = taskId => window.reviewAiLabel427?.(taskId);
  window.cancelMaterialBatch62 = async taskId => {
    const task = await json(await fetch(`${base()}/${encodeURIComponent(taskId)}/cancel`, {method: 'POST'}));
    remember(task); announce(task); return task;
  };
  window.retryMaterialBatch62 = async taskId => {
    const task = await json(await fetch(`${base()}/${encodeURIComponent(taskId)}/retry`, {method: 'POST'}));
    remember(task); poll(task.task_id); return task;
  };
  window.stopMaterialBatchPolling62 = taskId => { clearTimeout(timers.get(taskId)); timers.delete(taskId); };

  for (const [taskId, entry] of Object.entries(saved())) {
    if (entry.project_id === pid()) poll(taskId);
  }
  return true;
}
