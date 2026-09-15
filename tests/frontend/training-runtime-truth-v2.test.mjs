import test from 'node:test';
import assert from 'node:assert/strict';

import {
  trainingProgressView,
  trainingStageView,
  trainingTaskRow,
} from '../../static/modules/training-task-runtime.js';

test('preparation stages never masquerade as Epoch 0 progress', () => {
  const html = trainingTaskRow({
    id: 'prep-1',
    status: 'running',
    task_stage: 'materializing',
    progress_percent: 14,
    current_item: '准备训练数据 6842/10136',
    total_epochs: 30,
    framework: 'ultralytics',
  });

  assert.match(html, /准备训练数据 · 14%/);
  assert.match(html, /6842\/10136/);
  assert.doesNotMatch(html, /Epoch 0\/30/);
  assert.doesNotMatch(html, />0\/30 · 14%/);
});

test('trainer startup derives truthful substage from durable runtime evidence', () => {
  assert.equal(trainingStageView({
    status: 'running', task_stage: 'trainer_startup', message: '验证训练设备与资源',
  }).label, '验证训练设备');

  assert.equal(trainingStageView({
    status: 'running', task_stage: 'trainer_startup', actual_device: 'cuda:0',
    message: '验证训练设备与资源',
  }).label, '加载训练模型');

  assert.equal(trainingStageView({
    status: 'running', task_stage: 'trainer_startup', actual_device: 'cuda:0',
    resolved_resources: {resolved_batch: 8}, message: '验证训练设备与资源',
  }).label, '初始化训练器与数据加载器');
});

test('non-exact GPU queue rank is shown as dynamic candidate truth rather than exact execution order', () => {
  const html = trainingTaskRow({
    id: 'gpu-q3',
    status: 'queued',
    resource_pool_label: 'GPU 自动',
    resource_queue_position: 3,
    resource_queue_position_exact: false,
    progress_percent: 0,
    total_epochs: 30,
    framework: 'ultralytics',
  });

  assert.match(html, /GPU 自动 · 排队中 · 前方约 2 个候选任务（动态）/);
  assert.doesNotMatch(html, /队列第 3 位/);
});

test('exact resource queues keep exact numeric position', () => {
  const html = trainingTaskRow({
    id: 'cpu-q2',
    status: 'queued',
    resource_pool_label: 'CPU',
    resource_queue_position: 2,
    resource_queue_position_exact: true,
    total_epochs: 10,
    framework: 'ultralytics',
  });

  assert.match(html, /CPU · 队列第 2 位/);
});

test('epoch and batch truth are shown only after training actually starts', () => {
  const job = {
    id: 'train-1',
    status: 'running',
    task_stage: 'training',
    current_epoch: 7,
    total_epochs: 30,
    current_batch: 318,
    total_batches: 634,
    progress_percent: 34.2,
    framework: 'ultralytics',
    training_progress: {
      metrics: {
        'metrics/precision(B)': 0.817,
        'metrics/recall(B)': 0.763,
        'metrics/mAP50(B)': 0.801,
        'metrics/mAP50-95(B)': 0.526,
      },
      losses: {box_loss: 0.842, cls_loss: 0.391},
    },
  };
  const progress = trainingProgressView(job);
  const html = trainingTaskRow(job);

  assert.equal(progress.currentBatch, 318);
  assert.equal(progress.totalBatches, 634);
  assert.match(html, /Epoch 7\/30 · Batch 318\/634 · 34%/);
  assert.match(html, /Precision 0\.817/);
  assert.match(html, /Recall 0\.763/);
  assert.match(html, /mAP50 0\.801/);
});

test('resource waiting reason stays visible and is not converted into a fake queue rank', () => {
  const html = trainingTaskRow({
    id: 'wait-gpu',
    status: 'waiting',
    task_stage: 'resource_waiting',
    resource_pool_label: 'GPU 自动',
    resource_queue_position: 2,
    resource_queue_position_exact: false,
    resource_wait_reason: 'GPU_MEMORY_BUSY',
    progress_percent: 0,
    total_epochs: 30,
    framework: 'ultralytics',
  });

  assert.match(html, /等待资源/);
  assert.match(html, /GPU 自动 · GPU_MEMORY_BUSY/);
  assert.doesNotMatch(html, /队列第 2 位/);
});
