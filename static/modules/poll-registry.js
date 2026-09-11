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
    this.entries.set(key, {timer, owners: ownerSet(ownerPages), clearFn});
    return true;
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
    }));
  }
}

export function installPollRegistry({getState} = {}) {
  if (typeof window === 'undefined') return null;
  if (window.__pollRegistryInstalled) return window.PollRegistryRuntime;
  const registry = new PollRegistry();

  function state() { return getState?.() || {}; }

  function adoptLegacy() {
    const s = state();
    registry.adopt('training-jobs', ['训练任务', '检测台'], s.jobPollTimer);
    registry.adopt('sources', '素材接入', s.source422Timer);
    registry.adopt('auto-label', ['自动标注', '自动标注及清洗'], s.auto422Timer);
    registry.adopt('video-frames', '视频切帧', window.__videoFramePollTimer);
    registry.adopt('prelabel', ['自动标注', '自动标注及清洗'], window.__prelabelPollTimer);
    return registry.snapshot();
  }

  function clearLegacyReferences(nextPage) {
    const s = state();
    const page = String(nextPage || '');
    if (!['训练任务', '检测台'].includes(page)) s.jobPollTimer = null;
    if (page !== '素材接入') s.source422Timer = null;
    if (!['自动标注', '自动标注及清洗'].includes(page)) s.auto422Timer = null;
    if (page !== '视频切帧') window.__videoFramePollTimer = null;
    if (!['自动标注', '自动标注及清洗'].includes(page)) window.__prelabelPollTimer = null;
  }

  const runtime = {
    registry,
    adoptLegacy,
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
      if (window.PollRegistryRuntime === runtime) window.PollRegistryRuntime = null;
      window.__pollRegistryInstalled = false;
    },
  };

  window.PollRegistryRuntime = runtime;
  window.__pollRegistryInstalled = true;
  adoptLegacy();
  return runtime;
}
