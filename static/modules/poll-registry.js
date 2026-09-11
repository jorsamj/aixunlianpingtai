function ownerSet(ownerPages) {
  return new Set(Array.isArray(ownerPages) ? ownerPages.map(String) : [String(ownerPages || '')]);
}

export class PollRegistry {
  constructor() {
    this.entries = new Map();
  }

  adopt(key, ownerPages, timer, clearFn = clearInterval) {
    if (timer == null) return false;
    const existing = this.entries.get(key);
    if (existing?.timer === timer) return true;
    if (existing) {
      try { existing.clearFn(existing.timer); } catch (_) {}
    }
    this.entries.set(key, {timer, owners: ownerSet(ownerPages), clearFn, managed: false});
    return true;
  }

  startInterval(key, ownerPages, callback, delay, {setFn = setInterval, clearFn = clearInterval} = {}) {
    if (typeof callback !== 'function') throw new Error('poll callback must be a function');
    const ms = Number(delay);
    if (!Number.isFinite(ms) || ms <= 0) throw new Error('poll delay must be positive');
    this.clear(key);
    const timer = setFn(callback, ms);
    this.entries.set(key, {timer, owners: ownerSet(ownerPages), clearFn, managed: true, delay: ms});
    return timer;
  }

  startTimeout(key, ownerPages, callback, delay, {setFn = setTimeout, clearFn = clearTimeout} = {}) {
    if (typeof callback !== 'function') throw new Error('poll callback must be a function');
    const ms = Number(delay);
    if (!Number.isFinite(ms) || ms <= 0) throw new Error('poll delay must be positive');
    this.clear(key);
    let timer = null;
    const wrapped = async (...args) => {
      const current = this.entries.get(key);
      if (current?.timer === timer) this.entries.delete(key);
      return callback(...args);
    };
    timer = setFn(wrapped, ms);
    this.entries.set(key, {timer, owners: ownerSet(ownerPages), clearFn, managed: true, delay: ms});
    return timer;
  }

  clear(key) {
    const entry = this.entries.get(key);
    if (!entry) return false;
    try { entry.clearFn(entry.timer); } catch (_) {}
    this.entries.delete(key);
    return true;
  }

  leave(nextPage) {
    const page = String(nextPage || '');
    for (const [key, entry] of [...this.entries]) {
      if (!entry.owners.has(page)) this.clear(key);
    }
  }

  clearAll() {
    for (const key of [...this.entries.keys()]) this.clear(key);
  }

  snapshot() {
    return [...this.entries.entries()].map(([key, entry]) => ({
      key,
      owners: [...entry.owners],
      active: entry.timer != null,
      managed: Boolean(entry.managed),
      delay: entry.delay ?? null,
    }));
  }
}

