function unique(values) {
  return [...new Set((values || []).map(value => String(value || '').trim()).filter(Boolean))];
}

function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

export function createTrainingDraft(values = {}) {
  const splitMode = String(values.splitMode || 'random_test_from_training_pool');
  if (!['random_test_from_training_pool', 'independent_test_set'].includes(splitMode)) {
    throw new Error('不支持的训练素材切分方式');
  }

  const materialIds = unique(values.materialIds);
  const testMaterialIds = splitMode === 'independent_test_set' ? unique(values.testMaterialIds) : [];
  const inheritedLabelCodes = unique(values.inheritedLabelCodes);
  const newLabelCodes = unique(values.newLabelCodes).filter(code => !inheritedLabelCodes.includes(code));

  return {
    algorithmId: String(values.algorithmId || '').trim(),
    baseVersionId: String(values.baseVersionId || '').trim(),
    materialIds,
    testMaterialIds,
    splitMode,
    experimentPercent: splitMode === 'random_test_from_training_pool'
      ? numberOr(values.experimentPercent, 20)
      : null,
    validationPercent: numberOr(values.validationPercent, 20),
    inheritedLabelCodes,
    newLabelCodes,
    effectiveLabelCodes: unique([...inheritedLabelCodes, ...newLabelCodes]),
    resource: {
      strategy: String(values.resource?.strategy || 'auto'),
      device: String(values.resource?.device || 'auto'),
      gpuPolicy: String(values.resource?.gpuPolicy || 'auto'),
      batch: values.resource?.batch ?? null,
      workers: values.resource?.workers ?? null,
      cache: values.resource?.cache ?? null,
    },
    config: {...(values.config || {})},
    priority: numberOr(values.priority, 50),
  };
}

export function trainingDraftFromLegacyState(state = {}, {inheritedLabelCodes = []} = {}) {
  const algorithmId = String(state.train428AlgorithmId || '').trim();
  const split = state.trainSplitV3 || {};
  const trainSet = split.train instanceof Set
    ? [...split.train]
    : state.train429Selected instanceof Set
      ? [...state.train429Selected]
      : [];
  const testSet = split.test instanceof Set ? [...split.test] : [];
  const config = state.train428Config || {};
  const iteration = state.iteration414?.[algorithmId] || {};

  return createTrainingDraft({
    algorithmId,
    baseVersionId: iteration.version_id || iteration.id || '',
    materialIds: trainSet,
    testMaterialIds: testSet,
    splitMode: split.mode || 'random_test_from_training_pool',
    experimentPercent: split.experiment ?? 20,
    validationPercent: split.validation ?? 20,
    inheritedLabelCodes,
    newLabelCodes: state.trainingLabelSelected instanceof Set ? [...state.trainingLabelSelected] : [],
    resource: {
      strategy: config.resource_strategy || 'auto',
      device: config.device || 'auto',
      gpuPolicy: config.gpu_policy || 'auto',
      batch: config.batch ?? null,
      workers: config.workers ?? null,
      cache: config.cache ?? null,
    },
    config,
    priority: config.priority ?? state.trainPriority ?? 50,
  });
}

export function trainingDraftToRequest(draft, parameters = {}) {
  const normalized = createTrainingDraft(draft);
  if (!normalized.algorithmId) throw new Error('请选择训练算法');
  if (!normalized.materialIds.length) throw new Error('请选择训练素材');
  if (!normalized.effectiveLabelCodes.length) throw new Error('至少选择一个训练标签');
  if (!(normalized.validationPercent > 0 && normalized.validationPercent < 100)) {
    throw new Error('验证集比例必须在 0 到 100 之间');
  }
  if (normalized.splitMode === 'random_test_from_training_pool'
      && !(normalized.experimentPercent > 0 && normalized.experimentPercent < 100)) {
    throw new Error('试验集比例必须在 0 到 100 之间');
  }
  if (normalized.splitMode === 'independent_test_set' && !normalized.testMaterialIds.length) {
    throw new Error('请选择独立试验素材');
  }
  const overlap = normalized.testMaterialIds.filter(id => normalized.materialIds.includes(id));
  if (overlap.length) throw new Error('训练素材与独立试验素材不能重复');

  return {
    ...parameters,
    algorithm_asset_id: normalized.algorithmId,
    split_mode: normalized.splitMode,
    train_image_ids: normalized.materialIds,
    test_image_ids: normalized.testMaterialIds,
    experiment_percent: normalized.experimentPercent,
    validation_percent: normalized.validationPercent,
    train_labels: normalized.newLabelCodes,
    resource_strategy: normalized.resource.strategy,
    device: normalized.resource.device,
    gpu_policy: normalized.resource.gpuPolicy,
    batch: normalized.resource.batch,
    workers: normalized.resource.workers,
    cache: normalized.resource.cache,
    priority: normalized.priority,
  };
}
