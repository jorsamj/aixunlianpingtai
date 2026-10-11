const ALGORITHM_PAGE = '算法列表';

function rawFetch() {
  const scoped = window.fetch;
  return scoped?.__pageRequestScopeOriginal || scoped;
}

async function fetchJson(url, fetchImpl = rawFetch()) {
  const response = await fetchImpl(url, {headers: {'Accept': 'application/json'}});
  if (!response.ok) {
    const raw = await response.text();
    let body = {};
    try { body = JSON.parse(raw); } catch (_) { body = {detail: raw}; }
    throw new Error(String(body.message || body.detail || `刷新失败（HTTP ${response.status}）`));
  }
  return response.json();
}

function listFrom(value) {
  if (Array.isArray(value)) return value;
  return Array.isArray(value?.items) ? value.items : [];
}

export function algorithmListSearchMatch(algorithm = {}, query = '') {
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return true;
  const values = [
    algorithm?.name,
    algorithm?.code,
    algorithm?.algorithm_code,
    algorithm?.algorithmCode,
    algorithm?.product_id,
    algorithm?.productId,
    algorithm?.product_code,
    algorithm?.productCode,
    algorithm?.external_product_id,
    algorithm?.external_product_code,
    algorithm?.remark,
    algorithm?.industry,
    algorithm?.algorithm_type,
  ];
  return values.some(value => String(value ?? '').toLowerCase().includes(needle));
}

export function algorithmCategorySearch(rows = [], query = '') {
  const needle = String(query || '').trim().toLowerCase();
  if (!needle) return [];
  return rows.filter(row => `${row?.name || ''} ${row?.path || ''}`.toLowerCase().includes(needle));
}

