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

export function trainingInheritanceFromAlgorithm(algorithm = {}) {
  const versions = [...(algorithm?.versions || [])].sort((a, b) => versionSortKey(b).localeCompare(versionSortKey(a)));
  if (!versions.length) {
    return {hasAny: false, hasPrevious: false, blocked: false, legacy: false, codes: [], versionId: ''};
  }

  const currentVersionId = String(algorithm?.current_version_id || '').trim();
  const previous = currentVersionId
    ? versions.find(version => String(version?.id || version?.version_id || '').trim() === currentVersionId) || null
    : versions.find(successfulVersion) || null;
  if (!previous || !successfulVersion(previous)) {
    return {hasAny: true, hasPrevious: false, blocked: true, legacy: false, codes: [], versionId: ''};
  }

  const schema = [...(previous.label_schema || [])]
    .sort((a, b) => Number(a?.class_id ?? 1e9) - Number(b?.class_id ?? 1e9));
  const codes = unique(schema.map(item => item?.code));
  const fallbackCodes = codes.length ? codes : unique(previous.label_codes || []);
  return {
    hasAny: true,
    hasPrevious: true,
    blocked: false,
    legacy: !fallbackCodes.length,
    codes: fallbackCodes,
    versionId: String(previous.id || previous.version_id || '').trim(),
  };
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
    inheritancePending: Boolean(values.inheritancePending),
    benchmarkReuseEnabled: Boolean(values.benchmarkReuseEnabled),
    resource: {
      strategy: String(values.resource?.strategy || 'auto'),
      profile: String(values.resource?.profile || 'balanced'),
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

export function trainingDraftToRequest(draft, parameters = {}) {
  const normalized = createTrainingDraft(draft);
  if (!normalized.algorithmId) throw new Error('请选择训练算法');
  if (!normalized.materialIds.length) throw new Error('请选择训练素材');
  if (!normalized.effectiveLabelCodes.length && !normalized.inheritancePending) {
    throw new Error('至少选择一个训练标签');
  }
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
  if (!Number.isInteger(normalized.priority) || normalized.priority < 1 || normalized.priority > 999) {
    throw new Error('任务优先级必须是 1~999 的整数');
  }

  const request = {
    ...parameters,
    algorithm_asset_id: normalized.algorithmId,
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
