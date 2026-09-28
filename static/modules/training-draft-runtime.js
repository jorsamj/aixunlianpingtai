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
  trainingBaseVersionFromAlgorithm,
  directControlIds = [],
} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__trainingDraftRuntimeInstalled) return window.TrainingDraftRuntime;
  if (![createTrainingDraft, trainingBaseVersionFromAlgorithm].every(fn => typeof fn === 'function')) {
    throw new Error('TrainingDraftRuntime missing training draft dependencies');
  }

  const state = () => getState?.() || {};
  const directControlIdSet = new Set((directControlIds || []).map(value => String(value || '')).filter(Boolean));
  const subscribers = new Set();
  let destroyed = false;
  let syncQueued = false;
  let directControlSkips = 0;
  let initializationCount = 0;

  function baseFor(s, algorithmId = s.trainingDraft?.algorithmId) {
    const id = String(algorithmId || '').trim();
    const algorithm = (s.algorithms || []).find(item => String(item?.id || '') === id) || null;
    return algorithm ? trainingBaseVersionFromAlgorithm(algorithm) : {
      hasAny: false, hasPrevious: false, blocked: false, versionId: '',
    };
  }

  function withLiveControls(draft) {
    if (!draft) return draft;
    const experiment = numericInput('trV3Experiment');
    const validation = numericInput('trV3Validation');
    const priority = numericInput('tr429Priority');
    const strategy = inputValue('trV3ResourceStrategy');
    const profile = inputValue('trV3ResourceProfile');
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
        profile: profile ?? draft.resource?.profile,
        device: device ?? draft.resource?.device,
        gpuPolicy: gpuPolicy ?? draft.resource?.gpuPolicy,
      },
    });
  }

  function notifySubscribers(type, draft, patch = null) {
    if (destroyed || !subscribers.size) return;
    const event = {type, draft, patch};
    for (const listener of [...subscribers]) {
      try {
        listener(event);
      } catch (error) {
        console.error?.('TrainingDraftRuntime subscriber failed', error);
      }
    }
  }

  function commitDraft(s, draft, base, {type = 'sync', patch = null} = {}) {
    s.trainingDraft = draft;
    s.trainingDraftBase = base;
    delete s.trainingDraftInheritance;
    window.TrainingSubmitRuntime?.updateReadiness?.();
    notifySubscribers(type, draft, patch);
    return draft;
  }

  function initializeCanonical(s) {
    const base = baseFor(s, '');
    const draft = withLiveControls(createTrainingDraft({baseVersionId: base.versionId || ''}));
    initializationCount += 1;
    return {draft, base};
  }

  function normalizeCanonical(s, draft) {
    const base = baseFor(s, draft?.algorithmId);
    const normalized = withLiveControls(createTrainingDraft({
      ...(draft || {}),
      baseVersionId: base.versionId || '',
    }));
    return {draft: normalized, base};
  }

  function sync() {
    if (destroyed) return null;
    const s = state();
    const result = s.trainingDraft
      ? normalizeCanonical(s, s.trainingDraft)
      : initializeCanonical(s);
    return commitDraft(s, result.draft, result.base, {type: 'sync'});
  }

  function update(patch = {}) {
    if (destroyed) return null;
    const s = state();
    const baseDraft = s.trainingDraft || initializeCanonical(s).draft;
    const next = createTrainingDraft({
      ...baseDraft,
      ...patch,
      resource: {...(baseDraft?.resource || {}), ...(patch.resource || {})},
      config: {...(baseDraft?.config || {}), ...(patch.config || {})},
    });
    const result = normalizeCanonical(s, next);
    return commitDraft(s, result.draft, result.base, {type: 'update', patch});
  }

  function subscribe(listener) {
    if (destroyed || typeof listener !== 'function') return () => {};
    subscribers.add(listener);
    return () => subscribers.delete(listener);
  }

  function scheduleSync() {
    if (destroyed || syncQueued) return;
    syncQueued = true;
    queueMicrotask(() => {
      syncQueued = false;
      sync();
    });
  }

  function relevantTrainingEvent(event) {
    const target = event?.target;
    if (!target?.closest) return false;
    if (target.closest('.training-label-contract')) return false;
    return Boolean(target.closest('.train429-create') || target.closest('.train-v3-picker'));
  }

  function ownedDirectControl(event) {
    const id = String(event?.target?.id || '');
    if (!id || !directControlIdSet.has(id)) return false;
    directControlSkips += 1;
    return true;
  }

  const onChange = event => {
    if (ownedDirectControl(event)) return;
    if (relevantTrainingEvent(event)) scheduleSync();
  };
  const onInput = event => {
    if (ownedDirectControl(event)) return;
    if (relevantTrainingEvent(event)) scheduleSync();
  };
  const onClick = event => {
    if (ownedDirectControl(event)) return;
    if (relevantTrainingEvent(event)) scheduleSync();
  };

  if (typeof document !== 'undefined') {
    document.addEventListener?.('change', onChange);
    document.addEventListener?.('input', onInput);
    document.addEventListener?.('click', onClick);
  }

  sync();

  const runtime = {
    build: 'training-draft-runtime-422518',
    sync,
    update,
    subscribe,
    current() { return state().trainingDraft || sync(); },
    base() { return state().trainingDraftBase || baseFor(state()); },
    materialIds() {
      const draft = state().trainingDraft || sync();
      return [...(draft?.materialIds || [])];
    },
    setMaterialIds(ids = []) {
      const normalized = [...new Set((ids || []).map(value => String(value || '').trim()).filter(Boolean))];
      return update({materialIds: normalized});
    },
    toggleMaterialId(id) {
      const value = String(id || '').trim();
      if (!value) return state().trainingDraft || sync();
      const selected = new Set(runtime.materialIds());
      if (selected.has(value)) selected.delete(value);
      else selected.add(value);
      return runtime.setMaterialIds([...selected]);
    },
    state() {
      return {
        directControlSkips,
        initializationCount,
        subscribers: subscribers.size,
        networkOwner: false,
        classicWrapperOwner: false,
        labelInheritanceOwner: false,
      };
    },
    destroy() {
      destroyed = true;
      subscribers.clear();
      if (typeof document !== 'undefined') {
        document.removeEventListener?.('change', onChange);
        document.removeEventListener?.('input', onInput);
        document.removeEventListener?.('click', onClick);
      }
      if (window.TrainingDraftRuntime === runtime) window.TrainingDraftRuntime = null;
      window.__trainingDraftRuntimeInstalled = false;
    },
  };
  window.TrainingDraftRuntime = runtime;
  window.__trainingDraftRuntimeInstalled = true;
  return runtime;
}
