import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const appSource = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
const source = readFileSync(new URL('../../static/modules/algorithm-list-runtime.js', import.meta.url), 'utf8');

function stableVersionRenderer() {
  const start = source.indexOf('function versionRowsHtml');
  const end = source.indexOf('function algorithmRowView', start);
  assert.ok(start >= 0 && end > start, 'AlgorithmListRuntime version renderer must exist');
  return source.slice(start, end);
}

test('stable algorithm version renderer exposes persisted training lineage action', () => {
  const renderer = stableVersionRenderer();
  assert.match(renderer, /version\.training_lineage/);
  assert.match(renderer, /openVersionLineage429/);
  assert.match(renderer, /训练溯源/);
});

test('canonical algorithm compatibility entries delegate directly to AlgorithmListRuntime', () => {
  const start = appSource.indexOf('window.renderAlgorithms423=function()');
  assert.ok(start >= 0, 'renderAlgorithms423 must exist');
  const region = appSource.slice(start, appSource.indexOf('window.toggleAlgorithm412', start));
  assert.match(region, /AlgorithmListRuntime\?\.render\?\.\(\)/);
  assert.doesNotMatch(appSource, /function verRow412/);
});


test('stable algorithm version renderer exposes persisted evaluation action', () => {
  const renderer = stableVersionRenderer();
  assert.match(renderer, /version\.evaluation/);
  assert.match(renderer, /openVersionEvaluation429/);
  assert.match(renderer, /独立评测/);
});
