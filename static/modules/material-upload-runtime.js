export const DEFAULT_UPLOAD_CHUNK_SIZE = 64;
export const DEFAULT_UPLOAD_CHUNK_BYTES = 128 * 1024 * 1024;

function positiveInteger(value, fallback) {
  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.floor(parsed) : fallback;
}

function fileSize(file) {
  const size = Number(file?.size ?? 0);
  return Number.isFinite(size) && size > 0 ? size : 0;
}

export function partitionMaterialFiles(files, {
  maxFiles = DEFAULT_UPLOAD_CHUNK_SIZE,
  maxBytes = DEFAULT_UPLOAD_CHUNK_BYTES,
} = {}) {
  const rows = Array.from(files || []);
  const fileLimit = positiveInteger(maxFiles, DEFAULT_UPLOAD_CHUNK_SIZE);
  const byteLimit = positiveInteger(maxBytes, DEFAULT_UPLOAD_CHUNK_BYTES);
  const chunks = [];
  let current = [];
  let currentBytes = 0;

  for (const file of rows) {
    const size = fileSize(file);
    const wouldOverflowFiles = current.length >= fileLimit;
    const wouldOverflowBytes = current.length > 0 && currentBytes + size > byteLimit;
    if (wouldOverflowFiles || wouldOverflowBytes) {
      chunks.push(current);
      current = [];
      currentBytes = 0;
    }
    current.push(file);
    currentBytes += size;
  }
  if (current.length) chunks.push(current);
  return chunks;
}

function responseRows(response, key) {
  return Array.isArray(response?.[key]) ? response[key] : [];
}

export class MaterialUploadContractError extends Error {
  constructor(message, details = {}) {
    super(message);
    this.name = 'MaterialUploadContractError';
    this.details = details;
  }
}

export class MaterialUploadInterruptedError extends Error {
  constructor(message, details = {}) {
    super(message);
    this.name = 'MaterialUploadInterruptedError';
    this.details = details;
  }
}

export async function uploadMaterialFilesSequentially(files, {
  requestChunk,
  onEvent = () => {},
  maxFiles = DEFAULT_UPLOAD_CHUNK_SIZE,
  maxBytes = DEFAULT_UPLOAD_CHUNK_BYTES,
} = {}) {
  if (typeof requestChunk !== 'function') {
    throw new TypeError('requestChunk is required');
  }
  const allFiles = Array.from(files || []);
  const chunks = partitionMaterialFiles(allFiles, {maxFiles, maxBytes});
  const aggregate = {
    totalFiles: allFiles.length,
    confirmedFiles: 0,
    uploaded: [],
    failed: [],
    batchIds: [],
    chunks: chunks.length,
  };
  let activeRequests = 0;

  for (let index = 0; index < chunks.length; index += 1) {
    const chunk = chunks[index];
    const base = {
      chunkIndex: index,
      chunkNumber: index + 1,
      chunkCount: chunks.length,
      chunkSize: chunk.length,
      totalFiles: allFiles.length,
      confirmedFiles: aggregate.confirmedFiles,
      uploadedCount: aggregate.uploaded.length,
      failedCount: aggregate.failed.length,
    };
    onEvent({type: 'chunk-start', ...base});
    activeRequests += 1;
    if (activeRequests !== 1) {
      throw new MaterialUploadContractError('material upload chunks must stay sequential');
    }
    let response;
    try {
      response = await requestChunk(chunk, {
        ...base,
        onTransfer: progress => onEvent({type: 'transfer', ...base, ...progress}),
      });
    } catch (error) {
      activeRequests -= 1;
      throw new MaterialUploadInterruptedError(
        error?.message || '上传中断',
        {
          cause: error,
          chunkIndex: index,
          chunkNumber: index + 1,
          chunkCount: chunks.length,
          chunkSize: chunk.length,
          totalFiles: allFiles.length,
          confirmedFiles: aggregate.confirmedFiles,
          uploaded: [...aggregate.uploaded],
          failed: [...aggregate.failed],
        },
      );
    }
    activeRequests -= 1;

    const uploaded = responseRows(response, 'uploaded');
    const failed = responseRows(response, 'failed');
    const accounted = uploaded.length + failed.length;
    if (accounted !== chunk.length) {
      throw new MaterialUploadContractError(
        `服务器返回的本批处理数量不完整：${accounted}/${chunk.length}`,
        {chunkIndex: index, response, expected: chunk.length, accounted},
      );
    }
    aggregate.uploaded.push(...uploaded);
    aggregate.failed.push(...failed);
    if (response?.batch_id) aggregate.batchIds.push(String(response.batch_id));
    aggregate.confirmedFiles += accounted;
    onEvent({
      type: 'chunk-committed',
      ...base,
      confirmedFiles: aggregate.confirmedFiles,
      uploadedCount: aggregate.uploaded.length,
      failedCount: aggregate.failed.length,
      response,
    });
  }

  onEvent({
    type: 'complete',
    totalFiles: allFiles.length,
    confirmedFiles: aggregate.confirmedFiles,
    uploadedCount: aggregate.uploaded.length,
    failedCount: aggregate.failed.length,
    chunkCount: chunks.length,
  });
  return aggregate;
}

