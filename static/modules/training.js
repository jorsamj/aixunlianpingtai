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
