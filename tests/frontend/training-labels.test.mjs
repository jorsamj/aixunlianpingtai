import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';

import {
  latestVersionLabelInfo,
  resolveClientTrainingLabels,
  selectedMaterialLabelCodes,
  selectedTrainingMaterialIds,
} from '../../static/modules/training-labels.js';

const catalog = [
  {code: 'fire', display_name: '明火'},
  {code: 'smoke', display_name: '烟雾'},
  {code: 'person', display_name: '人员'},
  {code: 'helmet', display_name: '安全帽'},
  {code: 'cigarette', display_name: '香烟'},
];

function successfulVersion(overrides = {}) {
  return {
    id: 'v1',
    created_at: '2026-09-10T00:00:00Z',
    training_status: 'SUCCEEDED',
    artifact_verified: true,
    trainable: true,
    ...overrides,
  };
}

test('available labels come only from selected materials', () => {
  const materials = [
    {id: 'a', labels: ['fire', 'person']},
    {id: 'b', labels: ['smoke']},
    {id: 'c', labels: ['helmet']},
  ];
  assert.deepEqual(
    selectedMaterialLabelCodes(materials, ['a', 'b'], catalog),
    ['fire', 'smoke', 'person'],
  );
});

test('confirmed empty scope contributes concrete labels and ignores legacy star', () => {
  const materials = [
    {id: 'a', labels: [], annotation_scope: ['fire', 'smoke']},
    {id: 'b', labels: [], annotation_scope: ['*']},
  ];
  assert.deepEqual(
    selectedMaterialLabelCodes(materials, ['a', 'b'], catalog),
    ['fire', 'smoke'],
  );
});

test('training material ids come only from canonical draft even when historical state is polluted', () => {
  const state = {
    train428AlgorithmId: 'stale-algorithm',
    train429Selected: new Set(['stale-material']),
    train425Selected: {
      train: new Set(['stale-train']),
      val: new Set(['stale-val']),
    },
    trainingDraft: {
      algorithmId: 'canonical-algorithm',
      materialIds: ['canonical-1', 'canonical-2'],
    },
  };
  assert.deepEqual(selectedTrainingMaterialIds(state), ['canonical-1', 'canonical-2']);
});

test('training materials are empty before canonical draft exists', () => {
  const state = {
    train429Selected: new Set(['retired-value']),
    train425Selected: {train: new Set(['retired-train'])},
  };
  assert.deepEqual(selectedTrainingMaterialIds(state), []);
});

test('previous version labels are inherited and only material labels are selectable additions', () => {
  const algorithm = {
    versions: [successfulVersion({
      label_schema: [
        {code: 'fire', class_id: 0},
        {code: 'smoke', class_id: 1},
      ],
    })],
  };
  const view = resolveClientTrainingLabels({
    materials: [{id: 'a', labels: ['fire', 'cigarette', 'person']}],
    selectedIds: ['a'],
    labelCatalog: catalog,
    algorithm,
    requestedCodes: ['cigarette'],
  });
  assert.deepEqual(view.inherited, ['fire', 'smoke']);
  assert.deepEqual(view.selectable, ['person', 'cigarette']);
  assert.deepEqual(view.requested, ['cigarette']);
  assert.deepEqual(view.effectivePreview, ['fire', 'smoke', 'cigarette']);
});

test('failed newer version never overrides latest successful trainable label schema', () => {
  const info = latestVersionLabelInfo({
    versions: [
      successfulVersion({
        id: 'ok',
        created_at: '2026-09-10T00:00:00Z',
        label_schema: [{code: 'fire', class_id: 0}],
      }),
      {
        id: 'failed-newer',
        created_at: '2026-09-11T00:00:00Z',
        training_status: 'FAILED',
        artifact_verified: false,
        trainable: false,
        label_schema: [{code: 'person', class_id: 0}],
      },
    ],
  });
  assert.equal(info.version.id, 'ok');
  assert.deepEqual(info.codes, ['fire']);
});

test('algorithm with versions but no successful trainable version is blocked instead of treated as first training', () => {
  const info = latestVersionLabelInfo({
    versions: [{
      id: 'failed',
      created_at: '2026-09-11T00:00:00Z',
      training_status: 'FAILED',
      artifact_verified: false,
      trainable: false,
    }],
  });
  assert.equal(info.hasAnyVersion, true);
  assert.equal(info.hasVersion, false);
  assert.equal(info.blocked, true);
});

test('first training never inherits mother-model classes', () => {
  const view = resolveClientTrainingLabels({
    materials: [{id: 'a', labels: ['fire', 'smoke']}],
    selectedIds: ['a'],
    labelCatalog: catalog,
    algorithm: {versions: []},
    requestedCodes: ['fire'],
  });
  assert.equal(view.hasPreviousVersion, false);
  assert.deepEqual(view.inherited, []);
  assert.deepEqual(view.effectivePreview, ['fire']);
});

test('legacy successful previous version is flagged for server-side snapshot recovery', () => {
  const info = latestVersionLabelInfo({
    versions: [successfulVersion({id: 'old'})],
  });
  assert.equal(info.hasVersion, true);
  assert.equal(info.legacyUnknown, true);
  assert.deepEqual(info.codes, []);
});

test('TrainingLabelRuntime is wrapper-free timer-free and canonical-only', () => {
  const source = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url), 'utf8');
  for (const token of [
    '__trainingLabelsWrapped',
    'wrappedEntrypoints',
    "wrap('startAlgorithmTraining429'",
    "wrap('refreshTrain429'",
    'train425Selected',
    'tr425AssetAlg',
    'train423Asset',
    '.train425-data',
    '.train428-data',
    'setTimeout(',
  ]) {
    assert.equal(source.includes(token), false, `retired TrainingLabel lifecycle token remains: ${token}`);
  }
  assert.match(source, /trainingDraftRuntime\?\.subscribe/);
  assert.match(source, /queueMicrotask/);
  assert.match(source, /classicWrapperOwner: false/);
  assert.match(source, /timerOwner: false/);
  assert.match(source, /build: 'module-422511'/);
});

test('final stable renderers keep historical 423/425 training entrypoints unreachable', () => {
  const app = readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');

  const stableCards = app.lastIndexOf('window.renderAlg412=function(){');
  const stableAlgorithmPage = app.lastIndexOf('window.renderAlgorithms423=function(){');
  assert.ok(stableCards >= 0 && stableAlgorithmPage > stableCards);
  const cardSource = app.slice(stableCards, stableAlgorithmPage);
  assert.match(cardSource, /startAlgorithmTraining429\('\$\{a\.id\}'\)/);
  assert.equal(cardSource.includes("startAlgorithmTraining423('${a.id}')"), false);

  const finalTaskRenderer = app.lastIndexOf('window.renderTraining425=window.renderTraining424=window.renderTraining423=function(){');
  assert.ok(finalTaskRenderer >= 0);
  const taskSource = app.slice(finalTaskRenderer, finalTaskRenderer + 5000);
  assert.equal(taskSource.includes('openTrain425()'), false);
  assert.equal(taskSource.includes('▶ 开始训练'), false);

  const last423Call = app.lastIndexOf("startAlgorithmTraining423('${a.id}')");
  const last425OpenCall = app.lastIndexOf('openTrain425(');
  const last425CountCall = app.lastIndexOf('trainCounts425()');
  assert.ok(last423Call >= 0 && last423Call < stableCards);
  assert.ok(last425OpenCall >= 0 && last425OpenCall < finalTaskRenderer);
  assert.ok(last425CountCall >= 0 && last425CountCall < finalTaskRenderer);
});
