const ACTIVE_STATUSES = new Set(['UPLOADING','MERGING','VALIDATING','SELECTING','QUEUED','WAITING','WAITING_RESOURCE','RUNNING','SCANNING','EXTRACTING','MAPPING_LABELS','WRITING_ANNOTATIONS','INDEXING','FINALIZING']);
const TERMINAL_STATUSES = new Set(['DONE','SUCCEEDED','COMPLETED','FINISHED','FAILED','CANCELLED','CANCELED','INTERRUPTED']);
const STORAGE_PREFIX = 'mc_upload_task_center_v1:';
const POLL_MS = 1200;
const MAX_ROWS = 20;

const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const clamp = value => Math.max(0, Math.min(100, Number(value) || 0));
const upper = value => String(value || '').trim().toUpperCase();
const nowIso = () => new Date().toISOString();

function formatTime(value) {
  const date = new Date(value || '');
  if (Number.isNaN(date.getTime())) return '';
  return date.toLocaleTimeString('zh-CN', {hour12:false, hour:'2-digit', minute:'2-digit', second:'2-digit'});
}

function statusPresentation(status) {
  const key = upper(status);
  if (['DONE','SUCCEEDED','COMPLETED','FINISHED'].includes(key)) return {label:'已完成', cls:'ok'};
  if (['FAILED','INTERRUPTED'].includes(key)) return {label:'失败', cls:'bad'};
  if (['CANCELLED','CANCELED'].includes(key)) return {label:'已取消', cls:'muted'};
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

export function mergeUploadTask(previous = {}, next = {}) {
  const status = upper(next.status || previous.status || 'UPLOADING');
  const progress = status === 'SUCCEEDED' || status === 'DONE' || status === 'COMPLETED' || status === 'FINISHED'
    ? 100 : clamp(next.progress ?? previous.progress ?? 0);
  return {
    ...previous,
    ...next,
    id: String(next.id || previous.id || ''),
    kind: String(next.kind || previous.kind || 'upload'),
    title: String(next.title || previous.title || '上传任务'),
    status,
    progress,
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

export function renderUploadTaskCenterRow(row = {}) {
  const presentation = statusPresentation(row.status);
  const progress = clamp(row.progress);
  const scale = progress / 100;
  const detail = row.detail
    ? `<div class="utc-detail" title="${esc(row.detail)}">${esc(row.detail)}</div>`
    : '';
  return `<div class="utc-row" data-utc-id="${esc(row.id)}"><div class="utc-top"><div class="utc-name"><b>${esc(row.title)}</b><small>${esc(row.stage || presentation.label)}</small></div><span class="utc-pill ${presentation.cls}">${presentation.label}</span></div><div class="utc-progress"><i data-progress="${progress.toFixed(2)}" style="transform:scaleX(${scale.toFixed(4)})"></i></div><div class="utc-meta"><span>${progress.toFixed(progress % 1 ? 1 : 0)}%</span><span>${esc(formatTime(row.updatedAt))}</span></div>${detail}</div>`;
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
  if (currentMeta[0] && nextMeta[0]) currentMeta[0].textContent = nextMeta[0].textContent;
  if (currentMeta[1] && nextMeta[1]) currentMeta[1].textContent = nextMeta[1].textContent;

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
  if (window.UploadTaskCenterRuntime?.build === 'upload-task-center-3') return window.UploadTaskCenterRuntime;

  let rows = [];
  let expanded = false;
  let lastProjectId = '';
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
      .utc-root{position:fixed;right:20px;bottom:18px;z-index:900;width:min(430px,calc(100vw - 28px));font-size:13px;color:var(--text,#18212f)}
      .utc-shell{border:1px solid #dfe5ee;border-radius:16px;background:rgba(255,255,255,.98);box-shadow:0 18px 50px rgba(15,23,42,.14);backdrop-filter:blur(16px);overflow:hidden}
      .utc-head{width:100%;display:flex;align-items:center;gap:10px;border:0;background:linear-gradient(180deg,#fff,#f8fafc);color:inherit;padding:10px 12px;text-align:left}.utc-toggle{min-width:0;flex:1;display:flex;align-items:center;justify-content:space-between;gap:12px;border:0;background:transparent;color:inherit;padding:3px;cursor:pointer;text-align:left}.utc-head-actions{display:flex;align-items:center;gap:7px}.utc-clear{border:1px solid #d8e0ea;border-radius:8px;background:#fff;color:#536174;padding:6px 8px;font-size:11px;cursor:pointer}.utc-clear:hover{background:#f3f6fa}.utc-clear:disabled{opacity:.45;cursor:not-allowed}
      .utc-head strong{font-size:14px}.utc-head span{display:block;color:#728096;font-size:12px;margin-top:2px}.utc-count{min-width:26px;height:26px;border-radius:999px;display:grid;place-items:center;background:#eaf2ff;color:#2563eb;font-weight:800}
      .utc-body{border-top:1px solid #e7ebf1;max-height:390px;overflow:auto;background:#fff}.utc-row{padding:12px 14px;border-bottom:1px solid #edf0f4}.utc-row:last-child{border-bottom:0}
      .utc-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.utc-name{min-width:0}.utc-name b{display:block;color:#192231;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.utc-name small{display:block;color:#748197;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .utc-pill{flex:none;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:800}.utc-pill.ok{background:#ecfdf3;color:#15803d}.utc-pill.bad{background:#fff1f2;color:#be123c}.utc-pill.warn{background:#fff7ed;color:#c2410c}.utc-pill.run{background:#eff6ff;color:#2563eb}.utc-pill.muted{background:#f1f5f9;color:#64748b}
      .utc-progress{height:6px;border-radius:999px;background:#edf1f5;overflow:hidden;margin:9px 0 7px}.utc-progress i{display:block;width:100%;height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa);border-radius:inherit;transform-origin:left center;transition:transform .22s cubic-bezier(.22,1,.36,1);will-change:transform}
      .utc-meta{display:flex;justify-content:space-between;gap:10px;color:#738197;font-size:11px}.utc-detail{margin-top:5px;color:#64748b;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.utc-empty{padding:24px;text-align:center;color:#8995a7}
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

  function persist() {
    const project = pid();
    if (!project) return;
    const persistedRows = rows.slice(0, MAX_ROWS).map(row => { const value = {...row}; delete value.pollOwner; return value; });
    try { localStorage.setItem(storageKey(project), JSON.stringify(persistedRows)); } catch (_) {}
  }

  function load(project) {
    rows = [];
    if (!project) return;
    try {
      const parsed = JSON.parse(localStorage.getItem(storageKey(project)) || '[]');
      if (Array.isArray(parsed)) rows = parsed.map(row => mergeUploadTask({}, row)).slice(0, MAX_ROWS);
    } catch (_) { rows = []; }
    rows = rows.map(row => {
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
    });
  }

  function ensureShell(root) {
    let shell = root.querySelector?.('.utc-shell');
    if (shell) return shell;

    root.innerHTML = `<div class="utc-shell">
      <div class="utc-head"><button class="utc-toggle" type="button" data-utc-toggle aria-expanded="false"><div><strong>数据导入 / 上传</strong><span data-utc-summary></span></div></button><div class="utc-head-actions"><button class="utc-clear" type="button" data-utc-clear disabled>清空已结束</button><div class="utc-count" data-utc-count>0</div></div></div>
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
    return shell;
  }

  function render() {
    const root = ensureRoot();
    if (!rows.length) {
      root.style.display = 'none';
      return;
    }

    root.style.display = '';
    ensureShell(root);
    const active = rows.filter(isUploadTaskActive);
    const visible = expanded ? rows.slice(0, 10) : [];
    const latest = active[0] || rows[0];
    const terminalCount = rows.filter(row => TERMINAL_STATUSES.has(upper(row.status))).length;
    const summary = root.querySelector?.('[data-utc-summary]');
    const count = root.querySelector?.('[data-utc-count]');
    const clear = root.querySelector?.('[data-utc-clear]');
    const toggle = root.querySelector?.('[data-utc-toggle]');
    const body = root.querySelector?.('[data-utc-body]');

    if (summary) summary.textContent = active.length
      ? `${active.length} 个任务进行中`
      : `最近任务 · ${latest ? formatTime(latest.updatedAt) : ''}`;
    if (count) count.textContent = String(active.length || rows.length);
    if (clear) clear.disabled = terminalCount <= 0;
    if (toggle) toggle.setAttribute('aria-expanded', expanded ? 'true' : 'false');
    if (body) {
      body.style.display = expanded ? '' : 'none';
      if (expanded) patchUploadTaskCenterRows(body, visible);
    }
  }

  async function clearCompleted() {
    const before = rows.length;
    const project = pid();
    if (project && hasTerminalZipUploadTasks(rows)) {
      try {
        await responseJson(await fetchImpl(
          `/api/v19/projects/${encodeURIComponent(project)}/import/jobs`,
          {method:'DELETE', credentials:'same-origin'},
        ));
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
  }

  function upsert(task) {
    const incoming = mergeUploadTask({}, task);
    if (!incoming.id) throw new Error('upload task id is required');
    const index = rows.findIndex(row => row.id === incoming.id);
    if (index >= 0) rows[index] = mergeUploadTask(rows[index], incoming);
    else rows.unshift(incoming);
    rows.sort((a,b) => String(b.updatedAt).localeCompare(String(a.updatedAt)));
    rows = rows.slice(0, MAX_ROWS);
    persist();
    render();
    arm();
    return rows.find(row => row.id === incoming.id);
  }

  function remove(id) {
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
    const project = pid();
    if (project !== lastProjectId) {
      lastProjectId = project;
      load(project);
    }
    const active = rows.filter(row => isUploadTaskActive(row) && row.serverUrl && !row.pollOwner);
    if (active.length) {
      const updates = await Promise.all(active.map(refreshDurable));
      for (const updated of updates) {
        const index = rows.findIndex(row => row.id === updated.id);
        if (index >= 0) rows[index] = updated;
      }
      rows.sort((a,b) => String(b.updatedAt).localeCompare(String(a.updatedAt)));
      persist();
      render();
    }
    arm();
  }

  function arm() {
    registry?.clear?.(POLL_KEY);
    const needsPoll = rows.some(row => isUploadTaskActive(row) && row.serverUrl && !row.pollOwner);
    if (!needsPoll || document.visibilityState === 'hidden' || !registry?.startTimeout) return null;
    return registry.startTimeout(POLL_KEY, pollOwners, () => poll().catch(() => arm()), POLL_MS);
  }

  function switchProject() {
    const project = pid();
    if (project === lastProjectId) {
      arm();
      return;
    }
    lastProjectId = project;
    load(project);
    persist();
    render();
    arm();
  }

  const onVisibilityChange = () => {
    if (document.visibilityState === 'hidden') registry?.clear?.(POLL_KEY);
    else arm();
  };
  document.addEventListener?.('visibilitychange', onVisibilityChange);

  const runtime = Object.freeze({
    build:'upload-task-center-3',
    upsert,
    remove,
    clearCompleted,
    list:() => rows.map(row => ({...row})),
    refresh:() => poll(),
    switchProject,
    destroy() {
      registry?.clear?.(POLL_KEY);
      document.removeEventListener?.('visibilitychange', onVisibilityChange);
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
