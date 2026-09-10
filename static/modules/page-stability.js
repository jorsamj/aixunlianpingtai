const ACTIVE = new Set(['queued', 'running', 'paused', 'waiting', 'pending', 'cancel_requested']);
const TERMINAL = new Set(['done', 'finished', 'completed', 'succeeded', 'partial_success', 'post_processing_failed', 'failed', 'stopped', 'cancelled']);

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'})[character]);
}

async function responseJson(response) {
  if (response.ok) return response.json();
  const text = await response.text();
  let body = {};
  try { body = JSON.parse(text); } catch (_error) { body = {detail: text}; }
  throw new Error(body.message || body.detail || `HTTP ${response.status}`);
}

const statusOf = task => String(task?.status || '').trim().toLowerCase();
const idOf = task => String(task?.id || task?.task_id || '');

function algorithmTitle(task) {
  const algorithmId = task?.asset_algorithm_id || task?.algorithm_asset_id || task?.algorithm_id;
  const algorithm = (state.algorithms || []).find(row => String(row.id) === String(algorithmId || '')) || {};
  return task?.asset_algorithm_display_name || task?.algorithm_display_name || task?.asset_algorithm_name ||
    task?.algorithm_name || algorithm.display_name || algorithm.name || algorithm.code || idOf(task);
}

function statusView(status) {
  const labels = {queued:'排队中',running:'训练中',paused:'已暂停',waiting:'等待中',pending:'等待中',cancel_requested:'正在停止',done:'已完成',finished:'已完成',completed:'已完成',succeeded:'已完成',partial_success:'部分完成',post_processing_failed:'训练完成 · 后处理失败',failed:'失败',stopped:'已停止',cancelled:'已取消'};
  const cls = ['done','finished','completed','succeeded','partial_success'].includes(status) ? 'ok' : ['failed','post_processing_failed'].includes(status) ? 'err' : status === 'paused' ? 'blue' : 'warn';
  return {label: labels[status] || status || '-', cls};
}

function duration(seconds) {
  const value = Math.max(0, Number(seconds) || 0);
  if (!value) return '-';
  if (value < 60) return `${Math.round(value)}秒`;
  const minutes = Math.floor(value / 60), remainder = Math.round(value % 60);
  return `${minutes}分${remainder ? `${remainder}秒` : ''}`;
}

function actions(task) {
  const id = escapeHtml(idOf(task)), status = statusOf(task);
  if (status === 'queued') return `<button class="btn mini" onclick="promoteTrain428('${id}')">插队</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  if (status === 'running') return `<button class="btn mini" onclick="showTrainLog423('${id}')">详情</button><button class="btn mini" onclick="pauseTrain428('${id}')">暂停</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button>`;
  if (status === 'paused') return `<button class="btn mini" onclick="showTrainLog423('${id}')">详情</button><button class="btn mini primary" onclick="resumeTrain428('${id}')">继续</button><button class="btn mini danger" onclick="stopTrain428('${id}')">停止</button>`;
  if (status === 'post_processing_failed') return `<button class="btn mini" onclick="showTrainLog423('${id}')">详情</button><button class="btn mini primary" onclick="retryPostProcessing424('${id}')">重试后处理</button><button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
  return `<button class="btn mini" onclick="showTrainLog423('${id}')">详情</button>${task.auto_version_id ? `<button class="btn mini primary" onclick="trainingReport425('${id}')">训练报告</button>` : ''}<button class="btn mini danger" onclick="deleteTrain428('${id}')">删除</button>`;
}

function rowHtml(task) {
  const id = idOf(task), status = statusOf(task), view = statusView(status);
  const progress = Math.max(0, Math.min(100, Number(task.progress_percent ?? task.progress) || 0));
  const resource = task.execution_resource?.name || task.execution_resource?.base_url || task.server_name || task.server_id || (task.target === 'remote' ? '远程训练服务器' : '本机训练环境');
  const created = String(task.started_at || task.created_at || '').replace('T',' ').replace('Z','').slice(0,19) || '-';
  return `<tr data-training-task-id="${escapeHtml(id)}"><td><div class="train428-taskname"><b>${escapeHtml(algorithmTitle(task))}</b><span>任务ID：${escapeHtml(id)}</span>${task.base_version_name ? `<em>基于版本：${escapeHtml(task.base_version_name)}</em>` : task.auto_version_name ? `<em>版本 ${escapeHtml(task.auto_version_name)}</em>` : ''}</div></td><td><span class="pill ${view.cls}">${escapeHtml(view.label)}</span><small class="queuepriority428">优先级 ${Number(task.queue_priority ?? task.priority ?? 50)}</small></td><td><div class="train428-resource"><b>${escapeHtml(resource)}</b><span>${task.framework === 'paddle' ? 'PaddleDetection' : 'Ultralytics / YOLO'}</span></div></td><td><div class="progress424"><i style="width:${progress}%"></i></div><span class="train428-progress-txt">${Number(task.current_epoch)||0}/${escapeHtml(task.total_epochs || task.epochs || '-')} · ${progress.toFixed(0)}%</span></td><td>${duration(task.elapsed_seconds)}</td><td>${duration(task.eta_seconds)}</td><td>${escapeHtml(created)}</td><td><div class="row wrap">${actions(task)}</div></td></tr>`;
}