function escapeHtml(value) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[char]));
}

function formatBytes(value) {
  const bytes = Math.max(0, Number(value) || 0);
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(bytes < 10 * 1024 ? 1 : 0)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

export function requestMaterialChunkXHR(files, {
  projectId,
  datasetId = 'default',
  storageSourceId = 'default_local',
  onTransfer = () => {},
  xhrFactory = () => new XMLHttpRequest(),
} = {}) {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const file of files || []) form.append('files', file);
    form.append('dataset_id', datasetId || 'default');
    form.append('storage_source_id', storageSourceId || 'default_local');
    const xhr = xhrFactory();
    xhr.open('POST', `/api/projects/${encodeURIComponent(String(projectId || ''))}/images`, true);
    xhr.upload.onprogress = event => {
      if (!event.lengthComputable) return;
      onTransfer({loadedBytes: event.loaded, totalBytes: event.total, ratio: event.total ? event.loaded / event.total : 0});
    };
    xhr.onerror = () => reject(new Error('网络连接异常，当前批次结果未确认'));
    xhr.onabort = () => reject(new Error('上传已取消，当前批次结果未确认'));
    xhr.onload = () => {
      let body = {};
      try { body = JSON.parse(xhr.responseText || '{}'); } catch (_) {}
      if (xhr.status < 200 || xhr.status >= 300) {
        const detail = body?.error?.detail || body?.detail || xhr.responseText || `HTTP ${xhr.status}`;
        reject(new Error(String(detail)));
        return;
      }
      resolve(body);
    };
    xhr.send(form);
  });
}

