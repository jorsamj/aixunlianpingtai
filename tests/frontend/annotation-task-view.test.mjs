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
