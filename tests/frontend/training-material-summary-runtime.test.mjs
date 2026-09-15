import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {trainingMaterialSelectionSignature} from '../../static/modules/training-material-summary-runtime.js';
import {resolveClientTrainingLabels} from '../../static/modules/training-labels.js';

test('selection signature is stable and duplicate independent', () => {
  assert.equal(
    trainingMaterialSelectionSignature(['b', 'a', 'b']),
    trainingMaterialSelectionSignature(['a', 'b']),
  );
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

  assert.match(main, /FULL_MATERIAL_PAGES\.delete\('训练任务'\)/);
  assert.match(main, /installTrainingMaterialSummaryRuntime/);
  assert.match(main, /materialSummaryRuntime: trainingMaterialSummaryRuntime/);
  assert.match(summaryRuntime, /training-materials\/selection-summary/);
  assert.match(summaryRuntime, /fullPoolHydration: false/);
  assert.match(labelsRuntime, /materialSummaryRuntime\.summaryReadyFor/);
  assert.match(labelsRuntime, /正在读取已选素材标签/);
});
