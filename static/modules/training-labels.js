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
    for (const value of row?.annotation_scope || []) {
      const code = String(value || '').trim();
      if (code && code !== '*' && !seen.has(code)) {
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

function trainableSuccessfulVersion(version) {
  const status = String(version?.training_status || '').trim().toUpperCase();
  return ['SUCCEEDED', 'PARTIAL_SUCCESS', 'DONE', 'FINISHED', 'COMPLETED'].includes(status)
    && version?.artifact_verified === true
    && version?.trainable !== false;
}

export function latestVersionLabelInfo(algorithm) {
  const allVersions = [...(algorithm?.versions || [])].sort((left, right) => {
    const a = String(left?.finished_at || left?.created_at || left?.version_name || '');
    const b = String(right?.finished_at || right?.created_at || right?.version_name || '');
    return b.localeCompare(a);
  });
  if (!allVersions.length) {
    return {hasVersion: false, hasAnyVersion: false, codes: [], legacyUnknown: false, blocked: false, version: null};
  }
  const latest = allVersions.find(trainableSuccessfulVersion) || null;
  if (!latest) {
    return {hasVersion: false, hasAnyVersion: true, codes: [], legacyUnknown: false, blocked: true, version: null};
  }
  const schema = [...(latest?.label_schema || [])]
    .sort((a, b) => Number(a?.class_id ?? 1e9) - Number(b?.class_id ?? 1e9));
  const codes = unique(schema.map(item => item?.code));
  return {
    hasVersion: true,
    hasAnyVersion: true,
    codes,
    legacyUnknown: !codes.length,
    blocked: false,
    version: latest,
  };
}

export function resolveClientTrainingLabels({materials, selectedIds, labelCatalog, algorithm, requestedCodes}) {
  const available = selectedMaterialLabelCodes(materials, selectedIds, labelCatalog);
  const inherited = latestVersionLabelInfo(algorithm);
  const inheritedSet = new Set(inherited.codes);
  const selectable = available.filter(code => !inheritedSet.has(code));
  const requested = unique(requestedCodes).filter(code => selectable.includes(code));
  return {
    available,
    selectable,
    requested,
    inherited: inherited.codes,
    hasPreviousVersion: inherited.hasVersion,
    hasAnyVersion: inherited.hasAnyVersion,
    previousVersionBlocked: inherited.blocked,
    legacyPreviousVersion: inherited.legacyUnknown,
    effectivePreview: unique([...inherited.codes, ...requested]),
  };
}

export function selectedTrainingMaterialIds(state) {
  return unique(state?.trainingDraft?.materialIds || []);
}

function selectedIds(state) {
  return selectedTrainingMaterialIds(state);
}

function currentAlgorithm(state) {
  const id = String(state?.trainingDraft?.algorithmId || '').trim();
  if (!id) return null;
  return (state?.algorithms || []).find(item => String(item?.id || '') === id) || null;
}

function displayName(state, code) {
  const item = (state?.labels || []).find(label => String(label?.code || '') === String(code));
  return item?.display_name || item?.display_name_zh || item?.name || code;
}

function canonicalSelectedCodes(state) {
  return unique(state?.trainingDraft?.newLabelCodes || []);
}

function selectionForState(state, algorithmId, hasPreviousVersion, selectable) {
  const available = new Set(selectable);
  if (state.trainingLabelAlgorithmId !== algorithmId) {
    state.trainingLabelAlgorithmId = algorithmId;
    state.trainingLabelSelectionTouched = false;
    return hasPreviousVersion ? [] : unique(selectable);
  }
  const existing = canonicalSelectedCodes(state).filter(code => available.has(code));
  if (!state.trainingLabelSelectionTouched && !hasPreviousVersion) return unique(selectable);
  return existing;
}

function resetTaskLabelInteraction(state) {
  if (!state) return;
  state.trainingLabelAlgorithmId = '';
  state.trainingLabelSelectionTouched = false;
}

function startsTrainingSession(patch) {
  if (!patch || typeof patch !== 'object') return false;
  return Object.hasOwn(patch, 'algorithmId')
    && Array.isArray(patch.materialIds) && patch.materialIds.length === 0
    && Array.isArray(patch.testMaterialIds) && patch.testMaterialIds.length === 0
    && Array.isArray(patch.newLabelCodes) && patch.newLabelCodes.length === 0;
}

function currentHost() {
  const v3Summary = document.querySelector('.train429-create .train-v3-summary')
    || document.querySelector('.train-v3-summary');
  if (v3Summary) {
    return {
      host: v3Summary.closest('.train428-panel') || v3Summary.parentElement,
      anchor: v3Summary,
      mode: 'v3',
    };
  }

  const summary429 = document.querySelector('.train429-create .train429-data-summary');
  if (summary429) {
    return {
      host: summary429.closest('.train428-panel') || summary429.parentElement,
      anchor: summary429,
      mode: 'v429',
    };
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
    .training-label-contract-count{min-width:42px;text-align:center;padding:5px 8px;border-radius:9px;background:#eaf1ff;color:#315fc2;font-weight:900;font-size:10px}
    .training-label-contract-block{margin-top:10px}
    .training-label-contract-title{display:block;color:#758399;font-size:9px;margin-bottom:6px}
    .training-label-contract-list{display:flex;gap:6px;flex-wrap:wrap}
    .training-label-choice{display:inline-flex;align-items:center;gap:6px;padding:7px 9px;border:1px solid #dce5f2;border-radius:9px;background:#fff;cursor:pointer;min-width:96px}
    .training-label-choice:has(input:checked){border-color:#6c8ee0;background:#edf3ff;color:#244fae}
    .training-label-choice input{margin:0}
    .training-label-choice span{display:flex;flex-direction:column;line-height:1.2}
    .training-label-choice b{font-size:10px}
    .training-label-choice small{font-size:8px;color:#8491a4;margin-top:2px}
    .training-label-inherited{display:inline-flex;align-items:center;padding:6px 8px;border-radius:9px;background:#ecfdf5;color:#15803d;font-size:9px;font-weight:800}
    .training-label-empty{font-size:9px;color:#8a96a8}
    .training-label-warning{margin-top:8px;font-size:9px;color:#a16207;line-height:1.5}
  `;
  document.head.appendChild(style);
}

export function installTrainingLabelRuntime({getState, notify, trainingDraftRuntime} = {}) {
  if (window.__trainingLabelRuntimeInstalled) return window.TrainingLabelRuntime || null;
  window.__trainingLabelRuntimeInstalled = true;
  ensurePanelStyle();

  let destroyed = false;
  let refreshQueued = false;

  const syncDraftLabels = (state, codes) => {
    if (!trainingDraftRuntime?.update) return;
    try {
      trainingDraftRuntime.update({newLabelCodes: unique(codes)});
    } catch (error) {
      notify?.(error?.message || error);
    }
  };

  const refresh = () => {
    if (destroyed) return false;
    const state = getState?.();
    if (!state) return false;
    const placement = currentHost();
    const algorithm = currentAlgorithm(state);
    if (!placement?.host || !algorithm) return false;

    const ids = selectedIds(state);
    const draftRequested = canonicalSelectedCodes(state);
    const initial = resolveClientTrainingLabels({
      materials: state.images || [],
      selectedIds: ids,
      labelCatalog: state.labels || [],
      algorithm,
      requestedCodes: draftRequested,
    });
    const selectedCodes = selectionForState(
      state,
      String(algorithm.id || ''),
      initial.hasPreviousVersion,
      initial.selectable,
    );
    if (selectedCodes.join('\u0000') !== draftRequested.join('\u0000')) syncDraftLabels(state, selectedCodes);
    const view = resolveClientTrainingLabels({
      materials: state.images || [],
      selectedIds: ids,
      labelCatalog: state.labels || [],
      algorithm,
      requestedCodes: selectedCodes,
    });

    let panel = document.getElementById('trainingLabelContractPanel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'trainingLabelContractPanel';
      panel.className = 'training-label-contract';
      placement.anchor.insertAdjacentElement('afterend', panel);
    }

    const inheritedHtml = view.inherited.length
      ? view.inherited.map(code => `<span class="training-label-inherited" title="来自上一算法版本，迭代时不可移除">继承 · ${esc(displayName(state, code))}</span>`).join('')
      : (view.previousVersionBlocked
        ? '<span class="pill err">已有版本但没有可用于迭代的成功模型，服务器将拒绝回退母模型</span>'
        : view.legacyPreviousVersion
          ? '<span class="pill warn">上一历史版本标签将在启动时由服务器 Snapshot 恢复</span>'
          : '<span class="training-label-empty">首次训练：不继承母算法自带类别</span>');

    const selectedSet = new Set(view.requested);
    const selectableHtml = view.selectable.length
      ? view.selectable.map(code => {
          const checked = selectedSet.has(code) ? 'checked' : '';
          return `<label class="training-label-choice"><input type="checkbox" data-training-label-code="${esc(code)}" ${checked}><span><b>${esc(displayName(state, code))}</b><small>${esc(code)}</small></span></label>`;
        }).join('')
      : (ids.length
        ? '<span class="training-label-empty">已选素材没有可新增标签；请检查素材标注或负样本 scope。</span>'
        : '<span class="training-label-empty">请先选择训练素材，素材带有的标签会在这里出现。</span>');

    const missingInherited = view.inherited.filter(code => !view.available.includes(code));
    panel.innerHTML = `
      <div class="training-label-contract-head"><div><b>本次训练标签</b><small>只显示当前已选素材实际携带的标签；项目标签库中的其他标签不会进入本次算法。</small></div><span class="training-label-contract-count">${view.effectivePreview.length || (view.legacyPreviousVersion ? '?' : 0)} 类</span></div>
      <div class="training-label-contract-block"><span class="training-label-contract-title">上一版本自动继承</span><div class="training-label-contract-list">${inheritedHtml}</div></div>
      <div class="training-label-contract-block"><span class="training-label-contract-title">本次素材标签（可选择）</span><div class="training-label-contract-list">${selectableHtml}</div></div>
      ${missingInherited.length ? `<div class="training-label-warning">继承标签 ${missingInherited.map(code => esc(displayName(state, code))).join('、')} 在本次素材中没有正样本，但仍会保留原 class_id。</div>` : ''}
    `;

    panel.querySelectorAll('[data-training-label-code]').forEach(input => {
      input.addEventListener('change', event => {
        const code = String(event.currentTarget.dataset.trainingLabelCode || '');
        state.trainingLabelSelectionTouched = true;
        const next = new Set(canonicalSelectedCodes(state));
        if (event.currentTarget.checked) next.add(code);
        else next.delete(code);
        syncDraftLabels(state, [...next]);
        refresh();
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
    }
    queueRefresh();
  }) || (() => {});

  const modalObserver = typeof MutationObserver !== 'undefined'
    ? new MutationObserver(records => {
        if (destroyed || !currentHost()) return;
        if (records?.length && records.every(record => {
          const target = record?.target;
          return typeof Element !== 'undefined'
            && target instanceof Element
            && target.closest?.('#trainingLabelContractPanel');
        })) return;
        queueRefresh();
      })
    : null;
  modalObserver?.observe(document.body, {childList: true, subtree: true});

  queueRefresh();

  const runtime = {
    build: 'module-422511',
    refresh,
    queueRefresh,
    selectedIds: () => selectedIds(getState?.()),
    state() {
      return {
        refreshQueued,
        draftSubscriptionOwner: Boolean(trainingDraftRuntime?.subscribe),
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
