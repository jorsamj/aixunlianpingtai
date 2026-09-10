export function iterationBasePresentation(base) {
  if (base === null || base === undefined) {
    return {title: '正在读取最新版本…', detail: '', status: 'loading'};
  }
  if (base.error) {
    return {title: '读取失败', detail: String(base.error), status: 'error'};
  }
  if (base.version_name) {
    return {
      title: `从最新可训练版本继续：${base.version_name}`,
      detail: base.model_name || '模型权重',
      status: 'version'
    };
  }
  return {
    title: '首次训练：使用所选母模型',
    detail: '后续版本会自动以上一个可用版本继续训练',
    status: 'mother'
  };
}

export function projectedRandomSplit(total, experimentPercent) {
  const count = Math.max(0, Math.floor(Number(total) || 0));
  if (count < 2) return {train: count, experiment: 0};
  const percent = Math.max(1, Math.min(99, Number(experimentPercent) || 20));
  const experiment = Math.max(1, Math.min(count - 1, Math.round(count * percent / 100)));
  return {train: count - experiment, experiment};
}

function uniqueIds(values) {
  return [...new Set((values || []).map(value => String(value).trim()).filter(Boolean))];
}

function isProcessedMaterial(row) {
  return Boolean(
    row?.processing_status === 'processed'
    || row?.cleaned_at
    || row?.clean_skipped
    || row?.annotated
  );
}

export function filterTrainingMaterials(materials, {query = '', labelCodes = []} = {}) {
  const needle = String(query || '').trim().toLowerCase();
  const labels = uniqueIds(labelCodes);
  return (materials || []).filter(row => {
    if (!row?.annotated || !isProcessedMaterial(row)) return false;
    if (needle && !String(row.filename || '').toLowerCase().includes(needle)) return false;
    const rowLabels = new Set((row.labels || []).map(String));
    return !labels.length || labels.some(label => rowLabels.has(label));
  });
}

export function applyMaterialSelection(currentIds, filteredIds, eligibleIds, action) {
  const eligible = uniqueIds(eligibleIds);
  const eligibleSet = new Set(eligible);
  const selected = new Set(uniqueIds(currentIds).filter(id => eligibleSet.has(id)));
  const filtered = uniqueIds(filteredIds).filter(id => eligibleSet.has(id));
  if (action === 'select-filtered') filtered.forEach(id => selected.add(id));
  else if (action === 'invert-filtered') filtered.forEach(id => selected.has(id) ? selected.delete(id) : selected.add(id));
  else if (action === 'select-all') eligible.forEach(id => selected.add(id));
  else if (action === 'clear-all') selected.clear();
  else throw new Error('不支持的素材批量选择操作');
  return eligible.filter(id => selected.has(id));
}

export function buildTrainingPayload({
  splitMode,
  trainImageIds,
  testImageIds = [],
  trainingLabelIds = [],
  experimentPercent = null,
  validationPercent = 20,
  parameters = {},
}) {
  const mode = String(splitMode || 'random_test_from_training_pool');
  if (!['independent_test_set', 'random_test_from_training_pool'].includes(mode)) {
    throw new Error('不支持的试验集方式');
  }
  const train = uniqueIds(trainImageIds);
  if (!train.length) throw new Error('请选择训练素材');
  const labels = uniqueIds(trainingLabelIds);
  if (!labels.length) throw new Error('请至少选择一个本次训练标签');
  const validation = Number(validationPercent);
  if (!(validation > 0 && validation < 100)) throw new Error('验证集比例必须在 0 到 100 之间');
  const independent = mode === 'independent_test_set' ? uniqueIds(testImageIds) : [];
  if (mode === 'independent_test_set' && !independent.length) throw new Error('请选择独立试验素材');
  if (independent.some(id => train.includes(id))) throw new Error('训练素材与试验素材不能重复');
  const randomPercent = mode === 'random_test_from_training_pool' ? Number(experimentPercent) : null;
  if (mode === 'random_test_from_training_pool' && !(randomPercent > 0 && randomPercent < 100)) {
    throw new Error('试验集比例必须在 0 到 100 之间');
  }
  const payload = {...parameters};
  delete payload.selected_image_ids;
  delete payload.val_image_ids;
  delete payload.test_image_ids;
  delete payload.train_dataset_ids;
  delete payload.test_dataset_ids;
  return {
    ...payload,
    split_mode: mode,
    train_image_ids: train,
    test_image_ids: independent,
    training_label_ids: labels,
    experiment_percent: randomPercent,
    validation_percent: validation,
  };
}
