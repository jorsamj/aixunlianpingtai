import test from 'node:test';
import assert from 'node:assert/strict';

import {
  canRecoverTrainingTask,
  installTrainingRecoveryRuntime,
  trainingRecoveryDetailModel,
  trainingRecoveryTimeline,
} from '../../static/modules/training-recovery-runtime.js';

function response(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async text() { return JSON.stringify(body); },
  };
}

function cleanup() {
  delete globalThis.window;
  delete globalThis.document;
}

test('100/100 epochs never grant recovery without backend recovery truth', () => {
  const job = {
    id: 'train-100',
    status: 'failed',
    current_epoch: 100,
    total_epochs: 100,
    progress_percent: 100,
    failure_stage: 'final_validation',
  };
  const recovery = {
    completed_epochs: 100,
    requested_epochs: 100,
    training_loop_completed: true,
    checkpoint_available: true,
  };

  assert.equal(canRecoverTrainingTask(recovery), false);
  const model = trainingRecoveryDetailModel(job, recovery);
  assert.equal(model.completedEpochs, 100);
  assert.equal(model.requestedEpochs, 100);
  assert.equal(model.recoverable, false);
  assert.equal(model.action, null);
});

test('successful completion message is never rendered as a failure reason', () => {
  const model = trainingRecoveryDetailModel({
    id: 'train-success',
    status: 'done',
    task_status: 'SUCCEEDED',
    message: '训练完成，模型产物校验通过',
    current_item: '训练完成',
    progress_percent: 100,
    current_epoch: 30,
    total_epochs: 30,
    actual_device: 'cuda:0',
    actual_train_params: {batch: 32, workers: 8, cache: 'ram', effective_precision: 'fp16'},
  }, {});

  assert.equal(model.statusKind, 'success');
  assert.equal(model.failureReason, '');
  assert.deepEqual(model.warnings, []);
  assert.equal(model.trainingLoopCompleted, true);
  assert.equal(model.progressPercent, 100);
  assert.equal(model.actualDevice, 'cuda:0');
  assert.equal(model.batch, 32);
});


test('partial success keeps non-fatal evaluation problem as warning', () => {
  const model = trainingRecoveryDetailModel({
    id: 'train-partial',
    status: 'done',
    task_status: 'PARTIAL_SUCCESS',
    message: '训练主体完成，模型已归档',
    warning_message: '独立评测失败，但训练模型已归档',
  }, {});

  assert.equal(model.statusKind, 'partial');
  assert.equal(model.failureReason, '');
  assert.deepEqual(model.warnings, ['独立评测失败，但训练模型已归档']);
});



test('frontend accepts recovery only when all backend action flags agree', () => {
  const base = {
    available: true,
    recoverable: true,
    checkpoint_available: true,
    recovery_action: 'revalidate_checkpoint',
  };
  assert.equal(canRecoverTrainingTask(base), true);
  assert.equal(canRecoverTrainingTask({...base, available: false}), false);
  assert.equal(canRecoverTrainingTask({...base, recoverable: false}), false);
  assert.equal(canRecoverTrainingTask({...base, checkpoint_available: false}), false);
  assert.equal(canRecoverTrainingTask({...base, recovery_action: null}), false);
  assert.equal(canRecoverTrainingTask({...base, recovery_action: 'retry_training'}), false);
});

test('failure timeline distinguishes completed training from failed final validation', () => {
  const timeline = trainingRecoveryTimeline(
    {id: 'train-1', status: 'failed', current_epoch: 30, total_epochs: 30},
    {
      failure_stage: 'final_validation',
      completed_epochs: 30,
      requested_epochs: 30,
      training_loop_completed: true,
      checkpoint_available: true,
    },
  );
  const states = Object.fromEntries(timeline.map(step => [step.key, step.state]));
  assert.equal(states.training, 'done');
  assert.equal(states.checkpoint, 'done');
  assert.equal(states.validation, 'failed');
  assert.equal(states.archive, 'pending');
});

test('hydrateJobs asks backend only for failed task recovery truth', async () => {
  const state = {project: {id: 'p 1'}, jobs: []};
  const calls = [];
  globalThis.window = {};
  const runtime = installTrainingRecoveryRuntime({
    getState: () => state,
    projectId: () => state.project.id,
    fetchImpl: async (url, init = {}) => {
      calls.push({url, init});
      return response({
        ok: true,
        items: {
          failed1: {
            task_id: 'failed1',
            available: true,
            recoverable: true,
            checkpoint_available: true,
            recovery_action: 'revalidate_checkpoint',
          },
        },
      });
    },
  });

  const jobs = await runtime.hydrateJobs([
    {id: 'running1', status: 'running'},
    {id: 'failed1', status: 'failed'},
  ]);

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, '/api/v62/projects/p%201/training-tasks/recovery-query');
  assert.equal(calls[0].init.method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].init.body), {task_ids: ['failed1']});
  assert.equal(jobs[0].recovery, undefined);
  assert.equal(jobs[1].recovery.available, true);

  runtime.destroy();
  cleanup();
});

