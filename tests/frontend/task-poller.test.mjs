import test from 'node:test';
import assert from 'node:assert/strict';

import {createTaskPoller, isTaskActive, taskProgress} from '../../static/modules/task-poller.js';

test('only genuine backend running states continue polling', () => {
  assert.equal(isTaskActive('QUEUED'), true);
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
