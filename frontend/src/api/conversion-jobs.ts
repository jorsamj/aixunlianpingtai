import {request, requestText} from '../app/http.ts';
import type {
  ConversionCatalog,
  ConversionContractResult,
  ConversionJobDetail,
  ConversionJobRequest,
  ConversionNumericHistoryEntry,
  ConversionSource,
  DeployResource,
} from '../types/conversion-job';

const projectRoot = (projectId: string) =>
  `/api/v39/projects/${encodeURIComponent(projectId)}`;

// Dynamic vendor/chip/template dictionary owned by the existing conversion
// catalog API. The native page never keeps a copy of these records.
export async function loadConversionCatalog(signal: AbortSignal) {
  const value = await request<ConversionCatalog>('/api/v39/deploy/catalog', {signal});
  if (!value || !Array.isArray(value.vendors) || !Array.isArray(value.chips) ||
      !Array.isArray(value.templates)) throw new Error('转换字典响应格式无效');
  return value;
}

// Cached resource facts only: no SDK probe is started by opening the form.
export async function loadConversionResources(signal: AbortSignal) {
  const value = await request<{ok?: boolean; items?: DeployResource[]}>(
    '/api/v39/deploy/resources?detect_missing=false', {signal},
  );
  if (value?.ok !== true || !Array.isArray(value.items))
    throw new Error('转换资源响应格式无效');
  return value.items;
}

export async function loadConversionSources(projectId: string, signal: AbortSignal) {
  const value = await request<{ok?: boolean; items?: ConversionSource[]}>(
    `${projectRoot(projectId)}/deploy/source-models`, {signal},
  );
  if (value?.ok !== true || !Array.isArray(value.items))
    throw new Error('转换源模型响应格式无效');
  return value.items;
}

// Same preview/admission contract the original create dialog resolves.
export async function resolveConversion(
  projectId: string, body: ConversionJobRequest, signal: AbortSignal,
) {
  const value = await request<ConversionContractResult>(
    `${projectRoot(projectId)}/deploy/resolve`,
    {method: 'POST', signal, body: JSON.stringify(body)},
  );
  if (!value || typeof value.ready !== 'boolean' || typeof value.status !== 'string')
    throw new Error('转换合同响应格式无效');
  return value;
}

// Existing conversion task creation owner. Idempotency is the caller's
// request_id; the response is checked against the submitted identity.
export async function createConversionJob(
  projectId: string, body: ConversionJobRequest, signal: AbortSignal,
) {
  const value = await request<{ok?: boolean; job?: ConversionJobDetail}>(
    `${projectRoot(projectId)}/deploy/jobs`,
    {method: 'POST', signal, body: JSON.stringify(body)},
  );
  const job = value?.job;
  if (value?.ok !== true || !job?.id) throw new Error('转换任务创建回执不完整');
  if (job.project_id !== projectId || job.source_id !== body.source_id)
    throw new Error('转换任务回执与当前项目或源模型不一致');
  if (body.request_id && job.request_id !== body.request_id)
    throw new Error('转换任务回执与当前请求 ID 不一致');
  return job;
}

export async function loadConversionJob(
  projectId: string, jobId: string, signal: AbortSignal,
) {
  const job = await request<ConversionJobDetail>(
    `${projectRoot(projectId)}/deploy/jobs/${encodeURIComponent(jobId)}`, {signal},
  );
  if (job?.id !== jobId || (job.project_id && job.project_id !== projectId))
    throw new Error('转换任务响应身份不一致');
  return job;
}

export async function loadConversionNumericHistory(projectId:string,jobId:string,signal:AbortSignal) {
  const value = await request<{ok:boolean;items:ConversionNumericHistoryEntry[]}>(
    `${projectRoot(projectId)}/deploy/jobs/${encodeURIComponent(jobId)}/numeric-validations`,{signal},
  );
  if (value?.ok !== true || !Array.isArray(value.items) || value.items.length > 20 ||
      value.items.some(row=>!row?.id || row.conversion_job_id!==jobId || row.task?.task_id!==row.id ||
        row.task?.project_id!==projectId || row.task?.kind!=='MODEL_CONVERSION'))
    throw new Error('数值验证历史响应身份不一致');
  return value.items;
}

export async function stopConversionJob(projectId: string, jobId: string, signal: AbortSignal) {
  const value = await request<{ok?: boolean}>(
    `${projectRoot(projectId)}/deploy/jobs/${encodeURIComponent(jobId)}/stop`, {method: 'POST', signal},
  );
  if (value?.ok !== true) throw new Error('转换停止请求回执不完整');
}

const numericRoot = (projectId: string, jobId: string) =>
  `${projectRoot(projectId)}/deploy/jobs/${encodeURIComponent(jobId)}/numeric-validations`;

export async function resolveNumericVerificationId(projectId: string, jobId: string, requestId: string) {
  if (!globalThis.crypto?.subtle) return '';
  const digest = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(`${projectId}:${jobId}:${requestId}`));
  return 'nv_' + Array.from(new Uint8Array(digest).slice(0, 12), byte => byte.toString(16).padStart(2, '0')).join('');
}

function verifyNumericReceipt(
  value: ConversionNumericHistoryEntry & {ok?: boolean}, projectId: string, jobId: string, verificationId: string,
) {
  if (value?.ok !== true || !/^nv_[a-f0-9]{24}$/.test(value.id) || (verificationId && value.id !== verificationId) ||
      value.conversion_job_id !== jobId || value.task?.task_id !== value.id || value.task?.project_id !== projectId ||
      value.task?.kind !== 'MODEL_CONVERSION') throw new Error('数值验证回执身份不一致');
  return value;
}

export async function loadNumericValidation(projectId: string, jobId: string, verificationId: string, signal: AbortSignal) {
  const value = await request<ConversionNumericHistoryEntry & {ok?: boolean}>(
    `${numericRoot(projectId, jobId)}/${encodeURIComponent(verificationId)}`, {signal},
  );
  return verifyNumericReceipt(value, projectId, jobId, verificationId);
}

export async function createNumericValidation(
  projectId: string, jobId: string, verificationId: string, body: FormData, signal: AbortSignal,
) {
  const value = await request<ConversionNumericHistoryEntry & {ok?: boolean}>(
    numericRoot(projectId, jobId), {method: 'POST', body, signal},
  );
  return verifyNumericReceipt(value, projectId, jobId, verificationId);
}

// Read-only recovery of an unconfirmed creation; no new request ID is minted.
export async function findConversionByRequest(
  projectId: string, requestId: string, signal: AbortSignal,
) {
  const value = await request<{
    ok?: boolean; found?: boolean; pending?: boolean; job?: ConversionJobDetail;
  }>(
    `${projectRoot(projectId)}/deploy/jobs/by-request/${encodeURIComponent(requestId)}`,
    {signal},
  );
  if (value?.ok !== true || typeof value.found !== 'boolean')
    throw new Error('转换请求核验响应格式无效');
  return value;
}

// Existing plain-text log endpoint through the shared text request owner.
export async function loadConversionLog(
  projectId: string, jobId: string, signal: AbortSignal,
) {
  const text = await requestText(
    `${projectRoot(projectId)}/deploy/jobs/${encodeURIComponent(jobId)}/log`, {signal},
  );
  return text.slice(-160000);
}

export function newConversionRequestId() {
  const uuid = globalThis.crypto?.randomUUID?.().replace(/-/g, '');
  return uuid
    ? `conv_${uuid}`
    : `conv_${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
}
