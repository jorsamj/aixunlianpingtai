import test from 'node:test';
import assert from 'node:assert/strict';

import {
  canonicalTaskPhase,
  canonicalTaskProgressPercent,
  canonicalTaskStatus,
  exactTaskQueuePosition,
  isCanonicalTaskActive,
  isCanonicalTaskTerminal,
  taskRuntimeTruth,
  trainingDisplayStatus,
} from '../../static/modules/task-runtime-truth.js';

test('canonical durable task fields win over stale legacy aliases', () => {
  const task = {
    status: 'completed',
    task_status: 'WAITING_RESOURCE',
    stage: 'committed',
    task_stage: 'queued',
    phase: 'resource_waiting',
    progress: 99,
    progress_percent: 17,
  };
  assert.equal(canonicalTaskStatus(task), 'WAITING_RESOURCE');
  assert.equal(canonicalTaskPhase(task), 'resource_waiting');
  assert.equal(canonicalTaskProgressPercent(task), 17);
  assert.equal(trainingDisplayStatus(task), 'waiting');
  assert.equal(isCanonicalTaskActive(task), true);
});

test('all historical training success aliases canonicalize to terminal SUCCEEDED truth', () => {
  for (const status of ['done', 'finished', 'completed', 'succeeded', 'success']) {
    assert.equal(canonicalTaskStatus({status}), 'SUCCEEDED', status);
    assert.equal(isCanonicalTaskTerminal({status}), true, status);
    assert.equal(trainingDisplayStatus({status}), 'completed', status);
    assert.equal(taskRuntimeTruth({status}).status, 'SUCCEEDED', status);
  }
});

test('browser never invents durable task percentage from item counts', () => {
  assert.equal(canonicalTaskProgressPercent({completed_count: 50, total_count: 100}), 0);
  assert.equal(canonicalTaskProgressPercent({progress: 41, completed_count: 99, total_count: 100}), 41);
  assert.equal(canonicalTaskProgressPercent({progress: 41, progress_percent: 23}), 23);
});

test('runtime truth preserves backend queue exactness instead of promoting a candidate rank', () => {
  const truth = taskRuntimeTruth({
    task_id: 'train-1',
    status: 'QUEUED',
    phase: 'resource_waiting',
    progress_percent: 8,
    resource_queue_position: 3,
    resource_queue_position_exact: false,
    resource_pool_label: 'GPU 自动',
  });
  assert.equal(truth.status, 'QUEUED');
  assert.equal(truth.resource_queue_position, 3);
  assert.equal(truth.resource_queue_position_exact, false);
});


test('exact queue position is presentationally usable only with explicit backend exactness', () => {
  assert.equal(exactTaskQueuePosition({resource_queue_position: 2, resource_queue_position_exact: true}), 2);
  assert.equal(exactTaskQueuePosition({resource_queue_position: 2, resource_queue_position_exact: false}), null);
  assert.equal(exactTaskQueuePosition({resource_queue_position: 2}), null);
});
