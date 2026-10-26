import {canonicalTaskStatus, exactTaskQueuePosition, isCanonicalTaskActive} from './task-runtime-truth.js';
import {withRequestDeadline} from './api.js?v=20261021s';

const STORAGE_KEY = 'aixunlian.material-batches.v62';
export function isMaterialBatchActive(value) {
  return isCanonicalTaskActive(value);
}


export function materialBatchTaskText(task = {}) {
  const status = canonicalTaskStatus(task);
  const label = ({QUEUED:'排队中', WAITING_RESOURCE:'等待资源', RUNNING:'处理中', CANCEL_REQUESTED:'正在取消', AWAITING_CONFIRMATION:'等待确认', PARTIAL_SUCCESS:'部分成功', SUCCEEDED:'已完成', CANCELLED:'已取消', FAILED:'失败', BLOCKED_BY_ENVIRONMENT:'环境不可用', BLOCKED_BY_HARDWARE:'硬件不可用'})[status] || status || '未知';
  const queuePosition = exactTaskQueuePosition(task) || 0;
  const waitReason = String(task.resource_wait_reason || '').trim();
  const workerId = String(task.worker_id || '').trim();
  const runtime = ['QUEUED', 'WAITING_RESOURCE'].includes(status)
    ? (queuePosition ? ` · 资源队列第 ${queuePosition} 位${waitReason ? ` · ${waitReason}` : ''}` : (waitReason ? ` · ${waitReason}` : ''))
    : (workerId ? ` · Worker ${workerId}` : '');
  return `${label}${runtime}`;
}

async function json(response) {
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch (_error) { body = {detail: text}; }
  if (response.ok) return body;
  const detail = body?.detail;
  const message = detail?.message || body?.message || (typeof detail === 'string' ? detail : '') || `HTTP ${response.status}`;
  const error = new Error(message);
  error.code = detail?.code || body?.code || `HTTP_${response.status}`;
  error.httpStatus = response.status;
  throw error;
}

function saved() {
  try { return JSON.parse(localStorage.getItem(STORAGE_KEY) || '{}'); } catch (_error) { return {}; }
}

function save(items) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
}

