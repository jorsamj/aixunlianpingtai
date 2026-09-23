const PAGE = '平台对接';
const API_ROOT = '/api/v63/external-algorithm-platform';
const PLATFORM_CONFIG_SNAPSHOT_KEY = 'cl_external_platform_config_snapshot_v1';
const PLATFORM_CONFIG_SNAPSHOT_MAX_AGE_MS = 24 * 60 * 60 * 1000;

function rawFetch() {
  const scoped = window.fetch;
  return scoped?.__pageRequestScopeOriginal || scoped;
}

async function requestJson(url, options = {}, fetchImpl = rawFetch()) {
  const response = await fetchImpl(url, {
    headers: {'Accept': 'application/json', ...(options.headers || {})},
    ...options,
  });
  const text = await response.text();
  let body = {};
  try { body = text ? JSON.parse(text) : {}; } catch (_) { body = {detail: text}; }
  if (!response.ok) {
    const message = body.message || body.detail || `请求失败（HTTP ${response.status}）`;
    const solution = body.solution ? `\n建议：${body.solution}` : '';
    const error = new Error(`${message}${solution}`);
    error.code = body.code || '';
    error.detail = body.detail || '';
    error.solution = body.solution || '';
    error.httpStatus = response.status;
    throw error;
  }
  return body;
}

export function isExternalAlgorithm(algorithm) {
  return String(algorithm?.source_type || '').toUpperCase() === 'EXTERNAL';
}

export function externalAlgorithmTrainingReadiness(algorithm = {}, currentMasterDigest = '') {
  if (!isExternalAlgorithm(algorithm)) return {ready: true, status: 'local', reason: '', message: ''};
  if (String(algorithm?.provider_type || '').toUpperCase() !== 'CHANG_LIAN') {
    return {ready: true, status: 'external', reason: '', message: ''};
  }
  if (algorithm.external_active === false) {
    return {
      ready: false,
      status: 'inactive',
      reason: 'external-inactive',
      message: '该算法已在新畅联下架，不能新建训练任务',
    };
  }
  if (externalAnalysisOptions(algorithm).length === 0) {
    return {
      ready: false,
      status: 'no-visual-analysis',
      reason: 'external-visual-analysis-missing',
      message: '该算法当前没有可训练的视觉分析配置（需 status=1 且 analysisType=1），无法创建训练任务',
    };
  }
  const expected = String(currentMasterDigest || '').trim();
  const actual = String(algorithm.external_master_data_digest || '').trim();
  if (!expected || !actual || expected !== actual) {
    return {
      ready: false,
      status: 'stale',
      reason: 'external-master-data-stale',
      message: '当前算法的畅联云主数据需要重新同步，请到“配置中心 → 平台对接”执行“立即同步”',
    };
  }
  return {ready: true, status: 'current', reason: '', message: ''};
}

export function algorithmSourceLabel(algorithm) {
  if (!isExternalAlgorithm(algorithm)) return '本平台';
  return String(algorithm?.source_name || (
    String(algorithm?.provider_type || '').toUpperCase() === 'CHANG_LIAN' ? '新畅联' : '外部平台'
  ));
}

export function externalAnalysisOptions(algorithm = {}) {
  const rows = Array.isArray(algorithm.external_analyses) ? algorithm.external_analyses : [];
  return rows.map(row => ({
    id: String(row?.analysis_id || row?.analysisId || ''),
    name: String(row?.analysis_name || row?.analysisName || row?.analysis_type || row?.analysisType || ''),
    type: String(row?.analysis_type ?? row?.analysisType ?? '').trim(),
    status: String(row?.status ?? '').trim(),
  })).filter(row => row.id && row.type === '1' && row.status === '1');
}

export function externalAlgorithmMapping(algorithm = {}) {
  const analyses = externalAnalysisOptions(algorithm);
  return {
    source: algorithmSourceLabel(algorithm),
    productId: String(algorithm.external_product_id || ''),
    categoryId: String(algorithm.external_category_id || ''),
    analysisIds: analyses.map(row => row.id),
    analysisNames: analyses.map(row => row.name || row.id),
    active: algorithm.external_active !== false,
    syncedAt: String(algorithm.external_last_synced_at || ''),
    masterDataDigest: String(algorithm.external_master_data_digest || ''),
  };
}

export function externalCategoryTreeRows(categories = []) {
  const byId = new Map();
  for (const raw of categories || []) {
    const id = String(raw?.categoryId || raw?.id || '').trim();
    if (!id || byId.has(id)) continue;
    byId.set(id, {
      id,
      name: String(raw?.categoryName || raw?.name || id).trim() || id,
      parentId: String(raw?.parentId || '').trim(),
    });
  }

  const children = new Map();
  for (const row of byId.values()) {
    const parentId = row.parentId && byId.has(row.parentId) ? row.parentId : '';
    if (!children.has(parentId)) children.set(parentId, []);
    children.get(parentId).push(row);
  }
  for (const rows of children.values()) rows.sort((a, b) => a.name.localeCompare(b.name, 'zh-CN'));

  const flattened = [];
  const visited = new Set();
  const walk = (row, depth, ancestors, names) => {
    if (!row || visited.has(row.id)) return;
    visited.add(row.id);
    const descendants = children.get(row.id) || [];
    const pathNames = [...names, row.name];
    flattened.push({
      ...row,
      depth,
      ancestorIds: [...ancestors],
      path: pathNames.join(' / '),
      hasChildren: descendants.length > 0,
    });
    for (const child of descendants) {
      walk(child, depth + 1, [...ancestors, row.id], pathNames);
    }
  };

  for (const root of children.get('') || []) walk(root, 0, [], []);
  for (const row of byId.values()) {
    if (!visited.has(row.id)) walk(row, 0, [], []);
  }
  return flattened;
}

export function externalCategoryVisibleRows(
  categories = [],
  {expandedIds = [], query = ''} = {},
) {
  const rows = externalCategoryTreeRows(categories);
  const needle = String(query || '').trim().toLowerCase();
  if (needle) {
    const include = new Set();
    for (const row of rows) {
      if (`${row.name} ${row.path}`.toLowerCase().includes(needle)) {
        include.add(row.id);
        for (const ancestorId of row.ancestorIds) include.add(ancestorId);
      }
    }
    return rows.filter(row => include.has(row.id));
  }

  const expanded = new Set([...expandedIds].map(String));
  return rows.filter(row => row.ancestorIds.every(id => expanded.has(id)));
}

export function externalCategoryMatches(categoryId, selectedCategoryIds = [], categories = []) {
  const selected = new Set([...selectedCategoryIds].map(value => String(value || '')).filter(Boolean));
  if (!selected.size) return true;
  const parentById = new Map((categories || []).map(row => [
    String(row?.categoryId || row?.id || ''),
    String(row?.parentId || ''),
  ]));
  let current = String(categoryId || '');
  const seen = new Set();
  while (current && !seen.has(current)) {
    if (selected.has(current)) return true;
    seen.add(current);
    current = parentById.get(current) || '';
  }
  return false;
}

