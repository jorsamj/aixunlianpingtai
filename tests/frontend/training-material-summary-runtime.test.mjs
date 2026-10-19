import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  excludeTrainingMaterialFromDraft,
  trainingCompatibilitySignature,
  trainingMaterialSelectionSignature,
  updateTrainingGovernanceSelection,
  renderGtConflictEvidence,
} from '../../static/modules/training-material-summary-runtime.js';
import {resolveClientTrainingLabels} from '../../static/modules/training-labels.js';

test('shared GT evidence distinguishes unknown cause and null metrics without trusting HTML', () => {
  const html=renderGtConflictEvidence({observations:['COORDINATE_DIFFERENCE'],root_cause_status:'UNDETERMINED',
    iou_summary:{matched_count:0,min:null,max_pixel_delta:null}}, [{image_id:'a',filename:'<img onerror=bad()>',
    annotation_scope:['<script>'],boxes:[],content_sha256:'same'}]);
  assert.match(html,/根因待核验/);
  assert.match(html,/坐标不同/);
  assert.match(html,/未核验/);
  assert.ok(!html.includes('<img onerror=bad()>'));
  assert.match(html,/不会自动覆盖GT/);
});

test('governance selection retains cross-page choices and all-filtered exclusions without hydrating 99 pages', () => {
  let selected = updateTrainingGovernanceSelection(null, {mode:'page', ids:['a','b'], key:'project/filter/rev', total:2376});
  selected = updateTrainingGovernanceSelection(selected, {mode:'page', ids:['c'], key:'project/filter/rev', total:2376});
  assert.deepEqual(selected.image_ids, ['a','b','c']);
  selected = updateTrainingGovernanceSelection(selected, {mode:'all', key:'project/filter/rev', total:2376});
  selected = updateTrainingGovernanceSelection(selected, {mode:'toggle', id:'c', checked:false, key:'project/filter/rev', total:2376});
  assert.equal(selected.count, 2375);
  assert.equal(selected.all_filtered, true);
  assert.deepEqual(selected.image_ids, []);
  assert.deepEqual(selected.excluded_image_ids, ['c']);
  assert.equal(JSON.stringify(selected).length < 250, true);
  assert.equal(updateTrainingGovernanceSelection(selected, {mode:'read', key:'other-project/filter/rev', total:1}).count, 0);
  assert.equal(updateTrainingGovernanceSelection(selected, {mode:'read', key:'project/filter/new-rev', total:2376}).count, 0);
});

test('selection signature is stable and duplicate independent', () => {
  assert.equal(
    trainingMaterialSelectionSignature(['b', 'a', 'b']),
    trainingMaterialSelectionSignature(['a', 'b']),
  );
});

test('duplicate exclusions preserve explicit original scope and canonical revisions without deleting materials', () => {
  const draft={materialIds:['a','b','c'],testMaterialIds:[]};
  const truth={material_revision:12,annotation_revision:7,items:[{image_id:'b',issue_type:'duplicate_annotation_conflict'}]};
  const result=excludeTrainingMaterialFromDraft({update:patch=>patch},draft,'b',truth);
  assert.deepEqual(result.materialIds,['a','c']);
  assert.deepEqual(result.duplicateReview,{original_train_image_ids:['a','b','c'],original_test_image_ids:[],excluded_image_ids:['b'],material_revision:12,annotation_revision:7});
});

test('task compatibility signature changes with labels and selected material truth', () => {
  const base = {
    algorithmId: 'alg-1', materialIds: ['b', 'a'], testMaterialIds: [],
    splitMode: 'random_test_from_training_pool', newLabelCodes: ['fire'],
    config: {model: 'yolo11n.pt'}, experimentPercent: 20, validationPercent: 20,
  };
  assert.equal(
    trainingCompatibilitySignature(base),
    trainingCompatibilitySignature({...base, materialIds: ['a', 'b']}),
  );
  assert.notEqual(
    trainingCompatibilitySignature(base),
    trainingCompatibilitySignature({...base, newLabelCodes: ['fire', 'smoke']}),
  );
});

test('excluding an issue only updates the current training draft', () => {
  const updates = [];
  const draft = {materialIds: ['bad', 'good'], testMaterialIds: ['test']};
  const result = excludeTrainingMaterialFromDraft(
    {update: patch => { updates.push(patch); return patch; }},
    draft,
    'bad',
  );
  assert.deepEqual(result, {materialIds: ['good'], testMaterialIds: ['test']});
  assert.deepEqual(updates, [result]);
});

test('server available codes override a partial local material page', () => {
  const view = resolveClientTrainingLabels({
    materials: [{id: 'selected-1', labels: ['smoke']}],
    selectedIds: ['selected-1', 'selected-outside-page'],
    labelCatalog: [{code: 'smoke'}, {code: 'person'}],
    algorithm: {versions: []},
    requestedCodes: ['smoke', 'person'],
    availableCodes: ['smoke', 'person'],
  });
  assert.deepEqual(view.available, ['smoke', 'person']);
  assert.deepEqual(view.requested, ['smoke', 'person']);
});

test('training page full-pool hydration is explicitly disabled and summary runtime owns server truth', () => {
  const main = readFileSync(new URL('../../static/main.mjs', import.meta.url), 'utf8');
  const summaryRuntime = readFileSync(new URL('../../static/modules/training-material-summary-runtime.js', import.meta.url), 'utf8');
  const labelsRuntime = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url), 'utf8');
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

  assert.doesNotMatch(main, /FULL_MATERIAL_PAGES/);
  assert.match(main, /installTrainingMaterialSummaryRuntime/);
  assert.match(main, /materialSummaryRuntime: trainingMaterialSummaryRuntime/);
  assert.match(summaryRuntime, /training-materials\/selection-summary/);
  assert.match(summaryRuntime, /training-materials\/compatibility/);
  assert.match(summaryRuntime, /PlatformCore\?\.pagination\?\.mountPagination/);
  assert.match(summaryRuntime, /page: compatibilityPage/);
  assert.match(summaryRuntime, /page_size: pageSize/);
  assert.match(summaryRuntime, /onPageChange:/);
  assert.match(summaryRuntime, /onPageSizeChange:/);
  assert.doesNotMatch(summaryRuntime, /onclick="TrainingMaterialSummaryRuntime\.loadIssuePage[^>]*>上一页/);
  assert.match(summaryRuntime, /去补审/);
  assert.match(summaryRuntime, /排除本次训练/);
  assert.match(summaryRuntime, /fullPoolHydration: false/);
  assert.match(summaryRuntime, /selectable_total/);
  assert.match(summaryRuntime, /pending_annotation_count/);
  assert.match(summaryRuntime, /可直接训练/);
  assert.match(summaryRuntime, /待标注/);
  assert.match(labelsRuntime, /materialSummaryRuntime\.summaryReadyFor/);
  assert.match(labelsRuntime, /materialSummaryRuntime\?\.invalidate\?\.\(\)/);
  assert.match(labelsRuntime, /正在读取素材标签/);
  assert.match(summaryRuntime, /function invalidate\(\)/);
  assert.match(summaryRuntime, /currentSignature = null/);
  assert.match(summaryRuntime, /summary = null/);
  assert.match(app, /invalidateTrainingMaterialSummaryAfterLabelMutation414/);
  assert.match(app, /runtime\?\.refresh\?\.\(ids,\{force:true\}\)/);
});
