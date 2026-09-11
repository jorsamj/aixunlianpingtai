import test from 'node:test';
import assert from 'node:assert/strict';

import {
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
    mode: 'directory_scan', storageSourceId: 'local-a', prefix: 'dataset', importFormat: 'yolo', datasetYaml: 'data.yaml',
  }), {
    mode: 'directory_scan', import_format: 'yolo', dataset_yaml: 'data.yaml', storage_source_id: 'local-a', prefix: 'dataset', recursive: true,
  });
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
