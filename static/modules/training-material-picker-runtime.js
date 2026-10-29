import {withRequestDeadline} from './api.js?v=20261021s';

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
  try { body = await response.json(); } catch (_error) { throw new Error(`${fallback}：响应格式无效，请重试`); }
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

export function buildTrainingMaterialQuery({cursor = null, page = null, pageSize = DEFAULT_PAGE_SIZE, query = '', labels = [], sortOrder = 'newest', effectiveLabelCodes = [], sampleRole = '', sourceIds = [], createdFrom = '', createdTo = '', annotationState = '', usageState = '', historyScope = '', algorithmId = '', historyPolicy = 'new_for_algorithm', role = 'train', negativePoolOnly = false, negativeCategoryIds = []} = {}) {
  const params = new URLSearchParams();
  if (page != null) {
    params.set('page', String(page));
    params.set('page_size', String(pageSize));
  } else {
    params.set('limit', String(pageSize));
    if (cursor) params.set('cursor', String(cursor));
  }
  if (String(query || '').trim()) params.set('query', String(query).trim());
  uniqueIds(labels).forEach(label => params.append('label', label));
  uniqueIds(effectiveLabelCodes).forEach(code => params.append('effective_label_code', code));
  if (sampleRole) params.set('sample_role', sampleRole);
  uniqueIds(sourceIds).forEach(id => params.append('storage_source_id', id));
  for (const [key,value] of Object.entries({created_from:createdFrom,created_to:createdTo,annotation_state:annotationState,usage_state:usageState,history_scope:historyScope,algorithm_asset_id:algorithmId,history_policy:historyPolicy,role})) if(value)params.set(key,String(value));
  if(negativePoolOnly)params.set('negative_pool_only','true');
  uniqueIds(negativeCategoryIds).forEach(id=>params.append('negative_category_id',id));
  params.set('sort_order', sortOrder === 'oldest' ? 'oldest' : 'newest');
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
  const objectiveIssue = row.annotation_issue_type
    || (['invalid_annotation','annotation_needs_review'].includes(row.sample_role_issue_type) ? row.sample_role_issue_type : '');
  const issueName = ({material_unavailable:'素材来源不可用',stale_ground_truth:'标注内容与素材不一致',
    annotation_needs_review:'标注来源或一致性需核验',invalid_annotation:'标注数据无效'})[objectiveIssue];
  const status = issueName ? `标注异常 · ${issueName}` : state === 'annotated'
    ? `已标注 · ${boxes.length} 框`
    : state === 'confirmed_empty'
      ? '已确认无目标'
      : String(row.processing_status || '') === 'processed'
        ? '未标注 · 已清洗'
        : '未标注';
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
  let modalLayer = null;
  const pageCache = new Map();

  function injectStyles() {
    if (document.getElementById('training-material-picker-runtime-style')) return;
    const style = document.createElement('style');
    style.id = 'training-material-picker-runtime-style';
    style.textContent = `
      .train-v3-picker.server-paged{min-height:64vh;display:flex;flex-direction:column;min-width:0}
      .train-v3-workspace{display:grid;grid-template-columns:230px minmax(0,1fr);gap:16px;min-height:0}
      .train-v3-filters{display:flex;flex-direction:column;gap:10px;max-height:65vh;overflow:auto;padding-right:10px;border-right:1px solid #e2e8f0}
      .train-v3-filters label{display:flex;flex-direction:column;gap:5px;font-size:12px;color:#475569}
      .train-v3-filters .train-v3-filter{display:flex;flex-direction:column;gap:8px}
      .train-v3-results{min-width:0}.train-v3-view{display:flex;justify-content:flex-end;gap:6px;margin-bottom:8px}
      .train-v3-footer{padding:12px 0 0;border-top:1px solid #e2e8f0;margin-top:12px;flex:none}
      .train-v3-picker.server-paged .train-v3-grid.compact-list{display:flex!important;flex-direction:column;gap:6px}
      .train-v3-picker.server-paged .compact-list .train-v3-card{display:grid!important;grid-template-columns:100px minmax(100px,1fr) minmax(90px,1fr);gap:6px 14px;width:100%;min-height:100px;align-items:center}
      .train-v3-picker.server-paged .compact-list .train-v3-preview{grid-row:1 / span 4;width:100px}
      .train-v3-picker.server-paged .train-v3-card details{font-size:11px;color:#475569;overflow-wrap:anywhere}
      @media(max-width:760px){.train-v3-workspace{grid-template-columns:1fr}.train-v3-filters{max-height:230px;border-right:0;border-bottom:1px solid #e2e8f0}.train-v3-picker.server-paged .compact-list .train-v3-card{grid-template-columns:85px minmax(0,1fr)}}
      .train-v3-picker.server-paged .train-v3-role-tools{padding:12px;background:#f4f7fc;border:1px solid #dbe5f3;border-radius:12px;margin-bottom:12px}
      .train-v3-picker.server-paged .train-v3-role-tools p{font-size:12px;color:#475569;margin:6px 0}
      .train-v3-picker.server-paged .train-v3-sample-role{white-space:normal;color:#315fc2;font-weight:600}
      .train-v3-picker.server-paged #trV3ReviewProgress{display:block;margin:8px 0;color:#334155}
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
      .train-v3-picker.server-paged .train-v3-card .train-v3-label-list{white-space:normal;overflow:visible;text-overflow:clip;overflow-wrap:anywhere;font-size:12px;line-height:1.5;min-height:20px;color:#334155;padding-bottom:5px}
      .train-v3-picker.server-paged #trV3Chips{grid-column:1 / -1;max-height:none;overflow:visible;align-content:start}
      .train-v3-picker.server-paged #trV3Chips .data426-chip{max-width:100%;white-space:normal;overflow-wrap:anywhere;line-height:1.4;text-align:left}
      .train-v3-picker.server-paged .train-v3-card.blocked{opacity:.5;cursor:not-allowed}
      .train-v3-picker.server-paged .train-v3-card.blocked:after{content:attr(data-block-reason);position:absolute;left:14px;top:14px;padding:3px 7px;border-radius:7px;background:rgba(15,23,42,.82);color:#fff;font-size:10px;z-index:2}
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

  function taskPayload() {
    const shared = window.TrainingMaterialSummaryRuntime?.pickerDraftPayload?.();
    if (shared) return {...shared,history_policy:draft().history_policy || 'new_for_algorithm'};
    const current = draft();
    return {algorithm_asset_id: String(current.algorithmId || ''), train_labels: uniqueIds(current.newLabelCodes),
      model: String(current.config?.model || 'yolo11n.pt'), framework: String(current.config?.framework || 'ultralytics'),
      base_version_id:String(current.baseVersionId || ''),history_policy:current.history_policy || 'new_for_algorithm'};
  }

  function blockedIds(role) {
    const current = draft();
    if (String(current.splitMode || '') !== 'independent_test_set') return new Set();
    const values = role !== 'test' ? current.testMaterialIds : current.materialIds;
    return new Set(uniqueIds(values));
  }

  function labelDisplay(code) {
    const row = (state().labels || []).find(item => String(item?.code || '') === String(code));
    return String(row?.display_name || row?.name || code || '');
  }

  function signature() {
    return JSON.stringify({
      project: projectId(),
      filters: picker?.filters || {}, role:picker?.role, scope:picker?.scopeIds, task: taskPayload(), sampleRole: picker?.sampleRole || '',
      query: picker?.query || '',
      labels: picker ? [...picker.labels].sort() : [],
      sortOrder: picker?.sortOrder || 'newest',
      pageSize: picker?.pageSize || DEFAULT_PAGE_SIZE,
    });
  }

  function cacheKey(page) {
    return `${signature()}::page:${Math.max(1, Number(page) || 1)}`;
  }

  const revisionKey=value=>JSON.stringify([value.repository_revision??0,value.annotation_revision??0,value.usage_revision||'unknown',value.negative_confirmation_revision??0,value.negative_pool_revision??0]);
  function remember(key, value) {
    if (pageCache.has(key)) pageCache.delete(key);
    pageCache.set(key, value);
    while (pageCache.size > CACHE_LIMIT) pageCache.delete(pageCache.keys().next().value);
  }

  function modalHtml(role) {
    const title = role === 'robustness' ? '增强训练素材' : role === 'train' ? '训练候选素材' : '独立试验素材';
    const context = taskPayload();
    const hasTaskLabels = uniqueIds(context.train_labels).length > 0 || Boolean(context.base_version_id);
    const chips = (state().labels || []).map(row => (
      `<button class="data426-chip" data-label="${esc(row.code)}" onclick="toggleTrainMaterialLabelV3('${esc(row.code)}')">${esc(row.display_name || row.code)}</button>`
    )).join('');
    const rule = role === 'robustness' ? '仅从当前训练素材中选择增强候选；实际训练角色将在提交时核验' : role === 'train'
      ? '当前选择未确定训练目标时，先按正式标注状态选择素材；待标注素材会保留在任务中，但不会自动变成负样本'
      : '独立试验集必须具备正式 Ground Truth，未标注素材只展示但不可选择';
    return `<div class="train-v3-picker server-paged">
      <header><div><b>${title}</b><span>${rule}</span></div><strong id="trV3PickerCount">正在读取素材…</strong></header>
      <div class="train-v3-workspace"><aside class="train-v3-filters">${role === 'train' && hasTaskLabels ? `<section class="train-v3-role-tools"><b id="trV3TrainingLabels">本次训练目标：读取中…</b><p id="trV3RoleCounts" aria-live="polite"></p><select id="trV3RoleFilter" class="select" aria-label="按本次训练目标筛选" onchange="TrainingMaterialPickerRuntime.setSampleRole(this.value)"><option value="">全部素材</option><option value="positive">含本次目标</option><option value="confirmed_negative">已确认不含本次目标</option><option value="pending_negative">最终创建时确认候选背景</option><option value="pending_review">标注或目标范围需核验</option></select><p>选择素材不需要逐张确认；最终创建时统一检查类别覆盖、GT 问题和候选背景。</p></section>` : ''}
      <div class="train-v3-filter"><input id="trV3Q" class="input" placeholder="搜索图片名称" oninput="trainMaterialSearchV3(this.value)"><select id="trV3Sort" class="select" aria-label="按加入时间排序" onchange="trainMaterialSortV3(this.value)"><option value="newest">最新加入优先</option><option value="oldest">最早加入优先</option></select><div id="trV3Chips" class="data426-chips"><button class="data426-chip clear on" data-label="" onclick="clearTrainMaterialLabelsV3()">全部标签</button>${chips}</div></div>
      ${role==='train'?`<label>素材范围<select class="select" aria-label="素材范围" onchange="TrainingMaterialPickerRuntime.setFilter('negativePoolOnly',this.value)"><option value="">普通素材（含负样本池）</option><option value="pool">负样本池</option></select></label><label>负样本分类<select class="select" multiple aria-label="负样本分类筛选" id="trV3NegativeCategories" onchange="TrainingMaterialPickerRuntime.setFilter('negativeCategoryIds',[...this.selectedOptions].map(o=>o.value).join(','))"><option disabled>正在读取分类…</option></select></label>`:''}
      <label>存储来源<input class="input" placeholder="来源ID，多个用逗号分隔" onchange="TrainingMaterialPickerRuntime.setFilter('sourceIds',this.value)"></label>
      <label>加入时间从<input type="date" class="input" onchange="TrainingMaterialPickerRuntime.setFilter('createdFrom',this.value)"></label><label>至<input type="date" class="input" onchange="TrainingMaterialPickerRuntime.setFilter('createdTo',this.value)"></label>
      <label>正式标注<select class="select" onchange="TrainingMaterialPickerRuntime.setFilter('annotationState',this.value)"><option value="">全部状态</option><option value="annotated">已标注</option><option value="confirmed_empty">已确认无目标</option><option value="unannotated">未标注</option></select></label>
      <label>真实训练历史<select class="select" onchange="TrainingMaterialPickerRuntime.setFilter('usageState',this.value)"><option value="">全部历史</option><option value="used">已使用</option><option value="possible">可能使用</option><option value="selected">仅选入</option><option value="eval_only">仅参与评测</option><option value="unused">有据未使用</option><option value="unknown">未知</option></select></label>
      <label>算法训练范围<select class="select" onchange="TrainingMaterialPickerRuntime.setFilter('historyScope',this.value)"><option value="">所有算法范围</option><option value="current_only">仅当前算法训练（已知证据）</option><option value="other_only">仅其他算法训练（已知证据）</option></select></label><p class="train-v3-history-note">历史未完整回填时，“仅”表示当前已知证据；未知素材不能据此证明独立。</p>
      </aside><main class="train-v3-results"><div class="train-v3-view"><button class="btn mini" onclick="TrainingMaterialPickerRuntime.setView('grid')">网格</button><button class="btn mini" onclick="TrainingMaterialPickerRuntime.setView('list')">紧凑列表</button></div>
      <div class="picker412-actions train-v3-batch"><button class="btn mini" data-picker-action="select-filtered" onclick="trainMaterialSelectV3('select-filtered')">全选当前筛选</button><button class="btn mini" data-picker-action="invert-filtered" onclick="trainMaterialSelectV3('invert-filtered')">反选当前筛选</button><button class="btn mini" data-picker-action="select-all" onclick="trainMaterialSelectV3('select-all')">全选全部可用素材</button><button class="btn mini" onclick="trainMaterialSelectV3('clear-all')">全部不选</button><button class="btn mini" data-picker-action="select-page" onclick="trainMaterialSelectV3('select-page')">全选本页</button><button class="btn mini" data-picker-action="invert-all" onclick="trainMaterialSelectV3('invert-all')">反选全部</button><span id="trV3PageMeta" class="train-v3-page-meta"></span></div>
      <div id="trV3Grid" class="train-v3-grid"></div>
      <div id="trV3Pager" class="data426-pager"></div>
      </main></div><footer class="row end train-v3-footer"><button class="btn" onclick="TrainingMaterialPickerRuntime.close()">取消</button><button class="btn primary" data-picker-confirm onclick="confirmTrainMaterialPickerV3()">确认选择</button></footer>
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
    const labelHost = document.getElementById('trV3TrainingLabels');
    if (labelHost) labelHost.textContent = `本次训练标签：${(picker.effectiveLabels || []).join('、') || '请先选择训练标签'}`;
    const roleCounts = document.getElementById('trV3RoleCounts');
    if (roleCounts) {const c=picker.roleCounts || {}; roleCounts.textContent = `按当前训练目标 · 含目标 ${c.positive || 0} · 已确认无目标 ${c.confirmed_negative || 0} · 待确认无目标 ${c.pending_negative || 0} · 标注或范围需核验 ${c.pending_review || 0}`;}
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

  function renderPager() {
    if (!picker) return;
    const pager = document.getElementById('trV3Pager');
    window.PlatformCore?.pagination?.mountPagination?.(pager, {
      page: picker.page,
      pageSize: picker.pageSize,
      total: picker.total,
      totalPages: picker.totalPages,
      hasPrevious: picker.page > 1,
      hasNext: picker.page < picker.totalPages,
      loading: picker.loading,
    }, {
      label: '训练素材分页',
      showPageSize: true,
      pageSizes: [20, 50, 60, 100],
      onPageChange: targetPage => picker?.reviewPending ? null : loadPage({page: targetPage}),
      onPageSizeChange: pageSize => {
        if (picker?.reviewPending) return;
        picker.pageSize = pageSize;
        pageCache.clear();
        return loadPage({reset: true});
      },
    });
  }

  function renderPage() {
    if (!picker) return;
    const grid = document.getElementById('trV3Grid');
    if (!grid) return;
    cancelViewportFrame();
    grid.scrollTop = 0;grid.classList.toggle('compact-list',picker.view==='list');
    const blocked = blockedIds(picker.role);
    grid.innerHTML = picker.items.map((row, index) => {
      const id = String(row.id || '');
      const selected = picker.reviewing ? picker.reviewSelected.has(id) : picker.selected.has(id);
      const crossRoleBlocked = blocked.has(id);
      const missingTestTruth = picker.role === 'test' && String(row.annotation_state || '') === 'unannotated';
      const unavailable = crossRoleBlocked || missingTestTruth || (picker.reviewing && row.sample_role !== 'pending_negative');
      const blockReason = crossRoleBlocked ? '已用于另一素材集' : (missingTestTruth ? '试验集必须已标注' : '');
      const labelText = (row.labels || []).map(labelDisplay).filter(Boolean).join('、')
        || (String(row.annotation_state || '') === 'unannotated' ? '未标注' : '无标签');
      const loading = index < THUMBNAIL_EAGER_COUNT ? 'eager' : 'lazy';
      const priority = index < THUMBNAIL_EAGER_COUNT ? 'high' : 'low';
      return `<label class="train-v3-card ${selected ? 'on' : ''} ${unavailable ? 'blocked' : ''}" data-material-id="${esc(id)}" data-block-reason="${esc(blockReason)}">
        <input type="checkbox" ${selected ? 'checked' : ''} ${unavailable ? 'disabled' : ''} onchange="toggleTrainMaterialV3('${esc(id)}',this.checked,this)">
        ${renderTrainingMaterialPreview(row, {loading, priority})}
        <b title="${esc(row.filename || '')}">${esc(row.filename || id)}</b><span class="train-v3-label-list" title="${esc(labelText)}">${esc(labelText)}</span>
        ${picker.role === 'train' && (picker.sampleRole || picker.reviewing) && picker.effectiveLabels?.length ? `<span class="train-v3-sample-role" data-sample-role="${esc(row.sample_role || '')}">${esc(({positive:'含本次目标',confirmed_negative:`已确认不含 ${(picker.effectiveLabels || []).join('、')}`,pending_negative:`尚需确认不含 ${(picker.effectiveLabels || []).join('、')}`,pending_review:({missing_annotation:'未标注',partial_review_scope:'所需目标范围尚未确认',invalid_annotation:'标注数据无效',annotation_needs_review:'标注或来源一致性需核验',material_unavailable:'素材来源不可用',stale_ground_truth:'标注内容与素材不一致'})[row.annotation_issue_type || row.sample_role_issue_type] || '标注异常，请核验原因'})[row.sample_role] || '')}</span>` : ''}
        <span>${esc(row.storage_source_id || '')} · ${esc((row.created_at || '').slice(0,10))}</span>
        <details onclick="event.stopPropagation()" ontoggle="if(this.open)TrainingMaterialPickerRuntime.loadHistory('${esc(id)}',this)"><summary>训练历史 · 已知训练 ${Number(row.training_usage?.training_task_count || 0)} 次 · ${esc(({used:'已使用',possible:'可能使用',selected:'仅已选入',eval_only:'仅参与评测',unused:'有据未使用',unknown:'未知'})[row.training_usage?.state] || '未知')}</summary><p>${esc((row.training_usage?.task_ids || []).join('、') || '缺少完整执行证据，不能判定从未使用')}</p></details>
        <a class="btn mini" href="${esc(row.content_url || '#')}" target="_blank" rel="noopener" onclick="event.stopPropagation()">查看原图</a>
        ${picker.reviewing ? `<button type="button" class="btn mini" onclick="event.preventDefault();event.stopPropagation();TrainingMaterialPickerRuntime.editAnnotation('${esc(id)}')">发现目标 · 去标注</button>` : ''}
      </label>`;
    }).join('') || `<div class="empty">没有符合筛选条件的已清洗素材${taskPayload().history_policy==='new_for_algorithm' && ['used','possible'].includes(picker.filters?.usageState)?'<p>当前新素材策略已排除已参与或可能参与训练项，可在训练配置中调整。</p>':''}</div>`;
    updateCounts();
    renderPager();
    attachImageFallbacks();
  }

  async function loadPage({reset = false, page = null} = {}) {
    if (!picker) return;
    if (reset) {
      picker.page = 1;
      picker.totalPages = 1;
    }
    const owner=picker, pid=projectId(), contextKey=signature();
    const sequence = ++requestSequence;
    activeController?.abort?.();
    activeController = new AbortController();
    const controller=activeController;
    const current=()=>picker===owner && projectId()===pid && sequence===requestSequence && signature()===contextKey && Boolean(document.getElementById('trV3Grid'));
    const requestedPage = Math.max(1, Number(page ?? picker.page) || 1);
    const key = cacheKey(requestedPage);
    const cached = pageCache.get(key);
    if (cached) {
      try {
        const revision=await withRequestDeadline(async signal=>{const r=await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-materials/revision?algorithm_asset_id=${encodeURIComponent(taskPayload().algorithm_asset_id || '')}`,{signal});return readJson(r,'素材版本读取失败');},{signal:controller.signal,label:'素材版本读取'});
        if(!current())return;
        if(revisionKey(revision)!==cached.versionKey){pageCache.clear();return loadPage({page:requestedPage});}
      } catch(error) {if(current()){notify(error.code==='REQUEST_TIMEOUT'?'素材读取超时，请重试':error.message); const grid=document.getElementById('trV3Grid');if(grid)grid.innerHTML='<button class="btn" onclick="TrainingMaterialPickerRuntime.loadPage()">读取失败 · 重试</button>';}return;}
      picker.effectiveLabels = cached.effective_label_codes || [];
      picker.roleCounts = cached.sample_role_counts || {};
      picker.items = cached.items;
      picker.total = cached.total;
      picker.page = Math.max(1, Number(cached.page || requestedPage));
      picker.totalPages = Math.max(1, Number(cached.total_pages || 1));
      picker.repositoryRevision = cached.repository_revision ?? null;
      picker.loading = false;
      renderPage();
      return;
    }

    picker.loading = true;
    renderSkeleton();
    updateCounts();
    renderPager();
    try {
      if (!pid) throw new Error('当前项目不存在');
      const query = buildTrainingMaterialQuery({
        page: requestedPage,
        pageSize: picker.pageSize,
        query: picker.query,
        labels: [...picker.labels],
        sortOrder: picker.sortOrder,
        ...picker.filters, algorithmId:taskPayload().algorithm_asset_id,historyPolicy:taskPayload().history_policy,role:picker.role==='test'?'test':'train',
      });
      const context=taskPayload();
      const hasTaskLabels=uniqueIds(context.train_labels).length > 0 || Boolean(context.base_version_id);
      const withRoles=(picker.role === 'train' || picker.role === 'robustness') && hasTaskLabels;
      const scoped=picker.role==='robustness';
      const body = await withRequestDeadline(async signal=>{
      const response = await fetchImpl(withRoles
        ? `/api/v62/projects/${encodeURIComponent(pid)}/training-materials/role-page`
        : scoped ? `/api/v62/projects/${encodeURIComponent(pid)}/training-materials/page` : `/api/v62/projects/${encodeURIComponent(pid)}/training-materials?${query}`, {
        signal,
        ...((withRoles || scoped) ? {method:'POST', body:JSON.stringify({...taskPayload(), ...filterPayload(), page:requestedPage,
          page_size:picker.pageSize, query:picker.query, labels:[...picker.labels], sort_order:picker.sortOrder, sample_role:picker.sampleRole})} : {}),
        headers: {'Accept': 'application/json', 'Content-Type':'application/json'},
      });
      return readJson(response, '训练素材读取失败，请重试');
      }, {signal:controller.signal,label:'训练素材读取'});
      if (!current()) return;
      picker.effectiveLabels = body.effective_label_codes || [];
      picker.roleCounts = body.sample_role_counts || {};
      picker.items = Array.isArray(body.items) ? body.items : [];
      picker.total = Math.max(0, Number(body.total || 0));
      picker.page = Math.max(1, Number(body.page || requestedPage));
      picker.pageSize = Math.max(1, Number(body.page_size || picker.pageSize));
      picker.totalPages = Math.max(1, Number(body.total_pages || 1));
      picker.repositoryRevision = body.repository_revision ?? null;
      remember(key, {...body,versionKey:revisionKey(body)});
      picker.loading = false;
      renderPage();
    } catch (error) {
      if (error?.name === 'AbortError') return;
      if (!current()) return;
      const grid = document.getElementById('trV3Grid');
      if (grid) grid.innerHTML = `<div class="empty">${esc(error?.code==='REQUEST_TIMEOUT'?'素材读取超时，请重试':error?.message || '训练素材读取失败')}<button class="btn" onclick="TrainingMaterialPickerRuntime.loadPage()">重试</button></div>`;
      notify(error?.message || '训练素材读取失败');
    } finally {
      if (current()) {
        picker.loading = false;
        renderPager();
      }
    }
  }

  function resetFiltersAndLoad() {
    pageCache.clear();
    return loadPage({reset: true});
  }

  function filterPayload() {
    const f=picker?.filters || {};
    return {role:picker?.role==='test'?'test':'train',storage_source_ids:uniqueIds(f.sourceIds),annotation_state:f.annotationState || '',created_from:f.createdFrom || '',created_to:f.createdTo || '',usage_state:f.usageState || '',history_scope:f.historyScope || '',negative_pool_only:Boolean(f.negativePoolOnly),negative_category_ids:uniqueIds(f.negativeCategoryIds),
      ...(picker?.role==='robustness'?{image_ids:picker.scopeIds}:{} )};
  }

  async function resolveBulkSelection({allAvailable = false} = {}) {
    const pid = projectId();
    if (!pid) throw new Error('当前项目不存在');
    return withRequestDeadline(async signal=>{
    const response = await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-materials/bulk-selection`, {
      signal,
      method: 'POST',
      headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
      body: JSON.stringify({
        ...taskPayload(), ...filterPayload(), sample_role: allAvailable ? '' : (picker?.sampleRole || ''),
        all_available: Boolean(allAvailable),
        query: allAvailable ? '' : (picker?.query || ''),
        labels: allAvailable ? [] : [...(picker?.labels || [])],
        role: picker?.role === 'robustness' ? 'train' : (picker?.role || 'train'),
      }),
    });
    const body = await readJson(response, '训练素材批量选择读取失败');
    return uniqueIds(body.items);
    },{signal:picker?.bulkController?.signal,label:'素材批量选择'});
  }

  async function bulkAction(action) {
    if (!picker || picker.bulkPending || picker.reviewing) return;
    if (action === 'select-page') {
      picker.items.forEach(row=>{if(!blockedIds(picker.role).has(String(row.id)) && (picker.role!=='test' || row.annotation_state!=='unannotated'))picker.selected.add(String(row.id));});renderPage();return;
    }
    if (action === 'clear-all') {
      picker.selected.clear();
      renderPage();
      return;
    }
    const activePicker = picker, pid = projectId(), contextKey=signature();
    activePicker.bulkController?.abort();activePicker.bulkController=new AbortController();
    activePicker.bulkPending = true;
    const buttons = document.querySelectorAll('[data-picker-action], [data-picker-confirm]');
    buttons.forEach(button => {button.disabled = true;button.classList.add('train-v3-loading');});
    const count = document.getElementById('trV3PickerCount');
    if (count) count.textContent = '正在解析批量选择…';
    try {
      const ids = await resolveBulkSelection({allAvailable: action === 'select-all' || action === 'invert-all'});
      if (picker !== activePicker || projectId() !== pid || signature()!==contextKey) return;
      const blocked = blockedIds(picker.role);
      const eligible = ids.filter(id => !blocked.has(id));
      if (action === 'select-filtered' || action === 'select-all') eligible.forEach(id => picker.selected.add(id));
      else if (action === 'invert-filtered' || action === 'invert-all') eligible.forEach(id => picker.selected.has(id) ? picker.selected.delete(id) : picker.selected.add(id));
      renderPage();
    } catch (error) {
      if (picker !== activePicker || projectId() !== pid || signature()!==contextKey) return;
      notify(error?.message || '批量选择失败');
      updateCounts();
    } finally {
      activePicker.bulkPending = false;
      buttons.forEach(button => {button.disabled = false;button.classList.remove('train-v3-loading');});
    }
  }

  async function open(role) {
    const pid = projectId();
    if (!pid) return notify('当前项目不存在');
    cancelViewportFrame();
    activeController?.abort();picker?.bulkController?.abort();picker?.historyControllers?.forEach(c=>c.abort());++requestSequence;clearTimeout(searchTimer);
    injectStyles();
    if (typeof role === 'object') role=role.role;
    picker = {
      sampleRole:'', effectiveLabels:[], roleCounts:{}, reviewing:false, reviewSelected:new Set(),
      role: ['test','robustness'].includes(role) ? role : 'train',
      filters:{}, view:'grid', historyControllers:new Set(), scopeIds:uniqueIds(draft().materialIds),
      query: '', labels: new Set(), sortOrder: 'newest', selected: new Set(uniqueIds(role==='robustness'?draft().robustness_policy?.selection?.image_ids:role==='test'?draft().testMaterialIds:draft().materialIds).filter(id=>!blockedIds(role).has(id) && (role!=='robustness' || uniqueIds(draft().materialIds).includes(id)))),
      pageSize: DEFAULT_PAGE_SIZE, page: 1, totalPages: 1,
      items: [], total: 0, loading: false, repositoryRevision: null,
    };
    state().trainMaterialPickerV3 = picker;
    const title = picker.role === 'robustness' ? '选择增强训练素材' : picker.role === 'train' ? '选择本次训练素材' : '选择独立试验素材';
    modalLayer=window.modal?.(title, modalHtml(picker.role), true);
    renderSkeleton();
    void loadPage({reset: true});
    if(picker.role==='train'){
      const owner=picker,controller=new AbortController();owner.historyControllers.add(controller);
      void withRequestDeadline(async signal=>readJson(await fetchImpl(`/api/v61/projects/${encodeURIComponent(pid)}/negative-pool/categories`,{signal}),'负样本分类读取失败'),{signal:controller.signal,label:'负样本分类'}).then(data=>{
        if(picker!==owner||projectId()!==pid)return;
        const select=document.getElementById('trV3NegativeCategories');if(select)select.innerHTML=(data.items||[]).filter(row=>row.enabled!==false).map(row=>`<option value="${esc(row.id)}" ${(owner.filters.negativeCategoryIds||[]).includes(row.id)?'selected':''}>${esc(row.name)}</option>`).join('')||'<option disabled>暂无负样本分类</option>';
      }).catch(error=>{if(picker===owner&&error.name!=='AbortError'){const select=document.getElementById('trV3NegativeCategories');if(select)select.innerHTML='<option disabled>读取失败，重新打开可重试</option>';}}).finally(()=>owner.historyControllers.delete(controller));
    }
  }

  function setSearch(value) {
    if (!picker || picker.reviewPending) return;
    picker.query = String(value || '').trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => resetFiltersAndLoad(), 220);
  }

  function setSortOrder(value) {
    if (!picker || picker.reviewPending) return;
    picker.sortOrder = value === 'oldest' ? 'oldest' : 'newest';
    resetFiltersAndLoad();
  }

  function toggleLabel(code) {
    if (!picker || picker.reviewPending) return;
    const value = String(code || '');
    picker.labels.has(value) ? picker.labels.delete(value) : picker.labels.add(value);
    document.querySelectorAll('#trV3Chips .data426-chip').forEach(button => {
      button.classList.toggle('on', button.dataset.label ? picker.labels.has(button.dataset.label) : !picker.labels.size);
    });
    resetFiltersAndLoad();
  }

  function clearLabels() {
    if (!picker || picker.reviewPending) return;
    picker.labels.clear();
    document.querySelectorAll('#trV3Chips .data426-chip').forEach(button => button.classList.toggle('on', !button.dataset.label));
    resetFiltersAndLoad();
  }

  function toggle(id, on, checkbox) {
    if (!picker || picker.reviewPending) return;
    const value = String(id || '');
    if (picker.reviewing) {
      if (picker.items.find(row=>String(row.id)===value)?.sample_role !== 'pending_negative') return;
      if (on && picker.reviewSelected.size >= 50) {if(checkbox)checkbox.checked=false;return notify('每批最多审核 50 张');}
      on ? picker.reviewSelected.add(value) : picker.reviewSelected.delete(value);
      checkbox?.closest('.train-v3-card')?.classList.toggle('on', Boolean(on));
      const progress=document.getElementById('trV3ReviewProgress'); if(progress)progress.textContent=`本批已勾选 ${picker.reviewSelected.size}/50 张`;
      return;
    }
    const row = (picker.items || []).find(item => String(item?.id || '') === value);
    if (
      blockedIds(picker.role).has(value)
      || (picker.role === 'test' && String(row?.annotation_state || '') === 'unannotated')
    ) {
      if (checkbox) checkbox.checked = false;
      return;
    }
    on ? picker.selected.add(value) : picker.selected.delete(value);
    checkbox?.closest('.train-v3-card')?.classList.toggle('on', Boolean(on));
    updateCounts();
  }

  async function page(delta) {
    if (!picker || picker.loading || picker.reviewPending) return;
    const direction = Number(delta || 0);
    const targetPage = picker.page + Math.sign(direction);
    if (targetPage < 1 || targetPage > picker.totalPages) return;
    return loadPage({page: targetPage});
  }

  window.openTrainMaterialPickerV3 = open;
  window.trainMaterialSearchV3 = setSearch;
  window.trainMaterialSortV3 = setSortOrder;
  window.toggleTrainMaterialLabelV3 = toggleLabel;
  window.clearTrainMaterialLabelsV3 = clearLabels;
  window.toggleTrainMaterialV3 = toggle;
  window.trainMaterialSelectV3 = bulkAction;
  window.trainMaterialPageV3 = page;
  window.confirmTrainMaterialPickerV3 = function confirmPicker() {
    if (!picker || picker.bulkPending || picker.reviewPending) return false;
    const current = draft();
    if(picker.role==='robustness'){
      const policy=current.robustness_policy || {};
      trainingDraftRuntime.update({robustness_policy:{...policy,selection:{...(policy.selection || {}),mode:'manual',image_ids:[...picker.selected].filter(id=>picker.scopeIds.includes(id))}}});
      window.closeModal?.();window.refreshTrainingMaterialSelectionUiV3?.();return true;
    }
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
    build: 'training-material-picker-runtime-422615',
    open,
    setSampleRole(value) {
      if (!picker || picker.reviewPending) return;
      if(value && !uniqueIds(taskPayload().train_labels).length && !taskPayload().base_version_id){
        const select=document.getElementById('trV3RoleFilter');if(select)select.value=picker.sampleRole;
        notify('选择本次训练标签后可按样本角色筛选');return;
      }
      picker.sampleRole = ['positive','confirmed_negative','pending_negative','pending_review'].includes(value) ? value : '';
      return resetFiltersAndLoad();
    },
    startReview() {
      if (!picker?.effectiveLabels?.length) return notify('请先选择本次训练标签');
      picker.reviewing=true; picker.reviewSelected.clear(); picker.sampleRole='pending_negative';
      const tools=document.getElementById('trV3ReviewTools'); if(tools)tools.hidden=false;
      return resetFiltersAndLoad();
    },
    stopReview() {
      if (!picker || picker.reviewPending) return;
      picker.reviewing=false; picker.reviewSelected.clear();
      const tools=document.getElementById('trV3ReviewTools'); if(tools)tools.hidden=true;
      renderPage();
    },
    editAnnotation(id) {
      if (!picker || picker.reviewPending) return;
      const row=picker.items.find(item=>String(item.id)===String(id)); if(!row)return;
      const s=state();
      if(!(s.images || []).some(item=>String(item.id)===String(id)))s.images=[...(s.images || []),{...row,url:row.content_url}];
      s.trainingAnnotationReviewContext={imageId:String(id),requiredLabelCodes:picker.effectiveLabels,
        missingLabelCodes:picker.effectiveLabels,returnSource:'training',projectId:String(projectId() || '')};
      return window.openAnnotation?.(String(id));
    },
    async confirmReview() {
      if (!picker?.reviewing || picker.reviewPending) return;
      const rows=picker.items.filter(row=>picker.reviewSelected.has(String(row.id)) && row.sample_role==='pending_negative');
      if(!rows.length)return notify('请先逐张查看并勾选本页图片');
      if(!window.confirm(`确认已查看这 ${rows.length} 张图片，均不包含 ${(picker.effectiveLabels || []).join('、')}？原有标注框会保留。`))return;
      const owner=picker, pid=projectId(); owner.reviewPending=true;
      const progress=document.getElementById('trV3ReviewProgress');
      if(progress)progress.textContent=`正在保存 ${rows.length} 张审核结果…`;
      try {
        const context={...taskPayload(),image_ids:rows.map(row=>String(row.id))};
        const post=async(action,body)=>withRequestDeadline(async signal=>readJson(await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-materials/${action}`,{
          signal,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}),'审核保存失败，请重试'),{timeoutMs:30000,label:'负样本确认保存'});
        const preview=await post('negative-preview',context);
        if(preview.counts?.pending_review||preview.counts?.positive)throw new Error('素材或标注已变化，请重新核验，不能确认为负样本');
        if(Number(preview.pending_count)>0)await post('confirm-negatives',{...context,confirmed:true,proof_digest:preview.proof_digest});
        if(picker!==owner || projectId()!==pid)return;
        rows.forEach(row=>owner.reviewSelected.delete(String(row.id)));
        if(progress)progress.textContent=`已保存 ${rows.length}/${rows.length} 张任务目标确认；原图和正式标注未修改`;
        pageCache.clear(); await loadPage({reset:true});
        window.TrainingMaterialSummaryRuntime?.invalidate?.();
        void window.TrainingMaterialSummaryRuntime?.refresh?.(undefined,{force:true});
        window.refreshTrainingMaterialSelectionUiV3?.();
      } catch(error) {if(picker===owner && progress)progress.textContent=error.message+'；勾选已保留，可重试';}
      finally {owner.reviewPending=false;}
    },
    beforeModalClose(layer) {
      if(!picker || (modalLayer && layer!==modalLayer))return;
      activeController?.abort();picker.bulkController?.abort();picker.historyControllers?.forEach(c=>c.abort());++requestSequence;cancelViewportFrame();clearTimeout(searchTimer);picker=null;modalLayer=null;
    },
    async loadHistory(id,host,page=1) {
      if(!picker || !host || (host.dataset.loaded==='1' && page===Number(host.dataset.page || 1)))return;
      const owner=picker,pid=projectId(),controller=new AbortController();owner.historyControllers.add(controller);
      const text=host.querySelector('p');if(text)text.textContent='正在读取历史证据…';
      try {
        const body=await withRequestDeadline(async signal=>{
          const r=await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-materials/history`,{signal,method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({image_id:id,algorithm_asset_id:taskPayload().algorithm_asset_id,page})});
          return readJson(r,'历史读取失败');
        },{signal:controller.signal,label:'历史证据读取'});
        if(picker!==owner || projectId()!==pid || !host.isConnected)return;
        host.dataset.loaded='1';host.dataset.page=String(page);
        if(text)text.textContent=`已知训练任务 ${body.summary?.training_task_count || 0} 次 · 可能训练 ${body.summary?.possible_training_task_count || 0} 次 · 最近完成 ${body.summary?.last_completed_at || '未知'} · 第 ${body.page || 1} 页 / 共 ${body.total || 0} 条。`+(body.items || []).map(row=>`算法 ${row.algorithm_name || row.algorithm_id || '未知'} · 任务 ${row.task_id} · ${row.role} · ${row.evidence===2?'已使用':row.evidence===1?'可能使用':'仅选入'} · 版本 ${row.version_id || '未知'} · 加入 ${row.created_at || '未知'} · 完成 ${row.finished_at || '未知'} · Snapshot ${row.snapshot_id || '未知'}`).join('；') || ('缺少完整历史证据；不能推断从未使用。项目原任务追溯（与该图关系未核验）：'+(body.legacy_trace || []).map(row=>`${row.task_id} · ${row.status} · ${row.created_at || '时间未知'}`).join('；'));
        let previous=host.querySelector('[data-history-previous]');if(previous)previous.remove();
        if(page>1){previous=document.createElement('button');previous.type='button';previous.className='btn mini';previous.dataset.historyPrevious='1';previous.textContent='上一页历史';previous.onclick=e=>{e.preventDefault();e.stopPropagation();runtime.loadHistory(id,host,page-1);};host.appendChild(previous);}
        let next=host.querySelector('[data-history-next]');if(next)next.remove();
        if((body.page || 1)*(body.page_size || 20)<body.total){next=document.createElement('button');next.type='button';next.className='btn mini';next.dataset.historyNext='1';next.textContent='下一页历史';next.onclick=e=>{e.preventDefault();e.stopPropagation();runtime.loadHistory(id,host,(body.page || 1)+1);};host.appendChild(next);}
      } catch(error) {if(picker===owner && text)text.textContent='历史读取失败；关闭后展开可重试';}
      finally {owner.historyControllers.delete(controller);}
    },
    setFilter(key,value) {
      if(!picker || picker.reviewPending || picker.bulkPending)return;
      picker.filters[key]=['sourceIds','negativeCategoryIds'].includes(key)?uniqueIds(String(value).split(',')):key==='negativePoolOnly'?value==='pool':value;
      if(key==='negativeCategoryIds'&&picker.filters[key].length)picker.filters.negativePoolOnly=true;
      return resetFiltersAndLoad();
    },
    setView(value) {if(picker){picker.view=value==='list'?'list':'grid';renderPage();}},
    close() {activeController?.abort();picker?.bulkController?.abort();picker?.historyControllers?.forEach(c=>c.abort());++requestSequence;cancelViewportFrame();clearTimeout(searchTimer);picker=null;window.closeModal?.();},
    loadPage,
    bulkAction,
    state() {
      return picker ? {
        role: picker.role,
        query: picker.query,
        labels: [...picker.labels],
        sortOrder: picker.sortOrder,
        selected: picker.selected.size,
        pageIndex: picker.page - 1,
        page: picker.page,
        pageSize: picker.pageSize,
        totalPages: picker.totalPages,
        total: picker.total,
        items: picker.items.length,
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
