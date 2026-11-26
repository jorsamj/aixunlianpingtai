import {request} from '../app/http.ts';
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

export interface TrainingBatchDeleteResult {
  ok: boolean;
  requested: number;
  deleted: number;
  deleted_ids: string[];
  skipped_active: number;
  skipped_active_ids: string[];
  missing: number;
  missing_ids: string[];
  failures: {job_id: string; message: string}[];
}

// Existing v48 batch record deletion. The server keeps algorithm versions and
// artifacts, skips active tasks and caps one request at 200 records.
export async function deleteTrainingTaskRecords(
  projectId: string, taskIds: string[], signal: AbortSignal,
) {
  const ids = [...new Set(taskIds.map(id => String(id || '').trim()).filter(Boolean))];
  if (!ids.length || ids.length > 200) throw new Error('批量删除需选择 1–200 条训练记录');
  const result = await request<TrainingBatchDeleteResult>(
    `/api/v48/projects/${encodeURIComponent(projectId)}/jobs/batch-delete`,
    {method: 'POST', body: JSON.stringify({job_ids: ids}), signal},
  );
  if (!result || typeof result.deleted !== 'number' || !Array.isArray(result.failures))
    throw new Error('批量删除回执不完整');
  return result;
}

// Existing v48 training lifecycle endpoints. The native page sends the same
// parameterless POST the original task wall sends; receipts are re-read from the
// canonical v62 reader instead of trusting the legacy job.json projection.
export type TrainingLifecycleAction = 'pause' | 'resume' | 'promote';

export async function runTrainingLifecycleAction(
  projectId: string, taskId: string, action: TrainingLifecycleAction, signal: AbortSignal,
) {
  return request<Record<string, unknown>>(
    `/api/v48/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(taskId)}/${action}`,
    { method: 'POST', signal },
  );
}

// Terminal-only record deletion; the original endpoint refuses active tasks.
export async function deleteTrainingTaskRecord(
  projectId: string, taskId: string, signal: AbortSignal,
) {
  const result = await request<{ok?: boolean} | null>(
    `/api/v12/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(taskId)}`,
    { method: 'DELETE', signal },
  );
  if (result?.ok !== true) throw new Error('删除任务回执不完整');
  return result;
}

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
