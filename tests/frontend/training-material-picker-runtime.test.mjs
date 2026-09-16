import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {buildTrainingMaterialQuery} from '../../static/modules/training-material-picker-runtime.js';

const source = fs.readFileSync(new URL('../../static/modules/training-material-picker-runtime.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');

test('training material picker query is cursor paged and server filtered', () => {
  const query = new URLSearchParams(buildTrainingMaterialQuery({
    cursor: 'cursor-2',
    pageSize: 60,
    query: 'smoke 01',
    labels: ['smoke', 'person'],
  }));
  assert.equal(query.get('limit'), '60');
  assert.equal(query.get('cursor'), 'cursor-2');
  assert.equal(query.get('query'), 'smoke 01');
  assert.deepEqual(query.getAll('label'), ['smoke', 'person']);
});

test('training picker never hydrates the legacy full image pool', () => {
  assert.match(source, /DEFAULT_PAGE_SIZE = 60/);
  assert.match(source, /\/api\/v62\/projects\/\$\{encodeURIComponent\(pid\)\}\/training-materials/);
  assert.match(source, /\/training-materials\/bulk-selection/);
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

test('picker UI uses larger bounded preview cards rather than a dense thumbnail strip', () => {
  assert.match(source, /repeat\(5,minmax\(0,1fr\)\)/);
  assert.match(source, /aspect-ratio:4\/3/);
  assert.match(source, /height:clamp\(420px,60vh,620px\)/);
  assert.match(source, /overflow-y:auto!important/);
  assert.match(source, /Array\.from\(\{length: 15\}/);
  assert.match(source, /pageCache\.size > CACHE_LIMIT/);
  assert.match(source, /setTimeout\(\(\) => resetFiltersAndLoad\(\), 220\)/);
});

test('picker only activates thumbnails inside the bounded scroll viewport', () => {
  assert.match(source, /THUMBNAIL_EAGER_COUNT = 6/);
  assert.match(source, /THUMBNAIL_PRELOAD_MARGIN = 120/);
  assert.match(source, /data-src="\$\{esc\(thumbnail\)\}"/);
  assert.match(source, /getBoundingClientRect\(\)/);
  assert.match(source, /requestAnimationFrame/);
  assert.match(source, /addEventListener\('scroll', scheduleVisibleThumbnailWindow/);
  assert.match(source, /viewportThumbnailLoading: true/);
  assert.match(source, /eagerThumbnailCount: THUMBNAIL_EAGER_COUNT/);
  assert.doesNotMatch(source, /IntersectionObserver/);
});

test('large bulk selection has a single server owner', () => {
  assert.match(source, /resolveBulkSelection/);
  assert.match(source, /method: 'POST'/);
  assert.match(source, /bulkSelectionOwner: 'server'/);
  assert.doesNotMatch(source, /do \{[\s\S]*\/training-materials\/ids/);
});
