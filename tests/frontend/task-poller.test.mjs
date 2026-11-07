import test from 'node:test';
import assert from 'node:assert/strict';

import {createTaskPoller, isTaskActive, taskProgress, waitForTaskTerminal} from '../../static/modules/task-poller.js';

test('only genuine backend running states continue polling', () => {
  assert.equal(isTaskActive('QUEUED'), true);
  assert.equal(isTaskActive('WAITING_RESOURCE'), true);
  assert.equal(isTaskActive('RETRYING'), true);
  assert.equal(isTaskActive('RUNNING'), true);
  assert.equal(isTaskActive('CANCEL_REQUESTED'), true);
  assert.equal(isTaskActive('AWAITING_CONFIRMATION'), false);
  assert.equal(isTaskActive('SUCCEEDED'), false);
  assert.equal(isTaskActive('FAILED'), false);
});

test('task progress uses backend counts and never invents completion', () => {
  assert.deepEqual(taskProgress({progress: 31.7, completed_count: 38, total_count: 120, failed_count: 7}), {
    percent: 31.7, completed: 38, total: 120, failed: 7
  });
  assert.equal(taskProgress({progress: 180}).percent, 100);
  assert.deepEqual(taskProgress({progress_percent: 42, completed_units: 21, total_units: 50, failed_units: 2}), {percent: 42, completed: 21, total: 50, failed: 2});
});

test('poller stops after a terminal backend state', async () => {
  const states = [{status: 'RUNNING'}, {status: 'AWAITING_CONFIRMATION'}];
  const updates = [];
  const timers = [];
  const poller = createTaskPoller({
    load: async () => states.shift(),
    onUpdate: task => updates.push(task.status),
    schedule: callback => { timers.push(callback); return timers.length; },
    cancelSchedule: () => {}
  });
  await poller.refresh();
  assert.deepEqual(updates, ['RUNNING']);
  assert.equal(timers.length, 1);
  await timers.shift()();
  assert.deepEqual(updates, ['RUNNING', 'AWAITING_CONFIRMATION']);
  assert.equal(timers.length, 0);
});


test('poller uses task_status and progress_percent as canonical backend truth', () => {
  assert.equal(isTaskActive({status: 'completed', task_status: 'RUNNING'}), true);
  assert.deepEqual(taskProgress({progress: 81, progress_percent: 19, completed_count: 90, total_count: 100}), {
    percent: 19, completed: 90, total: 100, failed: 0
  });
});


test('managed terminal waiter resolves on backend terminal truth and updates every snapshot', async () => {
  const timers = [];
  const entries = new Map();
  const registry = {
    startTimeout(key, owners, callback, delay, options = {}) {
      entries.set(key, {owners, callback, delay, options});
      timers.push({key, callback});
      return timers.length;
    },
    clear(key) {
      const entry = entries.get(key);
      if (!entry) return false;
      entries.delete(key);
      entry.options?.onClear?.();
      return true;
    },
  };
  const states = [{task_status:'RUNNING', progress_percent:45}, {task_status:'SUCCEEDED', progress_percent:100}];
  const updates = [];
  const pending = waitForTaskTerminal({
    initialTask:{task_status:'QUEUED', progress_percent:0},
    registry,
    key:'task-1',
    ownerPages:'部署转换',
    delay:900,
    load:async()=>states.shift(),
    onUpdate:task=>updates.push(task.progress_percent),
  });
  await timers.shift().callback();
  await timers.shift().callback();
  const finalTask = await pending;
  assert.equal(finalTask.task_status, 'SUCCEEDED');
  assert.deepEqual(updates, [0,45,100]);
});

test('managed terminal waiter aborts when PollRegistry clears its page owner', async () => {
  let clearHook = null;
  const registry = {
    startTimeout(_key,_owners,_callback,_delay,options={}) { clearHook = options.onClear; return 1; },
    clear() { clearHook?.(); return true; },
  };
  const pending = waitForTaskTerminal({
    initialTask:{task_status:'RUNNING'},
    registry,
    key:'task-abort',
    ownerPages:'部署转换',
    load:async()=>({task_status:'RUNNING'}),
  });
  registry.clear('task-abort');
  await assert.rejects(pending, error => error?.name === 'AbortError');
});
