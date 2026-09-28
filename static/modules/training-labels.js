function unique(values) {
  return [...new Set((values || []).map(value => String(value || '').trim()).filter(Boolean))];
}

function esc(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
}

export function selectedMaterialLabelCodes(materials, selectedIds, labelCatalog = []) {
  const wanted = new Set(unique(selectedIds));
  const seen = new Set();
  const encountered = [];
  for (const row of materials || []) {
    if (!wanted.has(String(row?.id || ''))) continue;
    for (const value of row?.labels || []) {
      const code = String(value || '').trim();
      if (code && !seen.has(code)) {
        seen.add(code);
        encountered.push(code);
      }
    }
  }
  const rank = new Map((labelCatalog || []).map((item, index) => [String(item?.code || ''), index]));
  return encountered.sort((left, right) => {
    const a = rank.has(left) ? rank.get(left) : Number.MAX_SAFE_INTEGER;
    const b = rank.has(right) ? rank.get(right) : Number.MAX_SAFE_INTEGER;
    return a - b || left.localeCompare(right);
  });
}

function sortedAvailableCodes(values, labelCatalog = []) {
  const rank = new Map((labelCatalog || []).map((item, index) => [String(item?.code || ''), index]));
  return unique(values).sort((left, right) => {
    const a = rank.has(left) ? rank.get(left) : Number.MAX_SAFE_INTEGER;
    const b = rank.has(right) ? rank.get(right) : Number.MAX_SAFE_INTEGER;
    return a - b || left.localeCompare(right);
  });
}

export function resolveClientTrainingLabels({
  materials,
  selectedIds,
  labelCatalog,
  requestedCodes,
  availableCodes = null,
}) {
  const available = availableCodes === null
    ? selectedMaterialLabelCodes(materials, selectedIds, labelCatalog)
    : sortedAvailableCodes(availableCodes, labelCatalog);
  const activeCatalog = new Set((labelCatalog || [])
    .filter(item => (
      item?.code
      && item?.active !== false
      && String(item?.status || 'active').toLowerCase() === 'active'
    ))
    .map(item => String(item.code)));
  const selectable = available.filter(code => activeCatalog.has(code));
  const selectableSet = new Set(selectable);
  const requested = unique(requestedCodes).filter(code => selectableSet.has(code));
  const invalidAvailable = available.filter(code => !activeCatalog.has(code));
  return {available, selectable, requested, invalidAvailable};
}

export function selectedTrainingMaterialIds(state) {
  return unique(state?.trainingDraft?.materialIds || []);
}

function selectedIds(state) {
  return selectedTrainingMaterialIds(state);
}

function algorithmIdFor(state) {
  return String(state?.trainingDraft?.algorithmId || '').trim();
}

function displayName(state, code) {
  const item = (state?.labels || []).find(label => String(label?.code || '') === String(code));
  return item?.display_name || item?.display_name_zh || item?.name || code;
}

function canonicalSelectedCodes(state) {
  return unique(state?.trainingDraft?.newLabelCodes || []);
}

function selectionForState(state, algorithmId, selectable) {
  const available = new Set(selectable);
  if (state.trainingLabelAlgorithmId !== algorithmId) {
    state.trainingLabelAlgorithmId = algorithmId;
    return [];
  }
  return canonicalSelectedCodes(state).filter(code => available.has(code));
}

function resetTaskLabelInteraction(state) {
  if (!state) return;
  state.trainingLabelAlgorithmId = '';
}

function startsTrainingSession(patch) {
  if (!patch || typeof patch !== 'object') return false;
  return Object.hasOwn(patch, 'algorithmId')
    && Array.isArray(patch.materialIds) && patch.materialIds.length === 0
    && Array.isArray(patch.testMaterialIds) && patch.testMaterialIds.length === 0
    && Array.isArray(patch.newLabelCodes) && patch.newLabelCodes.length === 0;
}

function labelOnlyDraftUpdate(event) {
  if (event?.type !== 'update' || !event.patch || typeof event.patch !== 'object') return false;
  const keys = Object.keys(event.patch);
  return keys.length === 1 && keys[0] === 'newLabelCodes';
}

