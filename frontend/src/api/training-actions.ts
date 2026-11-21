import {request} from '../app/http';
import type {TrainingTask} from './training-reader';

export interface TrainingRecoveryTruth {
  task_id: string;
  project_id: string;
  task_status: string;
  available: boolean;
  recoverable: boolean;
  checkpoint_available: boolean;
  recovery_action: 'revalidate_checkpoint' | null;
  declared_recovery_action?: string | null;
  failure_stage?: string | null;
  failure_reason?: string | null;
  diagnosis?: string | null;
  completion_handshake?: string | null;
}

const root = (projectId: string) =>
  `/api/v62/projects/${encodeURIComponent(projectId)}`;

export async function stopTrainingTask(
  projectId: string, taskId: string, signal: AbortSignal,
) {
  const task = await request<TrainingTask>(`${root(projectId)}/tasks/${encodeURIComponent(taskId)}/cancel`, {
    method: 'POST', signal,
  });
  if (task.project_id !== projectId || task.task_id !== taskId)
    throw new Error('停止回执与当前训练任务身份不一致');
  return task;
}

export async function fetchTrainingRecovery(
  projectId: string, taskId: string, signal: AbortSignal,
) {
  const result = await request<{ok: boolean; recovery: TrainingRecoveryTruth}>(
    `${root(projectId)}/training-tasks/${encodeURIComponent(taskId)}/recovery`, {signal},
  );
  const recovery = result?.recovery;
  if (!recovery || recovery.task_id !== taskId || recovery.project_id !== projectId)
    throw new Error('恢复证据与当前训练任务身份不一致');
  return recovery;
}

export async function requestTrainingRecovery(
  projectId: string, taskId: string, action: 'revalidate_checkpoint', signal: AbortSignal,
) {
  const result = await request<{ok: boolean; task_id: string; status: string;
    stage?: string; attempt?: number; recovery_requested: boolean}>(
    `${root(projectId)}/training-tasks/${encodeURIComponent(taskId)}/recovery`,
    {method: 'POST', signal, body: JSON.stringify({action})},
  );
  if (!result?.ok || result.task_id !== taskId)
    throw new Error('恢复受理回执与当前训练任务身份不一致');
  return result;
}
