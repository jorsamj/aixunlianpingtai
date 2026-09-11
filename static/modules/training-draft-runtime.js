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

function checkboxInput(id) {
  if (typeof document === 'undefined') return null;
  const element = document.getElementById(id);
  return element ? Boolean(element.checked) : null;
}

function normalizedCache(value) {
  if (value === false || value === true) return value;
  const raw = String(value ?? '').trim();
  if (!raw || raw.toLowerCase() === 'false') return false;
  if (raw.toLowerCase() === 'true') return true;
  return raw;
}

export function installTrainingDraftRuntime({
  getState,
  createTrainingDraft,
  trainingDraftFromLegacyState,
  trainingDraftToRequest,
  trainingInheritanceFromAlgorithm,
  directControlIds = [],
} = {}) {
  if (typeof window === 'undefined' || typeof window.fetch !== 'function') return null;
  if (window.__trainingDraftRuntimeInstalled) return window.TrainingDraftRuntime;
  if (![createTrainingDraft, trainingDraftFromLegacyState, trainingDraftToRequest, trainingInheritanceFromAlgorithm].every(fn => typeof fn === 'function')) {
    throw new Error('TrainingDraftRuntime missing training draft dependencies');
  }

  const state = () => getState?.() || {};
  const originalFetch = window.fetch.bind(window);
  const directControlIdSet = new Set((directControlIds || []).map(value => String(value || '')).filter(Boolean));
  let destroyed = false;
  let syncQueued = false;
  let directWrites = 0;
  let directControlSkips = 0;
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

    const previousConfig = s.train428Config || {};
    const nextConfig = {
      ...previousConfig,
      ...draft.config,
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
    if (!relevantTrainingEvent(event)) return;
    scheduleSync();
    scheduleDelayedSyncs();
  };

  if (typeof document !== 'undefined') {
    document.addEventListener?.('change', onChange);
    document.addEventListener?.('input', onInput);
    document.addEventListener?.('click', onClick);
  }

  function settingsPatch(s) {
    if (typeof document === 'undefined' || !document.getElementById('ts428Epoch')) return null;
    const current = s.trainingDraft || fromLegacy(s).draft;
    const base = {...(s.train428Config || {}), ...(current.config || {})};
    const number = (id, key, fallback = 0) => numericInput(id) ?? base[key] ?? fallback;
    const text = (id, key, fallback = '') => inputValue(id) ?? base[key] ?? fallback;
    const checked = (id, key, fallback = false) => checkboxInput(id) ?? base[key] ?? fallback;
    const low = number('ts428Low', 'continue_threshold', 0) / (document.getElementById('ts428Low') ? 100 : 1);
    const goal = number('ts428Goal', 'stop_threshold', .9) / (document.getElementById('ts428Goal') ? 100 : 1);
    if (goal > 0 && low > 0 && low >= goal) return null;

    const cache = normalizedCache(text('ts428Cache', 'cache', false));
    const convertControls = [...(document.querySelectorAll?.('.ts428AutoConvert') || [])];
    const config = {
      ...base,
      model: text('ts428Model', 'model', ''),
      epochs: number('ts428Epoch', 'epochs', 100),
      imgsz: number('ts428Size', 'imgsz', 640),
      batch: number('ts428Batch', 'batch', 8),
      eval_interval: Math.max(1, number('ts428EvalInt', 'eval_interval', 10)),
      val_max_samples: Math.max(0, number('ts428ValN', 'val_max_samples', 0)),
      eval_metric: text('ts428Metric', 'eval_metric', 'map50'),
      continue_threshold: low,
      stop_threshold: goal,
      optimizer: text('ts428Opt', 'optimizer', 'auto'),
      patience: number('ts428Patience', 'patience', 100),
      workers: number('ts428Workers', 'workers', 0),
      lr0: number('ts428Lr0', 'lr0', .01),
      lrf: number('ts428Lrf', 'lrf', .01),
      momentum: number('ts428Momentum', 'momentum', .937),
      weight_decay: number('ts428WD', 'weight_decay', .0005),
      warmup_epochs: number('ts428Warmup', 'warmup_epochs', 3),
      close_mosaic: number('ts428CloseMosaic', 'close_mosaic', 10),
      mosaic: number('ts428Mosaic', 'mosaic', 1),
      mixup: number('ts428Mixup', 'mixup', 0),
      hsv_h: number('ts428HsvH', 'hsv_h', .015),
      hsv_s: number('ts428HsvS', 'hsv_s', .7),
      hsv_v: number('ts428HsvV', 'hsv_v', .4),
      degrees: number('ts428Degrees', 'degrees', 0),
      translate: number('ts428Translate', 'translate', .1),
      scale: number('ts428Scale', 'scale', .5),
      shear: number('ts428Shear', 'shear', 0),
      perspective: number('ts428Perspective', 'perspective', 0),
      flipud: number('ts428Flipud', 'flipud', 0),
      fliplr: number('ts428Fliplr', 'fliplr', .5),
      multi_scale: number('ts428MultiScale', 'multi_scale', 0),
      save_period: number('ts428Save', 'save_period', -1),
      freeze: number('ts428Freeze', 'freeze', 0),
      seed: number('ts428Seed', 'seed', 0),
      cache,
      pretrained: checked('ts428Pretrained', 'pretrained', true),
      amp: checked('ts428Amp', 'amp', true),
      deterministic: checked('ts428Det', 'deterministic', true),
      cos_lr: checked('ts428Cos', 'cos_lr', false),
      single_cls: checked('ts428SingleCls', 'single_cls', false),
      rect: checkboxInput('ts415Rect') ?? checkboxInput('ts428Rect') ?? base.rect ?? false,
      auto_convert_targets: convertControls.length
        ? convertControls.filter(control => control.checked).map(control => String(control.value))
        : [...(base.auto_convert_targets || [])],
    };
    return {
      config,
      resource: {
        batch: config.batch,
        workers: config.workers,
        cache,
      },
    };
  }

  function directMutationFor(name, args, s) {
    if (name === 'startAlgorithmTraining429') {
      const algorithmId = String(args?.[0] || '').trim();
      if (!algorithmId) return null;
      return {
        patch: {
          algorithmId,
          materialIds: [],
          testMaterialIds: [],
          splitMode: 'random_test_from_training_pool',
          experimentPercent: 20,
          validationPercent: 20,
          newLabelCodes: [],
        },
        resync: true,
      };
    }

    if (name === 'setTrainSplitModeV3') {
      const splitMode = String(args?.[0] || '').trim();
      return splitMode ? {patch: {splitMode}, resync: false} : null;
    }

    if (name === 'confirmTrainMaterialPickerV3') {
      const picker = s.trainMaterialPickerV3;
      if (!picker || !(picker.selected instanceof Set)) return null;
      const selected = [...picker.selected].map(String);
      const current = s.trainingDraft || fromLegacy(s).draft;
      const selectedSet = new Set(selected);
      if (picker.role === 'test') {
        return {
          patch: {
            materialIds: (current.materialIds || []).filter(id => !selectedSet.has(String(id))),
            testMaterialIds: selected,
          },
          resync: false,
        };
      }
      if (picker.role === 'train') {
        return {
          patch: {
            materialIds: selected,
            testMaterialIds: (current.testMaterialIds || []).filter(id => !selectedSet.has(String(id))),
          },
          resync: false,
        };
      }
    }

    if (name === 'saveTrainSettings428') {
      const patch = settingsPatch(s);
      return patch ? {patch, resync: false} : null;
    }
    return null;
  }

  function wrapLegacyMutation(name) {
    const original = window[name];
    if (typeof original !== 'function' || original.__trainingDraftMutationWrapped) return;
    const wrapped = function (...args) {
      const direct = directMutationFor(name, args, state());
      if (direct) {
        update(direct.patch);
        directWrites += 1;
      }
      const result = original.apply(this, args);
      const settle = () => {
        if (direct && !direct.resync) {
          const s = state();
          mirrorDraftToLegacy(s, s.trainingDraft);
          return;
        }
        sync();
        scheduleDelayedSyncs();
      };
      if (result && typeof result.then === 'function') return Promise.resolve(result).finally(settle);
      settle();
      return result;
    };
    wrapped.__trainingDraftMutationWrapped = true;
    wrapped.__trainingDraftDirectWrite = true;
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
    build: 'training-draft-runtime-422506',
    sync,
    update,
    current() { return state().trainingDraft || sync(); },
    inheritance() { return state().trainingDraftInheritance || inheritanceFor(state()); },
    state() { return {directWrites, directControlSkips}; },
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
