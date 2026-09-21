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

async function responseJson(response) {
  if (response.ok) return response.json();
  const text = await response.text();
  let body = {};
  try { body = JSON.parse(text); } catch (_) { body = {detail:text}; }
  throw new Error(String(body?.message || body?.detail || `HTTP ${response.status}`));
}

export function installUploadTaskCenter({getState, projectId, notify, fetchImpl = globalThis.fetch} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;
  if (window.UploadTaskCenterRuntime?.build === 'upload-task-center-1') return window.UploadTaskCenterRuntime;

  let rows = [];
  let expanded = false;
  let timer = null;
  let lastProjectId = '';

  const pid = () => String(projectId?.() || getState?.()?.project?.id || '');
  const storageKey = project => `${STORAGE_PREFIX}${project}`;

  function ensureStyle() {
    if (document.getElementById('uploadTaskCenterStyles')) return;
    const style = document.createElement('style');
    style.id = 'uploadTaskCenterStyles';
    style.textContent = `
      .utc-root{position:fixed;right:20px;bottom:18px;z-index:10025;width:min(430px,calc(100vw - 28px));font-size:13px;color:var(--text,#18212f)}
      .utc-shell{border:1px solid #dfe5ee;border-radius:16px;background:rgba(255,255,255,.98);box-shadow:0 18px 50px rgba(15,23,42,.14);backdrop-filter:blur(16px);overflow:hidden}
      .utc-head{width:100%;display:flex;align-items:center;gap:10px;border:0;background:linear-gradient(180deg,#fff,#f8fafc);color:inherit;padding:10px 12px;text-align:left}.utc-toggle{min-width:0;flex:1;display:flex;align-items:center;justify-content:space-between;gap:12px;border:0;background:transparent;color:inherit;padding:3px;cursor:pointer;text-align:left}.utc-head-actions{display:flex;align-items:center;gap:7px}.utc-clear{border:1px solid #d8e0ea;border-radius:8px;background:#fff;color:#536174;padding:6px 8px;font-size:11px;cursor:pointer}.utc-clear:hover{background:#f3f6fa}.utc-clear:disabled{opacity:.45;cursor:not-allowed}
      .utc-head strong{font-size:14px}.utc-head span{display:block;color:#728096;font-size:12px;margin-top:2px}.utc-count{min-width:26px;height:26px;border-radius:999px;display:grid;place-items:center;background:#eaf2ff;color:#2563eb;font-weight:800}
      .utc-body{border-top:1px solid #e7ebf1;max-height:390px;overflow:auto;background:#fff}.utc-row{padding:12px 14px;border-bottom:1px solid #edf0f4}.utc-row:last-child{border-bottom:0}
      .utc-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.utc-name{min-width:0}.utc-name b{display:block;color:#192231;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.utc-name small{display:block;color:#748197;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .utc-pill{flex:none;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:800}.utc-pill.ok{background:#ecfdf3;color:#15803d}.utc-pill.bad{background:#fff1f2;color:#be123c}.utc-pill.warn{background:#fff7ed;color:#c2410c}.utc-pill.run{background:#eff6ff;color:#2563eb}.utc-pill.muted{background:#f1f5f9;color:#64748b}
      .utc-progress{height:6px;border-radius:999px;background:#edf1f5;overflow:hidden;margin:9px 0 7px}.utc-progress i{display:block;height:100%;background:linear-gradient(90deg,#2563eb,#60a5fa);border-radius:inherit;transition:width .22s ease}
      .utc-meta{display:flex;justify-content:space-between;gap:10px;color:#738197;font-size:11px}.utc-detail{margin-top:5px;color:#64748b;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.utc-empty{padding:24px;text-align:center;color:#8995a7}
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
    try { localStorage.setItem(storageKey(project), JSON.stringify(rows.slice(0, MAX_ROWS))); } catch (_) {}
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

  function render() {
    const root = ensureRoot();
    const active = rows.filter(isUploadTaskActive);
    const visible = rows.slice(0, expanded ? 10 : 0);
    const latest = active[0] || rows[0];
    if (!rows.length) {
      root.innerHTML = '';
      root.style.display = 'none';
      return;
    }
    root.style.display = '';
    const terminalCount = rows.filter(row => TERMINAL_STATUSES.has(upper(row.status))).length;
    root.innerHTML = `<div class="utc-shell">
      <div class="utc-head"><button class="utc-toggle" type="button" data-utc-toggle><div><strong>数据导入 / 上传</strong><span>${active.length ? `${active.length} 个任务进行中` : `最近任务 · ${latest ? formatTime(latest.updatedAt) : ''}`}</span></div></button><div class="utc-head-actions"><button class="utc-clear" type="button" data-utc-clear ${terminalCount ? '' : 'disabled'}>清空已完成</button><div class="utc-count">${active.length || rows.length}</div></div></div>
      ${expanded ? `<div class="utc-body">${visible.length ? visible.map(row => {
        const presentation = statusPresentation(row.status);
        return `<div class="utc-row" data-utc-id="${esc(row.id)}"><div class="utc-top"><div class="utc-name"><b>${esc(row.title)}</b><small>${esc(row.stage || presentation.label)}</small></div><span class="utc-pill ${presentation.cls}">${presentation.label}</span></div><div class="utc-progress"><i style="width:${clamp(row.progress)}%"></i></div><div class="utc-meta"><span>${clamp(row.progress).toFixed(clamp(row.progress)%1 ? 1 : 0)}%</span><span>${esc(formatTime(row.updatedAt))}</span></div>${row.detail ? `<div class="utc-detail" title="${esc(row.detail)}">${esc(row.detail)}</div>` : ''}</div>`;
      }).join('') : '<div class="utc-empty">暂无上传任务</div>'}</div>` : ''}
    </div>`;
    root.querySelector('[data-utc-toggle]')?.addEventListener('click', () => { expanded = !expanded; render(); });
    root.querySelector('[data-utc-clear]')?.addEventListener('click', event => { event.stopPropagation(); void clearCompleted(); });
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
    if (cleared) notify?.(`已清空 ${cleared} 条已完成任务`);
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
    if (!row?.serverUrl || !isUploadTaskActive(row)) return row;
    try {
      const body = await responseJson(await fetchImpl(row.serverUrl, {credentials:'same-origin'}));
      return normalizeDurableUploadTask(body, row);
    } catch (error) {
      return mergeUploadTask(row, {detail:`状态刷新失败：${error?.message || error}`});
    }
  }

  async function poll() {
    timer = null;
    const project = pid();
    if (project !== lastProjectId) {
      lastProjectId = project;
      load(project);
    }
    const active = rows.filter(row => isUploadTaskActive(row) && row.serverUrl);
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
    if (timer) clearTimeout(timer);
    const needsPoll = rows.some(row => isUploadTaskActive(row) && row.serverUrl);
    if (needsPoll) timer = setTimeout(() => poll().catch(() => arm()), POLL_MS);
  }

  function switchProject() {
    const project = pid();
    if (project === lastProjectId) return;
    lastProjectId = project;
    load(project);
    persist();
    render();
    arm();
  }

  const runtime = Object.freeze({
    build:'upload-task-center-1',
    upsert,
    remove,
    clearCompleted,
    list:() => rows.map(row => ({...row})),
    refresh:() => poll(),
    switchProject,
  });
  window.UploadTaskCenterRuntime = runtime;
  lastProjectId = pid();
  load(lastProjectId);
  persist();
  render();
  arm();
  return runtime;
}
