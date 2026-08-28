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
