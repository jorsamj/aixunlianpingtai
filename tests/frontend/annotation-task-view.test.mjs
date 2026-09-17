import test from 'node:test';
import assert from 'node:assert/strict';

import {annotationTaskView, buildCandidateDecisions} from '../../static/modules/annotation-task-view.js';

test('annotation task view exposes truthful progress and review action', () => {
  const running = annotationTaskView({status: 'RUNNING', progress: 31.7, completed_count: 38, total_count: 120, failed_count: 7});
  assert.equal(running.progressText, '38 / 120');
  assert.equal(running.percent, 31.7);
  assert.equal(running.canCancel, true);
  assert.equal(running.canReview, false);
  const waiting = annotationTaskView({status: 'AWAITING_CONFIRMATION', summary: {total: 120, failed: 7, boxes: 93}});
  assert.equal(waiting.canReview, true);
  assert.equal(waiting.failed, 7);
});

test('candidate decisions explicitly retain both accepts and rejects', () => {
  const payload = buildCandidateDecisions([
    {image_id: 'a', accepted: true},
    {image_id: 'b', accepted: false},
    {image_id: 'failed', status: 'failed', accepted: true}
  ]);
  assert.deepEqual(payload, {
    decisions: [{image_id: 'a', accepted: true}, {image_id: 'b', accepted: false}],
    reject_unmentioned: true,
    commit: true
  });
});


test('annotation queue number is visible only when backend proves exactness', () => {
  const exact = annotationTaskView({
    task_status: 'WAITING_RESOURCE', status: 'completed',
    resource_queue_position: 2, resource_queue_position_exact: true,
    resource_wait_reason: 'VISION_CAPACITY_BUSY',
  });
  assert.equal(exact.status, 'WAITING_RESOURCE');
  assert.equal(exact.runtimeText, '资源队列第 2 位 · VISION_CAPACITY_BUSY');

  const inexact = annotationTaskView({
    status: 'QUEUED', resource_queue_position: 2, resource_queue_position_exact: false,
  });
  assert.equal(inexact.runtimeText, '');
});


test('annotation recovery execution is surfaced from durable attempt truth', () => {
  const recovery = annotationTaskView({
    task_status: 'RUNNING', status: 'RUNNING', attempt: 3,
    worker_id: 'annotation-worker-2', progress_percent: 48,
    completed_count: 24, total_count: 50,
  });
  assert.equal(recovery.status, 'RUNNING');
  assert.equal(recovery.attempt, 3);
  assert.equal(recovery.runtimeText, '恢复执行 · 第 3 次执行 · Worker annotation-worker-2');
  assert.equal(recovery.percent, 48);
  assert.equal(recovery.canCancel, true);
});
