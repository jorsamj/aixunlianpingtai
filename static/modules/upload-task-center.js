import {withRequestDeadline} from './api.js';

const ACTIVE_STATUSES = new Set(['WAITING_UPLOAD','UPLOADING','PAUSED','MERGING','VALIDATING','SELECTING','QUEUED','WAITING','WAITING_RESOURCE','RUNNING','SCANNING','EXTRACTING','MAPPING_LABELS','WRITING_ANNOTATIONS','INDEXING','FINALIZING']);
const TERMINAL_STATUSES = new Set(['DONE','SUCCEEDED','COMPLETED','FINISHED','FAILED','CANCELLED','CANCELED','INTERRUPTED']);
const STORAGE_PREFIX = 'mc_upload_task_center_v1:';
const POLL_MS = 1200;
const MAX_ROWS = 100;

const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const clamp = value => Math.max(0, Math.min(100, Number(value) || 0));
const upper = value => String(value || '').trim().toUpperCase();
const nowIso = () => new Date().toISOString();

function formatTime(value) {
  const date = new Date(value || '');
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString('zh-CN', {hour12:false, hour:'2-digit', minute:'2-digit', second:'2-digit'});
}

function formatBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`;
}

function statusPresentation(status) {
  const key = upper(status);
  if (['DONE','SUCCEEDED','COMPLETED','FINISHED'].includes(key)) return {label:'已完成', cls:'ok'};
  if (['FAILED','INTERRUPTED'].includes(key)) return {label:'失败', cls:'bad'};
  if (['CANCELLED','CANCELED'].includes(key)) return {label:'已取消', cls:'muted'};
  if (key === 'PAUSED') return {label:'已暂停', cls:'warn'};
  if (key === 'WAITING_UPLOAD') return {label:'排队中', cls:'warn'};
  if (['QUEUED','WAITING','WAITING_RESOURCE','SELECTING'].includes(key)) return {label:'等待中', cls:'warn'};
  return {label:'进行中', cls:'run'};
}

export function isUploadTaskActive(task = {}) {
  return ACTIVE_STATUSES.has(upper(task.status));
}

export function clearCompletedUploadTasks(tasks = []) {
  return (Array.isArray(tasks) ? tasks : []).filter(task => !TERMINAL_STATUSES.has(upper(task?.status)));
}

export function hasTerminalZipUploadTasks(tasks = []) {
  return (Array.isArray(tasks) ? tasks : []).some(
    task => String(task?.kind || '') === 'zip' && TERMINAL_STATUSES.has(upper(task?.status)),
  );
}

/** Stable task identity order: progress polling never reshuffles concurrent uploads. */
export function stableUploadTaskOrder(tasks = []) {
  return [...tasks].sort((a, b) =>
    String(b?.createdAt || '').localeCompare(String(a?.createdAt || ''))
    || String(a?.orderKey || a?.id || '').localeCompare(String(b?.orderKey || b?.id || ''))
  );
}

/** Never hide active work merely because terminal history reached its bound. */
export function retainUploadTaskRows(tasks = [], maximum = MAX_ROWS) {
  const ordered = stableUploadTaskOrder(Array.isArray(tasks) ? tasks : []);
  const active = ordered.filter(isUploadTaskActive);
  const limit = Math.max(1, Number(maximum) || MAX_ROWS);
  if (active.length >= limit) return active;
  const terminal = ordered.filter(task => !isUploadTaskActive(task)).slice(0, limit - active.length);
  const retained = new Set([...active, ...terminal].map(task => String(task.id || '')));
  return ordered.filter(task => retained.has(String(task.id || '')));
}

export function summarizeUploadTasks(tasks = []) {
  const rows = Array.isArray(tasks) ? tasks : [];
  return {
    total:rows.length,
    active:rows.filter(isUploadTaskActive).length,
    uploading:rows.filter(row => upper(row.status) === 'UPLOADING' && row.browserTransfer).length,
    queued:rows.filter(row => upper(row.status) === 'WAITING_UPLOAD').length,
    terminal:rows.filter(row => TERMINAL_STATUSES.has(upper(row.status))).length,
  };
}

export function mergeUploadTask(previous = {}, next = {}) {
  const status = upper(next.status || previous.status || 'UPLOADING');
  const progress = status === 'SUCCEEDED' || status === 'DONE' || status === 'COMPLETED' || status === 'FINISHED'
    ? 100 : clamp(next.progress ?? previous.progress ?? 0);
  return {
    ...previous,
    ...next,
    id: String(next.id || previous.id || ''),
    orderKey: String(previous.orderKey || next.orderKey || next.id || previous.id || ''),
    kind: String(next.kind || previous.kind || 'upload'),
    title: String(next.title || previous.title || '上传任务'),
    status,
    progress,
    progressKnown: next.progressKnown === false || next.progress === null ? false : next.progress !== undefined ? true : previous.progressKnown !== false,
    stage: String(next.stage || previous.stage || ''),
    detail: String(next.detail || previous.detail || ''),
    updatedAt: String(next.updatedAt || nowIso()),
    createdAt: String(previous.createdAt || next.createdAt || nowIso()),
  };
}

export function normalizeDurableUploadTask(task, row) {
  const backendStatus = upper(task?.status || row.status);
  const progress = task?.progress ?? task?.progress_percent ?? row.progress;
  if (row?.resumeRequired && backendStatus === 'UPLOADING') {
    return mergeUploadTask(row, {
      status:'WAITING',
      progress,
      stage:'上传已暂停，等待继续',
      detail:row?.detail || '页面刷新后浏览器已释放文件对象；重新选择同一个 ZIP 后会从已完成分片继续。',
      updatedAt:task?.updated_at || nowIso(),
      resumeRequired:true,
      browserTransfer:false,
    });
  }
  return mergeUploadTask(row, {
    status:backendStatus,
    progress,
    stage:task?.stage || task?.phase || row.stage,
    detail:task?.current_item || task?.message || task?.error || row.detail,
    updatedAt:task?.updated_at || nowIso(),
    resumeRequired:false,
    browserTransfer:false,
  });
}

export function recoverUploadTaskAfterRefresh(row = {}) {
  if (row.kind === 'zip' && row.localOnly && isUploadTaskActive(row)) {
    return mergeUploadTask(row, {
      status:'INTERRUPTED',
      stage:'需要重新选择文件',
      detail:'页面刷新后浏览器文件内容不可恢复；请重新选择该 ZIP，尚未创建服务器上传会话。',
      resumeRequired:false,
      browserTransfer:false,
      queuePosition:null,
    });
  }
  if (row.kind === 'zip' && row.browserTransfer && isUploadTaskActive(row)) {
    return mergeUploadTask(row, {
      status:'WAITING',
      stage:'上传已暂停，等待继续',
      detail:'页面刷新后浏览器已释放文件对象；重新选择同一个 ZIP 后会从已完成分片继续。',
      resumeRequired:true,
      browserTransfer:false,
    });
  }
  if (row.kind === 'browser-upload' && isUploadTaskActive(row) && !row.serverUrl) {
    return mergeUploadTask(row, {status:'INTERRUPTED', stage:'上传已中断', detail:'页面刷新后需重新选择文件；已创建的后台任务会自动恢复显示。'});
  }
  return row;
}

function taskActionMarkup(row) {
  if (String(row.kind || '') === 'browser-upload') return '<button type="button" class="utc-action" data-utc-action="details">查看详情</button>';
  if (String(row.kind || '') !== 'zip') return '';
  const status = upper(row.status);
  const button = (action, label, cls = '') => `<button type="button" class="utc-action ${cls}" data-utc-action="${action}">${label}</button>`;
  if (row.localOnly && ['WAITING_UPLOAD','UPLOADING','VALIDATING'].includes(status)) return button('cancel-local','取消','danger');
  if (row.localOnly && ['FAILED','INTERRUPTED'].includes(status)) return button('reselect','重新选择');
  if (status === 'UPLOADING' && row.browserTransfer) return button('pause','暂停') + button('cancel','取消','danger');
  if (status === 'PAUSED' || row.resumeRequired) return button('resume','继续') + button('cancel','取消','danger');
  if (status === 'SELECTING') return button('open','查看标签确认','primary');
  if (!row.localOnly) return button('open','查看任务');
  return '';
}

export function renderUploadTaskCenterRow(row = {}) {
  const presentation = statusPresentation(row.status);
  const progress = clamp(row.progress);
  const scale = progress / 100;
  const detail = row.detail
    ? `<div class="utc-detail" title="${esc(row.detail)}">${esc(row.detail)}</div>`
    : '';
  const reopenable=String(row.kind||'')==='zip'&&!row.localOnly;
  const size=Number(row.fileSize)>0?formatBytes(row.fileSize):'';
  const queue=Number(row.queuePosition)>0?`排队第 ${Number(row.queuePosition)} 位`:'';
  const leftMeta=[row.progressKnown === false ? '等待服务器进度' : `${progress.toFixed(progress % 1 ? 1 : 0)}%`,size,queue].filter(Boolean).join(' · ');
  const actions=taskActionMarkup(row);
  return `<div class="utc-row${reopenable?' utc-reopenable':''}" data-utc-id="${esc(row.id)}" data-utc-kind="${esc(row.kind||'')}" data-utc-local="${row.localOnly?'1':'0'}" ${reopenable?'role="button" tabindex="0" aria-label="重新打开 ZIP 导入任务"':''}><div class="utc-top"><div class="utc-name"><b>${esc(row.title)}</b><small>${esc(row.stage || presentation.label)}</small></div><span class="utc-pill ${presentation.cls}">${presentation.label}</span></div><div class="utc-progress"><i data-progress="${progress.toFixed(2)}" style="transform:scaleX(${scale.toFixed(4)});opacity:${row.progressKnown === false ? 0 : 1}"></i></div><div class="utc-meta"><span>${esc(leftMeta)}</span><span>${esc(formatTime(row.updatedAt))}</span></div>${detail}${actions?`<div class="utc-actions">${actions}</div>`:''}</div>`;
}

function createUploadTaskCenterRow(body, html) {
  const doc = body?.ownerDocument || globalThis.document;
  if (!doc?.createElement) return null;
  const holder = doc.createElement('div');
  holder.innerHTML = String(html || '').trim();
  return holder.firstElementChild || null;
}

function patchUploadTaskCenterRow(currentRow, nextRow) {
  const currentName = currentRow?.querySelector?.('.utc-name b');
  const nextName = nextRow?.querySelector?.('.utc-name b');
  const currentStage = currentRow?.querySelector?.('.utc-name small');
  const nextStage = nextRow?.querySelector?.('.utc-name small');
  const currentPill = currentRow?.querySelector?.('.utc-pill');
  const nextPill = nextRow?.querySelector?.('.utc-pill');
  const currentBar = currentRow?.querySelector?.('.utc-progress i');
  const nextBar = nextRow?.querySelector?.('.utc-progress i');
  const currentMeta = currentRow?.querySelectorAll?.('.utc-meta span') || [];
  const nextMeta = nextRow?.querySelectorAll?.('.utc-meta span') || [];

  if (!currentName || !nextName || !currentStage || !nextStage || !currentPill || !nextPill || !currentBar || !nextBar) {
    return nextRow;
  }

  currentName.textContent = nextName.textContent;
  currentStage.textContent = nextStage.textContent;
  currentPill.className = nextPill.className;
  currentPill.textContent = nextPill.textContent;
  currentBar.dataset.progress = nextBar.dataset.progress || '';
  currentBar.style.transform = nextBar.style.transform;
  currentBar.style.opacity = nextBar.style.opacity;
  if (currentMeta[0] && nextMeta[0]) currentMeta[0].textContent = nextMeta[0].textContent;
  if (currentMeta[1] && nextMeta[1]) currentMeta[1].textContent = nextMeta[1].textContent;
  currentRow.className = nextRow.className;
  currentRow.dataset.utcKind = nextRow.dataset.utcKind || '';
  currentRow.dataset.utcLocal = nextRow.dataset.utcLocal || '0';
  if (nextRow.hasAttribute?.('role')) {
    currentRow.setAttribute('role', nextRow.getAttribute('role'));
    currentRow.setAttribute('tabindex', nextRow.getAttribute('tabindex'));
    currentRow.setAttribute('aria-label', nextRow.getAttribute('aria-label'));
  } else {
    currentRow.removeAttribute?.('role');
    currentRow.removeAttribute?.('tabindex');
    currentRow.removeAttribute?.('aria-label');
  }

  const currentDetail = currentRow.querySelector?.('.utc-detail');
  const nextDetail = nextRow.querySelector?.('.utc-detail');
  if (currentDetail && nextDetail) {
    currentDetail.textContent = nextDetail.textContent;
    currentDetail.title = nextDetail.title;
  } else if (currentDetail && !nextDetail) {
    currentDetail.remove();
  } else if (!currentDetail && nextDetail) {
    currentRow.appendChild(nextDetail.cloneNode(true));
  }
  const currentActions = currentRow.querySelector?.('.utc-actions');
  const nextActions = nextRow.querySelector?.('.utc-actions');
  if (currentActions && nextActions) {
    const wanted = new Set();
    for (const next of nextActions.children) {
      const key = next.dataset.utcAction;
      wanted.add(key);
      const current = [...currentActions.children].find(node => node.dataset.utcAction === key);
      if (current) {
        current.className = next.className;
        if (!current.disabled) current.textContent = next.textContent;
      } else currentActions.appendChild(next.cloneNode(true));
    }
    for (const current of [...currentActions.children]) {
      if (!wanted.has(current.dataset.utcAction)) current.remove();
    }
  }
  else if (currentActions && !nextActions) currentActions.remove();
  else if (!currentActions && nextActions) currentRow.appendChild(nextActions.cloneNode(true));
  return currentRow;
}

export function patchUploadTaskCenterRows(body, visibleRows = []) {
  if (!body) return false;
  const list = Array.isArray(visibleRows) ? visibleRows : [];
  const doc = body?.ownerDocument || globalThis.document;
  const canPatch = Boolean(
    doc?.createElement
    && typeof body.querySelectorAll === 'function'
    && typeof body.insertBefore === 'function'
    && body.children,
  );

  if (!canPatch) {
    body.innerHTML = list.length
      ? list.map(renderUploadTaskCenterRow).join('')
      : '<div class="utc-empty">暂无上传任务</div>';
    return true;
  }

  if (!list.length) {
    if (!body.querySelector?.('.utc-empty')) body.innerHTML = '<div class="utc-empty">暂无上传任务</div>';
    return true;
  }

  body.querySelector?.('.utc-empty')?.remove?.();
  const existing = new Map(
    [...body.querySelectorAll('.utc-row[data-utc-id]')]
      .map(row => [String(row.dataset?.utcId || ''), row]),
  );
  const wanted = new Set();

  list.forEach((row, index) => {
    const id = String(row?.id || '');
    const nextRow = createUploadTaskCenterRow(body, renderUploadTaskCenterRow(row));
    if (!id || !nextRow) return;
    wanted.add(id);

    let currentRow = existing.get(id) || null;
    if (!currentRow) {
      currentRow = nextRow;
    } else {
      const patched = patchUploadTaskCenterRow(currentRow, nextRow);
      if (patched !== currentRow) {
        currentRow.replaceWith?.(patched);
        currentRow = patched;
      }
    }

    const reference = body.children[index] || null;
    if (reference !== currentRow) body.insertBefore(currentRow, reference);
  });

  for (const [id, row] of existing) {
    if (!wanted.has(id)) row.remove?.();
  }
  return true;
}

async function responseJson(response) {
  if (response.ok) return response.json();
  const text = await response.text();
  let body = {};
  try { body = JSON.parse(text); } catch (_) { body = {detail:text}; }
  throw new Error(String(body?.message || body?.detail || `HTTP ${response.status}`));
}

export function installUploadTaskCenter({getState, projectId, notify, fetchImpl = globalThis.fetch, pollRegistry, ownerPages} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;
  if (window.UploadTaskCenterRuntime?.build === 'upload-task-center-4') return window.UploadTaskCenterRuntime;

  let rows = [];
  let expanded = false;
  let lastProjectId = '';
  let renderFrame = 0;
  let persistTimer = 0;
  let destroyed = false;
  const pendingActions = new Map();
  let clearPending = false;
  const registry = pollRegistry || window.PollRegistryRuntime;
  const POLL_KEY = 'upload-task-center';
  const fallbackOwners = [
    '工作台','质量中心','算法列表','训练任务','素材接入','数据集','视频切帧','自动标注及清洗',
    '测试发布','检测台','标签管理','部署转换','部署产物','模型配置','训练资源','部署资源',
    '部署插件','组件检测','存储配置','平台对接','服务节点',
  ];
  const pollOwners = Array.isArray(ownerPages) && ownerPages.length ? [...ownerPages] : fallbackOwners;

  const pid = () => String(projectId?.() || getState?.()?.project?.id || '');
  const storageKey = project => `${STORAGE_PREFIX}${project}`;

  function ensureStyle() {
    if (document.getElementById('uploadTaskCenterStyles')) return;
    const style = document.createElement('style');
    style.id = 'uploadTaskCenterStyles';
    style.textContent = `
      .utc-root{position:fixed;right:20px;bottom:18px;z-index:1300;width:min(430px,calc(100vw - 28px));font-size:13px;color:var(--text,#18212f)}
      /* Keep upload details interactive above their own ZIP modal; unrelated dialogs win. */
      body:has(.modal:not(.hidden):not(.import350-modal)) .utc-root{z-index:900}
      /* An expanded ZIP label confirmation owns its action buttons.
         Keep the upload dock on top only during upload/minimized import. */
      body:has(.modal.import350-modal:not(.hidden):not(.import350-minimized) .zip-label-confirm) .utc-root{z-index:900}
      .utc-shell{border:1px solid #dfe5ee;border-radius:16px;background:rgba(255,255,255,.98);box-shadow:0 18px 50px rgba(15,23,42,.14);backdrop-filter:blur(16px);overflow:hidden}
      .utc-head{width:100%;display:flex;align-items:center;gap:10px;border:0;background:linear-gradient(180deg,#fff,#f8fafc);color:inherit;padding:10px 12px;text-align:left}.utc-toggle{min-width:0;flex:1;display:flex;align-items:center;justify-content:space-between;gap:12px;border:0;background:transparent;color:inherit;padding:3px;cursor:pointer;text-align:left}.utc-head-actions{display:flex;align-items:center;gap:7px}.utc-clear{border:1px solid #d8e0ea;border-radius:8px;background:#fff;color:#536174;padding:6px 8px;font-size:11px;cursor:pointer}.utc-clear:hover{background:#f3f6fa}.utc-clear:disabled{opacity:.45;cursor:not-allowed}
      .utc-head strong{font-size:14px}.utc-head span{display:block;color:#728096;font-size:12px;margin-top:2px}.utc-count{min-width:26px;height:26px;border-radius:999px;display:grid;place-items:center;background:#eaf2ff;color:#2563eb;font-weight:800}
      .utc-body{border-top:1px solid #e7ebf1;max-height:390px;overflow:auto;background:#fff}.utc-row{padding:12px 14px;border-bottom:1px solid #edf0f4}.utc-row:last-child{border-bottom:0}
      .utc-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.utc-name{min-width:0}.utc-name b{display:block;color:#192231;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.utc-name small{display:block;color:#748197;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .utc-pill{flex:none;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:800}.utc-pill.ok{background:#ecfdf3;color:#15803d}.utc-pill.bad{background:#fff1f2;color:#be123c}.utc-pill.warn{background:#fff7ed;color:#c2410c}.utc-pill.run{background:#eff6ff;color:#2563eb}.utc-pill.muted{background:#f1f5f9;color:#64748b}
      .utc-progress{height:6px;border-radius:999px;background:#edf1f5;overflow:hidden;margin:9px 0 7px}.utc-progress i{display:block;width:100%;height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa);border-radius:inherit;transform-origin:left center;transition:transform .22s cubic-bezier(.22,1,.36,1);will-change:transform}
      .utc-meta{display:flex;justify-content:space-between;gap:10px;color:#738197;font-size:11px}.utc-detail{margin-top:5px;color:#64748b;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.utc-empty{padding:24px;text-align:center;color:#8995a7}.utc-reopenable{cursor:pointer}.utc-reopenable:hover{background:#f8fafc}
      .utc-actions{display:flex;justify-content:flex-end;gap:7px;margin-top:9px}.utc-action{min-height:32px;padding:5px 10px;border:1px solid #d6deea;border-radius:8px;background:#fff;color:#334155;font-size:12px;font-weight:700;cursor:pointer}.utc-action:hover{background:#f8fafc}.utc-action:disabled{cursor:wait;opacity:.65}.utc-action.primary{border-color:#bfdbfe;background:#eff6ff;color:#1d4ed8}.utc-action.danger{border-color:#fecdd3;background:#fff1f2;color:#be123c}
      @media (prefers-reduced-motion: reduce){.utc-progress i{transition:none!important}}
      @media(max-width:720px){.utc-root{right:10px;bottom:10px;width:calc(100vw - 20px)}}
    `;
    document.head.appendChild(style);
  }

  function ensureRoot() {
    ensureStyle();
    let root = document.getElementById('uploadTaskCenter');
    if (!root) {
      root = document.createElement('div');
      root.id = 'uploadTaskCenter';
      root.className = 'utc-root';
      document.body.appendChild(root);
    }
    return root;
  }

  function persist(project = lastProjectId) {
    window.clearTimeout(persistTimer);
    persistTimer = 0;
    if (!project) return;
    const persistedRows = retainUploadTaskRows(rows).map(row => { const value = {...row}; delete value.pollOwner; return value; });
    try { localStorage.setItem(storageKey(project), JSON.stringify(persistedRows)); } catch (_) {}
  }

  function publish(critical = false) {
    if (destroyed) return;
    if (critical) {
      window.cancelAnimationFrame(renderFrame);
      renderFrame = 0;
      persist();
      render();
    } else {
      if (!renderFrame) renderFrame = window.requestAnimationFrame(() => {
        renderFrame = 0;
        if (!destroyed) render();
      });
      if (!persistTimer) persistTimer = window.setTimeout(() => persist(), 500);
    }
  }

  function load(project) {
    rows = [];
    if (!project) return;
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey(project)) || '[]');
      if (Array.isArray(parsed)) rows = retainUploadTaskRows(parsed.map(row => mergeUploadTask({}, row)));
    } catch (_) { rows = []; }
    rows = rows.map(recoverUploadTaskAfterRefresh);
    rows = stableUploadTaskOrder(rows);
  }

  function ensureShell(root) {
    let shell = root.querySelector?.('.utc-shell');
    if (shell) return shell;

    root.innerHTML = `<div class="utc-shell">
      <div class="utc-head"><button class="utc-toggle" type="button" data-utc-toggle aria-expanded="false"><div><strong data-utc-title>上传任务 0 个</strong><span data-utc-summary role="status" aria-live="polite"></span></div></button><div class="utc-head-actions"><button class="utc-clear" type="button" data-utc-clear disabled>清空已结束</button><div class="utc-count" data-utc-count>0</div></div></div>
      <div class="utc-body" data-utc-body style="display:none"></div>
    </div>`;
    shell = root.querySelector?.('.utc-shell');
    root.querySelector?.('[data-utc-toggle]')?.addEventListener('click', () => {
      expanded = !expanded;
      render();
    });
    root.querySelector?.('[data-utc-clear]')?.addEventListener('click', event => {
      event.stopPropagation();
      void clearCompleted();
    });
    const openTask = event => {
      const button = event.target?.closest?.('[data-utc-action]');
      // Native buttons synthesize their own keyboard click. Never invoke twice.
      if (event.type === 'keydown' && button) return;
      const element = event.target?.closest?.('.utc-row[data-utc-id]');
      const task = rows.find(row => row.id === element?.dataset.utcId);
      if (!task) return;
      const name = button?.dataset.utcAction || (task.kind === 'zip' && !task.localOnly ? 'open' : '');
      if (!name) return;
      event.preventDefault(); event.stopPropagation();
      void performAction(task, name, button);
    };
    root.querySelector?.('[data-utc-body]')?.addEventListener('click', openTask);
    root.querySelector?.('[data-utc-body]')?.addEventListener('keydown', event => {
      if (['Enter',' '].includes(event.key)) openTask(event);
    });
    return shell;
  }

  async function performAction(task, name, button) {
    if (pendingActions.has(task.id)) {
      if (name === 'open') void window.ZipImportRuntime?.openTask?.(task.id.replace(/^zip:/,''));
      return;
    }
    const operation = {project:pid(), id:task.id, action:name};
    pendingActions.set(task.id, operation);
    for (const sibling of button?.closest('.utc-actions')?.querySelectorAll('button') || []) sibling.disabled=true;
    if (button) { button.disabled = true; button.setAttribute('aria-busy','true'); button.textContent = '正在处理'; }
    try {
      if (name === 'details') {
        window.modal?.('图片任务详情', `<div class="utc-upload-details" data-utc-detail-id="${esc(task.id)}" data-utc-project="${esc(pid())}"><b>${esc(task.title)}</b><p data-utc-detail-stage>${esc(task.stage || statusPresentation(task.status).label)}</p><p data-utc-detail-message>${esc(task.detail)}</p><p data-utc-detail-progress>当前阶段进度：${clamp(task.progress)}%</p><small>任务 ID：${esc(task.id)}。网络传输完成不代表服务器入库完成；关闭本窗不会停止上传。</small></div>`, true);
        return;
      }
      const id = operation.id.replace(/^zip:/,'');
      const owner = window.ZipImportRuntime;
      const method = {'cancel-local':'cancelQueuedUpload',pause:'pauseUpload',cancel:'cancelUpload',resume:'promptResume',open:'openTask'}[name];
      if ((method && typeof owner?.[method] !== 'function') || (name === 'reselect' && typeof window.importData !== 'function')) {
        throw new Error('上传模块尚未就绪，请稍后重试');
      }
      const actions = {
        'cancel-local':()=>owner?.cancelQueuedUpload?.(id),
        pause:()=>owner?.pauseUpload?.(id), cancel:()=>owner?.cancelUpload?.(id),
        resume:()=>owner?.promptResume?.(id), reselect:()=>window.importData?.(),
        open:()=>owner?.openTask?.(id),
      };
      const request = Promise.resolve().then(() => actions[name]?.());
      const settled = () => {
        operation.settled = true;
        if (!operation.timedOut) return;
        if (pendingActions.get(operation.id) === operation) pendingActions.delete(operation.id);
        if (button?.isConnected) { button.disabled=false; button.removeAttribute('aria-busy'); }
        if (!destroyed && pid() === operation.project) render();
      };
      request.then(settled, settled);
      await withRequestDeadline(() => request, {timeoutMs:30000, label:'上传任务操作'});
    } catch (error) {
      operation.timedOut = error?.code === 'REQUEST_TIMEOUT' && !operation.settled;
      if (!destroyed && pid() === operation.project) notify?.(`操作未确认：${error?.message || error}；请查看任务状态，勿重复提交。`);
    } finally {
      if (!operation.timedOut && pendingActions.get(operation.id) === operation) pendingActions.delete(operation.id);
      if (button?.isConnected) {
        button.disabled = Boolean(operation.timedOut); button.removeAttribute('aria-busy');
        if (operation.timedOut) button.textContent = '等待结果确认';
      }
      if (!destroyed && pid() === operation.project) render();
    }
  }

  function render() {
    if (destroyed) return;
    for (const detail of document.querySelectorAll?.('.utc-upload-details[data-utc-detail-id]') || []) {
      if (detail.dataset.utcProject !== pid()) continue;
      const task = rows.find(row => row.id === detail.dataset.utcDetailId);
      if (!task) continue;
      detail.querySelector('[data-utc-detail-stage]').textContent = task.stage || statusPresentation(task.status).label;
      detail.querySelector('[data-utc-detail-message]').textContent = task.detail;
      detail.querySelector('[data-utc-detail-progress]').textContent = task.progressKnown === false ? '等待服务器进度' : `当前阶段进度：${clamp(task.progress)}%`;
    }
    const root = ensureRoot();
    if (!rows.length) {
      root.style.display = 'none';
      return;
    }

    root.style.display = '';
    ensureShell(root);
    const stats = summarizeUploadTasks(rows);
    const active = rows.filter(isUploadTaskActive);
    const visible = expanded ? rows : [];
    const latest = active[0] || rows[0];
    const terminalCount = rows.filter(row => TERMINAL_STATUSES.has(upper(row.status))).length;
    const summary = root.querySelector?.('[data-utc-summary]');
    const title = root.querySelector?.('[data-utc-title]');
    const count = root.querySelector?.('[data-utc-count]');
    const clear = root.querySelector?.('[data-utc-clear]');
    const toggle = root.querySelector?.('[data-utc-toggle]');
    const body = root.querySelector?.('[data-utc-body]');
    const processing = Math.max(0, stats.active - stats.uploading - stats.queued);

    if (title) title.textContent = `上传任务 ${stats.total} 个`;
    if (summary) summary.textContent = active.length
      ? [`上传中 ${stats.uploading}`,`排队 ${stats.queued}`,processing>0?`处理中 ${processing}`:''].filter(Boolean).join(' · ')
      : `最近任务 · ${latest ? formatTime(latest.updatedAt) : ''}`;
    if (count) count.textContent = String(active.length || rows.length);
    if (clear) clear.disabled = clearPending || terminalCount <= 0;
    if (toggle) toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    if (body) {
      body.style.display = expanded ? '' : 'none';
      if (expanded) {
        patchUploadTaskCenterRows(body, visible);
        for (const element of body.querySelectorAll('.utc-row')) {
          const pending = pendingActions.get(element.dataset.utcId);
          for (const button of element.querySelectorAll('[data-utc-action]')) {
            if (button.dataset.utcAction === 'open') continue;
            button.disabled = Boolean(pending);
            if (pending?.action === button.dataset.utcAction) {
              if (pending.timedOut) { button.removeAttribute('aria-busy'); button.textContent='等待结果确认'; }
              else { button.setAttribute('aria-busy','true'); button.textContent='正在处理'; }
            } else button.removeAttribute('aria-busy');
          }
        }
      }
    }
  }

  async function clearCompleted() {
    if (destroyed) return rows;
    if (clearPending) return rows;
    clearPending = true;
    const clearButton = document.querySelector('#uploadTaskCenter [data-utc-clear]');
    if (clearButton) { clearButton.disabled=true; clearButton.setAttribute('aria-busy','true'); }
    try {
    const before = rows.length;
    const project = pid();
    if (project && hasTerminalZipUploadTasks(rows)) {
      try {
        await withRequestDeadline(signal => fetchImpl(
          `/api/v19/projects/${encodeURIComponent(project)}/import/jobs`,
          {method:'DELETE', credentials:'same-origin', signal},
        ).then(responseJson), {timeoutMs:30000, label:'清空上传记录'});
        if (destroyed || project !== pid()) return rows;
        window.ZipImportRuntime?.forgetTerminal?.();
      } catch (error) {
        notify?.(`清空导入记录失败：${error?.message || error}`);
        return rows;
      }
    }
    rows = clearCompletedUploadTasks(rows);
    persist();
    render();
    arm();
    const cleared = Math.max(0, before - rows.length);
    if (cleared) notify?.(`已清空 ${cleared} 条已结束任务`);
    return rows;
    } finally { clearPending=false; clearButton?.removeAttribute('aria-busy'); render(); }
  }

  function upsert(task) {
    if (destroyed) return null;
    const id = String(task?.id || '');
    if (!id) throw new Error('upload task id is required');
    const index = rows.findIndex(row => row.id === id);
    const previous = index >= 0 ? rows[index] : null;
    const incoming = mergeUploadTask(previous || {}, task);
    if (index >= 0) rows[index] = incoming;
    else rows.unshift(incoming);
    if (!previous || previous.status !== incoming.status) rows = retainUploadTaskRows(rows);
    const critical = !previous || ['status','stage','browserTransfer','resumeRequired','localOnly'].some(key => previous[key] !== incoming[key]);
    publish(critical);
    if (critical) arm();
    return rows.find(row => row.id === incoming.id);
  }

  function rekey(oldId, newId) {
    if (destroyed) return null;
    const source = rows.find(row => row.id === String(oldId));
    if (!source || !newId || String(oldId) === String(newId)) return null;
    const target = rows.find(row => row.id === String(newId));
    const merged = target ? mergeUploadTask(source, target) : {...source};
    merged.id = String(newId);
    merged.createdAt = source.createdAt;
    merged.orderKey = source.orderKey;
    const element = [...(document.querySelectorAll('#uploadTaskCenter .utc-row') || [])].find(row => row.dataset.utcId === String(oldId));
    if (element) element.dataset.utcId = String(newId);
    const pending = pendingActions.get(String(oldId));
    if (pending) { pendingActions.delete(String(oldId)); pending.id=String(newId); pendingActions.set(pending.id,pending); }
    rows = retainUploadTaskRows([...rows.filter(row => row.id !== String(oldId) && row.id !== String(newId)), merged]);
    persist();
    render();
    return merged;
  }

  function remove(id) {
    if (destroyed) return;
    rows = rows.filter(row => row.id !== String(id));
    persist();
    render();
  }

  async function refreshDurable(row) {
    if (!row?.serverUrl || row?.pollOwner || !isUploadTaskActive(row)) return row;
    try {
      const body = await responseJson(await fetchImpl(row.serverUrl, {credentials:'same-origin'}));
      return normalizeDurableUploadTask(body, row);
    } catch (error) {
      return mergeUploadTask(row, {detail:`状态刷新失败：${error?.message || error}`});
    }
  }

  async function poll() {
    if (destroyed) return;
    const project = pid();
    if (project !== lastProjectId) {
      switchProject();
    }
    const active = rows.filter(row => isUploadTaskActive(row) && row.serverUrl && !row.pollOwner);
    if (active.length) {
      const updates = await Promise.all(active.map(refreshDurable));
      if (destroyed || project !== pid() || project !== lastProjectId) return;
      for (const [position, updated] of updates.entries()) {
        const index = rows.findIndex(row => row.id === updated.id);
        if (index >= 0 && rows[index] === active[position]) rows[index] = updated;
      }
      rows = retainUploadTaskRows(rows);
      persist();
      render();
    }
    arm();
  }

  function arm() {
    if (destroyed) return null;
    registry?.clear?.(POLL_KEY);
    const needsPoll = rows.some(row => isUploadTaskActive(row) && row.serverUrl && !row.pollOwner);
    if (!needsPoll || document.visibilityState === 'hidden' || !registry?.startTimeout) return null;
    return registry?.startTimeout(POLL_KEY, pollOwners, () => poll().catch(() => arm()), POLL_MS);
  }

  function switchProject() {
    if (destroyed) return;
    const project = pid();
    if (project === lastProjectId) {
      arm();
      return;
    }
    persist();
    window.cancelAnimationFrame(renderFrame); renderFrame=0;
    pendingActions.clear();
    lastProjectId = project;
    load(project);
    persist();
    render();
    arm();
  }

  const onVisibilityChange = () => {
    if (document.visibilityState === 'hidden') { persist(); registry?.clear?.(POLL_KEY); }
    else arm();
  };
  document.addEventListener?.('visibilitychange', onVisibilityChange);
  const onPageHide = () => persist();
  window.addEventListener?.('pagehide', onPageHide);

  const runtime = Object.freeze({
    build:'upload-task-center-4',
    upsert,
    rekey,
    remove,
    clearCompleted,
    list:() => rows.map(row => ({...row})),
    refresh:() => poll(),
    switchProject,
    destroy() {
      persist(); destroyed=true;
      window.cancelAnimationFrame(renderFrame); renderFrame=0;
      window.removeEventListener?.('pagehide', onPageHide);
      registry?.clear?.(POLL_KEY);
      document.removeEventListener?.('visibilitychange', onVisibilityChange);
      document.getElementById('uploadTaskCenter')?.remove();
      if (window.UploadTaskCenterRuntime === runtime) window.UploadTaskCenterRuntime = null;
    },
  });
  window.UploadTaskCenterRuntime = runtime;
  lastProjectId = pid();
  load(lastProjectId);
  persist();
  render();
  arm();
  return runtime;
}
