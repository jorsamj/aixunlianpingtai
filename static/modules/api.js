// Bounds one existing owner's operation, including response decoding. This
// utility neither sends requests nor retries mutations.
// Optional upload transport for the original api() owner. Response decoding,
// business errors, deadlines and mutation recovery remain with that owner.
export function fetchWithUploadProgress(url, options = {}, xhrFactory = () => new XMLHttpRequest()) {
  return new Promise((resolve, reject) => {
    const xhr = xhrFactory(), signal = options.signal;
    const cleanup = () => signal?.removeEventListener('abort', abort);
    const fail = error => {cleanup();reject(error);};
    const abort = () => {xhr.abort();fail(Object.assign(new Error('上传已取消，创建结果需要核验'), {name:'AbortError'}));};
    if (signal?.aborted) return fail(Object.assign(new Error('请求已取消'), {name:'AbortError'}));
    xhr.open(options.method || 'POST', url, true);
    xhr.withCredentials = options.credentials === 'include';
    for (const [key, value] of new Headers(options.headers || {})) xhr.setRequestHeader(key, value);
    xhr.upload.onprogress = event => options.onUploadProgress?.({loadedBytes:event.loaded,totalBytes:event.lengthComputable?event.total:null,
      loaded:event.loaded,total:event.total,lengthComputable:event.lengthComputable});
    xhr.onerror = () => fail(new TypeError('图片传输网络异常，创建结果需要核验'));
    xhr.onabort = () => fail(Object.assign(new Error('图片传输已中断'), {name:'AbortError'}));
    xhr.onload = () => {
      cleanup();
      if (!xhr.status) {reject(new TypeError('图片上传响应状态未知，请核验原请求'));return;}
      resolve(new Response(xhr.status === 204 ? null : xhr.responseText, {status:xhr.status,
        headers:{'Content-Type':xhr.getResponseHeader('Content-Type') || 'application/octet-stream'}}));
    };
    signal?.addEventListener('abort', abort, {once:true});
    try {xhr.send(options.body);} catch (error) {fail(error);}
  });
}

export async function withRequestDeadline(operation, {timeoutMs = 30000, label = '请求', signal, mutation = false} = {}) {
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
      const detail = mutation
        ? '提交结果尚未确认；服务端可能已受理，请先核验状态，勿直接重复提交。'
        : '读取未完成，请检查网络后重试。';
      reject(Object.assign(new Error(`${label}超时；${detail}`), {
        code:'REQUEST_TIMEOUT', outcome:mutation?'UNKNOWN':'READ_TIMEOUT',
      }));
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

