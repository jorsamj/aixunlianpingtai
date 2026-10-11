import test from 'node:test';
import assert from 'node:assert/strict';

import {trainingTaskPresentationRow as trainingTaskRow} from '../../static/modules/training-task-visibility-runtime.js';


test('completed 180/300 patience stop is terminal and explains why it stopped', () => {
  const html = trainingTaskRow({
    id: 'train-180',
    status: 'done',
    current_epoch: 180,
    total_epochs: 300,
    progress_percent: 100,
    elapsed_seconds: 600,
    eta_seconds: 0,
    completion_reason: 'early_stopping',
    early_stopping_reason: 'patience',
    early_stopping_patience: 100,
    best_epoch: 80,
  });

  assert.match(html, /已完成/);
  assert.match(html, /180\/300/);
  assert.match(html, /连续 100 Epoch 无提升，Early Stopping/);
  assert.match(html, /10m 0s/);
  assert.doesNotMatch(html, />训练中</);
});


test('quality target stop is not mislabeled as patience early stopping', () => {
  const html = trainingTaskRow({
    id: 'train-target',
    status: 'done',
    current_epoch: 180,
    total_epochs: 300,
    progress_percent: 100,
    elapsed_seconds: 600,
    completion_reason: 'quality_target_reached',
    training_outcome: 'target_reached',
    quality_gate_reason: 'map50 达到提前完成阈值 0.850',
  });

  assert.match(html, /达到质量目标，提前完成/);
  assert.doesNotMatch(html, /连续 100 Epoch/);
});