test('recover rechecks backend truth then posts checkpoint-only action and refreshes existing training runtime', async () => {
  const state = {project: {id: 'p1'}, jobs: [{id: 'failed1', status: 'failed'}]};
  const calls = [];
  let refreshes = 0;
  let pollResets = 0;
  const notices = [];
  globalThis.window = {
    confirm: () => true,
    TrainingTaskRuntime: {
      async refresh(options) {
        refreshes += 1;
        assert.deepEqual(options, {render: true, force: true, source: 'mutation'});
      },
    },
    PollRegistryRuntime: {
      replaceTrainingJobTimer() { pollResets += 1; },
    },
  };
  const validRecovery = {
    task_id: 'failed1',
    available: true,
    recoverable: true,
    checkpoint_available: true,
    recovery_action: 'revalidate_checkpoint',
  };
  const runtime = installTrainingRecoveryRuntime({
    getState: () => state,
    projectId: () => state.project.id,
    notify: message => notices.push(String(message)),
    fetchImpl: async (url, init = {}) => {
      calls.push(`${String(init.method || 'GET').toUpperCase()} ${url}`);
      if (String(init.method || 'GET').toUpperCase() === 'GET') {
        return response({ok: true, recovery: validRecovery});
      }
      return response({
        ok: true,
        task_id: 'failed1',
        status: 'QUEUED',
        recovery_requested: true,
        recovery_action: 'revalidate_checkpoint',
      }, 202);
    },
  });

  const ok = await runtime.recover('failed1');

  assert.equal(ok, true);
  assert.deepEqual(calls, [
    'GET /api/v62/projects/p1/training-tasks/failed1/recovery',
    'POST /api/v62/projects/p1/training-tasks/failed1/recovery',
  ]);
  assert.equal(refreshes, 1);
  assert.equal(pollResets, 1);
  assert.deepEqual(notices, ['已进入 Checkpoint 重新验证队列']);

  runtime.destroy();
  cleanup();
});

test('successful canonical task truth suppresses stale recoverable failure metadata', () => {
  const model = trainingRecoveryDetailModel({
    id: 'train-recovered-success',
    status: 'failed',
    task_status: 'SUCCEEDED',
    persisted_status: 'SUCCEEDED',
    message: '训练完成，模型产物校验通过',
    progress_percent: 100,
  }, {
    available: true,
    recoverable: true,
    checkpoint_available: true,
    recovery_action: 'revalidate_checkpoint',
    failure_reason: '历史验证失败，不应覆盖成功终态',
  });

  assert.equal(model.statusKind, 'success');
  assert.equal(model.recoverable, false);
  assert.equal(model.failureReason, '');
  assert.deepEqual(model.errors, []);
  assert.equal(model.progressPercent, 100);
});

test('terminal live event performs one final canonical detail and log reconciliation', async () => {
  const state = {
    project: {id: 'p1'},
    jobs: [{
      id: 'train-terminal-reconcile',
      task_id: 'train-terminal-reconcile',
      status: 'running',
      task_status: 'RUNNING',
      progress_percent: 72,
      message: 'Epoch 8/10',
    }],
  };
  const calls = [];
  let finalMode = false;
  globalThis.window = {
    PollRegistryRuntime: {
      clear() {},
      startTimeout() {},
    },
  };
  const runtime = installTrainingRecoveryRuntime({
    getState: () => state,
    projectId: () => state.project.id,
    fetchImpl: async url => {
      calls.push(String(url));
      if (String(url).endsWith('/log')) {
        return {
          ok: true,
          status: 200,
          async text() { return finalMode ? 'training finished\nmodel verified' : 'Epoch 8/10'; },
        };
      }
      return response(finalMode ? {
        id: 'train-terminal-reconcile',
        task_id: 'train-terminal-reconcile',
        status: 'done',
        task_status: 'SUCCEEDED',
        persisted_status: 'SUCCEEDED',
        phase: 'committed',
        progress_percent: 100,
        message: '训练完成，模型产物校验通过',
        artifact_verified: true,
        verified_models: ['best.pt'],
      } : {
        id: 'train-terminal-reconcile',
        task_id: 'train-terminal-reconcile',
        status: 'running',
        task_status: 'RUNNING',
        progress_percent: 72,
        message: 'Epoch 8/10',
      });
    },
  });

  await runtime.openDetail('train-terminal-reconcile');
  calls.length = 0;
  finalMode = true;

  assert.equal(runtime.acceptLiveTask({
    id: 'train-terminal-reconcile',
    task_id: 'train-terminal-reconcile',
    status: 'SUCCEEDED',
    persisted_status: 'SUCCEEDED',
    phase: 'committed',
    progress_percent: 100,
  }), true);

  await new Promise(resolve => setTimeout(resolve, 0));
  await new Promise(resolve => setTimeout(resolve, 0));

  assert.deepEqual(calls, [
    '/api/projects/p1/jobs/train-terminal-reconcile',
    '/api/projects/p1/jobs/train-terminal-reconcile/log',
  ]);
  assert.equal(state.jobs[0].task_status, 'SUCCEEDED');
  assert.equal(state.jobs[0].artifact_verified, true);
  assert.deepEqual(state.jobs[0].verified_models, ['best.pt']);
  assert.equal(state.jobs[0].message, '训练完成，模型产物校验通过');

  runtime.destroy();
  cleanup();
});

