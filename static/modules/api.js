export function messageFromApiError(error = {}) {
  const message = error.message || '操作失败';
  const base = error.detail && error.detail !== message
    ? `${message}：${error.detail}`
    : message;
  return error.solution ? `${base}\n建议：${error.solution}` : base;
}

