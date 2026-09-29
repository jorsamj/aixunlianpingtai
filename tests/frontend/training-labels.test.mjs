import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  resolveClientTrainingLabels,
  selectedMaterialLabelCodes,
  selectedTrainingMaterialIds,
} from '../../static/modules/training-labels.js';

const catalog = [
  {code: 'fire', display_name: '明火'},
  {code: 'smoke', display_name: '烟雾'},
  {code: 'person', display_name: '人员'},
  {code: 'helmet', display_name: '安全帽'},
];

test('available labels come only from selected material positive labels', () => {
  const materials = [
    {id: 'a', labels: ['fire', 'person']},
    {id: 'b', labels: ['smoke']},
    {id: 'c', labels: ['helmet']},
  ];
  assert.deepEqual(selectedMaterialLabelCodes(materials, ['a', 'b'], catalog), ['fire', 'smoke', 'person']);
});

test('confirmed empty scope never becomes selectable label evidence', () => {
  const materials = [
    {id: 'a', labels: [], annotation_scope: ['fire', 'smoke']},
    {id: 'b', labels: [], annotation_scope: ['*']},
  ];
  assert.deepEqual(selectedMaterialLabelCodes(materials, ['a', 'b'], catalog), []);
});

test('training material ids come only from canonical draft', () => {
  const state = {
    train429Selected: new Set(['stale-material']),
    trainingDraft: {algorithmId: 'canonical-algorithm', materialIds: ['canonical-1', 'canonical-2']},
  };
  assert.deepEqual(selectedTrainingMaterialIds(state), ['canonical-1', 'canonical-2']);
});

test('client label picker only filters current active material labels and explicit choices', () => {
  const labelCatalog = [
    {code: 'fire', display_name: '明火', active: true, status: 'active'},
    {code: 'smoke', display_name: '烟雾', active: true, status: 'active'},
    {code: 'legacy_smoke', display_name: '旧烟雾', active: false, status: 'merged', merged_into: 'smoke'},
  ];
  const view = resolveClientTrainingLabels({
    materials: [{id: 'a', labels: ['fire', 'smoke', 'legacy_smoke']}],
    selectedIds: ['a'],
    labelCatalog,
    requestedCodes: ['smoke', 'legacy_smoke'],
  });
  assert.deepEqual(view.selectable, ['fire', 'smoke']);
  assert.deepEqual(view.requested, ['smoke']);
  assert.deepEqual(view.invalidAvailable, ['legacy_smoke']);
  assert.equal('inherited' in view, false);
  assert.equal('effectivePreview' in view, false);
});

test('first render never auto-selects material labels for the user', () => {
  const source = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url), 'utf8');
  assert.match(source, /state\.trainingLabelAlgorithmId = algorithmId;\r?\n\s*return \[\];/);
  assert.equal(source.includes('return unique(selectable);'), false);
});

test('training label UI shows only server-resolved canonical inheritance without merge audit ownership', () => {
  const source = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url), 'utf8');
  for (const token of [
    'latestVersionLabelInfo',
    'resolveInheritedGovernance',
    'labelGovernance414',
    'merged_into',
    'mergedInherited',
    'droppedInherited',
    'governanceBlockedInherited',
    'historicalLabelSchema',
    '历史版本保持不变',
    'Label Schema Changed',
  ]) {
    assert.equal(source.includes(token), false, `training create UI must not own history audit token: ${token}`);
  }
  assert.match(source, /labelHistoryOwner: false/);
  assert.match(source, /serverInheritancePreviewOwner: true/);
  assert.match(source, /\/training-labels\/inherited\?algorithm_id=/);
  assert.match(source, /上一版本继承/);
  assert.match(source, /data-training-base-label/);
  assert.match(source, /当前素材标签已由上一版本继承，无需重复选择/);
  assert.equal(source.includes('inherited_from_codes'), false);
});

test('TrainingLabelRuntime remains wrapper-free timer-free and summary-backed', () => {
  const source = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url), 'utf8');
  for (const token of [
    '__trainingLabelsWrapped', 'wrappedEntrypoints', "wrap('startAlgorithmTraining429'", "wrap('refreshTrain429'",
    'train425Selected', 'tr425AssetAlg', 'train423Asset', '.train425-data', '.train428-data', 'setTimeout(',
  ]) {
    assert.equal(source.includes(token), false, `retired TrainingLabel lifecycle token remains: ${token}`);
  }
  assert.match(source, /trainingDraftRuntime\?\.subscribe/);
  assert.match(source, /materialSummaryRuntime\.summaryReadyFor/);
  assert.match(source, /materialSummaryRuntime\?\.invalidate\?\.\(\)/);
  assert.match(source, /queueMicrotask/);
  assert.match(source, /classicWrapperOwner: false/);
  assert.match(source, /timerOwner: false/);
  assert.match(source, /build: 'module-422569'/);
});

test('final stable renderers keep historical 423/425 training entrypoints unreachable', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const algorithmList = readFileSync(new URL('../../static/modules/algorithm-list-runtime.js', import.meta.url), 'utf8');
  assert.match(algorithmList, /data-algorithm-train="\$\{esc\(algorithm\.id\)\}"/);
  assert.match(algorithmList, /onclick="startAlgorithmTraining429\('\$\{esc\(algorithm\.id\)\}'\)"/);
  assert.equal(algorithmList.includes('startAlgorithmTraining423'), false);

  const finalTaskRenderer = app.lastIndexOf('window.renderTraining425=window.renderTraining424=window.renderTraining423=function(){');
  assert.ok(finalTaskRenderer >= 0);
  const taskSource = app.slice(finalTaskRenderer, finalTaskRenderer + 5000);
  assert.equal(taskSource.includes('openTrain425()'), false);
  assert.equal(taskSource.includes('▶ 开始训练'), false);
});
