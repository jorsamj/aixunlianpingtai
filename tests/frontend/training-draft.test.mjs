import test from 'node:test';
import assert from 'node:assert/strict';

import {
  createTrainingDraft,
  trainingDraftFromLegacyState,
  trainingDraftToRequest,
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
      priority: 30,
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
  }));

  assert.equal(request.algorithm_asset_id, 'alg-1');
  assert.deepEqual(request.train_image_ids, ['a', 'b']);
  assert.deepEqual(request.train_labels, ['person']);
  assert.equal(request.batch, 16);
  assert.equal(request.workers, 4);
  assert.equal(request.cache, false);
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
