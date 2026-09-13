import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {storageImportProgressText} from '../../static/modules/storage-import-progress.js';


test('storage scan renders authoritative unified runtime progress', () => {
  const text = storageImportProgressText({
    status: 'RUNNING',
    phase: 'SCANNING',
    progress_percent: 37.5,
    current_item: '已扫描 12531 / 可导入 9824 / 重复 2694 / 失败 13 / camera.jpg',
    worker_id: 'storage-worker-01',
  });
  assert.equal(text, 'SCANNING · 38% · 已扫描 12531 / 可导入 9824 / 重复 2694 / 失败 13 / camera.jpg · 执行节点 storage-worker-01');
});


test('queued and resource-waiting scans expose real queue state', () => {
  assert.equal(storageImportProgressText({status: 'QUEUED', resource_queue_position: 3, priority: 1}), '排队中 · 队列第 3 位 · 优先级 1');
  assert.equal(storageImportProgressText({status: 'WAITING_RESOURCE', resource_queue_position: 2, resource_wait_reason: 'RESOURCE_BUSY'}), '等待资源 · 队列第 2 位 · RESOURCE_BUSY');
  assert.equal(storageImportProgressText({status: 'RUNNING', phase: 'FINALIZING', progress_percent: 91}), '正在整理扫描结果 · 91%');
});


test('storage scan polls unified durable task truth while work is active', () => {
  const source = fs.readFileSync('static/modules/storage-import-progress.js', 'utf8');
  assert.match(source, /\/api\/v62\/projects\/\$\{encodeURIComponent\(projectId\)\}\/tasks\/\$\{encodeURIComponent\(task\.task_id\)\}/);
  assert.match(source, /while \(isTaskActive\(current\.status\)\)/);
  assert.match(source, /const completed=await responseJson|const completed = await responseJson/);
});
