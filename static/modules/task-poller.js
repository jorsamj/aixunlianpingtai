import {
  canonicalTaskProgressPercent,
  canonicalTaskStatus,
  isCanonicalTaskActive,
} from './task-runtime-truth.js';

export function normalizeTaskStatus(value) {
  return canonicalTaskStatus(value);
}

export function isTaskActive(value) {
  return isCanonicalTaskActive(value);
}

export function taskProgress(task = {}) {
  return {
    percent: canonicalTaskProgressPercent(task),
    completed: Math.max(0, Number(task.completed_units ?? task.completed_count) || 0),
    total: Math.max(0, Number(task.total_units ?? task.total_count) || 0),
    failed: Math.max(0, Number(task.failed_units ?? task.failed_count) || 0)
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
      if (isTaskActive(task)) timer = schedule(refresh, delay);
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
