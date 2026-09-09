function count(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

export function buildServerImportRequest(values = {}) {
  const mode = String(values.mode || 'directory_scan');
  const storageSourceId = String(values.storageSourceId || '').trim();
  if (!storageSourceId) throw new Error('请选择本地存储源');
  const importFormat = String(values.importFormat || 'auto');
  if (!['auto', 'images', 'yolo'].includes(importFormat)) throw new Error('暂不支持 COCO/VOC 服务器导入');
  const format = {import_format: importFormat};
  if (values.datasetYaml && importFormat !== 'images') format.dataset_yaml = String(values.datasetYaml).trim();

  if (mode === 'directory_scan') {
    return {
      mode,
      ...format,
      storage_source_id: storageSourceId,
      prefix: String(values.prefix || '').trim(),
      recursive: values.recursive !== false,
    };
  }
  if (mode === 'server_zip') {
    const zipPath = String(values.zipPath || '').trim();
    const targetPrefix = String(values.targetPrefix || '').trim();
    if (!zipPath) throw new Error('请选择服务器 ZIP');
    if (!targetPrefix) throw new Error('请填写 ZIP 解压目标目录');
    return {
      mode,
      ...format,
      storage_source_id: storageSourceId,
      zip_path: zipPath,
      target_prefix: targetPrefix,
      recursive: true,
    };
  }
  throw new Error(`不支持的导入方式：${mode}`);
}

export function buildImportConfirmation(rows = [], acceptQualityReport = false) {
  const label_mapping = {}, create_labels = [];
  for (const row of rows) {
    const code = String(row.code || '').trim();
    if (!code) throw new Error(`请选择外部类别 ${row.name || row.classId} 对应的平台标签`);
    label_mapping[String(row.classId)] = code;
    if (row.create) create_labels.push(code);
  }
  return {label_mapping, create_labels: [...new Set(create_labels)], accept_quality_report: Boolean(acceptQualityReport)};
}

export function serverImportView(task = {}) {
  const status = String(task.status || 'QUEUED').toUpperCase();
  const stage = String(task.stage || '').toLowerCase();
  const metrics = task.metrics || {};
  const current = String(metrics.current_file || task.current_item || '-');
  let text;

  if (stage === 'extracting') {
    text = `已解压 ${count(metrics.extracted_files)} 个文件 · ${count(metrics.extracted_bytes)} 字节 · 当前 ${current}`;
  } else if (stage === 'scanning') {
    text = `已扫描 ${count(metrics.scanned_files)} · 可导入 ${count(metrics.importable_images)} · 重复 ${count(metrics.duplicates)} · 失败 ${count(metrics.failed) + count(metrics.invalid_images)} · 当前 ${current}`;
  } else if (stage === 'indexing' || stage === 'indexing_queued') {
    text = `正在建立索引 ${count(metrics.indexed_at_least ?? metrics.indexed)} / ${count(metrics.selected)}`;
  } else if (status === 'AWAITING_CONFIRMATION') {
    text = '扫描完成，等待确认建立素材索引';
  } else if (status === 'QUEUED') {
    text = '任务已进入 Storage Worker 队列';
  } else if (status === 'SUCCEEDED') {
    text = `导入完成，共建立 ${count(task.result?.imported)} 条素材索引`;
  } else if (status === 'FAILED' || status === 'CANCELLED') {
    text = String(task.error || task.result?.error?.message || status);
  } else {
    text = stage || status;
  }

  return {
    status,
    stage,
    text,
    active: ['QUEUED', 'RUNNING'].includes(status),
    canConfirm: status === 'AWAITING_CONFIRMATION',
    showPercent: stage === 'extracting' && count(metrics.declared_bytes) > 0,
    terminal: ['SUCCEEDED', 'PARTIAL_SUCCESS', 'FAILED', 'CANCELLED', 'BLOCKED_BY_ENVIRONMENT'].includes(status),
  };
}

function abortError(signal) {
  return signal?.reason instanceof Error
    ? signal.reason
    : new DOMException('Polling stopped', 'AbortError');
}

function waitForNextPoll(delay, signal) {
  if (signal?.aborted) return Promise.reject(abortError(signal));
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      signal?.removeEventListener('abort', onAbort);
      resolve();
    }, delay);
    const onAbort = () => {
      clearTimeout(timer);
      reject(abortError(signal));
    };
    signal?.addEventListener('abort', onAbort, {once: true});
  });
}

export async function pollServerImport({initialTask, load, render, signal, delay = 1200}) {
  if (typeof load !== 'function') throw new TypeError('load must be a function');
  let task = initialTask || await load();
  while (true) {
    if (signal?.aborted) throw abortError(signal);
    render?.(task);
    if (!serverImportView(task).active) return task;
    await waitForNextPoll(delay, signal);
    task = await load();
  }
}