export function externalAlgorithmListFilterMatch(
  algorithm = {},
  {source = 'all', trainingStatus = 'all', selectedCategoryIds = [], categories = [], jobs = [], readiness = {ready: true}} = {},
) {
  const external = isExternalAlgorithm(algorithm);
  if (source === 'internal' && external) return false;
  if (source === 'external' && !external) return false;
  if (!externalCategoryMatches(algorithm.external_category_id, selectedCategoryIds, categories)) return false;
  const versions = Array.isArray(algorithm.versions) ? algorithm.versions : [];
  const activeStatuses = new Set(['queued', 'running', 'starting', 'preparing', 'paused']);
  const training = (jobs || []).some(job => {
    const algorithmId = job?.asset_algorithm_id || job?.algorithm_asset_id || job?.algorithm_id || '';
    return String(algorithmId) === String(algorithm.id || '') && activeStatuses.has(String(job?.status || '').toLowerCase());
  });
  if (trainingStatus === 'training') return training;
  if (trainingStatus === 'trained') return versions.length > 0;
  if (trainingStatus === 'untrained') return versions.length === 0;
  if (trainingStatus === 'blocked') return external && readiness?.ready === false;
  if (trainingStatus === 'trainable') return !external || readiness?.ready !== false;
  return true;
}

export function normalizeExternalPlatformConfig(body = {}) {
  const config = body?.config || body || {};
  const endpoints = config.endpoints || {};
  return {
    mode: config.mode === 'external' ? 'external' : 'local',
    provider: config.provider || 'changlian',
    providerName: config.provider_name || '新畅联',
    baseUrl: config.base_url || '',
    autoSyncEnabled: Boolean(config.auto_sync_enabled),
    autoSyncIntervalSeconds: Number(config.auto_sync_interval_seconds || 60),
    autoPublishEnabled: Boolean(config.auto_publish_enabled),
    authMode: config.auth_mode || 'test_sign_bridge',
    businessAuthMode: config.business_auth_mode || 'authorization_bearer',
    credentials: config.credentials || {configured: false, masked: ''},
    apiDocuments: Array.isArray(config.api_documents) ? config.api_documents : [],
    apiDocumentSummary: config.api_document_summary || {},
    endpoints: {
      test_sign: endpoints.test_sign || '/internal/auth/test-sign',
      token: endpoints.token || '/internal/auth/token',
      category_tree: endpoints.category_tree || '/internal/base/category/tree',
      product_list: endpoints.product_list || '/internal/algorithm/product-ai/listAll',
      analysis_by_product: endpoints.analysis_by_product || '/internal/algorithm/algorithm-analysis/listByProduct/{productId}',
      compute_platform_list: endpoints.compute_platform_list || '/internal/base/compute-platform/listAll',
      version_create: endpoints.version_create || '/internal/algorithm/algorithm-version/add',
      weight_create: endpoints.weight_create || '/internal/algorithm/algorithm-weight/add',
    },
    updatedAt: config.updated_at || '',
    lastSync: config.last_sync || null,
    cache: config.cache || {},
  };
}

export function safeExternalPlatformConfigSnapshot(current = {}) {
  const normalized = Object.prototype.hasOwnProperty.call(current || {}, 'baseUrl')
    ? current
    : normalizeExternalPlatformConfig(current);
  const credentials = normalized?.credentials || {};
  const summary = normalized?.apiDocumentSummary || {};
  const cache = normalized?.cache || {};
  const last = normalized?.lastSync || null;
  const lastCounts = last?.counts || {};
  const endpoints = normalized?.endpoints || {};
  return {
    mode: normalized?.mode === 'external' ? 'external' : 'local',
    provider: String(normalized?.provider || 'changlian'),
    providerName: String(normalized?.providerName || '新畅联'),
    baseUrl: String(normalized?.baseUrl || ''),
    autoSyncEnabled: Boolean(normalized?.autoSyncEnabled),
    autoSyncIntervalSeconds: Number(normalized?.autoSyncIntervalSeconds || 60),
    autoPublishEnabled: Boolean(normalized?.autoPublishEnabled),
    authMode: String(normalized?.authMode || 'test_sign_bridge'),
    businessAuthMode: String(normalized?.businessAuthMode || 'authorization_bearer'),
    credentials: {
      configured: credentials.configured === true,
      masked: String(credentials.masked || ''),
      ...(credentials.available === true || credentials.available === false ? {available: credentials.available} : {}),
      backend: String(credentials.backend || ''),
      ...(credentials.writable === true || credentials.writable === false ? {writable: credentials.writable} : {}),
      environment_name: String(credentials.environment_name || ''),
    },
    apiDocuments: (Array.isArray(normalized?.apiDocuments) ? normalized.apiDocuments : []).map(item => ({
      key: String(item?.key || ''),
      group: String(item?.group || ''),
      title: String(item?.title || ''),
      doc_url: String(item?.doc_url || ''),
      status: String(item?.status || ''),
      method: String(item?.method || ''),
      path: String(item?.path || ''),
    })),
    apiDocumentSummary: {
      total: Number(summary.total || 0),
      wired: Number(summary.wired || 0),
      documented: Number(summary.documented || 0),
      reference: Number(summary.reference || 0),
    },
    endpoints: {
      test_sign: String(endpoints.test_sign || '/internal/auth/test-sign'),
      token: String(endpoints.token || '/internal/auth/token'),
      category_tree: String(endpoints.category_tree || '/internal/base/category/tree'),
      product_list: String(endpoints.product_list || '/internal/algorithm/product-ai/listAll'),
      analysis_by_product: String(endpoints.analysis_by_product || '/internal/algorithm/algorithm-analysis/listByProduct/{productId}'),
      compute_platform_list: String(endpoints.compute_platform_list || '/internal/base/compute-platform/listAll'),
      version_create: String(endpoints.version_create || '/internal/algorithm/algorithm-version/add'),
      weight_create: String(endpoints.weight_create || '/internal/algorithm/algorithm-weight/add'),
    },
    updatedAt: String(normalized?.updatedAt || ''),
    lastSync: last ? {
      status: String(last.status || ''),
      sync_type: String(last.sync_type || ''),
      started_at: String(last.started_at || ''),
      finished_at: String(last.finished_at || ''),
      counts: {
        categories: Number(lastCounts.categories || 0),
        products: Number(lastCounts.products || 0),
        analyses: Number(lastCounts.analyses || 0),
        compute_platforms: Number(lastCounts.compute_platforms || 0),
      },
    } : null,
    cache: {
      category_count: Number(cache.category_count || 0),
      product_count: Number(cache.product_count || 0),
      analysis_count: Number(cache.analysis_count || 0),
      compute_platform_count: Number(cache.compute_platform_count || 0),
      master_data_digest: String(cache.master_data_digest || ''),
      updated_at: String(cache.updated_at || ''),
    },
  };
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, match => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[match]));
}

function timeText(value) {
  if (!value) return '-';
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 19);
}

function syncStatusText(value) {
  return ({success: '成功', failed: '失败', running: '同步中'}[String(value || '')] || '未同步');
}

function syncCountsText(item) {
  const counts = item?.counts || {};
  if (!item || item.status !== 'success') return '';
  return `品目 ${counts.categories || 0} · 算法 ${counts.products || 0} · 分析方式 ${counts.analyses || 0} · 算力环境 ${counts.compute_platforms || 0}`;
}

