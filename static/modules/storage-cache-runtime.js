import {buildStorageSourcePayload as hardenedBuildStorageSourcePayload} from './storage.js?v=422203';
import {withRequestDeadline} from './api.js?v=20261021s';

const REMOTE_TYPES = new Set(['oss', 's3', 'remote']);
const OBJECT_STORE_TYPES = new Set(['oss', 's3']);
const REPORT_HEARTBEAT_SKEW_MS = 5000;

export function storageCacheTruth(source) {
  const type = String(source?.type || 'local');
  if (!REMOTE_TYPES.has(type)) {
    return {
      remote: false,
      cacheLabel: '本地直读 · 训练 Bundle 缓存',
      protectionLabel: '本地源内容变化会在读取时校验',
      protectedWrites: false,
      externalMutationRequiresRescan: false,
    };
  }
  const protectedWrites = OBJECT_STORE_TYPES.has(type)
    && source?.config?.protect_existing_objects !== false;
  return {
    remote: true,
    cacheLabel: 'SHA256 素材内容缓存 · 训练 Bundle 缓存',
    protectionLabel: protectedWrites
      ? '平台写入禁止原地覆盖 · 外部变更需重新扫描'
      : '允许原地覆盖（不建议） · 外部变更需重新扫描',
    protectedWrites,
    externalMutationRequiresRescan: true,
  };
}

export function storageCacheSummary(source) {
  const truth = storageCacheTruth(source);
  return `${truth.cacheLabel} · ${truth.protectionLabel}`;
}

export function formatCacheBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024) return `${Math.round(bytes)} B`;
  const units = ['KB', 'MB', 'GB', 'TB'];
  let amount = bytes;
  let unit = 'B';
  for (const candidate of units) {
    amount /= 1024;
    unit = candidate;
    if (amount < 1024 || candidate === 'TB') break;
  }
  return `${amount >= 100 ? amount.toFixed(0) : amount >= 10 ? amount.toFixed(1) : amount.toFixed(2)} ${unit}`;
}

const LIFECYCLE_METRICS = [
  ['original_index_logical_bytes','原素材索引逻辑量','项目当前素材索引逻辑量'],
  ['gt_index_logical_bytes','GT 索引逻辑量','GT 索引文件逻辑量'],
  ['thumbnail_cache_logical_bytes','缩略图缓存逻辑量','配置缓存上次已索引缩略图逻辑量（失效指针孤立缓存不归属此项）'],
  ['shared_cache_logical_bytes','共享素材缓存逻辑量','配置素材缓存上次全部采样（可跨节点共享，不能直接算作节点独占）'],
  ['worker_workspace_logical_bytes','Worker 临时空间逻辑量','尚无可核验的占用快照'],
  ['reclaimable_logical_bytes','可回收逻辑量','尚无可核验的回收预览'],
  ['cleanup_pending_tasks','待清理任务','尚无可核验的任务统计'],
  ['cleanup_failed_tasks','清理失败任务','尚无可核验的任务统计'],
];

export function storageLifecycleView(summary) {
  return LIFECYCLE_METRICS.map(([key,label,scope])=>{
    const metric=summary?.metrics?.[key], value=metric?.value, count=key.endsWith('_tasks');
    const known=typeof value==='number' && Number.isFinite(value) && value>=0 && Number.isInteger(value);
    return {key,label,scope:String(metric?.scope || scope),value:known ? (count ? `${value} 项` : formatCacheBytes(value)) : '未获取'};
  });
}

