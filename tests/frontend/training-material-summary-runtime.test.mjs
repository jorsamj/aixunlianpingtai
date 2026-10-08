import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  excludeTrainingMaterialFromDraft,
  trainingCompatibilitySignature,
  trainingMaterialSelectionSignature,
} from '../../static/modules/training-material-summary-runtime.js';
import {resolveClientTrainingLabels} from '../../static/modules/training-labels.js';

test('selection signature is stable and duplicate independent', () => {
  assert.equal(
    trainingMaterialSelectionSignature(['b', 'a', 'b']),
    trainingMaterialSelectionSignature(['a', 'b']),
  );
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
