import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {buildTrainingMaterialQuery} from '../../static/modules/training-material-picker-runtime.js';

const source = fs.readFileSync(new URL('../../static/modules/training-material-picker-runtime.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

test('training material picker query is cursor paged and server filtered', () => {
  const query = new URLSearchParams(buildTrainingMaterialQuery({
    cursor: 'cursor-2',
    pageSize: 120,
    query: 'smoke 01',
    labels: ['smoke', 'person'],
  }));
  assert.equal(query.get('limit'), '120');
  assert.equal(query.get('cursor'), 'cursor-2');
  assert.equal(query.get('query'), 'smoke 01');
  assert.deepEqual(query.getAll('label'), ['smoke', 'person']);
});

test('training picker never hydrates the legacy full image pool', () => {
  assert.match(source, /DEFAULT_PAGE_SIZE = 120/);
  assert.match(source, /\/api\/v62\/projects\/\$\{encodeURIComponent\(pid\)\}\/training-materials/);
  assert.match(source, /\/training-materials\/ids/);
  assert.doesNotMatch(source, /\/api\/projects\/\$\{[^}]+\}\/images/);
  assert.match(source, /loading="\$\{loading\}"/);
  assert.match(source, /fetchpriority="\$\{priority\}"/);
});

test('training picker keeps TrainingDraftRuntime as the selection truth owner', () => {
  assert.match(source, /const legacyConfirm = window\.confirmTrainMaterialPickerV3/);
  assert.match(source, /legacyConfirm\.apply/);
  assert.doesNotMatch(source, /state\(\)\.trainingDraft\s*=/);
  assert.match(main, /installTrainingMaterialPickerRuntime/);
  assert.match(main, /trainingDraftRuntime,/);
  assert.match(main, /PlatformCore\.runtime\.trainingMaterialPickerRuntime/);
});

test('picker UI is dense but bounded rather than rendering an unbounded pool', () => {
  assert.match(source, /repeat\(8,minmax\(0,1fr\)\)/);
  assert.match(source, /Array\.from\(\{length: 32\}/);
  assert.match(source, /pageCache\.size > CACHE_LIMIT/);
  assert.match(source, /setTimeout\(\(\) => resetFiltersAndLoad\(\), 220\)/);
});
