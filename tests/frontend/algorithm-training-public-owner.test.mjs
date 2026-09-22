import test from 'node:test';
import assert from 'node:assert/strict';
import {readFile} from 'node:fs/promises';

const app = await readFile(new URL('../../static/app.js', import.meta.url), 'utf8');

test('algorithm and training public actions have one final owner each', () => {
  for (const name of [
    'renderAlgorithms423',
    'showTrainLog423',
    'startAlgorithmTraining423',
    'showVersionDeployments423',
    'toggleAlgorithm428',
  ]) {
    const pattern = new RegExp('window\\.' + name + '\\s*=', 'g');
    assert.equal((app.match(pattern) || []).length, 1, name);
  }
});

test('training start and algorithm expansion point at current canonical owners', () => {
  assert.match(app, /window\.startAlgorithmTraining423=window\.openTrainingCreateCanonical429/);
  assert.match(app, /window\.toggleAlgorithm428=window\.toggleAlgorithm412/);
  assert.match(app, /window\.showTrainLog423=async function\(id\)/);
});

test('historical implementations are isolated under Legacy names', () => {
  assert.match(app, /window\.renderAlgorithmsLegacy423_/);
  assert.match(app, /window\.showTrainLogLegacy423_/);
  assert.match(app, /window\.showVersionDeploymentsLegacy423_/);
});