function currentHost() {
  const v3Summary = document.querySelector('.train429-create .train-v3-summary')
    || document.querySelector('.train-v3-summary');
  if (v3Summary) {
    return {host: v3Summary.closest('.train428-panel') || v3Summary.parentElement, anchor: v3Summary, mode: 'v3'};
  }
  const summary429 = document.querySelector('.train429-create .train429-data-summary');
  if (summary429) {
    return {host: summary429.closest('.train428-panel') || summary429.parentElement, anchor: summary429, mode: 'v429'};
  }
  return null;
}

function ensurePanelStyle() {
  if (document.getElementById('trainingLabelContractStyle')) return;
  const style = document.createElement('style');
  style.id = 'trainingLabelContractStyle';
  style.textContent = `
    .training-label-contract{margin:11px 0 2px;padding:12px;border:1px solid #dfe7f2;border-radius:11px;background:#f8faff}
    .training-label-contract-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
    .training-label-contract-head b{font-size:11px;color:#263b5f}
    .training-label-contract-head small{display:block;margin-top:3px;color:#77869b;font-size:9px;line-height:1.5}
    .training-label-contract-count{min-width:58px;text-align:center;padding:5px 8px;border-radius:9px;background:#eaf1ff;color:#315fc2;font-weight:900;font-size:10px}
    .training-label-contract-list{display:flex;gap:6px;flex-wrap:wrap;margin-top:10px}
    .training-label-choice{display:inline-flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid #dce5f2;border-radius:9px;background:#fff;cursor:pointer;min-width:96px}
    .training-label-choice:has(input:checked){border-color:#6c8ee0;background:#edf3ff;color:#244fae}.training-label-choice input{margin:0}
    .training-label-choice span{display:flex;flex-direction:column;line-height:1.2}.training-label-choice b{font-size:10px}.training-label-choice small{font-size:8px;color:#8491a4;margin-top:2px}
    .training-label-empty{font-size:9px;color:#8a96a8}.training-label-warning{margin-top:8px;font-size:9px;color:#b42318;line-height:1.5}
  `;
  document.head.appendChild(style);
}

