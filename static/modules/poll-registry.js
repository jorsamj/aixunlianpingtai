function ownerSet(ownerPages) {
  return new Set(Array.isArray(ownerPages) ? ownerPages.map(String) : [String(ownerPages || '')]);
}

const TRAINING_POLL_STATUSES = new Set([
  'queued',
  'waiting',
  'pending',
  'starting',
  'running',
  'pausing',
  'resuming',
  'stopping',
  'cancel_requested',
]);

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
  const trainingOwner = '训练任务';
  const videoOwner = '视频切帧';
  const sourceOwner = '素材接入';
  const cleanOwner = '自动标注及清洗';

  function state() { return getState?.() || {}; }

  function clearLegacyReferences(nextPage) {
    const s = state();
    const page = String(nextPage || '');
    if (page !== videoOwner) {
      if (s.video424Timer != null) {
        try { clearTimeout(s.video424Timer); } catch (_) {}
      }
      s.video424Timer = null;
    }
  }

  function trainingTaskNeedsPolling(task) {
    return TRAINING_POLL_STATUSES.has(String(task?.status || '').toLowerCase());
  }

  function replaceTrainingJobTimer() {
    const s = state();
    registry.clear('training-jobs');
    if (String(s.page || '') !== trainingOwner) return null;
    if (!s.project?.id) return null;
    if (!(s.jobs || []).some(trainingTaskNeedsPolling)) return null;

    return registry.startTimeout(
      'training-jobs',
      trainingOwner,
      async () => {
        const current = state();
        if (String(current.page || '') !== trainingOwner) return;
        if (!current.project?.id) return;
        try {
          if (typeof window.TrainingTaskRuntime?.refresh === 'function') {
            await window.TrainingTaskRuntime.refresh({render: true, source: 'poll'});
          } else if (typeof window.refreshJobsOnly === 'function') {
            await window.refreshJobsOnly();
          }
        } catch (_) {
          // Keep the last truthful state. A still-dynamic task may retry next cycle.
        } finally {
          replaceTrainingJobTimer();
        }
      },
      2000,
    );
  }

  function videoTaskActive(task) {
    const helper = window.PlatformCore?.video?.isActiveVideoTask;
    if (typeof helper === 'function') return Boolean(helper(task));
    return ['QUEUED', 'RUNNING', 'CANCEL_REQUESTED'].includes(String(task?.status || '').toUpperCase());
  }

  function replaceVideo424Timer() {
    const s = state();
    if (s.video424Timer != null) {
      try { clearTimeout(s.video424Timer); } catch (_) {}
      s.video424Timer = null;
    }
    registry.clear('video-frames');
    if (String(s.page || '') !== videoOwner) return null;
    if (!(s.video424 || []).some(videoTaskActive)) return null;

    s.video424Timer = registry.startTimeout(
      'video-frames',
      videoOwner,
      async () => {
        const current = state();
        if (String(current.page || '') !== videoOwner) return;
        if (!current.project?.id) return;
        if (typeof window.refreshVideo424Delta === 'function') await window.refreshVideo424Delta();
      },
      2000,
    );
    return s.video424Timer;
  }


  function cleanTaskActive(task) {
    const helper = window.PlatformCore?.cleaning?.isActiveCleanTask;
    if (typeof helper === 'function') return Boolean(helper(task));
    return ['queued', 'running'].includes(String(task?.status || '').toLowerCase());
  }

  function replaceCleanTaskTimer() {
    const s = state();
    registry.clear('clean-tasks-v47');
    if (String(s.page || '') !== cleanOwner) return null;
    if (String(s.v427OpsTab || 'label') !== 'clean') return null;
    if (!(s.clean427 || []).some(cleanTaskActive)) return null;

    return registry.startTimeout(
      'clean-tasks-v47',
      cleanOwner,
      async () => {
        const current = state();
        if (String(current.page || '') !== cleanOwner) return;
        if (String(current.v427OpsTab || 'label') !== 'clean') return;
        if (!current.project?.id) return;
        if (typeof window.refreshCleanOps427Delta === 'function') {
          await window.refreshCleanOps427Delta();
        }
      },
      2200,
    );
  }

  function replaceSourceTimer() {
    const s = state();
    registry.clear('sources');
    if (String(s.page || '') !== sourceOwner) return null;

    const callback = async () => {
      const current = state();
      if (String(current.page || '') !== sourceOwner) return;
      if (!current.project?.id) return;
      if (typeof window.refreshSources422 === 'function') await window.refreshSources422();
    };
    return registry.startInterval(
      'sources',
      sourceOwner,
      callback,
      2500,
    );
  }

  const runtime = {
    registry,
    startInterval(key, ownerPages, callback, delay, options) {
      return registry.startInterval(key, ownerPages, callback, delay, options);
    },
    startTimeout(key, ownerPages, callback, delay, options) {
      return registry.startTimeout(key, ownerPages, callback, delay, options);
    },
    clear(key) { return registry.clear(key); },
    replaceTrainingJobTimer,
    replaceVideo424Timer,
    replaceCleanTaskTimer,
    replaceSourceTimer,
    beforeNavigate(nextPage) {
      registry.leave(nextPage);
      clearLegacyReferences(nextPage);
    },
    afterNavigate(page) {
      if (String(page || state().page || '') === trainingOwner) return replaceTrainingJobTimer();
      return null;
    },
    snapshot() { return registry.snapshot(); },
    destroy() {
      registry.clearAll();
      const s = state();
      s.video424Timer = null;
      if (window.PollRegistryRuntime === runtime) window.PollRegistryRuntime = null;
      window.__pollRegistryInstalled = false;
    },
  };

  window.PollRegistryRuntime = runtime;
  window.__pollRegistryInstalled = true;
  replaceTrainingJobTimer();
  replaceVideo424Timer();
  replaceCleanTaskTimer();
  replaceSourceTimer();
  return runtime;
}
