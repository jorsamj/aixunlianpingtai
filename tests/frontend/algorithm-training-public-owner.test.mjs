import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');
const recovery = await readFile(new URL('../../static/modules/training-recovery-runtime.js', import.meta.url), 'utf8');

test('algorithm and training public actions have one final owner each', () => {
  for (const name of [
    'renderAlgorithms423',
    'startAlgorithmTraining423',
    'showVersionDeployments423',
    'toggleAlgorithm428',
  ]) {
    const pattern = new RegExp('window\\.' + name + '\\s*=', 'g');
    assert.equal((app.match(pattern) || []).length, 1, name);
  }
  assert.equal((app.match(/window\.showTrainLog423\s*=/g) || []).length, 0, 'app.js must not own training detail/log rendering');
  assert.equal((recovery.match(/window\.showTrainLog423\s*=/g) || []).length, 1, 'TrainingRecoveryRuntime must be the sole training log owner');
});

test('training start and algorithm expansion point at current canonical owners', () => {
  assert.match(app, /window\.startAlgorithmTraining423=window\.openTrainingCreateCanonical429/);
  assert.match(app, /window\.toggleAlgorithm428=window\.toggleAlgorithm412/);
  assert.match(recovery, /window\.showTrainLog423 = taskId => openDetail\(taskId, \{focus: 'log'\}\)/);
});

test('historical implementations are isolated under Legacy names', () => {
  assert.match(app, /window\.renderAlgorithmsLegacy423_/);
  assert.match(app, /window\.showTrainLogLegacy423_/);
  assert.match(app, /window\.showVersionDeploymentsLegacy423_/);
});