export function installMaterialBatchRuntime({projectId, projectName, currentPageIds, selectedIds, filteredSpec, notify, refresh, pollRegistry, requestTimeoutMs = 30000} = {}) {
  if (typeof window === 'undefined' || window.__materialBatchRuntime62Installed) return false;
  window.__materialBatchRuntime62Installed = true;
  const registry = pollRegistry || window.PollRegistryRuntime;
  if (!registry?.startTimeout || !registry?.clear) {
    window.__materialBatchRuntime62Installed = false;
    return false;
  }
  const POLL_OWNERS = ['数据集', '自动标注及清洗', '训练任务', '算法列表'];
  const auditAnnouncementStatus = new Map();
  const submissions = new Map();
  const deletionContexts = new Map();
  const unknownKey = `${STORAGE_KEY}.unknown`;
  const unknowns = () => {try {return JSON.parse(localStorage.getItem(unknownKey) || '{}')} catch (_) {return {}}};
  const markUnknown = (project, operation) => {const values=unknowns();if(operation)values[project]=operation;else delete values[project];localStorage.setItem(unknownKey,JSON.stringify(values))};
  const request = (url, options = {}) => withRequestDeadline(async signal => json(await fetch(url, {...options, signal})), {timeoutMs:requestTimeoutMs,label:'素材任务请求'});

  const pid = () => String(projectId?.() || '');
  const base = () => `/api/v62/projects/${encodeURIComponent(pid())}/material-batches`;
  const tell = message => (notify || window.toast || console.info)(message);

  function remember(task) {
    const items = saved();
    if (isMaterialBatchActive(task) || task.review_required) items[task.task_id] = {project_id: pid()};
    else delete items[task.task_id];
    save(items);
  }

  async function get(taskId, project = pid()) {
    return request(`/api/v62/projects/${encodeURIComponent(project)}/material-batches/${encodeURIComponent(taskId)}`);
  }

  function announce(task) {
    if (task.operation === 'SMART_AUDIT') {
      try { window.SmartMaterialAuditRuntime?.onTask?.(task); } catch (_) {}
      return;
    }
    window.updateTrainingIntegrityAudit47?.(task);
    window.updateMaterialIntegrityTask47?.(task);
    window.updateMaterialIntegrityAudit47?.(task);
    if (task.operation === 'AUDIT_MATERIAL_INTEGRITY') {
      const status = canonicalTaskStatus(task);
      if (auditAnnouncementStatus.get(task.task_id) === status) return;
      auditAnnouncementStatus.set(task.task_id, status);
      tell(`素材完整性审计：${materialBatchTaskText(task)} · Task ${task.task_id}`);
      return;
    }
    const total = Number(task.total || 0);
    const processed = Number(task.processed || 0);
    const failed = Number(task.failed || 0);
    const cleaning = task.operation === 'CLEAN' ? `，发现问题 ${Number(task.flagged || 0)} 张（仅检查，待复核）` : '';
    if (task.material_integrity_plan_id && Number(task.planned_groups || 0) > 0) {
      tell(`批量去重：${materialBatchTaskText(task)} · 完成组 ${Number(task.completed_groups || 0)}/${Number(task.planned_groups || 0)} · 已保留 ${Number(task.kept_count || 0)} · 已清理 ${Number(task.succeeded || 0)} · 跳过 ${Number(task.skipped_groups || 0)}${Number(task.failed_groups || 0) ? ` · 失败组 ${Number(task.failed_groups || 0)}` : ''}`);
      return;
    }
    tell(`${task.operation || '批量任务'}：${materialBatchTaskText(task)} ${processed}/${total}${failed ? `，失败 ${failed}` : ''}${cleaning}`);
  }

  function pollKey(taskId) {
    return `material-batch:${String(taskId || '')}`;
  }

  function stopPolling(taskId) {
    return registry.clear(pollKey(taskId));
  }

  function poll(taskId, {foreground = false} = {}) {
    const id = String(taskId || '');
    if (!id) return false;
    const projectAtStart = pid();
    stopPolling(id);
    const tick = async () => {
      try {
        const task = await get(id, projectAtStart);
        if (pid() !== projectAtStart) { stopPolling(id); return; }
        remember(task);
        announce(task);
        if (isMaterialBatchActive(task)) {
          registry.startTimeout(pollKey(id), POLL_OWNERS, tick, 1500);
        } else {
          stopPolling(id);
          if (task.operation !== 'SMART_AUDIT') {
            try {await refresh?.();} catch(error) {tell('素材任务已结束，列表刷新失败，可手动刷新：'+(error.message||error));}
          }
          if (pid() !== projectAtStart) return;
          if (task.operation === 'DELETE_INDEX' && typeof window.invalidateMaterialIntegrityGovernance47 === 'function') {
            await window.invalidateMaterialIntegrityGovernance47(task);
          }
          if(task.operation==='DELETE_INDEX')await window.TrainingMaterialSummaryRuntime?.onMaterialBatchCompleted?.(task);
          if (foreground && task.operation === 'AI_ANNOTATE' && task.review_required && typeof window.reviewAiLabel427 === 'function') {
            await window.reviewAiLabel427(task.task_id);
          }
        }
      } catch (error) {
        stopPolling(id);
        if (pid() !== projectAtStart) return;
        tell(error.message || String(error));
      }
    };
    void tick();
    return true;
  }

  function resume() {
    for (const [taskId, entry] of Object.entries(saved())) {
      if (entry.project_id === pid()) poll(taskId);
    }
    return true;
  }

  function selection(scope, explicitIds = []) {
    if(scope==='PROJECT')return {scope:'FILTERED',filters:{}};
    if (scope === 'CURRENT_PAGE') return {scope, image_ids: (currentPageIds?.() || []).map(String)};
    if (scope === 'SELECTED') {
      const source = explicitIds?.length ? explicitIds : (selectedIds?.() || []);
      return {scope, image_ids: [...new Set(source.map(String).filter(Boolean))]};
    }
    return {scope: 'FILTERED', filters: filteredSpec?.() || {}};
  }

  async function run(operation, {scope, options = {}, imageIds = [], skipConfirm = false} = {}) {
    if (!pid()) throw new Error('请先选择项目');
    const trainingContext=window.TrainingMaterialSummaryRuntime?.captureDeletionContext?.()||null;
    const chosen = scope || window.prompt('处理范围：CURRENT_PAGE 当前页 / FILTERED 全部筛选结果 / SELECTED 当前已选', 'CURRENT_PAGE');
    if (!['CURRENT_PAGE', 'FILTERED', 'SELECTED', 'PROJECT'].includes(chosen)) return null;
    if(chosen==='PROJECT'){
      if(operation!=='DELETE_INDEX')throw new Error('项目清空只允许删除当前素材索引');
      const name=String(projectName?.()||options.project_name||'');
      const confirmation=window.prompt(`清空整个项目素材库。请输入当前项目名称：${name}`,'');
      if(confirmation===null)return null;
      if(!name||confirmation!==name)throw new Error('项目名称确认不一致，未创建删除任务');
      options={...options,clear_project:true,project_name_confirmation:confirmation};
    }
    if (operation === 'AI_ANNOTATE' && !options.labels?.length && !options.labels_text && !options.reference_image_ids?.length) {
      const labels = window.prompt('请输入标签库中的标签编码（逗号分隔）；使用默认 AI 模型生成待确认候选', '');
      if (!labels?.trim()) return null;
      options = {...options, labels_text: labels};
    }
    const projectAtStart = pid();
    const selectionAtStart = selection(chosen, imageIds);
    const selectionSignature = JSON.stringify(selectionAtStart);
    const batchUrl = `/api/v62/projects/${encodeURIComponent(projectAtStart)}/material-batches`;
    const assertScopeUnchanged = () => {
      if (pid() !== projectAtStart || JSON.stringify(selection(chosen, imageIds)) !== selectionSignature) {
        throw new Error('项目或筛选条件已变更，已取消操作，请重新预览删除范围');
      }
    };
    const payload = {operation, selection_spec: selectionAtStart, options};
    const estimate = await request(`${batchUrl}/estimate`, {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    assertScopeUnchanged();
    if (!estimate.supported) throw new Error(estimate.message || (estimate.error_code === 'BATCH_OPERATION_NOT_READY' ? '该批量操作尚未具备安全后台执行链路' : '当前操作不可用'));
    if (!Number(estimate.count || 0)) throw new Error('当前范围没有可处理素材');
    const cleanNote = operation === 'CLEAN' ? '清洗将检查并记录问题，不自动删除或确认素材。\n' : '';
    let deleteNote = operation === 'DELETE_INDEX'
      ? '将删除素材索引及对应全部标注（Ground Truth 与标注文件）；共享原图及平台标签字典不会被删除。\n'
      : operation === 'DELETE_SOURCE'
        ? '将尝试删除原始图片对象及对应标注，操作不可撤销。\n' : '';
    const preview=estimate.deletion_preview;
    if(operation==='DELETE_INDEX'&&preview){
      if(!preview.plan_id||!preview.confirmation_credential)throw new Error('删除预览身份不完整，请重新预览');
      const count=value=>value==null?'未核验':Number(value);
      deleteNote+=`正式 GT ${count(preview.gt_count)} · 当前 Test ${count(preview.current_test_count)}\n历史引用 ${count(preview.historical_reference_count)} · 活动引用 ${count(preview.active_reference_count)}\n保留物理图片 ${count(preview.physical_retained_count)} · 释放空间 0 字节\n历史证据保留；已删除原图不保证完整复评。\n`;
      payload.options={...options,deletion_plan_id:preview.plan_id,confirmation_credential:preview.confirmation_credential};
    }
    if ((!skipConfirm || preview) && !window.confirm(`${deleteNote}${cleanNote}本次将${deleteNote ? '删除' : '处理'} ${estimate.count} 张素材（${chosen==='PROJECT'?'整个项目':chosen === 'CURRENT_PAGE' ? '当前页' : chosen === 'SELECTED' ? '当前已选' : '全部筛选结果'}），确认继续？`)) return null;
    assertScopeUnchanged();
    payload.selection_spec = estimate.selection_spec;
    if (operation === 'DELETE_SOURCE') payload.options.confirmation_token = estimate.confirmation_token;
    if(preview?.plan_id)deletionContexts.set(preview.plan_id,trainingContext);
    markUnknown(projectAtStart, preview?.plan_id?{operation,task_id:preview.plan_id}:operation);
    let task;
    try {
      task = await request(batchUrl, {
        method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
      });
      if (!task?.task_id) throw new Error('服务端未返回可核验的任务身份');
      markUnknown(projectAtStart, null);
    } catch (error) {
      if (error.httpStatus && error.httpStatus < 500) markUnknown(projectAtStart, null);
      else {
        if(pid()===projectAtStart)tell('素材任务提交结果待确认；已保留原数据。再次点击只查询后台任务，不重复提交。');
        await recoverUnknown(projectAtStart);
        return null;
      }
      throw error;
    }
    if(pid()!==projectAtStart)return task;
    if(operation==='DELETE_INDEX')window.TrainingMaterialSummaryRuntime?.trackMaterialDeletion?.(task,trainingContext);
    deletionContexts.delete(task.task_id);
    remember(task);
    announce(task);
    poll(task.task_id, {foreground: true});
    return task;
  }

  async function recoverUnknown(project = pid()) {
    try {
      const pending=unknowns()[project];
      if(pending?.task_id){
        const task=await get(pending.task_id,project);
        if(pid()!==project)return null;
        if(task?.task_id!==pending.task_id||task.operation!==pending.operation)throw new Error('提交结果身份不一致，请查询原任务');
        markUnknown(project,null);
        window.TrainingMaterialSummaryRuntime?.trackMaterialDeletion?.(task,deletionContexts.get(task.task_id)||null);
        deletionContexts.delete(task.task_id);
        remember(task);announce(task);poll(task.task_id);
        tell('已按原计划身份核验素材任务，不会重复创建');return task;
      }
      const page=await request(`/api/v62/projects/${encodeURIComponent(project)}/material-batches?limit=50`);
      if(pid()!==project)return null;
      const items=(page.items||[]).filter(task=>task.operation===unknowns()[project]);
      for(const task of items){remember(task);if(isMaterialBatchActive(task))poll(task.task_id)}
      tell(`提交结果待确认；已查询后台任务${items.length?'：'+items.map(task=>task.task_id).join('、'):'，尚未找到可核验记录'}。请在任务列表核对；此入口保持查询，不重复创建。`);
      return page;
    } catch(error){if(pid()===project)tell('提交结果待确认；状态查询失败：'+(error.message||error));return null}
  }
  window.runMaterialBatch62 = (operation, config = {}) => {
    const project=pid();
    if(submissions.has(project))return submissions.get(project);
    const button=config.triggerButton||window.event?.currentTarget,wasDisabled=button?.disabled;
    if(button){button.disabled=true;button.setAttribute?.('aria-busy','true');button.classList?.add('loading')}
    const pending=Promise.resolve().then(()=>pid()!==project?null:unknowns()[project]?recoverUnknown(project):run(operation,config))
      .catch(error=>{if(pid()===project)tell(error.message||String(error))})
      .finally(()=>{submissions.delete(project);if(button?.isConnected){button.disabled=wasDisabled;button.removeAttribute?.('aria-busy');button.classList?.remove('loading')}});
    submissions.set(project,pending);
    return pending;
  };
  window.reviewMaterialBatch62 = taskId => window.reviewAiLabel427?.(taskId);
  window.cancelMaterialBatch62 = async taskId => {
    const task = await json(await fetch(`${base()}/${encodeURIComponent(taskId)}/cancel`, {method: 'POST'}));
    remember(task); announce(task); return task;
  };
  window.retryMaterialBatch62 = async taskId => {
    const task = await json(await fetch(`${base()}/${encodeURIComponent(taskId)}/retry`, {method: 'POST'}));
    remember(task); poll(task.task_id); return task;
  };
  window.stopMaterialBatchPolling62 = taskId => stopPolling(taskId);

  const runtime = Object.freeze({
    build: 'material-batch-runtime-422408',
    poll,
    resume,
    stop: stopPolling,
    pendingSmart: () => unknowns()[`smart:${pid()}`] || null,
    submitSmart(payload) {
      const project = pid(), key = `smart:${project}`;
      if (!project) return Promise.reject(new Error('请先选择项目'));
      if (submissions.has(key)) return submissions.get(key);
      const pending = unknowns()[key];
      const body = pending?.payload || payload;
      const promise = Promise.resolve().then(async () => {
        if (pid() !== project) throw new Error('项目已切换');
        markUnknown(key, {operation:'SMART_AUDIT', payload:body});
        try {
          const task = await request(`/api/v62/projects/${encodeURIComponent(project)}/smart-material-audit`, {
            method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body),
          });
          if (!task?.task_id || task.project_id !== project || task.operation !== 'SMART_AUDIT' || task.kind !== 'MATERIAL_BATCH')
            throw new Error('智能分析受理身份未确认；重试将使用原请求，不重复创建');
          markUnknown(key, null);
          if (pid() === project) {
            try {remember(task);} catch (_) {tell('分析任务已创建；浏览器恢复记录未保存，可从历史任务查看');}
            announce(task);poll(task.task_id);
          }
          return task;
        } catch (error) {
          if (!pending && error.httpStatus && error.httpStatus < 500) markUnknown(key,null);
          throw error;
        }
      }).finally(() => submissions.delete(key));
      submissions.set(key,promise);
      return promise;
    },
  });
  window.MaterialBatchRuntime62 = runtime;
  resume();
  return true;
}
