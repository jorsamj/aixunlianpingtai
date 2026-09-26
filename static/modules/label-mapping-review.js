export const LABEL_MAPPING_REVIEW_PAGE_SIZE = 50;

function text(value) {
  return String(value ?? '').trim();
}

function positiveInt(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? Math.floor(number) : 0;
}

function normalizeClasses(classes) {
  const seen = new Set();
  const rows = [];
  for (const item of classes || []) {
    if (!item || typeof item !== 'object') continue;
    const classId = text(item.class_id ?? item.classId);
    if (!classId || seen.has(classId)) continue;
    seen.add(classId);
    rows.push({
      classId,
      name: text(item.name),
      imageCount: positiveInt(item.image_count ?? item.imageCount),
      boxCount: positiveInt(item.box_count ?? item.boxCount),
    });
  }
  return rows;
}

export function createLabelMappingReview(classes, {pageSize = LABEL_MAPPING_REVIEW_PAGE_SIZE, mapping = {}} = {}) {
  const rows = normalizeClasses(classes);
  const allowed = new Set(rows.map(row => row.classId));
  const nextMapping = {};
  for (const [classId, code] of Object.entries(mapping || {})) {
    if (allowed.has(String(classId)) && text(code)) nextMapping[String(classId)] = text(code);
  }
  return {
    rows,
    mapping: nextMapping,
    selected: {},
    query: '',
    targetQuery: '',
    page: 1,
    pageSize: Math.max(10, Math.min(100, positiveInt(pageSize) || LABEL_MAPPING_REVIEW_PAGE_SIZE)),
  };
}

export function reconcileLabelMappingReview(review, classes) {
  const next = createLabelMappingReview(classes, {
    pageSize: review?.pageSize,
    mapping: review?.mapping,
  });
  next.query = text(review?.query);
  next.targetQuery = text(review?.targetQuery);
  const allowed = new Set(next.rows.map(row => row.classId));
  for (const [classId, selected] of Object.entries(review?.selected || {})) {
    if (selected && allowed.has(String(classId))) next.selected[String(classId)] = true;
  }
  const pageCount = Math.max(1, Math.ceil(filteredRows(next).length / next.pageSize));
  next.page = Math.max(1, Math.min(pageCount, positiveInt(review?.page) || 1));
  return next;
}

function filteredRows(review) {
  const query = text(review?.query).toLowerCase();
  if (!query) return [...(review?.rows || [])];
  return (review?.rows || []).filter(row =>
    row.classId.toLowerCase().includes(query)
    || row.name.toLowerCase().includes(query)
  );
}

export function setLabelMappingReviewSearch(review, query) {
  review.query = text(query);
  review.page = 1;
  return review;
}

export function setLabelMappingTargetSearch(review, query) {
  review.targetQuery = text(query);
  return review;
}

export function setLabelMappingReviewPage(review, page) {
  const pageCount = Math.max(1, Math.ceil(filteredRows(review).length / review.pageSize));
  review.page = Math.max(1, Math.min(pageCount, positiveInt(page) || 1));
  return review;
}

export function setLabelMapping(review, classId, code) {
  const id = text(classId);
  if (!(review?.rows || []).some(row => row.classId === id)) throw new Error('外部标签不存在或已变化');
  const target = text(code);
  if (target) review.mapping[id] = target;
  else delete review.mapping[id];
  return review;
}

export function setLabelMappingSelected(review, classId, selected) {
  const id = text(classId);
  if (!(review?.rows || []).some(row => row.classId === id)) return review;
  if (selected) review.selected[id] = true;
  else delete review.selected[id];
  return review;
}

export function bulkSetLabelMapping(review, code) {
  const target = text(code);
  if (!target) throw new Error('请选择批量映射的目标平台标签');
  const selectedIds = Object.entries(review?.selected || {})
    .filter(([, selected]) => Boolean(selected))
    .map(([classId]) => classId);
  if (!selectedIds.length) throw new Error('请先勾选要批量映射的外部标签');
  for (const classId of selectedIds) review.mapping[classId] = target;
  review.selected = {};
  return review;
}

export function labelMappingReviewPage(review) {
  const rows = filteredRows(review);
  const pageCount = Math.max(1, Math.ceil(rows.length / review.pageSize));
  const page = Math.max(1, Math.min(pageCount, positiveInt(review.page) || 1));
  review.page = page;
  const start = (page - 1) * review.pageSize;
  return {
    rows: rows.slice(start, start + review.pageSize).map(row => ({
      ...row,
      code: text(review.mapping[row.classId]),
      selected: Boolean(review.selected[row.classId]),
    })),
    total: review.rows.length,
    filtered: rows.length,
    page,
    pageCount,
    pageSize: review.pageSize,
  };
}

export function labelMappingReviewSummary(review) {
  const targetCounts = {};
  let mapped = 0;
  let images = 0;
  let boxes = 0;
  for (const row of review?.rows || []) {
    images += row.imageCount;
    boxes += row.boxCount;
    const code = text(review.mapping?.[row.classId]);
    if (!code) continue;
    mapped += 1;
    targetCounts[code] = (targetCounts[code] || 0) + 1;
  }
  return {
    total: (review?.rows || []).length,
    mapped,
    unmapped: Math.max(0, (review?.rows || []).length - mapped),
    selected: Object.values(review?.selected || {}).filter(Boolean).length,
    images,
    boxes,
    targetCounts,
  };
}

export function buildManualLabelMapping(review) {
  const summary = labelMappingReviewSummary(review);
  if (summary.unmapped) throw new Error('还有 ' + summary.unmapped + ' 个外部标签未映射，请全部人工确认后再提交');
  return Object.fromEntries((review?.rows || []).map(row => [row.classId, text(review.mapping[row.classId])]));
}

export function filterCanonicalLabels(labels, query = '', keepCodes = []) {
  const keep = new Set((keepCodes || []).map(text).filter(Boolean));
  const needle = text(query).toLowerCase();
  const seen = new Set();
  const normalized = [];
  for (const raw of labels || []) {
    const row = typeof raw === 'string' ? {code: raw, display_name: raw} : (raw || {});
    const code = text(row.code);
    if (!code || seen.has(code)) continue;
    if (String(row.status || 'active').toLowerCase() !== 'active') continue;
    seen.add(code);
    normalized.push({...row, code});
  }
  if (!needle) return normalized;
  return normalized.filter(row => {
    if (keep.has(row.code)) return true;
    const aliases = Array.isArray(row.aliases) ? row.aliases.join(' ') : '';
    return [row.code, row.display_name, row.display_name_zh, aliases]
      .some(value => String(value || '').toLowerCase().includes(needle));
  });
}


export function labelSampleOverlay(bbox) {
  const number = value => Number.isFinite(Number(value)) ? Number(value) : 0;
  const cx = number(bbox?.cx), cy = number(bbox?.cy);
  const w = Math.max(0, number(bbox?.w)), h = Math.max(0, number(bbox?.h));
  const x1 = Math.max(0, Math.min(1, cx - w / 2));
  const y1 = Math.max(0, Math.min(1, cy - h / 2));
  const x2 = Math.max(x1, Math.min(1, cx + w / 2));
  const y2 = Math.max(y1, Math.min(1, cy + h / 2));
  const percent = value => Math.round(value * 1000000) / 10000;
  return {
    left: percent(x1),
    top: percent(y1),
    width: percent(x2 - x1),
    height: percent(y2 - y1),
  };
}
