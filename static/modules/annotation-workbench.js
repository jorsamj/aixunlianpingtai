export function queueWindow(ids, activeId, windowSize = 9) {
  const rows = [...ids];
  const bounded = Math.max(1, Math.floor(Number(windowSize) || 9));
  if (rows.length <= bounded) return rows;
  const active = Math.max(0, rows.indexOf(activeId));
  const half = Math.floor(bounded / 2);
  const start = Math.max(0, Math.min(rows.length - bounded, active - half));
  return rows.slice(start, start + bounded);
}


export function createAnnotationWorkbench({load, save, apply}) {
  let requestToken = 0;
  let dirty = false;
  let activeId = null;
  return {
    get activeId() { return activeId; },
    get dirty() { return dirty; },
    markDirty() { dirty = true; },
    markSaved() { dirty = false; },
    async open(id) {
      const nextId = String(id);
      if (activeId && activeId !== nextId && dirty) {
        const saved = await save();
        if (!saved) return false;
        dirty = false;
      }
      const token = ++requestToken;
      const result = await load(nextId, token);
      if (token !== requestToken) return false;
      activeId = nextId;
      apply(result, token);
      return true;
    },
    invalidate() { requestToken += 1; },
  };
}
