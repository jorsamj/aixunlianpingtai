import test from 'node:test';
import assert from 'node:assert/strict';

import {
  checkpointResumeBadge,
  checkpointResumeTimeline,
  checkpointResumeView,
  isCheckpointResumeJob,
} from '../../static/modules/training-checkpoint-resume-ui.js';

const running = {
  id: 'train-1',
  status: 'running',
  task_status: 'RUNNING',
  phase: 'resuming_training',
  recovery_mode: 'training_checkpoint_resume',
  recovery_state: 'training',
  resume_from_epoch: 36,
  current_epoch: 41,
  requested_epochs: 100,
  total_epochs: 100,
  resume_checkpoint: '/data/projects/p1/runs/train_train-1/weights/last.pt',
  assigned_device: 'cuda:0',
  task_worker_id: 'worker-a',
  current_item: '断点续训 · Epoch 41/100',
};

test('checkpoint resume job is distinguished from final-validation retry', () => {
  assert.equal(isCheckpointResumeJob(running), true);
  assert.equal(isCheckpointResumeJob({recovery_action: 'revalidate_checkpoint'}), false);
});

test('checkpoint resume view keeps backend epoch truth', () => {
  const view = checkpointResumeView(running);
  assert.equal(view.fromEpoch, 36);
  assert.equal(view.currentEpoch, 41);
  assert.equal(view.totalEpochs, 100);
  assert.equal(view.checkpointName, 'last.pt');
  assert.equal(view.assignedDevice, 'cuda:0');
  assert.equal(view.workerId, 'worker-a');
});

test('active resume badge states the real resume point', () => {
  assert.equal(checkpointResumeBadge(running), '断点续训 · 从 Epoch 36');
});

test('resume timeline does not claim validation or archive finished early', () => {
  const timeline = checkpointResumeTimeline(running);
  assert.deepEqual(timeline.map(step => step.state), ['done', 'done', 'active', 'pending', 'pending']);
});

test('validation phase is shown after resumed training loop', () => {
  const job = {...running, phase: 'final_validation', recovery_state: 'training_loop_completed', current_epoch: 100};
  assert.equal(checkpointResumeBadge(job), '续训完成 · 正在模型验证');
  assert.deepEqual(checkpointResumeTimeline(job).map(step => step.state), ['done', 'done', 'done', 'active', 'pending']);
});

test('finalizing commit phase comes from backend task truth and marks archive active', () => {
  const job = {...running, phase: 'finalizing_commit', recovery_state: 'validation_completed', current_epoch: 100};
  assert.equal(checkpointResumeBadge(job), '续训完成 · 正在归档');
  assert.deepEqual(checkpointResumeTimeline(job).map(step => step.state), ['done', 'done', 'done', 'pending', 'active']);
});

test('completed resume shows archive complete without exposing a manual retry button contract', () => {
  const job = {...running, status: 'done', task_status: 'SUCCEEDED', recovery_state: 'completed', current_epoch: 100};
  assert.equal(checkpointResumeBadge(job), '已从 Epoch 36 恢复');
  assert.deepEqual(checkpointResumeTimeline(job).map(step => step.state), ['done', 'done', 'done', 'done', 'done']);
});
