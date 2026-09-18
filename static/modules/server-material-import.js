import {
  canonicalTaskPhase,
  canonicalTaskStatus,
  exactTaskQueuePosition,
  isCanonicalTaskActive,
  isCanonicalTaskTerminal,
} from './task-runtime-truth.js';

function count(value) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : 0;
}

export function buildServerImportRequest(values = {}) {
  const mode = String(values.mode || 'directory_scan');
  const storageSourceId = String(values.storageSourceId || '').trim();
  if (!storageSourceId) throw new Error('请选择存储源');
  const importFormat = String(values.importFormat || 'auto').toLowerCase();
  if (!['auto', 'images', 'yolo', 'coco', 'voc'].includes(importFormat)) {
    throw new Error(`不支持的数据格式：${importFormat}`);
  }
  const format = {import_format: importFormat};
  if (values.datasetYaml) {
    if (importFormat !== 'yolo') throw new Error('只有 YOLO 模式可以提交数据集 YAML');
    format.dataset_yaml = String(values.datasetYaml).trim();
  }

  if (mode === 'storage_scan') {
    const prefix = String(values.prefix || '').trim();
    if (!prefix) throw new Error('请填写对象存储目录');
    if (importFormat === 'auto') throw new Error('远程对象存储扫描请选择“仅图片”、YOLO、COCO 或 Pascal VOC');
    return {
      mode,
      execution_mode: 'agent',
      ...format,
      storage_source_id: storageSourceId,
      prefix,
      recursive: values.recursive !== false,
    };
  }
  if (mode === 'directory_scan') {
    if (['coco', 'voc'].includes(importFormat)) {
      throw new Error('COCO / Pascal VOC 当前仅支持远程 Agent 导入');
    }
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
    const executionMode = String(values.executionMode || 'local').trim().toLowerCase();
    if (!['local', 'agent'].includes(executionMode)) throw new Error('服务器 ZIP 执行方式仅支持中央 Worker 或远程 Agent');
    if (!zipPath) throw new Error('请选择服务器 ZIP');
    if (!targetPrefix) throw new Error('请填写 ZIP 解压目标目录');
    if (executionMode === 'agent' && importFormat === 'auto') {
      throw new Error('远程 Agent ZIP 导入请选择“仅图片”、YOLO、COCO 或 Pascal VOC');
    }
    if (executionMode !== 'agent' && ['coco', 'voc'].includes(importFormat)) {
      throw new Error('COCO / Pascal VOC 服务器 ZIP 仅支持远程 Agent');
    }
    return {
      mode,
      ...(executionMode === 'agent' ? {execution_mode: 'agent'} : {}),
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
  const status = canonicalTaskStatus(task) || 'QUEUED';
  const stage = canonicalTaskPhase(task);
  const metrics = task.metrics || {};
  const current = String(metrics.current_file || task.current_item || '-');
  const queuePosition = exactTaskQueuePosition(task);
  const waitReason = String(task.resource_wait_reason || '').trim();
  let text;

  const isAgent = String(task.execution_mode || '').toLowerCase() === 'agent'
    || String(task.worker_id || '').startsWith('agent:');
  const remoteStages = {
    remote_material_scanning: '正在扫描对象存储',
    remote_material_downloading: '正在读取素材',
    remote_material_extracting: '正在安全解包素材',
    remote_material_reviewing: '正在检查素材内容',
    remote_material_preparing_upload: '正在整理审查结果',
    remote_material_confirming_review: '正在校验审查结果',
  };

  if (status === 'WAITING_RESOURCE') {
    text = [isAgent ? '等待远程素材节点' : '等待 Storage Worker 资源', queuePosition ? `队列第 ${queuePosition} 位` : '', waitReason].filter(Boolean).join(' · ');
  } else if (status === 'AWAITING_CONFIRMATION') {
    text = '扫描完成，等待确认建立素材索引';
  } else if (status === 'QUEUED') {
    const queueLabel = isAgent ? '远程素材任务已排队' : '任务已进入 Storage Worker 队列';
    text = queuePosition ? `${queueLabel} · 第 ${queuePosition} 位` : queueLabel;
  } else if (status === 'SUCCEEDED') {
    text = `导入完成，共建立 ${count(task.result?.imported)} 条素材索引`;
  } else if (status === 'FAILED' || status === 'CANCELLED' || status === 'BLOCKED_BY_ENVIRONMENT') {
    text = String(task.error || task.result?.error?.message || status);
  } else if (remoteStages[stage]) {
    text = [remoteStages[stage], current !== '-' ? current : ''].filter(Boolean).join(' · ');
  } else if (stage === 'extracting') {
    text = `已解压 ${count(metrics.extracted_files)} 个文件 · ${count(metrics.extracted_bytes)} 字节 · 当前 ${current}`;
  } else if (stage === 'scanning') {
    text = `已扫描 ${count(metrics.scanned_files)} · 可导入 ${count(metrics.importable_images)} · 重复 ${count(metrics.duplicates)} · 失败 ${count(metrics.failed) + count(metrics.invalid_images)} · 当前 ${current}`;
  } else if (stage === 'indexing' || stage === 'indexing_queued') {
    text = `正在建立索引 ${count(metrics.indexed_at_least ?? metrics.indexed)} / ${count(metrics.selected)}`;
  } else {
    text = stage || status;
  }

  return {
    status,
    stage,
    text,
    active: isCanonicalTaskActive(task),
    canConfirm: status === 'AWAITING_CONFIRMATION',
    showPercent: stage === 'extracting' && count(metrics.declared_bytes) > 0,
    terminal: isCanonicalTaskTerminal(task),
  };
}
