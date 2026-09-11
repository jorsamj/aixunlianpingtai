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

test('current training modal prefers canonical material ids over stale train429Selected', () => {
  const state = {
    train428AlgorithmId: 'alg-1',
    trainingDraft: {algorithmId: 'alg-1', materialIds: ['img-new-1', 'img-new-2']},
    train429Selected: new Set(['img-stale']),
    train425Selected: {
      train: new Set(['img-old-train']),
      val: new Set(['img-old-val']),
    },
  };
  assert.deepEqual(
    selectedTrainingMaterialIds(state, {preferV429: true}),
    ['img-new-1', 'img-new-2'],
  );
  assert.deepEqual(
    selectedTrainingMaterialIds(state, {preferV429: false}),
    ['img-old-train', 'img-old-val'],
  );
});

test('canonical material ids stay authoritative when legacy algorithm and selection are stale', () => {
  const state = {
    train428AlgorithmId: 'stale-algorithm',
    train429Selected: new Set(['stale-material']),
    trainingDraft: {
      algorithmId: 'canonical-algorithm',
      materialIds: ['canonical-1', 'canonical-2'],
    },
  };
  assert.deepEqual(
    selectedTrainingMaterialIds(state, {preferV429: true}),
    ['canonical-1', 'canonical-2'],
  );
});

test('current training modal returns no materials before canonical draft exists', () => {
  const state = {train429Selected: new Set(['retired-legacy-value'])};
  assert.deepEqual(selectedTrainingMaterialIds(state, {preferV429: true}), []);
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


test('TrainingLabel runtime does not rebind removed 428 entrypoints', () => {
  const source = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url), 'utf8');
  assert.equal(source.includes("wrap('openTrain428'"), false);
  assert.equal(source.includes("wrap('refreshTrain428'"), false);
  assert.match(source, /build: 'module-422510'/);
});


test('final stable renderers make historical 423/425 training entrypoints unreachable', () => {
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

  const labels = readFileSync(new URL('../../static/modules/training-labels.js', import.meta.url), 'utf8');
  assert.equal(labels.includes("wrap('startAlgorithmTraining423'"), false);
  assert.equal(labels.includes("wrap('openTrain425'"), false);
  assert.equal(labels.includes("wrap('trainCounts425'"), false);
  assert.match(labels, /build: 'module-422510'/);
});
