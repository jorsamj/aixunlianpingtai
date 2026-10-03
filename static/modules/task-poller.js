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


function taskPollingAbortError() {
  const error = new Error('task polling cancelled');
  error.name = 'AbortError';
  return error;
}

export function waitForTaskTerminal({
  initialTask,
  load,
  onUpdate = () => {},
  onError = () => {},
  delay = 1600,
  maxAttempts = 700,
  registry,
  key,
  ownerPages,
} = {}) {
  if (typeof load !== 'function') throw new Error('task terminal waiter requires load');
  if (!registry?.startTimeout || !registry?.clear) throw new Error('task terminal waiter requires PollRegistry');
  const pollKey = String(key || '').trim();
  if (!pollKey) throw new Error('task terminal waiter requires key');
  const limit = Math.max(1, Math.floor(Number(maxAttempts) || 1));
  const ms = Math.max(1, Number(delay) || 1);
  let task = initialTask || {};
  let attempts = 0;
  let settled = false;

  return new Promise((resolve, reject) => {
    const settle = (kind, value) => {
      if (settled) return;
      settled = true;
      if (kind === 'resolve') resolve(value);
      else reject(value);
    };

    const scheduleNext = () => {
      if (settled) return;
      if (attempts >= limit) {
        const error = new Error(`task polling exceeded ${limit} attempts`);
        error.name = 'TimeoutError';
        settle('reject', error);
        return;
      }
      attempts += 1;
      registry.startTimeout(pollKey, ownerPages, tick, ms, {
        onClear: () => settle('reject', taskPollingAbortError()),
      });
    };

    const tick = async () => {
      if (settled) return;
      try {
        task = await load(task);
        if (settled) return;
        onUpdate(task);
        if (isTaskActive(task)) scheduleNext();
        else settle('resolve', task);
      } catch (error) {
        if (settled) return;
        onError(error);
        settle('reject', error);
      }
    };

    onUpdate(task);
    if (isTaskActive(task)) scheduleNext();
    else settle('resolve', task);
  });
}
