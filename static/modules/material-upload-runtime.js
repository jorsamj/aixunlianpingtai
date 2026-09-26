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
  const setProgress = (id, percent) => {
    const node = document.getElementById(id);
    if (!node) return;
    const value = Math.max(0, Math.min(100, Number(percent) || 0));
    node.dataset.progress = value.toFixed(2);
    node.style.transform = `scaleX(${(value / 100).toFixed(4)})`;
  };
  const renderShell = (total, chunkCount) => {
    window.closeModal?.();
    const body = `<div class="up411">
      <section><b>正在上传图片</b><span>${total} 个文件 · ${chunkCount} 批</span></section>
      <div class="up411-bar"><i id="up411Bar" data-progress="0.00" style="transform:scaleX(0)"></i></div>
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
    const pagedDataset = state.page === '数据集' && window.__materialPaging61?.mode === 'paged';
    if (!pagedDataset) {
      state.images = [...uploaded, ...(state.images || []).filter(item => !uploadedIds.has(String(item?.id)))];
    }
  };
  const renderResult = (aggregate, elapsedSeconds) => {
    const out = document.getElementById('up411Result');
    if (!out) return;
    const uploaded = aggregate.uploaded || [];
    const failed = aggregate.failed || [];
    const shownFailed = failed.slice(0, 100);
    const failedHtml = shownFailed.map(item => `<div class="alert warn">${escapeHtml(item?.name || '文件')}：${escapeHtml(item?.reason || '处理失败')}</div>`).join('');
    const failedOverflow = failed.length > shownFailed.length
      ? `<div class="alert warn">另有 ${failed.length - shownFailed.length} 条失败记录未在弹窗中展开，可在任务记录中查看。</div>`
      : '';
    const decision = uploaded.length ? `<div class="upload414-decision"><div><b>本次上传 ${uploaded.length} 张素材</b><span>可以继续批量清洗或标记无需清洗；大批量素材会分页展示。</span></div><div class="row"><button class="btn" onclick='closeModal();openRecentUploadBatch414("ready")'>批量无需清洗</button><button class="btn primary" onclick='closeModal();openRecentUploadBatch414("clean")'>批量清洗</button></div></div>` : '';
    out.innerHTML = `<div class="alert ok">成功上传 ${uploaded.length} 张${failed.length ? `，失败 ${failed.length} 张` : ''} · 服务器已处理 ${aggregate.confirmedFiles}/${aggregate.totalFiles} · ${elapsedSeconds.toFixed(1)} 秒</div>${failedHtml}${failedOverflow}${decision}`;
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
    const uploadTaskId = `images:${Date.now()}:${Math.random().toString(16).slice(2,8)}`;
    const chunkBytes = chunks.map(chunk => chunk.reduce((sum,file)=>sum+fileSize(file),0));
    const totalBytes = Math.max(1, chunkBytes.reduce((sum,value)=>sum+value,0));
    const bytesBefore = chunkBytes.map((_,index)=>chunkBytes.slice(0,index).reduce((sum,value)=>sum+value,0));
    window.UploadTaskCenterRuntime?.upsert?.({id:uploadTaskId,kind:'browser-upload',title:`图片上传 · ${rows.length} 张`,status:'UPLOADING',progress:0,stage:'准备上传',detail:`${chunks.length} 个批次`});
    renderShell(rows.length, chunks.length);
    const started = performance.now();
    const state = getState() || {};
    state.recentUploadedMaterials61 = [];
    let transferFrame = 0;
    let pendingTransfer = null;
    let lastTaskCenterProgressAt = 0;

    const cancelTransferFrame = () => {
      if (transferFrame && typeof window.cancelAnimationFrame === 'function') {
        window.cancelAnimationFrame(transferFrame);
      }
      transferFrame = 0;
      pendingTransfer = null;
    };

    const paintTransfer = (payload, timestamp = performance.now()) => {
      if (!payload) return;
      const {event, overallBytes, overallPercent} = payload;
      const chunkPercent = Math.round((event.ratio || 0) * 100);
      setProgress('up411Bar', overallPercent);
      setText('up411Pct', `${Math.round(overallPercent)}%`);
      const transferComplete = Number(event.ratio || 0) >= 1;
      setText('up411TransferText', transferComplete
        ? `当前批次已上传，等待服务器入库 · ${formatBytes(event.loadedBytes)} / ${formatBytes(event.totalBytes)}`
        : `当前批次传输 ${chunkPercent}% · ${formatBytes(event.loadedBytes)} / ${formatBytes(event.totalBytes)}`);
      if (timestamp - lastTaskCenterProgressAt >= 150 || transferComplete) {
        lastTaskCenterProgressAt = timestamp;
        window.UploadTaskCenterRuntime?.upsert?.({
          id:uploadTaskId,
          status:'UPLOADING',
          progress:overallPercent,
          stage:transferComplete ? `第 ${event.chunkNumber}/${event.chunkCount} 批已上传，等待服务器入库` : `上传第 ${event.chunkNumber}/${event.chunkCount} 批`,
          detail:`${formatBytes(overallBytes)} / ${formatBytes(totalBytes)}`,
        });
      }
    };

    const scheduleTransferPaint = payload => {
      pendingTransfer = payload;
      if (transferFrame) return;
      if (typeof window.requestAnimationFrame !== 'function') {
        const latest = pendingTransfer;
        pendingTransfer = null;
        paintTransfer(latest);
        return;
      }
      transferFrame = window.requestAnimationFrame(timestamp => {
        transferFrame = 0;
        const latest = pendingTransfer;
        pendingTransfer = null;
        paintTransfer(latest, timestamp);
      });
    };

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
            const overallBytes = bytesBefore[event.chunkIndex] + chunkBytes[event.chunkIndex] * (event.ratio || 0);
            scheduleTransferPaint({
              event,
              overallBytes,
              overallPercent: Math.min(99, overallBytes / totalBytes * 100),
            });
          } else if (event.type === 'chunk-committed') {
            cancelTransferFrame();
            patchState(responseRows(event.response, 'uploaded'));
            const committedBytes = bytesBefore[event.chunkIndex] + chunkBytes[event.chunkIndex];
            const percent = committedBytes / totalBytes * 100;
            setProgress('up411Bar', percent);
            setText('up411Pct', `${Math.round(percent)}%`);
            setText('up411Text', `第 ${event.chunkNumber}/${event.chunkCount} 批服务器处理完成`);
            setText('up411ServerText', `服务器已处理 ${event.confirmedFiles} / ${event.totalFiles} · 成功入库 ${event.uploadedCount} · 失败 ${event.failedCount}`);
            window.UploadTaskCenterRuntime?.upsert?.({
              id:uploadTaskId,
              status:'UPLOADING',
              progress:percent,
              stage:`第 ${event.chunkNumber}/${event.chunkCount} 批服务器处理完成`,
              detail:`已确认 ${event.confirmedFiles}/${event.totalFiles}`,
            });
          }
        },
      });
      cancelTransferFrame();
      setProgress('up411Bar', 100);
      setText('up411Pct', '100%');
      window.UploadTaskCenterRuntime?.upsert?.({id:uploadTaskId,status:'SUCCEEDED',progress:100,stage:'上传完成',detail:`成功 ${aggregate.uploaded.length} · 失败 ${aggregate.failed.length}`});
      renderResult(aggregate, (performance.now() - started) / 1000);
      if (getState()?.page === '数据集') {
        if (typeof window.reloadMaterialPage61 === 'function') await window.reloadMaterialPage61();
        else window.renderDatasets424?.();
      }
      return aggregate;
    } catch (error) {
      cancelTransferFrame();
      const details = error?.details || {};
      const confirmed = Number(details.confirmedFiles || 0);
      const total = rows.length;
      const out = document.getElementById('up411Result');
      if (out) out.innerHTML = `<div class="alert err">上传中断：${escapeHtml(error?.message || error)}。服务器已确认处理 ${confirmed}/${total}。为避免网络响应丢失后重复入库，系统不会自动重试当前未确认批次。</div>`;
      window.UploadTaskCenterRuntime?.upsert?.({id:uploadTaskId,status:'FAILED',stage:'上传中断',detail:String(error?.message||error)});
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
