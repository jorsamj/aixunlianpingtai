function unique(values) {
  return [...new Set((values || []).map(value => String(value || '').trim()).filter(Boolean))];
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
  const schema = [...(latest?.label_schema || [])].sort((a, b) => Number(a?.class_id ?? 1e9) - Number(b?.class_id ?? 1e9));
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

function selectedIds(state) {
  const train = [...(state?.train425Selected?.train || new Set())];
  const val = [...(state?.train425Selected?.val || new Set())];
  return unique([...train, ...val]);
}

function currentAlgorithm(state) {
  const fixed = String(state?.train428AlgorithmId || '').trim();
  const fallback = document.getElementById('tr425AssetAlg')?.value || document.getElementById('train423Asset')?.value || '';
  const id = fixed || String(fallback || '').trim();
  return (state?.algorithms || []).find(item => String(item?.id || '') === id) || null;
}

function displayName(state, code) {
  const item = (state?.labels || []).find(label => String(label?.code || '') === String(code));
  return item?.display_name || item?.display_name_zh || item?.name || code;
}

function ensureState(state, algorithmId, hasPreviousVersion, selectable) {
  if (state.trainingLabelAlgorithmId !== algorithmId) {
    state.trainingLabelAlgorithmId = algorithmId;
    state.trainingLabelSelectionTouched = false;
    state.trainingLabelSelected = new Set(hasPreviousVersion ? [] : selectable);
    return;
  }
  const available = new Set(selectable);
  const existing = [...(state.trainingLabelSelected || new Set())].filter(code => available.has(code));
  if (!state.trainingLabelSelectionTouched && !hasPreviousVersion) {
    state.trainingLabelSelected = new Set(selectable);
  } else {
    state.trainingLabelSelected = new Set(existing);
  }
}

export function installTrainingLabelRuntime({getState, notify}) {
  if (window.__trainingLabelRuntimeInstalled) return;
  window.__trainingLabelRuntimeInstalled = true;

  const refresh = () => {
    const state = getState?.();
    if (!state) return;
    const algorithm = currentAlgorithm(state);
    const host = document.querySelector('.train428-data') || document.querySelector('.train425-data');
    if (!algorithm || !host) return;

    const ids = selectedIds(state);
    const initial = resolveClientTrainingLabels({
      materials: state.images || [],
      selectedIds: ids,
      labelCatalog: state.labels || [],
      algorithm,
      requestedCodes: [...(state.trainingLabelSelected || new Set())],
    });
    ensureState(state, String(algorithm.id || ''), initial.hasPreviousVersion, initial.selectable);
    const view = resolveClientTrainingLabels({
      materials: state.images || [],
      selectedIds: ids,
      labelCatalog: state.labels || [],
      algorithm,
      requestedCodes: [...(state.trainingLabelSelected || new Set())],
    });

    let panel = document.getElementById('trainingLabelContractPanel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'trainingLabelContractPanel';
      panel.className = 'train425-filter-head';
      panel.style.marginTop = '14px';
      panel.style.paddingTop = '12px';
      panel.style.borderTop = '1px solid var(--border, #e5e7eb)';
      host.appendChild(panel);
    }

    const inheritedHtml = view.inherited.length
      ? view.inherited.map(code => `<span class="pill ok" title="来自上一算法版本，迭代时不可移除">继承 · ${displayName(state, code)}</span>`).join('')
      : (view.previousVersionBlocked
        ? '<span class="pill err">已有版本但没有可用于迭代的成功模型，服务器将拒绝回退母模型</span>'
        : view.legacyPreviousVersion
          ? '<span class="pill warn">上一历史版本标签将在启动时由服务器 Snapshot 恢复</span>'
          : '<span class="item-sub">首次训练，不继承母模型自带类别</span>');

    const selectableHtml = view.selectable.length
      ? view.selectable.map(code => {
          const checked = state.trainingLabelSelected?.has(code) ? 'checked' : '';
          return `<label class="pill" style="cursor:pointer"><input type="checkbox" data-training-label-code="${code.replace(/"/g, '&quot;')}" ${checked}> ${displayName(state, code)}</label>`;
        }).join('')
      : '<span class="item-sub">当前已选素材没有可新增的标签</span>';

    const missingInherited = view.inherited.filter(code => !view.available.includes(code));
    panel.innerHTML = `
      <div class="row between"><div><b>本次训练标签</b><div class="item-sub">可选项只来自已选训练/试验素材；项目其他标签不会自动加入。</div></div><b>${view.effectivePreview.length || (view.legacyPreviousVersion ? '?' : 0)} 类</b></div>
      <div style="margin-top:8px"><span class="item-sub">上个版本：</span><div class="row" style="margin-top:5px;flex-wrap:wrap">${inheritedHtml}</div></div>
      <div style="margin-top:10px"><span class="item-sub">本次素材可新增：</span><div class="row" style="margin-top:5px;flex-wrap:wrap">${selectableHtml}</div></div>
      ${missingInherited.length ? `<div class="item-sub" style="margin-top:8px">提示：继承标签 ${missingInherited.map(code => displayName(state, code)).join('、')} 在本次素材中没有正样本，仍会保留在算法类别中。</div>` : ''}
    `;
    panel.querySelectorAll('[data-training-label-code]').forEach(input => {
      input.addEventListener('change', event => {
        const code = String(event.currentTarget.dataset.trainingLabelCode || '');
        state.trainingLabelSelectionTouched = true;
        state.trainingLabelSelected = state.trainingLabelSelected || new Set();
        event.currentTarget.checked ? state.trainingLabelSelected.add(code) : state.trainingLabelSelected.delete(code);
        refresh();
      });
    });
  };

  const wrapOpen = name => {
    const original = window[name];
    if (typeof original !== 'function' || original.__trainingLabelsWrapped) return;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      setTimeout(refresh, 60);
      return result;
    };
    wrapped.__trainingLabelsWrapped = true;
    window[name] = wrapped;
  };

  const wrapCounts = () => {
    const original = window.trainCounts425;
    if (typeof original !== 'function' || original.__trainingLabelsWrapped) return;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      setTimeout(refresh, 0);
      return result;
    };
    wrapped.__trainingLabelsWrapped = true;
    window.trainCounts425 = wrapped;
  };

  for (const delay of [0, 100, 400, 1000]) {
    setTimeout(() => {
      wrapOpen('openTrain428');
      wrapOpen('openTrain425');
      wrapCounts();
    }, delay);
  }

  const originalFetch = window.fetch.bind(window);
  window.fetch = async function (input, init = {}) {
    const url = typeof input === 'string' ? input : String(input?.url || '');
    const method = String(init?.method || (typeof input !== 'string' ? input?.method : '') || 'GET').toUpperCase();
    if (method === 'POST' && /\/api\/v12\/projects\/[^/]+\/train\/start(?:\?|$)/.test(url) && typeof init?.body === 'string') {
      let payload;
      try { payload = JSON.parse(init.body); } catch { payload = null; }
      if (payload && payload.algorithm_asset_id) {
        const state = getState?.();
        const algorithm = (state?.algorithms || []).find(item => String(item?.id || '') === String(payload.algorithm_asset_id));
        const ids = unique([...(payload.train_image_ids || []), ...(payload.val_image_ids || []), ...(payload.test_image_ids || [])]);
        const view = resolveClientTrainingLabels({
          materials: state?.images || [],
          selectedIds: ids,
          labelCatalog: state?.labels || [],
          algorithm,
          requestedCodes: [...(state?.trainingLabelSelected || new Set())],
        });
        if (view.previousVersionBlocked) {
          throw new Error('该算法已有版本，但没有成功且可继续训练的版本；平台不会回退到母算法。');
        }
        if (!view.hasPreviousVersion && !view.requested.length) {
          throw new Error('首次训练至少选择一个标签；母算法自带类别不会自动加入。');
        }
        payload.train_labels = view.requested;
        init = {...init, body: JSON.stringify(payload)};
      }
    }
    return originalFetch(input, init);
  };

  document.addEventListener('change', event => {
    if (event.target?.id === 'tr425AssetAlg') setTimeout(refresh, 0);
  });
}
