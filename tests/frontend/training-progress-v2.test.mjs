import test from 'node:test';
import assert from 'node:assert/strict';

import {trainingProgressView} from '../../static/modules/training-task-runtime.js';
import {trainingTaskPresentationRow as trainingTaskRow} from '../../static/modules/training-task-visibility-runtime.js';

test('training progress v2 renders real epoch metrics throughput and rolling ETA', () => {
  const job = {
    id: 'train-v2', status: 'running', progress_percent: 45, framework: 'ultralytics',
    current_item: '5', elapsed_seconds: 999, eta_seconds: 999,
    training_progress: {
      epoch: 5, total_epochs: 10, elapsed_seconds: 60, eta_seconds: 61,
      images_per_second: 10.25,
      losses: {box_loss: 0.51234, cls_loss: 0.22345, dfl_loss: 0.17891},
      metrics: {'metrics/mAP50(B)': 0.6612, 'metrics/mAP50-95(B)': 0.4123},
      learning_rates: {'lr/pg0': 0.001},
    },
  };
  const view = trainingProgressView(job);
  assert.equal(view.epoch, 5);
  assert.equal(view.totalEpochs, 10);
  assert.equal(view.elapsedSeconds, 60);
  assert.equal(view.etaSeconds, 61);
  assert.match(view.metricLine, /mAP50 0\.661/);
  assert.match(view.metricLine, /mAP50-95 0\.412/);
  assert.match(view.metricLine, /box loss 0\.5123/);
  assert.match(view.metricLine, /10\.3 img\/s/);
  assert.match(view.metricLine, /LR 0\.00100/);

  const html = trainingTaskRow(job);
  assert.match(html, /Epoch 5\/10/);
  assert.match(html, />45%<\/b>/);
  assert.doesNotMatch(html, /45% · 5/);
  assert.doesNotMatch(html, /mAP50 0\.661/, 'dense metrics belong in detail/report, not the primary task row');
  assert.match(html, />1m 1s</);
  assert.doesNotMatch(html, />16m 39s</);
});

test('training progress v2 omits unavailable metrics instead of manufacturing zeroes', () => {
  const view = trainingProgressView({id: 'queued', status: 'queued', progress_percent: 0});
  assert.equal(view.metricLine, '');
  const html = trainingTaskRow({id: 'queued', status: 'queued', progress_percent: 0});
  assert.doesNotMatch(html, /mAP50/);
  assert.doesNotMatch(html, /box loss/);
  assert.doesNotMatch(html, /img\/s/);
});
