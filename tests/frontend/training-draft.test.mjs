import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTrainingDraft,
  trainingDraftFromLegacyState,
  trainingDraftToRequest,
  trainingInheritanceFromAlgorithm,
} from '../../static/modules/training-draft.js';

test('canonical draft deduplicates materials and separates inherited from new labels', () => {
  const draft = createTrainingDraft({
    algorithmId: 'alg-1',
    materialIds: ['a', 'a', 'b'],
    inheritedLabelCodes: ['fire', 'smoke'],
    newLabelCodes: ['smoke', 'person', 'person'],
  });

  assert.deepEqual(draft.materialIds, ['a', 'b']);
  assert.deepEqual(draft.inheritedLabelCodes, ['fire', 'smoke']);
  assert.deepEqual(draft.newLabelCodes, ['person']);
  assert.deepEqual(draft.effectiveLabelCodes, ['fire', 'smoke', 'person']);
});

test('inheritance comes only from the latest successful artifact-verified trainable version', () => {
  const inheritance = trainingInheritanceFromAlgorithm({
    versions: [
      {
        id: 'failed-new', created_at: '2026-09-11T03:00:00Z', training_status: 'FAILED',
        artifact_verified: false, label_schema: [{class_id: 0, code: 'wrong'}],
      },
      {
        id: 'good-old', created_at: '2026-09-10T03:00:00Z', training_status: 'SUCCEEDED',
        artifact_verified: true, trainable: true,
        label_schema: [{class_id: 1, code: 'smoke'}, {class_id: 0, code: 'fire'}],
      },
    ],
  });

  assert.equal(inheritance.versionId, 'good-old');
  assert.deepEqual(inheritance.codes, ['fire', 'smoke']);
  assert.equal(inheritance.legacy, false);
});

test('successful historical version without stored schema is marked pending instead of guessing labels', () => {
  const inheritance = trainingInheritanceFromAlgorithm({
    versions: [{
      id: 'legacy-v1', training_status: 'SUCCEEDED', artifact_verified: true, trainable: true,
    }],
  });

  assert.equal(inheritance.hasPrevious, true);
  assert.equal(inheritance.legacy, true);
  assert.deepEqual(inheritance.codes, []);
});

test('legacy training state is mapped into one canonical draft without changing old state', () => {
  const state = {
    train428AlgorithmId: 'alg-1',
    trainSplitV3: {
      mode: 'independent_test_set',
      train: new Set(['a', 'b']),
      test: new Set(['c']),
      experiment: 15,
      validation: 20,
    },
    trainingLabelSelected: new Set(['person']),
    train428Config: {
      resource_strategy: 'manual',
      device: '0',
      gpu_policy: 'exclusive',
      batch: 16,
      workers: 4,
      cache: false,
      queue_priority: 30,
    },
    iteration414: {'alg-1': {version_id: 'v-prev'}},
  };

  const draft = trainingDraftFromLegacyState(state, {inheritedLabelCodes: ['fire', 'smoke']});

  assert.equal(draft.baseVersionId, 'v-prev');
  assert.deepEqual(draft.materialIds, ['a', 'b']);
  assert.deepEqual(draft.testMaterialIds, ['c']);
  assert.deepEqual(draft.effectiveLabelCodes, ['fire', 'smoke', 'person']);
  assert.deepEqual(draft.resource, {
    strategy: 'manual', device: '0', gpuPolicy: 'exclusive', batch: 16, workers: 4, cache: false,
  });
  assert.equal(draft.priority, 30);
  assert.deepEqual([...state.trainSplitV3.train], ['a', 'b']);
});

test('request uses new labels for the task while inherited labels remain in effective schema', () => {
  const request = trainingDraftToRequest(createTrainingDraft({
    algorithmId: 'alg-1',
    materialIds: ['a', 'b'],
    inheritedLabelCodes: ['fire', 'smoke'],
    newLabelCodes: ['person'],
    splitMode: 'random_test_from_training_pool',
    experimentPercent: 20,
    validationPercent: 20,
    resource: {strategy: 'manual', device: '0', batch: 16, workers: 4, cache: false},
    priority: 30,
  }));

  assert.equal(request.algorithm_asset_id, 'alg-1');
  assert.deepEqual(request.train_image_ids, ['a', 'b']);
  assert.deepEqual(request.train_labels, ['person']);
  assert.equal(request.batch, 16);
  assert.equal(request.workers, 4);
  assert.equal(request.cache, false);
  assert.equal(request.queue_priority, 30);
  assert.equal('priority' in request, false);
});

test('legacy inherited schema pending allows backend snapshot recovery without frontend guessing', () => {
  const request = trainingDraftToRequest(createTrainingDraft({
    algorithmId: 'alg-1',
    materialIds: ['a', 'b'],
    inheritedLabelCodes: [],
    newLabelCodes: [],
    inheritancePending: true,
  }));
  assert.deepEqual(request.train_labels, []);
});

test('draft request rejects overlapping independent test materials', () => {
  assert.throws(() => trainingDraftToRequest(createTrainingDraft({
    algorithmId: 'alg-1',
    materialIds: ['a', 'b'],
    testMaterialIds: ['b', 'c'],
    splitMode: 'independent_test_set',
    inheritedLabelCodes: ['fire'],
  })), /不能重复/);
});
