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

export function trainingInheritedDefaults(algorithm={}) {
  const base=trainingBaseVersionFromAlgorithm(algorithm);
  if(!base.hasPrevious)return {};
  const version=algorithm.versions.find(row=>String(row.id||row.version_id)===base.versionId);
  const actual=version?.training_lineage?.parameters?.actual||version?.training_report?.actual_train_params||version?.report?.actual_train_params||{};
  const precision=String(actual.effective_precision||actual.runtime_precision||actual.precision||'').toLowerCase();
  const size=actual.imgsz;
  return {...(['fp16','fp32'].includes(precision)?{precision,amp:precision==='fp16'}:{}),...(Number.isInteger(size)&&size>=32&&size<=4096?{imgsz:size}:{})};
}

export function createTrainingDraft(values = {}) {
  const splitMode = String(values.splitMode || 'random_test_from_training_pool');
  if (!['random_test_from_training_pool', 'independent_test_set', 'fixed_zip_train_val_test'].includes(splitMode)) {
    throw new Error('不支持的训练素材切分方式');
  }

  // Existing manual drafts remain valid without a mode field. New create UI
  // explicitly selects full; the mode belongs to this canonical draft.
  const legacyManualInput = values.resource?.strategy === 'manual'
    || (values.trainingMode == null && values.resource != null
      && values.resource.strategy == null
      && ['batch', 'workers', 'cache'].some(key => values.resource[key] != null));
  const requestedMode = String(values.trainingMode || (legacyManualInput ? 'custom' : 'full'));
  const trainingMode = ['quick', 'full', 'complex', 'custom'].includes(requestedMode) ? requestedMode : 'full';
  const automaticMode = trainingMode !== 'custom';
  const materialIds = unique(values.materialIds);
  const testMaterialIds = splitMode === 'independent_test_set' ? unique(values.testMaterialIds) : [];

  return {
    trainingMode,
    algorithmId: String(values.algorithmId || '').trim(),
    baseVersionId: String(values.baseVersionId || '').trim(),
    materialIds,
    trainSelectionRef:String(values.trainSelectionRef || ''),
    trainSelectionCount:Math.max(0,Number(values.trainSelectionCount || 0)),
    testMaterialIds,
    ...(values.duplicateReview ? {duplicateReview: {
      ...(values.duplicateReview.review_kind==='EXPLICIT_SELECTION_ADJUSTMENT'?{review_kind:'EXPLICIT_SELECTION_ADJUSTMENT'}:{}),
      original_train_image_ids: unique(values.duplicateReview.original_train_image_ids),
      original_test_image_ids: unique(values.duplicateReview.original_test_image_ids),
      excluded_image_ids: unique(values.duplicateReview.excluded_image_ids),
      material_revision: Number(values.duplicateReview.material_revision),
      annotation_revision: Number(values.duplicateReview.annotation_revision),
    }} : {}),
    splitMode,
    zipSourceJobIds: unique(values.zipSourceJobIds),
    experimentPercent: splitMode === 'random_test_from_training_pool'
      ? numberOr(values.experimentPercent ?? 20, 20)
      : null,
    validationPercent: splitMode === 'fixed_zip_train_val_test' ? null : numberOr(values.validationPercent, 20),
    newLabelCodes: unique(values.newLabelCodes),
    benchmarkReuseEnabled: Boolean(values.benchmarkReuseEnabled),
    history_policy: String(values.history_policy || 'new_for_algorithm'),
    robustness_policy: JSON.parse(JSON.stringify(values.robustness_policy || {mode:'inherit'})),
    resource: {
      strategy: automaticMode ? 'auto' : String(values.resource?.strategy || 'manual'),
      profile: automaticMode ? 'performance' : String(values.resource?.profile || 'performance'),
      device: String(values.resource?.device || 'auto'),
      // Legacy auto must not override the single-physical-GPU reservation contract.
      gpuPolicy: 'exclusive',
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
  if (normalized.splitMode !== 'fixed_zip_train_val_test' && !normalized.materialIds.length && !normalized.trainSelectionRef) throw new Error('请选择训练素材');
  if (!normalized.baseVersionId && !normalized.newLabelCodes.length) {
    throw new Error('首次训练至少选择一个训练标签');
  }
  if (normalized.splitMode !== 'fixed_zip_train_val_test' && !(normalized.validationPercent > 0 && normalized.validationPercent < 100)) {
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
  const trainIdSet = normalized.testMaterialIds.length ? new Set(normalized.materialIds) : null;
  const overlap = normalized.testMaterialIds.filter(id => trainIdSet.has(id));
  if (overlap.length) throw new Error('训练素材与独立试验素材不能重复');
  if (!Number.isInteger(normalized.priority) || normalized.priority < 1 || normalized.priority > 999) {
    throw new Error('任务优先级必须是 1~999 的整数');
  }

  if (normalized.splitMode === 'fixed_zip_train_val_test' && !normalized.zipSourceJobIds.length) throw new Error('请选择 ZIP 来源');
  const request = {
    ...parameters,
    algorithm_asset_id: normalized.algorithmId,
    base_version_id: normalized.baseVersionId,
    training_mode: normalized.trainingMode,
    history_policy: normalized.history_policy,
    robustness_policy: normalized.robustness_policy,
    split_mode: normalized.splitMode,
    train_image_ids: normalized.trainSelectionRef ? [] : normalized.materialIds,
    ...(normalized.trainSelectionRef?{train_selection_ref:normalized.trainSelectionRef}:{}),
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
  if (normalized.splitMode === 'fixed_zip_train_val_test') {
    delete request.train_image_ids; delete request.test_image_ids; delete request.train_selection_ref;
    request.zip_source_job_ids = normalized.zipSourceJobIds;
  }
  if (normalized.resource.batch != null) request.batch = normalized.resource.batch;
  if (normalized.duplicateReview && normalized.splitMode !== 'fixed_zip_train_val_test') {
    request.duplicate_review = normalized.duplicateReview;
    request.expected_material_revision = normalized.duplicateReview.material_revision;
    request.expected_annotation_revision = normalized.duplicateReview.annotation_revision;
  }
  if (normalized.resource.workers != null) request.workers = normalized.resource.workers;
  if (normalized.resource.cache != null) request.cache = normalized.resource.cache;
  if (Object.hasOwn(request, 'cache')) request.cache = trainingCacheRequestValue(request.cache);
  return request;
}

export function trainingConfigurationDefaults() {
  return {
    model: '', epochs: 150, time: null, imgsz: 640, batch: 8,
    device: 'auto', precision: 'auto', optimizer: 'auto', patience: 40,
    early_stopping_enabled: false, workers: 0,
    lr0: .01, lrf: .01, momentum: .937, weight_decay: .0005, warmup_epochs: 3,
    close_mosaic: 10, mosaic: 1, mixup: 0, hsv_h: .015, hsv_s: .7, hsv_v: .4,
    degrees: 0, translate: .1, scale: .5, shear: 0, perspective: 0, flipud: 0, fliplr: .5,
    cache: 'False', pretrained: true, amp: true, rect: false, cos_lr: false,
    freeze: 0, multi_scale: 0, save_period: -1, seed: 0, deterministic: true,
    eval_interval: 10, eval_metric: 'map50', continue_threshold: 0, stop_threshold: .90,
    val_max_samples: 0, queue_priority: 50, auto_convert_targets: [],
  };
}
