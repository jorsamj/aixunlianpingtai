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

export function buildTrainingPayload({
  splitMode,
  trainDatasetIds,
  testDatasetIds = [],
  experimentPercent = null,
  validationPercent = 20,
  parameters = {},
}) {
  const mode = String(splitMode || 'random_test_from_training_pool');
  if (!['independent_test_set', 'random_test_from_training_pool'].includes(mode)) {
    throw new Error('不支持的试验集方式');
  }
  const train = uniqueIds(trainDatasetIds);
  if (!train.length) throw new Error('请选择训练数据集');
  const validation = Number(validationPercent);
  if (!(validation > 0 && validation < 100)) throw new Error('验证集比例必须在 0 到 100 之间');
  const independent = mode === 'independent_test_set' ? uniqueIds(testDatasetIds) : [];
  if (mode === 'independent_test_set' && !independent.length) throw new Error('请选择独立试验数据集');
  if (independent.some(id => train.includes(id))) throw new Error('训练数据集与试验数据集不能重复');
  const randomPercent = mode === 'random_test_from_training_pool' ? Number(experimentPercent) : null;
  if (mode === 'random_test_from_training_pool' && !(randomPercent > 0 && randomPercent < 100)) {
    throw new Error('试验集比例必须在 0 到 100 之间');
  }
  const payload = {...parameters};
  delete payload.selected_image_ids;
  delete payload.train_image_ids;
  delete payload.val_image_ids;
  return {
    ...payload,
    split_mode: mode,
    train_dataset_ids: train,
    test_dataset_ids: independent,
    experiment_percent: randomPercent,
    validation_percent: validation,
  };
}
