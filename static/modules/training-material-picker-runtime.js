import {withRequestDeadline} from './api.js?v=20261021s';

const DEFAULT_PAGE_SIZE = 60;
const CACHE_LIMIT = 12;
const THUMBNAIL_EAGER_COUNT = 10;
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

export function trainingMaterialSelectable(row, role = 'train', blocked = new Set()) {
  return !blocked.has(String(row?.id || '')) && !row?.training_usage?.excluded
    && (role !== 'test' || (row?.annotation_state !== 'unannotated' && row?.training_usage?.state !== 'unknown'));
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

// A picker may open with tens of thousands of explicit IDs. Build the
// robustness scope once instead of repeatedly normalizing it per candidate.
export function initialTrainingMaterialIds({role='train', materialIds=[], testMaterialIds=[], robustnessImageIds=[], blocked=new Set()}={}) {
  const source = role==='robustness' ? robustnessImageIds : role==='test' ? testMaterialIds : materialIds;
  const scope = role==='robustness' ? new Set(uniqueIds(materialIds)) : null;
  return uniqueIds(source).filter(id => !blocked.has(id) && (!scope || scope.has(id)));
}

export function buildTrainingMaterialQuery({cursor = null, page = null, pageSize = DEFAULT_PAGE_SIZE, query = '', labels = [], sortOrder = 'newest', effectiveLabelCodes = [], sampleRole = '', sourceIds = [], createdFrom = '', createdTo = '', annotationState = '', usageState = '', historyScope = '', algorithmId = '', historyPolicy = 'new_for_algorithm', role = 'train', negativePoolOnly = false, negativeCategoryIds = [], countMode = '', labelMode = 'any'} = {}) {
  const params = new URLSearchParams();
  if (page != null) {
    params.set('page', String(page));
    params.set('page_size', String(pageSize));
  } else {
    params.set('limit', String(pageSize));
    if (cursor) params.set('cursor', String(cursor));
  }
  if (countMode) params.set('count_mode', countMode);
  params.set('label_mode',labelMode);
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
  let activePageKey = null;
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
      /* The compact-list and preview geometry are shared by both picker views. */
      .train-v3-picker.server-paged .train-v3-grid.compact-list{display:flex!important;flex-direction:column;gap:6px}
      .train-v3-picker.server-paged .compact-list .train-v3-card{display:grid!important;grid-template-columns:100px minmax(100px,1fr) minmax(90px,1fr);gap:6px 14px;width:100%;min-height:100px;align-items:center}
      .train-v3-picker.server-paged .compact-list .train-v3-preview{grid-row:1 / span 4;width:100px}
      .train-v3-picker.server-paged #trV3ReviewProgress{display:block;margin:8px 0;color:#334155}
      .train-v3-picker.server-paged .train-v3-box-layer{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;overflow:visible}
      .train-v3-picker.server-paged .train-v3-box-layer text{paint-order:stroke;stroke:#fff;stroke-width:3px;stroke-linejoin:round}
      .train-v3-picker.server-paged .train-v3-annotation-state.confirmed_empty{background:rgba(22,163,74,.88)}
      .train-v3-picker.server-paged .train-v3-annotation-state.unannotated{background:rgba(100,116,139,.88)}
      .train-v3-picker.server-paged .train-v3-card.blocked:after{
        content:'不可选';position:absolute;left:8px;top:8px;z-index:2;
        max-width:calc(100% - 48px);padding:4px 7px;border-radius:6px;
        background:rgba(15,23,42,.84);color:#fff;font-size:11px;line-height:1.4;
        overflow:hidden;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;
      }
      .train-v3-picker.server-paged .train-v3-card.blocked:hover:after,
      .train-v3-picker.server-paged .train-v3-card.blocked:focus-within:after{
        content:attr(data-block-reason);font-size:12px;
      }
      .train-v3-picker.server-paged .train-v3-loading{pointer-events:none;opacity:.65}
      @keyframes trainPickerShimmer{to{background-position:-220% 0}}

      /* Picker visual refinement: existing fields and handlers remain mounted. */
      .modal-card:has(.train-v3-picker.server-paged){
        width:min(1480px,calc(100vw - 48px))!important;
        max-width:1480px!important;
        height:min(calc(100dvh - 48px),880px)!important;
        max-height:calc(100dvh - 48px)!important;
        display:flex!important;flex-direction:column!important;overflow:hidden!important;
        border:1px solid #e1e8f2;
        border-radius:17px;
        box-shadow:0 30px 85px rgba(17,34,61,.19),0 5px 18px rgba(17,34,61,.05);
        animation:pickerDialogEnter .19s cubic-bezier(.2,.8,.2,1) both;
      }
      .modal-card:has(.train-v3-picker.server-paged)>.modal-head{
        flex:none;min-height:56px;height:56px;padding:0 24px;
        border-bottom:1px solid #e9edf4;background:#fff;
      }
      .modal-card:has(.train-v3-picker.server-paged)>.modal-head .modal-title{
        color:#1c304b;font-size:21px;font-weight:700;letter-spacing:-.35px;
      }
      .modal-card:has(.train-v3-picker.server-paged)>.modal-body{
        display:flex;flex:1;min-height:0;overflow:hidden!important;
        padding:0 24px!important;background:#fff;
      }
      .train-v3-picker.server-paged{
        display:flex!important;flex-direction:column!important;
        width:100%;height:100%;min-width:0;min-height:0;overflow:hidden;
        gap:0;color:#263a53;font-size:13px;
        --picker-accent:var(--primary,#2563eb);
        --picker-border:#e5ebf3;
        --picker-muted:#63748c;
      }
      .train-v3-picker.server-paged>header{
        display:flex;align-items:center;justify-content:flex-end;
        flex:none;min-height:32px;padding:5px 0;border-bottom:1px solid var(--picker-border);
      }
      .train-v3-picker.server-paged>header strong{
        color:#526b8a;font-size:12px;font-weight:600;white-space:nowrap;
      }
      .train-v3-picker.server-paged .train-v3-workspace{
        display:grid!important;
        grid-template-columns:274px minmax(0,1fr)!important;
        grid-template-rows:minmax(0,1fr);
        gap:0!important;min-height:0;flex:1;overflow:hidden;
      }
      .train-v3-picker.server-paged .train-v3-filters{
        grid-column:1;grid-row:1;
        display:flex;flex-direction:column;align-items:stretch;gap:15px;
        min-width:0;min-height:0;overflow-y:auto;overflow-x:hidden;
        padding:17px 17px 22px 0;margin:0 17px 0 0;
        border:0;border-right:1px solid var(--picker-border);
        overscroll-behavior:contain;scrollbar-gutter:stable;font-size:13px;
      }
      .train-v3-picker.server-paged .train-v3-sidebar-head{
        display:flex;align-items:center;justify-content:space-between;gap:12px;
        padding:0 0 12px;border-bottom:1px solid var(--picker-border);
      }
      .train-v3-picker.server-paged .train-v3-sidebar-head strong{
        color:#223a56;font-size:15px;font-weight:700;
      }
      .train-v3-picker.server-paged .train-v3-sidebar-head .btn{
        border:0;background:transparent;color:#416fd0;padding:3px 0;font-size:12px;
      }
      .train-v3-picker.server-paged .train-v3-mobile-toggle{display:none}
      .train-v3-picker.server-paged .train-v3-role-tools{
        display:flex;flex-direction:column;align-items:stretch;
        gap:6px;min-width:0;margin:0;padding:0;
      }
      .train-v3-picker.server-paged .train-v3-role-tools>label{
        color:#536981;font-size:12px;font-weight:550;
      }
      .train-v3-picker.server-paged .train-v3-role-tools #trV3RoleFilter{
        height:38px;min-width:0;width:100%;font-size:13px;
      }
      .train-v3-picker.server-paged .train-v3-filter{
        display:flex;flex-direction:column;align-items:stretch;
        gap:13px;min-width:0;
      }
      .train-v3-picker.server-paged .train-v3-filter>label,
      .train-v3-picker.server-paged .train-v3-label-group{
        display:flex;flex-direction:column;align-items:stretch;gap:6px;
        min-width:0;color:#536981;font-size:12px;font-weight:550;
      }
      .train-v3-picker.server-paged .train-v3-filter .input,
      .train-v3-picker.server-paged .train-v3-filter .select{
        width:100%;min-width:0;height:38px;
      }
      .train-v3-picker.server-paged .train-v3-label-group{
        padding-top:13px;border-top:1px solid var(--picker-border);
      }
      .train-v3-picker.server-paged .input,
      .train-v3-picker.server-paged .select{
        border:1px solid #dce4ef;border-radius:8px;background:#fff;
        color:#334861;font-size:13px;transition:border-color .16s ease,box-shadow .16s ease;
      }
      .train-v3-picker.server-paged .input:focus,
      .train-v3-picker.server-paged .select:focus{
        border-color:#83a9f4;outline:0;box-shadow:0 0 0 3px rgba(47,102,234,.1);
      }
      .train-v3-picker.server-paged #trV3Q{background:#fafbfd}
      .train-v3-picker.server-paged #trV3Chips{
        display:flex;flex-wrap:wrap;align-content:start;align-items:start;
        min-height:32px;max-height:202px;gap:7px;padding:3px 2px 3px 0;
        overflow-x:hidden;overflow-y:auto;scrollbar-width:thin;scrollbar-color:#d5e0f0 transparent;
      }
      .train-v3-picker.server-paged #trV3Chips .data426-chip{
        flex:0 1 auto;max-width:100%;min-height:30px;padding:4px 10px;
        border:1px solid #e2e9f3;border-radius:7px;background:#f8fafd;
        color:#586c86;font-size:12px;font-weight:500;white-space:nowrap;
        text-overflow:ellipsis;overflow:hidden;
        transition:background .15s ease,border-color .15s ease,color .15s ease;
      }
      .train-v3-picker.server-paged #trV3Chips .data426-chip.on{
        border-color:#a9c5f7;background:#eff5ff;color:#245fce;
      }
      .train-v3-picker.server-paged .train-v3-filters>#trV3ActiveFilters{
        display:flex;flex-wrap:wrap;gap:6px;
        min-height:0;margin:0;padding:0;color:#526b88;font-size:12px;
      }
      .train-v3-picker.server-paged .train-v3-filters>#trV3ActiveFilters:empty{
        display:none;
      }
      .train-v3-picker.server-paged .train-v3-filters>label{
        display:grid;align-content:start;gap:3px;min-width:0;margin:0;
        color:#526780;font-size:12px;font-weight:550;
      }
      .train-v3-picker.server-paged .train-v3-filters>label>.select{
        min-width:0;width:100%;height:34px;
      }
      .train-v3-picker.server-paged .train-v3-filters>label>.select[multiple]{
        min-height:55px;max-height:95px;overflow:auto;
      }
      .train-v3-picker.server-paged .train-v3-advanced{
        position:relative;align-self:stretch;margin:0;min-width:0;z-index:1;
      }
      .train-v3-picker.server-paged .train-v3-advanced>summary{
        display:flex;justify-content:space-between;align-items:center;
        min-height:38px;padding:0 11px;list-style:none;cursor:pointer;
        color:#365b97;font-size:13px;font-weight:600;
        border:1px solid #dce5f1;border-radius:8px;background:#fff;
        transition:border-color .16s ease,background .16s ease;
      }
      .train-v3-picker.server-paged .train-v3-advanced>summary::-webkit-details-marker{display:none}
      .train-v3-picker.server-paged .train-v3-advanced>summary:after{
        content:'⌄';color:#8396ad;font-size:17px;line-height:1;
        transition:transform .16s ease;
      }
      .train-v3-picker.server-paged .train-v3-advanced[open]>summary:after{transform:rotate(180deg)}
      .train-v3-picker.server-paged .train-v3-advanced[open]>summary{
        border-color:#bfd1f1;background:#f4f8ff;
      }
      .train-v3-picker.server-paged .train-v3-advanced-panel{
        display:flex;flex-direction:column;gap:12px;
        position:static;width:100%;max-height:none;
        margin-top:10px;padding:12px;overflow:visible;
        border:1px solid #e2eaf5;border-radius:9px;background:#fbfcff;
        box-shadow:none;
        animation:pickerFadeUp .16s ease both;
      }
      .train-v3-picker.server-paged .train-v3-advanced-panel>label{
        display:flex;flex-direction:column;gap:5px;min-width:0;
        color:#536b86;font-size:12px;
      }
      .train-v3-picker.server-paged .train-v3-advanced-panel>label>.input,
      .train-v3-picker.server-paged .train-v3-advanced-panel>label>.select{
        min-height:36px;width:100%;min-width:0;
      }
      .train-v3-picker.server-paged .train-v3-advanced-panel>.train-v3-history-note{
        margin:0;color:#5e728b;font-size:12px;line-height:1.5;
      }
      .train-v3-picker.server-paged .train-v3-advanced-panel>.btn{
        align-self:flex-start;margin:0;
      }
      .train-v3-picker.server-paged .train-v3-results{
        grid-column:2;grid-row:1;position:relative;
        display:grid!important;grid-template-columns:minmax(0,1fr) auto;
        grid-template-rows:auto auto minmax(0,1fr) auto;
        gap:0 10px;min-width:0;min-height:0;overflow:hidden;
        padding:0 0 0 2px;background:#fff;
      }
      .train-v3-picker.server-paged .train-v3-batch{
        grid-column:1;grid-row:1;display:flex;align-items:center;
        min-width:0;flex-wrap:wrap;gap:7px;margin:0;padding:10px 0 7px;
      }
      .train-v3-picker.server-paged .train-v3-view{
        grid-column:2;grid-row:1;display:flex;align-items:center;
        justify-content:flex-end;gap:6px;margin:0;padding:10px 0 7px;
      }
      .train-v3-picker.server-paged .train-v3-batch .btn,
      .train-v3-picker.server-paged .train-v3-view .btn{
        min-height:31px;padding:5px 10px;border:1px solid #dfe7f1;
        border-radius:7px;background:#fff;color:#526781;
        font-size:12px;font-weight:550;box-shadow:none;
        transition:background .15s ease,border-color .15s ease,color .15s ease;
      }
      .train-v3-picker.server-paged .train-v3-batch .btn:hover,
      .train-v3-picker.server-paged .train-v3-view .btn:hover{
        background:#f1f6ff;border-color:#b8cef3;color:#285dc4;
      }
      .train-v3-picker.server-paged .train-v3-page-meta{
        color:#63748a;font-size:12px;white-space:nowrap;
      }
      .train-v3-picker.server-paged .train-v3-more{position:relative;z-index:5}
      .train-v3-picker.server-paged .train-v3-more>summary{list-style:none}
      .train-v3-picker.server-paged .train-v3-more>summary::-webkit-details-marker{display:none}
      .train-v3-picker.server-paged .train-v3-more[open]{
        padding:0;border:0;background:transparent;
      }
      .train-v3-picker.server-paged .train-v3-more[open]>button{
        position:absolute;right:0;z-index:7;display:block;width:182px;
        min-height:35px;text-align:left;padding:8px 11px;
        border:1px solid #e3eaf3;background:#fff;border-radius:0;
        box-shadow:0 9px 22px rgba(27,49,85,.10);
      }
      .train-v3-picker.server-paged .train-v3-more[open]>button:nth-of-type(1){top:calc(100% + 6px);border-radius:8px 8px 0 0}
      .train-v3-picker.server-paged .train-v3-more[open]>button:nth-of-type(2){top:calc(100% + 40px)}
      .train-v3-picker.server-paged .train-v3-more[open]>button:nth-of-type(3){top:calc(100% + 74px)}
      .train-v3-picker.server-paged .train-v3-more[open]>button:nth-of-type(4){top:calc(100% + 108px);border-radius:0 0 8px 8px}
      .train-v3-picker.server-paged .train-v3-policy{
        grid-column:1/-1;grid-row:2;display:flex;align-items:center;flex-wrap:wrap;
        min-height:39px;gap:9px;margin:0;padding:0 0 7px;
        color:#566d87;font-size:12px;
      }
      .train-v3-picker.server-paged .train-v3-policy .select{
        width:auto;min-width:210px;height:32px;
      }
      .train-v3-picker.server-paged .train-v3-grid{
        grid-column:1/-1;grid-row:3;display:grid!important;
        grid-template-columns:repeat(4,minmax(0,1fr))!important;
        grid-auto-rows:max-content!important;align-content:start;align-items:start;
        gap:14px;min-height:0!important;max-height:none!important;
        overflow:auto!important;overscroll-behavior:contain;
        padding:3px 7px 10px 3px;
        scrollbar-gutter:stable;
      }
      .train-v3-picker.server-paged .train-v3-card{
        position:relative;overflow:hidden;
        align-self:start;display:flex!important;flex-direction:column;
        min-width:0;min-height:0;height:auto!important;padding:0 0 9px;
        border:1px solid #e3eaf3;border-radius:11px;background:#fff;
        box-shadow:0 2px 7px rgba(29,52,90,.035);
        transition:transform .16s ease,border-color .16s ease,box-shadow .16s ease;
      }
      .train-v3-picker.server-paged .train-v3-card:hover,
      .train-v3-picker.server-paged .train-v3-card:focus-within{
        border-color:#afc5ec;box-shadow:0 5px 15px rgba(22,53,111,.09);
        transform:translateY(-1px);
      }
      .train-v3-picker.server-paged .train-v3-card.on{
        border-color:#2c68e8;
        box-shadow:0 0 0 2px rgba(47,105,236,.14),0 5px 17px rgba(35,77,143,.10);
      }
      .train-v3-picker.server-paged .train-v3-card>input[type="checkbox"]{
        position:absolute;top:10px;right:10px;z-index:3;
        width:22px;height:22px;margin:0;
        accent-color:var(--picker-accent);
        filter:drop-shadow(0 1px 3px rgba(20,40,70,.22));
      }
      .train-v3-picker.server-paged .train-v3-preview{
        position:relative;flex:none;width:100%;aspect-ratio:4/3;
        border-radius:10px 10px 0 0;
        background:#e9eef5;overflow:hidden;
      }
      .train-v3-picker.server-paged .train-v3-card img{
        position:absolute;inset:0;display:block!important;
        width:100%!important;height:100%!important;min-height:0;
        aspect-ratio:4/3!important;border-radius:0;
        background:#e9eef5;object-fit:contain;
      }
      .train-v3-picker.server-paged .train-v3-annotation-state{
        position:absolute;display:block;z-index:2;min-height:0;
        left:9px;bottom:9px;padding:3px 7px;border-radius:5px;
        background:rgba(24,40,62,.86);color:#fff;
        font-size:11px;line-height:17px;font-weight:600;
      }
      .train-v3-picker.server-paged .train-v3-card>b{
        display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
        margin:9px 11px 0;padding:0;color:#253951;
        font-size:13px;font-weight:650;line-height:19px;
      }
      .train-v3-picker.server-paged .train-v3-card>span{
        display:block;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
        margin:5px 11px 0;padding:0;color:#667b95;
        font-size:12px;line-height:17px;min-height:0;
      }
      .train-v3-picker.server-paged .train-v3-card>.train-v3-label-list{white-space:normal;overflow:visible;
        text-overflow:clip;overflow-wrap:anywhere;
        margin-top:5px;padding:0;color:#4e6681;
        font-size:12px;line-height:1.4;min-height:0;
      }
      .train-v3-picker.server-paged .train-v3-card>.train-v3-sample-role{
        color:#285fc2;font-weight:600;white-space:normal;
      }
      .train-v3-picker.server-paged .train-v3-card>details{
        margin:8px 10px 0;padding:7px 0 0;
        border-top:1px solid #edf1f6;color:#5a708b;font-size:12px;
      }
      .train-v3-picker.server-paged .train-v3-card>details>summary{
        line-height:1.45;white-space:nowrap;text-overflow:ellipsis;overflow:hidden;
      }
      .train-v3-picker.server-paged .train-v3-card>details[open]>p{
        margin:6px 0;animation:pickerFadeUp .16s ease both;
      }
      .train-v3-picker.server-paged .train-v3-card>a,
      .train-v3-picker.server-paged .train-v3-card>button{
        align-self:flex-start;margin:7px 10px 0;padding:4px 9px;
        min-height:27px;border-color:#e0e8f3;border-radius:6px;
        background:#f8faff;color:#4d6f9c;font-size:12px;
      }
      .train-v3-picker.server-paged .train-v3-card.blocked{
        opacity:1;cursor:not-allowed;background:#fbfcfe;box-shadow:none;
      }
      .train-v3-picker.server-paged .train-v3-card.blocked:hover{
        transform:none;box-shadow:none;
      }
      .train-v3-picker.server-paged .train-v3-skeleton{
        height:230px;border:1px solid #e7edf5;border-radius:11px;
        background:linear-gradient(100deg,#edf2f8 18%,#f8fafc 42%,#edf2f8 68%);
        background-size:220% 100%;animation:trainPickerShimmer 1.35s ease-in-out infinite;
      }
      .train-v3-picker.server-paged #trV3Grid>.btn{
        grid-column:1/-1;justify-self:center;align-self:center;
        margin:35px 0;padding:12px 18px;
      }
      .train-v3-picker.server-paged #trV3Grid>.empty{
        grid-column:1/-1;min-width:0;margin:14px 0;
        border-radius:10px;color:#5c718d;font-size:13px;
      }
      .train-v3-picker.server-paged #trV3Pager{
        grid-column:1/-1;grid-row:4;min-height:0;padding:9px 0 7px;
      }
      .train-v3-picker.server-paged .train-v3-selected{
        position:relative;z-index:8;flex:none;min-width:0;min-height:0;
        margin:0;padding:0;border:0;background:transparent;
      }
      .train-v3-picker.server-paged .train-v3-selected>summary{
        display:flex;align-items:center;justify-content:space-between;gap:7px;
        min-height:31px;padding:4px 9px;border:1px solid #cbdaf1;border-radius:7px;
        background:#f5f8ff;color:#2859ba;font-size:12px;font-weight:650;
        list-style:none;cursor:pointer;
        transition:background .16s ease,border-color .16s ease;
      }
      .train-v3-picker.server-paged .train-v3-selected>summary::-webkit-details-marker{display:none}
      .train-v3-picker.server-paged .train-v3-selected>summary:hover,
      .train-v3-picker.server-paged .train-v3-selected[open]>summary{
        background:#ecf3ff;border-color:#a5c3f5;
      }
      .train-v3-picker.server-paged #trV3SelectedTotal{
        display:inline-grid;place-items:center;min-width:23px;height:23px;
        padding:0 6px;border-radius:6px;
        color:#fff;background:#2b64df;font-size:12px;font-weight:700;
      }
      .train-v3-picker.server-paged .train-v3-selected>div{
        position:absolute;top:calc(100% + 8px);right:0;z-index:10;
        width:min(345px,calc(100vw - 60px));max-height:min(62dvh,510px);
        min-height:0;overflow:auto;overscroll-behavior:contain;
        padding:16px;border:1px solid #dce5f2;border-radius:11px;
        background:#fff;box-shadow:0 14px 35px rgba(20,43,80,.16);
        animation:pickerFadeUp .17s ease both;
      }
      .train-v3-picker.server-paged .train-v3-selected>div>.input{
        width:100%;height:38px;
      }
      .train-v3-picker.server-paged #trV3SelectedSummary{
        margin:10px 0;padding:9px 10px;border:1px solid #e9effa;
        border-radius:8px;background:#f6f9ff;
        color:#5b7290;font-size:12px;line-height:1.5;
      }
      .train-v3-picker.server-paged .train-v3-selected-row{
        display:flex;align-items:center;justify-content:space-between;
        padding:9px 0;gap:8px;border-bottom:1px solid #f0f3f8;
      }
      .train-v3-picker.server-paged .train-v3-selected-row>span{
        min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;
        color:#435770;font-size:12px;
      }
      .train-v3-picker.server-paged .train-v3-selected-row .btn{
        flex:none;min-height:27px;padding:4px 8px;
        border-color:transparent;background:transparent;
        color:#637b97;font-size:12px;
      }
      .train-v3-picker.server-paged .train-v3-selected p{
        color:#5b7290;font-size:12px;line-height:1.5;
      }
      .train-v3-picker.server-paged #trV3SelectedList:empty:before{
        content:'尚未选择素材';display:block;padding:26px 8px;
        color:#657a95;font-size:12px;text-align:center;
      }
      .train-v3-picker.server-paged .train-v3-selected-row .btn:hover{
        border-color:#f7dbe0;background:#fff3f5;color:#b34053;
      }
      .train-v3-picker.server-paged .train-v3-footer{
        display:flex!important;flex:none;align-items:center;justify-content:flex-end;
        min-height:56px;gap:10px;margin:0;
        padding:8px 0;border-top:1px solid var(--picker-border);
        background:#fff;box-shadow:0 -5px 16px rgba(33,54,87,.025);
      }
      .train-v3-picker.server-paged .train-v3-footer>.btn{
        min-height:40px;min-width:88px;padding:8px 18px;
        border:1px solid #dce5f0;border-radius:8px;
        background:#fff;color:#486079;font-size:13px;font-weight:650;
        transition:background .16s ease,border-color .16s ease,box-shadow .16s ease,transform .12s ease;
      }
      .train-v3-picker.server-paged .train-v3-footer>.btn.primary{
        min-width:128px;background:#2c64e8;border-color:#2c64e8;
        color:white;box-shadow:0 4px 11px rgba(42,101,229,.18);
      }
      .train-v3-picker.server-paged .train-v3-footer>.btn.primary:hover{
        background:#2459d3;box-shadow:0 6px 16px rgba(42,101,229,.22);
      }
      .train-v3-picker.server-paged .train-v3-footer>.btn:active{
        transform:scale(.985);
      }
      .train-v3-picker.server-paged .btn:disabled,
      .train-v3-picker.server-paged .btn[aria-disabled="true"]{
        opacity:.55;cursor:not-allowed;box-shadow:none;transform:none;
      }
      .train-v3-picker.server-paged :is(button,input,select,summary,a):focus-visible{
        outline:2px solid rgba(37,99,235,.68);outline-offset:2px;
      }
      @keyframes pickerFadeUp{
        from{opacity:.7;transform:translateY(4px)}
        to{opacity:1;transform:translateY(0)}
      }
      @keyframes pickerDialogEnter{
        from{opacity:.85;transform:translateY(7px) scale(.988)}
        to{opacity:1;transform:translateY(0) scale(1)}
      }
      @media(max-width:1180px){
        .train-v3-picker.server-paged .train-v3-workspace{
          grid-template-columns:252px minmax(0,1fr)!important;
        }
        .train-v3-picker.server-paged .train-v3-grid{
          grid-template-columns:repeat(3,minmax(0,1fr))!important;
        }
      }
      @media(max-width:960px){
        .train-v3-picker.server-paged .train-v3-grid{
          grid-template-columns:repeat(2,minmax(0,1fr))!important;
        }
        .train-v3-picker.server-paged .train-v3-workspace{
          grid-template-columns:230px minmax(0,1fr)!important;
        }
        .train-v3-picker.server-paged .train-v3-filters{
          margin-right:12px;padding-right:12px;
        }
        .train-v3-picker.server-paged .train-v3-batch{
          gap:5px;
        }
      }
      @media(max-width:760px){
        .modal-card:has(.train-v3-picker.server-paged){
          width:calc(100vw - 16px)!important;height:calc(100dvh - 16px)!important;
          max-height:calc(100dvh - 16px)!important;border-radius:12px;
        }
        .modal-card:has(.train-v3-picker.server-paged)>.modal-head{
          min-height:52px;height:52px;padding:0 16px;
        }
        .modal-card:has(.train-v3-picker.server-paged)>.modal-body{
          padding:0 14px!important;
        }
        .train-v3-picker.server-paged>header{min-height:30px;padding:4px 0}
        .train-v3-picker.server-paged>header strong{font-size:12px;white-space:normal;text-align:right}
        .train-v3-picker.server-paged .train-v3-workspace{
          display:grid!important;grid-template-columns:minmax(0,1fr)!important;
          grid-template-rows:auto minmax(0,1fr);gap:0!important;
        }
        .train-v3-picker.server-paged .train-v3-filters{
          grid-column:1;grid-row:1;display:block;
          flex:none;max-height:none;overflow:visible;
          margin:0;padding:7px 0;border:0;border-bottom:1px solid var(--picker-border);
        }
        .train-v3-picker.server-paged .train-v3-sidebar-head{
          padding:0;border:0;
        }
        .train-v3-picker.server-paged .train-v3-sidebar-head .btn{display:none}
        .train-v3-picker.server-paged .train-v3-filters:not([open])>:not(.train-v3-mobile-toggle){display:none}
        .train-v3-picker.server-paged .train-v3-mobile-toggle{
          display:flex;align-items:center;justify-content:space-between;
          width:100%;padding:7px 2px;border:0;background:transparent;
          color:#2b4a72;font-size:13px;font-weight:650;cursor:pointer;
        }
        .train-v3-picker.server-paged .train-v3-mobile-toggle:after{
          content:'⌄';font-size:17px;transition:transform .16s ease;
        }
        .train-v3-picker.server-paged .train-v3-filters[open] .train-v3-mobile-toggle:after{
          transform:rotate(180deg);
        }
        .train-v3-picker.server-paged .train-v3-filters[open]{
          display:flex;gap:12px;max-height:45dvh;overflow-y:auto;
        }
        .train-v3-picker.server-paged .train-v3-filters[open] .train-v3-sidebar-head{
          display:flex;
        }
        .train-v3-picker.server-paged .train-v3-results{
          grid-column:1;grid-row:2;
          display:grid!important;grid-template-columns:minmax(0,1fr);
          grid-template-rows:auto auto auto minmax(0,1fr) auto;
          flex:1;min-height:0;padding:0;overflow:hidden;
        }
        .train-v3-picker.server-paged .train-v3-batch{
          grid-column:1;grid-row:1;flex-wrap:wrap;overflow:visible;
          max-width:100%;padding:7px 0 4px;white-space:normal;
        }
        .train-v3-picker.server-paged .train-v3-view{
          grid-column:1;grid-row:2;justify-content:flex-end;padding:4px 0;
        }
        .train-v3-picker.server-paged .train-v3-policy{
          grid-column:1;grid-row:3;min-height:38px;padding:0 0 6px;gap:5px;
        }
        .train-v3-picker.server-paged .train-v3-policy .select{
          height:32px;min-width:0;max-width:100%;
        }
        .train-v3-picker.server-paged .train-v3-grid{
          grid-column:1;grid-row:4;
          grid-template-columns:repeat(2,minmax(0,1fr))!important;
          gap:10px;min-height:0!important;
        }
        .train-v3-picker.server-paged .train-v3-selected>div{
          max-height:min(55dvh,430px);
        }
        .train-v3-picker.server-paged .train-v3-footer{
          min-height:56px;padding:8px 0;gap:8px;
        }
        .train-v3-picker.server-paged .train-v3-footer>.btn{
          min-height:40px;padding:7px 13px;
        }
        .train-v3-picker.server-paged #trV3Pager{
          grid-column:1;grid-row:5;
          max-height:76px;overflow:auto;
        }
        .train-v3-picker.server-paged #trV3Pager .platform-pagination{
          padding:6px;margin:0;box-shadow:none;
        }
        .train-v3-picker.server-paged .compact-list .train-v3-card{
          grid-template-columns:85px minmax(0,1fr);
        }
      }
      @media(max-width:420px){
        .train-v3-picker.server-paged .train-v3-grid{
          gap:8px;
        }
        .train-v3-picker.server-paged .train-v3-selected>summary{
          font-size:12px;padding:4px 6px;
        }
      }
      @media(prefers-reduced-motion:reduce){
        .modal-card:has(.train-v3-picker.server-paged){animation:none!important}
        .train-v3-picker.server-paged *,
        .train-v3-picker.server-paged *:before,
        .train-v3-picker.server-paged *:after{
          animation:none!important;transition:none!important;scroll-behavior:auto!important;
        }
        .train-v3-picker.server-paged .train-v3-card:hover,
        .train-v3-picker.server-paged .train-v3-card:focus-within,
        .train-v3-picker.server-paged .train-v3-footer>.btn:active{
          transform:none;
        }
      }
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
    const context=taskPayload();
    const requiresRoles=(picker?.role==='train'||picker?.role==='robustness') &&
      (uniqueIds(context.train_labels).length>0 || Boolean(context.base_version_id));
    return JSON.stringify({
      project: projectId(),
      filters: picker?.filters || {}, role:picker?.role, scope:picker?.scopeIds,
      task: {algorithm_asset_id:context.algorithm_asset_id || '',history_policy:context.history_policy || 'new_for_algorithm',
        ...(requiresRoles?{train_labels:uniqueIds(context.train_labels).sort(),base_version_id:context.base_version_id || '',
          model:context.model || '',framework:context.framework || ''}:{})},
      selectionRef:picker?.reference?.selection_ref || '',
      sampleRole: picker?.sampleRole || '',
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
    const context = taskPayload();
    const hasTaskLabels = uniqueIds(context.train_labels).length > 0 || Boolean(context.base_version_id);
    const chips = (state().labels || []).slice(0,40).map(row => (
      `<button class="data426-chip" data-label="${esc(row.code)}" onclick="toggleTrainMaterialLabelV3('${esc(row.code)}')">${esc(row.display_name || row.code)}</button>`
    )).join('');
    return `<div class="train-v3-picker server-paged">
      <header><strong id="trV3PickerCount" aria-live="polite">正在读取素材…</strong></header>
      <div class="train-v3-workspace"><aside class="train-v3-filters"><button type="button" class="train-v3-mobile-toggle" aria-expanded="false" onclick="TrainingMaterialPickerRuntime.toggleFilterSidebar()">筛选与标签</button><div class="train-v3-sidebar-head"><strong>筛选条件</strong><button type="button" class="btn mini" onclick="TrainingMaterialPickerRuntime.clearFilters()">清空筛选</button></div>${role === 'train' && hasTaskLabels ? `<section class="train-v3-role-tools"><label for="trV3RoleFilter">按训练目标筛选</label><select id="trV3RoleFilter" class="select" aria-label="按训练目标筛选素材" onchange="TrainingMaterialPickerRuntime.setSampleRole(this.value)"><option value="">全部素材</option><option value="positive">含本次目标</option><option value="confirmed_negative">已确认不含本次目标</option><option value="pending_negative">候选背景素材</option><option value="pending_review">标注需核验</option></select></section>` : ''}
      <div class="train-v3-filter"><label>搜索素材<input id="trV3Q" class="input" placeholder="搜索图片名称" oninput="trainMaterialSearchV3(this.value)"></label><label>排序方式<select id="trV3Sort" class="select" aria-label="按加入时间排序" onchange="trainMaterialSortV3(this.value)"><option value="newest">最新加入优先</option><option value="oldest">最早加入优先</option></select></label><div class="train-v3-label-group"><span>标签筛选</span><input class="input" placeholder="检索标签名称或编码" aria-label="检索标签" oninput="TrainingMaterialPickerRuntime.searchLabels(this.value)"><select class="select" aria-label="标签组合" onchange="TrainingMaterialPickerRuntime.setLabelMode(this.value)"><option value="any">包含任意标签</option><option value="all">同时包含全部标签</option></select><div id="trV3Chips" class="data426-chips"><button class="data426-chip clear on" data-label="" onclick="clearTrainMaterialLabelsV3()">全部标签</button>${chips}</div></div></div>
      <div id="trV3ActiveFilters" class="data426-chips" aria-live="polite"></div>
      ${role==='train'?`<label>素材范围<select class="select" data-filter-key="negativePoolOnly" aria-label="素材范围" onchange="TrainingMaterialPickerRuntime.setFilter('negativePoolOnly',this.value)"><option value="">普通素材（含负样本池）</option><option value="pool">负样本池</option></select></label><label>负样本分类<select class="select" multiple data-filter-key="negativeCategoryIds" aria-label="负样本分类筛选" id="trV3NegativeCategories" onfocus="TrainingMaterialPickerRuntime.loadNegativeCategories()" onchange="TrainingMaterialPickerRuntime.setFilter('negativeCategoryIds',[...this.selectedOptions].map(o=>o.value).join(','))"><option disabled>点击后读取分类…</option></select></label>`:''}
      <details class="train-v3-advanced"><summary>更多筛选</summary><div class="train-v3-advanced-panel"><label>存储来源<select class="select" multiple id="trV3StorageSources" aria-label="存储来源" onfocus="TrainingMaterialPickerRuntime.loadStorageSources()" onchange="TrainingMaterialPickerRuntime.setFilter('sourceIds',[...this.selectedOptions].map(o=>o.value).join(','))"><option disabled>点击读取存储来源…</option></select></label>
      <label>加入时间从<input type="date" class="input" data-filter-key="createdFrom" onchange="TrainingMaterialPickerRuntime.setFilter('createdFrom',this.value)"></label><label>至<input type="date" class="input" data-filter-key="createdTo" onchange="TrainingMaterialPickerRuntime.setFilter('createdTo',this.value)"></label>
      <label>正式标注<select class="select" data-filter-key="annotationState" onchange="TrainingMaterialPickerRuntime.setFilter('annotationState',this.value)"><option value="">全部状态</option><option value="annotated">已标注</option><option value="confirmed_empty">已确认无目标</option><option value="unannotated">未标注</option></select></label>
      <label>真实训练历史<select class="select" data-filter-key="usageState" onchange="TrainingMaterialPickerRuntime.setFilter('usageState',this.value)"><option value="">全部历史</option><option value="used">已使用</option><option value="possible">可能使用</option><option value="selected">仅选入</option><option value="eval_only">仅参与评测</option><option value="test_reserved">独立 Test 已保留</option><option value="unused">有据未使用</option><option value="unknown">未知</option></select></label>
      <label>算法训练范围<select class="select" data-filter-key="historyScope" onchange="TrainingMaterialPickerRuntime.setFilter('historyScope',this.value)"><option value="">所有算法范围</option><option value="current_only">当前算法训练（含共同使用）</option><option value="other_only">仅其他算法训练（已知证据）</option></select></label><p class="train-v3-history-note">历史未完整回填时，“仅”表示当前已知证据；未知素材不能据此证明独立。</p>
      </div></details></aside><main class="train-v3-results"><div class="train-v3-view"><button class="btn mini" onclick="TrainingMaterialPickerRuntime.setView('grid')">网格</button><button class="btn mini" onclick="TrainingMaterialPickerRuntime.setView('list')">紧凑列表</button><details class="train-v3-selected"><summary>本次已选 <span id="trV3SelectedTotal">0</span></summary><div><input class="input" aria-label="搜索已选素材" placeholder="搜索已选名称或ID" oninput="TrainingMaterialPickerRuntime.searchSelected(this.value)"><p id="trV3SelectedSummary"></p><div id="trV3SelectedList"></div></div></details></div>
      <div class="picker412-actions train-v3-batch"><button class="btn mini" data-picker-action="select-filtered" onclick="trainMaterialSelectV3('select-filtered')">全选当前筛选</button><details class="train-v3-more"><summary class="btn mini">更多</summary><button class="btn mini" data-picker-action="invert-filtered" onclick="trainMaterialSelectV3('invert-filtered')">反选当前筛选</button><button class="btn mini" data-picker-action="select-all" onclick="trainMaterialSelectV3('select-all')">全选全部可用素材</button><button class="btn mini" onclick="trainMaterialSelectV3('clear-all')">全部不选</button><button class="btn mini" data-picker-action="invert-all" onclick="trainMaterialSelectV3('invert-all')">反选全部</button></details><button class="btn mini" data-picker-action="select-page" onclick="trainMaterialSelectV3('select-page')">全选本页</button><span id="trV3PageMeta" class="train-v3-page-meta"></span></div>
      <label class="train-v3-policy">训练素材使用策略 <select class="select" onchange="TrainingMaterialPickerRuntime.setHistoryPolicy(this.value)"><option value="new_for_algorithm" ${taskPayload().history_policy==='new_for_algorithm'?'selected':''}>仅使用未训练素材</option><option value="include_history" ${taskPayload().history_policy==='include_history'?'selected':''}>允许复用历史训练素材</option></select></label>
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

  // Keep the modal's batch and confirm actions disabled until the current read settles.
  function syncPickerActions(owner = picker) {
    if (!owner || picker !== owner) return;
    const disabled = Boolean(owner.loading || owner.bulkPending || owner.reviewPending);
    const buttons = modalLayer?.querySelectorAll?.('[data-picker-action], [data-picker-confirm]')
      || document.querySelectorAll('[data-picker-action], [data-picker-confirm]');
    buttons.forEach(button => {
      button.disabled = disabled;
      button.classList.toggle('train-v3-loading', disabled);
    });
  }

  function renderSelectedList() {
    if (!picker) return;
    const records=new Map();
    for (const cached of pageCache.values()) for(const row of cached.items || []) records.set(String(row.id),row);
    for(const row of picker.items || [])records.set(String(row.id),row);
    const query=String(picker.selectedQuery || '').toLowerCase();
    if(picker.reference){
      const total=document.getElementById('trV3SelectedTotal');if(total)total.textContent=String(picker.reference.count);
      const list=document.getElementById('trV3SelectedList');if(list)list.textContent='已冻结筛选结果；正式GT与历史资格在准备任务中逐项复核。修改选择将解除冻结范围。';
      return;
    }
    const visible=[];let history=0, unknown=0, negative=0;
    for(const id of picker.selected){
      const row=records.get(id);
      if(!row?.training_usage?.state || row.training_usage.state==='unknown')unknown++;
      if(Number(row?.training_usage?.training_task_count || 0)>0)history++;
      if(row?.sample_role==='confirmed_negative')negative++;
      if(visible.length<100 && `${row?.filename || ''} ${id}`.toLowerCase().includes(query))visible.push({id,name:row?.filename || id});
    }
    const total=document.getElementById('trV3SelectedTotal');if(total)total.textContent=String(picker.selected.size);
    const summary=document.getElementById('trV3SelectedSummary');if(summary)summary.textContent=`历史复用 ${history} · 已知负样本 ${negative} · 待核验 ${unknown}（基于已加载证据）`;
    const list=document.getElementById('trV3SelectedList');
    if(list)list.innerHTML=visible.map(row=>`<div class="train-v3-selected-row"><span title="${esc(row.name)}">${esc(row.name)}</span><button type="button" class="btn mini" aria-label="移除 ${esc(row.name)}" onclick="TrainingMaterialPickerRuntime.removeSelected('${esc(row.id)}')">移除</button></div>`).join('')+(picker.selected.size>100?'<small>最多展示100项，可搜索定位</small>':'');
  }

  function updateCounts() {
    renderSelectedList();
    if (!picker) return;
    const count = document.getElementById('trV3PickerCount');
    if(picker.reference){if(count)count.textContent=`服务器已冻结 ${picker.reference.count} 张`;return;}
    if (count) count.textContent = picker.total === null
      ? `本页 ${picker.items.length} 张 · 总数按需统计 · 已选 ${picker.selected.size} 张`
      : `筛选结果 ${picker.total} 张 · 已选 ${picker.selected.size} 张`;
    const meta = document.getElementById('trV3PageMeta');
    if (meta) meta.textContent = `当前页 ${picker.items.length} 张 · 每页最多 ${picker.pageSize} 张`;
    const active = document.getElementById('trV3ActiveFilters');
    if (active) {
      const names={sourceIds:'来源',negativePoolOnly:'负样本池',negativeCategoryIds:'负样本分类',
        createdFrom:'起始日期',createdTo:'结束日期',annotationState:'标注',usageState:'历史状态',historyScope:'算法范围'};
      const entries=[...(picker.query?[['query',picker.query]]:[]),
        ...(picker.sampleRole?[['sampleRole',picker.sampleRole]]:[]),
        ...(picker.labels.size?[['labels',[...picker.labels].join('、')]]:[]),
        ...Object.entries(picker.filters).filter(([key,value])=>names[key] && (Array.isArray(value)?value.length:Boolean(value)))];
      active.innerHTML=entries.map(([key,value])=>`<button type="button" class="data426-chip on" onclick="TrainingMaterialPickerRuntime.removeFilter('${key}')" title="移除此筛选条件">${esc(names[key] || ({query:'名称',labels:'标签',sampleRole:'训练角色'}[key]))}：${esc(Array.isArray(value)?value.join('、'):value===true?'是':value)} ×</button>`).join('');
    }
  }

  function syncFilterControls() {
    if (!picker) return;
    const query=document.getElementById('trV3Q');if(query)query.value=picker.query;
    const role=document.getElementById('trV3RoleFilter');if(role)role.value=picker.sampleRole;
    document.querySelectorAll('#trV3Chips .data426-chip').forEach(button=>{
      button.classList.toggle('on',button.dataset.label?picker.labels.has(button.dataset.label):!picker.labels.size);
    });
    document.querySelectorAll('[data-filter-key]').forEach(input=>{
      const value=picker.filters[input.dataset.filterKey];
      if(input.multiple){const selected=new Set(uniqueIds(value));[...input.options].forEach(option=>{option.selected=selected.has(option.value);});}
      else input.value=input.dataset.filterKey==='negativePoolOnly'?(value?'pool':''):
        Array.isArray(value)?value.join(','):String(value || '');
    });
  }

  function removeFilter(key) {
    if(!picker || picker.reviewPending || picker.bulkPending)return;
    if(key==='query')picker.query='';
    else if(key==='sampleRole')picker.sampleRole='';
    else if(key==='labels')picker.labels.clear();
    else if(['sourceIds','negativeCategoryIds'].includes(key))picker.filters[key]=[];
    else if(key==='negativePoolOnly')picker.filters[key]=false;
    else if(Object.prototype.hasOwnProperty.call(picker.filters,key))picker.filters[key]='';
    syncFilterControls();
    return resetFiltersAndLoad();
  }

  function clearFilters() {
    if(!picker || picker.reviewPending || picker.bulkPending)return;
    picker.filters={};picker.query='';picker.labels.clear();picker.sampleRole='';
    syncFilterControls();
    return resetFiltersAndLoad();
  }

  function attachImageFallbacks() {
    document.querySelectorAll('#trV3Grid img[data-fallback]').forEach(image => {
      image.addEventListener('error', () => {
        image.src = IMAGE_PLACEHOLDER;
        const host=image.parentElement;
        if(!host || host.querySelector?.('[data-thumbnail-retry]'))return;
        const retry=document.createElement('button');
        retry.type='button';retry.className='btn mini';retry.dataset.thumbnailRetry='1';
        retry.textContent='缩略图失败 · 重试';
        retry.onclick=event=>{
          event.preventDefault();event.stopPropagation();retry.remove();
          image.dataset.thumbnailLoaded='0';attachImageFallbacks();loadThumbnail(image);
        };
        host.append(retry);
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
      totalPages: picker.total === null ? null : picker.totalPages,
      hasPrevious: picker.page > 1,
      hasNext: picker.hasNext,
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
    syncPickerActions();
    const grid = document.getElementById('trV3Grid');
    if (!grid) return;
    cancelViewportFrame();
    grid.scrollTop = 0;grid.classList.toggle('compact-list',picker.view==='list');
    const blocked = blockedIds(picker.role);
    grid.innerHTML = picker.items.map((row, index) => {
      const id = String(row.id || '');
      const selected = picker.reviewing ? picker.reviewSelected.has(id) : picker.reference ? Boolean(row.selection_member) : picker.selected.has(id);
      const crossRoleBlocked = blocked.has(id);
      const missingTestTruth = picker.role === 'test' && String(row.annotation_state || '') === 'unannotated';
      const historyBlocked = Boolean(row.training_usage?.excluded);
      const historyUnknown = picker.role === 'test' && row.training_usage?.state === 'unknown';
      const unavailable = crossRoleBlocked || missingTestTruth || historyBlocked || historyUnknown || (picker.reviewing && row.sample_role !== 'pending_negative');
      const blockReason = historyUnknown ? '历史训练证据尚未核实，不能确认独立 Test 资格' : historyBlocked
        ? (picker.role === 'test' ? '本算法历史训练或验证已接触该素材，不能用于独立 Test' :
          row.training_usage?.benchmark_protected ? '已保留为本算法独立 Test，不能用于训练' : '当前新素材策略不允许复用历史训练素材')
        : crossRoleBlocked ? '已用于另一素材集' : (missingTestTruth ? '试验集必须已标注' : '');
      const labelText = (row.labels || []).map(labelDisplay).filter(Boolean).join('、')
        || (String(row.annotation_state || '') === 'unannotated' ? '未标注' : '无标签');
      const loading = index < THUMBNAIL_EAGER_COUNT ? 'eager' : 'lazy';
      const priority = index < THUMBNAIL_EAGER_COUNT ? 'high' : 'low';
      return `<label class="train-v3-card ${selected ? 'on' : ''} ${unavailable ? 'blocked' : ''}" data-material-id="${esc(id)}" data-block-reason="${esc(blockReason)}" title="${unavailable ? esc(blockReason) : ''}">
        <input type="checkbox" ${selected ? 'checked' : ''} ${unavailable && !selected ? 'disabled' : ''} onchange="toggleTrainMaterialV3('${esc(id)}',this.checked,this)">
        ${renderTrainingMaterialPreview(row, {loading, priority})}
        <b title="${esc(row.filename || '')}">${esc(row.filename || id)}</b><span class="train-v3-label-list" title="${esc(labelText)}">${esc((row.labels || []).slice(0,3).map(labelDisplay).join('、') || labelText)}${(row.labels || []).length>3?` +${row.labels.length-3}`:''}</span>${historyBlocked ? `<small class="train-v3-history-blocked" title="${esc(blockReason)}">${esc(blockReason)}</small>` : ''}
        ${picker.role === 'train' && (picker.sampleRole || picker.reviewing) && picker.effectiveLabels?.length ? `<span class="train-v3-sample-role" data-sample-role="${esc(row.sample_role || '')}">${esc(({positive:'含本次目标',confirmed_negative:`已确认不含 ${(picker.effectiveLabels || []).join('、')}`,pending_negative:`尚需确认不含 ${(picker.effectiveLabels || []).join('、')}`,pending_review:({missing_annotation:'未标注',partial_review_scope:'所需目标范围尚未确认',invalid_annotation:'标注数据无效',annotation_needs_review:'标注或来源一致性需核验',material_unavailable:'素材来源不可用',stale_ground_truth:'标注内容与素材不一致'})[row.annotation_issue_type || row.sample_role_issue_type] || '标注异常，请核验原因'})[row.sample_role] || '')}</span>` : ''}
        <span>${esc(row.storage_source_id || '')} · ${esc((row.created_at || '').slice(0,10))}</span>
        <details onclick="event.stopPropagation()" ontoggle="if(this.open)TrainingMaterialPickerRuntime.loadHistory('${esc(id)}',this)"><summary>训练历史 · ${(!row.training_usage?.state || row.training_usage?.state==='unknown')?'历史未知':`当前算法已训练 ${Number(row.training_usage?.training_task_count || 0)} 次`} · ${esc(({used:'已使用',possible:'可能使用',selected:'仅已选入',eval_only:'仅参与评测',test_reserved:'独立 Test 已保留',unused:'有据未使用',unknown:'未知'})[row.training_usage?.state] || '未知')}</summary><p>${esc((row.training_usage?.task_ids || []).join('、') || '缺少完整执行证据，不能判定从未使用')}</p></details>
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
    const requestedPage = Math.max(1, Number(page ?? picker.page) || 1);
    const key = cacheKey(requestedPage);
    if (picker.loading && activePageKey === key && activeController?.signal?.aborted === false) return;
    const sequence = ++requestSequence;
    activeController?.abort?.();
    activeController = new AbortController();
    const controller=activeController;
    activePageKey = key;
    const current=()=>picker===owner && projectId()===pid && sequence===requestSequence && signature()===contextKey && Boolean(document.getElementById('trV3Grid'));
    picker.loading = true;
    syncPickerActions(owner);
    const cached = pageCache.get(key);
    if (cached) {
      try {
        const revision=await withRequestDeadline(async signal=>{const r=await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-materials/revision?algorithm_asset_id=${encodeURIComponent(taskPayload().algorithm_asset_id || '')}`,{signal});return readJson(r,'素材版本读取失败');},{signal:controller.signal,label:'素材版本读取'});
        if(!current())return;
        if(revisionKey(revision)!==cached.versionKey){pageCache.clear();activePageKey=null;return loadPage({page:requestedPage});}
      } catch(error) {if(current()){notify(error.code==='REQUEST_TIMEOUT'?'素材读取超时，请重试':error.message); const grid=document.getElementById('trV3Grid');if(grid)grid.innerHTML='<button class="btn" onclick="TrainingMaterialPickerRuntime.loadPage()">读取失败 · 重试</button>';}return;}
      finally {if(activeController===controller){activePageKey=null;owner.loading=false;syncPickerActions(owner);}}
      picker.effectiveLabels = cached.effective_label_codes || [];
      picker.roleCounts = cached.sample_role_counts || null;
      picker.items = cached.items;
      picker.total = cached.total == null ? null : Math.max(0, Number(cached.total));
      picker.page = Math.max(1, Number(cached.page || requestedPage));
      picker.hasNext = cached.has_next === true || (cached.total != null && picker.page < Number(cached.total_pages || 1));
      picker.totalPages = picker.total === null ? picker.page + Number(picker.hasNext) : Math.max(1, Number(cached.total_pages || 1));
      picker.repositoryRevision = cached.repository_revision ?? null;
      picker.annotationRevision = cached.annotation_revision ?? null;
      picker.usageRevision = cached.usage_revision ?? null;
      picker.negativePoolRevision = cached.negative_pool_revision ?? null;
      picker.negativeConfirmationRevision = cached.negative_confirmation_revision ?? null;
      picker.loading = false;
      syncPickerActions(owner);
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
        countMode: 'deferred',
        labelMode:picker.labelMode || 'any',
        query: picker.query,
        labels: [...picker.labels],
        sortOrder: picker.sortOrder,
        ...picker.filters, algorithmId:taskPayload().algorithm_asset_id,historyPolicy:taskPayload().history_policy,role:picker.role==='test'?'test':'train',
      });
      const context=taskPayload();
      const hasTaskLabels=uniqueIds(context.train_labels).length > 0 || Boolean(context.base_version_id);
      // Opening the picker only needs the page. Building a task-role index
      // across 200k materials is only justified after a role filter is chosen.
      const withRoles=(picker.role === 'train' || picker.role === 'robustness') && hasTaskLabels
        && Boolean(picker.sampleRole || picker.reviewing);
      const scoped=picker.role==='robustness';
      const body = await withRequestDeadline(async signal=>{
      const response = await fetchImpl(withRoles
        ? `/api/v62/projects/${encodeURIComponent(pid)}/training-materials/role-page`
        : scoped ? `/api/v62/projects/${encodeURIComponent(pid)}/training-materials/page` : `/api/v62/projects/${encodeURIComponent(pid)}/training-materials?${query}`, {
        signal,
        ...((withRoles || scoped) ? {method:'POST', body:JSON.stringify({...taskPayload(), ...filterPayload(), page:requestedPage,
          page_size:picker.pageSize, query:picker.query, labels:[...picker.labels], sort_order:picker.sortOrder, sample_role:picker.sampleRole,
          defer_role_counts:!picker.sampleRole, count_mode:'deferred'})} : {}),
        headers: {'Accept': 'application/json', 'Content-Type':'application/json'},
      });
      const data=await readJson(response, '训练素材读取失败，请重试');
      if(owner.reference){
        const selected=await readJson(await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-materials/selection-membership`,{
          signal,method:'POST',headers:{'Content-Type':'application/json'},
          body:JSON.stringify({...taskPayload(),role:picker.role,selection_ref:owner.reference.selection_ref,image_ids:data.items.map(r=>r.id)})}),'冻结选择核验失败');
        const members=new Set(selected.items);for(const row of data.items)row.selection_member=members.has(row.id);
      }
      return data;
      }, {signal:controller.signal,label:'训练素材读取'});
      if (!current()) return;
      picker.effectiveLabels = body.effective_label_codes || [];
      picker.roleCounts = body.sample_role_counts || null;
      picker.items = Array.isArray(body.items) ? body.items : [];
      picker.total = body.total == null ? null : Math.max(0, Number(body.total));
      picker.page = Math.max(1, Number(body.page || requestedPage));
      picker.pageSize = Math.max(1, Number(body.page_size || picker.pageSize));
      picker.hasNext = body.has_next === true || (body.total != null && picker.page < Number(body.total_pages || 1));
      picker.totalPages = picker.total === null ? picker.page + Number(picker.hasNext) : Math.max(1, Number(body.total_pages || 1));
      picker.repositoryRevision = body.repository_revision ?? null;
      picker.annotationRevision = body.annotation_revision ?? null;
      picker.usageRevision = body.usage_revision ?? null;
      picker.negativePoolRevision = body.negative_pool_revision ?? null;
      picker.negativeConfirmationRevision = body.negative_confirmation_revision ?? null;
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
      if(activeController===controller)activePageKey=null;
      if (current()) {
        picker.loading = false;
        syncPickerActions(owner);
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
    return {label_mode:picker?.labelMode || 'any',role:picker?.role==='test'?'test':'train',storage_source_ids:uniqueIds(f.sourceIds),annotation_state:f.annotationState || '',created_from:f.createdFrom || '',created_to:f.createdTo || '',usage_state:f.usageState || '',history_scope:f.historyScope || '',negative_pool_only:Boolean(f.negativePoolOnly),negative_category_ids:uniqueIds(f.negativeCategoryIds),
      ...(picker?.role==='robustness'?{image_ids:picker.scopeIds}:{} )};
  }

  async function resolveBulkSelection({allAvailable = false, preferReference = false} = {}) {
    const pid = projectId();
    if (!pid) throw new Error('当前项目不存在');
    return withRequestDeadline(async signal=>{
    const freezeReference=async()=>{
      // Reuse the existing frozen selection owner. Scope and request ID must
      // be identical whether the server cap triggered the fallback or this
      // dialog already knows the filtered count exceeds the fast-path cap.
      const referenceScope=allAvailable ? taskPayload() : {...taskPayload(),...filterPayload()};
      const requestKey=JSON.stringify({...referenceScope,query:allAvailable?'':picker.query,
        labels:allAvailable?[]:[...picker.labels],sample_role:allAvailable?'':picker.sampleRole,allAvailable});
      if(picker.referenceRequest?.key!==requestKey)picker.referenceRequest={key:requestKey,id:window.crypto.randomUUID()};
      const plan=await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-materials/selection-reference`,{
        signal,method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({...referenceScope,request_id:picker.referenceRequest.id,query:allAvailable?'':picker.query,
          labels:allAvailable?[]:[...picker.labels],sort_order:picker.sortOrder,sample_role:allAvailable?'':picker.sampleRole})});
      return {reference:await readJson(plan,'大范围素材选择冻结失败')};
    };
    if(preferReference && ((Number.isSafeInteger(picker?.total) && picker.total>2000)
      || (picker?.total == null && (picker?.hasNext === true || picker?.page > 1))))return freezeReference();
    const response = await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/training-materials/bulk-selection`, {
      signal,
      method: 'POST',
      headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
      body: JSON.stringify({
        ...taskPayload(), ...filterPayload(), sample_role: allAvailable ? '' : (picker?.sampleRole || ''),
        all_available: Boolean(allAvailable),
        prefer_reference_over: preferReference ? 2000 : 0,
        query: allAvailable ? '' : (picker?.query || ''),
        labels: allAvailable ? [] : [...(picker?.labels || [])],
        role: picker?.role === 'robustness' ? 'train' : (picker?.role || 'train'),
      }),
    });
    if(!response.ok && picker?.role==='train'){
      const error=await response.clone().json().catch(()=>({}));
      if(String(error.detail || '').includes('超过单次选择上限')){
        return freezeReference();
      }
    }
    const body = await readJson(response, '训练素材批量选择读取失败');
    return {ids:uniqueIds(body.items),revision:body.repository_revision,
      usageRevision:body.usage_revision,annotationRevision:body.annotation_revision,
      negativePoolRevision:body.negative_pool_revision,
      negativeConfirmationRevision:body.negative_confirmation_revision,
      total:Number(body.total || 0)};
    },{signal:picker?.bulkController?.signal,label:'素材批量选择'});
  }

  async function bulkAction(action) {
    if (!picker || picker.bulkPending || picker.reviewing) return;
    if (picker.loading) return notify('当前筛选结果尚未加载完成，请稍后重试选择');
    if(picker.reference && !['select-filtered','select-all','clear-all'].includes(action)){picker.reference=null;picker.selected.clear();notify('已解除服务器冻结范围，改为显式选择');}
    if (action === 'select-page') {
      picker.items.forEach(row=>{if(trainingMaterialSelectable(row,picker.role,blockedIds(picker.role)))picker.selected.add(String(row.id));});renderPage();return;
    }
    if (action === 'clear-all') {
      picker.reference=null;picker.selected.clear();
      renderPage();
      return;
    }
    const activePicker = picker, pid = projectId(), contextKey=signature();
    activePicker.bulkController?.abort();activePicker.bulkController=new AbortController();
    activePicker.bulkPending = true;
    syncPickerActions(activePicker);
    const count = document.getElementById('trV3PickerCount');
    if (count) count.textContent = '正在解析批量选择…';
    try {
      const result = await resolveBulkSelection({allAvailable: action === 'select-all' || action === 'invert-all',
        // A frozen filter cannot safely union earlier ad-hoc page selections.
        // Preserve those explicit IDs instead of silently dropping them.
        preferReference: picker.role === 'train' && picker.selected.size === 0 && ['select-filtered','select-all'].includes(action)});
      if (picker !== activePicker || projectId() !== pid || signature()!==contextKey) return;
      if(result.reference){
        if(!['select-filtered','select-all'].includes(action))return notify('大范围冻结选择不支持反选，请使用全选当前筛选');
        picker.reference=result.reference;picker.selected.clear();pageCache.clear();
        notify(`已在服务器冻结 ${result.reference.count} 张素材；调整已选内容将解除冻结选择`);
        updateCounts();return loadPage();
      }
      if(result.total!==result.ids.length ||
         (picker.repositoryRevision!==null && result.revision!==picker.repositoryRevision) ||
         (picker.annotationRevision!==null && result.annotationRevision!==picker.annotationRevision) ||
         (picker.usageRevision!==null && result.usageRevision!==picker.usageRevision) ||
         (picker.negativePoolRevision!==null && result.negativePoolRevision!==picker.negativePoolRevision) ||
         (picker.negativeConfirmationRevision!==null && result.negativeConfirmationRevision!==picker.negativeConfirmationRevision)){
        notify('素材版本或筛选结果已变化，请刷新当前页后重试批量选择');
        return;
      }
      const blocked = blockedIds(picker.role);
      const eligible = result.ids.filter(id => !blocked.has(id));
      if (action === 'select-filtered' || action === 'select-all') eligible.forEach(id => picker.selected.add(id));
      else if (action === 'invert-filtered' || action === 'invert-all') eligible.forEach(id => picker.selected.has(id) ? picker.selected.delete(id) : picker.selected.add(id));
      renderPage();
    } catch (error) {
      if (picker !== activePicker || projectId() !== pid || signature()!==contextKey) return;
      notify(error?.message || '批量选择失败');
      updateCounts();
    } finally {
      activePicker.bulkPending = false;
      syncPickerActions(activePicker);
    }
  }

  async function open(role) {
    const pid = projectId();
    if (!pid) return notify('当前项目不存在');
    cancelViewportFrame();
    activeController?.abort();activePageKey=null;picker?.bulkController?.abort();picker?.historyControllers?.forEach(c=>c.abort());++requestSequence;clearTimeout(searchTimer);
    injectStyles();
    if (typeof role === 'object') role=role.role;
    const currentDraft = draft();
    const scopeIds = uniqueIds(currentDraft.materialIds);
    const selectedRole = ['test','robustness'].includes(role) ? role : 'train';
    const initialIds = initialTrainingMaterialIds({
      role: selectedRole,
      materialIds: scopeIds,
      testMaterialIds: currentDraft.testMaterialIds,
      robustnessImageIds: currentDraft.robustness_policy?.selection?.image_ids,
      blocked: blockedIds(selectedRole),
    });
    picker = {
      reference:selectedRole!=='test' && currentDraft.trainSelectionRef?{selection_ref:currentDraft.trainSelectionRef,count:currentDraft.trainSelectionCount}:null,
      sampleRole:'', effectiveLabels:[], roleCounts:null, reviewing:false, reviewSelected:new Set(),
      role: selectedRole,
      filters:{}, view:'grid', historyControllers:new Set(), scopeIds,
      query: '', labels: new Set(), sortOrder: 'newest', selected: new Set(initialIds),
      pageSize: DEFAULT_PAGE_SIZE, page: 1, totalPages: 1,
      items: [], total: null, hasNext: false, loading: false, repositoryRevision: null,
      annotationRevision: null, usageRevision: null,
      negativePoolRevision: null, negativeConfirmationRevision: null,
    };
    state().trainMaterialPickerV3 = picker;
    const title = picker.role === 'robustness' ? '选择增强训练素材' : picker.role === 'train' ? '选择本次训练素材' : '选择独立试验素材';
    modalLayer=window.modal?.(title, modalHtml(picker.role), true);
    renderSkeleton();
    void loadPage({reset: true});
  }

  async function loadNegativeCategories() {
    if (!picker || picker.role !== 'train' || picker.negativeCategoriesLoading || picker.negativeCategoriesLoaded) return;
    const owner = picker, pid = projectId(), controller = new AbortController();
    owner.negativeCategoriesLoading = true;
    owner.historyControllers.add(controller);
    const select = document.getElementById('trV3NegativeCategories');
    if (select) select.innerHTML = '<option disabled>正在读取分类…</option>';
    try {
      const data = await withRequestDeadline(async signal => readJson(await fetchImpl(
        `/api/v61/projects/${encodeURIComponent(pid)}/negative-pool/categories`, {signal},
      ), '负样本分类读取失败'), {signal: controller.signal, label: '负样本分类'});
      if (picker !== owner || projectId() !== pid) return;
      owner.negativeCategoriesLoaded = true;
      const current = document.getElementById('trV3NegativeCategories');
      if (current) current.innerHTML = (data.items || []).filter(row => row.enabled !== false)
        .map(row => `<option value="${esc(row.id)}" ${(owner.filters.negativeCategoryIds || []).includes(row.id) ? 'selected' : ''}>${esc(row.name)}</option>`).join('') || '<option disabled>暂无负样本分类</option>';
    } catch (error) {
      if (picker !== owner || error?.name === 'AbortError') return;
      const current = document.getElementById('trV3NegativeCategories');
      if (current) current.innerHTML = '<option disabled>读取失败，重新点击重试</option>';
    } finally {
      owner.negativeCategoriesLoading = false;
      owner.historyControllers.delete(controller);
    }
  }

  function setSearch(value) {
    if (!picker || picker.reviewPending || picker.bulkPending) return;
    picker.query = String(value || '').trim();
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => resetFiltersAndLoad(), 220);
  }

  function setSortOrder(value) {
    if (!picker || picker.reviewPending || picker.bulkPending) return;
    picker.sortOrder = value === 'oldest' ? 'oldest' : 'newest';
    resetFiltersAndLoad();
  }

  function toggleLabel(code) {
    if (!picker || picker.reviewPending || picker.bulkPending) return;
    const value = String(code || '');
    picker.labels.has(value) ? picker.labels.delete(value) : picker.labels.add(value);
    document.querySelectorAll('#trV3Chips .data426-chip').forEach(button => {
      button.classList.toggle('on', button.dataset.label ? picker.labels.has(button.dataset.label) : !picker.labels.size);
    });
    resetFiltersAndLoad();
  }

  function clearLabels() {
    if (!picker || picker.reviewPending || picker.bulkPending) return;
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
      on && !trainingMaterialSelectable(row,picker.role,blockedIds(picker.role))
    ) {
      if (checkbox) checkbox.checked = false;
      return;
    }
    if(picker.reference){picker.reference=null;picker.selected.clear();notify('已解除服务器冻结选择，改为逐张选择');}
    on ? picker.selected.add(value) : picker.selected.delete(value);
    checkbox?.closest('.train-v3-card')?.classList.toggle('on', Boolean(on));
    updateCounts();
  }

  async function page(delta) {
    if (!picker || picker.loading || picker.reviewPending) return;
    const direction = Number(delta || 0);
    const targetPage = picker.page + Math.sign(direction);
    if (targetPage < 1 || (direction > 0 && !picker.hasNext) || targetPage > picker.totalPages) return;
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
    if (!picker || picker.loading || picker.bulkPending || picker.reviewPending) return false;
    if (picker.items.some(row=>picker.selected.has(String(row.id)) && !trainingMaterialSelectable(row,picker.role,blockedIds(picker.role)))) {
      notify('已选素材中包含当前策略不可用项，请取消这些选择或调整使用策略');return false;
    }
    const current = draft();
    if(picker.reference){trainingDraftRuntime.update({materialIds:[],trainSelectionRef:picker.reference.selection_ref,trainSelectionCount:picker.reference.count});window.closeModal?.();window.refreshTrainingMaterialSelectionUiV3?.();return true;}
    if(picker.role==='robustness'){
      const policy=current.robustness_policy || {};
      const scope = new Set(picker.scopeIds);
      trainingDraftRuntime.update({robustness_policy:{...policy,selection:{...(policy.selection || {}),mode:'manual',image_ids:[...picker.selected].filter(id=>scope.has(id))}}});
      window.closeModal?.();window.refreshTrainingMaterialSelectionUiV3?.();return true;
    }
    const patch = trainingMaterialSelectionPatch({
      role: picker.role,
      selectedIds: [...picker.selected],
      materialIds: current.materialIds || [],
      testMaterialIds: current.testMaterialIds || [],
    });
    trainingDraftRuntime.update({...patch,trainSelectionRef:'',trainSelectionCount:0});
    window.closeModal?.();
    window.refreshTrainingMaterialSelectionUiV3?.();
    return true;
  };

  const runtime = {
    build: 'training-material-picker-runtime-422616',
    open,
    searchSelected(value) {if(picker){picker.selectedQuery=String(value || '');renderSelectedList();}},
    removeSelected(id) {
      if(!picker || picker.bulkPending || picker.reviewPending)return;
      picker.selected.delete(String(id));
      const card=[...document.querySelectorAll('#trV3Grid [data-material-id]')].find(row=>row.dataset.materialId===String(id));
      if(card){card.classList.remove('on');const checkbox=card.querySelector('input');if(checkbox)checkbox.checked=false;}
      updateCounts();
    },
    async loadStorageSources() {
      const owner=picker;if(!owner)return;
      try{
        const rows=await window.loadStorageSources61?.() || window.getStorageSourcesSnapshot61?.() || [];
        if(picker!==owner)return;
        const control=document.getElementById('trV3StorageSources');
        if(control)control.innerHTML=rows.map(row=>`<option value="${esc(row.id)}" ${picker.filters.sourceIds?.includes(String(row.id))?'selected':''}>${esc(row.name || row.id)}</option>`).join('');
      }catch(error){if(picker===owner)notify('存储来源读取失败，请重试');}
    },
    setLabelMode(value) {
      if (!picker || picker.loading || picker.bulkPending) return;
      picker.labelMode=value==='all'?'all':'any';return resetFiltersAndLoad();
    },
    searchLabels(value) {
      if (!picker) return;
      const query=String(value || '').trim().toLowerCase();
      const matches=(state().labels || []).filter(row=>`${row.code} ${row.display_name || row.name || ''}`.toLowerCase().includes(query)).slice(0,40);
      const box=document.getElementById('trV3Chips');
      if(box) box.innerHTML=matches.map(row=>`<button class="data426-chip ${picker.labels.has(String(row.code))?'on':''}" data-label="${esc(row.code)}" onclick="toggleTrainMaterialLabelV3('${esc(row.code)}')">${esc(row.display_name || row.code)}</button>`).join('');
    },
    setHistoryPolicy(value) {
      if (!picker || picker.loading || picker.bulkPending || picker.reviewPending) return;
      if (!['new_for_algorithm','include_history'].includes(value)) return;
      if(picker.reference){picker.reference=null;picker.selected.clear();notify('使用策略变化，已解除旧的服务器冻结选择，请重新选择');}
      trainingDraftRuntime.update({history_policy:value});
      notify('使用策略已更新；已选素材保留，确认时将校验资格');
      return resetFiltersAndLoad();
    },
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
      activeController?.abort();activePageKey=null;picker.bulkController?.abort();picker.historyControllers?.forEach(c=>c.abort());++requestSequence;cancelViewportFrame();clearTimeout(searchTimer);picker=null;modalLayer=null;
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
      if(key==='negativePoolOnly' && picker.filters[key]) void loadNegativeCategories();
      return resetFiltersAndLoad();
    },
    loadNegativeCategories,
    removeFilter,
    clearFilters,
    toggleFilterSidebar() {
      const sidebar=modalLayer?.querySelector('.train-v3-filters');
      if(!sidebar)return;
      const expanded=sidebar.toggleAttribute('open');
      sidebar.querySelector('.train-v3-mobile-toggle')?.setAttribute('aria-expanded',String(expanded));
    },
    setView(value) {if(picker){picker.view=value==='list'?'list':'grid';renderPage();}},
    close() {activeController?.abort();activePageKey=null;picker?.bulkController?.abort();picker?.historyControllers?.forEach(c=>c.abort());++requestSequence;cancelViewportFrame();clearTimeout(searchTimer);picker=null;window.closeModal?.();},
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
        loading: Boolean(picker.loading),
        bulkPending: Boolean(picker.bulkPending),
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
