import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';

import {
  checkpointResumeBadge,
  checkpointResumeTimeline,
  checkpointResumeView,
  isAutomaticTrainingRecoveryJob,
  isCheckpointResumeJob,
  isFinalizationReplayJob,
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

const replayingFinalization = {
  id: 'train-archive-1',
  status: 'running',
  task_status: 'RUNNING',
  phase: 'finalizing_commit',
  recovery_mode: 'finalization_replay',
  recovery_state: 'finalizing_commit',
  final_validation_reused: true,
  progress_percent: 98,
  current_epoch: 100,
  requested_epochs: 100,
  total_epochs: 100,
  assigned_device: 'cuda:0',
  task_worker_id: 'worker-b',
  current_item: 'Final Validation 已通过，正在恢复结果与算法版本归档',
};

test('checkpoint resume job is distinguished from final-validation retry', () => {
  assert.equal(isCheckpointResumeJob(running), true);
  assert.equal(isCheckpointResumeJob({recovery_action: 'revalidate_checkpoint'}), false);
});

test('automatic recovery distinguishes checkpoint resume and finalization replay', () => {
  assert.equal(isFinalizationReplayJob(replayingFinalization), true);
  assert.equal(isCheckpointResumeJob(replayingFinalization), false);
  assert.equal(isAutomaticTrainingRecoveryJob(running), true);
  assert.equal(isAutomaticTrainingRecoveryJob(replayingFinalization), true);
  assert.equal(isAutomaticTrainingRecoveryJob({recovery_action: 'revalidate_checkpoint'}), false);
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

test('finalization replay shows validation as already complete and archive as active', () => {
  const view = checkpointResumeView(replayingFinalization);
  assert.equal(view.finalizationReplay, true);
  assert.equal(view.finalValidationReused, true);
  assert.equal(checkpointResumeBadge(replayingFinalization), '恢复归档 · 跳过重训和重验证');
  assert.deepEqual(
    checkpointResumeTimeline(replayingFinalization).map(step => step.state),
    ['done', 'done', 'done', 'active'],
  );
  assert.deepEqual(
    checkpointResumeTimeline(replayingFinalization).map(step => step.label),
    ['任务重新接管', '模型训练', '独立 Final Validation', '版本与结果归档'],
  );
});

test('completed resume shows archive complete without exposing a manual retry button contract', () => {
  const job = {...running, status: 'done', task_status: 'SUCCEEDED', recovery_state: 'completed', current_epoch: 100};
  assert.equal(checkpointResumeBadge(job), '已从 Epoch 36 恢复');
  assert.deepEqual(checkpointResumeTimeline(job).map(step => step.state), ['done', 'done', 'done', 'done', 'done']);
});


test('checkpoint detail fallback calls the named recovery runtime instead of a captured previous window owner', () => {
  const source = fs.readFileSync(new URL('../../static/modules/training-checkpoint-resume-ui.js', import.meta.url), 'utf8');
  assert.equal(source.includes('originalOpenDetail'), false);
  assert.match(source, /window\.TrainingRecoveryRuntime\?\.openDetail\?\.\(taskId\)/);
  assert.match(source, /const recoveryOpen = window\.TrainingRecoveryRuntime\?\.openDetail/);
});
