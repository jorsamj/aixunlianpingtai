export function trainingOptionsHydrated(targets = []) {
  return (targets || []).some(target => (
    target?.status === 'ready'
    && Array.isArray(target.algorithms)
    && target.algorithms.length > 0
    && Array.isArray(target.base_models)
  ));
}

export function trainingCreationInputsReady(state = {}) {
  return trainingOptionsHydrated(state.targets) && state.rec != null;
}

export function installTrainingCreateHydrationRuntime({
  getState,
  projectId,
  request = async (url, options) => {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    return response.json();
  },
  preflight,
  preflightFresh,
  openTrainingForm,
  openShell,
  isShellCurrent,
  closeShell,
  notify = () => {},
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingCreateHydrationInstalled) return window.TrainingCreateHydrationRuntime || null;

  const openForm = openTrainingForm || window.openTrainingCreateCanonical429;
  if (typeof openForm !== 'function') return null;

  let inflight = null;
  let openEpoch = 0;
  let destroyed = false;
  const prewarmInflight = new Map();

  const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  })[char]);
  const defaultOpenShell = (aid, token) => {
    const state = getState?.() || {};
    const algorithm = (state.algorithms || []).find(item => String(item?.id || '') === String(aid || ''));
    const name = algorithm?.name || '训练任务';
    window.modal?.(`训练 · ${name}`, `<div class="train429-create train-create-loading" data-training-create-shell="1" data-training-algorithm-id="${escapeHtml(aid)}" data-training-open-token="${token}"><div class="train-create-loading-card"><b>正在准备训练配置</b><span data-training-create-status>正在读取训练资源、推荐配置与算法状态…</span></div><div class="row end"><button class="btn" onclick="closeModal()">取消</button><button class="btn primary" data-training-create-retry disabled>重试</button></div></div>`, true);
  };
  const shellRoot = (token, aid) => {
    if (typeof document === 'undefined') return null;
    const root = document.querySelector?.(`[data-training-create-shell="1"][data-training-open-token="${token}"]`);
    return root && String(root.dataset?.trainingAlgorithmId || '') === String(aid || '') ? root : null;
  };
  const defaultIsShellCurrent = (token, aid) => Boolean(shellRoot(token, aid));
  const defaultCloseShell = (token, aid) => {
    if (shellRoot(token, aid)) window.closeModal?.();
  };
  const showShell = openShell || defaultOpenShell;
  const shellIsCurrent = isShellCurrent || defaultIsShellCurrent;
  const dismissShell = closeShell || defaultCloseShell;

  function renderShellError(token, aid, error) {
    const root = shellRoot(token, aid);
    if (!root) return;
    root.classList?.add?.('error');
    const status = root.querySelector?.('[data-training-create-status]');
    if (status) status.textContent = error?.message || String(error);
    const retry = root.querySelector?.('[data-training-create-retry]');
    if (retry) {
      retry.disabled = false;
      retry.addEventListener?.('click', () => {
        dismissShell(token, aid);
        void start(aid);
      }, {once: true});
    }
  }
  const hydrate = async ({force = false} = {}) => {
    const state = getState?.() || {};
    if (!force && trainingCreationInputsReady(state)) return state;
    if (inflight) return inflight;
    const pid = projectId?.();
    if (!pid) throw new Error('当前项目尚未加载完成');

    inflight = (async () => {
      const needsOptions = force || !trainingOptionsHydrated(state.targets);
      const needsRecommendation = force || state.rec == null;
      const [optionsResult, recommendationResult] = await Promise.all([
        needsOptions ? request(`/api/training_options?project_id=${encodeURIComponent(pid)}`) : Promise.resolve(null),
        needsRecommendation ? request('/api/system/recommendation') : Promise.resolve(null),
      ]);
      if (optionsResult) state.targets = optionsResult.targets || [];
      if (recommendationResult) state.rec = recommendationResult;
      if (!trainingOptionsHydrated(state.targets)) throw new Error('没有读取到可用训练配置，请检查训练资源');
      return state;
    })().finally(() => { inflight = null; });
    return inflight;
  };

  const prewarm = async (aid = '', {includePreflight = true} = {}) => {
    if (destroyed) return null;
    const algorithmId = String(aid || '');
    const state = getState?.() || {};
    const algorithm = algorithmId
      ? (state.algorithms || []).find(item => String(item?.id || '') === algorithmId)
      : null;
    const externalChangLian = Boolean(algorithm)
      && String(algorithm?.source_type || '').toUpperCase() === 'EXTERNAL'
      && ['CHANG_LIAN', 'CHANGLIAN'].includes(String(algorithm?.provider_type || '').toUpperCase());
    const key = externalChangLian && includePreflight ? algorithmId : '__common__';
    if (prewarmInflight.has(key)) return prewarmInflight.get(key);
    const task = (async () => {
      const jobs = [hydrate()];
      const externalPreflightFresh = externalChangLian
        && typeof preflightFresh === 'function'
        && preflightFresh(algorithmId) === true;
      if (includePreflight && externalChangLian && !externalPreflightFresh && typeof preflight === 'function') {
        jobs.push(preflight(algorithmId));
      }
      return Promise.all(jobs);
    })().catch(() => null).finally(() => prewarmInflight.delete(key));
    prewarmInflight.set(key, task);
    return task;
  };

  const start = async aid => {
    const token = ++openEpoch;
    const state = getState?.() || {};
    const algorithm = (state.algorithms || []).find(item => String(item?.id || '') === String(aid || ''));
    const externalChangLian = String(algorithm?.source_type || '').toUpperCase() === 'EXTERNAL'
      && ['CHANG_LIAN', 'CHANGLIAN'].includes(String(algorithm?.provider_type || '').toUpperCase());
    const needsHydration = !trainingCreationInputsReady(state);
    const externalPreflightFresh = externalChangLian
      && typeof preflightFresh === 'function'
      && preflightFresh(aid) === true;
    const needsExternalPreflight = externalChangLian && !externalPreflightFresh;
    const needsPreparation = needsHydration || needsExternalPreflight;

    // Cached training inputs and a recent authoritative external preflight are already usable.
    // Open the real form immediately instead of flashing a temporary preparation modal.
    if (!needsPreparation) return openForm(aid);

    showShell(aid, token);
    try {
      await Promise.all([
        hydrate(),
        needsExternalPreflight && typeof preflight === 'function' ? preflight(aid) : Promise.resolve(null),
      ]);
    } catch (error) {
      if (!destroyed && token === openEpoch && shellIsCurrent(token, aid)) {
        renderShellError(token, aid, error);
        notify(error?.message || String(error));
      }
      return null;
    }
    if (destroyed || token !== openEpoch || !shellIsCurrent(token, aid)) return null;
    dismissShell(token, aid);
    return openForm(aid);
  };

  window.startAlgorithmTraining429 = start;
  window.startAlgorithmTraining423 = start;
  const runtime = Object.freeze({
    hydrate,
    start,
    prewarm,
    build: 'training-create-hydration-422536',
    destroy() {
      destroyed = true;
      openEpoch += 1;
      prewarmInflight.clear();
      if (window.startAlgorithmTraining429 === start) window.startAlgorithmTraining429 = openForm;
      if (window.TrainingCreateHydrationRuntime === runtime) window.TrainingCreateHydrationRuntime = null;
      window.__trainingCreateHydrationInstalled = false;
    },
  });
  window.TrainingCreateHydrationRuntime = runtime;
  window.__trainingCreateHydrationInstalled = true;
  return runtime;
}
