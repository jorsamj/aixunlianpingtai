export function queueWindow(ids, activeId, windowSize = 9) {
  const rows = [...ids];
  const bounded = Math.max(1, Math.floor(Number(windowSize) || 9));
  if (rows.length <= bounded) return rows;
  const active = Math.max(0, rows.indexOf(activeId));
  const half = Math.floor(bounded / 2);
  const start = Math.max(0, Math.min(rows.length - bounded, active - half));
  return rows.slice(start, start + bounded);
}


export function createAnnotationWorkbench({
  load,
  save,
  apply,
  beforeLoad,
  cacheTtlMs = 60_000,
}) {
  let requestToken = 0;
  let cacheGeneration = 0;
  let dirty = false;
  let activeId = null;
  const cache = new Map();
  const inflight = new Map();
  const ttl = Number.isFinite(Number(cacheTtlMs)) ? Math.max(0, Number(cacheTtlMs)) : 60_000;

  function cached(id) {
    const key = String(id);
    const entry = cache.get(key);
    if (!entry) return null;
    const age = Date.now() - Number(entry.loadedAt || 0);
    if (ttl <= 0 || age < 0 || age > ttl) {
      cache.delete(key);
      return null;
    }
    return entry;
  }

  function remember(id, value) {
    if (ttl <= 0 || value == null) return value;
    cache.set(String(id), {value, loadedAt: Date.now()});
    return value;
  }

  function loadOne(id, token = requestToken) {
    const key = String(id);
    const hit = cached(key);
    if (hit) return Promise.resolve(hit.value);
    if (inflight.has(key)) return inflight.get(key);
    const generation = cacheGeneration;
    const pending = Promise.resolve(load(key, token)).then(value => {
      if (generation === cacheGeneration) remember(key, value);
      return value;
    }).finally(() => {
      if (inflight.get(key) === pending) inflight.delete(key);
    });
    inflight.set(key, pending);
    return pending;
  }

  return {
    get activeId() { return activeId; },
    get dirty() { return dirty; },
    markDirty() { dirty = true; },
    markSaved() { dirty = false; },
    remember,
    prefetch(ids = []) {
      const unique = [...new Set(ids.map(String).filter(Boolean))]
        .filter(id => id !== activeId);
      return Promise.allSettled(unique.map(id => loadOne(id)));
    },
    async open(id) {
      const nextId = String(id);
      if (activeId && activeId !== nextId && dirty) {
        const saved = await save();
        if (!saved) return false;
        dirty = false;
      }
      const token = ++requestToken;
      const hit = cached(nextId);
      beforeLoad?.(nextId, {token, cached: Boolean(hit)});
      const result = hit ? hit.value : await loadOne(nextId, token);
      if (token !== requestToken) return false;
      activeId = nextId;
      apply(result, token);
      return true;
    },
    invalidate(id = null) {
      requestToken += 1;
      cacheGeneration += 1;
      if (id == null) cache.clear();
      else cache.delete(String(id));
    },
  };
}
