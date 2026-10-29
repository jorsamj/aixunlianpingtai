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

function temporaryLabel(code) {
  const value = String(code || '').trim().toLowerCase();
  return ['unknown', 'unmapped', 'temporary', 'temp', 'class'].includes(value)
    || /^(?:class|cls)[_-]?\d+$/.test(value)
    || /^(?:unknown|unmapped|temp)_/.test(value);
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
  // Existing summary contains only selected formal GT box labels. An active
  // project label without a selected positive is NOT a new task choice.
  const selectable = available.filter(code => activeCatalog.has(code) && !temporaryLabel(code));
  const selectableSet = new Set(selectable);
  const requested = unique(requestedCodes).filter(code => selectableSet.has(code));
  const invalidAvailable = available.filter(code => !activeCatalog.has(code) || temporaryLabel(code));
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

export function selectionForState(state, sessionKey, selectable) {
  const available = new Set(selectable);
  if (state.trainingLabelAlgorithmId !== sessionKey) {
    state.trainingLabelAlgorithmId = sessionKey;
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
  const slot=document.querySelector('.train429-create #trainUiLabelSlot');
  if(slot)return {host:slot,anchor:null,mode:'workbench'};
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

  let destroyed = false;
  let refreshQueued = false;
  let basePreviewSequence = 0;
  let basePreview = {key: '', status: 'idle', labels: [], versionName: '', error: ''};
  let panelSignature='';
  let filterQuery='';
  let labelPage=1;
  let labelRows=[];
  const pageSize=24;
  const paintPage=()=>{
    const panel=document.getElementById('trainingLabelContractPanel'),list=panel?.querySelector('.training-label-contract-list');if(!list)return;
    const rows=labelRows.filter(row=>!filterQuery||row.search.includes(filterQuery));
    const pages=Math.max(1,Math.ceil(rows.length/pageSize));labelPage=Math.min(Math.max(1,labelPage),pages);
    const visible=rows.slice((labelPage-1)*pageSize,labelPage*pageSize),selected=new Set(canonicalSelectedCodes(getState?.()));
    const same=list.children.length===visible.length&&visible.every((row,index)=>list.children[index]?.querySelector('input')?.dataset.trainingLabelCode===row.code);
    if(!same){const nodes=visible.map(row=>{const label=document.createElement('label');label.className='training-label-choice';label.innerHTML=`<input type="checkbox" data-training-label-code="${esc(row.code)}"><span><b>${esc(row.name)}</b><small>${esc(row.code)}</small></span>`;return label});if(!nodes.length){const empty=document.createElement('span');empty.className='training-label-empty';empty.textContent=labelRows.length?'没有匹配的标签':'没有可新增的标签';nodes.push(empty)}list.replaceChildren(...nodes)}
    for(const input of list.querySelectorAll('[data-training-label-code]'))input.checked=selected.has(input.dataset.trainingLabelCode);
    let pager=panel.querySelector('#trainingLabelPager');if(!pager){pager=document.createElement('div');pager.id='trainingLabelPager';pager.className='training-label-pager';pager.innerHTML='<button type="button" class="btn mini" data-label-prev>上一页</button><span></span><button type="button" class="btn mini" data-label-next>下一页</button>';panel.appendChild(pager);pager.querySelector('[data-label-prev]').onclick=()=>{labelPage--;paintPage()};pager.querySelector('[data-label-next]').onclick=()=>{labelPage++;paintPage()}}
    pager.querySelector('span').textContent=`${labelPage} / ${pages} · ${rows.length} 个标签`;pager.querySelector('[data-label-prev]').disabled=labelPage<=1;pager.querySelector('[data-label-next]').disabled=labelPage>=pages;
  };

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
    // Never use local Material projection/visible-page labels as formal GT.
    if (!materialSummaryRuntime) return [];
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
    let draftRequested = canonicalSelectedCodes(state);
    const sessionKey = JSON.stringify([String(projectId?.() || state?.project?.id || ''),algorithmId,
      String(state?.trainingDraft?.baseVersionId || '')]);
    const sessionChanged = state.trainingLabelAlgorithmId !== sessionKey;
    if (sessionChanged) {
      state.trainingLabelAlgorithmId = sessionKey;
      if (draftRequested.length) syncDraftLabels(state, []);
      draftRequested = [];
    }
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
      panel.addEventListener('change',event=>{const input=event.target;if(!input?.matches?.('[data-training-label-code]'))return;const current=getState?.(),next=new Set(canonicalSelectedCodes(current));if(input.checked)next.add(input.dataset.trainingLabelCode);else next.delete(input.dataset.trainingLabelCode);syncDraftLabels(current,[...next]);updateCount(current)});
      if(placement.mode==='workbench')placement.host.replaceChildren(panel);else placement.anchor.insertAdjacentElement('afterend', panel);
      panelSignature='';labelRows=[];labelPage=1;filterQuery=String(document.getElementById('trainUiLabelSearch')?.value||'').trim().toLowerCase();
    }

    if (availableCodes === null || (hasBaseVersion && (!previewCurrent || basePreview.status === 'loading' || basePreview.status === 'idle'))) {
      panelSignature='';labelRows=[];
      panel.innerHTML = `
        <div class="training-label-contract-head"><div><b>训练标签</b><small>正在准备本次训练的标签范围。</small></div><span class="training-label-contract-count">读取中</span></div>
        ${hasBaseVersion ? '<div class="training-label-base"><div class="training-label-base-title"><b>上一版本继承</b><small>自动继承</small></div><div class="training-label-base-loading">正在读取继承标签</div></div>' : ''}
        <div class="training-label-material"><div class="training-label-material-head"><b>本次训练标签</b><small>默认不选</small></div><div class="training-label-contract-list"><span class="training-label-empty">正在读取训练标签…</span></div></div>`;
      return true;
    }

    if (hasBaseVersion && previewCurrent && basePreview.status === 'error') {
      panelSignature='';labelRows=[];
      panel.innerHTML = `
        <div class="training-label-contract-head"><div><b>训练标签</b><small>上一版本标签暂未读取成功。</small></div><span class="training-label-contract-count">需重试</span></div>
        <div class="training-label-warning">继承标签读取失败，请关闭后重新打开训练窗口。</div>`;
      return true;
    }

    const baseLabels = hasBaseVersion && previewCurrent && basePreview.status === 'ready' ? basePreview.labels : [];
    const baseCodes = new Set(baseLabels.map(row => row.code));
    const initial = resolveFor(state, ids, draftRequested, availableCodes);
    const materialSelectable = initial.selectable.filter(code => !baseCodes.has(code));
    const selectedCodes = selectionForState(state, sessionKey, materialSelectable);
    if (selectedCodes.join('\u0000') !== draftRequested.join('\u0000')) {
      syncDraftLabels(state, selectedCodes);
      const removed = draftRequested.filter(code => !materialSelectable.includes(code));
      if (!sessionChanged && removed.length) notify?.(`已取消不再受所选素材正样本支持的新增标签：${removed.map(code => displayName(state,code)).join('、')}`);
    }
    const view = resolveFor(state, ids, selectedCodes, availableCodes);
    const selectedSet = new Set(view.requested);
    const finalMaterialSelectable = view.selectable.filter(code => !baseCodes.has(code));
    const signature=JSON.stringify([algorithmId,previewKey,baseLabels,finalMaterialSelectable.map(code=>[code,displayName(state,code)]),view.invalidAvailable,ids]);
    if(panelSignature===signature){updateCount(state);paintPage();return true}
    panelSignature=signature;
    labelRows=finalMaterialSelectable.map(code=>({code,name:displayName(state,code),search:(displayName(state,code)+' '+code).toLowerCase()}));

    const baseHtml = baseLabels.length
      ? `<div class="training-label-base">
          <div class="training-label-base-title"><b>上一版本继承</b><small>${esc(basePreview.versionName || '已验证版本')}</small></div>
          <div class="training-label-base-list">${baseLabels.map(row => `<span class="training-label-base-chip" data-training-base-label="${esc(row.code)}"><i>✓</i><b>${esc(row.display_name || row.code)}</b><small>${esc(row.code)}</small></span>`).join('')}</div>
        </div>`
      : '';
    const materialHint = !ids.length ? '请先选择训练素材。' : !finalMaterialSelectable.length
      ? baseLabels.length
        ? '当前所选素材没有可新增的已标注目标标签；上一版本继承标签保持不变。'
        : '当前所选素材没有可新增的已标注目标标签，请选择或标注正样本。'
      : '';

    panel.innerHTML = `
      <div class="training-label-contract-head"><div><b>训练标签</b><small>继承标签自动保留；本次训练标签按需选择。</small></div><span class="training-label-contract-count">新增 ${view.requested.length}</span></div>
      ${baseHtml}
      <div class="training-label-material">
        <div class="training-label-material-head"><b>本次可新增标签</b><small>仅来自已选素材的正式正样本 · 默认不选</small></div>
        <div class="training-label-contract-list"></div>
      </div>
      ${materialHint ? `<div class="training-label-material-hint">${esc(materialHint)}</div>` : ''}
      ${view.invalidAvailable.length ? '<div class="training-label-warning">部分素材标签已失效，请先到标签管理统一后再训练。</div>' : ''}
    `;

    paintPage();
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
  const mountBoundary=document.getElementById('modalBody');
  if(mountBoundary)modalObserver?.observe(mountBoundary, {childList: true, subtree: false});

  queueRefresh();

  const runtime = {
    build: 'module-422572',
    refresh,
    queueRefresh,
    filter(value){const next=String(value||'').trim().toLowerCase();if(next!==filterQuery){filterQuery=next;labelPage=1;paintPage()}},
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
