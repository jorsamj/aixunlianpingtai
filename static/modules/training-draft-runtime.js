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

function numericInput(id) {
  if (typeof document === 'undefined') return null;
  const raw = document.getElementById(id)?.value;
  if (raw == null || raw === '') return null;
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
  const delayedSyncTimers = [];

  function inheritanceFor(s) {
    const algorithmId = String(s.train428AlgorithmId || '').trim();
    const algorithm = (s.algorithms || []).find(item => String(item?.id || '') === algorithmId) || null;
    return algorithm ? trainingInheritanceFromAlgorithm(algorithm) : {
      hasAny: false, hasPrevious: false, blocked: false, legacy: false, codes: [], versionId: '',
    };
  }

  function sync() {
    if (destroyed) return null;
    const s = state();
    const inheritance = inheritanceFor(s);
    let draft = trainingDraftFromLegacyState(s, {
      inheritedLabelCodes: inheritance.codes,
      inheritancePending: inheritance.legacy,
      baseVersionId: inheritance.versionId,
    });

    // Priority is still owned by the legacy train-v3 DOM in this migration phase.
    // Read it into the canonical draft so submit and display state cannot diverge.
    const priority = numericInput('tr429Priority');
    if (priority != null && priority !== draft.priority) {
      draft = createTrainingDraft({...draft, priority});
    }

    s.trainingDraft = draft;
    s.trainingDraftInheritance = inheritance;
    return draft;
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
      delayedSyncTimers.push(setTimeout(() => sync(), delay));
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

  document?.addEventListener?.('change', onChange);
  document?.addEventListener?.('input', onInput);
  document?.addEventListener?.('click', onClick);

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
    current() { return state().trainingDraft || sync(); },
    inheritance() { return state().trainingDraftInheritance || inheritanceFor(state()); },
    destroy() {
      destroyed = true;
      for (const timer of delayedSyncTimers) clearTimeout(timer);
      delayedSyncTimers.length = 0;
      document?.removeEventListener?.('change', onChange);
      document?.removeEventListener?.('input', onInput);
      document?.removeEventListener?.('click', onClick);
      if (window.fetch === wrappedFetch) window.fetch = originalFetch;
      if (window.TrainingDraftRuntime === runtime) window.TrainingDraftRuntime = null;
      window.__trainingDraftRuntimeInstalled = false;
    },
  };
  window.TrainingDraftRuntime = runtime;
  window.__trainingDraftRuntimeInstalled = true;
  return runtime;
}
