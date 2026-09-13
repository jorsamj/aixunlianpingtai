import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {annotationTaskView} from '../../static/modules/annotation-task-view.js';
import {isMaterialBatchActive, materialBatchTaskText} from '../../static/modules/material-batches.js';

test('AI annotation waiting-resource state stays active and shows real queue metadata', () => {
  const view = annotationTaskView({
    status: 'WAITING_RESOURCE', progress_percent: 12.5, completed_count: 5, total_count: 40,
    resource_queue_position: 2, resource_wait_reason: 'VISION_CAPACITY_BUSY',
  });
  assert.equal(view.active, true);
  assert.equal(view.statusText, '等待资源');
  assert.equal(view.percent, 12.5);
  assert.equal(view.runtimeText, '资源队列第 2 位 · VISION_CAPACITY_BUSY');
});

test('material batch waiting-resource state remains pollable and human-readable', () => {
  assert.equal(isMaterialBatchActive('WAITING_RESOURCE'), true);
  assert.equal(
    materialBatchTaskText({status:'WAITING_RESOURCE', resource_queue_position:3, resource_wait_reason:'MATERIAL_WORKER_BUSY'}),
    '等待资源 · 资源队列第 3 位 · MATERIAL_WORKER_BUSY',
  );
  assert.equal(materialBatchTaskText({status:'RUNNING', worker_id:'materials-worker-01'}), '处理中 · Worker materials-worker-01');
});

test('live annotation table/modal consumes runtimeText instead of hiding it', () => {
  const source = fs.readFileSync(new URL('../../static/app.js', import.meta.url), 'utf8');
  assert.match(source, /task\.current_item\|\|view\.runtimeText\|\|'等待 Worker 处理'/);
  assert.match(source, /view\.runtimeText\?`<div class="muted-line">/);
});