export function installPageStability({lifecycle} = {}) {
  if (typeof window === 'undefined' || window.__pageStability425Installed) return false;
  window.__pageStability425Installed = true;
  let visibleOrder = [];

  function selectedTasks() {
    const tab = state.train428Tab || 'active';
    return (state.jobs || []).filter(task => tab === 'history' ? TERMINAL.has(statusOf(task)) : ACTIVE.has(statusOf(task)));
  }

  function stableTasks() {
    const rows = selectedTasks(), ids = new Set(rows.map(idOf));
    visibleOrder = visibleOrder.filter(id => ids.has(id));
    for (const task of rows) if (!visibleOrder.includes(idOf(task))) visibleOrder.push(idOf(task));
    const byId = new Map(rows.map(task => [idOf(task), task]));
    return visibleOrder.map(id => byId.get(id)).filter(Boolean);
  }

  function patchRows() {
    const body = document.getElementById('trainingTaskRows425');
    if (!body) return;
    const rows = stableTasks(), nextIds = new Set(rows.map(idOf));
    for (const existing of [...body.querySelectorAll('tr[data-training-task-id]')]) if (!nextIds.has(existing.dataset.trainingTaskId)) existing.remove();
    if (!rows.length) { body.innerHTML = '<tr class="training-empty425"><td colspan="8" class="empty-row">暂无记录</td></tr>'; return; }
    body.querySelector('.training-empty425')?.remove();
    for (const task of rows) {
      const id = idOf(task), signature = JSON.stringify([task.status,task.stage,task.progress_percent,task.progress,task.current_epoch,task.elapsed_seconds,task.eta_seconds,task.message,algorithmTitle(task),task.actual_device]);
      const current = body.querySelector(`tr[data-training-task-id="${CSS.escape(id)}"]`);
      if (!current) body.insertAdjacentHTML('beforeend', rowHtml(task));
      else if (current.dataset.signature !== signature) { const holder=document.createElement('tbody');holder.innerHTML=rowHtml(task);holder.firstElementChild.dataset.signature=signature;current.replaceWith(holder.firstElementChild); }
      const row = body.querySelector(`tr[data-training-task-id="${CSS.escape(id)}"]`); if (row) row.dataset.signature=signature;
    }
    const activeCount=document.getElementById('trainingActiveCount425'),historyCount=document.getElementById('trainingHistoryCount425');
    if(activeCount)activeCount.textContent=String((state.jobs||[]).filter(task=>ACTIVE.has(statusOf(task))).length);
    if(historyCount)historyCount.textContent=String((state.jobs||[]).filter(task=>TERMINAL.has(statusOf(task))).length);
  }

  async function refreshTasks({notify=false}={}) {
    const projectId=String(state.project?.id||'');if(!projectId)return;
    const request=lifecycle?.request?.('training-task-list');
    try { const response=await responseJson(await fetch(`/api/projects/${encodeURIComponent(projectId)}/jobs`,{signal:request?.signal}));if(request&&!request.isCurrent())return;state.jobs=Array.isArray(response)?response:(response.items||[]);if(state.page==='训练任务')patchRows();if(notify)window.toast?.('训练任务已刷新'); }
    catch(error){if(error?.name!=='AbortError')window.toast?.(error.message||String(error))}finally{request?.release?.()}
  }

  window.renderTraining425=window.renderTraining424=window.renderTraining423=function stableTrainingPage(){
    if(state.page!=='训练任务')return;
    const active=(state.jobs||[]).filter(task=>ACTIVE.has(statusOf(task))).length,history=(state.jobs||[]).filter(task=>TERMINAL.has(statusOf(task))).length;
    if(!document.querySelector('.train428-page'))document.getElementById('view').innerHTML=`<section class="train428-page"><div class="train428-tabs"><button class="${(state.train428Tab||'active')==='active'?'on':''}" onclick="setTrainTab428('active')">进行中 <span id="trainingActiveCount425">${active}</span></button><button class="${state.train428Tab==='history'?'on':''}" onclick="setTrainTab428('history')">历史记录 <span id="trainingHistoryCount425">${history}</span></button><button class="train428-refresh" onclick="refreshTrainPage428()">刷新</button></div><section class="panel"><div class="table-wrap"><table class="table train428-table"><thead><tr><th>训练任务</th><th>状态</th><th>执行机器 / 框架</th><th>进度</th><th>已用时间</th><th>预计剩余</th><th>开始时间</th><th>操作</th></tr></thead><tbody id="trainingTaskRows425"></tbody></table></div></section></section>`;
    if(!visibleOrder.length)visibleOrder=selectedTasks().map(idOf);patchRows();lifecycle?.startPolling?.('training-task-list',()=>refreshTasks(),active?1800:5000);
  };
  window.setTrainTab428=function(tab){state.train428Tab=tab==='history'?'history':'active';visibleOrder=[];document.querySelector('.train428-page')?.remove();window.renderTraining423()};
  window.refreshTrainPage428=()=>refreshTasks({notify:true});

  const baseShowTrainingDetail=window.showTrainLog423;
  window.showTrainLog423=async function stableTrainingDetail(id){
    await baseShowTrainingDetail?.(id);
    const task=(state.jobs||[]).find(row=>idOf(row)===String(id));if(!task)return;
    const titles=[...document.querySelectorAll('.modal-title')],title=titles.at(-1)||document.getElementById('modalTitle');
    if(title)title.textContent=`${algorithmTitle(task)} · 训练详情`;
  };

  const baseRefresh=window.refreshCurrentPage413;
  window.refreshCurrentPage413=async function(){
    if(!state.uiReady){if(state.page==='数据集')return window.reloadMaterialPage61?.();return;}
    if(state.page==='数据集')return window.reloadMaterialPage61?.();
    if(state.page==='训练任务')return refreshTasks();
    if(state.page==='训练资源'){await window.ResourceDiscoveryRuntime?.refreshCache?.(true);return}
    return baseRefresh?.()
  };
  return true;
}
