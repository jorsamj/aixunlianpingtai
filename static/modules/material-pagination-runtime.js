export const FULL_MATERIAL_PAGES = new Set([
  // These legacy selectors still filter state.images (training V3 also pages
  // locally). Keep their complete pool only while visiting the relevant page.
  // Dataset batch actions already use server filters and frozen manifests.
  // main.mjs adds the untouched test/publish, deployment-test and iteration pages.
  '训练任务',
  '自动标注',
  '自动标注及清洗',
  '质量中心',
]);

export function requiresFullMaterialPool(page) {
  return FULL_MATERIAL_PAGES.has(String(page || ''));
}

export function buildMaterialQuery({
  limit = 48,
  cursor = '',
  query = '',
  sourceId = 'all',
  processingStatus = '',
  labels = [],
  annotated = 'all',
} = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(Math.max(1, Math.min(1000, Number(limit) || 48))));
  if (cursor) params.set('cursor', String(cursor));
  if (query) params.set('query', String(query));
  if (sourceId && sourceId !== 'all') params.append('storage_source_id', String(sourceId));
  if (processingStatus) params.set('processing_status', String(processingStatus));
  for (const label of labels || []) if (label) params.append('label', String(label));
  if (annotated === 'marked' || annotated === true) params.set('annotated', 'true');
  if (annotated === 'unmarked' || annotated === false) params.set('annotated', 'false');
  return params;
}

async function responseJson(response) {
  if (response.ok) return response.json();
  const text = await response.text();
  let body = {};
  try { body = JSON.parse(text); } catch (_error) { body = {detail: text}; }
  throw new Error(body.message || body.detail || `HTTP ${response.status}`);
}

function escHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

