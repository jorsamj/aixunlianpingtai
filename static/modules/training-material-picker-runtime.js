const DEFAULT_PAGE_SIZE = 60;
const CACHE_LIMIT = 12;
const THUMBNAIL_EAGER_COUNT = 15;
const THUMBNAIL_PRELOAD_MARGIN = 120;
const IMAGE_PLACEHOLDER = 'data:image/gif;base64,R0lGODlhAQABAAD/ACwAAAAAAQABAAACADs=';

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, character => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[character]);
}

function uniqueIds(values) {
  return [...new Set((values || []).map(value => String(value || '').trim()).filter(Boolean))];
}

function responseMessage(body, fallback) {
  if (typeof body?.detail === 'string') return body.detail;
  if (typeof body?.detail?.message === 'string') return body.detail.message;
  return fallback;
}

async function readJson(response, fallback) {
  let body = null;
  try { body = await response.json(); } catch (_error) {}
  if (!response.ok) throw new Error(responseMessage(body, fallback));
  return body || {};
}

export function trainingMaterialSelectionPatch({role = 'train', selectedIds = [], materialIds = [], testMaterialIds = []} = {}) {
  const selected = uniqueIds(selectedIds);
  const selectedSet = new Set(selected);
  return role === 'test'
    ? {
      materialIds: uniqueIds(materialIds).filter(id => !selectedSet.has(id)),
      testMaterialIds: selected,
    }
    : {
      materialIds: selected,
      testMaterialIds: uniqueIds(testMaterialIds).filter(id => !selectedSet.has(id)),
    };
}

export function buildTrainingMaterialQuery({cursor = null, pageSize = DEFAULT_PAGE_SIZE, query = '', labels = []} = {}) {
  const params = new URLSearchParams();
  params.set('limit', String(pageSize));
  if (cursor) params.set('cursor', String(cursor));
  if (String(query || '').trim()) params.set('query', String(query).trim());
  uniqueIds(labels).forEach(label => params.append('label', label));
  return params.toString();
}

function annotationColor(label) {
  const palette = ['#ef4444', '#2563eb', '#16a34a', '#9333ea', '#ea580c', '#0891b2', '#db2777', '#65a30d'];
  const text = String(label || '目标');
  let hash = 0;
  for (let index = 0; index < text.length; index += 1) hash = ((hash << 5) - hash + text.charCodeAt(index)) | 0;
  return palette[Math.abs(hash) % palette.length];
}

function finiteCoordinate(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : 0;
}

export function renderTrainingMaterialPreview(row = {}, {loading = 'lazy', priority = 'low'} = {}) {
  const width = Math.max(1, finiteCoordinate(row.width));
  const height = Math.max(1, finiteCoordinate(row.height));
  const state = ['annotated', 'confirmed_empty'].includes(String(row.annotation_state || ''))
    ? String(row.annotation_state)
    : 'unannotated';
  const boxes = state === 'annotated' && Array.isArray(row.boxes) ? row.boxes : [];
  const shapes = boxes.map(box => {
    const x1 = finiteCoordinate(box.x1), y1 = finiteCoordinate(box.y1);
    const x2 = finiteCoordinate(box.x2), y2 = finiteCoordinate(box.y2);
    if (x2 <= x1 || y2 <= y1) return '';
    const label = String(box.label || box.code || '目标');
    const color = annotationColor(label);
    const textY = Math.max(12, y1 + 14);
    return `<g><rect data-label="${esc(label)}" x="${x1}" y="${y1}" width="${x2 - x1}" height="${y2 - y1}" fill="none" stroke="${color}" stroke-width="2" vector-effect="non-scaling-stroke"><title>${esc(label)}</title></rect><text x="${x1 + 3}" y="${textY}" fill="${color}" font-size="12" font-weight="700">${esc(label)}</text></g>`;
  }).join('');
  const overlay = shapes
    ? `<svg class="train-v3-box-layer" viewBox="0 0 ${width} ${height}" preserveAspectRatio="xMidYMid meet" aria-hidden="true">${shapes}</svg>`
    : '';
  const status = state === 'annotated'
    ? `已标注 · ${boxes.length} 框`
    : state === 'confirmed_empty' ? '已确认无目标' : '未标注';
  const thumbnail = row.thumbnail_url || row.content_url || '';
  return `<div class="train-v3-preview" data-annotation-state="${state}"><img src="${IMAGE_PLACEHOLDER}" data-src="${esc(thumbnail)}" data-fallback="${esc(row.content_url || '')}" loading="${loading}" decoding="async" fetchpriority="${priority}" alt="">${overlay}<span class="train-v3-annotation-state ${state}" data-annotation-state="${state}">${status}</span></div>`;
}

