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
  notify = () => {},
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingCreateHydrationInstalled) return window.TrainingCreateHydrationRuntime || null;

  const previousStart = window.startAlgorithmTraining429;
  if (typeof previousStart !== 'function') return null;

  let inflight = null;
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

  const start = async aid => {
    try {
      await hydrate();
    } catch (error) {
      notify(error?.message || String(error));
      return null;
    }
    return previousStart(aid);
  };

  window.startAlgorithmTraining429 = start;
  window.startAlgorithmTraining423 = start;
  const runtime = Object.freeze({hydrate, start, build: 'training-create-hydration-422532'});
  window.TrainingCreateHydrationRuntime = runtime;
  window.__trainingCreateHydrationInstalled = true;
  return runtime;
}