export function installMaterialPaginationRuntime() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return false;
  if (window.__materialPaginationRuntime61Installed) return true;
  if (!window.__materialPaging61?.installed || typeof state === 'undefined') return false;

  window.__materialPaginationRuntime61Installed = true;
  const transport = window.__materialPaging61;
  const materialFetch = typeof transport.originalFetch === 'function'
    ? transport.originalFetch
    : window.fetch.bind(window);
  const baseSetPage = window.setPage;
  const baseRenderDatasets = window.renderDatasets424;
  const baseRenderCards = window.renderData412Cards;
  let requestSerial = 0;
  let searchTimer = null;
  let suppressCardReload = false;
  let refreshBusy = false;

  state.materialQuery61 = state.materialQuery61 || '';
  state.materialAnnotated61 = state.materialAnnotated61 || 'all';
  state.materialPage61 = state.materialPage61 || {
    cursor: '', nextCursor: '', cursorStack: [], page: 1, total: 0,
    unprocessedTotal: 0, processedTotal: 0,
  };
  state.materialShellSignature61 = state.materialShellSignature61 || '';

  const projectId = () => String(state.project?.id || '');
  const isPagedDataset = () => state.page === '数据集' && transport.mode === 'paged';

  function filters61() {
    const tab = state.data412Tab || 'unprocessed';
    return {
      query: String(state.materialQuery61 || '').trim(),
      sourceId: String(state.materialSourceFilter61 || 'all'),
      processingStatus: tab === 'processed' ? 'processed' : 'unprocessed',
      labels: tab === 'processed' ? [...(state.data412Labels || new Set())] : [],
      annotated: tab === 'processed' ? (state.materialAnnotated61 || 'all') : 'all',
    };
  }

  function filterSignature61() {
    const f = filters61();
    return JSON.stringify([
      projectId(), state.data412Tab || 'unprocessed', f.query, f.sourceId,
      f.processingStatus, [...f.labels].sort(), f.annotated,
    ]);
  }

  function shellSignature61() {
    return JSON.stringify([
      state.data412Tab || 'unprocessed',
      Boolean(state.data412DeleteMode),
    ]);
  }

  function hasDatasetShell61() {
    return Boolean(
      isPagedDataset()
      && document.querySelector('.data426-shell')
      && document.getElementById('data412Grid')
      && document.getElementById('data412Pager')
    );
  }

  async function fetchMaterialPage61(cursor = '') {
    const pid = projectId();
    if (!pid) return {items: [], total: 0, next_cursor: null};
    const f = filters61();
    const params = buildMaterialQuery({...f, cursor, limit: transport.pageSize || 48});
    return responseJson(await materialFetch(`/api/v61/projects/${encodeURIComponent(pid)}/materials?${params}`, {
      headers: {Accept: 'application/json'},
      credentials: 'same-origin',
    }));
  }

  async function fetchStatusTotal61(processingStatus) {
    const pid = projectId();
    if (!pid) return 0;
    const params = buildMaterialQuery({
      limit: 1,
      sourceId: String(state.materialSourceFilter61 || 'all'),
      processingStatus,
    });
    const page = await responseJson(await materialFetch(`/api/v61/projects/${encodeURIComponent(pid)}/materials?${params}`, {
      headers: {Accept: 'application/json'},
      credentials: 'same-origin',
    }));
    return Number(page.total || 0);
  }

  async function refreshSummary61() {
    const pid = projectId();
    if (!pid || transport.mode !== 'paged') return;
    try {
      const totalParams = buildMaterialQuery({limit: 1});
      const annotatedParams = buildMaterialQuery({limit: 1, annotated: 'marked'});
      const [totalPage, annotatedPage] = await Promise.all([
        responseJson(await materialFetch(`/api/v61/projects/${encodeURIComponent(pid)}/materials?${totalParams}`, {headers: {Accept: 'application/json'}, credentials: 'same-origin'})),
        responseJson(await materialFetch(`/api/v61/projects/${encodeURIComponent(pid)}/materials?${annotatedParams}`, {headers: {Accept: 'application/json'}, credentials: 'same-origin'})),
      ]);
      if (transport.mode !== 'paged') return;
      state.materialSummary61 = {
        total: Number(totalPage.total || 0),
        annotated: Number(annotatedPage.total || 0),
      };
      decorateSummary61();
    } catch (_error) {
      // Summary enhancement must never block the page.
    }
  }

  function decorateSummary61() {
    if (transport.mode !== 'paged') return;
    const summary = state.materialSummary61;
    if (!summary) return;
    for (const stat of document.querySelectorAll('#summary .stat')) {
      const key = stat.querySelector('.k');
      const value = stat.querySelector('.v');
      if (!key || !value) continue;
      const text = key.textContent.trim();
      if (text === '图片 / 已标注' || text === '素材 / 已标注') {
        value.textContent = `${summary.total}/${summary.annotated}`;
      } else if (text === '标注框' || text === '当前页标注框') {
        key.textContent = '当前页标注框';
        value.textContent = String((state.images || []).reduce((sum, row) => sum + Number(row.box_count || 0), 0));
      }
    }
  }

  function restoreControls61() {
    const q = document.getElementById('data412Q');
    if (q) {
      q.value = state.materialQuery61 || '';
      q.oninput = () => {
        state.materialQuery61 = q.value || '';
        clearTimeout(searchTimer);
        searchTimer = setTimeout(() => loadMaterialPage61({reset: true}), 220);
      };
    }
    const ann = document.getElementById('data412Ann');
    if (ann) {
      ann.value = state.materialAnnotated61 || 'all';
      ann.onchange = () => {
        state.materialAnnotated61 = ann.value || 'all';
        loadMaterialPage61({reset: true});
      };
    }
    const source = document.getElementById('materialSource61');
    if (source) {
      source.value = state.materialSourceFilter61 || 'all';
      source.onchange = () => {
        state.materialSourceFilter61 = source.value || 'all';
        loadMaterialPage61({reset: true});
      };
    }
  }

  function decorateStorage61() {
    const storageApi = window.PlatformCore?.storage;
    const toolbar = document.querySelector('.data426-toolbar');
    if (toolbar && !document.getElementById('materialSource61')) {
      const enabled = storageApi?.enabledStorageSources?.(state.storageSources61 || []) || [];
      const selected = String(state.materialSourceFilter61 || 'all');
      toolbar.insertAdjacentHTML('afterbegin', `<select id="materialSource61" class="select storage61-filter"><option value="all">全部来源</option>${enabled.map(source => `<option value="${escHtml(source.id)}" ${String(source.id) === selected ? 'selected' : ''}>${escHtml(source.name)}</option>`).join('')}</select>`);
    }
    const sourceSelect = document.getElementById('materialSource61');
    if (sourceSelect) sourceSelect.value = String(state.materialSourceFilter61 || 'all');

    const cards = [...document.querySelectorAll('.data426-card')];
    cards.forEach((card, index) => {
      const row = (state.images || [])[index];
      const meta = card.querySelector('.data426-meta');
      if (!row || !meta || meta.querySelector('.storage61-badge')) return;
      const source = (state.storageSources61 || []).find(item => item.id === (row.storage_source_id || 'default_local'));
      const label = storageApi?.storageSourceLabel?.(source) || row.storage_type || '本地';
      meta.insertAdjacentHTML('beforeend', `<span class="storage61-badge">${escHtml(label)}</span>`);
    });
  }

  function syncLabelChipState61() {
    const selected = state.data412Labels || new Set();
    const clear = document.querySelector('.data426-chip.clear');
    if (clear) clear.classList.toggle('on', selected.size === 0);
  }

  function decorateDataset61() {
    const info = state.materialPage61;
    const tabs = [...document.querySelectorAll('.data424-tabs button')];
    if (tabs[0]?.querySelector('b')) tabs[0].querySelector('b').textContent = String(info.unprocessedTotal || 0);
    if (tabs[1]?.querySelector('b')) tabs[1].querySelector('b').textContent = String(info.processedTotal || 0);
    const count = document.getElementById('data412Count');
    if (count) count.textContent = `${info.total || 0} 张`;
    const selectedCount = document.getElementById('data412SelCount');
    if (selectedCount) selectedCount.textContent = `已选 ${(state.data412Selected || new Set()).size} 张`;
    const pager = document.getElementById('data412Pager');
    if (pager) {
      const pages = Math.max(1, Math.ceil(Number(info.total || 0) / Number(transport.pageSize || 48)));
      pager.innerHTML = `<button class="btn mini" ${info.page <= 1 ? 'disabled' : ''} onclick="materialPrev61()">上一页</button><span>${info.page} / ${pages}</span><button class="btn mini" ${!info.nextCursor ? 'disabled' : ''} onclick="materialNext61()">下一页</button>`;
    }
    decorateStorage61();
    restoreControls61();
    syncLabelChipState61();
    decorateSummary61();

    const buttons = [...document.querySelectorAll('.data426-head button')];
    const clean = buttons.find(button => button.textContent.trim() === '清洗当前素材');
    if (clean) clean.onclick = () => window.runMaterialBatch62?.('CLEAN');
    const ready = buttons.find(button => button.textContent.trim() === '当前素材无需清洗');
    if (ready) ready.onclick = () => window.runMaterialBatch62?.('MARK_CLEAN_SKIPPED');
  }

  function patchPagedDataset61() {
    if (!hasDatasetShell61() || typeof baseRenderCards !== 'function') return false;
    suppressCardReload = true;
    state.data412Page = 1;
    try { baseRenderCards(); } finally { suppressCardReload = false; }
    decorateDataset61();
    return true;
  }

  function renderPagedDataset61({forceShell = false} = {}) {
    if (!isPagedDataset() || typeof baseRenderDatasets !== 'function') return false;
    const structure = shellSignature61();
    const needsShell = forceShell || !hasDatasetShell61() || state.materialShellSignature61 !== structure;
    if (needsShell) {
      suppressCardReload = true;
      state.data412Page = 1;
      try { baseRenderDatasets(); } finally { suppressCardReload = false; }
      state.materialShellSignature61 = structure;
      decorateDataset61();
      return 'shell';
    }
    patchPagedDataset61();
    return 'patch';
  }

  async function loadMaterialPage61({reset = false, cursor = undefined, page = undefined} = {}) {
    if (!isPagedDataset()) return {stale: true};
    const serial = ++requestSerial;
    const info = state.materialPage61;
    if (reset) {
      info.cursor = '';
      info.nextCursor = '';
      info.cursorStack = [];
      info.page = 1;
    }
    const requestedCursor = cursor === undefined ? info.cursor : (cursor || '');
    const expectedPage = state.page;
    try {
      const [materialPage, unprocessedTotal, processedTotal] = await Promise.all([
        fetchMaterialPage61(requestedCursor),
        fetchStatusTotal61('unprocessed'),
        fetchStatusTotal61('processed'),
      ]);
      if (serial !== requestSerial || state.page !== expectedPage || !isPagedDataset()) return {stale: true};
      state.images = Array.isArray(materialPage.items) ? materialPage.items : [];
      info.cursor = requestedCursor;
      info.nextCursor = materialPage.next_cursor || '';
      info.total = Number(materialPage.total || 0);
      info.unprocessedTotal = unprocessedTotal;
      info.processedTotal = processedTotal;
      if (page !== undefined) info.page = Math.max(1, Number(page) || 1);
      transport.lastPage = materialPage;
      state.materialFilterSignature61 = filterSignature61();
      const mode = renderPagedDataset61();
      return {stale: false, mode, items: state.images, total: info.total};
    } catch (error) {
      if (serial === requestSerial && isPagedDataset()) window.toast?.(error.message || String(error));
      return {stale: serial !== requestSerial, error};
    }
  }

  async function focusedRefresh61() {
    if (!isPagedDataset()) return false;
    const info = state.materialPage61;
    await Promise.all([
      loadMaterialPage61({cursor: info.cursor || '', page: info.page || 1}),
      refreshSummary61(),
    ]);
    return true;
  }

  window.materialNext61 = async () => {
    const info = state.materialPage61;
    if (!info.nextCursor) return;
    info.cursorStack.push(info.cursor || '');
    await loadMaterialPage61({cursor: info.nextCursor, page: info.page + 1});
  };

  window.materialPrev61 = async () => {
    const info = state.materialPage61;
    if (info.page <= 1) return;
    const previous = info.cursorStack.pop() || '';
    await loadMaterialPage61({cursor: previous, page: info.page - 1});
  };

  window.materialFilteredIds61 = async () => {
    const pid = projectId();
    if (!pid) return [];
    const f = filters61();
    const ids = [];
    let cursor = '';
    do {
      const params = buildMaterialQuery({...f, cursor, limit: 1000});
      const page = await responseJson(await materialFetch(`/api/v61/projects/${encodeURIComponent(pid)}/materials/ids?${params}`, {headers: {Accept: 'application/json'}, credentials: 'same-origin'}));
      ids.push(...(page.items || []).map(String));
      cursor = page.next_cursor || '';
    } while (cursor);
    return ids;
  };

  const baseTab = window.setData412Tab;
  window.setData412Tab = function setPagedMaterialTab(tab) {
    if (!isPagedDataset()) return baseTab?.(tab);
    state.data412Tab = tab;
    state.data412Labels?.clear?.();
    state.data412Selected?.clear?.();
    state.data412DeleteMode = false;
    state.data412Page = 1;
    state.materialAnnotated61 = 'all';
    state.materialShellSignature61 = '';
    renderPagedDataset61({forceShell: true});
    void loadMaterialPage61({reset: true});
  };

  const baseToggleLabel = window.toggleLabel412;
  window.toggleLabel412 = function togglePagedMaterialLabel(label) {
    if (!isPagedDataset()) return baseToggleLabel?.(label);
    if (state.data412Labels.has(label)) state.data412Labels.delete(label);
    else state.data412Labels.add(label);
    const active = document.activeElement;
    if (active?.classList?.contains('data426-chip') && !active.classList.contains('clear')) {
      active.classList.toggle('on', state.data412Labels.has(label));
    }
    syncLabelChipState61();
    void loadMaterialPage61({reset: true});
  };

  const baseClearLabels = window.clearLabels412;
  window.clearLabels412 = function clearPagedMaterialLabels() {
    if (!isPagedDataset()) return baseClearLabels?.();
    state.data412Labels.clear();
    document.querySelectorAll('.data426-chip').forEach(button => button.classList.toggle('on', button.classList.contains('clear')));
    void loadMaterialPage61({reset: true});
  };

  window.materialBatchFilters61 = () => {
    const value = filters61();
    return {
      query: value.query,
      storage_source_ids: value.sourceId && value.sourceId !== 'all' ? [value.sourceId] : [],
      processing_status: value.processingStatus,
      labels: [...value.labels],
      annotated: value.annotated === 'marked' ? true : value.annotated === 'unmarked' ? false : null,
    };
  };
  window.materialCurrentPageIds61 = () => (state.images || []).map(row => String(row.id));
  window.materialSelectedIds61 = () => [...(state.data412Selected || new Set())].map(String);
  window.reloadMaterialPage61 = () => loadMaterialPage61({reset: true});

  const baseMarkReady = window.markReady412;
  window.markReady412 = async function markReadyAndRefreshPagedMaterials(imageIds) {
    const result = await baseMarkReady?.(imageIds);
    if (isPagedDataset()) await loadMaterialPage61({reset: true});
    return result;
  };

  const baseBatchDelete = window.batchDelete412;
  window.batchDelete412 = async function durablePagedDelete() {
    if (!isPagedDataset()) return baseBatchDelete?.();
    if (!(state.data412Selected?.size)) return window.toast?.('请选择要删除的素材');
    return window.runMaterialBatch62?.('DELETE_INDEX', {scope: 'SELECTED'});
  };

  window.renderData412Cards = function pagedMaterialCards() {
    if (!isPagedDataset() || suppressCardReload) return baseRenderCards?.();
    const q = document.getElementById('data412Q');
    const ann = document.getElementById('data412Ann');
    const nextQuery = q?.value || state.materialQuery61 || '';
    const nextAnn = ann?.value || state.materialAnnotated61 || 'all';
    const changed = nextQuery !== state.materialQuery61 || nextAnn !== state.materialAnnotated61;
    state.materialQuery61 = nextQuery;
    state.materialAnnotated61 = nextAnn;
    state.data412Page = 1;
    if (changed) {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadMaterialPage61({reset: true}), 220);
      return;
    }
    patchPagedDataset61();
  };

  window.renderDatasets424 = function serverPagedDatasets() {
    if (!isPagedDataset()) return baseRenderDatasets?.();
    const signature = filterSignature61();
    const needsLoad = !hasDatasetShell61() || signature !== state.materialFilterSignature61;
    const mode = renderPagedDataset61();
    if (needsLoad) void loadMaterialPage61({reset: true});
    return mode;
  };

  if (typeof baseSetPage === 'function') {
    window.setPage = function materialAwareSetPage(page) {
      const target = page === '自动标注' ? '自动标注及清洗' : String(page || '');
      const full = requiresFullMaterialPool(target);
      transport.mode = full ? 'full' : 'paged';
      if (target === '数据集') {
        state.materialFilterSignature61 = '';
        state.materialShellSignature61 = '';
      }
      const result = baseSetPage(page);
      if (full) {
        setTimeout(async () => {
          try {
            if (state.page !== target) return;
            await window.refreshCurrentPage413?.();
            if (state.page !== target || target === '训练任务') return;
            if (typeof window.render === 'function') window.render();
            else if (typeof render === 'function') render();
          } catch (error) {
            window.toast?.(error.message || String(error));
          }
        }, 0);
      } else if (target !== '数据集') {
        setTimeout(refreshSummary61, 0);
      }
      return result;
    };
  }

  const onRefreshCapture = event => {
    const button = event?.target?.closest?.('#refreshBtn');
    if (!button || !isPagedDataset()) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    if (button.disabled || refreshBusy) return;
    refreshBusy = true;
    button.disabled = true;
    void focusedRefresh61().then(
      () => window.toast?.('素材已刷新'),
      error => window.toast?.(error?.message || error),
    ).finally(() => {
      refreshBusy = false;
      if (button?.isConnected !== false) button.disabled = false;
    });
  };
  document.addEventListener('click', onRefreshCapture, true);

  const runtime = {
    build: 'material-pagination-runtime-422205',
    load: loadMaterialPage61,
    refresh: focusedRefresh61,
    patch: patchPagedDataset61,
    render: renderPagedDataset61,
    state() {
      return {
        requestSerial,
        refreshBusy,
        filterSignature: state.materialFilterSignature61 || '',
        shellSignature: state.materialShellSignature61 || '',
      };
    },
  };
  window.MaterialPaginationRuntime61 = runtime;

  setTimeout(() => {
    refreshSummary61();
    if (state.page !== '数据集') return;
    const signature = filterSignature61();
    const needsBootstrap = !hasDatasetShell61() || signature !== state.materialFilterSignature61;
    if (needsBootstrap) loadMaterialPage61({reset: true});
  }, 250);
  setTimeout(refreshSummary61, 1200);
  return true;
}