export function installMaterialUploadRuntime({
  getState = () => ({}),
  projectId = () => getState()?.project?.id,
  notify = message => globalThis.window?.toast?.(message),
  maxFiles = DEFAULT_UPLOAD_CHUNK_SIZE,
  maxBytes = DEFAULT_UPLOAD_CHUNK_BYTES,
} = {}) {
  if (typeof window === 'undefined' || typeof document === 'undefined') return null;

  const setText = (id, text) => {
    const node = document.getElementById(id);
    if (node) node.textContent = text;
  };
  const setWidth = (id, percent) => {
    const node = document.getElementById(id);
    if (node) node.style.width = `${Math.max(0, Math.min(100, percent))}%`;
  };
  const renderShell = (total, chunkCount) => {
    window.closeModal?.();
    const body = `<div class="up411">
      <section><b>正在上传图片</b><span>${total} 个文件 · ${chunkCount} 批</span></section>
      <div class="up411-bar"><i id="up411Bar" style="width:0%"></i></div>
      <div class="up411-line"><span id="up411Text">准备上传</span><b id="up411Pct">0%</b></div>
      <div class="item-sub" id="up411ServerText">服务器已处理 0 / ${total} · 成功入库 0 · 失败 0</div>
      <div class="item-sub" id="up411TransferText">当前批次尚未开始传输</div>
      <div id="up411Result"></div>
    </div>`;
    if (typeof window.modal === 'function') window.modal('图片上传', body, true);
  };
  const patchState = uploaded => {
    const state = getState() || {};
    const uploadedIds = new Set(uploaded.map(item => String(item?.id)));
    const recent = new Map((state.recentUploadedMaterials61 || []).map(item => [String(item?.id), item]));
    for (const item of uploaded) recent.set(String(item?.id), item);
    state.recentUploadedMaterials61 = [...recent.values()];
    state.images = [...uploaded, ...(state.images || []).filter(item => !uploadedIds.has(String(item?.id)))];
  };
  const renderResult = (aggregate, elapsedSeconds) => {
    const out = document.getElementById('up411Result');
    if (!out) return;
    const uploaded = aggregate.uploaded || [];
    const failed = aggregate.failed || [];
    const failedHtml = failed.map(item => `<div class="alert warn">${escapeHtml(item?.name || '文件')}：${escapeHtml(item?.reason || '处理失败')}</div>`).join('');
    const ids = uploaded.map(row => String(row?.id || '')).filter(Boolean);
    const idsJson = JSON.stringify(ids).replace(/'/g, '&#39;');
    const decision = ids.length ? `<div class="upload414-decision"><div><b>本次上传 ${ids.length} 张素材</b><span>可以继续批量清洗或标记无需清洗。</span></div><div class="row"><button class="btn" onclick='closeModal();openBatch414("ready",${idsJson})'>批量无需清洗</button><button class="btn primary" onclick='closeModal();openBatch414("clean",${idsJson})'>批量清洗</button></div></div>` : '';
    out.innerHTML = `<div class="alert ok">成功上传 ${uploaded.length} 张${failed.length ? `，失败 ${failed.length} 张` : ''} · 服务器已处理 ${aggregate.confirmedFiles}/${aggregate.totalFiles} · ${elapsedSeconds.toFixed(1)} 秒</div>${failedHtml}${decision}`;
  };

  async function uploadFiles(files, {storageSourceId = 'default_local', datasetId = 'default', input = null} = {}) {
    const rows = Array.from(files || []);
    if (!rows.length) return null;
    const pid = projectId();
    if (!pid) {
      notify?.('当前项目未加载，请刷新后重试');
      return null;
    }
    const chunks = partitionMaterialFiles(rows, {maxFiles, maxBytes});
    renderShell(rows.length, chunks.length);
    const started = performance.now();
    const state = getState() || {};
    state.recentUploadedMaterials61 = [];
    try {
      const aggregate = await uploadMaterialFilesSequentially(rows, {
        maxFiles,
        maxBytes,
        requestChunk: (chunk, context) => requestMaterialChunkXHR(chunk, {
          projectId: pid,
          datasetId,
          storageSourceId,
          onTransfer: context.onTransfer,
        }),
        onEvent: event => {
          if (event.type === 'chunk-start') {
            setText('up411Text', `正在上传第 ${event.chunkNumber}/${event.chunkCount} 批`);
            setText('up411TransferText', `当前批次 ${event.chunkSize} 张 · 等待传输`);
          } else if (event.type === 'transfer') {
            const percent = Math.round((event.ratio || 0) * 100);
            setText('up411TransferText', `当前批次传输 ${percent}% · ${formatBytes(event.loadedBytes)} / ${formatBytes(event.totalBytes)}`);
          } else if (event.type === 'chunk-committed') {
            patchState(responseRows(event.response, 'uploaded'));
            const percent = event.totalFiles ? Math.round(event.confirmedFiles / event.totalFiles * 100) : 100;
            setWidth('up411Bar', percent);
            setText('up411Pct', `${percent}%`);
            setText('up411Text', `第 ${event.chunkNumber}/${event.chunkCount} 批服务器处理完成`);
            setText('up411ServerText', `服务器已处理 ${event.confirmedFiles} / ${event.totalFiles} · 成功入库 ${event.uploadedCount} · 失败 ${event.failedCount}`);
          }
        },
      });
      renderResult(aggregate, (performance.now() - started) / 1000);
      if (getState()?.page === '数据集') {
        if (typeof window.reloadMaterialPage61 === 'function') await window.reloadMaterialPage61();
        else window.renderDatasets424?.();
      }
      return aggregate;
    } catch (error) {
      const details = error?.details || {};
      const confirmed = Number(details.confirmedFiles || 0);
      const total = rows.length;
      const out = document.getElementById('up411Result');
      if (out) out.innerHTML = `<div class="alert err">上传中断：${escapeHtml(error?.message || error)}。服务器已确认处理 ${confirmed}/${total}。为避免网络响应丢失后重复入库，系统不会自动重试当前未确认批次。</div>`;
      setText('up411Text', '上传中断');
      throw error;
    } finally {
      if (input) input.value = '';
    }
  }

  const runtime = {uploadFiles, partitionMaterialFiles};
  window.MaterialUploadRuntime = runtime;
  window.doUploadImages426 = input => {
    const files = Array.from(input?.files || []);
    const storageSourceId = document.getElementById('uploadStorage61')?.value || 'default_local';
    uploadFiles(files, {storageSourceId, datasetId: 'default', input}).catch(error => notify?.(error?.message || error));
  };
  window.uploadData424 = () => {
    const input = document.getElementById('data424Upload');
    const files = Array.from(input?.files || []);
    if (!files.length) return notify?.('请选择图片');
    uploadFiles(files, {datasetId: 'default', input}).catch(error => notify?.(error?.message || error));
  };
  return runtime;
}
