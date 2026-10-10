import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTrainingDraft,
  trainingBaseVersionFromAlgorithm,
  trainingDraftToRequest,
} from '../../static/modules/training-draft.js';

test('canonical draft deduplicates materials and only stores explicit user label choices', () => {
  const draft = createTrainingDraft({
    algorithmId: 'alg-1',
    materialIds: ['a', 'a', 'b'],
    newLabelCodes: ['smoke', 'person', 'person'],
  });
  assert.deepEqual(draft.materialIds, ['a', 'b']);
  assert.deepEqual(draft.newLabelCodes, ['smoke', 'person']);
  assert.equal('inheritedLabelCodes' in draft, false);
  assert.equal('effectiveLabelCodes' in draft, false);
  assert.equal('inheritancePending' in draft, false);
});

test('base version identity follows latest successful verified trainable version without reading labels', () => {
  const base = trainingBaseVersionFromAlgorithm({
    versions: [
      {id: 'failed-new', created_at: '2026-09-11T03:00:00Z', training_status: 'FAILED', artifact_verified: false},
      {id: 'good-old', created_at: '2026-09-10T03:00:00Z', training_status: 'SUCCEEDED', artifact_verified: true, trainable: true,
       label_schema: [{class_id: 0, code: 'fire'}]},
    ],
  });
  assert.equal(base.versionId, 'good-old');
  assert.equal(base.hasPrevious, true);
  assert.equal('codes' in base, false);
});

test('explicit current version remains the base identity after rollback', () => {
  const base = trainingBaseVersionFromAlgorithm({
    current_version_id: 'v3',
    versions: [
      {id: 'v5', created_at: '2026-09-12T03:00:00Z', training_status: 'SUCCEEDED', artifact_verified: true, trainable: true},
      {id: 'v3', created_at: '2026-09-10T03:00:00Z', training_status: 'SUCCEEDED', artifact_verified: true, trainable: true},
    ],
  });
  assert.equal(base.versionId, 'v3');
});

test('versions without a successful trainable base are blocked without guessing label history', () => {
  const base = trainingBaseVersionFromAlgorithm({
    versions: [{id: 'failed', training_status: 'FAILED', artifact_verified: false}],
  });
  assert.equal(base.hasAny, true);
  assert.equal(base.hasPrevious, false);
  assert.equal(base.blocked, true);
  assert.equal('codes' in base, false);
});

test('empty canonical draft has safe defaults and no label-history state', () => {
  const draft = createTrainingDraft();
  assert.equal(draft.algorithmId, '');
  assert.equal(draft.baseVersionId, '');
  assert.deepEqual(draft.materialIds, []);
  assert.deepEqual(draft.testMaterialIds, []);
  assert.deepEqual(draft.newLabelCodes, []);
  assert.equal(draft.splitMode, 'random_test_from_training_pool');
  assert.equal(draft.experimentPercent, 20);
  assert.equal(draft.validationPercent, 20);
  assert.deepEqual(draft.resource, {
    strategy: 'auto', profile: 'performance', device: 'auto', gpuPolicy: 'exclusive', batch: null, workers: null, cache: null,
  });
  assert.equal(draft.priority, 50);
});

test('request submits only explicit labels while server owns inherited and merged schema', () => {
  const request = trainingDraftToRequest(createTrainingDraft({
    algorithmId: 'alg-1',
    baseVersionId: 'v1',
    materialIds: ['a', 'b'],
    newLabelCodes: ['person'],
    resource: {strategy: 'manual', device: '0', batch: 16, workers: 4, cache: false},
    priority: 30,
  }));
  assert.equal(request.algorithm_asset_id, 'alg-1');
  assert.deepEqual(request.train_image_ids, ['a', 'b']);
  assert.deepEqual(request.train_labels, ['person']);
  assert.equal(request.batch, 16);
  assert.equal(request.workers, 4);
  assert.equal(request.cache, 'False');
  assert.equal(request.queue_priority, 30);
});

test('iteration may submit zero explicit new labels because server owns previous schema', () => {
  const request = trainingDraftToRequest(createTrainingDraft({
    algorithmId: 'alg-1',
    baseVersionId: 'v1',
    materialIds: ['a', 'b'],
    newLabelCodes: [],
  }));
  assert.deepEqual(request.train_labels, []);
});

test('first training still requires at least one explicit material label', () => {
  assert.throws(() => trainingDraftToRequest(createTrainingDraft({
    algorithmId: 'alg-1',
    materialIds: ['a', 'b'],
    newLabelCodes: [],
  })), /首次训练至少选择一个训练标签/);
});

test('retired shared GPU draft state normalizes to exclusive GPU ownership', () => {
  assert.equal(createTrainingDraft({resource: {gpuPolicy: 'shared'}}).resource.gpuPolicy, 'exclusive');
  assert.equal(createTrainingDraft({resource: {gpuPolicy: 'exclusive'}}).resource.gpuPolicy, 'exclusive');
});

test('request serializes cache into backend string contract', () => {
  const base = {algorithmId: 'alg-1', materialIds: ['a', 'b'], newLabelCodes: ['fire']};
  for (const [cache, expected] of [[false, 'False'], [true, 'True'], ['False', 'False'], ['True', 'True'], ['ram', 'ram'], ['disk', 'disk']]) {
    assert.equal(trainingDraftToRequest(createTrainingDraft({...base, resource: {cache}})).cache, expected);
  }
});

test('draft request rejects overlapping independent test materials', () => {
  assert.throws(() => trainingDraftToRequest(createTrainingDraft({
    algorithmId: 'alg-1',
    baseVersionId: 'v1',
    materialIds: ['a', 'b'],
    testMaterialIds: ['b', 'c'],
    splitMode: 'independent_test_set',
  })), /不能重复/);
});

test('draft request preserves 1-999 integer priority contract', () => {
  const base = {algorithmId: 'alg-1', materialIds: ['a', 'b'], newLabelCodes: ['fire']};
  for (const priority of [0, 1000, 1.5]) {
    assert.throws(() => trainingDraftToRequest(createTrainingDraft({...base, priority})), /1~999 的整数/);
  }
  assert.equal(trainingDraftToRequest(createTrainingDraft({...base, priority: 1})).queue_priority, 1);
  assert.equal(trainingDraftToRequest(createTrainingDraft({...base, priority: 999})).queue_priority, 999);
});
