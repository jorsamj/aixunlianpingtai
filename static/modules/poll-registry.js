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
  let originalSetupPagePolling = null;
  let wrappedSetupPagePolling = null;

  function state() { return getState?.() || {}; }

  function adoptLegacy() {
    const s = state();
    registry.adopt('training-jobs', trainingOwners, s.jobPollTimer);
    registry.adopt('sources', '素材接入', s.source422Timer);
    registry.adopt('auto-label', ['自动标注', '自动标注及清洗'], s.auto422Timer);
    registry.adopt('video-frames', '视频切帧', window.__videoFramePollTimer);
    registry.adopt('prelabel', ['自动标注', '自动标注及清洗'], window.__prelabelPollTimer);
    return registry.snapshot();
  }

  function clearLegacyReferences(nextPage) {
    const s = state();
    const page = String(nextPage || '');
    if (!trainingOwners.includes(page)) s.jobPollTimer = null;
    if (page !== '素材接入') s.source422Timer = null;
    if (!['自动标注', '自动标注及清洗'].includes(page)) s.auto422Timer = null;
    if (page !== '视频切帧') window.__videoFramePollTimer = null;
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

  function installTrainingJobCreationBridge() {
    const current = window.setupPagePolling;
    if (typeof current !== 'function' || current.__pollRegistryCreationWrapped) return false;
    originalSetupPagePolling = current;
    wrappedSetupPagePolling = function (...args) {
      const result = current.apply(this, args);
      replaceTrainingJobTimer();
      adoptLegacy();
      return result;
    };
    wrappedSetupPagePolling.__pollRegistryCreationWrapped = true;
    wrappedSetupPagePolling.__pollRegistryCreationOriginal = current;
    window.setupPagePolling = wrappedSetupPagePolling;
    replaceTrainingJobTimer();
    adoptLegacy();
    return true;
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
    rebindCreation: installTrainingJobCreationBridge,
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
      const s = state();
      s.jobPollTimer = null;
      if (window.PollRegistryRuntime === runtime) window.PollRegistryRuntime = null;
      window.__pollRegistryInstalled = false;
    },
  };

  window.PollRegistryRuntime = runtime;
  window.__pollRegistryInstalled = true;
  adoptLegacy();
  installTrainingJobCreationBridge();
  return runtime;
}