function renderLifecycleSummary(value) {
  const shell=document.querySelector?.('.storage61-shell');
  if (!shell) return;
  let card=document.getElementById('storageLifecycleStatus61');
  if (!card) {
    card=document.createElement('section');card.id='storageLifecycleStatus61';card.className='panel';
    shell.appendChild(card);
  }
  const rows=storageLifecycleView(value?.payload);
  card.innerHTML=`<div class="panel-head"><div><div class="panel-title">存储生命周期占用</div><div class="item-sub">逻辑量不代表物理占用、独占空间或实际释放量；不同范围的指标不累加。</div></div><button class="btn" data-storage-lifecycle-refresh onclick="window.StorageCacheRuntime.refresh({force:true})" ${value?.loading ? 'disabled' : ''} aria-busy="${Boolean(value?.loading)}">${value?.loading ? '正在读取…' : '刷新占用信息'}</button></div><div class="panel-body" aria-live="polite">${value?.loading ? '<p role="status"><i class="loading-spinner" aria-hidden="true"></i> 正在读取可核验的存储占用…</p>' : ''}${value?.error ? `<p role="status">${value.payload ? '刷新失败，显示上次采样（旧数据）' : '占用信息未获取'}：${escapeHtml(value.error)}，可点击刷新重试。</p>` : ''}<div class="storage-lifecycle-metrics">${rows.map(row=>`<div class="stat" data-storage-lifecycle-metric="${row.key}"><div class="k">${row.label}</div><div class="v">${escapeHtml(row.value)}</div><small>${escapeHtml(row.scope)}</small></div>`).join('')}</div><p class="item-sub">采样时间：${value?.payload?.sampled_at ? escapeHtml(displayTime(value.payload.sampled_at)) : '未获取'} · 仅按需读取已有索引与采样，不触发全盘扫描。</p></div>`;
}

export function materialCacheStatusView(status) {
  if (!status || typeof status !== 'object' || status.inventory_complete === false) {
    return {
      available: false,
      usage: '未知',
      files: '-',
      limit: '-',
      ttl: '-',
      generatedAt: '',
      overBudget: false,
    };
  }
  const used = Math.max(0, Number(status.after_bytes) || 0);
  const max = Math.max(0, Number(status.max_bytes) || 0);
  const ttlSeconds = Math.max(0, Number(status.ttl_seconds) || 0);
  const files = Math.max(0, Number(status.scanned_files) || 0) - Math.max(0, Number(status.evicted_files) || 0);
  return {
    available: true,
    usage: formatCacheBytes(used),
    files: String(Math.max(0, files)),
    limit: max > 0 ? formatCacheBytes(max) : '不限制',
    ttl: ttlSeconds > 0 ? `${Math.round(ttlSeconds / 86400)} 天` : '不按 TTL 清理',
    generatedAt: String(status.generated_at || ''),
    overBudget: Number(status.over_budget_bytes || 0) > 0,
  };
}

function asTime(value) {
  const time = Date.parse(String(value || ''));
  return Number.isFinite(time) ? time : 0;
}

function scopeLabel(report) {
  if (report?.cache_root_source === 'MC_MATERIAL_CACHE_DIR') return '独立缓存目录';
  if (report?.cache_scope === 'data_dir_cache') return '数据目录兼容缓存';
  return report ? '缓存目录已上报' : '缓存目录未知';
}

export function materialCacheNodeRuntimeView(workers) {
  const rows = Array.isArray(workers) ? workers : [];
  const groups = new Map();
  for (const worker of rows) {
    const nodeId = String(worker?.node_id || 'legacy-unscoped');
    if (!groups.has(nodeId)) groups.set(nodeId, []);
    groups.get(nodeId).push(worker || {});
  }
  const nodes = [];
  for (const [nodeId, nodeWorkers] of groups.entries()) {
    const ordered = [...nodeWorkers].sort((a, b) => asTime(b?.heartbeat_at) - asTime(a?.heartbeat_at));
    const onlineWorkers = nodeWorkers.filter(item => item?.online === true);
    const reports = nodeWorkers
      .map(item => item?.material_cache)
      .filter(item => item && typeof item === 'object')
      .sort((a, b) => asTime(b?.reported_at) - asTime(a?.reported_at));
    const report = reports[0] || null;
    const reporterWorker = report
      ? nodeWorkers.find(item => item?.online === true && String(item?.worker_id || '') === String(report?.reporter_worker_id || ''))
      : null;
    const reportedAt = asTime(report?.reported_at);
    const reporterHeartbeatAt = asTime(reporterWorker?.heartbeat_at);
    const reporterFresh = Boolean(
      report
      && reporterWorker
      && reportedAt > 0
      && reporterHeartbeatAt > 0
      && reportedAt + REPORT_HEARTBEAT_SKEW_MS >= reporterHeartbeatAt
    );
    const snapshotView = materialCacheStatusView(report?.snapshot || null);
    let state = '未知';
    if (report && !reporterFresh) state = '上报已过期';
    else if (reporterFresh && report?.snapshot?.inventory_complete === false) state = '缓存采样不完整';
    else if (reporterFresh && !snapshotView.available) state = '等待维护快照';
    else if (reporterFresh && snapshotView.overBudget) state = '超出缓存配额';
    else if (reporterFresh && snapshotView.available) state = '已上报';
    nodes.push({
      nodeId,
      hostname: String(ordered[0]?.hostname || ''),
      workerCount: nodeWorkers.length,
      onlineWorkerCount: onlineWorkers.length,
      online: onlineWorkers.length > 0,
      report,
      reporterFresh,
      snapshot: snapshotView,
      state,
      scopeLabel: scopeLabel(report),
    });
  }
  nodes.sort((a, b) => Number(b.online) - Number(a.online) || a.hostname.localeCompare(b.hostname) || a.nodeId.localeCompare(b.nodeId));
  return {
    aggregation: 'per_node_only_no_sum',
    knownNodeCount: nodes.length,
    onlineNodeCount: nodes.filter(node => node.online).length,
    snapshotNodeCount: nodes.filter(node => node.snapshot.available && node.reporterFresh).length,
    unknownSnapshotNodeCount: nodes.filter(node => !node.snapshot.available || !node.reporterFresh).length,
    nodes,
  };
}

