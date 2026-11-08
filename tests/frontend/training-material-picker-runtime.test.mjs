import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {buildTrainingMaterialQuery, renderTrainingMaterialPreview, trainingMaterialSelectable, trainingMaterialSelectionPatch} from '../../static/modules/training-material-picker-runtime.js';

const source = fs.readFileSync(new URL('../../static/modules/training-material-picker-runtime.js', import.meta.url), 'utf8');
const main = fs.readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
const app = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

test('ordinary material selection does not project an undefined training-target role as a review state',()=>{
  assert.match(source,/role === 'train' && hasTaskLabels/);
  assert.match(source,/id="trV3RoleFilter"/);
  assert.match(source,/value="pending_review">标注需核验/);
  assert.doesNotMatch(source,/审核待确认素材/);
});

test('independent Test reservation is a visible server-backed lock, including history reuse',()=>{
  assert.match(source, /const historyBlocked = Boolean\(row\.training_usage\?\.excluded\)/);
  assert.match(source, /row\.training_usage\?\.benchmark_protected/);
  assert.match(source, /本算法历史训练或验证已接触该素材，不能用于独立 Test/);
  assert.match(source, /已保留为本算法独立 Test，不能用于训练/);
  assert.match(source, /test_reserved:'独立 Test 已保留'/);
  assert.match(source, /historyUnknown = picker\.role === 'test' && row\.training_usage\?\.state === 'unknown'/);
  assert.match(source, /historyBlocked \? `<small class="train-v3-history-blocked"/);
});

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
  assert.equal(query.get('sort_order'), 'newest');
  assert.deepEqual(query.getAll('label'), ['smoke', 'person']);
});

test('training material picker supports authoritative page-number queries', () => {
  const query = new URLSearchParams(buildTrainingMaterialQuery({
    page: 7,
    pageSize: 20,
    query: 'smoke',
    labels: ['smoke'],
    sortOrder: 'oldest',
  }));
  assert.equal(query.get('sort_order'), 'oldest');
  assert.equal(query.get('page'), '7');
  assert.equal(query.get('page_size'), '20');
  assert.equal(query.has('cursor'), false);
});

test('training picker never hydrates the legacy full image pool', () => {
  assert.match(source, /DEFAULT_PAGE_SIZE = 60/);
  assert.match(source, /\/api\/v62\/projects\/\$\{encodeURIComponent\(pid\)\}\/training-materials/);
  assert.match(source, /\/training-materials\/bulk-selection/);
  assert.doesNotMatch(source, /\/api\/projects\/\$\{[^}]+\}\/images/);
  assert.match(source, /loading="\$\{loading\}"/);
  assert.match(source, /fetchpriority="\$\{priority\}"/);
});

test('ordinary iteration picker defers full role statistics until explicitly filtered or submitted', () => {
  assert.match(source, /defer_role_counts:!picker\.sampleRole/);
  assert.match(source, /picker\.roleCounts = body\.sample_role_counts \|\| null/);
  assert.match(source, /const hasTaskLabels=uniqueIds\(context\.train_labels\)\.length > 0 \|\| Boolean\(context\.base_version_id\)/);
});

test('training picker offers concise role filtering without duplicate targets or instructional paragraphs', () => {
  assert.match(source, /<header><strong id="trV3PickerCount"/);
  assert.match(source, /<label for="trV3RoleFilter">按训练目标筛选<\/label>/);
  assert.match(source, /value="positive">含本次目标/);
  assert.match(source, /value="confirmed_negative">已确认不含本次目标/);
  assert.match(source, /value="pending_negative">候选背景素材/);
  assert.doesNotMatch(source, /本次训练标签：/);
  assert.doesNotMatch(source, /请先选择训练标签/);
  assert.doesNotMatch(source, /本次训练目标：读取中/);
  assert.doesNotMatch(source, /选材说明/);
  assert.doesNotMatch(source, /当前选择未确定训练目标/);
});

test('legacy train button does not await an all-images response before showing the canonical picker', () => {
  assert.match(app, /window\.openTrainMaterialPickerV3=function\(role\)/);
  assert.match(app, /TrainingMaterialPickerRuntime/);
  assert.doesNotMatch(app, /const fetchPool=window\.__materialPaging61\?\.originalFetch/);
  assert.doesNotMatch(app, /const response=await fetchPool\(`\/api\/projects\/\$\{pid\(\)\}\/images`\)/);
});

test('training picker keeps TrainingDraftRuntime as the selection truth owner without a legacy confirm wrapper', () => {
  assert.doesNotMatch(source, /legacyConfirm/);
  assert.doesNotMatch(source, /\.apply\(this, arguments\)/);
  assert.doesNotMatch(source, /state\(\)\.trainingDraft\s*=/);
  assert.match(source, /trainingDraftRuntime\.update\(\{\.\.\.patch,trainSelectionRef:'',trainSelectionCount:0\}\)/);
  assert.match(source, /window\.refreshTrainingMaterialSelectionUiV3\?\.\(\)/);
  assert.match(source, /window\.confirmTrainMaterialPickerV3 = function confirmPicker/);
  assert.match(main, /installTrainingMaterialPickerRuntime/);
  assert.match(main, /trainingDraftRuntime,/);
  assert.match(main, /PlatformCore\.runtime\.trainingMaterialPickerRuntime/);
});

test('canonical picker confirmation preserves train and independent-test mutual exclusion', () => {
  assert.deepEqual(trainingMaterialSelectionPatch({
    role: 'train',
    selectedIds: ['m1', 'm2'],
    materialIds: ['old'],
    testMaterialIds: ['m2', 'm3'],
  }), {
    materialIds: ['m1', 'm2'],
    testMaterialIds: ['m3'],
  });
  assert.deepEqual(trainingMaterialSelectionPatch({
    role: 'test',
    selectedIds: ['m2', 'm4'],
    materialIds: ['m1', 'm2', 'm3'],
    testMaterialIds: ['old-test'],
  }), {
    materialIds: ['m1', 'm3'],
    testMaterialIds: ['m2', 'm4'],
  });
});

test('picker UI keeps responsive contain-preview cards inside a bounded viewport', () => {
  assert.match(source, /repeat\(4,minmax\(0,1fr\)\)/);
  assert.match(source, /grid-auto-rows:max-content!important/);
  assert.match(source, /height:min\(calc\(100dvh - 48px\),880px\)!important/);
  assert.match(source, /aspect-ratio:4\/3!important/);
  assert.doesNotMatch(fs.readFileSync(new URL('../../static/training-create-modal.css', import.meta.url),'utf8'), /\.modal-card:has\(\.train-v3-picker\.server-paged\)/);
  assert.match(source, /overflow:auto!important/);
  assert.match(source, /Array\.from\(\{length: 15\}/);
  assert.match(source, /pageCache\.size > CACHE_LIMIT/);
  assert.match(source, /setTimeout\(\(\) => resetFiltersAndLoad\(\), 220\)/);
});

test('picker visual refinements stay scoped and respect motion and image geometry', () => {
  assert.match(source, /\.modal-card:has\(\.train-v3-picker\.server-paged\)/);
  assert.match(source, /@keyframes pickerDialogEnter/);
  assert.match(source, /@media\(prefers-reduced-motion:reduce\)/);
  assert.match(source, /class="train-v3-advanced-panel"/);
  assert.match(source, /\.train-v3-filters>#trV3ActiveFilters:empty/);
  assert.match(source, /class="train-v3-role-tools"/);
  assert.match(source, /\.train-v3-advanced-panel\{[\s\S]*?position:static/);
  assert.match(source, /grid-template-columns:274px minmax\(0,1fr\)/);
  assert.match(source, /grid-column:1;grid-row:1;[\s\S]*?overflow-y:auto/);
  assert.match(source, /class="train-v3-mobile-toggle"/);
  assert.match(source, /<main class="train-v3-results"><div class="train-v3-view">[\s\S]*?<details class="train-v3-selected">/);
  assert.match(source, /toggleFilterSidebar\(\)/);
  assert.match(source, /\.train-v3-picker\.server-paged \.train-v3-card\.on\{/);
  assert.match(source, /object-fit:contain/);
  assert.doesNotMatch(source, /\.train-v3-picker\.server-paged \.train-v3-card img\{[^}]*object-fit:cover/);
  assert.match(source, /onclick="confirmTrainMaterialPickerV3\(\)"/);
  assert.match(source, /onclick="trainMaterialSelectV3\('select-page'\)"/);
});

test('picker delegates all numbered navigation and jump input to shared pagination', () => {
  assert.match(source, /PlatformCore\?\.pagination\?\.mountPagination/);
  assert.match(source, /onPageChange:/);
  assert.match(source, /onPageSizeChange:/);
  assert.match(source, /page: picker\.page/);
  assert.match(source, /totalPages: picker\.totalPages/);
  assert.doesNotMatch(source, /pager\.innerHTML = `<button[^`]*上一页/);
});

test('picker caps first-paint thumbnails and only expands loading after scroll', () => {
  assert.match(source, /THUMBNAIL_EAGER_COUNT = 10/);
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

test('all-available frozen fallback does not inherit active picker filters or role', () => {
  assert.match(source, /const referenceScope=allAvailable \? taskPayload\(\) : \{\.\.\.taskPayload\(\),\.\.\.filterPayload\(\)\}/);
  assert.match(source, /sample_role:allAvailable\?'':picker\.sampleRole/);
  assert.match(source, /JSON\.stringify\(\{\.\.\.referenceScope,request_id:/);
});

test('combined filters remain in one server query and cross-page selection uses that query', () => {
  const params = new URLSearchParams(buildTrainingMaterialQuery({
    page: 3, pageSize: 60, query: 'camera', labels: ['person', 'smoke'],
    sourceIds: ['nas-1'], negativePoolOnly: true, negativeCategoryIds: ['hard-negative'],
    createdFrom: '2026-10-01', createdTo: '2026-10-30',
    annotationState: 'annotated', usageState: 'unknown', historyScope: 'other_only',
    algorithmId: 'algo-b', historyPolicy: 'include_history',
  }));
  assert.equal(params.get('page'), '3');
  assert.deepEqual(params.getAll('label'), ['person', 'smoke']);
  for (const [key, value] of Object.entries({
    query: 'camera', storage_source_id: 'nas-1', negative_pool_only: 'true',
    negative_category_id: 'hard-negative', created_from: '2026-10-01', created_to: '2026-10-30',
    annotation_state: 'annotated', usage_state: 'unknown', history_scope: 'other_only',
    algorithm_asset_id: 'algo-b', history_policy: 'include_history',
  })) assert.equal(params.get(key), value);
  assert.match(source, /sample_role: allAvailable \? '' : \(picker\?\.sampleRole/);
  assert.match(source, /labels: allAvailable \? \[\] : \[\.\.\.\(picker\?\.labels/);
  assert.match(source, /\.\.\.taskPayload\(\), \.\.\.filterPayload\(\)/);
  assert.match(source, /function clearFilters\(\)/);
  assert.match(source, /function removeFilter\(key\)/);
});

test('picker refuses duplicate in-flight pages and stale cross-page bulk responses', () => {
  assert.match(source, /activePageKey === key/);
  assert.match(source, /activePageKey=null/);
  assert.match(source, /result\.total!==result\.ids\.length/);
  assert.match(source, /result\.annotationRevision!==picker\.annotationRevision/);
  assert.match(source, /result\.usageRevision!==picker\.usageRevision/);
  assert.match(source, /result\.negativePoolRevision!==picker\.negativePoolRevision/);
  assert.match(source, /result\.negativeConfirmationRevision!==picker\.negativeConfirmationRevision/);
  assert.match(source, /negativePoolRevision:body\.negative_pool_revision/);
  assert.match(source, /negativeConfirmationRevision:body\.negative_confirmation_revision/);
  assert.match(source, /picker\.selected\.add\(id\)/);
  assert.match(source, /picker\.selected\.has\(id\) \? picker\.selected\.delete\(id\) : picker\.selected\.add\(id\)/);
  assert.doesNotMatch(source, /task: taskPayload\(\)/);
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
  const unannotated = renderTrainingMaterialPreview({width: 10, height: 10, processing_status: 'processed', annotation_state: 'unannotated', boxes: []});
  assert.match(confirmed, /已确认无目标/);
  assert.match(unannotated, /未标注 · 已清洗/);
  assert.doesNotMatch(confirmed, /<svg/);
  assert.doesNotMatch(unannotated, /<svg/);
});

test('objective material annotation anomaly gives its cause without inventing a sample role',()=>{
  const html=renderTrainingMaterialPreview({annotation_state:'annotated',boxes:[{label:'person',x1:1,y1:2,x2:10,y2:12}],width:50,height:50,annotation_issue_type:'material_unavailable'});
  assert.match(html,/标注异常 · 素材来源不可用/);
  assert.doesNotMatch(html,/待审核|待确认负样本/);
});


test('cleaned unannotated materials are selectable for train but fenced from independent test', () => {
  assert.match(source, /missingTestTruth = picker\.role === 'test'/);
  assert.match(source, /role: picker\?\.role === 'robustness' \? 'train' : \(picker\?\.role \|\| 'train'\)/);
  assert.match(source, /试验集必须已标注/);
  const unannotated = {id:'cleaned-img-1',annotation_state:'unannotated',training_usage:{state:'unknown'}};
  assert.equal(trainingMaterialSelectable(unannotated,'train'),true);
  assert.equal(trainingMaterialSelectable(unannotated,'test'),false);
  assert.doesNotMatch(source, /blocked\.has\(id\) \|\| String\(row\.annotation_state \|\| ''\) === 'unannotated'/);
});

test('picker exposes a time ordering control with server paging and filter persistence', () => {
  const liveSource = fs.readFileSync(new URL('../../static/modules/training-material-picker-runtime.js', import.meta.url), 'utf8');
  assert.match(liveSource, /id="trV3Sort"/);
  assert.match(liveSource, /trainMaterialSortV3\(this.value\)/);
  assert.match(liveSource, /sortOrder: picker.sortOrder/);
  assert.match(liveSource, /function setSortOrder\(value\)/);
});

test('training candidate labels remain readable while sidebar chips wrap within bounded scrolling', () => {
  assert.match(source, /train-v3-label-list/);
  assert.match(source, /\.train-v3-label-list\{white-space:normal;overflow:visible/);
  assert.match(source, /#trV3Chips\{[\s\S]*?flex-wrap:wrap/);
  assert.match(source, /max-height:202px/);
  assert.match(source, /overflow-x:hidden;overflow-y:auto/);
});

test('task roles stay separate from original label filters', () => {
  const query = new URLSearchParams(buildTrainingMaterialQuery({labels:['person'], effectiveLabelCodes:['vest'], sampleRole:'pending_review'}));
  assert.deepEqual(query.getAll('label'), ['person']);
  assert.deepEqual(query.getAll('effective_label_code'), ['vest']);
  assert.equal(query.get('sample_role'), 'pending_review');
});

test('picker query carries shared source time formal annotation and usage filters', () => {
  const q = new URLSearchParams(buildTrainingMaterialQuery({sourceIds:['nas'], createdFrom:'2026-10-01', createdTo:'2026-10-28', annotationState:'confirmed_empty', usageState:'unknown'}));
  assert.deepEqual(q.getAll('storage_source_id'), ['nas']);
  assert.equal(q.get('created_from'), '2026-10-01');
  assert.equal(q.get('created_to'), '2026-10-28');
  assert.equal(q.get('annotation_state'), 'confirmed_empty');
  assert.equal(q.get('usage_state'), 'unknown');
});

test('training picker action owner disables confirmation during page and bulk requests', () => {
  const begin = source.indexOf('  function syncPickerActions(owner = picker) {');
  const end = source.indexOf('\n  function updateCounts()', begin);
  assert.ok(begin >= 0 && end > begin);
  const buttons = [0, 1, 2].map(() => ({
    disabled: false, classes: new Set(),
    classList: { toggle() {} },
  }));
  const modalLayer = { querySelectorAll: () => buttons };
  const owner = {loading: true, bulkPending: false, reviewPending: false};
  const getSync = new Function('picker', 'modalLayer', 'document',
    source.slice(begin, end) + '\nreturn syncPickerActions;');
  const sync = getSync(owner, modalLayer, {querySelectorAll: () => {throw new Error('must scope to modal')}});
  sync();
  assert.equal(buttons.every(button => button.disabled), true, 'initial page load must lock actions');
  owner.loading = false;
  owner.bulkPending = true;
  sync();
  assert.equal(buttons.every(button => button.disabled), true, 'server bulk selection must lock actions');
  owner.bulkPending = false;
  sync();
  assert.equal(buttons.every(button => !button.disabled), true, 'actions must unlock on final completion');
  assert.match(source, /if \(!picker \|\| picker\.loading \|\| picker\.bulkPending \|\| picker\.reviewPending\) return false/);
});