export function installTrainingMaterialPickerRuntime({
  getState,
  projectId,
  trainingDraftRuntime,
  notify = () => {},
  fetchImpl = (...args) => fetch(...args),
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingMaterialPickerRuntimeInstalled) return window.TrainingMaterialPickerRuntime;
  if (typeof getState !== 'function' || typeof projectId !== 'function' || !trainingDraftRuntime) {
    throw new Error('TrainingMaterialPickerRuntime missing dependencies');
  }

  const state = () => getState() || {};
  let picker = null;
  let requestSequence = 0;
  let searchTimer = null;
  let activeController = null;
  let imageScrollFrame = null;
  const pageCache = new Map();

  function injectStyles() {
    if (document.getElementById('training-material-picker-runtime-style')) return;
    const style = document.createElement('style');
    style.id = 'training-material-picker-runtime-style';
    style.textContent = `
      .train-v3-picker.server-paged{min-height:64vh}
      .train-v3-picker.server-paged .train-v3-grid{display:grid!important;grid-template-columns:repeat(5,minmax(0,1fr))!important;grid-auto-rows:minmax(210px,max-content);align-items:start;gap:12px;height:clamp(420px,60vh,620px);max-height:none!important;min-height:0;align-content:start;padding:4px 2px 10px;overflow-y:auto!important;overflow-x:hidden!important;overscroll-behavior:contain}
      .train-v3-picker.server-paged .train-v3-card{position:relative;display:flex!important;flex-direction:column;align-self:start;min-width:0;min-height:210px;height:auto!important;padding:8px;border:1px solid #e3e8f0;border-radius:14px;background:#fff;box-shadow:0 2px 8px rgba(15,23,42,.04);overflow:hidden;transition:border-color .16s ease,box-shadow .16s ease,transform .16s ease}
      .train-v3-picker.server-paged .train-v3-card:hover{border-color:#bcc9da;box-shadow:0 8px 20px rgba(15,23,42,.08);transform:translateY(-1px)}
      .train-v3-picker.server-paged .train-v3-card.on{border-color:#4f7cff;box-shadow:0 0 0 2px rgba(79,124,255,.12),0 8px 20px rgba(15,23,42,.08)}
      .train-v3-picker.server-paged .train-v3-card>input[type="checkbox"]{position:absolute;top:14px;right:14px;z-index:3;width:18px;height:18px;margin:0;accent-color:#2563eb;box-shadow:0 1px 4px rgba(15,23,42,.22)}
      .train-v3-picker.server-paged .train-v3-preview{position:relative;width:100%;aspect-ratio:4/3;flex:none;background:#eef2f7;border-radius:9px;overflow:hidden}
      .train-v3-picker.server-paged .train-v3-card img{position:absolute;inset:0;display:block!important;width:100%!important;height:100%!important;min-height:0;aspect-ratio:4/3!important;background:#eef2f7;object-fit:contain;border-radius:9px}
      .train-v3-picker.server-paged .train-v3-box-layer{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible}
      .train-v3-picker.server-paged .train-v3-box-layer text{paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}
      .train-v3-picker.server-paged .train-v3-annotation-state{position:absolute;left:6px;bottom:6px;display:block;min-height:0;padding:2px 6px;border-radius:6px;background:rgba(15,23,42,.78);color:#fff;font-size:10px;line-height:16px;z-index:2}
      .train-v3-picker.server-paged .train-v3-annotation-state.confirmed_empty{background:rgba(22,163,74,.88)}
      .train-v3-picker.server-paged .train-v3-annotation-state.unannotated{background:rgba(100,116,139,.88)}
      .train-v3-picker.server-paged .train-v3-card b{display:block;margin-top:8px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px;line-height:20px;color:#172033}
      .train-v3-picker.server-paged .train-v3-card span{display:block;min-height:18px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:11px;line-height:18px;color:#64748b}
      .train-v3-picker.server-paged .train-v3-card.blocked{opacity:.5;cursor:not-allowed}
      .train-v3-picker.server-paged .train-v3-card.blocked:after{content:'已用于另一素材集';position:absolute;left:14px;top:14px;padding:3px 7px;border-radius:7px;background:rgba(15,23,42,.82);color:#fff;font-size:10px;z-index:2}
      .train-v3-picker.server-paged .train-v3-skeleton{height:210px;border:1px solid #e5eaf2;border-radius:14px;background:linear-gradient(100deg,#f1f5f9 20%,#f8fafc 45%,#f1f5f9 70%);background-size:220% 100%;animation:trainPickerShimmer 1.1s linear infinite}
      .train-v3-picker.server-paged .train-v3-page-meta{color:#64748b;font-size:11px}
      .train-v3-picker.server-paged .train-v3-loading{pointer-events:none;opacity:.65}
      @keyframes trainPickerShimmer{to{background-position:-220% 0}}
      @media(max-width:1180px){.train-v3-picker.server-paged .train-v3-grid{grid-template-columns:repeat(4,minmax(0,1fr))!important}}
      @media(max-width:900px){.train-v3-picker.server-paged .train-v3-grid{grid-template-columns:repeat(3,minmax(0,1fr))!important}}
      @media(max-width:620px){.train-v3-picker.server-paged .train-v3-grid{grid-template-columns:repeat(2,minmax(0,1fr))!important;gap:9px;height:clamp(360px,56vh,520px)}.train-v3-picker.server-paged .train-v3-card{padding:6px;min-height:190px}}
    `;
    document.head.appendChild(style);
  }

  function draft() {
    return trainingDraftRuntime.current?.() || state().trainingDraft || {};
  }

  function blockedIds(role) {
    const current = draft();
    if (String(current.splitMode || '') !== 'independent_test_set') return new Set();
    const values = role === 'train' ? current.testMaterialIds : current.materialIds;
    return new Set(uniqueIds(values));
  }

  function labelDisplay(code) {
    const row = (state().labels || []).find(item => String(item?.code || '') === String(code));
    return String(row?.display_name || row?.name || code || '');
  }

  function signature() {
    return JSON.stringify({
      project: projectId(),
      query: picker?.query || '',
      labels: picker ? [...picker.labels].sort() : [],
      pageSize: picker?.pageSize || DEFAULT_PAGE_SIZE,
    });
  }

  function cacheKey(cursor) {
    return `${signature()}::${cursor || ''}`;
  }

  function remember(key, value) {
    if (pageCache.has(key)) pageCache.delete(key);
    pageCache.set(key, value);
    while (pageCache.size > CACHE_LIMIT) pageCache.delete(pageCache.keys().next().value);
  }

  function modalHtml(role) {
    const title = role === 'train' ? '训练候选素材' : '独立试验素材';
    const chips = (state().labels || []).map(row => (
      `<button class="data426-chip" data-label="${esc(row.code)}" onclick="toggleTrainMaterialLabelV3('${esc(row.code)}')">${esc(row.display_name || row.code)}</button>`
    )).join('');
    return `<div class="train-v3-picker server-paged">
      <header><div><b>${title}</b><span>服务端分页 · 滚动后按需加载更多缩略图 · 批量选择由服务器解析</span></div><strong id="trV3PickerCount">正在读取素材…</strong></header>
      <div class="train-v3-filter"><input id="trV3Q" class="input" placeholder="搜索图片名称" oninput="trainMaterialSearchV3(this.value)"><div id="trV3Chips" class="data426-chips"><button class="data426-chip clear on" data-label="" onclick="clearTrainMaterialLabelsV3()">全部标签</button>${chips}</div></div>
      <div class="picker412-actions train-v3-batch"><button class="btn mini" data-picker-action="select-filtered" onclick="trainMaterialSelectV3('select-filtered')">全选当前筛选</button><button class="btn mini" data-picker-action="invert-filtered" onclick="trainMaterialSelectV3('invert-filtered')">反选当前筛选</button><button class="btn mini" data-picker-action="select-all" onclick="trainMaterialSelectV3('select-all')">全选全部可用素材</button><button class="btn mini" onclick="trainMaterialSelectV3('clear-all')">全部不选</button><span id="trV3PageMeta" class="train-v3-page-meta"></span></div>
      <div id="trV3Grid" class="train-v3-grid"></div>
      <div id="trV3Pager" class="data426-pager"></div>
      <div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" onclick="confirmTrainMaterialPickerV3()">确认选择</button></div>
    </div>`;
  }

  function cancelViewportFrame() {
    if (imageScrollFrame != null && typeof window.cancelAnimationFrame === 'function') {
      window.cancelAnimationFrame(imageScrollFrame);
    }
    imageScrollFrame = null;
  }

  function loadThumbnail(image) {
    if (!image || image.dataset.thumbnailLoaded === '1') return;
    const source = image.dataset.src;
    if (!source) return;
    image.dataset.thumbnailLoaded = '1';
    image.src = source;
  }

  function loadVisibleThumbnailWindow() {
    imageScrollFrame = null;
    const grid = document.getElementById('trV3Grid');
    if (!grid) return;
    const rootRect = grid.getBoundingClientRect();
    const top = rootRect.top - THUMBNAIL_PRELOAD_MARGIN;
    const bottom = rootRect.bottom + THUMBNAIL_PRELOAD_MARGIN;
    document.querySelectorAll('#trV3Grid img[data-src]').forEach(image => {
      if (image.dataset.thumbnailLoaded === '1') return;
      const card = image.closest('.train-v3-card');
      const rect = (card || image).getBoundingClientRect();
      if (rect.bottom >= top && rect.top <= bottom) loadThumbnail(image);
    });
  }

  function scheduleVisibleThumbnailWindow() {
    if (imageScrollFrame != null) return;
    if (typeof window.requestAnimationFrame !== 'function') {
      loadVisibleThumbnailWindow();
      return;
    }
    imageScrollFrame = window.requestAnimationFrame(loadVisibleThumbnailWindow);
  }

  function attachViewportImages() {
    cancelViewportFrame();
    const grid = document.getElementById('trV3Grid');
    const images = [...document.querySelectorAll('#trV3Grid img[data-src]')];
    if (!grid || !images.length) return;
    // First paint is deliberately capped. Do not run a geometry scan during
    // modal opening: legacy page CSS can report every grid card as visible in
    // the first layout pass and would immediately request the whole page.
    images.slice(0, THUMBNAIL_EAGER_COUNT).forEach(loadThumbnail);
    if (!grid.dataset.thumbnailScrollBound) {
      grid.dataset.thumbnailScrollBound = 'true';
      grid.addEventListener('scroll', scheduleVisibleThumbnailWindow, {passive: true});
    }
  }

  function renderSkeleton() {
    cancelViewportFrame();
    const grid = document.getElementById('trV3Grid');
    if (!grid) return;
    grid.innerHTML = Array.from({length: 15}, () => '<div class="train-v3-skeleton" aria-hidden="true"></div>').join('');
  }

  function updateCounts() {
    if (!picker) return;
    const count = document.getElementById('trV3PickerCount');
    if (count) count.textContent = `筛选结果 ${picker.total} 张 · 已选 ${picker.selected.size} 张`;
    const meta = document.getElementById('trV3PageMeta');
    if (meta) meta.textContent = `当前页 ${picker.items.length} 张 · 每页最多 ${picker.pageSize} 张`;
  }

  function attachImageFallbacks() {
    document.querySelectorAll('#trV3Grid img[data-fallback]').forEach(image => {
      image.addEventListener('error', () => {
        const fallback = image.dataset.fallback;
        if (!fallback || image.dataset.fallbackUsed === '1') return;
        image.dataset.fallbackUsed = '1';
        image.dataset.thumbnailLoaded = '1';
        image.src = fallback;
      }, {once: true});
    });
    attachViewportImages();
  }

  function renderPage() {
    if (!picker) return;
    const grid = document.getElementById('trV3Grid');
    if (!grid) return;
    cancelViewportFrame();
    grid.scrollTop = 0;
    const blocked = blockedIds(picker.role);
    grid.innerHTML = picker.items.map((row, index) => {
      const id = String(row.id || '');
      const selected = picker.selected.has(id);
      const unavailable = blocked.has(id) || String(row.annotation_state || '') === 'unannotated';
      const labelText = (row.labels || []).map(labelDisplay).filter(Boolean).join('、') || '无标签';
      const loading = index < THUMBNAIL_EAGER_COUNT ? 'eager' : 'lazy';
      const priority = index < THUMBNAIL_EAGER_COUNT ? 'high' : 'low';
      return `<label class="train-v3-card ${selected ? 'on' : ''} ${unavailable ? 'blocked' : ''}" data-material-id="${esc(id)}">
        <input type="checkbox" ${selected ? 'checked' : ''} ${unavailable ? 'disabled' : ''} onchange="toggleTrainMaterialV3('${esc(id)}',this.checked,this)">
        ${renderTrainingMaterialPreview(row, {loading, priority})}
        <b title="${esc(row.filename || '')}">${esc(row.filename || id)}</b><span title="${esc(labelText)}">${esc(labelText)}</span>
      </label>`;
    }).join('') || '<div class="empty">没有符合筛选条件的可训练图片</div>';
    updateCounts();
    const pager = document.getElementById('trV3Pager');
    if (pager) pager.innerHTML = `<button class="btn mini" ${picker.pageIndex <= 0 ? 'disabled' : ''} onclick="trainMaterialPageV3(-1)">上一页</button><span>第 ${picker.pageIndex + 1} 页</span><button class="btn mini" ${picker.nextCursor ? '' : 'disabled'} onclick="trainMaterialPageV3(1)">下一页</button>`;
    attachImageFallbacks();
  }

  async function loadPage({reset = false} = {}) {
    if (!picker) return;
    if (reset) {
      picker.pageIndex = 0;
      picker.cursors = [null];
      picker.nextCursor = null;
    }
    const cursor = picker.cursors[picker.pageIndex] || null;
    const key = cacheKey(cursor);
    const cached = pageCache.get(key);
    if (cached) {
      picker.items = cached.items;
      picker.total = cached.total;
      picker.nextCursor = cached.next_cursor || null;
      picker.repositoryRevision = cached.repository_revision ?? null;
      renderPage();
      return;
    }

    const sequence = ++requestSequence;
    activeController?.abort?.();
    activeController = new AbortController();
    picker.loading = true;
    renderSkeleton();
    updateCounts();
    try {
      const pid = projectId();
      if (!pid) throw new Error('当前项目不存在');
      const query = buildTrainingMaterialQuery({
        cursor,
        pageSize: picker.pageSize,
        query: picker.query,
        labels: [...picker.labels],
      });
      const response = await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-materials?${query}`, {
        signal: activeController.signal,
        headers: {'Accept': 'application/json'},
      });
      const body = await readJson(response, '训练素材读取失败，请重试');
      if (!picker || sequence !== requestSequence) return;
      picker.items = Array.isArray(body.items) ? body.items : [];
      picker.total = Math.max(0, Number(body.total || 0));
      picker.nextCursor = body.next_cursor || null;
      picker.repositoryRevision = body.repository_revision ?? null;
      remember(key, body);
      renderPage();
    } catch (error) {
      if (error?.name === 'AbortError') return;
      if (sequence !== requestSequence) return;
      const grid = document.getElementById('trV3Grid');
      if (grid) grid.innerHTML = `<div class="empty">${esc(error?.message || '训练素材读取失败')}</div>`;
      notify(error?.message || '训练素材读取失败');
    } finally {
      if (picker && sequence === requestSequence) picker.loading = false;
    }
  }

  function resetFiltersAndLoad() {
    pageCache.clear();
    return loadPage({reset: true});
  }

  async function resolveBulkSelection({allAvailable = false} = {}) {
    const pid = projectId();
    if (!pid) throw new Error('当前项目不存在');
    const response = await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-materials/bulk-selection`, {
      method: 'POST',
      headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
      body: JSON.stringify({
        all_available: Boolean(allAvailable),
        query: allAvailable ? '' : (picker?.query || ''),
        labels: allAvailable ? [] : [...(picker?.labels || [])],
      }),
    });
    const body = await readJson(response, '训练素材批量选择读取失败');
    return uniqueIds(body.items);
  }

  async function bulkAction(action) {
    if (!picker) return;
    if (action === 'clear-all') {
      picker.selected.clear();
      renderPage();
      return;
    }
    const buttons = document.querySelectorAll('[data-picker-action]');
    buttons.forEach(button => button.classList.add('train-v3-loading'));
    const count = document.getElementById('trV3PickerCount');
    if (count) count.textContent = '正在解析批量选择…';
    try {
      const ids = await resolveBulkSelection({allAvailable: action === 'select-all'});
      const blocked = blockedIds(picker.role);
      const eligible = ids.filter(id => !blocked.has(id));
      if (action === 'select-filtered' || action === 'select-all') eligible.forEach(id => picker.selected.add(id));
      else if (action === 'invert-filtered') eligible.forEach(id => picker.selected.has(id) ? picker.selected.delete(id) : picker.selected.add(id));
      renderPage();
    } catch (error) {
      notify(error?.message || '批量选择失败');
      updateCounts();
    } finally {
      buttons.forEach(button => button.classList.remove('train-v3-loading'));
    }
  }

  async function open(role) {
    const pid = projectId();
    if (!pid) return notify('当前项目不存在');
    cancelViewportFrame();
    injectStyles();
    picker = {
      role: role === 'test' ? 'test' : 'train',
      query: '', labels: new Set(), selected: new Set(),
      pageSize: DEFAULT_PAGE_SIZE, pageIndex: 0, cursors: [null], nextCursor: null,
      items: [], total: 0, loading: false, repositoryRevision: null,
    };
    state().trainMaterialPickerV3 = picker;
    const title = picker.role === 'train' ? '选择本次训练素材' : '选择独立试验素材';
    window.modal?.(title, modalHtml(picker.role), true);
    renderSkeleton();
    void loadPage({reset: true});
  }

  function setSearch(value) {
    if (!picker) return;
    picker.query = String(value || '').trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => resetFiltersAndLoad(), 220);
  }

  function toggleLabel(code) {
    if (!picker) return;
    const value = String(code || '');
    picker.labels.has(value) ? picker.labels.delete(value) : picker.labels.add(value);
    document.querySelectorAll('#trV3Chips .data426-chip').forEach(button => {
      button.classList.toggle('on', button.dataset.label ? picker.labels.has(button.dataset.label) : !picker.labels.size);
    });
    resetFiltersAndLoad();
  }

  function clearLabels() {
    if (!picker) return;
    picker.labels.clear();
    document.querySelectorAll('#trV3Chips .data426-chip').forEach(button => button.classList.toggle('on', !button.dataset.label));
    resetFiltersAndLoad();
  }

  function toggle(id, on, checkbox) {
    if (!picker) return;
    const value = String(id || '');
    if (blockedIds(picker.role).has(value)) {
      if (checkbox) checkbox.checked = false;
      return;
    }
    on ? picker.selected.add(value) : picker.selected.delete(value);
    checkbox?.closest('.train-v3-card')?.classList.toggle('on', Boolean(on));
    updateCounts();
  }

  async function page(delta) {
    if (!picker || picker.loading) return;
    const direction = Number(delta || 0);
    if (direction < 0) {
      if (picker.pageIndex <= 0) return;
      picker.pageIndex -= 1;
      return loadPage();
    }
    if (direction > 0 && picker.nextCursor) {
      picker.cursors[picker.pageIndex + 1] = picker.nextCursor;
      picker.pageIndex += 1;
      return loadPage();
    }
  }

  window.openTrainMaterialPickerV3 = open;
  window.trainMaterialSearchV3 = setSearch;
  window.toggleTrainMaterialLabelV3 = toggleLabel;
  window.clearTrainMaterialLabelsV3 = clearLabels;
  window.toggleTrainMaterialV3 = toggle;
  window.trainMaterialSelectV3 = bulkAction;
  window.trainMaterialPageV3 = page;
  window.confirmTrainMaterialPickerV3 = function confirmPicker() {
    if (!picker) return false;
    const current = draft();
    const patch = trainingMaterialSelectionPatch({
      role: picker.role,
      selectedIds: [...picker.selected],
      materialIds: current.materialIds || [],
      testMaterialIds: current.testMaterialIds || [],
    });
    trainingDraftRuntime.update(patch);
    window.closeModal?.();
    window.refreshTrainingMaterialSelectionUiV3?.();
    return true;
  };

  const runtime = {
    build: 'training-material-picker-runtime-422505',
    open,
    loadPage,
    bulkAction,
    state() {
      return picker ? {
        role: picker.role,
        query: picker.query,
        labels: [...picker.labels],
        selected: picker.selected.size,
        pageIndex: picker.pageIndex,
        pageSize: picker.pageSize,
        total: picker.total,
        items: picker.items.length,
        nextCursor: picker.nextCursor,
        repositoryRevision: picker.repositoryRevision,
        networkOwner: true,
        fullPoolHydration: false,
        bulkSelectionOwner: 'server',
        viewportThumbnailLoading: true,
        eagerThumbnailCount: THUMBNAIL_EAGER_COUNT,
      } : null;
    },
  };
  window.TrainingMaterialPickerRuntime = runtime;
  window.__trainingMaterialPickerRuntimeInstalled = true;
  return runtime;
}