function apiErrorMessage(body, status) {
  if (body && typeof body === 'object') {
    return String(body.message || body.detail || `HTTP ${status}`);
  }
  return String(body || `HTTP ${status}`);
}

async function fetchWorkerRuntime(fetchImpl) {
  const response = await fetchImpl('/api/v62/workers', {cache: 'no-store'});
  if (!response.ok) throw new Error(`Worker 状态读取失败（HTTP ${response.status}）`);
  const payload = await response.json();
  if (!Array.isArray(payload?.items)) throw new Error('Worker 状态响应未核验');
  return payload.items;
}

function appendTruth(row, source) {
  if (!row || !source) return;
  const truth = storageCacheTruth(source);
  const firstCell = row.children?.[0];
  if (!firstCell) return;
  let node = firstCell.querySelector?.('[data-storage-cache-truth]');
  if (!node) {
    node = document.createElement('small');
    node.dataset.storageCacheTruth = '1';
    node.style.display = 'block';
    node.style.marginTop = '4px';
    node.style.lineHeight = '1.45';
    firstCell.appendChild(node);
  }
  node.textContent = `${truth.cacheLabel}；${truth.protectionLabel}`;
  node.dataset.protectedWrites = truth.protectedWrites ? '1' : '0';
}

function updatePageNote(sources) {
  const note = document.querySelector?.('.storage61-note span');
  if (!note) return;
  const hasRemote = sources.some(source => storageCacheTruth(source).remote);
  if (!hasRemote) return;
  note.textContent = '远程素材训练使用 SHA256 内容缓存并复用已验证的训练 Bundle。多 Worker 缓存状态按 node_id 去重展示；不同节点可能仍指向同一共享文件系统，因此平台不会伪造跨节点缓存总容量。OSS / S3 平台写入默认禁止覆盖同一 object_key，外部修改后需重新扫描确认。';
}

function escapeHtml(value) {
  return String(value ?? '')
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;');
}

function displayTime(value) {
  const text = String(value || '').trim();
  if (!text) return '-';
  return text.replace('T', ' ').replace('Z', '').slice(0, 19);
}

