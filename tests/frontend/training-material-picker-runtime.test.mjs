import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {buildTrainingMaterialQuery, renderTrainingMaterialPreview} from '../../static/modules/training-material-picker-runtime.js';

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
  assert.match(source, /grid-auto-rows:minmax\(210px,max-content\)/);
  assert.match(source, /min-height:210px/);
  assert.match(source, /aspect-ratio:4\/3!important/);
  assert.match(source, /height:clamp\(420px,60vh,620px\)/);
  assert.match(source, /overflow-y:auto!important/);
  assert.match(source, /Array\.from\(\{length: 15\}/);
  assert.match(source, /pageCache\.size > CACHE_LIMIT/);
  assert.match(source, /setTimeout\(\(\) => resetFiltersAndLoad\(\), 220\)/);
});

test('picker caps first-paint thumbnails and only expands loading after scroll', () => {
  assert.match(source, /THUMBNAIL_EAGER_COUNT = 15/);
  assert.match(source, /THUMBNAIL_PRELOAD_MARGIN = 120/);
  assert.match(source, /data-src="\$\{esc\(thumbnail\)\}"/);
  assert.match(source, /images\.slice\(0, THUMBNAIL_EAGER_COUNT\)\.forEach\(loadThumbnail\)/);
  assert.match(source, /addEventListener\('scroll', scheduleVisibleThumbnailWindow/);
  assert.match(source, /getBoundingClientRect\(\)/);
  assert.match(source, /requestAnimationFrame/);
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

test('annotated preview uses source coordinates as the SVG viewBox', () => {
  const html = renderTrainingMaterialPreview({
    id: 'm1', filename: 'm1.jpg', width: 400, height: 200,
    thumbnail_url: '/thumb/m1.jpg', content_url: '/full/m1.jpg',
    annotation_state: 'annotated',
    boxes: [{label: 'smoke', x1: 40, y1: 20, x2: 200, y2: 100}],
  }, {loading: 'eager', priority: 'high'});

  assert.match(html, /viewBox="0 0 400 200"/);
  assert.match(html, /preserveAspectRatio="xMidYMid meet"/);
  assert.match(html, /<rect[^>]*x="40"[^>]*y="20"[^>]*width="160"[^>]*height="80"/);
  assert.match(html, /data-label="smoke"/);
  assert.match(html, /已标注 · 1 框/);
});

test('empty boxes preserve confirmed-empty and unannotated as distinct states', () => {
  const confirmed = renderTrainingMaterialPreview({width: 10, height: 10, annotation_state: 'confirmed_empty', boxes: []});
  const unannotated = renderTrainingMaterialPreview({width: 10, height: 10, annotation_state: 'unannotated', boxes: []});
  assert.match(confirmed, /已确认无目标/);
  assert.match(unannotated, /未标注/);
  assert.doesNotMatch(confirmed, /<svg/);
  assert.doesNotMatch(unannotated, /<svg/);
});
