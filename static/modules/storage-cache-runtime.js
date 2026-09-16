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

  const decorate = async () => {
    try {
      latestSources = await fetchSources(fetchImpl);
      const container = document.getElementById('storage61Rows');
      if (container) {
        const rows = [...container.children].filter(row => row.classList?.contains('storage61-row'));
        latestSources.forEach((source, index) => appendTruth(rows[index], source));
      }
      updatePageNote(latestSources);
      decorateEditor();
      return latestSources;
    } catch (error) {
      notify(error?.message || String(error));
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

  const runtime = Object.freeze({refresh: decorate, decorateEditor, storageCacheTruth, storageCacheSummary});
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
