function unique(values) {
  return [...new Set((values || []).map(value => String(value || '').trim()).filter(Boolean))];
}

function numberOr(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function trainingCacheRequestValue(value) {
  if (value === true) return 'True';
  if (value === false || value === null || value === undefined || value === '') return 'False';
  const normalized = String(value).trim().toLowerCase();
  if (['true', '1', 'yes', 'on'].includes(normalized)) return 'True';
  if (['false', '0', 'no', 'off', 'none'].includes(normalized)) return 'False';
  if (normalized === 'ram' || normalized === 'disk') return normalized;
  throw new Error('Cache 只支持 False / True / ram / disk');
}

function successfulVersion(version) {
  const status = String(version?.training_status || '').trim().toUpperCase();
  return ['SUCCEEDED', 'PARTIAL_SUCCESS', 'DONE', 'FINISHED', 'COMPLETED'].includes(status)
    && version?.artifact_verified === true
    && version?.trainable !== false;
}

function versionSortKey(version) {
  return String(version?.finished_at || version?.created_at || version?.version_name || '');
}

export function trainingBaseVersionFromAlgorithm(algorithm = {}) {
  const versions = [...(algorithm?.versions || [])]
    .sort((a, b) => versionSortKey(b).localeCompare(versionSortKey(a)));
  if (!versions.length) {
    return {hasAny: false, hasPrevious: false, blocked: false, versionId: ''};
  }

  const currentVersionId = String(algorithm?.current_version_id || '').trim();
  const previous = currentVersionId
    ? versions.find(version => String(version?.id || version?.version_id || '').trim() === currentVersionId) || null
    : versions.find(successfulVersion) || null;
  if (!previous || !successfulVersion(previous)) {
    return {hasAny: true, hasPrevious: false, blocked: true, versionId: ''};
  }
  return {
    hasAny: true,
    hasPrevious: true,
    blocked: false,
    versionId: String(previous.id || previous.version_id || '').trim(),
  };
}

export function createTrainingDraft(values = {}) {
  const splitMode = String(values.splitMode || 'random_test_from_training_pool');
  if (!['random_test_from_training_pool', 'independent_test_set'].includes(splitMode)) {
    throw new Error('不支持的训练素材切分方式');
  }

  // Existing manual drafts remain valid without a mode field. New create UI
  // explicitly selects full; the mode belongs to this canonical draft.
  const requestedMode = String(values.trainingMode || (values.resource?.strategy === 'manual' ? 'custom' : 'full'));
  const trainingMode = ['quick', 'full', 'complex', 'custom'].includes(requestedMode) ? requestedMode : 'full';
  const automaticMode = trainingMode !== 'custom';
  const materialIds = unique(values.materialIds);
  const testMaterialIds = splitMode === 'independent_test_set' ? unique(values.testMaterialIds) : [];

  return {
    trainingMode,
    algorithmId: String(values.algorithmId || '').trim(),
    baseVersionId: String(values.baseVersionId || '').trim(),
    materialIds,
    testMaterialIds,
    splitMode,
    experimentPercent: splitMode === 'random_test_from_training_pool'
      ? numberOr(values.experimentPercent, 20)
      : null,
    validationPercent: numberOr(values.validationPercent, 20),
    newLabelCodes: unique(values.newLabelCodes),
    benchmarkReuseEnabled: Boolean(values.benchmarkReuseEnabled),
    resource: {
      strategy: automaticMode ? 'auto' : String(values.resource?.strategy || 'manual'),
      profile: automaticMode ? 'performance' : String(values.resource?.profile || 'performance'),
      device: String(values.resource?.device || 'auto'),
      gpuPolicy: ['auto', 'exclusive'].includes(String(values.resource?.gpuPolicy || 'exclusive'))
        ? String(values.resource?.gpuPolicy || 'exclusive')
        : 'exclusive',
      batch: automaticMode ? null : (values.resource?.batch ?? null),
      workers: automaticMode ? null : (values.resource?.workers ?? null),
      cache: automaticMode ? null : (values.resource?.cache ?? null),
    },
    config: {...(values.config || {})},
    priority: numberOr(values.priority, 50),
  };
}

export function trainingDraftToRequest(draft, parameters = {}) {
  const normalized = createTrainingDraft(draft);
  if (!normalized.algorithmId) throw new Error('请选择训练算法');
  if (!normalized.materialIds.length) throw new Error('请选择训练素材');
  if (!normalized.baseVersionId && !normalized.newLabelCodes.length) {
    throw new Error('首次训练至少选择一个训练标签');
  }
  if (!(normalized.validationPercent > 0 && normalized.validationPercent < 100)) {
    throw new Error('验证集比例必须在 0 到 100 之间');
  }
  if (normalized.splitMode === 'random_test_from_training_pool'
      && !(normalized.experimentPercent > 0 && normalized.experimentPercent < 100)) {
    throw new Error('试验集比例必须在 0 到 100 之间');
  }
  if (normalized.splitMode === 'random_test_from_training_pool' && normalized.validationPercent + normalized.experimentPercent >= 100) {
    throw new Error('训练集比例必须大于 0；请调整验证集和试验集比例');
  }
  if (normalized.splitMode === 'independent_test_set' && !normalized.testMaterialIds.length) {
    throw new Error('请选择独立试验素材');
  }
  const overlap = normalized.testMaterialIds.filter(id => normalized.materialIds.includes(id));
  if (overlap.length) throw new Error('训练素材与独立试验素材不能重复');
  if (!Number.isInteger(normalized.priority) || normalized.priority < 1 || normalized.priority > 999) {
    throw new Error('任务优先级必须是 1~999 的整数');
  }

  const request = {
    ...parameters,
    algorithm_asset_id: normalized.algorithmId,
    training_mode: normalized.trainingMode,
    split_mode: normalized.splitMode,
    train_image_ids: normalized.materialIds,
    test_image_ids: normalized.testMaterialIds,
    experiment_percent: normalized.experimentPercent,
    validation_percent: normalized.validationPercent,
    train_labels: normalized.newLabelCodes,
    resource_strategy: normalized.resource.strategy,
    resource_profile: normalized.resource.profile,
    device: normalized.resource.device,
    gpu_policy: normalized.resource.gpuPolicy,
    queue_priority: normalized.priority,
  };
  if (normalized.resource.batch != null) request.batch = normalized.resource.batch;
  if (normalized.resource.workers != null) request.workers = normalized.resource.workers;
  if (normalized.resource.cache != null) request.cache = normalized.resource.cache;
  if (Object.hasOwn(request, 'cache')) request.cache = trainingCacheRequestValue(request.cache);
  return request;
}
