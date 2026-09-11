import test from 'node:test';
import assert from 'node:assert/strict';

import {
  latestVersionLabelInfo,
  resolveClientTrainingLabels,
  selectedMaterialLabelCodes,
} from '../../static/modules/training-labels.js';

const catalog = [
  {code: 'fire', display_name: '明火'},
  {code: 'smoke', display_name: '烟雾'},
  {code: 'person', display_name: '人员'},
  {code: 'helmet', display_name: '安全帽'},
  {code: 'cigarette', display_name: '香烟'},
];

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

test('previous version labels are inherited and only material labels are selectable additions', () => {
  const algorithm = {
    versions: [{
      id: 'v1',
      created_at: '2026-09-10T00:00:00Z',
      artifact_verified: true,
      trainable: true,
      label_schema: [
        {code: 'fire', class_id: 0},
        {code: 'smoke', class_id: 1},
      ],
    }],
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

test('legacy previous version is flagged for server-side snapshot recovery', () => {
  const info = latestVersionLabelInfo({
    versions: [{id: 'old', created_at: '2026-09-10T00:00:00Z', artifact_verified: true, trainable: true}],
  });
  assert.equal(info.hasVersion, true);
  assert.equal(info.legacyUnknown, true);
  assert.deepEqual(info.codes, []);
});
