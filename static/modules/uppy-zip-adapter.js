// Uppy owns this view only. ZipImportRuntime owns all transport and task state.
import {withRequestDeadline} from './api.js';
const styles = new WeakMap();

async function loadLocalUppy(target) {
  const doc = target.ownerDocument || globalThis.document;
  if (!styles.has(doc)) {
    const loading = new Promise((resolve, reject) => {
      const link = doc.createElement('link');
      link.rel = 'stylesheet';
      link.href = '/static/vendor/uppy/uppy.min.css';
      link.onload = resolve;
      link.onerror = () => { link.remove(); styles.delete(doc); reject(new Error('ZIP上传界面样式加载失败')); };
      doc.head.appendChild(link);
    });
    styles.set(doc, loading);
  }
  const [uppy, locale] = await Promise.all([
    import('/static/vendor/uppy/uppy.min.mjs'),
    import('/static/vendor/uppy/zh_CN.mjs'),
    styles.get(doc),
  ]);
  return {...uppy, zhCN: locale.default};
}

export async function mountUppyZipAdapter({target, runtime, projectId, loadUppy = loadLocalUppy, loadTimeoutMs = 30000, onFallback = () => {}, notify = () => {}}) {
  let uppy = null, destroyed = false, unsubscribe = () => {}, hostObserver = null;
  const records = new Map(), byFile = new Map(), listeners = [];
  const current = () => !destroyed && target?.isConnected !== false && !target?.closest?.('.modal')?.classList?.contains('hidden') && String(runtime.getProjectId()) === String(projectId);
  const listen = (name, fn) => { uppy.on(name, fn); listeners.push([name, fn]); };
  const settle = record => { record.resolve?.(); record.resolve = null; };
  const destroy = () => {
    if (destroyed) return;
    destroyed = true;
    hostObserver?.disconnect();
    unsubscribe();
    for (const [name, fn] of listeners) uppy.off(name, fn);
    listeners.length = 0;
    if (uppy) uppy.removeUploader(upload);
    for (const record of records.values()) settle(record);
    records.clear(); byFile.clear();
    // Official destroy emits cancel-all. Our owner delegates are already removed.
    uppy?.destroy();
  };
  function fail(record, error) {
    if (!current() || record.complete || !uppy.getFile(record.id)) return;
    record.running = false;
    record.failed = true;
    record.pauseInFlight = false;
    record.processing = false;
    uppy.emit('upload-error', uppy.getFile(record.id), error instanceof Error ? error : new Error(String(error || 'ZIP上传失败')));
    settle(record);
  }
  function operation(record, fn) {
    try { Promise.resolve(fn()).catch(error => fail(record, error)); }
    catch (error) { fail(record, error); }
  }
  function resume(record) {
    if (!current()) return;
    record.desiredPaused = false;
    if (!record.uploadId || record.running || record.complete) return;
    record.running = true;
    record.failed = false;
    uppy.setFileState(record.id, {isPaused: false, error: null});
    operation(record, () => runtime.resumeTransfer(record.file, record.uploadId));
  }
  function pause(record) {
    if (!current() || record.complete) return;
    if (record.processing) {
      record.desiredPaused = false;
      uppy.setFileState(record.id, {isPaused: false});
      notify('上传字节已交付，服务端正在合并校验；后台任务状态请查看任务中心。');
      return;
    }
    record.desiredPaused = true;
    if (!record.uploadId || !record.running || record.pauseInFlight) return;
    record.pauseInFlight = true;
    operation(record, () => runtime.pauseUpload(record.uploadId));
  }
  function observe(event) {
    if (!current() || String(event.projectId) !== String(projectId)) return;
    const record = byFile.get(event.file);
    if (!record || !uppy.getFile(record.id)) return;
    if (event.transferId) record.transferId = event.transferId;
    if (event.uploadId) record.uploadId = event.uploadId;
    if (event.jobId) record.jobId = event.jobId;
    const file = uppy.getFile(record.id);
    switch (event.type) {
      case 'session':
        record.running = true; record.pauseInFlight = false; record.processing = false;
        uppy.setFileState(record.id, {isPaused: false});
        if (record.desiredPaused) pause(record);
        break;
      case 'progress':
        if (record.complete) break;
        // Core ignores progress after a 100% percentage, even before handoff.
        // A failed optimistic XHR must still roll back to the owner's real bytes.
        if (!file.progress.uploadComplete && file.progress.percentage === 100 && event.loaded < event.total) {
          uppy.setFileState(record.id, {progress: {...file.progress, bytesUploaded: event.loaded, bytesTotal: event.total, percentage: Math.round(event.loaded / event.total * 100)}});
        }
        uppy.emit('upload-progress', file, {uploader: runtime, bytesUploaded: event.loaded, bytesTotal: event.total});
        break;
      case 'processing':
        if (record.complete) break;
        record.processing = true; record.desiredPaused = false; record.pauseInFlight = false;
        uppy.setFileState(record.id, {isPaused: false});
        break;
      case 'paused': {
        const resumeRequested = record.pauseInFlight && record.desiredPaused === false;
        record.running = false; record.pauseInFlight = false;
        uppy.setFileState(record.id, {isPaused: true});
        if (resumeRequested) resume(record);
        break;
      }
      case 'error': fail(record, event.error || event.message); break;
      case 'cancelled': fail(record, new Error('上传已取消；任务状态请查看任务中心')); break;
      case 'success':
        if (record.complete) break;
        record.running = false; record.complete = true;
        uppy.emit('upload-success', file, {status: 200, body: event.response});
        settle(record);
        break;
    }
  }
  function upload(ids) {
    if (!current()) return Promise.resolve();
    const fresh = [], pending = [], restarting = [], starting = [];
    for (const id of ids) {
      const file = uppy.getFile(id);
      if (!file) continue;
      let record = records.get(id);
      if (!record) {
        record = {id, file: file.data, running: false, complete: false};
        records.set(id, record); byFile.set(file.data, record);
      }
      if (record.complete) continue;
      if (!record.resolve) record.waiting = new Promise(resolve => { record.resolve = resolve; });
      pending.push(record.waiting);
      if (record.running) continue;
      starting.push(file);
      if (record.uploadId) restarting.push(record);
      else { record.running = true; fresh.push(record); }
    }
    if (starting.length) uppy.emit('upload-start', starting);
    if (fresh.length) {
      try {
        Promise.resolve(runtime.uploadBatch({files: fresh.map(record => record.file), value: '', closest: () => null, externalView: true}))
          .catch(error => { for (const record of fresh) if (record.resolve) fail(record, error); });
      } catch (error) { for (const record of fresh) fail(record, error); }
    }
    for (const record of restarting) resume(record);
    return Promise.all(pending).then(() => undefined);
  }
  try {
    const doc = target?.ownerDocument;
    const Observer = doc?.defaultView?.MutationObserver || globalThis.MutationObserver;
    if (Observer && doc?.body) {
      hostObserver = new Observer(() => { if (!current()) destroy(); });
      hostObserver.observe(doc.body, {childList: true, subtree: true, attributes: true, attributeFilter: ['class']});
    }
    const {Uppy, Dashboard, zhCN} = await withRequestDeadline(()=>loadUppy(target),{timeoutMs:loadTimeoutMs,label:'ZIP上传界面加载'});
    if (!current()) { destroy(); return {uppy: null, destroy}; }
    const locale = {...zhCN, strings: {...zhCN?.strings,
      complete: '上传已交付；后台导入请查看任务中心',
      uploadComplete: '上传已交付；后台导入请查看任务中心',
      xFilesUploaded: {0: '%{smart_count}个文件已上传，后台导入请查看任务中心'},
    }};
    uppy = new Uppy({autoProceed: false, allowMultipleUploadBatches: true, restrictions: {allowedFileTypes: ['.zip']}, locale});
    uppy.setState({capabilities: {...uppy.getState().capabilities, resumableUploads: true, individualCancellation: false, uploadProgress: true}});
    target.querySelector?.('.loading')?.remove();
    uppy.use(Dashboard, {inline: true, target, width: '100%', height: 390, proudlyDisplayPoweredByUppy: false, hideCancelButton: true, showRemoveButtonAfterComplete: false,
      note: 'ZIP上传完成后仍需后台校验、标签确认与导入。取消任务请使用原任务中心；关闭此窗口后上传继续。', locale});
    uppy.addUploader(upload);
    unsubscribe = runtime.subscribeTransfers(observe);
    listen('upload-pause', (file, isPaused) => { const record = records.get(file.id); if (record) (isPaused ? pause : resume)(record); });
    listen('pause-all', () => { for (const record of records.values()) pause(record); });
    listen('resume-all', () => { for (const record of records.values()) resume(record); });
    listen('file-removed', file => {
      if (!current()) return;
      const record = records.get(file.id);
      if (!record) return;
      if (!record.complete) {
        if (record.uploadId) operation(record, () => runtime.cancelJob(record.uploadId));
        else if (record.transferId) operation(record, () => runtime.cancelQueuedUpload(record.transferId));
      }
      settle(record); records.delete(file.id); byFile.delete(record.file);
    });
    return {uppy, destroy};
  } catch (error) {
    const shouldFallback = current();
    destroy();
    if (shouldFallback) { notify('ZIP上传界面加载失败，已返回原上传界面'); onFallback(error); }
    return {uppy: null, destroy};
  }
}
