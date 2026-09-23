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
