(() => {
  'use strict';

  if (window.__trainingLabelBootstrapInstalled) return;
  window.__trainingLabelBootstrapInstalled = true;
  // Prevent the optional ES-module runtime from installing a second competing wrapper.
  window.__trainingLabelRuntimeInstalled = true;

  const BUILD = '42.25.0-dev';
  const uniq = values => [...new Set((values || []).map(v => String(v || '').trim()).filter(Boolean))];
  const htmlEsc = value => String(value ?? '').replace(/[&<>"']/g, ch => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[ch]);

  function appState() {
    try {
      // app.js is a classic script and declares `const state` in the global environment.
      // A later classic script can resolve that binding directly.
      if (typeof state !== 'undefined') return state;
    } catch (_) {}
    return window.state || null;
  }

  function notify(message) {
    try {
      if (typeof toast === 'function') return toast(message);
    } catch (_) {}
    if (typeof window.toast === 'function') return window.toast(message);
    console.warn(message);
  }

  function labelCatalogMap(s) {
    return new Map((s?.labels || []).map(item => [String(item?.code || ''), item]));
  }

  function labelName(s, code) {
    const item = labelCatalogMap(s).get(String(code));
    return item?.display_name || item?.display_name_zh || item?.name || code;
  }

  function selectedIds(s) {
    if (s?.train429Selected instanceof Set) return uniq([...s.train429Selected]);
    const train = [...(s?.train425Selected?.train || new Set())];
    const val = [...(s?.train425Selected?.val || new Set())];
    return uniq([...train, ...val]);
  }

  function availableCodes(s, ids = selectedIds(s)) {
    const wanted = new Set(ids.map(String));
    const seen = new Set();
    const codes = [];
    for (const row of s?.images || []) {
      if (!wanted.has(String(row?.id || ''))) continue;
      for (const raw of row?.labels || []) {
        const code = String(raw || '').trim();
        if (code && !seen.has(code)) { seen.add(code); codes.push(code); }
      }
      for (const raw of row?.annotation_scope || []) {
        const code = String(raw || '').trim();
        if (code && code !== '*' && !seen.has(code)) { seen.add(code); codes.push(code); }
      }
    }
    const rank = new Map((s?.labels || []).map((item, index) => [String(item?.code || ''), index]));
    return codes.sort((a, b) => {
      const ra = rank.has(a) ? rank.get(a) : Number.MAX_SAFE_INTEGER;
      const rb = rank.has(b) ? rank.get(b) : Number.MAX_SAFE_INTEGER;
      return ra - rb || a.localeCompare(b);
    });
  }

  function successfulVersion(v) {
    const status = String(v?.training_status || '').trim().toUpperCase();
    return ['SUCCEEDED', 'PARTIAL_SUCCESS', 'DONE', 'FINISHED', 'COMPLETED'].includes(status)
      && v?.artifact_verified === true
      && v?.trainable !== false;
  }

  function latestVersionInfo(algorithm) {
    const versions = [...(algorithm?.versions || [])].sort((a, b) => {
      const av = String(a?.finished_at || a?.created_at || a?.version_name || '');
      const bv = String(b?.finished_at || b?.created_at || b?.version_name || '');
      return bv.localeCompare(av);
    });
    if (!versions.length) return {hasAny: false, hasPrevious: false, blocked: false, legacy: false, codes: []};
    const latest = versions.find(successfulVersion) || null;
    if (!latest) return {hasAny: true, hasPrevious: false, blocked: true, legacy: false, codes: []};
    const schema = [...(latest.label_schema || [])].sort((a, b) => Number(a?.class_id ?? 1e9) - Number(b?.class_id ?? 1e9));
    const codes = uniq(schema.map(item => item?.code));
    return {hasAny: true, hasPrevious: true, blocked: false, legacy: !codes.length, codes};
  }

  function currentAlgorithm(s) {
    const id = String(s?.train428AlgorithmId || document.getElementById('tr425AssetAlg')?.value || '').trim();
    return (s?.algorithms || []).find(item => String(item?.id || '') === id) || null;
  }

  function resetSelection(s) {
    if (!s) return;
    s.trainingLabelAlgorithmId = '';
    s.trainingLabelSelectionTouched = false;
    s.trainingLabelSelected = new Set();
  }

  function resolveView(s) {
    const algorithm = currentAlgorithm(s);
    if (!algorithm) return null;
    const ids = selectedIds(s);
    const available = availableCodes(s, ids);
    const previous = latestVersionInfo(algorithm);
    const inheritedSet = new Set(previous.codes);
    const selectable = available.filter(code => !inheritedSet.has(code));

    if (s.trainingLabelAlgorithmId !== String(algorithm.id || '')) {
      s.trainingLabelAlgorithmId = String(algorithm.id || '');
      s.trainingLabelSelectionTouched = false;
      s.trainingLabelSelected = new Set(previous.hasPrevious ? [] : selectable);
    } else {
      const allowed = new Set(selectable);
      const kept = [...(s.trainingLabelSelected || new Set())].filter(code => allowed.has(code));
      s.trainingLabelSelected = (!s.trainingLabelSelectionTouched && !previous.hasPrevious)
        ? new Set(selectable)
        : new Set(kept);
    }

    const requested = uniq([...(s.trainingLabelSelected || new Set())]).filter(code => selectable.includes(code));
    return {
      algorithm,
      ids,
      available,
      previous,
      selectable,
      requested,
      effective: uniq([...previous.codes, ...requested]),
    };
  }

  function ensureStyles() {
    if (document.getElementById('trainingLabelClassicStyle')) return;
    const style = document.createElement('style');
    style.id = 'trainingLabelClassicStyle';
    style.textContent = `
      .training-label-classic{margin-top:12px;padding:13px;border:1px solid #dbe5f2;border-radius:12px;background:#f8faff}
      .training-label-classic-head{display:flex;align-items:flex-start;justify-content:space-between;gap:12px}
      .training-label-classic-head b{font-size:12px;color:#233957}
      .training-label-classic-head small{display:block;margin-top:4px;font-size:9px;color:#75849a;line-height:1.5}
      .training-label-classic-count{padding:5px 9px;border-radius:9px;background:#e8f0ff;color:#2f5fbe;font-size:10px;font-weight:900;white-space:nowrap}
      .training-label-classic-block{margin-top:10px}
      .training-label-classic-title{display:block;margin-bottom:6px;font-size:9px;color:#718096}
      .training-label-classic-list{display:flex;gap:7px;flex-wrap:wrap}
      .training-label-classic-choice{display:inline-flex;align-items:center;gap:7px;min-width:108px;padding:8px 10px;border:1px solid #d9e3f0;border-radius:10px;background:#fff;cursor:pointer}
      .training-label-classic-choice.checked{border-color:#5c83d5;background:#edf3ff;color:#244fae}
      .training-label-classic-choice input{margin:0}
      .training-label-classic-choice span{display:flex;flex-direction:column;line-height:1.25}
      .training-label-classic-choice b{font-size:10px}
      .training-label-classic-choice small{font-size:8px;color:#8492a6;margin-top:2px}
      .training-label-classic-inherited{display:inline-flex;padding:7px 9px;border-radius:9px;background:#ecfdf5;color:#15803d;font-size:9px;font-weight:800}
      .training-label-classic-empty{font-size:9px;color:#8794a6}
      .training-label-classic-error{font-size:9px;color:#dc2626;font-weight:700}
      .training-label-classic-warn{margin-top:8px;font-size:9px;color:#a16207;line-height:1.5}
    `;
    document.head.appendChild(style);
  }

  function placement() {
    const summary = document.querySelector('.train429-create .train429-data-summary');
    if (summary) return {host: summary.closest('.train428-panel'), anchor: summary};
    const host = document.querySelector('.train428-data') || document.querySelector('.train425-data');
    return host ? {host, anchor: null} : null;
  }

  function refresh() {
    const s = appState();
    const where = placement();
    if (!s || !where?.host) return false;
    const view = resolveView(s);
    if (!view) return false;

    let panel = document.getElementById('trainingLabelContractPanel');
    if (!panel) {
      panel = document.createElement('div');
      panel.id = 'trainingLabelContractPanel';
      panel.className = 'training-label-classic';
      if (where.anchor) where.anchor.insertAdjacentElement('afterend', panel);
      else where.host.appendChild(panel);
    }

    const inherited = view.previous.codes.length
      ? view.previous.codes.map(code => `<span class="training-label-classic-inherited">继承 · ${htmlEsc(labelName(s, code))}</span>`).join('')
      : view.previous.blocked
        ? '<span class="training-label-classic-error">已有版本但没有成功且可继续训练的模型，禁止回退母算法。</span>'
        : view.previous.legacy
          ? '<span class="training-label-classic-warn">历史版本标签将在服务器端从训练 Snapshot 恢复。</span>'
          : '<span class="training-label-classic-empty">首次训练：不继承母算法自带类别。</span>';

    const selectable = view.selectable.length
      ? view.selectable.map(code => {
          const checked = s.trainingLabelSelected?.has(code);
          return `<label class="training-label-classic-choice ${checked ? 'checked' : ''}"><input type="checkbox" data-training-label-code="${htmlEsc(code)}" ${checked ? 'checked' : ''}><span><b>${htmlEsc(labelName(s, code))}</b><small>${htmlEsc(code)}</small></span></label>`;
        }).join('')
      : view.ids.length
        ? '<span class="training-label-classic-empty">已选素材没有可选标签，请检查正式标注或负样本 scope。</span>'
        : '<span class="training-label-classic-empty">请先选择训练素材，素材中的标签会自动出现在这里。</span>';

    const missingInherited = view.previous.codes.filter(code => !view.available.includes(code));
    panel.innerHTML = `
      <div class="training-label-classic-head"><div><b>本次训练标签</b><small>标签只来自本次已选素材。项目标签库和母模型自带类别不会自动加入。</small></div><span class="training-label-classic-count">${view.effective.length || (view.previous.legacy ? '?' : 0)} 类</span></div>
      <div class="training-label-classic-block"><span class="training-label-classic-title">上一版本自动继承</span><div class="training-label-classic-list">${inherited}</div></div>
      <div class="training-label-classic-block"><span class="training-label-classic-title">本次素材标签（可选择）</span><div class="training-label-classic-list">${selectable}</div></div>
      ${missingInherited.length ? `<div class="training-label-classic-warn">继承标签 ${missingInherited.map(code => htmlEsc(labelName(s, code))).join('、')} 在本次素材中没有正样本，但仍保留原 class_id。</div>` : ''}
    `;

    panel.querySelectorAll('[data-training-label-code]').forEach(input => {
      input.addEventListener('change', event => {
        const code = String(event.currentTarget.dataset.trainingLabelCode || '');
        s.trainingLabelSelectionTouched = true;
        s.trainingLabelSelected = s.trainingLabelSelected || new Set();
        if (event.currentTarget.checked) s.trainingLabelSelected.add(code);
        else s.trainingLabelSelected.delete(code);
        refresh();
      });
    });
    return true;
  }

  function wrapOpen(name) {
    const original = window[name];
    if (typeof original !== 'function' || original.__trainingLabelClassicWrapped) return;
    const wrapped = function (...args) {
      resetSelection(appState());
      const result = original.apply(this, args);
      setTimeout(refresh, 0);
      setTimeout(refresh, 50);
      setTimeout(refresh, 150);
      return result;
    };
    wrapped.__trainingLabelClassicWrapped = true;
    wrapped.__trainingLabelClassicOriginal = original;
    window[name] = wrapped;
  }

  function wrapRefresh(name) {
    const original = window[name];
    if (typeof original !== 'function' || original.__trainingLabelClassicWrapped) return;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      setTimeout(refresh, 0);
      return result;
    };
    wrapped.__trainingLabelClassicWrapped = true;
    wrapped.__trainingLabelClassicOriginal = original;
    window[name] = wrapped;
  }

  function bind() {
    wrapOpen('startAlgorithmTraining429');
    wrapOpen('startAlgorithmTraining423');
    wrapOpen('openTrain428');
    wrapOpen('openTrain425');
    wrapRefresh('refreshTrain429');
    wrapRefresh('refreshTrain428');
    wrapRefresh('trainCounts425');
  }

  // Authoritative request injection. This executes in the same classic-script layer as app.js.
  const nativeFetch = window.fetch.bind(window);
  window.fetch = async function (input, init = {}) {
    const url = typeof input === 'string' ? input : String(input?.url || '');
    const method = String(init?.method || (typeof input !== 'string' ? input?.method : '') || 'GET').toUpperCase();
    if (method === 'POST' && /\/api\/v12\/projects\/[^/]+\/train\/start(?:\?|$)/.test(url) && typeof init?.body === 'string') {
      let payload = null;
      try { payload = JSON.parse(init.body); } catch (_) {}
      if (payload?.algorithm_asset_id) {
        const s = appState();
        const view = resolveView(s);
        if (!view) throw new Error('训练标签状态不可用，请关闭训练窗口后重新打开。');
        if (view.previous.blocked) throw new Error('该算法已有版本，但没有成功且可继续训练的版本；平台不会回退母算法。');
        if (!view.previous.hasPrevious && !view.requested.length) {
          refresh();
          throw new Error('首次训练至少选择一个标签；请在“本次训练标签”中勾选。');
        }
        payload.train_labels = view.requested;
        init = {...init, body: JSON.stringify(payload)};
      }
    }
    return nativeFetch(input, init);
  };

  ensureStyles();
  bind();
  for (const delay of [50, 250, 800, 1800, 3500]) setTimeout(bind, delay);

  const observer = typeof MutationObserver !== 'undefined'
    ? new MutationObserver(() => {
        if (document.querySelector('.train429-create') && !document.getElementById('trainingLabelContractPanel')) queueMicrotask(refresh);
      })
    : null;
  observer?.observe(document.getElementById('modalBody') || document.body, {childList: true, subtree: true});

  function stampBuild() {
    const badge = document.getElementById('versionBadge');
    if (badge) badge.textContent = `v${BUILD}`;
    const footer = document.querySelector('.nav-footer b');
    if (footer) footer.textContent = `v${BUILD}`;
  }
  stampBuild();
  for (const delay of [100, 500, 1800, 3600]) setTimeout(stampBuild, delay);

  window.TrainingLabelRuntime = {
    build: 'classic-422504',
    refresh,
    rebind: bind,
    selectedIds: () => selectedIds(appState()),
    destroy() { observer?.disconnect(); },
  };
})();
