// Bounds one existing owner's operation, including response decoding. This
// utility neither sends requests nor retries mutations.
export async function withRequestDeadline(operation, {timeoutMs = 30000, label = '请求', signal} = {}) {
  const controller = new AbortController();
  let timer, onAbort;
  const cancelled = new Promise((_, reject) => {
    onAbort = () => {
      controller.abort();
      reject(Object.assign(new Error('请求已取消'), {name: 'AbortError'}));
    };
    if (signal?.aborted) onAbort();
    else signal?.addEventListener('abort', onAbort, {once: true});
    timer = setTimeout(() => {
      reject(Object.assign(new Error(`${label}超时；提交结果可能已被服务端受理，请先查询状态。`), {code: 'REQUEST_TIMEOUT'}));
      controller.abort();
    }, timeoutMs);
  });
  try {
    return await Promise.race([cancelled, Promise.resolve().then(() => {
      if (controller.signal.aborted) throw Object.assign(new Error('请求已取消'), {name: 'AbortError'});
      return operation(controller.signal);
    })]);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener('abort', onAbort);
  }
}

export function messageFromApiError(error = {}) {
  const message = error.message || '操作失败';
  const base = error.detail && error.detail !== message
    ? `${message}：${error.detail}`
    : message;
  return error.solution ? `${base}\n建议：${error.solution}` : base;
}