function renderCacheRuntime(workers, error = '') {
  const shell = document.querySelector?.('.storage61-shell');
  const sourcePanel = shell?.querySelector?.('.panel');
  if (!shell || !sourcePanel) return;
  let card = document.getElementById('storageCacheStatus61');
  if (!card) {
    card = document.createElement('section');
    card.id = 'storageCacheStatus61';
    card.className = 'panel';
    shell.insertBefore(card, sourcePanel);
  }
  const view = materialCacheNodeRuntimeView(workers);
  const nodeRows = view.nodes.length
    ? view.nodes.map(node => {
      const snapshot = node.snapshot;
      const pillClass = node.state === '已上报' ? 'ok' : node.state === '未知' || node.state === '等待维护快照' ? '' : 'warn';
      const reportTime = displayTime(node.report?.reported_at);
      const snapshotTime = displayTime(node.report?.snapshot_generated_at || snapshot.generatedAt);
      return `<div class="storage61-row" style="grid-template-columns:minmax(220px,1.6fr) repeat(5,minmax(110px,1fr));align-items:center">
        <div><b>${escapeHtml(node.hostname || node.nodeId)}</b><div class="item-sub">${escapeHtml(node.nodeId)} · 在线 Worker ${node.onlineWorkerCount}/${node.workerCount}</div></div>
        <div><span class="pill ${pillClass}">${escapeHtml(node.state)}</span><div class="item-sub">${escapeHtml(node.scopeLabel)}</div></div>
        <div><b>${escapeHtml(snapshot.usage)}</b><div class="item-sub">当前占用</div></div>
        <div><b>${escapeHtml(snapshot.files)}</b><div class="item-sub">缓存文件</div></div>
        <div><b>${escapeHtml(snapshot.limit)}</b><div class="item-sub">容量上限 · ${escapeHtml(snapshot.ttl)}</div></div>
        <div><b>${escapeHtml(snapshotTime)}</b><div class="item-sub">快照 · 上报 ${escapeHtml(reportTime)}</div></div>
      </div>`;
    }).join('')
    : `<div class="empty">${error ? 'Worker 节点状态未获取' : '尚无 Worker 节点缓存状态'}</div>`;
  card.innerHTML = `<div class="panel-head"><div><div class="panel-title">Worker 节点素材缓存</div><div class="item-sub">按 node_id 去重展示，不跨节点累加容量</div></div><span class="pill ${view.unknownSnapshotNodeCount ? 'warn' : view.snapshotNodeCount ? 'ok' : ''}">在线节点 ${view.onlineNodeCount} / 已知 ${view.knownNodeCount}</span></div>
    <div class="panel-body">${error ? `<p role="status">刷新失败，${workers.length ? '显示上次节点数据（旧数据）' : '节点状态未获取'}：${escapeHtml(error)}，可点击页面刷新重试。</p>` : ''}<div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-bottom:12px"><div class="stat"><div class="k">在线节点</div><div class="v">${view.onlineNodeCount}</div></div><div class="stat"><div class="k">有效缓存快照</div><div class="v">${view.snapshotNodeCount}</div></div><div class="stat"><div class="k">未知/过期</div><div class="v">${view.unknownSnapshotNodeCount}</div></div></div>${nodeRows}</div>`;
}

function editorType() {
  return String(document.getElementById?.('ss61Type')?.value || 'local');
}

function decorateEditor() {
  const fields = document.getElementById?.('ss61Fields');
  if (!fields) return;
  const existing = document.getElementById?.('ss61CachePolicy');
  const type = editorType();
  if (!REMOTE_TYPES.has(type)) {
    existing?.remove?.();
    return;
  }
  const source = {
    type,
    config: {protect_existing_objects: true},
  };
  const truth = storageCacheTruth(source);
  const block = existing || document.createElement('div');
  block.id = 'ss61CachePolicy';
  block.className = 'storage61-note';
  block.style.gridColumn = '1 / -1';
  block.innerHTML = `<b>缓存与对象保护</b><span>${truth.cacheLabel}。${truth.protectionLabel}。缓存命中不会在每次训练前逐张请求远端 HEAD；外部直接改源对象后，应先重新扫描确认。</span>`;
  if (!existing) fields.appendChild(block);
}

