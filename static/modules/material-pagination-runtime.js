export const FULL_MATERIAL_PAGES = new Set([
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

export function installMaterialPaginationRuntime() {
  if (typeof window === 'undefined' || typeof document === 'undefined') return false;
  if (window.__materialPaginationRuntime61Installed) return true;
  if (!window.__materialPaging61?.installed || typeof state === 'undefined') return false;

  window.__materialPaginationRuntime61Installed = true;
  const transport = window.__materialPaging61;
  const baseSetPage = window.setPage;
  const baseRenderDatasets = window.renderDatasets424;
  const baseRenderCards = window.renderData412Cards;
  let requestSerial = 0;
  let searchTimer = null;
  let suppressCardReload = false;

  state.materialQuery61 = state.materialQuery61 || '';
  state.materialAnnotated61 = state.materialAnnotated61 || 'all';
  state.materialPage61 = state.materialPage61 || {
    cursor: '', nextCursor: '', cursorStack: [], page: 1, total: 0,
    unprocessedTotal: 0, processedTotal: 0,
  };

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

  async function fetchMaterialPage61(cursor = '') {
    const pid = projectId();
    if (!pid) return {items: [], total: 0, next_cursor: null};
    const f = filters61();
    const params = buildMaterialQuery({...f, cursor, limit: transport.pageSize || 48});
    return responseJson(await fetch(`/api/v61/projects/${encodeURIComponent(pid)}/materials?${params}`));
  }

  async function fetchStatusTotal61(processingStatus) {
    const pid = projectId();
    if (!pid) return 0;
    const params = buildMaterialQuery({
      limit: 1,
      sourceId: String(state.materialSourceFilter61 || 'all'),
      processingStatus,
    });
    const page = await responseJson(await fetch(`/api/v61/projects/${encodeURIComponent(pid)}/materials?${params}`));
    return Number(page.total || 0);
  }

  async function refreshSummary61() {
    const pid = projectId();
    if (!pid || transport.mode !== 'paged') return;
    try {
      const totalParams = buildMaterialQuery({limit: 1});
      const annotatedParams = buildMaterialQuery({limit: 1, annotated: 'marked'});
      const [totalPage, annotatedPage] = await Promise.all([
        responseJson(await fetch(`/api/v61/projects/${encodeURIComponent(pid)}/materials?${totalParams}`)),
        responseJson(await fetch(`/api/v61/projects/${encodeURIComponent(pid)}/materials?${annotatedParams}`)),
      ]);
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

  function decorateDataset61() {
    const info = state.materialPage61;
    const tabs = [...document.querySelectorAll('.data424-tabs button')];
    if (tabs[0]?.querySelector('b')) tabs[0].querySelector('b').textContent = String(info.unprocessedTotal || 0);
    if (tabs[1]?.querySelector('b')) tabs[1].querySelector('b').textContent = String(info.processedTotal || 0);
    const count = document.getElementById('data412Count');
    if (count) count.textContent = `${info.total || 0} 张`;
    const pager = document.getElementById('data412Pager');
    if (pager) {
      const pages = Math.max(1, Math.ceil(Number(info.total || 0) / Number(transport.pageSize || 48)));
      pager.innerHTML = `<button class="btn mini" ${info.page <= 1 ? 'disabled' : ''} onclick="materialPrev61()">上一页</button><span>${info.page} / ${pages}</span><button class="btn mini" ${!info.nextCursor ? 'disabled' : ''} onclick="materialNext61()">下一页</button>`;
    }
    restoreControls61();
    decorateSummary61();

    const buttons = [...document.querySelectorAll('.data426-head button')];
    const clean = buttons.find(button => button.textContent.trim() === '清洗当前素材');
    if (clean) clean.onclick = async () => window.createClean427?.({image_ids: await window.materialFilteredIds61()});
    const ready = buttons.find(button => button.textContent.trim() === '当前素材无需清洗');
    if (ready) ready.onclick = async () => window.markReady412?.(await window.materialFilteredIds61());
  }

  function renderPagedDataset61() {
    if (!isPagedDataset() || typeof baseRenderDatasets !== 'function') return;
    suppressCardReload = true;
    state.data412Page = 1;
    try { baseRenderDatasets(); } finally { suppressCardReload = false; }
    decorateDataset61();
  }

  async function loadMaterialPage61({reset = false, cursor = undefined, page = undefined} = {}) {
    if (!isPagedDataset()) return;
    const serial = ++requestSerial;
    const info = state.materialPage61;
    if (reset) {
      info.cursor = '';
      info.nextCursor = '';
      info.cursorStack = [];
      info.page = 1;
    }
    const requestedCursor = cursor === undefined ? info.cursor : (cursor || '');
    try {
      const [materialPage, unprocessedTotal, processedTotal] = await Promise.all([
        fetchMaterialPage61(requestedCursor),
        fetchStatusTotal61('unprocessed'),
        fetchStatusTotal61('processed'),
      ]);
      if (serial !== requestSerial || !isPagedDataset()) return;
      state.images = Array.isArray(materialPage.items) ? materialPage.items : [];
      info.cursor = requestedCursor;
      info.nextCursor = materialPage.next_cursor || '';
      info.total = Number(materialPage.total || 0);
      info.unprocessedTotal = unprocessedTotal;
      info.processedTotal = processedTotal;
      if (page !== undefined) info.page = Math.max(1, Number(page) || 1);
      transport.lastPage = materialPage;
      state.materialFilterSignature61 = filterSignature61();
      renderPagedDataset61();
    } catch (error) {
      window.toast?.(error.message || String(error));
    }
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
      const page = await responseJson(await fetch(`/api/v61/projects/${encodeURIComponent(pid)}/materials/ids?${params}`));
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
    loadMaterialPage61({reset: true});
  };

  const baseToggleLabel = window.toggleLabel412;
  window.toggleLabel412 = function togglePagedMaterialLabel(label) {
    if (!isPagedDataset()) return baseToggleLabel?.(label);
    if (state.data412Labels.has(label)) state.data412Labels.delete(label);
    else state.data412Labels.add(label);
    loadMaterialPage61({reset: true});
  };

  const baseClearLabels = window.clearLabels412;
  window.clearLabels412 = function clearPagedMaterialLabels() {
    if (!isPagedDataset()) return baseClearLabels?.();
    state.data412Labels.clear();
    loadMaterialPage61({reset: true});
  };

  const baseMarkReady = window.markReady412;
  window.markReady412 = async function markReadyAndRefreshPagedMaterials(imageIds) {
    const result = await baseMarkReady?.(imageIds);
    if (isPagedDataset()) await loadMaterialPage61({reset: true});
    return result;
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
    baseRenderCards?.();
    decorateDataset61();
    if (changed) {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(() => loadMaterialPage61({reset: true}), 220);
    }
  };

  window.renderDatasets424 = function serverPagedDatasets() {
    if (!isPagedDataset()) return baseRenderDatasets?.();
    const signature = filterSignature61();
    if (signature !== state.materialFilterSignature61) {
      loadMaterialPage61({reset: true});
      return renderPagedDataset61();
    }
    return renderPagedDataset61();
  };

  if (typeof baseSetPage === 'function') {
    window.setPage = function materialAwareSetPage(page) {
      const target = page === '自动标注' ? '自动标注及清洗' : String(page || '');
      const full = requiresFullMaterialPool(target);
      transport.mode = full ? 'full' : 'paged';
      const result = baseSetPage(page);
      if (target === '数据集') {
        setTimeout(() => loadMaterialPage61({reset: true}), 0);
      } else if (full) {
        setTimeout(async () => {
          try {
            if (typeof window.loadRelated === 'function') await window.loadRelated();
            else if (typeof loadRelated === 'function') await loadRelated();
            if (typeof window.render === 'function') window.render();
            else if (typeof render === 'function') render();
          } catch (error) {
            window.toast?.(error.message || String(error));
          }
        }, 0);
      } else {
        setTimeout(refreshSummary61, 0);
      }
      return result;
    };
  }

  setTimeout(() => {
    refreshSummary61();
    if (state.page === '数据集') loadMaterialPage61({reset: true});
  }, 250);
  setTimeout(refreshSummary61, 1200);
  return true;
}