export function installPollRegistry({getState} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__pollRegistryInstalled) return window.PollRegistryRuntime;
  const registry = new PollRegistry();
  const trainingOwners = ['训练任务', '检测台'];
  const videoOwner = '视频切帧';
  const sourceOwner = '素材接入';
  let originalSetupPagePolling = null;
  let wrappedSetupPagePolling = null;
  let originalRenderSources = null;
  let wrappedRenderSources = null;

  function state() { return getState?.() || {}; }

  function adoptLegacy() {
    const s = state();
    registry.adopt('training-jobs', trainingOwners, s.jobPollTimer);
    registry.adopt('sources', sourceOwner, s.source422Timer);
    registry.adopt('auto-label', ['自动标注', '自动标注及清洗'], s.auto422Timer);
    registry.adopt('video-frames', videoOwner, window.__videoFramePollTimer);
    registry.adopt('prelabel', ['自动标注', '自动标注及清洗'], window.__prelabelPollTimer);
    return registry.snapshot();
  }

  function clearLegacyReferences(nextPage) {
    const s = state();
    const page = String(nextPage || '');
    if (!trainingOwners.includes(page)) s.jobPollTimer = null;
    if (page !== sourceOwner) s.source422Timer = null;
    if (!['自动标注', '自动标注及清洗'].includes(page)) s.auto422Timer = null;
    if (page !== videoOwner) window.__videoFramePollTimer = null;
    if (!['自动标注', '自动标注及清洗'].includes(page)) window.__prelabelPollTimer = null;
  }

  function trainingPollDelay(s) {
    const live = (s.jobs || []).some(job => ['queued', 'running', 'waiting', 'pending'].includes(String(job?.status || '')));
    return live ? 2000 : 5000;
  }

  function replaceTrainingJobTimer() {
    const s = state();
    if (s.jobPollTimer != null) {
      try { clearInterval(s.jobPollTimer); } catch (_) {}
      s.jobPollTimer = null;
    }
    registry.clear('training-jobs');
    if (!trainingOwners.includes(String(s.page || ''))) return null;

    const callback = async () => {
      const current = state();
      if (!trainingOwners.includes(String(current.page || ''))) return;
      if (!current.project?.id) return;
      if (typeof window.refreshJobsOnly === 'function') await window.refreshJobsOnly();
    };
    s.jobPollTimer = registry.startInterval(
      'training-jobs',
      trainingOwners,
      callback,
      trainingPollDelay(s),
    );
    return s.jobPollTimer;
  }

  function replaceVideoFrameTimer() {
    if (window.__videoFramePollTimer != null) {
      try { clearInterval(window.__videoFramePollTimer); } catch (_) {}
      window.__videoFramePollTimer = null;
    }
    registry.clear('video-frames');
    const s = state();
    if (String(s.page || '') !== videoOwner) return null;

    const callback = async () => {
      const current = state();
      if (String(current.page || '') !== videoOwner) return;
      if (!current.project?.id) return;
      if (typeof window.refreshVideoTasksOnly === 'function') await window.refreshVideoTasksOnly();
    };
    window.__videoFramePollTimer = registry.startInterval(
      'video-frames',
      videoOwner,
      callback,
      2500,
    );
    return window.__videoFramePollTimer;
  }

  function replaceSourceTimer() {
    const s = state();
    if (s.source422Timer != null) {
      try { clearInterval(s.source422Timer); } catch (_) {}
      s.source422Timer = null;
    }
    registry.clear('sources');
    if (String(s.page || '') !== sourceOwner) return null;

    const callback = async () => {
      const current = state();
      if (String(current.page || '') !== sourceOwner) return;
      if (!current.project?.id) return;
      if (typeof window.refreshSources422 === 'function') await window.refreshSources422();
    };
    s.source422Timer = registry.startInterval(
      'sources',
      sourceOwner,
      callback,
      2500,
    );
    return s.source422Timer;
  }

  function installPollingCreationBridge() {
    const current = window.setupPagePolling;
    if (typeof current !== 'function' || current.__pollRegistryCreationWrapped) return false;
    originalSetupPagePolling = current;
    wrappedSetupPagePolling = function (...args) {
      const result = current.apply(this, args);
      replaceTrainingJobTimer();
      replaceVideoFrameTimer();
      adoptLegacy();
      return result;
    };
    wrappedSetupPagePolling.__pollRegistryCreationWrapped = true;
    wrappedSetupPagePolling.__pollRegistryCreationOriginal = current;
    window.setupPagePolling = wrappedSetupPagePolling;
    replaceTrainingJobTimer();
    replaceVideoFrameTimer();
    adoptLegacy();
    return true;
  }

  function installSourceCreationBridge() {
    const current = window.renderSources422;
    if (typeof current !== 'function' || current.__pollRegistrySourceWrapped) return false;
    originalRenderSources = current;
    wrappedRenderSources = async function (...args) {
      try {
        return await current.apply(this, args);
      } finally {
        replaceSourceTimer();
        adoptLegacy();
      }
    };
    wrappedRenderSources.__pollRegistrySourceWrapped = true;
    wrappedRenderSources.__pollRegistrySourceOriginal = current;
    window.renderSources422 = wrappedRenderSources;
    if (String(state().page || '') === sourceOwner) replaceSourceTimer();
    adoptLegacy();
    return true;
  }

  function rebindCreation() {
    const page = installPollingCreationBridge();
    const source = installSourceCreationBridge();
    return page || source;
  }

  const runtime = {
    registry,
    adoptLegacy,
    startInterval(key, ownerPages, callback, delay, options) {
      return registry.startInterval(key, ownerPages, callback, delay, options);
    },
    startTimeout(key, ownerPages, callback, delay, options) {
      return registry.startTimeout(key, ownerPages, callback, delay, options);
    },
    clear(key) { return registry.clear(key); },
    replaceTrainingJobTimer,
    replaceVideoFrameTimer,
    replaceSourceTimer,
    rebindCreation,
    beforeNavigate(nextPage) {
      adoptLegacy();
      registry.leave(nextPage);
      clearLegacyReferences(nextPage);
    },
    afterNavigate() {
      adoptLegacy();
    },
    snapshot() { return registry.snapshot(); },
    destroy() {
      registry.clearAll();
      if (wrappedSetupPagePolling && window.setupPagePolling === wrappedSetupPagePolling) {
        window.setupPagePolling = originalSetupPagePolling;
      }
      if (wrappedRenderSources && window.renderSources422 === wrappedRenderSources) {
        window.renderSources422 = originalRenderSources;
      }
      const s = state();
      s.jobPollTimer = null;
      s.source422Timer = null;
      window.__videoFramePollTimer = null;
      if (window.PollRegistryRuntime === runtime) window.PollRegistryRuntime = null;
      window.__pollRegistryInstalled = false;
    },
  };

  window.PollRegistryRuntime = runtime;
  window.__pollRegistryInstalled = true;
  adoptLegacy();
  rebindCreation();
  return runtime;
}
