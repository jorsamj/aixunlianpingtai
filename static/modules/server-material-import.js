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
  const class_actions = {};
  for (const row of rows) {
    const classId = String(row.classId);
    const action = String(row.action || 'map');
    if (action === 'ignore') class_actions[classId] = {action};
    else if (action === 'map') {
      const target_label_id = String(row.targetLabelId || '').trim();
      if (!target_label_id) throw new Error(`请选择外部类别 ${row.name || classId} 对应的平台标签`);
      class_actions[classId] = {action, target_label_id};
    } else if (action === 'create') {
      const code = String(row.code || '').trim();
      const display_name = String(row.displayName || '').trim();
      if (!/^[A-Za-z][A-Za-z0-9_-]{0,63}$/.test(code) || !display_name) {
        throw new Error(`外部类别 ${row.name || classId} 的新标签需要英文 code 和显示名称`);
      }
      class_actions[classId] = {action, code, display_name};
    } else if (action === 'preserve') class_actions[classId] = {action};
    else throw new Error(`外部类别 ${row.name || classId} 的处理方式无效`);
  }
  return {class_actions, accept_quality_report: Boolean(acceptQualityReport)};
}

export function externalClassMappingHtml(classes = [], labels = [], escape = value => String(value)) {
  return classes.map(row => {
    const classId = escape(row.class_id), name = escape(row.name);
    const options = labels.map(label => `<option value="${escape(label.label_id)}" ${label.label_id === row.suggested_target_label_id ? 'selected' : ''}>${escape(label.code)} · ${escape(label.display_name || label.code)}</option>`).join('');
    return `<div class="storage61-mapping-row" data-import-class="${classId}" data-import-name="${name}"><div><b>${classId} · ${name}</b><small>${Number(row.image_count || 0)} 图 · ${Number(row.box_count || 0)} 框</small></div><select class="select" data-class-action><option value="map">映射现有标签</option><option value="create">创建新标签</option><option value="preserve">保留原名创建</option><option value="ignore">忽略</option></select><select class="select" data-target-label><option value="">请选择平台标签</option>${options}</select><input class="input" data-new-code placeholder="英文 code" hidden><input class="input" data-new-display placeholder="显示名称" hidden><button type="button" class="btn mini" data-sample-class="${classId}">查看样例</button></div>`;
  }).join('');
}

export function sampleGalleryHtml(items = [], escape = value => String(value)) {
  return items.map(item => {
    const width = Number(item.width || 1), height = Number(item.height || 1);
    const boxes = (item.boxes || []).map(box => `<rect x="${(Number(box.cx)-Number(box.w)/2)*width}" y="${(Number(box.cy)-Number(box.h)/2)*height}" width="${Number(box.w)*width}" height="${Number(box.h)*height}" fill="none" stroke="#ef4444" stroke-width="${Math.max(1, width/300)}"/>`).join('');
    return `<figure class="storage61-import-sample"><div style="position:relative"><img src="${escape(item.preview_url)}" alt="${escape(item.filename)}"><svg viewBox="0 0 ${width} ${height}" style="position:absolute;inset:0;width:100%;height:100%">${boxes}</svg></div><figcaption>${escape(item.filename)}</figcaption></figure>`;
  }).join('') || '<div class="empty">该类别暂无可用样例</div>';
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
