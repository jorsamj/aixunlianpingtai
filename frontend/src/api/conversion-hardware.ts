import {request} from '../app/http';

interface EvidenceFile {
  file_name: string;
  sha256: string;
  size_bytes: number;
}

interface HardwarePreflight {
  ok: boolean;
  ready: boolean;
  already_verified: boolean;
  chip: string;
  model: EvidenceFile;
  board_nodes: {node_id: string; display_name: string; rknn_lite_version: string}[];
  reason: string;
  solution: string;
}

export interface HardwareTask {
  task_id: string;
  project_id: string;
  kind: string;
  status: string;
  attempt: number;
  phase: string;
  progress_percent: number;
  resource_key: string;
  error?: string;
  resource_wait_reason?: string;
}

interface HardwareReport {
  ok: boolean;
  project_id: string;
  conversion_job_id: string;
  status: string;
  acceptance_scope: string;
  hardware_acceptance: string;
  model: EvidenceFile;
  target: {chip: string; precision: string};
  board: {node_id: string; rknn_lite_version: string};
  verification: {
    task_id: string;
    execution_generation: number;
    verified_at: string;
    input: EvidenceFile;
    inference_ms: number;
    output_count: number;
    output_shapes: number[][];
  };
  statement: string;
}

const root = (projectId: string, jobId: string) =>
  `/api/v39/projects/${encodeURIComponent(projectId)}/deploy/jobs/${encodeURIComponent(jobId)}/hardware-tests`;

export const hardwareReportDownload = (projectId: string, jobId: string) =>
  `${root(projectId, jobId)}/report?download=true`;

export async function loadHardwarePreflight(projectId: string, jobId: string, signal: AbortSignal) {
  const value = await request<HardwarePreflight>(`${root(projectId, jobId)}/preflight`, {signal});
  if (value?.ok !== true || typeof value.ready !== 'boolean' || typeof value.already_verified !== 'boolean' ||
      !value.model?.sha256 || !Array.isArray(value.board_nodes) || !value.chip)
    throw new Error('板端验证预检缺少模型或板卡证据');
  return value;
}

function verifyTask(task: HardwareTask, projectId: string, taskId: string, chip: string) {
  if (!/^[a-f0-9]{12}$/.test(taskId) || task?.task_id !== taskId || task.project_id !== projectId ||
      task.kind !== 'DEPLOYMENT_TEST' || task.resource_key !== `deployment-rknn-board:${chip}`)
    throw new Error('板端验证任务回执身份不一致');
  return task;
}

export async function createHardwareTest(
  projectId: string, jobId: string, chip: string, file: File, signal: AbortSignal,
) {
  const body = new FormData();
  body.append('file', file);
  const value = await request<HardwareTask & {source_conversion_job_id: string; chip: string}>(
    root(projectId, jobId), {method: 'POST', body, signal},
  );
  if (value?.source_conversion_job_id !== jobId || value.chip !== chip)
    throw new Error('板端验证回执与当前转换产物不一致');
  return verifyTask(value, projectId, value.task_id, chip);
}

export async function loadHardwareTask(projectId: string, taskId: string, chip: string, signal: AbortSignal) {
  const task = await request<HardwareTask>(
    `/api/v62/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}`, {signal},
  );
  return verifyTask(task, projectId, taskId, chip);
}

export async function loadHardwareReport(projectId: string, jobId: string, signal: AbortSignal) {
  const value = await request<HardwareReport>(`${root(projectId, jobId)}/report`, {signal});
  if (value?.ok !== true || value.project_id !== projectId || value.conversion_job_id !== jobId ||
      value.status !== 'passed' || value.hardware_acceptance !== 'VERIFIED' ||
      value.acceptance_scope !== 'rknn_runtime_hardware' || !value.verification?.task_id)
    throw new Error('板端验收报告与当前转换任务不一致');
  return value;
}
