import {buildStorageSourcePayload as hardenedBuildStorageSourcePayload} from './storage.js?v=422203';

const REMOTE_TYPES = new Set(['oss', 's3', 'remote']);
const OBJECT_STORE_TYPES = new Set(['oss', 's3']);

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
    cacheLabel: 'SHA256 本地内容缓存 · 训练 Bundle 缓存',
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

export function materialCacheStatusView(status) {
  if (!status || typeof status !== 'object') {
    return {
      available: false,
      usage: '尚无维护快照',
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

function apiErrorMessage(body, status) {
  if (body && typeof body === 'object') {
    return String(body.message || body.detail || `HTTP ${status}`);
  }
  return String(body || `HTTP ${status}`);
}

async function fetchSources(fetchImpl) {
  const response = await fetchImpl('/api/v61/storage-sources');
  if (!response.ok) {
    let body = null;
    try { body = await response.json(); } catch (_) { body = await response.text(); }
    throw new Error(apiErrorMessage(body, response.status));
  }
  const payload = await response.json();
  return Array.isArray(payload?.items) ? payload.items : [];
}

async function fetchMaterialCacheStatus(fetchImpl) {
  const response = await fetchImpl(`/data/cache/materials/status.json?_=${Date.now()}`, {cache: 'no-store'});
  if (response.status === 404) return null;
  if (!response.ok) return null;
  try { return await response.json(); } catch (_) { return null; }
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
  note.textContent = '远程素材训练优先使用 Worker 本地 SHA256 内容缓存，再复用已验证的训练 Bundle。OSS / S3 平台写入默认禁止覆盖同一 object_key；如果有人在平台外直接修改源对象，需先执行“重新扫描 / 恢复”确认变化，避免缓存与源端语义不一致。';
}

function renderCacheStatus(status) {
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
  const view = materialCacheStatusView(status);
  const generated = view.generatedAt ? String(view.generatedAt).replace('T', ' ').replace('Z', '').slice(0, 19) : '';
  const statusText = view.available
    ? (view.overBudget ? '超出配额，等待后续安全清理' : '生命周期受控')
    : '首次远程素材访问后生成维护快照';
  card.innerHTML = `<div class="panel-head"><div><div class="panel-title">当前节点素材内容缓存</div><div class="item-sub">Worker 本地 SHA256 缓存维护快照${generated ? ` · ${generated}` : ''}</div></div><span class="pill ${view.overBudget ? 'warn' : view.available ? 'ok' : ''}">${statusText}</span></div><div class="panel-body"><div style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px"><div class="stat"><div class="k">当前占用</div><div class="v">${view.usage}</div></div><div class="stat"><div class="k">缓存文件</div><div class="v">${view.files}</div></div><div class="stat"><div class="k">容量上限</div><div class="v">${view.limit}</div></div><div class="stat"><div class="k">缓存 TTL</div><div class="v">${view.ttl}</div></div></div></div>`;
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

export function installStorageCacheRuntime({fetchImpl = globalThis.fetch, notify = () => {}} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') {
    return {refresh: async () => [], decorateEditor};
  }
  if (window.__storageCacheRuntimeInstalled) return window.StorageCacheRuntime;
  window.__storageCacheRuntimeInstalled = true;
  if (window.PlatformCore?.storage) {
    window.PlatformCore.storage.buildStorageSourcePayload = hardenedBuildStorageSourcePayload;
  }

  let latestSources = [];
  let latestCacheStatus = null;

  const decorate = async () => {
    try {
      const [sources, cacheStatus] = await Promise.all([
        fetchSources(fetchImpl),
        fetchMaterialCacheStatus(fetchImpl),
      ]);
      latestSources = sources;
      latestCacheStatus = cacheStatus;
      const container = document.getElementById('storage61Rows');
      if (container) {
        const rows = [...container.children].filter(row => row.classList?.contains('storage61-row'));
        latestSources.forEach((source, index) => appendTruth(rows[index], source));
      }
      updatePageNote(latestSources);
      renderCacheStatus(latestCacheStatus);
      decorateEditor();
      return latestSources;
    } catch (error) {
      notify(error?.message || String(error));
      renderCacheStatus(latestCacheStatus);
      return latestSources;
    }
  };

  const originalRender = window.renderStorageSources61;
  if (typeof originalRender === 'function') {
    const wrapped = async function(...args) {
      const result = await originalRender.apply(this, args);
      await decorate();
      return result;
    };
    wrapped.__storageCacheRuntimeWrapped = true;
    window.renderStorageSources61 = wrapped;
  }

  const originalOpen = window.openStorageSource61;
  if (typeof originalOpen === 'function') {
    window.openStorageSource61 = async function(...args) {
      const result = await originalOpen.apply(this, args);
      decorateEditor();
      return result;
    };
  }

  const originalTypeChanged = window.storageTypeChanged61;
  if (typeof originalTypeChanged === 'function') {
    window.storageTypeChanged61 = function(...args) {
      const result = originalTypeChanged.apply(this, args);
      queueMicrotask(decorateEditor);
      return result;
    };
  }

  const runtime = Object.freeze({refresh: decorate, decorateEditor, storageCacheTruth, storageCacheSummary, materialCacheStatusView});
  window.StorageCacheRuntime = runtime;
  if (document.getElementById('storage61Rows')) void decorate();
  return runtime;
}

if (typeof window !== 'undefined' && typeof document !== 'undefined') {
  installStorageCacheRuntime({
    fetchImpl: (...args) => window.fetch(...args),
    notify: message => window.toast?.(message),
  });
}
