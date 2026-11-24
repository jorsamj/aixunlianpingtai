import {request} from '../app/http.ts';
import type {AiFailurePage,AiTask} from '../types/ai-tasks';

// Write/read owner for the existing v60 annotation-task endpoints. Parameter
// names, receipts and idempotency stay those of the original workbench; this
// module never invents a second task or receipt store.
const base = (projectId: string) =>
  `/api/v60/projects/${encodeURIComponent(projectId)}/annotation-tasks`;

function identity<T extends {ok?: boolean; project_id?: string}>(value: T, projectId: string) {
  if (value?.ok !== true || value.project_id !== projectId)
    throw new Error('AI任务响应项目身份不一致');
  return value;
}
function receipt(projectId: string, taskId: string, value: AiTask) {
  if (typeof value?.id !== 'string' || !value.id.trim() || value.id !== taskId
      || value.project_id !== projectId)
    throw new Error('AI任务操作回执身份不一致');
  return value;
}

export async function fetchAiTaskDetail(projectId: string, taskId: string, signal: AbortSignal) {
  const value = await request<{ok: boolean; project_id: string; task: AiTask}>(
    `${base(projectId)}/${encodeURIComponent(taskId)}?reader_view=true`, {signal});
  identity(value, projectId);
  if (value.task?.id !== taskId || value.task.project_id !== projectId)
    throw new Error('AI任务详情身份不一致');
  return value.task;
}

export async function fetchAiTaskFailures(
  projectId: string, taskId: string, signal: AbortSignal, cursor = '',
) {
  const query = new URLSearchParams({reader_view: 'true', filter: 'failed', limit: '12'});
  if (cursor) query.set('cursor', cursor);
  const value = await request<AiFailurePage>(
    `${base(projectId)}/${encodeURIComponent(taskId)}/candidates?${query}`, {signal});
  identity(value, projectId);
  if (value.task_id !== taskId || !Array.isArray(value.items)
      || value.items.some(row => row.status !== 'failed'))
    throw new Error('AI任务失败分页身份不一致');
  return value;
}

export async function cancelAiTask(projectId: string, taskId: string, signal: AbortSignal) {
  return receipt(projectId, taskId, await request<AiTask>(
    `${base(projectId)}/${encodeURIComponent(taskId)}/cancel`, {method: 'POST', signal}));
}

// The original endpoint accepts an optional failed-image subset. Omit the body
// for the whole-task retry the legacy wall used.
export async function retryAiTask(
  projectId: string, taskId: string, signal: AbortSignal, imageIds: string[] = [],
) {
  const options: RequestInit = {method: 'POST', signal};
  if (imageIds.length) options.body = JSON.stringify({image_ids: imageIds});
  return receipt(projectId, taskId, await request<AiTask>(
    `${base(projectId)}/${encodeURIComponent(taskId)}/retry`, options));
}

export async function recoverAiTaskReview(projectId: string, taskId: string, signal: AbortSignal) {
  return receipt(projectId, taskId, await request<AiTask>(
    `${base(projectId)}/${encodeURIComponent(taskId)}/review-completed`, {method: 'POST', signal}));
}