test('detail model exposes live metrics resources and dataset evidence', () => {
  const model = trainingRecoveryDetailModel({
    id: 'train-live-detail',
    status: 'running',
    task_status: 'RUNNING',
    progress_percent: 46.5,
    current_epoch: 4,
    total_epochs: 10,
    current_batch: 20,
    total_batches: 100,
    elapsed_seconds: 120,
    eta_seconds: 180,
    training_progress: {
      epoch: 4,
      total_epochs: 10,
      current_batch: 20,
      total_batches: 100,
      elapsed_seconds: 120,
      eta_seconds: 180,
      images_per_second: 92.4,
      metrics: {'metrics/map50(B)': 0.81, 'metrics/precision(B)': 0.78},
      losses: {box_loss: 0.32},
      learning_rates: {'lr/pg0': 0.001},
    },
    actual_device: 'cuda:1',
    actual_train_params: {
      batch: 48,
      workers: 8,
      cache: 'ram',
      resource_profile: 'performance',
      resource_strategy: 'auto',
      gpu_policy: 'exclusive',
      effective_precision: 'fp16',
      imgsz: 640,
      optimizer: 'AdamW',
    },
    dataset_counts: {train: 800, val: 100, test: 100},
  }, {});

  assert.equal(model.statusKind, 'active');
  assert.equal(model.currentBatch, 20);
  assert.equal(model.totalBatches, 100);
  assert.equal(model.resourceProfileLabel, '性能优先');
  assert.equal(model.batch, 48);
  assert.equal(model.datasetCounts.train, 800);
  assert.match(model.metricLine, /mAP50 0\.810/);
  assert.match(model.metricLine, /92\.4 img\/s/);
});

test('detail model exposes runtime resource telemetry from backend metrics truth', () => {
  const model = trainingRecoveryDetailModel({
    id: 'train-resource-live',
    status: 'running',
    task_status: 'RUNNING',
    runtime_metrics: {
      latest: {
        gpu_utilization: 87.5,
        gpu_memory_percent: 71.2,
        cpu_percent: 63.4,
        io_wait_percent: 2.1,
      },
      images_per_second: 155.6,
      epoch_duration_seconds: 18.4,
      diagnostic: {code: 'healthy_utilization'},
    },
  }, {});

  assert.equal(model.gpuUtilization, 87.5);
  assert.equal(model.gpuMemoryPercent, 71.2);
  assert.equal(model.cpuPercent, 63.4);
  assert.equal(model.ioWaitPercent, 2.1);
  assert.equal(model.imagesPerSecond, 155.6);
  assert.equal(model.latestEpochDuration, 18.4);
  assert.equal(model.diagnosticCode, 'healthy_utilization');
});



test('failed detail prioritizes worker root cause and keeps requested resolved runtime resource layers distinct', () => {
  const model = trainingRecoveryDetailModel({
    id: 'train-resource-mismatch',
    status: 'failed',
    task_status: 'FAILED',
    error: 'RESOURCE_RUNTIME_MISMATCH: resolved workers=2; runtime workers=0',
    message: 'training process exited with returncode=1',
    requested_train_params: {
      batch: 4,
      workers: 0,
      cache: false,
    },
    resolved_resources: {
      resource_strategy: 'auto',
      resolved_batch: 11,
      resolved_workers: 0,
      resolved_cache: 'ram',
      adjustments: ['batch capped 100->11 by train image count 11'],
    },
    runtime_resources: {
      runtime_batch: 11,
      runtime_workers: 0,
      runtime_cache: 'ram',
    },
    actual_train_params: {
      batch: 11,
      workers: 0,
      cache: 'ram',
    },
  }, {
    failure_reason: 'training process exited with returncode=1; completion_handshake=job status is not done',
    process_returncode: 1,
    checkpoint_available: false,
    recoverable: false,
  });

  assert.equal(model.errors[0], 'RESOURCE_RUNTIME_MISMATCH: resolved workers=2; runtime workers=0');
  assert.match(model.errors[1], /completion_handshake=job status is not done/);
  assert.equal(model.requestedBatch, 4);
  assert.equal(model.requestedWorkers, 0);
  assert.equal(model.requestedWorkersText, '自动');
  assert.equal(model.requestedCache, false);
  assert.equal(model.requestedCacheText, '关闭');
  assert.equal(model.resolvedBatch, 11);
  assert.equal(model.resolvedWorkers, 0);
  assert.equal(model.resolvedCache, 'ram');
  assert.equal(model.runtimeBatch, 11);
  assert.equal(model.runtimeWorkers, 0);
  assert.equal(model.runtimeCache, 'ram');
  assert.equal(model.batch, 11);
});