export function algorithmCategoryColumns(rows = [], activePath = []) {
  const path = Array.from(activePath || [], value => String(value || '')).filter(Boolean);
  const parentIds = ['', ...path].slice(-3);
  while (parentIds.length < 3) parentIds.push(`__empty_${parentIds.length}`);
  return parentIds.map(parentId => ({
    parentId,
    rows: rows.filter(row => String(row?.parentId || '') === parentId),
  }));
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function dateText(value) {
  if (!value) return '-';
  return String(value).replace('T', ' ').replace('Z', '').slice(0, 16);
}

function algorithmTypeText(value) {
  return ({
    yolo_ultralytics: 'YOLO / Ultralytics',
    paddle_detection: 'PaddleDetection',
    opencv: 'OpenCV',
    mmdetection: 'MMDetection',
    custom_python: '自定义 Python',
  })[String(value || '')] || String(value || '未分类');
}

function currentVersion(algorithm = {}) {
  const versions = Array.isArray(algorithm.versions) ? algorithm.versions : [];
  return versions.find(row => String(row.id || '') === String(algorithm.current_version_id || '')) || versions[0] || null;
}

export function algorithmVersionMap50(version = {}) {
  const metrics = version?.metrics || version?.evaluation?.metrics || {};
  for (const value of [version?.map50, version?.mAP50, metrics?.map50, metrics?.mAP50, metrics?.['metrics/mAP50(B)']]) {
    const number = Number(value);
    if (Number.isFinite(number)) return number > 1 ? number : number * 100;
  }
  return null;
}

function activeJob(algorithmId, jobs = []) {
  const active = new Set(['queued', 'waiting', 'pending', 'starting', 'running', 'pausing', 'paused', 'resuming']);
  return jobs.find(job => {
    const id = job?.asset_algorithm_id || job?.algorithm_asset_id || job?.algorithm_id || '';
    return String(id) === String(algorithmId) && active.has(String(job?.status || '').toLowerCase());
  }) || null;
}

function trainingStatusText(status) {
  return ({queued: '排队中', waiting: '等待资源', pending: '等待提交', starting: '启动中', running: '训练中', pausing: '暂停中', paused: '已暂停', resuming: '恢复中', stopping: '停止中', cancel_requested: '取消中'})[String(status || '').toLowerCase()] || String(status || '训练中');
}

function trainingFilterText(value) {
  return ({
    trainable: '仅可训练',
    training: '训练中',
    trained: '已有版本',
    untrained: '尚未训练',
    blocked: '不可训练',
  })[String(value || '')] || String(value || '');
}

export function installAlgorithmListRuntime({getState, projectId, notify} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__algorithmListRuntimeInstalled) return window.AlgorithmListRuntime;

  const state = () => getState?.() || {};
  const doc = typeof document !== 'undefined' ? document : null;
  let destroyed = false;
  let inflight = null;
  let lastRefreshAt = 0;
  let refreshError = '';
  let externalProvider = null;
  let trainingWarmupHandle = null;
  let trainingWarmupGeneration = 0;
  let commonTrainingWarmupProjectId = '';
  let commonTrainingWarmupAt = 0;
  const COMMON_TRAINING_WARMUP_TTL_MS = 5 * 60 * 1000;
  const renderedRows = new Map();
  const filters = {
    query: '',
    selectedCategoryIds: [],
    source: 'all',
    status: 'all',
    industry: 'all',
    type: 'all',
  };
  const viewState = {
    sort: 'comprehensive',
    page: 1,
    pageSize: 10,
    categoryOpen: false,
    categoryQuery: '',
    categoryPath: [],
    draftCategoryIds: new Set(),
  };
  const originalToggle412 = window.toggleAlgorithm412;
  const originalToggle428 = window.toggleAlgorithm428;

  function externalSnapshot() {
    const value = externalProvider?.snapshot?.() || {};
    return {
      categories: Array.isArray(value.categories) ? value.categories : [],
      categoryRows: Array.isArray(value.categoryRows) ? value.categoryRows : [],
      externalMode: value.externalMode === true,
    };
  }

  function categoryRows() {
    return externalSnapshot().categoryRows;
  }

  function filterState() {
    return {
      query: filters.query,
      selectedCategoryIds: [...filters.selectedCategoryIds],
      source: filters.source,
      status: filters.status,
    };
  }

  function setFilters(patch = {}, {render = true} = {}) {
    const next = patch && typeof patch === 'object' ? patch : {};
    if (Object.prototype.hasOwnProperty.call(next, 'query')) {
      filters.query = String(next.query || '').trim();
    }
    if (Object.prototype.hasOwnProperty.call(next, 'selectedCategoryIds')) {
      filters.selectedCategoryIds = [...new Set(
        Array.from(next.selectedCategoryIds || [], value => String(value || '').trim()).filter(Boolean),
      )];
    }
    if (Object.prototype.hasOwnProperty.call(next, 'source')) {
      const source = String(next.source || 'all');
      filters.source = ['all', 'internal', 'external'].includes(source) ? source : 'all';
    }
    if (Object.prototype.hasOwnProperty.call(next, 'status')) {
      const status = String(next.status || 'all');
      filters.status = ['all', 'trainable', 'training', 'trained', 'untrained', 'blocked'].includes(status)
        ? status
        : 'all';
    }
    if (Object.prototype.hasOwnProperty.call(next, 'industry')) filters.industry = String(next.industry || 'all');
    if (Object.prototype.hasOwnProperty.call(next, 'type')) filters.type = String(next.type || 'all');
    viewState.page = 1;
    if (render && String(state().page || '') === ALGORITHM_PAGE) renderPage();
    return filterState();
  }

  function matchesSearch(algorithm, query = filters.query) {
    return algorithmListSearchMatch(algorithm, query);
  }

  function categoryById(id) {
    return categoryRows().find(row => String(row.id) === String(id)) || null;
  }

  function setExternalProvider(provider) {
    externalProvider = provider && typeof provider === 'object' ? provider : null;
    const valid = new Set(categoryRows().map(row => String(row.id)));
    filters.selectedCategoryIds = filters.selectedCategoryIds.filter(id => valid.has(id));
    if (String(state().page || '') === ALGORITHM_PAGE) renderPage();
    return () => { if (externalProvider === provider) externalProvider = null; };
  }

  function openCategoryPicker() {
    viewState.categoryOpen = true;
    viewState.categoryQuery = '';
    viewState.categoryPath = [];
    viewState.draftCategoryIds = new Set(filters.selectedCategoryIds);
    renderCategoryPicker();
    return runtimeState();
  }

  function cancelCategoryPicker() {
    viewState.categoryOpen = false;
    viewState.categoryQuery = '';
    viewState.categoryPath = [];
    viewState.draftCategoryIds = new Set(filters.selectedCategoryIds);
    renderCategoryPicker();
    return runtimeState();
  }

  function toggleDraftCategory(id) {
    const key = String(id || '');
    const row = categoryById(key);
    if (!row || row.hasChildren === true) return runtimeState();
    if (viewState.draftCategoryIds.has(key)) viewState.draftCategoryIds.delete(key);
    else viewState.draftCategoryIds.add(key);
    renderCategoryPicker();
    return runtimeState();
  }

  function activateCategoryRow(id) {
    const row = categoryById(id);
    if (!row) return runtimeState();
    if (row.hasChildren === true) {
      viewState.categoryQuery = '';
      viewState.categoryPath = [...(row.ancestorIds || []).map(value => String(value || '')).filter(Boolean), String(row.id)];
      renderCategoryPicker();
      return runtimeState();
    }
    return toggleDraftCategory(row.id);
  }

  function confirmCategoryPicker() {
    const valid = [...viewState.draftCategoryIds].filter(id => { const row = categoryById(id); return row && row.hasChildren !== true; });
    filters.selectedCategoryIds = valid;
    try {
      const previous = JSON.parse(localStorage.getItem('cl_algorithm_recent_categories_v1') || '[]');
      localStorage.setItem('cl_algorithm_recent_categories_v1', JSON.stringify([...new Set([...valid, ...(Array.isArray(previous) ? previous : [])])].slice(0, 6)));
    } catch (_) {}
    viewState.categoryOpen = false;
    viewState.page = 1;
    renderPage();
    return filterState();
  }

  function providerMeta(algorithm) {
    return externalProvider?.meta?.(algorithm) || {
      external: String(algorithm?.source_type || '').toUpperCase() === 'EXTERNAL',
      sourceLabel: String(algorithm?.source_type || '').toUpperCase() === 'EXTERNAL' ? '外部平台' : '本平台',
      readiness: {ready: true, status: 'local', message: ''},
    };
  }

  function algorithmTrainability(algorithm) {
    const meta = providerMeta(algorithm);
    if (meta.external) {
      const ready = meta.readiness?.ready !== false;
      return {
        ready,
        message: ready ? '' : String(meta.readiness?.message || '当前外部算法不可训练'),
      };
    }
    const supported = new Set(['yolo_ultralytics', 'paddle_detection']);
    const ready = supported.has(String(algorithm?.algorithm_type || ''));
    return {
      ready,
      message: ready ? '' : '当前算法类型暂不支持直接训练',
    };
  }

  function warmTrainingInputs(algorithmId = '', {includePreflight = true} = {}) {
    const runtime = window.TrainingCreateHydrationRuntime;
    if (!runtime?.prewarm) return null;
    return runtime.prewarm(String(algorithmId || ''), {includePreflight}).catch(() => null);
  }

  function cancelTrainingWarmup() {
    trainingWarmupGeneration += 1;
    if (trainingWarmupHandle == null) return;
    if (typeof window.cancelIdleCallback === 'function') window.cancelIdleCallback(trainingWarmupHandle);
    else clearTimeout(trainingWarmupHandle);
    trainingWarmupHandle = null;
  }

  function scheduleTrainingWarmup(rows = []) {
    cancelTrainingWarmup();
    const generation = trainingWarmupGeneration;
    // The common training options/recommendation are global for the current
    // project. Warm them once, then keep local card rerenders network-free.
    const currentProjectId = String(projectId?.() || '');
    const now = Date.now();
    const commonWarmupFresh = currentProjectId
      && commonTrainingWarmupProjectId === currentProjectId
      && now - commonTrainingWarmupAt >= 0
      && now - commonTrainingWarmupAt < COMMON_TRAINING_WARMUP_TTL_MS;
    if (!commonWarmupFresh) {
      commonTrainingWarmupProjectId = currentProjectId;
      commonTrainingWarmupAt = now;
      queueMicrotask(() => {
        if (destroyed || generation !== trainingWarmupGeneration || String(state().page || '') !== ALGORITHM_PAGE) return;
        void warmTrainingInputs('', {includePreflight: false});
      });
    }
    // Real-time ChangLian preflight remains authoritative. Move the latency
    // off the click path by warming a small visible window while the browser is idle.
    const candidates = rows.filter(row => {
      const meta = providerMeta(row);
      return meta.external && algorithmTrainability(row).ready;
    }).slice(0, 6);
    if (!candidates.length) return;
    const run = async () => {
      trainingWarmupHandle = null;
      for (const row of candidates) {
        if (destroyed || generation !== trainingWarmupGeneration || String(state().page || '') !== ALGORITHM_PAGE) return;
        await warmTrainingInputs(row.id, {includePreflight: true});
      }
    };
    if (typeof window.requestIdleCallback === 'function') {
      trainingWarmupHandle = window.requestIdleCallback(() => void run(), {timeout: 800});
    } else {
      trainingWarmupHandle = window.setTimeout(() => void run(), 80);
    }
  }

  function algorithmMatches(algorithm) {
    if (!matchesSearch(algorithm)) return false;
    if (filters.industry !== 'all' && String(algorithm?.industry || '') !== filters.industry) return false;
    if (filters.type !== 'all' && String(algorithm?.algorithm_type || '') !== filters.type) return false;
    const meta = providerMeta(algorithm);
    const trainability = algorithmTrainability(algorithm);
    if (externalProvider?.matches) {
      const providerMatch = externalProvider.matches(algorithm, {
        source: filters.source,
        trainingStatus: filters.status,
        selectedCategoryIds: [...filters.selectedCategoryIds],
        jobs: state().jobs || [],
      });
      if (filters.status === 'blocked' && !meta.external) return trainability.ready === false;
      if (providerMatch === false) return false;
      if (filters.status === 'trainable') return trainability.ready;
      return true;
    }
    const external = String(algorithm?.source_type || '').toUpperCase() === 'EXTERNAL';
    if (filters.source === 'internal' && external) return false;
    if (filters.source === 'external' && !external) return false;
    if (filters.selectedCategoryIds.length !== 0) return false;
    if (filters.status === 'trainable') return trainability.ready;
    if (filters.status === 'blocked') return !trainability.ready;
    if (filters.status === 'trained') return (algorithm.versions || []).length > 0;
    if (filters.status === 'untrained') return (algorithm.versions || []).length === 0;
    if (filters.status === 'training') return Boolean(activeJob(algorithm.id, state().jobs || []));
    return true;
  }

  function trainingCount(id) {
    return (state().jobs || []).filter(job => String(job?.asset_algorithm_id || job?.algorithm_asset_id || job?.algorithm_id || '') === String(id)).length;
  }

  function visibleAlgorithms() {
    const rows = (state().algorithms || []).filter(algorithmMatches);
    if (viewState.sort === 'updated') return [...rows].sort((a, b) => String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')));
    if (viewState.sort === 'training') return [...rows].sort((a, b) => trainingCount(b.id) - trainingCount(a.id));
    if (viewState.sort === 'metric') return [...rows].sort((a, b) => (algorithmVersionMap50(currentVersion(b)) ?? -1) - (algorithmVersionMap50(currentVersion(a)) ?? -1));
    return [...rows].sort((a, b) => Number(Boolean(activeJob(b.id, state().jobs || []))) - Number(Boolean(activeJob(a.id, state().jobs || []))));
  }

  function shellHtml() {
    return `<section class="entity-page algorithm-list-page alg428-shell algorithm-card-page" data-algorithm-list-owner="AlgorithmListRuntime">
      <header class="algorithm-list-hero">
        <div><span class="algorithm-list-eyebrow">ALGORITHM REGISTRY</span><h2>算法列表</h2><p>以算法为单位查看训练状态、当前版本和核心指标；点击卡片空白区域即可展开版本。</p></div>
        <div class="entity-page-actions"><button class="btn" data-algorithm-sync hidden>同步畅联云</button><button class="btn primary" data-action="algorithm.create">＋ 新建算法</button></div>
      </header>
      <section class="entity-query-surface algorithm-filter-surface">
        <div class="algorithm-filter-primary">
          <label class="entity-search algorithm-search"><span>⌕</span><input id="alg412Q" class="input" type="search" placeholder="搜索算法名称 / 算法ID" data-algorithm-query></label>
          <button type="button" class="algorithm-trainable-toggle" data-algorithm-trainable-only><i>✓</i><span>仅看可训练</span><em data-algorithm-trainable-count>0</em></button>
          <div class="algorithm-category-control"><button class="btn algorithm-category-trigger" data-category-picker-toggle>品目筛选 <span></span></button><div class="algorithm-category-popover" data-category-popover hidden></div></div>
        </div>
        <div class="algorithm-filter-secondary">
          <select class="select" data-algorithm-source-filter><option value="all">来源 · 全部</option><option value="internal">本平台</option><option value="external">外部平台</option></select>
          <select id="alg412Industry" class="select" data-algorithm-industry-filter></select>
          <select id="alg412Type" class="select" data-algorithm-type-filter><option value="all">算法类型 · 全部</option><option value="yolo_ultralytics">YOLO / Ultralytics</option><option value="paddle_detection">PaddleDetection</option><option value="opencv">OpenCV</option><option value="mmdetection">MMDetection</option><option value="custom_python">自定义 Python</option></select>
          <select class="select" data-algorithm-training-status-filter><option value="all">训练状态 · 全部</option><option value="trainable">可训练</option><option value="training">训练中</option><option value="trained">已有版本</option><option value="untrained">尚未训练</option><option value="blocked">不可训练</option></select>
          <button class="btn entity-reset" data-algorithm-reset>重置</button>
        </div>
        <div class="entity-applied-filters" data-algorithm-applied hidden></div>
      </section>
      <div class="algorithm-list-meta"><div class="entity-sortbar"><button data-algorithm-sort="comprehensive" class="on">综合排序</button><button data-algorithm-sort="updated">最近更新</button><button data-algorithm-sort="training">训练次数</button><button data-algorithm-sort="metric">mAP50</button></div><span data-algorithm-result-count></span></div>
      <div class="entity-region-error" data-algorithm-error hidden></div>
      <section class="algorithm-card-surface"><div id="alg412List" class="algorithm-card-grid"></div><footer class="entity-pagination algorithm-card-pagination" data-algorithm-pagination></footer></section>
    </section>`;
  }

  function ensureAlgorithmShell() {
    if (destroyed || String(state().page || '') !== ALGORITHM_PAGE || !doc) return null;
    let root = doc.querySelector?.('[data-algorithm-list-owner="AlgorithmListRuntime"]');
    if (root) return root;
    const host = doc.getElementById?.('view');
    if (!host) return null;
    host.innerHTML = shellHtml();
    root = host.querySelector?.('[data-algorithm-list-owner="AlgorithmListRuntime"]') || null;
    bindShell(root);
    return root;
  }

  function renderControls(root) {
    const industries = [...new Set((state().algorithms || []).map(row => String(row?.industry || '').trim()).filter(Boolean))].sort((a, b) => a.localeCompare(b, 'zh-CN'));
    const industry = root.querySelector('[data-algorithm-industry-filter]');
    const signature = industries.join('|');
    if (industry?.dataset.signature !== signature) {
      industry.dataset.signature = signature;
      industry.innerHTML = `<option value="all">行业场景 · 全部</option>${industries.map(value => `<option value="${esc(value)}">${esc(value)}</option>`).join('')}`;
    }
    for (const [selector, value] of [['[data-algorithm-query]', filters.query], ['[data-algorithm-source-filter]', filters.source], ['[data-algorithm-industry-filter]', filters.industry], ['[data-algorithm-type-filter]', filters.type], ['[data-algorithm-training-status-filter]', filters.status]]) {
      const control = root.querySelector(selector);
      if (control && control.value !== value) control.value = value;
    }
    for (const button of root.querySelectorAll('[data-algorithm-sort]')) button.classList.toggle('on', button.dataset.algorithmSort === viewState.sort);
    const trainableToggle = root.querySelector('[data-algorithm-trainable-only]');
    const trainableCount = (state().algorithms || []).filter(row => algorithmTrainability(row).ready).length;
    if (trainableToggle) trainableToggle.classList.toggle('on', filters.status === 'trainable');
    const trainableCountNode = root.querySelector('[data-algorithm-trainable-count]');
    if (trainableCountNode) trainableCountNode.textContent = String(trainableCount);
    const sync = root.querySelector('[data-algorithm-sync]');
    if (sync) sync.hidden = !externalSnapshot().externalMode;
    const categories = filters.selectedCategoryIds.map(categoryById).filter(Boolean);
    const trigger = root.querySelector('[data-category-picker-toggle]');
    if (trigger) {
      trigger.classList.toggle('has-selection', categories.length > 0);
      trigger.querySelector('span').textContent = categories.length ? `已选 ${categories.length}` : '';
    }
    const applied = root.querySelector('[data-algorithm-applied]');
    const tags = [...categories.map(row => ({key: `category:${row.id}`, label: row.name})),
      ...(filters.source !== 'all' ? [{key: 'source', label: filters.source === 'external' ? '外部平台' : '本平台'}] : []),
      ...(filters.industry !== 'all' ? [{key: 'industry', label: filters.industry}] : []),
      ...(filters.type !== 'all' ? [{key: 'type', label: algorithmTypeText(filters.type)}] : []),
      ...(filters.status !== 'all' ? [{key: 'status', label: trainingFilterText(filters.status)}] : [])];
    if (applied) {
      applied.hidden = tags.length === 0;
      applied.innerHTML = tags.length ? `<span>已选：</span>${tags.map(tag => `<button data-remove-filter="${esc(tag.key)}">${esc(tag.label)} ×</button>`).join('')}<button class="entity-filter-clear" data-algorithm-reset>清空</button>` : '';
    }
  }

  function renderCategoryPicker() {
    const popover = doc?.querySelector?.('[data-algorithm-list-owner="AlgorithmListRuntime"] [data-category-popover]');
    if (!popover) return false;
    popover.hidden = !viewState.categoryOpen;
    if (!viewState.categoryOpen) return true;
    const rows = categoryRows();
    const active = new Set(viewState.categoryPath);
    const search = algorithmCategorySearch(rows, viewState.categoryQuery);
    const columns = algorithmCategoryColumns(rows, viewState.categoryPath);
    let recentIds = [];
    try { recentIds = JSON.parse(localStorage.getItem('cl_algorithm_recent_categories_v1') || '[]'); } catch (_) {}
    const recent = (Array.isArray(recentIds) ? recentIds : []).map(categoryById).filter(row => row && row.hasChildren !== true).slice(0, 6);
    const item = row => `<div class="algorithm-category-item ${active.has(String(row.id)) ? 'active' : ''}" data-category-id="${esc(row.id)}" data-category-row="${esc(row.id)}" role="button" tabindex="0" aria-label="${row.hasChildren ? '展开' : '选择'} ${esc(row.name)}"><span class="algorithm-category-item-main">${row.hasChildren ? '<span class="algorithm-category-node-dot" aria-hidden="true">·</span>' : `<input type="checkbox" data-category-check="${esc(row.id)}" aria-label="选择 ${esc(row.name)}" ${viewState.draftCategoryIds.has(String(row.id)) ? 'checked' : ''}>`}<span>${esc(row.name)}</span></span>${row.hasChildren ? '<button type="button" data-category-drill aria-label="查看下级">›</button>' : ''}</div>`;
    const body = viewState.categoryQuery
      ? `<div class="algorithm-category-search-results">${search.map(row => `<div class="algorithm-category-search-row ${viewState.draftCategoryIds.has(String(row.id)) ? 'selected' : ''}" data-category-id="${esc(row.id)}" data-category-row="${esc(row.id)}" role="button" tabindex="0" aria-label="${row.hasChildren ? '展开' : '选择'} ${esc(row.name)}">${row.hasChildren ? '<span class="algorithm-category-node-dot" aria-hidden="true">·</span>' : `<input type="checkbox" data-category-check="${esc(row.id)}" aria-label="选择 ${esc(row.name)}" ${viewState.draftCategoryIds.has(String(row.id)) ? 'checked' : ''}>`}<span><b>${esc(row.name)}</b><small>${esc(row.path)}</small></span>${row.hasChildren ? '<button type="button" data-category-drill aria-label="查看下级">›</button>' : ''}</div>`).join('') || '<div class="entity-empty compact">未找到匹配品目</div>'}</div>`
      : `<div class="algorithm-category-columns">${columns.map(column => `<div class="algorithm-category-column">${column.rows.map(item).join('') || '<div class="algorithm-category-column-empty">请选择上级品目</div>'}</div>`).join('')}</div>`;
    const selected = [...viewState.draftCategoryIds].map(categoryById).filter(Boolean);
    popover.innerHTML = `<header><b>选择品目</b><button data-category-close>×</button></header><label class="algorithm-category-search"><span>⌕</span><input type="search" value="${esc(viewState.categoryQuery)}" placeholder="搜索品目名称或路径" data-category-search></label>${recent.length ? `<div class="algorithm-category-recent"><span>最近使用：</span>${recent.map(row => `<button data-category-recent="${esc(row.id)}">${esc(row.name)}</button>`).join('')}</div>` : ''}${body}<footer><div><b>已选择 ${selected.length} 项</b><span>${selected.slice(0, 2).map(row => `<em>${esc(row.name)}</em>`).join('')}${selected.length > 2 ? `<em>+${selected.length - 2}</em>` : ''}</span></div><div><button class="btn" data-category-clear>清空</button><button class="btn primary" data-category-confirm>确定</button></div></footer>`;
    return true;
  }

  function versionRowsHtml(algorithm) {
    const versions = Array.isArray(algorithm?.versions) ? algorithm.versions : [];
    if (!versions.length) return '<div class="entity-empty compact">暂无版本，点击“训练”开始第一次迭代</div>';
    return versions.map(version => {
      const metric = algorithmVersionMap50(version);
      const current = String(algorithm.current_version_id || '') === String(version.id || '');
      const external = String(algorithm.source_type || '').toUpperCase() === 'EXTERNAL' && String(algorithm.provider_type || '').toUpperCase() === 'CHANG_LIAN';
      const published = String(version.external_publish_status || '').toLowerCase() === 'published';
      const downloadable = Boolean(String(version.stored_path || '').trim());
      const pid = encodeURIComponent(String(projectId?.() || ''));
      return `<div class="alg428-version-row"><div><b>${esc(version.version_name || '-')} ${current ? '<em>当前版本</em>' : ''}</b><span>${dateText(version.finished_at || version.created_at)}</span></div><div><span>mAP50</span><b>${metric == null ? '-' : `${metric.toFixed(1)}%`}</b></div><div class="alg428-version-actions"><button class="btn mini" onclick="openVersionReport429('${esc(algorithm.id)}','${esc(version.id)}')">训练报告</button>${version.training_lineage ? `<button class="btn mini" onclick="openVersionLineage429('${esc(algorithm.id)}','${esc(version.id)}')">训练溯源</button>` : ''}${version.evaluation ? `<button class="btn mini" onclick="openVersionEvaluation429('${esc(algorithm.id)}','${esc(version.id)}')">独立评测</button>` : ''}<button class="btn mini" onclick="openVersionConvert428('${esc(algorithm.id)}','${esc(version.id)}')">转换</button>${downloadable ? `<a class="btn mini" href="/api/v12/projects/${pid}/algorithms/${encodeURIComponent(String(algorithm.id || ''))}/versions/${encodeURIComponent(String(version.id || ''))}/download">下载模型</a>` : ''}${external ? `<button class="btn mini" data-external-publish-action onclick="window.AlgorithmListRuntime.publishVersion('${esc(algorithm.id)}','${esc(version.id)}',this)" ${published ? 'disabled' : ''}>${published ? '已发布' : '发布'}</button>` : ''}${current ? '' : `<button class="btn mini" onclick="openVersionRollback('${esc(algorithm.id)}','${esc(version.id)}')">回退</button>`}</div></div>`;
    }).join('');
  }

  function algorithmRowView(algorithm) {
    const version = currentVersion(algorithm);
    const metric = algorithmVersionMap50(version);
    const count = trainingCount(algorithm.id);
    const meta = providerMeta(algorithm);
    const trainability = algorithmTrainability(algorithm);
    const run = activeJob(algorithm.id, state().jobs || []);
    const status = run
      ? String(run.status_text || trainingStatusText(run.status))
      : algorithm.external_active === false ? '已下架'
        : !trainability.ready ? '不可训练'
          : version ? '已训练' : '可训练';
    const statusClass = run ? 'running' : !trainability.ready ? 'warning' : version ? 'success' : 'neutral';
    const open = Boolean(state().alg428Expanded?.[algorithm.id]);
    const tags = [algorithm.industry, algorithmTypeText(algorithm.algorithm_type), meta.sourceLabel || '本平台'].filter(Boolean);
    const updated = algorithm.updated_at || version?.finished_at || version?.created_at || algorithm.created_at;
    const remark = String(algorithm.remark || '').trim() || '暂无算法说明';
    const html = `<article class="alg428-card algorithm-registry-card ${open ? 'open' : ''}" data-algorithm-id="${esc(algorithm.id)}" data-algorithm-card="1" tabindex="0" aria-expanded="${open ? 'true' : 'false'}">
      <div class="alg428-main algorithm-card-main">
        <div class="algorithm-card-overview">
          <section class="algorithm-card-primary">
            <header class="algorithm-card-head">
              <span class="algorithm-avatar algorithm-card-avatar">${esc(String(algorithm.name || '算').slice(0, 1))}</span>
              <div class="algorithm-card-title"><div><h3 title="${esc(algorithm.name || '')}">${esc(algorithm.name || '未命名算法')}</h3><span class="entity-status ${statusClass}" title="${esc(trainability.message || meta.readiness?.message || '')}">${esc(status)}</span></div><div class="algorithm-card-tags">${tags.map(tag => `<em>${esc(tag)}</em>`).join('')}</div></div>
              <span class="algorithm-card-chevron" aria-hidden="true">⌄</span>
            </header>
            <p class="algorithm-card-description" title="${esc(remark)}">${esc(remark)}</p>
          </section>
          <div class="algorithm-card-stats">
            <div><span>当前版本</span><b>${esc(version?.version_name || '尚未训练')}</b><small>${(algorithm.versions || []).length} 个版本</small></div>
            <div><span>当前 mAP50</span><b class="${metric == null ? '' : 'metric'}">${metric == null ? '-' : `${metric.toFixed(1)}%`}</b><small>${metric == null ? '暂无指标' : '当前版本'}</small></div>
            <div><span>训练次数</span><b>${count}</b><small>历史任务</small></div>
          </div>
          <aside class="algorithm-card-side">
            <div class="algorithm-card-updated"><span>最近更新</span><b>${dateText(updated)}</b></div>
            <div class="entity-row-actions algorithm-card-actions">
              <button onclick="window.AlgorithmListRuntime.openDetail('${esc(algorithm.id)}')">详情</button>
              <button onclick="algorithmReport429('${esc(algorithm.id)}')">报告</button>
              <button class="primary-link" data-algorithm-train="${esc(algorithm.id)}" onclick="startAlgorithmTraining429('${esc(algorithm.id)}')" ${trainability.ready ? '' : `disabled title="${esc(trainability.message || '当前不可训练')}"`}>训练</button>
              <details class="entity-more"><summary>•••</summary><div><button onclick="editAlgorithm423('${esc(algorithm.id)}')" ${meta.external ? 'disabled' : ''}>编辑</button><button class="danger" onclick="delAlgorithm('${esc(algorithm.id)}')" ${meta.external ? 'disabled' : ''}>删除</button></div></details>
            </div>
          </aside>
        </div>
      </div>
      ${open ? `<div class="algorithm-version-surface"><header><b>迭代版本</b><span>当前版本决定训练、转换和检测的默认起点</span></header>${versionRowsHtml(algorithm)}</div>` : ''}
    </article>`;
    return {id: String(algorithm.id || ''), html, signature: JSON.stringify({algorithm, count, meta, trainability, status, open})};
  }

  function renderRows() {
    const root = ensureAlgorithmShell();
    const body = root?.querySelector?.('#alg412List');
    if (!body) return false;
    const all = visibleAlgorithms();
    const maxPage = Math.max(1, Math.ceil(all.length / viewState.pageSize));
    viewState.page = Math.min(Math.max(1, viewState.page), maxPage);
    const rows = all.slice((viewState.page - 1) * viewState.pageSize, viewState.page * viewState.pageSize);
    if (!doc?.createElement || typeof body.querySelectorAll !== 'function') {
      body.innerHTML = rows.map(row => algorithmRowView(row).html).join('');
    } else if (!rows.length) {
      body.innerHTML = '<div class="entity-empty algorithm-card-empty"><b>暂无符合条件的算法</b><span>请调整筛选条件或新建算法</span></div>';
      renderedRows.clear();
    } else {
      body.querySelector('.algorithm-card-empty')?.remove();
      const existing = new Map([...body.querySelectorAll('[data-algorithm-id]')].map(row => [String(row.dataset.algorithmId || ''), row]));
      const wanted = new Set();
      rows.forEach((algorithm, index) => {
        const item = algorithmRowView(algorithm);
        wanted.add(item.id);
        let row = existing.get(item.id) || null;
        if (!row || renderedRows.get(item.id) !== item.signature) {
          const holder = doc.createElement('div');
          holder.innerHTML = item.html;
          const next = holder.firstElementChild;
          if (!next) return;
          if (row) row.replaceWith(next);
          row = next;
        }
        const reference = body.children[index] || null;
        if (reference !== row) body.insertBefore(row, reference);
        renderedRows.set(item.id, item.signature);
      });
      for (const [id, row] of existing) if (!wanted.has(id)) {
        row.remove();
        renderedRows.delete(id);
      }
    }
    const count = root.querySelector('[data-algorithm-result-count]');
    if (count) count.textContent = `共 ${all.length} 个算法`;
    const pagination = root.querySelector('[data-algorithm-pagination]');
    if (pagination) pagination.innerHTML = `<span>共 ${all.length} 条</span><div><span>${viewState.pageSize} 条/页</span><button data-algorithm-page="${viewState.page - 1}" ${viewState.page <= 1 ? 'disabled' : ''}>‹</button>${Array.from({length: maxPage}, (_, index) => index + 1).slice(Math.max(0, viewState.page - 3), Math.max(5, viewState.page + 2)).map(page => `<button data-algorithm-page="${page}" class="${page === viewState.page ? 'on' : ''}">${page}</button>`).join('')}<button data-algorithm-page="${viewState.page + 1}" ${viewState.page >= maxPage ? 'disabled' : ''}>›</button></div>`;
    scheduleTrainingWarmup(rows);
    return true;
  }

  function renderPage() {
    const root = ensureAlgorithmShell();
    if (!root) return false;
    renderControls(root);
    const error = root.querySelector('[data-algorithm-error]');
    if (error) { error.hidden = !refreshError; error.textContent = refreshError; }
    renderRows();
    renderCategoryPicker();
    return true;
  }

  function resetFilters() {
    Object.assign(filters, {query: '', selectedCategoryIds: [], source: 'all', status: 'all', industry: 'all', type: 'all'});
    viewState.page = 1;
    renderPage();
  }

  function runtimeState() {
    return {inflight: Boolean(inflight), lastRefreshAt, error: refreshError, ...filterState(), industry: filters.industry, type: filters.type, sort: viewState.sort, page: viewState.page, categoryOpen: viewState.categoryOpen, draftCategoryIds: [...viewState.draftCategoryIds]};
  }

  function bindShell(root) {
    if (!root || root.dataset.bound === '1') return;
    root.dataset.bound = '1';
    root.addEventListener('input', event => {
      if (event.target.matches('[data-algorithm-query]')) setFilters({query: event.target.value});
      if (event.target.matches('[data-category-search]')) { viewState.categoryQuery = event.target.value; renderCategoryPicker(); root.querySelector('[data-category-search]')?.focus?.(); }
    });
    root.addEventListener('change', event => {
      if (event.target.matches('[data-algorithm-source-filter]')) setFilters({source: event.target.value});
      if (event.target.matches('[data-algorithm-industry-filter]')) setFilters({industry: event.target.value});
      if (event.target.matches('[data-algorithm-type-filter]')) setFilters({type: event.target.value});
      if (event.target.matches('[data-algorithm-training-status-filter]')) setFilters({status: event.target.value});
      if (event.target.matches('[data-category-check]')) toggleDraftCategory(event.target.dataset.categoryCheck);
    });
    root.addEventListener('click', event => {
      if (event.target.closest('[data-algorithm-reset]')) return resetFilters();
      const remove = event.target.closest('[data-remove-filter]');
      if (remove) { const key = String(remove.dataset.removeFilter || ''); if (key.startsWith('category:')) filters.selectedCategoryIds = filters.selectedCategoryIds.filter(id => id !== key.slice(9)); else if (key in filters) filters[key] = 'all'; return renderPage(); }
      const sort = event.target.closest('[data-algorithm-sort]'); if (sort) { viewState.sort = sort.dataset.algorithmSort; viewState.page = 1; return renderPage(); }
      const page = event.target.closest('[data-algorithm-page]'); if (page && !page.disabled) { viewState.page = Number(page.dataset.algorithmPage || 1); return renderRows(); }
      const toggleRow = event.target.closest('[data-algorithm-toggle]'); if (toggleRow) return toggle(toggleRow.dataset.algorithmToggle);
      if (event.target.closest('[data-algorithm-trainable-only]')) return setFilters({status: filters.status === 'trainable' ? 'all' : 'trainable'});
      if (event.target.closest('[data-category-picker-toggle]')) return openCategoryPicker();
      if (event.target.closest('[data-category-close]')) return cancelCategoryPicker();
      if (event.target.closest('[data-category-clear]')) { viewState.draftCategoryIds.clear(); return renderCategoryPicker(); }
      if (event.target.closest('[data-category-confirm]')) return confirmCategoryPicker();
      const recent = event.target.closest('[data-category-recent]'); if (recent) return toggleDraftCategory(recent.dataset.categoryRecent);
      const categoryCheck = event.target.closest('[data-category-check]');
      if (categoryCheck) return;
      const categoryRow = event.target.closest('[data-category-row]');
      if (categoryRow) return activateCategoryRow(categoryRow.dataset.categoryRow);
      if (event.target.closest('[data-algorithm-sync]')) return void externalProvider?.sync?.();
      const card = event.target.closest('[data-algorithm-card]');
      if (card && !event.target.closest('button,a,input,select,textarea,label,details,summary')) return toggle(card.dataset.algorithmId);
    });
    root.addEventListener('keydown', event => {
      const categoryRow = event.target.closest?.('[data-category-row]');
      if (categoryRow && event.target === categoryRow && ['Enter', ' '].includes(event.key)) {
        event.preventDefault();
        activateCategoryRow(categoryRow.dataset.categoryRow);
        return;
      }
      const card = event.target.closest?.('[data-algorithm-card]');
      if (!card || event.target !== card || !['Enter', ' '].includes(event.key)) return;
      event.preventDefault();
      toggle(card.dataset.algorithmId);
    });
    const prewarmTrainingAction = event => {
      const button = event.target.closest?.('[data-algorithm-train]');
      if (!button) return;
      const card = button.closest?.('[data-algorithm-card]');
      if (!card) return;
      const algorithm = (state().algorithms || []).find(row => String(row.id) === String(card.dataset.algorithmId || ''));
      if (!algorithm || !algorithmTrainability(algorithm).ready) return;
      void warmTrainingInputs(algorithm.id, {includePreflight: true});
    };
    root.addEventListener('pointerover', prewarmTrainingAction, {passive: true});
    root.addEventListener('focusin', prewarmTrainingAction);
    root.addEventListener('touchstart', prewarmTrainingAction, {passive: true});
  }

  function toggle(id) {
    if (destroyed) return false;
    const s = state();
    s.alg428Expanded = s.alg428Expanded || {};
    const key = String(id || '');
    s.alg428Expanded[key] = !s.alg428Expanded[key];
    renderRows();
    return s.alg428Expanded[key];
  }
  toggle.__algorithmListRuntime = true;
  toggle.__algorithmListOriginal = originalToggle412;

  async function refresh({render = true, minAgeMs = 0} = {}) {
    if (destroyed) throw new Error('算法列表模块已销毁');
    const now = Date.now();
    if (minAgeMs > 0 && now - lastRefreshAt < minAgeMs) {
      if (render) renderPage();
      return {algorithms: state().algorithms || [], jobs: state().jobs || [], cached: true};
    }
    if (inflight) return inflight;
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目不可用，请刷新页面后重试');

    const navigationGeneration = window.PageRequestScopeRuntime?.stats?.().generation ?? null;
    const fetchImpl = rawFetch();
    if (typeof fetchImpl !== 'function') throw new Error('浏览器请求能力不可用');

    inflight = (async () => {
      const encoded = encodeURIComponent(pid);
      const [algorithmBody, jobBody] = await Promise.all([
        fetchJson(`/api/v12/projects/${encoded}/algorithms`, fetchImpl),
        fetchJson(`/api/projects/${encoded}/jobs`, fetchImpl),
      ]);

      const latestGeneration = window.PageRequestScopeRuntime?.stats?.().generation ?? null;
      const navigationChanged = navigationGeneration != null
        && latestGeneration != null
        && latestGeneration !== navigationGeneration;
      const sameProject = String(projectId?.() || '') === String(pid);
      const s = state();
      if (destroyed || navigationChanged || !sameProject) {
        return {algorithms: s.algorithms || [], jobs: s.jobs || [], cached: false, stale: true};
      }

      s.algorithms = listFrom(algorithmBody);
      s.jobs = listFrom(jobBody);
      lastRefreshAt = Date.now();
      refreshError = '';
      if (render && String(s.page || '') === ALGORITHM_PAGE) renderPage();
      return {algorithms: s.algorithms, jobs: s.jobs, cached: false, stale: false};
    })();

    try {
      return await inflight;
    } catch (error) {
      refreshError = String(error?.message || error || '算法列表刷新失败');
      if (render && String(state().page || '') === ALGORITHM_PAGE) renderPage();
      throw error;
    } finally {
      inflight = null;
    }
  }

  const onRefreshCapture = event => {
    const target = event?.target?.closest?.('#refreshBtn');
    if (!target || String(state().page || '') !== ALGORITHM_PAGE) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (target.disabled || inflight) return;
    target.disabled = true;
    void refresh({render: true}).then(
      result => {
        if (!result?.stale) notify?.('算法列表已刷新');
      },
      error => notify?.(error?.message || error),
    ).finally(() => { target.disabled = false; });
  };

  window.toggleAlgorithm412 = toggle;
  window.toggleAlgorithm428 = toggle;
  doc?.addEventListener?.('click', onRefreshCapture, true);

  const runtime = {
    build: 'algorithm-list-runtime-422565',
    toggle,
    refresh,
    render: renderPage,
    renderCards: renderPage,
    renderRows,
    filterState,
    setFilters,
    matchesSearch,
    visibleAlgorithms,
    setExternalProvider,
    openCategoryPicker,
    cancelCategoryPicker,
    toggleDraftCategory,
    confirmCategoryPicker,
    resetFilters,
    state: runtimeState,
    openDetail(id) {
      window.viewAlgorithm429?.(String(id));
      const algorithm = (state().algorithms || []).find(row => String(row.id) === String(id));
      if (algorithm) queueMicrotask(() => externalProvider?.decorateDetail?.(algorithm));
    },
    publishVersion(algorithmId, versionId, button) {
      return window.ExternalAlgorithmPublishRuntime?.publishVersion?.(algorithmId, versionId, button);
    },
    destroy() {
      destroyed = true;
      cancelTrainingWarmup();
      renderedRows.clear();
      externalProvider = null;
      doc?.removeEventListener?.('click', onRefreshCapture, true);
      if (window.toggleAlgorithm412 === toggle) window.toggleAlgorithm412 = originalToggle412;
      if (window.toggleAlgorithm428 === toggle) window.toggleAlgorithm428 = originalToggle428;
      if (window.AlgorithmListRuntime === runtime) window.AlgorithmListRuntime = null;
      window.__algorithmListRuntimeInstalled = false;
    },
  };
  window.AlgorithmListRuntime = runtime;
  window.__algorithmListRuntimeInstalled = true;
  return runtime;
}
