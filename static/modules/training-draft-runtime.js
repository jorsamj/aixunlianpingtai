function isTrainStart(url, method) {
  return String(method || 'GET').toUpperCase() === 'POST'
    && /\/api\/v12\/projects\/[^/]+\/train\/start(?:\?|$)/.test(String(url || ''));
}

function requestUrl(input) {
  return typeof input === 'string' ? input : String(input?.url || '');
}

function requestMethod(input, init = {}) {
  return String(init?.method || input?.method || 'GET').toUpperCase();
}

function parseBody(init) {
  if (typeof init?.body !== 'string') return null;
  try { return JSON.parse(init.body); } catch (_) { return null; }
}

function inputValue(id) {
  if (typeof document === 'undefined') return null;
  const raw = document.getElementById(id)?.value;
  if (raw == null || raw === '') return null;
  return String(raw);
}

function numericInput(id) {
  const raw = inputValue(id);
  if (raw == null) return null;
  const value = Number(raw);
  return Number.isFinite(value) ? value : null;
}

export function installTrainingDraftRuntime({
  getState,
  createTrainingDraft,
  trainingDraftFromLegacyState,
  trainingDraftToRequest,
  trainingInheritanceFromAlgorithm,
} = {}) {
  if (typeof window === 'undefined' || typeof window.fetch !== 'function') return null;
  if (window.__trainingDraftRuntimeInstalled) return window.TrainingDraftRuntime;
  if (![createTrainingDraft, trainingDraftFromLegacyState, trainingDraftToRequest, trainingInheritanceFromAlgorithm].every(fn => typeof fn === 'function')) {
    throw new Error('TrainingDraftRuntime missing training draft dependencies');
  }

  const state = () => getState?.() || {};
  const originalFetch = window.fetch.bind(window);
  let destroyed = false;
  let syncQueued = false;
  const delayedSyncTimers = new Set();
  const mutationWrappers = [];

  function inheritanceFor(s, algorithmId = s.train428AlgorithmId) {
    const id = String(algorithmId || '').trim();
    const algorithm = (s.algorithms || []).find(item => String(item?.id || '') === id) || null;
    return algorithm ? trainingInheritanceFromAlgorithm(algorithm) : {
      hasAny: false, hasPrevious: false, blocked: false, legacy: false, codes: [], versionId: '',
    };
  }

  function withLiveControls(draft) {
    if (!draft) return draft;
    const experiment = numericInput('trV3Experiment');
    const validation = numericInput('trV3Validation');
    const priority = numericInput('tr429Priority');
    const strategy = inputValue('trV3ResourceStrategy');
    const device = inputValue('trV3Device');
    const gpuPolicy = inputValue('trV3GpuPolicy');

    return createTrainingDraft({
      ...draft,
      experimentPercent: experiment ?? draft.experimentPercent,
      validationPercent: validation ?? draft.validationPercent,
      priority: priority ?? draft.priority,
      resource: {
        ...draft.resource,
        strategy: strategy ?? draft.resource?.strategy,
        device: device ?? draft.resource?.device,
        gpuPolicy: gpuPolicy ?? draft.resource?.gpuPolicy,
      },
    });
  }

  function mirrorDraftToLegacy(s, draft) {
    if (!draft) return;
    if (draft.algorithmId) s.train428AlgorithmId = draft.algorithmId;

    const previousSplit = s.trainSplitV3 || {};
    const train = new Set(draft.materialIds || []);
    const test = new Set(draft.testMaterialIds || []);
    s.trainSplitV3 = {
      ...previousSplit,
      mode: draft.splitMode,
      train,
      test,
      experiment: draft.experimentPercent ?? previousSplit.experiment ?? 20,
      validation: draft.validationPercent,
    };
    s.train429Selected = train;
    s.trainingLabelSelected = new Set(draft.newLabelCodes || []);

    const previousConfig = s.train428Config || {};
    const nextConfig = {
      ...previousConfig,
      resource_strategy: draft.resource?.strategy || previousConfig.resource_strategy || 'auto',
      device: draft.resource?.device || previousConfig.device || 'auto',
      gpu_policy: draft.resource?.gpuPolicy || previousConfig.gpu_policy || 'auto',
      queue_priority: draft.priority,
    };
    if (draft.resource?.batch != null) nextConfig.batch = draft.resource.batch;
    if (draft.resource?.workers != null) nextConfig.workers = draft.resource.workers;
    if (draft.resource?.cache != null) nextConfig.cache = draft.resource.cache;
    s.train428Config = nextConfig;
  }

  function commitDraft(s, draft, inheritance) {
    s.trainingDraft = draft;
    s.trainingDraftInheritance = inheritance;
    mirrorDraftToLegacy(s, draft);
    return draft;
  }

  function fromLegacy(s) {
    const inheritance = inheritanceFor(s);
    const draft = withLiveControls(trainingDraftFromLegacyState(s, {
      inheritedLabelCodes: inheritance.codes,
      inheritancePending: inheritance.legacy,
      baseVersionId: inheritance.versionId,
    }));
    return {draft, inheritance};
  }

  function sync() {
    if (destroyed) return null;
    const s = state();
    const {draft, inheritance} = fromLegacy(s);
    return commitDraft(s, draft, inheritance);
  }

  function update(patch = {}) {
    if (destroyed) return null;
    const s = state();
    const base = s.trainingDraft || fromLegacy(s).draft;
    const next = withLiveControls(createTrainingDraft({
      ...base,
      ...patch,
      resource: {...(base?.resource || {}), ...(patch.resource || {})},
      config: {...(base?.config || {}), ...(patch.config || {})},
    }));
    const inheritance = inheritanceFor(s, next.algorithmId);
    return commitDraft(s, createTrainingDraft({
      ...next,
      baseVersionId: inheritance.versionId || next.baseVersionId,
      inheritedLabelCodes: inheritance.codes,
      inheritancePending: inheritance.legacy,
    }), inheritance);
  }

  function scheduleSync() {
    if (destroyed || syncQueued) return;
    syncQueued = true;
    queueMicrotask(() => {
      syncQueued = false;
      sync();
    });
  }

  function scheduleDelayedSyncs() {
    for (const delay of [0, 80, 220, 500]) {
      const timer = setTimeout(() => {
        delayedSyncTimers.delete(timer);
        sync();
      }, delay);
      delayedSyncTimers.add(timer);
    }
  }

  function relevantTrainingEvent(event) {
    const target = event?.target;
    if (!target?.closest) return false;
    return Boolean(
      target.closest('.train429-create')
      || target.closest('.train-v3-picker')
      || target.closest('#trainingLabelContractPanel')
    );
  }

  const onChange = event => {
    if (relevantTrainingEvent(event)) scheduleSync();
  };
  const onInput = event => {
    if (relevantTrainingEvent(event)) scheduleSync();
  };
  const onClick = event => {
    if (!relevantTrainingEvent(event)) return;
    scheduleSync();
    // Opening/closing pickers and async training-dialog initialization mutate legacy state
    // after the click handler returns; re-sample briefly without observing DOM mutations.
    scheduleDelayedSyncs();
  };

  if (typeof document !== 'undefined') {
    document.addEventListener?.('change', onChange);
    document.addEventListener?.('input', onInput);
    document.addEventListener?.('click', onClick);
  }

  function wrapLegacyMutation(name) {
    const original = window[name];
    if (typeof original !== 'function' || original.__trainingDraftMutationWrapped) return;
    const wrapped = function (...args) {
      const result = original.apply(this, args);
      if (result && typeof result.then === 'function') {
        return Promise.resolve(result).finally(() => {
          sync();
          scheduleDelayedSyncs();
        });
      }
      sync();
      scheduleDelayedSyncs();
      return result;
    };
    wrapped.__trainingDraftMutationWrapped = true;
    wrapped.__trainingDraftMutationOriginal = original;
    window[name] = wrapped;
    mutationWrappers.push({name, original, wrapped});
  }

  for (const name of [
    'startAlgorithmTraining429',
    'confirmTrainMaterialPickerV3',
    'setTrainSplitModeV3',
    'saveTrainSettings428',
  ]) wrapLegacyMutation(name);

  const wrappedFetch = async function (input, init = {}) {
    const url = requestUrl(input);
    const method = requestMethod(input, init);
    if (isTrainStart(url, method)) {
      const payload = parseBody(init);
      if (payload?.algorithm_asset_id) {
        const s = state();
        const draft = sync();
        const inheritance = s.trainingDraftInheritance || {};
        if (inheritance.blocked) {
          throw new Error('该算法已有版本，但没有成功且可继续训练的版本；平台不会回退母算法。');
        }
        if (!draft || String(draft.algorithmId) !== String(payload.algorithm_asset_id)) {
          throw new Error('训练草稿与当前算法不一致，请关闭训练窗口后重新打开。');
        }
        const canonical = trainingDraftToRequest(draft, payload);
        init = {...init, body: JSON.stringify(canonical)};
      }
    }
    return originalFetch(input, init);
  };
  wrappedFetch.__trainingDraftRuntimeWrapped = true;
  wrappedFetch.__trainingDraftRuntimeOriginal = originalFetch;
  window.fetch = wrappedFetch;

  scheduleDelayedSyncs();

  const runtime = {
    sync,
    update,
    current() { return state().trainingDraft || sync(); },
    inheritance() { return state().trainingDraftInheritance || inheritanceFor(state()); },
    destroy() {
      destroyed = true;
      for (const timer of delayedSyncTimers) clearTimeout(timer);
      delayedSyncTimers.clear();
      if (typeof document !== 'undefined') {
        document.removeEventListener?.('change', onChange);
        document.removeEventListener?.('input', onInput);
        document.removeEventListener?.('click', onClick);
      }
      for (const {name, original, wrapped} of mutationWrappers) {
        if (window[name] === wrapped) window[name] = original;
      }
      mutationWrappers.length = 0;
      if (window.fetch === wrappedFetch) window.fetch = originalFetch;
      if (window.TrainingDraftRuntime === runtime) window.TrainingDraftRuntime = null;
      window.__trainingDraftRuntimeInstalled = false;
    },
  };
  window.TrainingDraftRuntime = runtime;
  window.__trainingDraftRuntimeInstalled = true;
  return runtime;
}