export function installExternalAlgorithmPlatformRuntime({
  getState,
  projectId,
  notify,
  algorithmListRuntime,
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__externalAlgorithmPlatformRuntimeInstalled) return window.ExternalAlgorithmPlatformRuntime;

  const state = () => getState?.() || {};
  let config = null;
  let history = [];
  let pageLoadedAt = 0;

  function persistConfigSnapshot() {
    if (!config) return false;
    try {
      window.localStorage?.setItem(PLATFORM_CONFIG_SNAPSHOT_KEY, JSON.stringify({
        ts: Date.now(),
        config: safeExternalPlatformConfigSnapshot(config),
      }));
      return true;
    } catch (_) {
      return false;
    }
  }

  function restoreConfigSnapshot() {
    try {
      const payload = JSON.parse(window.localStorage?.getItem(PLATFORM_CONFIG_SNAPSHOT_KEY) || 'null');
      const ts = Number(payload?.ts || 0);
      const age = Date.now() - ts;
      if (!payload?.config || !ts || age < 0 || age > PLATFORM_CONFIG_SNAPSHOT_MAX_AGE_MS) {
        window.localStorage?.removeItem(PLATFORM_CONFIG_SNAPSHOT_KEY);
        return false;
      }
      config = safeExternalPlatformConfigSnapshot(payload.config);
      state().externalAlgorithmPlatformConfig = config;
      return true;
    } catch (_) {
      try { window.localStorage?.removeItem(PLATFORM_CONFIG_SNAPSHOT_KEY); } catch (_) {}
      return false;
    }
  }

  restoreConfigSnapshot();
  const PLATFORM_PAGE_CACHE_TTL_MS = 60 * 1000;
  let cacheData = {categories: [], products: [], analyses_by_product: {}, compute_platforms: []};
  let loading = false;
  let destroyed = false;
  let renderQueued = false;
  let diagnostics = null;
  let readiness = null;
  let connectionTest = null;
  let configEditing = false;
  let activeTab = String(state().externalPlatformTab64 || 'overview');
  if (!['overview', 'connection', 'sync', 'vendor', 'api', 'history'].includes(activeTab)) activeTab = 'overview';
  let trainingAnalysisObserver = null;
  const trainingPreflightCache = new Map();

  function currentProjectId() {
    return String(projectId?.() || '');
  }

  async function loadConfig({silent = false} = {}) {
    try {
      const body = await requestJson(`${API_ROOT}/config`);
      config = normalizeExternalPlatformConfig(body);
      state().externalAlgorithmPlatformConfig = config;
      persistConfigSnapshot();
      return config;
    } catch (error) {
      if (!silent) notify?.(error?.message || error);
      throw error;
    }
  }

  async function loadHistory({silent = false} = {}) {
    try {
      const body = await requestJson(`${API_ROOT}/sync-history?limit=20`);
      history = Array.isArray(body?.items) ? body.items : [];
      return history;
    } catch (error) {
      if (!silent) notify?.(error?.message || error);
      throw error;
    }
  }

  async function loadCache({silent = false} = {}) {
    try {
      const body = await requestJson(`${API_ROOT}/cache`);
      cacheData = body?.cache || {categories: [], products: [], analyses_by_product: {}, compute_platforms: []};
      return cacheData;
    } catch (error) {
      if (!silent) notify?.(error?.message || error);
      throw error;
    }
  }

  async function loadReadiness({silent = false} = {}) {
    const pid = currentProjectId();
    if (!pid) {
      readiness = null;
      return null;
    }
    try {
      readiness = await requestJson(`${API_ROOT}/readiness?project_id=${encodeURIComponent(pid)}`);
      return readiness;
    } catch (error) {
      readiness = null;
      if (!silent) notify?.(error?.message || error);
      throw error;
    }
  }

  function externalMode() {
    return (config || state().externalAlgorithmPlatformConfig)?.mode === 'external';
  }

  function currentMasterDataDigest() {
    return String(
      cacheData?.master_data_digest
      || config?.cache?.master_data_digest
      || state().externalAlgorithmPlatformConfig?.cache?.master_data_digest
      || ''
    ).trim();
  }

  function trainingReadiness(algorithmId) {
    const algorithm = (state().algorithms || []).find(row => String(row.id) === String(algorithmId));
    if (!algorithm) {
      return {ready: false, status: 'missing', reason: 'algorithm', message: '当前训练算法不存在，请刷新算法列表后重试'};
    }
    return externalAlgorithmTrainingReadiness(algorithm, currentMasterDataDigest());
  }

  function trainingPreflightFresh(algorithmId, {maxAgeMs = 30000} = {}) {
    const pid = currentProjectId();
    const id = String(algorithmId || '').trim();
    if (!pid || !id) return false;
    const cached = trainingPreflightCache.get(`${pid}:${id}`);
    const age = Date.now() - Number(cached?.loadedAt || 0);
    return Boolean(cached?.algorithm) && age >= 0 && age < Math.max(0, Number(maxAgeMs) || 0);
  }

  async function preflightTraining(algorithmId, {request, force = false, maxAgeMs = 30000} = {}) {
    const pid = currentProjectId();
    const id = String(algorithmId || '').trim();
    if (!pid || !id) throw new Error('当前训练算法或项目不可用');
    const key = `${pid}:${id}`;
    const cached = trainingPreflightCache.get(key);
    if (!force && cached?.algorithm && Date.now() - cached.loadedAt < maxAgeMs) return cached.algorithm;
    if (cached?.promise) return cached.promise;
    const requester = typeof request === 'function' ? request : url => requestJson(url);
    const promise = (async () => {
      const body = await requester(`${API_ROOT}/training-preflight?project_id=${encodeURIComponent(pid)}&algorithm_id=${encodeURIComponent(id)}`);
      const fresh = body?.algorithm;
      if (!body?.ready || !fresh) throw new Error('训练算法不存在、已下架或当前没有可训练的视觉分析配置');
      if (currentProjectId() !== pid) throw new Error('当前项目已切换，请重新打开训练窗口');
      const rows = state().algorithms || [];
      const index = rows.findIndex(item => String(item?.id || '') === id);
      if (index >= 0) rows[index] = fresh;
      else state().algorithms = [fresh, ...rows];
      trainingPreflightCache.set(key, {algorithm: fresh, loadedAt: Date.now()});
      return fresh;
    })();
    trainingPreflightCache.set(key, {promise, loadedAt: Date.now()});
    try { return await promise; }
    catch (error) { trainingPreflightCache.delete(key); throw error; }
  }

  function decorateAlgorithmDetail(algorithm) {
    if (!isExternalAlgorithm(algorithm)) return;
    const detail = document.querySelector('#modalBody .alg428-detail');
    if (!detail || detail.querySelector('[data-external-algorithm-detail]')) return;
    const mapping = externalAlgorithmMapping(algorithm);
    const trainingState = externalAlgorithmTrainingReadiness(algorithm, currentMasterDataDigest());
    const panel = document.createElement('section');
    panel.dataset.externalAlgorithmDetail = '1';
    panel.innerHTML = `<div class="alg428-version-head"><b>外部平台映射</b><span>${escapeHtml(mapping.source)}</span></div>
      <dl class="report429-dl">
        <dt>来源平台</dt><dd>${escapeHtml(mapping.source)}</dd>
        <dt>Product ID</dt><dd>${escapeHtml(mapping.productId || '-')}</dd>
        <dt>Category ID</dt><dd>${escapeHtml(mapping.categoryId || '-')}</dd>
        <dt>Analysis ID</dt><dd>${escapeHtml(mapping.analysisIds.join('、') || '-')}</dd>
        <dt>分析方式</dt><dd>${escapeHtml(mapping.analysisNames.join('、') || '-')}</dd>
        <dt>同步状态</dt><dd>${trainingState.status === 'inactive' ? '已下架' : trainingState.status === 'stale' ? '待同步' : '正常'}</dd>
        <dt>最近同步</dt><dd>${escapeHtml(timeText(mapping.syncedAt))}</dd>
      </dl>`;
    detail.insertBefore(panel, detail.children[1] || null);
    if (!trainingState.ready) {
      for (const button of detail.querySelectorAll('button')) {
        if (/开始训练/.test(String(button.textContent || ''))) {
          button.disabled = true;
          button.title = trainingState.message;
        }
      }
    }
  }

  const algorithmListProvider = {
    snapshot: () => ({
      categories: cacheData?.categories || [],
      categoryRows: externalCategoryTreeRows(cacheData?.categories || []),
      externalMode: externalMode(),
    }),
    matches: (algorithm, filters = {}) => externalAlgorithmListFilterMatch(algorithm, {
      source: filters.source,
      trainingStatus: filters.trainingStatus,
      selectedCategoryIds: filters.selectedCategoryIds,
      categories: cacheData?.categories || [],
      jobs: filters.jobs || state().jobs || [],
      readiness: isExternalAlgorithm(algorithm)
        ? externalAlgorithmTrainingReadiness(algorithm, currentMasterDataDigest())
        : {ready: true},
    }),
    meta: algorithm => ({
      external: isExternalAlgorithm(algorithm),
      sourceLabel: algorithmSourceLabel(algorithm),
      readiness: externalAlgorithmTrainingReadiness(algorithm, currentMasterDataDigest()),
    }),
    sync: () => syncNow(),
    decorateDetail: decorateAlgorithmDetail,
  };

  function selectedAnalysisId(algorithmId) {
    const algorithm = (state().algorithms || []).find(row => String(row.id) === String(algorithmId));
    if (!isExternalAlgorithm(algorithm)) return '';
    const options = externalAnalysisOptions(algorithm);
    state().externalAnalysisSelection = state().externalAnalysisSelection || {};
    return String(state().externalAnalysisSelection[algorithmId] || algorithm.external_analysis_id || options[0]?.id || '');
  }

  function decorateTrainingAnalysisSelector() {
    const form = document.querySelector('.train429-create');
    if (!form || form.querySelector('[data-external-analysis-selector]')) return;
    const algorithmId = String(state().trainingDraft?.algorithmId || '');
    const algorithm = (state().algorithms || []).find(row => String(row.id) === algorithmId);
    if (!isExternalAlgorithm(algorithm)) return;
    const trainingState = externalAlgorithmTrainingReadiness(algorithm, currentMasterDataDigest());
    if (!trainingState.ready) {
      const panel = document.createElement('div');
      panel.className = 'alert warn';
      panel.dataset.externalTrainingBlocked = trainingState.reason || 'external-blocked';
      panel.textContent = trainingState.message;
      form.prepend(panel);
      window.TrainingSubmitRuntime?.updateReadiness?.();
      return;
    }
    const options = externalAnalysisOptions(algorithm);
    state().externalAnalysisSelection = state().externalAnalysisSelection || {};
    if (options.length <= 1) {
      if (options[0]?.id) state().externalAnalysisSelection[algorithmId] = options[0].id;
      return;
    }
    const panel = document.createElement('div');
    panel.className = 'panel';
    panel.dataset.externalAnalysisSelector = '1';
    panel.innerHTML = `<div class="panel-body"><div class="field"><label>本次训练分析方式</label><select id="externalTrainingAnalysis" class="select">${options.map(row => `<option value="${escapeHtml(row.id)}">${escapeHtml(row.name || row.id)}</option>`).join('')}</select></div></div>`;
    form.prepend(panel);
    const select = panel.querySelector('#externalTrainingAnalysis');
    const current = selectedAnalysisId(algorithmId);
    if (current && options.some(row => row.id === current)) select.value = current;
    state().externalAnalysisSelection[algorithmId] = select.value;
    select.addEventListener('change', () => { state().externalAnalysisSelection[algorithmId] = select.value; });
  }

  function scheduleRender() {
    if (renderQueued || destroyed) return;
    renderQueued = true;
    queueMicrotask(() => {
      renderQueued = false;
      if (!destroyed && String(state().page || '') === PAGE) void render();
    });
  }

  function configFormHtml(current) {
    const c = current || normalizeExternalPlatformConfig({});
    const external = c.mode === 'external';
    const last = c.lastSync;
    const cache = c.cache || {};
    const credential = c.credentials || {};
    const credentialBackendText = ({
      environment: '环境变量',
      keyring: '系统密钥环',
      encrypted_file: '服务器加密文件',
      memory: '内存',
      unavailable: '不可用',
    })[String(credential.backend || '')] || '待检测';
    const credentialManaged = credential.backend === 'environment';
    const credentialStatusText = credential.configured
      ? `已配置（${escapeHtml(credential.masked || 'AccessKey 已保存')}）`
      : credential.available === false ? '安全存储不可用' : '未配置';
    const credentialHelpText = credential.available === false
      ? '服务器没有可用的安全 Secret 后端。请配置系统 SecretService，或设置 MC_SECRET_MASTER_KEY 启用服务器加密文件。'
      : credentialManaged
        ? `当前凭据由 ${escapeHtml(credential.environment_name || '环境变量')} 管理，只读；页面不会覆盖。`
        : 'AccessSecret 仅提交给后端安全存储，页面不会读取已保存的明文 Secret。';
    const savedConnectionReady = external && Boolean(c.baseUrl) && credential.configured === true;
    const configLocked = savedConnectionReady && !configEditing;
    const formDisabled = configLocked ? 'disabled' : '';
    const credentialDisabled = (credentialManaged || configLocked) ? 'disabled' : '';
    const configActionsHtml = configLocked
      ? '<button class="btn primary" id="externalPlatformEdit">编辑配置</button>'
      : `<button class="btn primary" id="externalPlatformSave">保存配置</button>${savedConnectionReady ? '<button class="btn" id="externalPlatformCancelEdit">取消编辑</button>' : ''}`;
    const connectionHelpText = configLocked
      ? '使用服务器已保存的 API 地址和凭据测试连接；已保存的 Secret 不会回显到浏览器。'
      : '使用当前页面填写的 API 地址和凭据临时测试，不会自动保存或覆盖已保存凭据。';
    const syncSucceeded = last?.status === 'success';
    const configSaved = Boolean(c.updatedAt);
    const sourceStatus = external ? '新畅联管理' : '本平台管理';
    const connectionStatus = connectionTest?.ok === true
      ? '连接正常'
      : connectionTest ? '连接异常' : savedConnectionReady ? '待测试' : '待配置';
    const syncStatus = syncSucceeded ? '主数据已同步' : last?.status === 'failed' ? '同步异常' : '尚未同步';
    const savedStatus = configSaved ? `已保存 · ${timeText(c.updatedAt)}` : '尚未保存';
    const providerText = external ? '新畅联' : '本平台';
    const tab = key => activeTab === key ? ' active' : '';
    const tabButton = (key, label, meta = '') => `<button type="button" class="external-platform-tab${tab(key)}" data-external-platform-tab="${key}"><span>${label}</span>${meta ? `<em>${meta}</em>` : ''}</button>`;
    return `<section class="label414-shell external-platform-shell external-platform-shell-v2" data-external-platform-page="1" data-active-tab="${escapeHtml(activeTab)}">
      <section class="external-platform-hero external-platform-hero-v2">
        <div class="external-platform-hero-main">
          <div class="external-platform-provider">
            <div class="external-platform-provider-mark">CL</div>
            <div>
              <div class="external-platform-eyebrow">EXTERNAL PLATFORM INTEGRATION</div>
              <h2>新畅联平台对接</h2>
              <p>连接、同步、厂商映射和版本权重发布统一在这里管理。常用操作前置，接口细节与诊断信息收进独立切页。</p>
            </div>
          </div>
          <div class="external-platform-actions">
            <button class="btn" id="externalPlatformTest">测试连接</button>
            ${configActionsHtml}
            <button class="btn green" id="externalPlatformSync" ${savedConnectionReady ? '' : 'disabled'} title="${savedConnectionReady ? '使用已保存配置同步新畅联主数据' : '请先保存 API 地址与应用凭据'}">↻ 立即同步</button>
          </div>
        </div>
        <div class="external-platform-status external-platform-status-v2">
          <span><i class="external-status-dot ${configSaved ? 'ok' : 'warn'}"></i><b>配置</b><em>${escapeHtml(savedStatus)}</em></span>
          <span><i class="external-status-dot ${external ? 'ok' : ''}"></i><b>当前来源</b><em>${escapeHtml(providerText)}</em></span>
          <span><i class="external-status-dot ${connectionTest?.ok === true ? 'ok' : connectionTest ? 'err' : savedConnectionReady ? 'warn' : ''}"></i><b>连接</b><em>${escapeHtml(connectionStatus)}</em></span>
          <span><i class="external-status-dot ${syncSucceeded ? 'ok' : last?.status === 'failed' ? 'err' : ''}"></i><b>主数据</b><em>${escapeHtml(syncStatus)}</em></span>
        </div>
      </section>

      <nav class="external-platform-tabs" aria-label="平台对接页面切换">
        ${tabButton('overview', '概览')}
        ${tabButton('connection', '连接配置')}
        ${tabButton('sync', '数据同步', String(Number(cache.product_count || 0)))}
        ${tabButton('vendor', '厂商对应表', String(Number(cache.compute_platform_count || 0)))}
        ${tabButton('api', '接口契约')}
        ${tabButton('history', '同步记录')}
      </nav>

      <section class="external-platform-overview" data-platform-tab-panel="overview">
        <div class="external-overview-grid">
          <article class="external-overview-card external-overview-card-primary">
            <div class="external-overview-card-head"><span class="external-overview-icon">↔</span><span class="pill ${savedConnectionReady ? 'ok' : 'warn'}">${savedConnectionReady ? '已连接' : '待配置'}</span></div>
            <b>平台连接</b>
            <strong>${escapeHtml(sourceStatus)}</strong>
            <small>${escapeHtml(c.baseUrl || '尚未配置 API 服务地址')}</small>
          </article>
          <article class="external-overview-card">
            <div class="external-overview-card-head"><span class="external-overview-icon">◎</span><span>${Number(cache.compute_platform_count || 0)}</span></div>
            <b>畅联云算力环境</b>
            <strong>${Number(cache.compute_platform_count || 0)} 个</strong>
            <small>供“厂商对应表”选择与映射</small>
          </article>
          <article class="external-overview-card">
            <div class="external-overview-card-head"><span class="external-overview-icon">◆</span><span>${Number(cache.product_count || 0)}</span></div>
            <b>算法产品</b>
            <strong>${Number(cache.product_count || 0)} 个</strong>
            <small>视觉分析方式 ${Number(cache.analysis_count || 0)} 个</small>
          </article>
          <article class="external-overview-card">
            <div class="external-overview-card-head"><span class="external-overview-icon">↻</span><span class="pill ${syncSucceeded ? 'ok' : last?.status === 'failed' ? 'err' : 'warn'}">${escapeHtml(syncStatusText(last?.status))}</span></div>
            <b>最近同步</b>
            <strong>${escapeHtml(timeText(last?.finished_at || last?.started_at))}</strong>
            <small>${escapeHtml(syncCountsText(last) || '等待首次主数据同步')}</small>
          </article>
        </div>

        <div class="external-platform-steps" aria-label="新畅联对接流程">
          <div class="external-step ${savedConnectionReady ? 'done' : 'current'}"><i>1</i><div><b>保存连接配置</b><span>API 地址与应用凭据</span></div></div>
          <div class="external-step ${connectionTest?.ok === true ? 'done' : savedConnectionReady ? 'current' : ''}"><i>2</i><div><b>验证连接</b><span>确认鉴权与只读接口</span></div></div>
          <div class="external-step ${syncSucceeded ? 'done' : external && savedConnectionReady ? 'current' : ''}"><i>3</i><div><b>同步主数据</b><span>产品、分析方式、算力环境</span></div></div>
          <div class="external-step ${syncSucceeded ? 'current' : ''}"><i>4</i><div><b>配置厂商对应</b><span>通用与转换厂商映射</span></div></div>
        </div>
      </section>

      <section class="panel external-platform-config" data-platform-tab-panel="connection">
        <div class="panel-head"><div><div class="panel-title">连接配置</div><div class="subline">${configLocked ? '当前配置已锁定；点击“编辑配置”后才能修改。' : '先配置并测试连接，再手动同步算法品目、算法产品、分析方式和算力环境。'}</div></div></div>
        <div class="panel-body">
          <div class="external-config-layout">
            <div class="form two external-config-form">
              <div class="field full">
                <label>算法数据来源</label>
                <div class="external-source-choice">
                  <label class="field check"><input type="radio" name="externalMode" value="local" ${external ? '' : 'checked'} ${formDisabled}> 本平台管理</label>
                  <label class="field check"><input type="radio" name="externalMode" value="external" ${external ? 'checked' : ''} ${formDisabled}> 外部平台</label>
                </div>
              </div>
              <div class="field"><label>外部平台</label><select id="externalProvider" class="select" ${formDisabled}><option value="changlian">新畅联</option></select></div>
              <div class="field"><label>API 服务地址</label><input id="externalBaseUrl" class="input" value="${escapeHtml(c.baseUrl)}" placeholder="https://api.example.com" ${formDisabled}></div>
              <div class="field"><label>AccessKey</label><input id="externalAccessKey" class="input" autocomplete="off" spellcheck="false" ${credentialDisabled} placeholder="${escapeHtml(credentialManaged ? '由环境变量管理' : (credential.masked || '请输入 AccessKey'))}"></div>
              <div class="field"><label>AccessSecret</label><div class="row"><input id="externalAccessSecret" type="password" class="input" autocomplete="new-password" spellcheck="false" ${credentialDisabled} placeholder="${credentialManaged ? '由环境变量管理' : (credential.configured ? '已配置，编辑时留空表示继续使用原 Secret' : '请输入 AccessSecret')}"><button type="button" class="btn" id="externalSecretToggle" ${credentialDisabled}>显示</button></div></div>
              <div class="field full"><div class="subline">凭据状态：${credentialStatusText} · 存储后端：${escapeHtml(credentialBackendText)}。 ${credentialHelpText}</div>${credential.available === false ? '<div class="alert warn" style="margin-top:10px">当前只能查看公开配置，保存 AccessKey / AccessSecret 会失败关闭（fail-closed），不会降级成明文 JSON。</div>' : ''}</div>
            </div>
            <aside class="external-config-aside">
              <div><span>连接方式</span><b>${escapeHtml(sourceStatus)}</b></div>
              <div><span>凭据状态</span><b>${escapeHtml(credential.configured ? '已安全保存' : '未配置')}</b></div>
              <div><span>自动同步</span><b>每 60 秒</b></div>
              <div><span>训练成果发布</span><b>后台自动执行</b></div>
            </aside>
          </div>
          <details data-external-sync-settings="1" class="external-sync-details">
            <summary>同步策略说明</summary>
            <div class="external-sync-policy">
              <div class="alert soft"><b>自动同步已启用</b><span>新畅联当前 OpenAPI 没有 Webhook、订阅或推送接口，平台固定每 60 秒主动拉取一次主数据。</span></div>
              <div class="subline" style="margin-top:8px">训练成功、转换完成后的版本与权重同步由后台自动执行，不需要人工重复点击。</div>
            </div>
          </details>
        </div>
      </section>

      <section class="panel" data-platform-tab-panel="connection">
        <div class="panel-head">
          <div><div class="panel-title">连接测试</div><div class="subline">${connectionHelpText}</div></div>
          <details class="external-platform-tools"><summary>高级联调</summary><button class="btn small" id="externalPlatformDiagnostics">运行联调诊断</button></details>
        </div>
        <div class="panel-body" id="externalConnectionResult">${connectionTestHtml()}</div>
      </section>

      <section class="panel" data-platform-tab-panel="sync">
        <div class="panel-head"><div><div class="panel-title">数据同步</div><div class="subline">“立即同步”只执行 新畅联 → 本平台 的算法品目、算法产品、分析方式和算力环境同步。</div></div></div>
        <div class="panel-body">
          <div class="external-sync-kpis">
            <div><span>最近同步</span><b>${escapeHtml(timeText(last?.finished_at || last?.started_at))}</b></div>
            <div><span>状态</span><b>${escapeHtml(syncStatusText(last?.status))}</b></div>
            <div><span>算法品目</span><b>${Number(cache.category_count || 0)}</b></div>
            <div><span>算法产品</span><b>${Number(cache.product_count || 0)}</b></div>
            <div><span>分析方式</span><b>${Number(cache.analysis_count || 0)}</b></div>
            <div><span>算力环境</span><b>${Number(cache.compute_platform_count || 0)}</b></div>
          </div>
          ${last?.status === 'failed' ? `<div class="alert warn">${escapeHtml(last.error || '同步失败')}：${escapeHtml(last.detail || '')}</div>` : ''}
          ${c.authMode === 'test_sign_bridge' ? '<div class="alert warn">当前鉴权使用新畅联 /internal/auth/test-sign 联调辅助接口生成签名参数。待新畅联提供正式签名算法规范后，应切换为本地签名实现。</div>' : ''}
        </div>
      </section>

      ${diagnosticsHtml()}
      ${masterDataPreviewHtml()}
      ${apiContractHtml()}

      <section class="panel" data-platform-tab-panel="history">
        <div class="panel-head"><div><div class="panel-title">同步记录</div><div class="subline">保留最近同步结果，便于排查主数据变化和接口异常。</div></div></div>
        <div class="panel-body">
          <div class="table-wrap">
            <table class="table external-history-table">
              <thead><tr><th>时间</th><th>方式</th><th>结果</th><th>同步内容</th></tr></thead>
              <tbody>${historyRows()}</tbody>
            </table>
          </div>
        </div>
      </section>
    </section>`;
  }

  function connectionTestHtml() {
    if (!connectionTest) return '<div class="subline">尚未测试连接</div>';
    if (!connectionTest.ok) {
      return `<div class="alert err"><b>连接失败</b><div>${escapeHtml(connectionTest.message || '新畅联连接测试失败')}</div>${connectionTest.detail ? `<div>${escapeHtml(connectionTest.detail)}</div>` : ''}${connectionTest.solution ? `<div>建议：${escapeHtml(connectionTest.solution)}</div>` : ''}</div>`;
    }
    const rows = Array.isArray(connectionTest.steps) ? connectionTest.steps : [];
    const body = rows.map(row => {
      const status = String(row.status || '');
      const pill = status === 'success' ? 'ok' : status === 'skipped' ? 'warn' : 'err';
      const label = status === 'success' ? '成功' : status === 'skipped' ? '跳过' : '失败';
      return `<tr><td>${escapeHtml(row.name || row.key || '-')}</td><td><span class="pill ${pill}">${label}</span></td><td>${escapeHtml(row.count ?? row.detail ?? '-')}</td></tr>`;
    }).join('');
    return `<div class="alert ok"><b>连接成功</b> · ${escapeHtml(connectionTest.base_url || '')}</div><table class="table"><thead><tr><th>检查项</th><th>结果</th><th>详情/数量</th></tr></thead><tbody>${body || '<tr><td colspan="3">鉴权连接正常</td></tr>'}</tbody></table>`;
  }

  function paintConnectionTest() {
    const root = document.getElementById('externalConnectionResult');
    if (root) root.innerHTML = connectionTestHtml();
  }

  function diagnosticsHtml() {
    if (!diagnostics) return '';
    const rows = Array.isArray(diagnostics.steps) ? diagnostics.steps : [];
    const body = rows.map(row => `<tr><td>${escapeHtml(row.name || row.key || '-')}</td><td><span class="pill ${row.status === 'success' ? 'ok' : row.status === 'skipped' ? 'warn' : 'err'}">${row.status === 'success' ? '成功' : row.status === 'skipped' ? '跳过' : '失败'}</span></td><td>${escapeHtml(row.count ?? row.detail ?? '-')}</td></tr>`).join('');
    return `<section class="panel" data-platform-tab-panel="sync"><div class="panel-head"><div><div class="panel-title">联调诊断</div><div class="subline">只读检查鉴权、品目、算法产品、分析方式、算力环境、算法版本和算法权重，不创建、修改或删除新畅联数据。</div></div></div><div class="panel-body"><table class="table"><thead><tr><th>检查项</th><th>结果</th><th>详情/数量</th></tr></thead><tbody>${body || '<tr><td colspan="3">暂无诊断结果</td></tr>'}</tbody></table></div></section>`;
  }


  function apiContractHtml() {
    const documents = Array.isArray(config?.apiDocuments) ? config.apiDocuments : [];
    if (!documents.length) return '';
    const rows = documents.map(item => {
      const wired = item.status === 'wired';
      const reference = item.status === 'reference';
      const stateText = wired ? '已接入' : reference ? '参考文档' : '文档已纳入';
      const pill = wired ? 'ok' : reference ? 'warn' : '';
      const methodPath = item.method && item.path
        ? `<code>${escapeHtml(item.method)} ${escapeHtml(item.path)}</code>`
        : '<span class="subline">未配置 Method / Path</span>';
      return `<tr>
        <td>${escapeHtml(item.group || '其他')}</td>
        <td><a href="${escapeHtml(item.doc_url || '#')}" target="_blank" rel="noopener noreferrer">${escapeHtml(item.title || item.key || '-')}</a></td>
        <td>${methodPath}</td>
        <td><span class="pill ${pill}">${stateText}</span></td>
      </tr>`;
    }).join('');
    const summary = config?.apiDocumentSummary || {};
    return `<section class="panel external-api-contract" data-platform-tab-panel="api" data-changlian-api-contract="1">
      <div class="panel-head">
        <div><div class="panel-title">新畅联接口契约</div><div class="external-contract-summary muted-line">已核对 ${Number(summary.total || documents.length)} 个官方 OpenAPI 接口；除人员登录参考外，内部算法接口均已进入 Provider contract。连接测试只调用鉴权和只读查询，不会自动执行新增、修改或删除。</div></div>
      </div>
      <div class="panel-body">
        <div class="alert warn" style="margin-bottom:12px">完整 OpenAPI 已锁定正式 Method / Path / Bearer 鉴权；算法版本与算法权重的修改、删除只允许显式管理操作，测试连接不会触发。</div>
        <table class="table"><thead><tr><th>分类</th><th>官方接口文档</th><th>当前绑定</th><th>状态</th></tr></thead><tbody>${rows}</tbody></table>
      </div>
    </section>`;
  }

  function masterDataPreviewHtml() {
    const categories = Array.isArray(cacheData?.categories) ? cacheData.categories.slice(0, 12) : [];
    const products = Array.isArray(cacheData?.products) ? cacheData.products.slice(0, 20) : [];
    const categoryRows = categories.length ? categories.map(row => `<tr>
      <td>${escapeHtml(row.categoryName || row.name || '-')}</td>
      <td>${escapeHtml(row.categoryId || row.id || '-')}</td>
      <td>${escapeHtml(row.parentId || '-')}</td>
    </tr>`).join('') : '<tr><td colspan="3">尚未同步算法品目</td></tr>';
    const productRows = products.length ? products.map(row => `<tr>
      <td>${escapeHtml(row.productName || row.name || '-')}</td>
      <td>${escapeHtml(row.productCode || row.code || '-')}</td>
      <td>${escapeHtml(row.productId || row.id || '-')}</td>
      <td>${escapeHtml(row.categoryName || row.category?.categoryName || row.categoryId || '-')}</td>
    </tr>`).join('') : '<tr><td colspan="4">尚未同步算法产品</td></tr>';
    return `<section class="panel">
      <details class="external-master-data">
        <summary><div><b>已同步主数据</b><span>只读查看新畅联缓存，名称与归属仍以新畅联为准</span></div><em>查看详情</em></summary>
        <div class="panel-body">
          <div class="panel-title" style="margin-bottom:10px">算法品目</div>
          <table class="table"><thead><tr><th>品目名称</th><th>品目 ID</th><th>父级 ID</th></tr></thead><tbody>${categoryRows}</tbody></table>
          <div class="panel-title" style="margin:18px 0 10px">算法产品</div>
          <table class="table"><thead><tr><th>算法名称</th><th>产品编码</th><th>Product ID</th><th>品目</th></tr></thead><tbody>${productRows}</tbody></table>
        </div>
      </details>
    </section>`;
  }

  function historyRows() {
    if (!history.length) return '<tr><td colspan="4">暂无同步记录</td></tr>';
    return history.map(item => `<tr>
      <td>${escapeHtml(timeText(item.finished_at || item.started_at))}</td>
      <td>${item.sync_type === 'manual' ? '手动' : '自动'}</td>
      <td><span class="pill ${item.status === 'success' ? 'ok' : item.status === 'failed' ? 'err' : 'warn'}">${escapeHtml(syncStatusText(item.status))}</span></td>
      <td>${escapeHtml(syncCountsText(item) || item.error || '-')}</td>
    </tr>`).join('');
  }

  function collectForm() {
    const mode = document.querySelector('input[name="externalMode"]:checked')?.value || 'local';
    return {
      mode,
      provider: document.getElementById('externalProvider')?.value || 'changlian',
      base_url: document.getElementById('externalBaseUrl')?.value.trim() || '',
      auto_sync_enabled: mode === 'external',
      auto_sync_interval_seconds: 60,
      auto_publish_enabled: mode === 'external',
      access_key: document.getElementById('externalAccessKey')?.value.trim() || null,
      access_secret: document.getElementById('externalAccessSecret')?.value || null,
      endpoints: config?.endpoints || {},
    };
  }

  async function save({quiet = false} = {}) {
    if (externalMode() && config?.baseUrl && config?.credentials?.configured === true && !configEditing) {
      throw new Error('配置已锁定，请先点击“编辑配置”再修改');
    }
    const payload = collectForm();
    const body = await requestJson(`${API_ROOT}/config`, {
      method: 'PUT',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    config = normalizeExternalPlatformConfig(body);
    state().externalAlgorithmPlatformConfig = config;
    persistConfigSnapshot();
    configEditing = false;
    if (!quiet) notify?.('平台对接配置已保存并锁定，后续将持续使用此配置');
    return config;
  }

  async function beginConfigEdit() {
    if (!(externalMode() && config?.baseUrl && config?.credentials?.configured === true)) return false;
    configEditing = true;
    connectionTest = null;
    await render({reload: false, refreshConfigPanel: true});
    return true;
  }

  async function cancelConfigEdit() {
    configEditing = false;
    connectionTest = null;
    await render({reload: false, refreshConfigPanel: true});
    return true;
  }

  async function testConnection() {
    const payload = collectForm();
    const button = document.getElementById('externalPlatformTest');
    if (button) { button.disabled = true; button.textContent = '正在测试…'; }
    connectionTest = null;
    paintConnectionTest();
    try {
      connectionTest = await requestJson(`${API_ROOT}/test`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload),
      });
      paintConnectionTest();
      notify?.(connectionTest.ok ? '新畅联连接测试通过' : '新畅联连接测试存在失败项');
      return connectionTest;
    } catch (error) {
      connectionTest = {
        ok: false,
        message: error?.message || '新畅联连接测试失败',
        detail: error?.detail || '',
        solution: error?.solution || '',
      };
      paintConnectionTest();
      notify?.(connectionTest.message);
      return connectionTest;
    } finally {
      if (button) { button.disabled = false; button.textContent = '测试连接'; }
    }
  }

  async function runDiagnostics() {
    const payload = String(state().page || '') === PAGE ? collectForm() : null;
    const button = document.getElementById('externalPlatformDiagnostics');
    if (button) { button.disabled = true; button.textContent = '正在诊断…'; }
    try {
      diagnostics = await requestJson(`${API_ROOT}/diagnostics`, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: payload ? JSON.stringify(payload) : undefined,
      });
      notify?.(diagnostics.ok ? '新畅联联调诊断通过' : '联调诊断存在失败项，请查看详情');
      if (String(state().page || '') === PAGE) await render({reload: false});
      return diagnostics;
    } finally {
      if (button) { button.disabled = false; button.textContent = '联调诊断'; }
    }
  }

  async function syncNow() {
    const pid = currentProjectId();
    if (!pid) return notify?.('当前项目不可用，请刷新页面后重试');
    if (!config) await loadConfig({silent: true});
    if (!externalMode()) return notify?.('请先切换为外部平台并保存配置');
    if (!config?.baseUrl || config?.credentials?.configured !== true) {
      return notify?.('请先保存 API 地址、AccessKey 和 AccessSecret，再执行同步');
    }

    const buttons = [
      document.getElementById('externalPlatformSync'),
      ...document.querySelectorAll('[data-external-list-sync]'),
    ].filter(Boolean);
    for (const button of buttons) {
      button.disabled = true;
      button.dataset.originalText = button.textContent || '';
      button.textContent = '正在同步…';
    }
    try {
      const body = await requestJson(`${API_ROOT}/sync?project_id=${encodeURIComponent(pid)}`, {method: 'POST'});
      const counts = body?.sync?.counts || {};
      await Promise.all([loadConfig({silent: true}), loadHistory({silent: true}), loadCache({silent: true}), loadReadiness({silent: true})]);
      await algorithmListRuntime?.refresh?.({render: String(state().page || '') === '算法列表'});
      notify?.(`同步完成：算法新增 ${counts.added || 0}，更新 ${counts.updated || 0}`);
      if (String(state().page || '') === PAGE) await render({reload: false});
      return body;
    } finally {
      for (const button of buttons) {
        button.disabled = false;
        button.textContent = button.dataset.originalText || (button.id === 'externalPlatformSync' ? '↻ 立即同步' : '↻ 同步畅联云');
        delete button.dataset.originalText;
      }
    }
  }

  function bindPage() {
    const root = document.querySelector('[data-external-platform-page="1"]');
    for (const tabButton of document.querySelectorAll('[data-external-platform-tab]')) {
      tabButton.onclick = () => {
        const next = String(tabButton.dataset.externalPlatformTab || 'overview');
        if (!['overview', 'connection', 'sync', 'vendor', 'api', 'history'].includes(next)) return;
        activeTab = next;
        state().externalPlatformTab64 = next;
        if (root) root.dataset.activeTab = next;
        for (const button of document.querySelectorAll('[data-external-platform-tab]')) {
          button.classList.toggle('active', button === tabButton);
        }
        if (next === 'vendor') void window.ExternalAlgorithmPublishRuntime?.decoratePlatformPage?.();
      };
    }
    const saveButton = document.getElementById('externalPlatformSave');
    const editButton = document.getElementById('externalPlatformEdit');
    const cancelEditButton = document.getElementById('externalPlatformCancelEdit');
    const testButton = document.getElementById('externalPlatformTest');
    const diagnosticsButton = document.getElementById('externalPlatformDiagnostics');
    const syncButton = document.getElementById('externalPlatformSync');
    const secretToggle = document.getElementById('externalSecretToggle');
    const secretInput = document.getElementById('externalAccessSecret');
    if (saveButton) saveButton.onclick = () => void save().then(() => render({reload: false})).catch(error => notify?.(error?.message || error));
    if (editButton) editButton.onclick = () => void beginConfigEdit().catch(error => notify?.(error?.message || error));
    if (cancelEditButton) cancelEditButton.onclick = () => void cancelConfigEdit().catch(error => notify?.(error?.message || error));
    if (testButton) testButton.onclick = () => void testConnection().catch(error => notify?.(error?.message || error));
    if (diagnosticsButton) diagnosticsButton.onclick = () => void runDiagnostics().catch(error => notify?.(error?.message || error));
    if (syncButton) syncButton.onclick = () => void syncNow().catch(error => notify?.(error?.message || error));
    if (secretToggle && secretInput) secretToggle.onclick = () => {
      const show = secretInput.type === 'password';
      secretInput.type = show ? 'text' : 'password';
      secretToggle.textContent = show ? '隐藏' : '显示';
    };

    const markConfigDirty = () => {
      if (externalMode() && config?.baseUrl && config?.credentials?.configured === true && !configEditing) return;
      if (syncButton) {
        syncButton.disabled = true;
        syncButton.title = '当前配置有未保存修改，请先保存配置';
      }
      if (saveButton) saveButton.dataset.dirty = '1';
    };
    for (const input of document.querySelectorAll(
      'input[name="externalMode"], #externalProvider, #externalBaseUrl, #externalAccessKey, #externalAccessSecret, [data-external-endpoint]'
    )) {
      if (input.dataset.externalDirtyBound === '1') continue;
      input.dataset.externalDirtyBound = '1';
      input.addEventListener('input', markConfigDirty);
      input.addEventListener('change', markConfigDirty);
    }
  }

  function externalPagePatchKey(node, index) {
    if (!node) return `missing:${index}`;
    if (node.matches?.('.external-platform-hero')) return 'hero';
    if (node.matches?.('.external-platform-steps')) return 'steps';
    if (node.matches?.('.external-platform-config')) return 'config';
    const title = node.querySelector?.('.panel-title')?.textContent?.trim();
    if (title) return `panel:${title}`;
    const marker = [...(node.classList || [])].sort().join('.');
    return `${node.tagName || 'node'}:${marker}:${index}`;
  }

  function patchExternalPlatformPage(view, html, {preserveConfigDraft = false} = {}) {
    if (!view || !html) return false;
    const template = document.createElement('template');
    template.innerHTML = html.trim();
    const nextRoot = template.content.firstElementChild;
    if (!nextRoot) return false;
    const currentRoot = view.querySelector(':scope > [data-external-platform-page="1"]');
    if (!currentRoot) {
      view.replaceChildren(nextRoot);
      bindPage();
      return true;
    }

    const currentByKey = new Map(
      [...currentRoot.children].map((node, index) => [externalPagePatchKey(node, index), node])
    );
    const keep = new Set();
    [...nextRoot.children].forEach((nextNode, index) => {
      const key = externalPagePatchKey(nextNode, index);
      keep.add(key);
      let currentNode = currentByKey.get(key);
      const preserveDraft = preserveConfigDraft && key === 'config';
      if (!currentNode) {
        currentRoot.appendChild(nextNode);
        currentNode = nextNode;
      } else if (!preserveDraft && currentNode.outerHTML !== nextNode.outerHTML) {
        currentNode.replaceWith(nextNode);
        currentNode = nextNode;
      }
      const at = currentRoot.children[index];
      if (at !== currentNode) currentRoot.insertBefore(currentNode, at || null);
    });
    for (const [key, node] of currentByKey) {
      if (!keep.has(key)) node.remove();
    }
    currentRoot.className = nextRoot.className;
    currentRoot.dataset.externalPlatformPage = '1';
    currentRoot.dataset.activeTab = activeTab;
    bindPage();
    return true;
  }

  async function render({reload = true, force = false, refreshConfigPanel = false} = {}) {
    if (destroyed || String(state().page || '') !== PAGE) return false;
    const view = document.getElementById('view');
    if (!view) return false;
    if (reload) configEditing = false;

    const paintCachedPage = () => {
      if (!config || String(state().page || '') !== PAGE) return false;
      return patchExternalPlatformPage(view, configFormHtml(config), {
        preserveConfigDraft: configEditing && !refreshConfigPanel,
      });
    };
    const hasSnapshot = paintCachedPage();
    if (loading) return hasSnapshot;

    const age = Date.now() - Number(pageLoadedAt || 0);
    const fresh = pageLoadedAt > 0 && age >= 0 && age < PLATFORM_PAGE_CACHE_TTL_MS;
    if (config && (!reload || (!force && fresh))) return true;

    loading = true;
    if (!config) view.innerHTML = '<div class="empty">首次读取平台对接配置…</div>';
    try {
      const [nextConfig, nextHistory, nextCache, nextReadiness] = await Promise.all([
        loadConfig({silent: true}),
        loadHistory({silent: true}),
        loadCache({silent: true}),
        loadReadiness({silent: true}),
      ]);
      config = nextConfig;
      history = nextHistory;
      cacheData = nextCache;
      readiness = nextReadiness;
      pageLoadedAt = Date.now();
      return paintCachedPage();
    } catch (error) {
      if (!hasSnapshot && String(state().page || '') === PAGE) {
        view.innerHTML = `<div class="alert err">${escapeHtml(error?.message || error)}</div>`;
      } else if (force) {
        notify?.(error?.message || error);
      }
      return hasSnapshot;
    } finally {
      loading = false;
    }
  }

  const detachAlgorithmListProvider = algorithmListRuntime?.setExternalProvider?.(algorithmListProvider) || null;
  trainingAnalysisObserver = new MutationObserver(() => decorateTrainingAnalysisSelector());
  trainingAnalysisObserver.observe(document.body, {childList: true, subtree: true});
  void Promise.all([loadConfig({silent: true}), loadCache({silent: true})]).then(() => {
    if (String(state().page || '') === '算法列表') algorithmListRuntime?.render?.();
    decorateTrainingAnalysisSelector();
  }).catch(() => {});

  const runtime = {
    build: 'external-algorithm-platform-63018',
    page: PAGE,
    loadConfig,
    loadHistory,
    loadCache,
    loadReadiness,
    render,
    save,
    beginConfigEdit,
    cancelConfigEdit,
    isConfigEditing: () => configEditing,
    testConnection,
    runDiagnostics,
    syncNow,
    selectedAnalysisId,
    trainingReadiness,
    trainingPreflightFresh,
    preflightTraining,
    decorateTrainingAnalysisSelector,
    config: () => config,
    destroy() {
      destroyed = true;
      trainingAnalysisObserver?.disconnect();
      detachAlgorithmListProvider?.();
      trainingPreflightCache.clear();
      if (window.ExternalAlgorithmPlatformRuntime === runtime) window.ExternalAlgorithmPlatformRuntime = null;
      window.__externalAlgorithmPlatformRuntimeInstalled = false;
    },
  };
  window.ExternalAlgorithmPlatformRuntime = runtime;
  window.__externalAlgorithmPlatformRuntimeInstalled = true;
  return runtime;
}
