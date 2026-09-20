import test from 'node:test';
import assert from 'node:assert/strict';

import {
  buildImportConfirmation,
  buildServerImportRequest,
  serverImportView,
} from '../../static/modules/server-material-import.js';

test('server material import requests contain source-relative fields and explicit format', () => {
  assert.deepEqual(buildServerImportRequest({
    mode: 'directory_scan', storageSourceId: 'local-a', prefix: 'fire/2026', recursive: true,
  }), {
    mode: 'directory_scan', import_format: 'auto', storage_source_id: 'local-a', prefix: 'fire/2026', recursive: true,
  });
  assert.deepEqual(buildServerImportRequest({
    mode: 'server_zip', storageSourceId: 'local-a', zipPath: 'fire.zip', targetPrefix: 'fire',
  }), {
    mode: 'server_zip', import_format: 'auto', storage_source_id: 'local-a', zip_path: 'fire.zip', target_prefix: 'fire', recursive: true,
  });
  assert.deepEqual(buildServerImportRequest({
    mode: 'server_zip', executionMode: 'agent', storageSourceId: 's3-a',
    zipPath: 'coco.zip', targetPrefix: 'incoming/coco', importFormat: 'coco',
  }), {
    mode: 'server_zip', execution_mode: 'agent', import_format: 'coco',
    storage_source_id: 's3-a', zip_path: 'coco.zip', target_prefix: 'incoming/coco', recursive: true,
  });
  assert.deepEqual(buildServerImportRequest({
    mode: 'server_zip', executionMode: 'agent', storageSourceId: 's3-a',
    zipPath: 'voc.zip', targetPrefix: 'incoming/voc', importFormat: 'voc',
  }), {
    mode: 'server_zip', execution_mode: 'agent', import_format: 'voc',
    storage_source_id: 's3-a', zip_path: 'voc.zip', target_prefix: 'incoming/voc', recursive: true,
  });
  assert.deepEqual(buildServerImportRequest({
    mode: 'directory_scan', storageSourceId: 'local-a', prefix: 'dataset', importFormat: 'yolo', datasetYaml: 'data.yaml',
  }), {
    mode: 'directory_scan', import_format: 'yolo', dataset_yaml: 'data.yaml', storage_source_id: 'local-a', prefix: 'dataset', recursive: true,
  });
  assert.deepEqual(buildServerImportRequest({
    mode: 'storage_scan', storageSourceId: 's3-a', prefix: 'datasets/fire/2026',
    recursive: true, importFormat: 'yolo', datasetYaml: 'datasets/fire/2026/data.yaml',
  }), {
    mode: 'storage_scan', execution_mode: 'agent', import_format: 'yolo',
    dataset_yaml: 'datasets/fire/2026/data.yaml', storage_source_id: 's3-a',
    prefix: 'datasets/fire/2026', recursive: true,
  });
  assert.deepEqual(buildServerImportRequest({
    mode: 'storage_scan', storageSourceId: 's3-a', prefix: 'datasets/coco',
    recursive: true, importFormat: 'coco',
  }), {
    mode: 'storage_scan', execution_mode: 'agent', import_format: 'coco',
    storage_source_id: 's3-a', prefix: 'datasets/coco', recursive: true,
  });
  assert.deepEqual(buildServerImportRequest({
    mode: 'storage_scan', storageSourceId: 's3-a', prefix: 'datasets/voc',
    recursive: false, importFormat: 'voc',
  }), {
    mode: 'storage_scan', execution_mode: 'agent', import_format: 'voc',
    storage_source_id: 's3-a', prefix: 'datasets/voc', recursive: false,
  });
  assert.throws(() => buildServerImportRequest({
    mode: 'directory_scan', storageSourceId: 'local-a', prefix: 'dataset', importFormat: 'coco',
  }), /仅支持远程 Agent/);
  assert.throws(() => buildServerImportRequest({
    mode: 'server_zip', executionMode: 'local', storageSourceId: 'local-a',
    zipPath: 'coco.zip', targetPrefix: 'incoming/coco', importFormat: 'coco',
  }), /服务器 ZIP 仅支持远程 Agent/);
  assert.throws(() => buildServerImportRequest({
    mode: 'server_zip', executionMode: 'agent', storageSourceId: 's3-a',
    zipPath: 'coco.zip', targetPrefix: 'incoming/coco', importFormat: 'auto',
  }), /远程 Agent ZIP 导入/);
  assert.throws(() => buildServerImportRequest({
    mode: 'storage_scan', storageSourceId: 's3-a', prefix: 'dataset',
    importFormat: 'voc', datasetYaml: 'data.yaml',
  }), /只有 YOLO/);
  assert.throws(() => buildServerImportRequest({
    mode: 'storage_scan', storageSourceId: 's3-a', prefix: '', importFormat: 'images',
  }), /对象存储目录/);
  assert.throws(() => buildServerImportRequest({
    mode: 'storage_scan', storageSourceId: 's3-a', prefix: 'datasets', importFormat: 'auto',
  }), /远程对象存储扫描/);
});

