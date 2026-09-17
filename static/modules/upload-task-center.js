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
      .utc-root{position:fixed;right:20px;bottom:18px;z-index:10025;width:min(390px,calc(100vw - 28px));font-size:13px;color:var(--text,#e5edf5)}
      .utc-shell{border:1px solid rgba(130,149,170,.24);border-radius:14px;background:rgba(15,23,34,.96);box-shadow:0 18px 55px rgba(0,0,0,.32);backdrop-filter:blur(16px);overflow:hidden}
      .utc-head{width:100%;display:flex;align-items:center;justify-content:space-between;gap:12px;border:0;background:transparent;color:inherit;padding:13px 15px;cursor:pointer;text-align:left}
      .utc-head strong{font-size:14px}.utc-head span{display:block;opacity:.62;font-size:12px;margin-top:2px}.utc-count{min-width:26px;height:26px;border-radius:999px;display:grid;place-items:center;background:rgba(59,130,246,.15);color:#9bc2ff;font-weight:700}
      .utc-body{border-top:1px solid rgba(130,149,170,.15);max-height:390px;overflow:auto}.utc-row{padding:12px 14px;border-bottom:1px solid rgba(130,149,170,.12)}.utc-row:last-child{border-bottom:0}
      .utc-top{display:flex;justify-content:space-between;gap:10px;align-items:flex-start}.utc-name{min-width:0}.utc-name b{display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.utc-name small{display:block;opacity:.62;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
      .utc-pill{flex:none;padding:3px 8px;border-radius:999px;font-size:11px;font-weight:700}.utc-pill.ok{background:rgba(34,197,94,.13);color:#7ae5a2}.utc-pill.bad{background:rgba(239,68,68,.13);color:#ff9a9a}.utc-pill.warn{background:rgba(245,158,11,.13);color:#ffd080}.utc-pill.run{background:rgba(59,130,246,.13);color:#9bc2ff}.utc-pill.muted{background:rgba(148,163,184,.12);color:#b8c4d1}
      .utc-progress{height:6px;border-radius:999px;background:rgba(148,163,184,.12);overflow:hidden;margin:9px 0 7px}.utc-progress i{display:block;height:100%;background:linear-gradient(90deg,#3b82f6,#60a5fa);border-radius:inherit;transition:width .22s ease}
      .utc-meta{display:flex;justify-content:space-between;gap:10px;opacity:.7;font-size:11px}.utc-detail{margin-top:5px;opacity:.72;font-size:12px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.utc-empty{padding:24px;text-align:center;opacity:.55}
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
    root.innerHTML = `<div class="utc-shell">
      <button class="utc-head" type="button" data-utc-toggle><div><strong>上传任务</strong><span>${active.length ? `${active.length} 个任务进行中` : `最近任务 · ${latest ? formatTime(latest.updatedAt) : ''}`}</span></div><div class="utc-count">${active.length || rows.length}</div></button>
      ${expanded ? `<div class="utc-body">${visible.length ? visible.map(row => {
        const presentation = statusPresentation(row.status);
        return `<div class="utc-row" data-utc-id="${esc(row.id)}"><div class="utc-top"><div class="utc-name"><b>${esc(row.title)}</b><small>${esc(row.stage || presentation.label)}</small></div><span class="utc-pill ${presentation.cls}">${presentation.label}</span></div><div class="utc-progress"><i style="width:${clamp(row.progress)}%"></i></div><div class="utc-meta"><span>${clamp(row.progress).toFixed(clamp(row.progress)%1 ? 1 : 0)}%</span><span>${esc(formatTime(row.updatedAt))}</span></div>${row.detail ? `<div class="utc-detail" title="${esc(row.detail)}">${esc(row.detail)}</div>` : ''}</div>`;
      }).join('') : '<div class="utc-empty">暂无上传任务</div>'}</div>` : ''}
    </div>`;
    root.querySelector('[data-utc-toggle]')?.addEventListener('click', () => { expanded = !expanded; render(); });
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
  window.__uploadTaskCenterProjectTimer = window.setInterval(switchProject, 1500);
  return runtime;
}