export function installStorageCacheRuntime({fetchImpl = globalThis.fetch, notify = () => {}, projectId = () => window.pid?.()} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return {refresh: async () => [], decorate: () => [], decorateEditor};
  }
  if (window.__storageCacheRuntimeInstalled) return window.StorageCacheRuntime;
  window.__storageCacheRuntimeInstalled = true;
  if (window.PlatformCore?.storage) {
    window.PlatformCore.storage.buildStorageSourcePayload = hardenedBuildStorageSourcePayload;
  }

  const WORKER_CACHE_TTL_MS = 2 * 60 * 1000;
  let latestSources = [];
  let latestWorkers = [];
  let workerError = '';
  let workersLoadedAt = 0;
  let workerInflight = null;
  const lifecycleStates = new Map();

  const snapshotSources = provided => {
    if (Array.isArray(provided)) return provided;
    const pageSnapshot = window.getStorageSourcesSnapshot61?.();
    return Array.isArray(pageSnapshot) ? pageSnapshot : latestSources;
  };

  const decorate = providedSources => {
    latestSources = [...snapshotSources(providedSources)];
    const container = document.getElementById('storage61Rows');
    if (container) {
      const rows = [...container.children].filter(row => row.classList?.contains('storage61-row'));
      latestSources.forEach((source, index) => appendTruth(rows[index], source));
    }
    updatePageNote(latestSources);
    renderCacheRuntime(latestWorkers, workerError);
    if (projectId?.()) renderLifecycleSummary(lifecycleStates.get(String(projectId())));
    decorateEditor();
    return latestSources;
  };

  const refreshWorkers = async ({force = false} = {}) => {
    const age = Date.now() - workersLoadedAt;
    if (!force && workersLoadedAt > 0 && age >= 0 && age < WORKER_CACHE_TTL_MS) return latestWorkers;
    if (workerInflight) return workerInflight;
    workerInflight = withRequestDeadline(signal=>fetchWorkerRuntime((url,options)=>fetchImpl(url,{...options,signal})),{label:'Worker 缓存状态'})
      .then(workers => {
        latestWorkers = workers;
        workerError = '';
        workersLoadedAt = Date.now();
        return latestWorkers;
      })
      .catch(error => {
        workerError = String(error?.message || error);
        // Throttle failed/cancelled transport attempts as well: a quick page
        // revisit must not immediately duplicate a worker discovery request.
        // The explicit refresh action may still bypass the TTL.
        workersLoadedAt = Date.now();
        throw error;
      })
      .finally(() => { workerInflight = null; });
    return workerInflight;
  };

  const refreshLifecycle = async ({force=false}={})=>{
    const pid=String(projectId?.() || ''),shell=document.querySelector?.('.storage61-shell');
    if (!pid || !shell) return;
    let value=lifecycleStates.get(pid);
    if (!value) {value={loaded:false};lifecycleStates.set(pid,value);}
    if (value.inflight && value.shell!==shell) {
      value.token={};
      value.controller?.abort();
      value.inflight=null;
      value.loading=false;
    }
    if (value.inflight && value.shell===shell) return value.inflight;
    if (!force && value.loaded) {renderLifecycleSummary(value);return;}
    value.controller?.abort();
    const controller=new AbortController(),token={};
    Object.assign(value,{loading:true,error:'',controller,token,shell});
    const current=()=>value.token===token && String(projectId?.() || '')===pid && document.querySelector?.('.storage61-shell')===shell;
    renderLifecycleSummary(value);
    const promise=withRequestDeadline(async signal=>{
      const response=await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/storage/lifecycle-summary`,{signal,cache:'no-store'});
      const body=await response.json();
      if (!response.ok) throw new Error(body?.detail?.message || body?.message || (typeof body?.detail==='string' ? body.detail : '读取占用信息失败'));
      if (body?.ok!==true || body.project_id!==pid || !body.metrics || typeof body.metrics!=='object') throw new Error('占用快照身份或指标未核验');
      if (current()) {value.payload=body;value.loaded=true;}
    },{label:'存储占用快照',signal:controller.signal}).catch(error=>{
      if (current()) {value.error=String(error.message || error);value.loaded=true;}
    }).finally(()=>{
      if(value.token===token){value.loading=false;value.inflight=null;if(current())renderLifecycleSummary(value);}
    });
    value.inflight=promise;
    return promise;
  };

  const refresh = async ({sources = null, force = false} = {}) => {
    const shell=document.querySelector?.('.storage61-shell'),pid=String(projectId?.() || '');
    const current=()=>document.querySelector?.('.storage61-shell')===shell && String(projectId?.() || '')===pid;
    decorate(sources);
    try {
      await Promise.all([refreshWorkers({force}),refreshLifecycle({force})]);
    } catch (error) {
      if(current())notify(error?.message || String(error));
    }
    if(current())decorate(sources);
    return latestSources;
  };

  const runtime = Object.freeze({
    refresh,
    decorate,
    decorateEditor,
    storageCacheTruth,
    storageCacheSummary,
    materialCacheStatusView,
    materialCacheNodeRuntimeView,
    state() {
      return {
        sourceCount: latestSources.length,
        workerCount: latestWorkers.length,
        workersLoadedAt,
        workerInflight: Boolean(workerInflight),
      };
    },
  });
  window.StorageCacheRuntime = runtime;
  if (document.getElementById('storage61Rows')) void refresh({sources: snapshotSources()});
  return runtime;
}
if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  installStorageCacheRuntime({
    fetchImpl: (...args) => window.fetch(...args),
    notify: message => window.toast?.(message),
  });
}