export function installTrainingLabelRuntime({getState, notify, trainingDraftRuntime, materialSummaryRuntime} = {}) {
  if (window.__trainingLabelRuntimeInstalled) return window.TrainingLabelRuntime || null;
  window.__trainingLabelRuntimeInstalled = true;
  ensurePanelStyle();

  let destroyed = false;
  let refreshQueued = false;

  const syncDraftLabels = (state, codes) => {
    if (!trainingDraftRuntime?.update) return;
    try { trainingDraftRuntime.update({newLabelCodes: unique(codes)}); }
    catch (error) { notify?.(error?.message || error); }
  };

  const availableCodesFor = (state, ids) => {
    if (!ids.length) return [];
    if (!materialSummaryRuntime) return selectedMaterialLabelCodes(state.images || [], ids, state.labels || []);
    if (!materialSummaryRuntime.summaryReadyFor?.(ids)) {
      void materialSummaryRuntime.refresh?.(ids);
      return null;
    }
    return materialSummaryRuntime.selectedLabelCodes?.(ids) || [];
  };

  const resolveFor = (state, ids, requestedCodes, availableCodes) => resolveClientTrainingLabels({
    materials: state.images || [],
    selectedIds: ids,
    labelCatalog: state.labels || [],
    requestedCodes,
    availableCodes,
  });

  const updateCount = state => {
    const count = document.querySelector('#trainingLabelContractPanel .training-label-contract-count');
    if (!count) return;
    const ids = selectedIds(state);
    const availableCodes = availableCodesFor(state, ids);
    if (availableCodes === null) {
      count.textContent = '读取中';
      return;
    }
    const view = resolveFor(state, ids, canonicalSelectedCodes(state), availableCodes);
    count.textContent = `已选 ${view.requested.length}`;
  };

  const refresh = () => {
    if (destroyed) return false;
    const state = getState?.();
    if (!state) return false;
    const placement = currentHost();
    const algorithmId = algorithmIdFor(state);
    if (!placement?.host || !algorithmId) return false;

    const ids = selectedIds(state);
    const draftRequested = canonicalSelectedCodes(state);
    const availableCodes = availableCodesFor(state, ids);
    let panel = document.getElementById('trainingLabelContractPanel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'trainingLabelContractPanel';
      panel.className = 'training-label-contract';
      placement.anchor.insertAdjacentElement('afterend', panel);
    }

    if (availableCodes === null) {
      panel.innerHTML = `
        <div class="training-label-contract-head"><div><b>训练标签</b><small>正在读取当前已选素材的真实标签。</small></div><span class="training-label-contract-count">读取中</span></div>
        <div class="training-label-contract-list"><span class="training-label-empty">正在读取素材标签…</span></div>`;
      return true;
    }

    const initial = resolveFor(state, ids, draftRequested, availableCodes);
    const selectedCodes = selectionForState(state, algorithmId, initial.selectable);
    if (selectedCodes.join('\u0000') !== draftRequested.join('\u0000')) syncDraftLabels(state, selectedCodes);
    const view = resolveFor(state, ids, selectedCodes, availableCodes);
    const selectedSet = new Set(view.requested);
    const selectableHtml = view.selectable.length
      ? view.selectable.map(code => {
          const checked = selectedSet.has(code) ? 'checked' : '';
          return `<label class="training-label-choice"><input type="checkbox" data-training-label-code="${esc(code)}" ${checked}><span><b>${esc(displayName(state, code))}</b><small>${esc(code)}</small></span></label>`;
        }).join('')
      : (ids.length
        ? '<span class="training-label-empty">已选素材没有可选择的有效标签。</span>'
        : '<span class="training-label-empty">请先选择训练素材。</span>');

    panel.innerHTML = `
      <div class="training-label-contract-head"><div><b>训练标签</b><small>只选择本次素材需要显式加入训练的标签；迭代类别与标签合并由服务器自动处理。</small></div><span class="training-label-contract-count">已选 ${view.requested.length}</span></div>
      <div class="training-label-contract-list">${selectableHtml}</div>
      ${view.invalidAvailable.length ? '<div class="training-label-warning">部分素材标签已失效，请先到标签管理统一后再训练。</div>' : ''}
    `;

    panel.querySelectorAll('[data-training-label-code]').forEach(input => {
      input.addEventListener('change', event => {
        const code = String(event.currentTarget.dataset.trainingLabelCode || '');
        const next = new Set(canonicalSelectedCodes(state));
        if (event.currentTarget.checked) next.add(code);
        else next.delete(code);
        syncDraftLabels(state, [...next]);
        updateCount(state);
      });
    });
    return true;
  };

  const queueRefresh = () => {
    if (destroyed || refreshQueued) return;
    refreshQueued = true;
    queueMicrotask(() => {
      refreshQueued = false;
      if (!destroyed) refresh();
    });
  };

  const unsubscribeDraft = trainingDraftRuntime?.subscribe?.(event => {
    const state = getState?.();
    if (event?.type === 'update' && startsTrainingSession(event.patch)) {
      resetTaskLabelInteraction(state);
      materialSummaryRuntime?.invalidate?.();
    }
    if (labelOnlyDraftUpdate(event)) {
      updateCount(state);
      return;
    }
    queueRefresh();
  }) || (() => {});

  const modalObserver = typeof MutationObserver !== 'undefined'
    ? new MutationObserver(records => {
        if (destroyed || !currentHost()) return;
        if (records?.length && records.every(record => {
          const target = record?.target;
          return typeof Element !== 'undefined' && target instanceof Element && target.closest?.('#trainingLabelContractPanel');
        })) return;
        queueRefresh();
      })
    : null;
  modalObserver?.observe(document.body, {childList: true, subtree: true});

  queueRefresh();

  const runtime = {
    build: 'module-422568',
    refresh,
    queueRefresh,
    selectedIds: () => selectedIds(getState?.()),
    state() {
      return {
        refreshQueued,
        serverSummaryOwner: Boolean(materialSummaryRuntime),
        draftSubscriptionOwner: Boolean(trainingDraftRuntime?.subscribe),
        labelHistoryOwner: false,
        classicWrapperOwner: false,
        timerOwner: false,
      };
    },
    destroy() {
      destroyed = true;
      unsubscribeDraft();
      modalObserver?.disconnect();
      if (window.TrainingLabelRuntime === runtime) window.TrainingLabelRuntime = null;
      window.__trainingLabelRuntimeInstalled = false;
    },
  };

  window.TrainingLabelRuntime = runtime;
  return runtime;
}