test('server material import view uses real counters and distinct confirmation state', () => {
  const scanning = serverImportView({
    status: 'RUNNING', stage: 'scanning', progress: 58,
    metrics: {scanned_files: 15420, importable_images: 14886, duplicates: 522, failed: 12},
    current_item: 'fire/a.jpg',
  });
  assert.match(scanning.text, /已扫描 15420/);
  assert.equal(scanning.showPercent, false);
  assert.equal(scanning.text.includes('58%'), false);
  assert.equal(serverImportView({status: 'AWAITING_CONFIRMATION'}).canConfirm, true);
  assert.equal(serverImportView({status: 'RUNNING', stage: 'indexing'}).canConfirm, false);
});

test('resource-waiting storage import remains active until durable truth changes', () => {
  const waiting = serverImportView({
    status: 'WAITING_RESOURCE',
    resource_queue_position: 2,
    resource_queue_position_exact: true,
    resource_wait_reason: 'STORAGE_WORKER_BUSY',
  });
  assert.equal(waiting.active, true);
  assert.equal(waiting.terminal, false);

  const remoteWaiting = serverImportView({
    status: 'WAITING_RESOURCE',
    execution_mode: 'agent',
    resource_wait_reason: 'NO_COMPATIBLE_NODE',
  });
  assert.match(remoteWaiting.text, /等待远程素材节点/);

  const remoteRunning = serverImportView({
    status: 'RUNNING',
    execution_mode: 'agent',
    stage: 'REMOTE_MATERIAL_SCANNING',
    current_item: 'datasets/fire/a.jpg',
  });
  assert.match(remoteRunning.text, /正在扫描对象存储/);
  assert.match(remoteRunning.text, /datasets\/fire\/a.jpg/);

  const confirmationWinsOverStaleStage = serverImportView({
    status: 'AWAITING_CONFIRMATION',
    execution_mode: 'agent',
    stage: 'REMOTE_MATERIAL_REVIEWING',
    current_item: 'datasets/fire/a.jpg',
  });
  assert.equal(confirmationWinsOverStaleStage.canConfirm, true);
  assert.equal(confirmationWinsOverStaleStage.text, '扫描完成，等待确认建立素材索引');
});


test('server import canonical task status wins and candidate queue rank is not presented as exact', () => {
  const waiting = serverImportView({
    status: 'SUCCEEDED', task_status: 'WAITING_RESOURCE', phase: 'resource_waiting',
    resource_queue_position: 9, resource_queue_position_exact: false,
    resource_wait_reason: 'STORAGE_WORKER_BUSY',
  });
  assert.equal(waiting.status, 'WAITING_RESOURCE');
  assert.equal(waiting.active, true);
  assert.match(waiting.text, /等待 Storage Worker 资源/);
  assert.match(waiting.text, /STORAGE_WORKER_BUSY/);
  assert.doesNotMatch(waiting.text, /队列第 9 位/);
});

test('server import confirmation emits mappings only for existing labels', () => {
  assert.deepEqual(buildImportConfirmation([
    {classId: '0', code: 'helmet'},
    {classId: '1', code: 'person'},
  ], true), {
    label_mapping: {'0': 'helmet', '1': 'person'},
    accept_quality_report: true,
  });
  assert.throws(() => buildImportConfirmation([
    {classId: '0', code: 'helmet_new', create: true},
  ]), /不能创建平台标签/);
});

