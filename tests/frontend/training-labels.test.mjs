import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  resolveClientTrainingLabels,
  selectedMaterialLabelCodes,
  selectedTrainingMaterialIds,
  selectionForState,
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

test('session-scoped new-label choices persist with supported positives, then reset for a new version',()=>{
  const state={trainingLabelAlgorithmId:'["p","algorithm","base-v1"]',trainingDraft:{newLabelCodes:['helmet','smoke']}};
  assert.deepEqual(selectionForState(state,state.trainingLabelAlgorithmId,['helmet']),['helmet']);
  assert.deepEqual(selectionForState(state,'["p","algorithm","base-v2"]',['helmet','smoke']),[]);
  assert.equal(state.trainingLabelAlgorithmId,'["p","algorithm","base-v2"]');
});

test('client task choices exclude retired project labels', () => {
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

test('only selected formal positive evidence creates new first-training choices', () => {
  const availableCodes = ['person', 'helmet', 'smoke']; // Server summary across selected pages.
  const view = resolveClientTrainingLabels({
    materials: [{id:'page-1', labels:['person']}],
    selectedIds:['page-1','page-9','page-15','confirmed-empty'],
    labelCatalog:[{code:'person'},{code:'helmet'},{code:'smoke'},{code:'fire'},{code:'phone'},{code:'car'}],
    availableCodes,
    requestedCodes:['person','smoke','fire','car'],
  });
  assert.deepEqual(view.selectable,['person','helmet','smoke']);
  assert.deepEqual(view.requested,['person','smoke']);
});

test('no selected positive GT means no new classes, and inactive or unmapped labels cannot be chosen',()=>{
  const view=resolveClientTrainingLabels({materials:[],selectedIds:['negative'],
    availableCodes:['retired','unknown_2'],labelCatalog:[{code:'fire'},{code:'retired',active:false},{code:'unknown_2'}],
    requestedCodes:['fire','retired','unknown_2']});
  assert.deepEqual(view.selectable,[]);
  assert.deepEqual(view.requested,[]);
  assert.deepEqual(view.invalidAvailable,['retired','unknown_2']);
});

test('first render never auto-selects material labels for the user', () => {
  const source = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url), 'utf8');
  assert.match(source, /state\.trainingLabelAlgorithmId = sessionKey;\r?\n\s*return \[\];/);
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
  assert.match(source, /上一版本继承标签保持不变/);
  assert.match(source, /本次可新增标签/);
  assert.equal(source.includes('inherited_from_codes'), false);
});

test('switching selected algorithm or base version invalidates temporary new-label choices',()=>{
  const source = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url),'utf8');
  assert.match(source,/sessionKey = JSON\.stringify\(\[String\(projectId\?\.\(\)/);
  assert.match(source,/state\?\.trainingDraft\?\.baseVersionId/);
  assert.match(source,/if \(sessionChanged\) \{/);
  assert.match(source,/syncDraftLabels\(state, \[\]\)/);
  assert.match(source,/已取消不再受所选素材正样本支持的新增标签/);
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
  assert.match(source, /build: 'module-422574'/);
});

test('final stable renderers keep historical 423/425 training entrypoints unreachable', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  const algorithmList = readFileSync(new URL('../../static/modules/algorithm-list-runtime.js', import.meta.url), 'utf8');
  const visibility = readFileSync(new URL('../../static/modules/training-task-visibility-runtime.js', import.meta.url), 'utf8');
  assert.match(algorithmList, /data-algorithm-train="\$\{esc\(algorithm\.id\)\}"/);
  assert.match(algorithmList, /onclick="startAlgorithmTraining429\('\$\{esc\(algorithm\.id\)\}'\)"/);
  assert.equal(algorithmList.includes('startAlgorithmTraining423'), false);

  assert.equal(app.includes('window.renderTraining423'), false);
  for (const name of ['renderTraining423', 'renderTraining424', 'renderTraining425']) {
    assert.equal((visibility.match(new RegExp('window\\.' + name + '\\s*=\\s*renderTraining', 'g')) || []).length, 1, name);
  }
  const finalTaskRenderer = visibility.indexOf('const renderTraining = () => {');
  assert.ok(finalTaskRenderer >= 0);
  const taskSource = visibility.slice(finalTaskRenderer, finalTaskRenderer + 2500);
  assert.equal(taskSource.includes('openTrain425()'), false);
  assert.equal(taskSource.includes('▶ 开始训练'), false);
});

test('cross-label target without a selected positive is not an allowed new class',()=>{
 const view=resolveClientTrainingLabels({materials:[{id:'p',labels:['person']}],selectedIds:['p'],labelCatalog:[{code:'vest'},{code:'person'}],requestedCodes:['vest']});
 assert.deepEqual(view.available,['person']);assert.deepEqual(view.requested,[]);assert.deepEqual(view.selectable,['person']);
});

 test('first cross-label target is unavailable until positive evidence exists',()=>{
 const args={materials:[{id:'p',labels:['person']}],selectedIds:['p'],labelCatalog:[{code:'vest'},{code:'person'},{code:'retired',active:false}],requestedCodes:[]};
 const initial=resolveClientTrainingLabels(args);
 assert.deepEqual(initial.selectable,['person']);
 assert.deepEqual(initial.available,['person']);
 assert.deepEqual(initial.requested,[]);
 const chosen=resolveClientTrainingLabels({...args,requestedCodes:['vest']});
 assert.deepEqual(chosen.requested,[]);
 assert.deepEqual(chosen.available,['person']);
 });
