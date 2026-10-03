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
    .training-label-contract{margin:14px 0 2px;padding:14px;border:1px solid #dbe5f3;border-radius:16px;background:linear-gradient(180deg,#fbfdff 0%,#f6f9fe 100%);box-shadow:0 8px 24px rgba(44,72,120,.06)}
    .training-label-contract-head{display:flex;align-items:center;justify-content:space-between;gap:16px}
    .training-label-contract-head b{font-size:12px;color:#233653;letter-spacing:.02em}
    .training-label-contract-head small{display:block;margin-top:4px;color:#7d8ba0;font-size:9px;line-height:1.55}
    .training-label-contract-count{min-width:68px;text-align:center;padding:6px 10px;border-radius:999px;background:#eaf1ff;color:#315fc2;font-weight:800;font-size:10px;white-space:nowrap}
    .training-label-base{display:grid;grid-template-columns:minmax(112px,auto) 1fr;align-items:center;gap:14px;margin-top:12px;padding:12px 13px;border:1px solid #d7e3f5;border-radius:13px;background:rgba(238,244,255,.72)}
    .training-label-base-title{display:flex;flex-direction:column;gap:3px}.training-label-base-title b{font-size:10px;color:#385680}.training-label-base-title small{font-size:8px;color:#8795aa}
    .training-label-base-list{display:flex;align-items:center;gap:8px;flex-wrap:wrap;min-width:0}
    .training-label-base-chip{display:inline-flex;align-items:center;gap:7px;min-height:30px;padding:5px 10px;border:1px solid #cbdaf2;border-radius:999px;background:#fff;box-shadow:0 3px 10px rgba(49,95,194,.05);white-space:nowrap}
    .training-label-base-chip i{display:inline-grid;place-items:center;width:17px;height:17px;border-radius:50%;background:#315fc2;color:#fff;font-style:normal;font-size:9px;font-weight:900}
    .training-label-base-chip b{font-size:10px;color:#263d64}.training-label-base-chip small{font-size:8px;color:#8794a8}
    .training-label-material{margin-top:12px;padding-top:12px;border-top:1px solid #e5ebf4}
    .training-label-material-head{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:8px}.training-label-material-head b{font-size:10px;color:#465975}.training-label-material-head small{font-size:8px;color:#8a97aa}
    .training-label-contract-list{display:flex;gap:8px;flex-wrap:wrap}
    .training-label-choice{display:inline-flex;align-items:center;gap:8px;min-height:34px;padding:7px 11px;border:1px solid #dce5f2;border-radius:11px;background:#fff;cursor:pointer;min-width:112px;transition:border-color .16s ease,box-shadow .16s ease,transform .16s ease}
    .training-label-choice:hover{border-color:#b9cbea;box-shadow:0 6px 16px rgba(45,79,139,.07);transform:translateY(-1px)}
    .training-label-choice:has(input:checked){border-color:#6c8ee0;background:#edf3ff;color:#244fae;box-shadow:0 6px 18px rgba(49,95,194,.10)}.training-label-choice input{margin:0}
    .training-label-choice span{display:flex;flex-direction:column;line-height:1.2}.training-label-choice b{font-size:10px}.training-label-choice small{font-size:8px;color:#8491a4;margin-top:2px}
    .training-label-empty{font-size:9px;color:#8a96a8;padding:3px 0}.training-label-warning{margin-top:8px;font-size:9px;color:#b42318;line-height:1.5}
    .training-label-base-loading{display:inline-flex;align-items:center;gap:8px;color:#7d8ba0;font-size:9px}.training-label-base-loading:before{content:'';width:12px;height:12px;border:2px solid #cbd8ec;border-top-color:#5679cb;border-radius:50%;animation:trainingLabelSpin .8s linear infinite}
    @keyframes trainingLabelSpin{to{transform:rotate(360deg)}}
    @media(max-width:760px){.training-label-base{grid-template-columns:1fr}.training-label-contract-head{align-items:flex-start}.training-label-material-head{align-items:flex-start}}
  `;
  document.head.appendChild(style);
}

export function installTrainingLabelRuntime({
  getState,
  notify,
  trainingDraftRuntime,
  materialSummaryRuntime,
  projectId,
  request,
} = {}) {
  if (window.__trainingLabelRuntimeInstalled) return window.TrainingLabelRuntime || null;
  window.__trainingLabelRuntimeInstalled = true;
  ensurePanelStyle();

  let destroyed = false;
  let refreshQueued = false;
  let basePreviewSequence = 0;
  let basePreview = {key: '', status: 'idle', labels: [], versionName: '', error: ''};

  const basePreviewKey = state => {
    const pid = String(projectId?.() || state?.project?.id || '').trim();
    const algorithmId = algorithmIdFor(state);
    const baseVersionId = String(state?.trainingDraft?.baseVersionId || '').trim();
    return pid && algorithmId && baseVersionId ? `${pid}:${algorithmId}:${baseVersionId}` : '';
  };

  const resetBasePreview = () => {
    basePreviewSequence += 1;
    basePreview = {key: '', status: 'idle', labels: [], versionName: '', error: ''};
  };

  const ensureBasePreview = state => {
    const key = basePreviewKey(state);
    if (!key) {
      if (basePreview.key) resetBasePreview();
      return;
    }
    if (basePreview.key === key && ['loading', 'ready', 'error'].includes(basePreview.status)) return;
    if (typeof request !== 'function') return;
    const [pid, algorithmId, baseVersionId] = key.split(':');
    const sequence = ++basePreviewSequence;
    basePreview = {key, status: 'loading', labels: [], versionName: '', error: ''};
    const url = `/api/v62/projects/${encodeURIComponent(pid)}/training-labels/inherited?algorithm_id=${encodeURIComponent(algorithmId)}&base_version_id=${encodeURIComponent(baseVersionId)}`;
    Promise.resolve(request(url))
      .then(result => {
        if (destroyed || sequence !== basePreviewSequence || basePreview.key !== key) return;
        const rows = Array.isArray(result?.labels) ? result.labels : [];
        basePreview = {
          key,
          status: 'ready',
          labels: rows.map(row => ({
            code: String(row?.code || '').trim(),
            display_name: String(row?.display_name || row?.code || '').trim(),
          })).filter(row => row.code),
          versionName: String(result?.base_version_name || baseVersionId),
          error: '',
        };
        queueRefresh();
      })
      .catch(error => {
        if (destroyed || sequence !== basePreviewSequence || basePreview.key !== key) return;
        basePreview = {key, status: 'error', labels: [], versionName: '', error: String(error?.message || error || '读取失败')};
        queueRefresh();
      });
  };

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
    count.textContent = `新增 ${view.requested.length}`;
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
    ensureBasePreview(state);
    const previewKey = basePreviewKey(state);
    const hasBaseVersion = Boolean(previewKey);
    const previewCurrent = !hasBaseVersion || basePreview.key === previewKey;
    const availableCodes = availableCodesFor(state, ids);
    let panel = document.getElementById('trainingLabelContractPanel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'trainingLabelContractPanel';
      panel.className = 'training-label-contract';
      placement.anchor.insertAdjacentElement('afterend', panel);
    }

    if (availableCodes === null || (hasBaseVersion && (!previewCurrent || basePreview.status === 'loading' || basePreview.status === 'idle'))) {
      panel.innerHTML = `
        <div class="training-label-contract-head"><div><b>训练标签</b><small>正在准备本次训练的标签范围。</small></div><span class="training-label-contract-count">读取中</span></div>
        ${hasBaseVersion ? '<div class="training-label-base"><div class="training-label-base-title"><b>上一版本继承</b><small>自动继承</small></div><div class="training-label-base-loading">正在读取继承标签</div></div>' : ''}
        <div class="training-label-material"><div class="training-label-material-head"><b>本次素材标签</b><small>默认不选</small></div><div class="training-label-contract-list"><span class="training-label-empty">正在读取素材标签…</span></div></div>`;
      return true;
    }

    if (hasBaseVersion && previewCurrent && basePreview.status === 'error') {
      panel.innerHTML = `
        <div class="training-label-contract-head"><div><b>训练标签</b><small>上一版本标签暂未读取成功。</small></div><span class="training-label-contract-count">需重试</span></div>
        <div class="training-label-warning">继承标签读取失败，请关闭后重新打开训练窗口。</div>`;
      return true;
    }

    const baseLabels = hasBaseVersion && previewCurrent && basePreview.status === 'ready' ? basePreview.labels : [];
    const baseCodes = new Set(baseLabels.map(row => row.code));
    const initial = resolveFor(state, ids, draftRequested, availableCodes);
    const materialSelectable = initial.selectable.filter(code => !baseCodes.has(code));
    const selectedCodes = selectionForState(state, algorithmId, materialSelectable);
    if (selectedCodes.join('\u0000') !== draftRequested.join('\u0000')) syncDraftLabels(state, selectedCodes);
    const view = resolveFor(state, ids, selectedCodes, availableCodes);
    const selectedSet = new Set(view.requested);
    const finalMaterialSelectable = view.selectable.filter(code => !baseCodes.has(code));
    const selectableHtml = finalMaterialSelectable.length
      ? finalMaterialSelectable.map(code => {
          const checked = selectedSet.has(code) ? 'checked' : '';
          return `<label class="training-label-choice"><input type="checkbox" data-training-label-code="${esc(code)}" ${checked}><span><b>${esc(displayName(state, code))}</b><small>${esc(code)}</small></span></label>`;
        }).join('')
      : (ids.length
        ? '<span class="training-label-empty">已选素材没有可选择的有效标签。</span>'
        : '<span class="training-label-empty">请先选择训练素材。</span>');

    const baseHtml = baseLabels.length
      ? `<div class="training-label-base">
          <div class="training-label-base-title"><b>上一版本继承</b><small>${esc(basePreview.versionName || '已验证版本')}</small></div>
          <div class="training-label-base-list">${baseLabels.map(row => `<span class="training-label-base-chip" data-training-base-label="${esc(row.code)}"><i>✓</i><b>${esc(row.display_name || row.code)}</b><small>${esc(row.code)}</small></span>`).join('')}</div>
        </div>`
      : '';
    const materialHint = ids.length && !finalMaterialSelectable.length && baseLabels.length
      ? '当前素材标签已由上一版本继承，无需重复选择。'
      : '';

    panel.innerHTML = `
      <div class="training-label-contract-head"><div><b>训练标签</b><small>继承标签自动保留；本次素材标签按需选择。</small></div><span class="training-label-contract-count">新增 ${view.requested.length}</span></div>
      ${baseHtml}
      <div class="training-label-material">
        <div class="training-label-material-head"><b>本次素材标签</b><small>默认不选</small></div>
        <div class="training-label-contract-list">${materialHint ? `<span class="training-label-empty">${materialHint}</span>` : selectableHtml}</div>
      </div>
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
      resetBasePreview();
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
    build: 'module-422569',
    refresh,
    queueRefresh,
    selectedIds: () => selectedIds(getState?.()),
    state() {
      return {
        refreshQueued,
        serverSummaryOwner: Boolean(materialSummaryRuntime),
        draftSubscriptionOwner: Boolean(trainingDraftRuntime?.subscribe),
        labelHistoryOwner: false,
        serverInheritancePreviewOwner: true,
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
