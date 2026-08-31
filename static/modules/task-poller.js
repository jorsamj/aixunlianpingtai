const ACTIVE = new Set(['QUEUED', 'RUNNING', 'CANCEL_REQUESTED']);

export function normalizeTaskStatus(value) {
  return String(value || '').trim().toUpperCase();
}

export function isTaskActive(value) {
  return ACTIVE.has(normalizeTaskStatus(value));
}

export function taskProgress(task = {}) {
  const clamp = value => Math.max(0, Math.min(100, Number(value) || 0));
  return {
    percent: clamp(task.progress),
    completed: Math.max(0, Number(task.completed_count) || 0),
    total: Math.max(0, Number(task.total_count) || 0),
    failed: Math.max(0, Number(task.failed_count) || 0)
  };
}

export function createTaskPoller({load, onUpdate, onError = () => {}, delay = 1600, schedule = setTimeout, cancelSchedule = clearTimeout}) {
  let stopped = false;
  let timer = null;
  let generation = 0;
  async function refresh() {
    if (stopped) return null;
    const token = ++generation;
    try {
      const task = await load();
      if (stopped || token !== generation) return null;
      onUpdate(task);
      if (isTaskActive(task?.status)) timer = schedule(refresh, delay);
      return task;
    } catch (error) {
      if (!stopped && token === generation) onError(error);
      return null;
    }
  }
  return {
    refresh,
    start: refresh,
    stop() {
      stopped = true;
      generation += 1;
      if (timer != null) cancelSchedule(timer);
      timer = null;
    }
  };
}
