function uniqueIds(values) {
  return [...new Set((values || []).map(value => String(value || '').trim()).filter(Boolean))];
}

export function trainingMaterialSelectionSignature(ids = []) {
  return uniqueIds(ids).sort().join('\u0000');
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
  let activeController = null;
  let currentSignature = null;
  let pendingSignature = null;
  let summary = null;
  let lastError = '';
  let decorateQueued = false;

  function currentIds() {
    return uniqueIds(trainingDraftRuntime.materialIds?.() || state().trainingDraft?.materialIds || []);
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
      const labelText = !ids.length ? '—' : ready
        ? (labels.map(labelDisplay).filter(Boolean).join('、') || '无标签')
        : '读取中…';
      setTextIfChanged(labelElement, labelText);
    }

    const cards = document.querySelectorAll('.train-v3-summary > div');
    for (const card of cards) {
      const title = card.querySelector('span');
      const value = card.querySelector('b');
      if (title?.textContent?.trim() === '可选素材' && value) {
        const totalText = summary ? String(Math.max(0, Number(summary.eligible_total || 0))) : '…';
        setTextIfChanged(value, totalText);
        if (value.dataset.serverTruth !== 'training-material-summary') {
          value.dataset.serverTruth = 'training-material-summary';
        }
      }
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
        eligible_count: Math.max(0, Number(body.eligible_count || 0)),
        eligible_total: Math.max(0, Number(body.eligible_total || 0)),
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

  function syncSelection() {
    const ids = currentIds();
    const signature = trainingMaterialSelectionSignature(ids);
    if (signature !== currentSignature && signature !== pendingSignature) void refresh(ids);
    else queueDecorate();
  }

  const unsubscribeDraft = trainingDraftRuntime.subscribe?.(() => syncSelection()) || (() => {});
  const observer = typeof MutationObserver !== 'undefined'
    ? new MutationObserver(() => queueDecorate())
    : null;
  observer?.observe(document.body, {childList: true, subtree: true});

  const runtime = {
    build: 'training-material-summary-runtime-422500',
    refresh,
    summaryReadyFor,
    summaryFor,
    selectedLabelCodes,
    decorateTrainingCreateUi,
    state() {
      return {
        signature: currentSignature,
        pendingSignature,
        loading: Boolean(pendingSignature),
        eligibleTotal: summary?.eligible_total ?? null,
        selectedLabels: summary?.label_codes?.length || 0,
        lastError,
        networkOwner: true,
        fullPoolHydration: false,
      };
    },
    destroy() {
      destroyed = true;
      activeController?.abort?.();
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
