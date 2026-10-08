function uniqueIds(values) {
  return [...new Set((values || []).map(value => String(value || '').trim()).filter(Boolean))];
}

export function trainingMaterialSelectionSignature(ids = []) {
  return uniqueIds(ids).sort().join('\u0000');
}

function htmlEscape(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

export function trainingCompatibilitySignature(draft = {}) {
  return JSON.stringify({
    algorithmId: String(draft?.algorithmId || ''),
    materialIds: uniqueIds(draft?.materialIds).sort(),
    testMaterialIds: uniqueIds(draft?.testMaterialIds).sort(),
    splitMode: String(draft?.splitMode || 'random_test_from_training_pool'),
    labels: uniqueIds(draft?.newLabelCodes).sort(),
    model: String(draft?.config?.model || ''),
    experimentPercent: draft?.experimentPercent ?? null,
    validationPercent: draft?.validationPercent ?? null,
  });
}

export function excludeTrainingMaterialFromDraft(trainingDraftRuntime, draft, imageId) {
  const key = String(imageId || '').trim();
  if (!key || !trainingDraftRuntime?.update) return draft || null;
  return trainingDraftRuntime.update({
    materialIds: uniqueIds(draft?.materialIds).filter(id => id !== key),
    testMaterialIds: uniqueIds(draft?.testMaterialIds).filter(id => id !== key),
  });
}

function responseMessage(body, fallback) {
  if (typeof body?.detail === 'string') {
    try { return JSON.parse(body.detail)?.message || body.detail; } catch (_error) { return body.detail; }
  }
  if (typeof body?.detail?.message === 'string') return body.detail.message;
  return fallback;
}

async function readJson(response, fallback) {
  let body = null;
  try { body = await response.json(); } catch (_error) {}
  if (!response.ok) throw new Error(responseMessage(body, fallback));
  return body || {};
}

function setTextIfChanged(element, value) {
  if (!element) return false;
  const next = String(value ?? '');
  if (element.textContent === next) return false;
  element.textContent = next;
  return true;
}

export function installTrainingMaterialSummaryRuntime({
  getState,
  projectId,
  trainingDraftRuntime,
  notify = () => {},
  fetchImpl = (...args) => fetch(...args),
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingMaterialSummaryRuntimeInstalled) return window.TrainingMaterialSummaryRuntime;
  if (typeof getState !== 'function' || typeof projectId !== 'function' || !trainingDraftRuntime) {
    throw new Error('TrainingMaterialSummaryRuntime missing dependencies');
  }

  const state = () => getState() || {};
  let destroyed = false;
  let requestSequence = 0;
  let compatibilitySequence = 0;
  let activeController = null;
  let currentSignature = null;
  let pendingSignature = null;
  let summary = null;
  let lastError = '';
  let decorateQueued = false;
  let compatibilitySignature = null;
  let compatibilityPendingSignature = null;
  let compatibility = null;
  let compatibilityController = null;
  let compatibilityQuery = '';
  let compatibilityIssueType = '';
  let compatibilityCursor = '';
  let compatibilityLimit = 50;

  function currentIds() {
    return uniqueIds(trainingDraftRuntime.materialIds?.() || state().trainingDraft?.materialIds || []);
  }

  function currentDraft() {
    return state().trainingDraft || trainingDraftRuntime.current?.() || null;
  }

  function compatibilityPayload(draft = currentDraft(), overrides = {}) {
    return {
      algorithm_asset_id: String(draft?.algorithmId || ''),
      split_mode: String(draft?.splitMode || 'random_test_from_training_pool'),
      train_image_ids: uniqueIds(draft?.materialIds),
      test_image_ids: uniqueIds(draft?.testMaterialIds),
      train_labels: uniqueIds(draft?.newLabelCodes),
      model: String(draft?.config?.model || 'yolo11n.pt'),
      framework: String(draft?.config?.framework || 'ultralytics'),
      experiment_percent: draft?.experimentPercent ?? 20,
      validation_percent: draft?.validationPercent ?? 20,
      limit: 50,
      ...overrides,
    };
  }

  function compatibilityFor(draft = currentDraft()) {
    const signature = trainingCompatibilitySignature(draft || {});
    if (compatibilityPendingSignature === signature) {
      return {ready: false, loading: true, issue_count: null, signature};
    }
    if (compatibilitySignature !== signature || !compatibility) {
      return {ready: false, loading: false, issue_count: null, signature};
    }
    return {...compatibility, ready: true, loading: false, signature};
  }

  function labelDisplay(code) {
    const row = (state().labels || []).find(item => String(item?.code || '') === String(code));
    return String(row?.display_name || row?.display_name_zh || row?.name || code || '');
  }

  function summaryReadyFor(ids = currentIds()) {
    return currentSignature === trainingMaterialSelectionSignature(ids) && Boolean(summary) && !pendingSignature;
  }

  function summaryFor(ids = currentIds()) {
    return summaryReadyFor(ids) ? summary : null;
  }

  function selectedLabelCodes(ids = currentIds()) {
    return uniqueIds(summaryFor(ids)?.label_codes || []);
  }

  function decorateTrainingCreateUi() {
    if (destroyed || typeof document === 'undefined') return;
    const ids = currentIds();
    const ready = summaryReadyFor(ids);
    const labels = ready ? selectedLabelCodes(ids) : [];
    const labelElement = document.getElementById('tr429Labels');
    if (labelElement) {
      const baseLabels = labels.map(labelDisplay).filter(Boolean).join('、') || '无标签';
      const labelText = !ids.length ? '—' : ready
        ? `${baseLabels} · 可直接训练 ${summary.eligible_count} / 待标注 ${summary.pending_annotation_count}`
        : '读取中…';
      setTextIfChanged(labelElement, labelText);
    }

    const cards = document.querySelectorAll('.train-v3-summary > div');
    for (const card of cards) {
      const title = card.querySelector('span');
      const value = card.querySelector('b');
      if (title?.textContent?.trim() === '可选素材' && value) {
        const totalText = summary ? String(Math.max(0, Number(summary.selectable_total || 0))) : '…';
        setTextIfChanged(value, totalText);
        if (value.dataset.serverTruth !== 'training-material-summary') {
          value.dataset.serverTruth = 'training-material-summary';
        }
      }
    }
    const host = document.querySelector?.('.train429-data-summary');
    if (host) {
      let row = host.querySelector?.('[data-training-compatibility-summary]');
      if (!row) {
        row = document.createElement('div');
        row.dataset.trainingCompatibilitySummary = '1';
        host.appendChild(row);
      }
      const truth = compatibilityFor();
      const count = Number(truth.issue_count || 0);
      row.innerHTML = truth.loading || !truth.ready
        ? '<span>标签适配</span><b>检查中…</b>'
        : count
          ? `<span>标签适配</span><b class="warn">需补审 ${count} 张</b><button class="btn mini" type="button" data-training-compatibility-open>查看问题素材</button>`
          : '<span>标签适配</span><b>已通过</b>';
      row.querySelector?.('[data-training-compatibility-open]')?.addEventListener?.('click', () => openCompatibilityIssues());
    }
  }

  function queueDecorate() {
    if (destroyed || decorateQueued) return;
    decorateQueued = true;
    queueMicrotask(() => {
      decorateQueued = false;
      decorateTrainingCreateUi();
    });
  }

  async function refresh(ids = currentIds(), {force = false} = {}) {
    const normalizedIds = uniqueIds(ids);
    const signature = trainingMaterialSelectionSignature(normalizedIds);
    if (!force && currentSignature === signature && summary) {
      queueDecorate();
      return summary;
    }
    if (!force && pendingSignature === signature) return null;
    const pid = String(projectId() || '');
    if (!pid) {
      currentSignature = signature;
      pendingSignature = null;
      summary = null;
      queueDecorate();
      return null;
    }

    const sequence = ++requestSequence;
    activeController?.abort?.();
    activeController = new AbortController();
    pendingSignature = signature;
    lastError = '';
    queueDecorate();
    try {
      const response = await fetchImpl(
        `/api/v62/projects/${encodeURIComponent(pid)}/training-materials/selection-summary`,
        {
          method: 'POST',
          signal: activeController.signal,
          headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
          body: JSON.stringify({image_ids: normalizedIds}),
        },
      );
      const body = await readJson(response, '训练素材摘要读取失败');
      if (destroyed || sequence !== requestSequence) return null;
      currentSignature = signature;
      pendingSignature = null;
      summary = {
        requested_count: Math.max(0, Number(body.requested_count || 0)),
        matched_count: Math.max(0, Number(body.matched_count || 0)),
        selectable_count: Math.max(0, Number(body.selectable_count || 0)),
        eligible_count: Math.max(0, Number(body.eligible_count || 0)),
        pending_annotation_count: Math.max(0, Number(body.pending_annotation_count || 0)),
        selectable_total: Math.max(0, Number(body.selectable_total || 0)),
        eligible_total: Math.max(0, Number(body.eligible_total || 0)),
        pending_annotation_total: Math.max(0, Number(body.pending_annotation_total || 0)),
        box_count: Math.max(0, Number(body.box_count || 0)),
        size_bytes: Math.max(0, Number(body.size_bytes || 0)),
        label_codes: uniqueIds(body.label_codes),
        label_counts: body.label_counts && typeof body.label_counts === 'object' ? {...body.label_counts} : {},
        repository_revision: body.repository_revision ?? null,
      };
      queueDecorate();
      window.TrainingLabelRuntime?.queueRefresh?.();
      return summary;
    } catch (error) {
      if (error?.name === 'AbortError' || sequence !== requestSequence) return null;
      pendingSignature = null;
      lastError = String(error?.message || error || '训练素材摘要读取失败');
      queueDecorate();
      notify(lastError);
      return null;
    }
  }

  async function refreshCompatibility({force = false, payload = null, query = '', issueType = '', cursor = '', limit = 50} = {}) {
    const draft = currentDraft();
    const signature = trainingCompatibilitySignature(draft || {});
    if (!draft?.algorithmId || !uniqueIds(draft?.materialIds).length) {
      compatibilitySignature = signature;
      compatibilityPendingSignature = null;
      compatibility = {compatible: false, issue_count: 0, items: [], skipped: true};
      queueDecorate();
      return compatibility;
    }
    if (!force && compatibilitySignature === signature && compatibility) return compatibility;
    if (!force && compatibilityPendingSignature === signature) return null;
    const pid = String(projectId() || '');
    if (!pid) return null;
    const sequence = ++compatibilitySequence;
    compatibilityController?.abort?.();
    compatibilityController = new AbortController();
    compatibilityPendingSignature = signature;
    queueDecorate();
    try {
      const requestBody = payload ? {...payload} : compatibilityPayload(draft);
      Object.assign(requestBody, {query, issue_type: issueType, cursor, limit});
      const response = await fetchImpl(
        `/api/v62/projects/${encodeURIComponent(pid)}/training-materials/compatibility`,
        {
          method: 'POST',
          signal: compatibilityController.signal,
          headers: {'Accept': 'application/json', 'Content-Type': 'application/json'},
          body: JSON.stringify(requestBody),
        },
      );
      const body = await readJson(response, '训练标签适配检查失败');
      if (destroyed || sequence !== compatibilitySequence) return null;
      compatibilitySignature = signature;
      compatibilityPendingSignature = null;
      compatibility = {
        ...body,
        compatible: body.compatible === true,
        issue_count: Math.max(0, Number(body.issue_count || 0)),
        items: Array.isArray(body.items) ? body.items.map(item => ({...item})) : [],
      };
      compatibilityQuery = String(query || '');
      compatibilityIssueType = String(issueType || '');
      compatibilityCursor = String(cursor || '');
      compatibilityLimit = Math.max(1, Math.min(100, Number(limit || 50)));
      queueDecorate();
      window.TrainingSubmitRuntime?.updateReadiness?.();
      return compatibility;
    } catch (error) {
      if (error?.name === 'AbortError' || sequence !== compatibilitySequence) return null;
      compatibilityPendingSignature = null;
      compatibility = null;
      lastError = String(error?.message || error || '训练标签适配检查失败');
      queueDecorate();
      window.TrainingSubmitRuntime?.updateReadiness?.();
      notify(lastError);
      return null;
    }
  }

  function issueHtml(item) {
    const reviewed = uniqueIds(item?.annotation_scope).join('、') || '无';
    const required = uniqueIds(item?.required_label_codes).join('、') || '无';
    const missing = uniqueIds(item?.missing_label_codes).join('、') || '无';
    const imageId = String(item?.image_id || '');
    const preview = String(item?.thumbnail_url || item?.content_url || '');
    return `<article class="training-compatibility-item"><img src="${htmlEscape(preview)}" loading="lazy"><div><b>${htmlEscape(item?.filename || imageId)}</b><small>${htmlEscape(item?.dataset_name || item?.dataset_id || '-')} · ${htmlEscape(item?.annotation_state || '-')}</small><p>已审核：${htmlEscape(reviewed)}</p><p>本次要求：${htmlEscape(required)}</p><p class="warn">缺失：${htmlEscape(missing)}</p><div class="row"><button class="btn mini primary" onclick="TrainingMaterialSummaryRuntime.openReview('${htmlEscape(imageId)}')">去补审</button><button class="btn mini" onclick="TrainingMaterialSummaryRuntime.excludeFromDraft('${htmlEscape(imageId)}')">排除本次训练</button></div></div></article>`;
  }

  function openCompatibilityIssues() {
    const truth = compatibilityFor();
    if (!truth.ready) return void refreshCompatibility({force: true});
    const rows = truth.items || [];
    const issueTypes = Object.keys(truth.issue_counts || {});
    const offset = Math.max(0, Number(compatibilityCursor || 0));
    const html = `<div class="training-compatibility-list"><div class="alert warn"><b>${truth.issue_count} 张素材不适配本次训练</b><span>补审只记录你明确检查过的标签；AI 未检出不会自动确认不存在。</span></div><div class="row"><input id="trainingCompatibilityQuery" class="input" value="${htmlEscape(compatibilityQuery)}" placeholder="搜索文件名 / image_id"><select id="trainingCompatibilityType" class="select"><option value="">全部异常</option>${issueTypes.map(type=>`<option value="${htmlEscape(type)}" ${type===compatibilityIssueType?'selected':''}>${htmlEscape(type)} · ${Number(truth.issue_counts[type]||0)}</option>`).join('')}</select><button class="btn" type="button" onclick="TrainingMaterialSummaryRuntime.applyIssueFilters()">筛选</button></div><div class="item-sub">筛选结果 ${Number(truth.filtered_count||0)} 条 · 当前 ${rows.length?offset+1:0}-${offset+rows.length}</div>${rows.map(issueHtml).join('') || '<div class="empty">当前筛选没有问题素材</div>'}<div class="row between"><button class="btn mini" ${offset<=0?'disabled':''} onclick="TrainingMaterialSummaryRuntime.loadIssuePage('${Math.max(0,offset-compatibilityLimit)}')">上一页</button><button class="btn mini" ${truth.next_cursor==null?'disabled':''} onclick="TrainingMaterialSummaryRuntime.loadIssuePage('${htmlEscape(truth.next_cursor||'')}')">下一页</button></div></div>`;
    window.modal?.('训练标签适配问题', html, true);
  }

  async function loadIssuePage(cursor = '') {
    const result = await refreshCompatibility({
      force: true,
      query: compatibilityQuery,
      issueType: compatibilityIssueType,
      cursor,
      limit: compatibilityLimit,
    });
    if (result) openCompatibilityIssues();
    return result;
  }

  function applyIssueFilters() {
    compatibilityQuery = String(document.getElementById('trainingCompatibilityQuery')?.value || '').trim();
    compatibilityIssueType = String(document.getElementById('trainingCompatibilityType')?.value || '').trim();
    return loadIssuePage('');
  }

  async function openReview(imageId) {
    const item = (compatibility?.items || []).find(row => String(row?.image_id || '') === String(imageId));
    if (!item) return false;
    const s = state();
    if (!(s.images || []).some(row => String(row?.id || '') === String(imageId))) {
      s.images = [...(s.images || []), {
        id: String(imageId), filename: item.filename, dataset_id: item.dataset_id,
        url: item.content_url || item.thumbnail_url, content_sha256: item.content_sha256,
      }];
    }
    s.trainingAnnotationReviewContext = {
      imageId: String(imageId),
      requiredLabelCodes: uniqueIds(item.required_label_codes),
      missingLabelCodes: uniqueIds(item.missing_label_codes),
    };
    return window.openAnnotation?.(String(imageId));
  }

  function excludeFromDraft(imageId) {
    const next = excludeTrainingMaterialFromDraft(trainingDraftRuntime, currentDraft(), imageId);
    invalidateCompatibility();
    void refreshCompatibility({force: true});
    return next;
  }

  function invalidateCompatibility() {
    compatibilitySequence += 1;
    compatibilityController?.abort?.();
    compatibilityController = null;
    compatibilitySignature = null;
    compatibilityPendingSignature = null;
    compatibility = null;
    queueDecorate();
    window.TrainingSubmitRuntime?.updateReadiness?.();
  }

  function invalidate() {
    requestSequence += 1;
    activeController?.abort?.();
    activeController = null;
    currentSignature = null;
    pendingSignature = null;
    summary = null;
    lastError = '';
    invalidateCompatibility();
    queueDecorate();
    window.TrainingLabelRuntime?.queueRefresh?.();
  }

  function syncSelection() {
    const ids = currentIds();
    const signature = trainingMaterialSelectionSignature(ids);
    if (signature !== currentSignature && signature !== pendingSignature) void refresh(ids);
    else queueDecorate();
    const draft = currentDraft();
    const compatibilityKey = trainingCompatibilitySignature(draft || {});
    if (compatibilityKey !== compatibilitySignature && compatibilityKey !== compatibilityPendingSignature) {
      void refreshCompatibility();
    }
  }

  const unsubscribeDraft = trainingDraftRuntime.subscribe?.(() => syncSelection()) || (() => {});
  const observer = typeof MutationObserver !== 'undefined'
    ? new MutationObserver(() => queueDecorate())
    : null;
  observer?.observe(document.body, {childList: true, subtree: true});

  const runtime = {
    build: 'training-material-summary-runtime-422595',
    refresh,
    refreshCompatibility,
    invalidateCompatibility,
    compatibilityFor,
    openCompatibilityIssues,
    loadIssuePage,
    applyIssueFilters,
    openReview,
    excludeFromDraft,
    invalidate,
    summaryReadyFor,
    summaryFor,
    selectedLabelCodes,
    decorateTrainingCreateUi,
    state() {
      return {
        signature: currentSignature,
        pendingSignature,
        loading: Boolean(pendingSignature),
        selectableTotal: summary?.selectable_total ?? null,
        eligibleTotal: summary?.eligible_total ?? null,
        pendingAnnotation: summary?.pending_annotation_count ?? null,
        selectedLabels: summary?.label_codes?.length || 0,
        lastError,
        compatibility: compatibilityFor(),
        networkOwner: true,
        fullPoolHydration: false,
      };
    },
    destroy() {
      destroyed = true;
      activeController?.abort?.();
      compatibilityController?.abort?.();
      unsubscribeDraft();
      observer?.disconnect();
      if (window.TrainingMaterialSummaryRuntime === runtime) window.TrainingMaterialSummaryRuntime = null;
      window.__trainingMaterialSummaryRuntimeInstalled = false;
    },
  };

  window.TrainingMaterialSummaryRuntime = runtime;
  window.__trainingMaterialSummaryRuntimeInstalled = true;
  syncSelection();
  return runtime;
}
