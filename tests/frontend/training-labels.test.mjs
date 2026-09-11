import test from 'node:test';
import assert from 'node:assert/strict';

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

test('current v42.9 training modal reads train429Selected instead of legacy train425Selected', () => {
  const state = {
    train429Selected: new Set(['img-new-1', 'img-new-2']),
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
