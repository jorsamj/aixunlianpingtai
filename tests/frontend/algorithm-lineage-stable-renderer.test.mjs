import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

const source = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

function stableVersionRenderer() {
  const start = source.indexOf('function verRow412');
  const end = source.indexOf('window.renderAlg412', start);
  assert.ok(start >= 0 && end > start, 'stable verRow412 renderer must exist');
  return source.slice(start, end);
}

test('stable algorithm version renderer exposes persisted training lineage action', () => {
  const renderer = stableVersionRenderer();
  assert.match(renderer, /v\.training_lineage/);
  assert.match(renderer, /openVersionLineage429/);
  assert.match(renderer, /训练溯源/);
});

test('canonical algorithm route still renders through stable renderAlg412 owner', () => {
  const start = source.indexOf('window.renderAlgorithms423=function()');
  assert.ok(start >= 0, 'renderAlgorithms423 must exist');
  const region = source.slice(start, source.indexOf('window.toggleAlgorithm412', start));
  assert.match(region, /renderAlg412\(\)/);
});


test('stable algorithm version renderer exposes persisted evaluation action', () => {
  const renderer = stableVersionRenderer();
  assert.match(renderer, /v\.evaluation/);
  assert.match(renderer, /openVersionEvaluation429/);
  assert.match(renderer, /独立评测/);
});
