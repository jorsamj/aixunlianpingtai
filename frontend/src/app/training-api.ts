import {request} from './http';
import type {AlgorithmSummary, ModelVersion} from '../types/model-browse';
import {withRequestDeadline} from '../../../static/modules/api.js';
import {trainingBaseVersionFromAlgorithm, trainingDraftToRequest} from '../../../static/modules/training-draft.js';
import {
  benchmarkReuseContext, buildTrainingStartPayload, collectTrainingAdmissionBlockers,
  isCanonicalTrainingTaskId, supplementCandidateContext, validateTrainingCreatedResponse,
  validateTrainingDevice,
} from '../../../static/modules/training-submit.js';

export interface TrainingEngine {
  key: string;
  name?: string;
  short_name?: string;
  base_model?: string;
  default_epochs?: number;
  default_imgsz?: number;
  default_batch?: number;
}

export interface TrainingMotherModel {
  value: string;
  label?: string;
  model_status?: string;
  trainable?: boolean;
  downloadable?: boolean;
}

export interface TrainingTarget {
  id: string;
  name: string;
  type: string;
  framework: string;
  status: string;
  server_id?: string;
  scheduler_owned?: boolean;
  algorithms: TrainingEngine[];
  base_models: TrainingMotherModel[];
}

export interface TrainingRevision {
  repository_revision: number;
  annotation_revision: number;
  usage_revision: number;
  negative_pool_revision: number;
  negative_confirmation_revision: number;
}

export interface TrainingSelectionSummary {
  requested_count: number;
  matched_count: number;
  repository_revision: number;
  annotation_revision: number;
  eligible_count: number;
  pending_annotation_count: number;
  positive_label_codes: string[];
  label_counts: Record<string, number>;
  selection_reference: boolean;
  selection_validation?: TrainingRevision & {
    requested_count: number;
    eligible_count: number;
    excluded_count: number;
    unknown_count: number;
  };
}

export interface TrainingSelectionReference {
  selection_ref: string;
  count: number;
  role: string;
  history_policy: string;
}

export interface TrainingMaterialRow {
  selectable?: boolean;
  id: string;
  name?: string;
  filename?: string;
  thumbnail_url?: string;
  content_url?: string;
  annotation_state?: string;
  sample_role?: string;
  training_usage?: {state?: string; coverage?: string};
}

export interface TrainingMaterialPage {
  items: TrainingMaterialRow[];
  total: number | null;
  page: number;
  page_size: number;
  has_next: boolean;
  total_pages: number | null;
  repository_revision: number;
  annotation_revision: number;
  usage_revision: number;
}

export interface TrainingPreflight {
  ready: boolean;
  algorithm: TrainingAsset;
  drift_detected?: boolean;
  drift_fields?: string[];
}

export interface TrainingAsset extends AlgorithmSummary {
  versions?: (ModelVersion & {
    supplement_data_candidate_set?: {candidate_set_id: string; material_ids: string[]};
  })[];
}

export interface TrainingBenchmark {
  available: boolean;
  reason?: string;
  algorithm_id?: string;
  source_version_id?: string;
  source_version_name?: string;
  scope_id?: string;
  snapshot_id?: string;
  test_image_count?: number;
  binding_level?: string;
}

export interface TrainingNegativePreview {
  counts: Record<string, number>;
  pending_count: number;
  pending_scope_count?: number;
  coverage?: {partial_coverage_count?: number};
  base_training_mode?: string;
  proof_digest: string;
  pending_preview?: Record<string, unknown>[];
  preview_offset?: number;
}

export interface TrainingDevice {
  id: string;
  label: string;
  type: string;
  available: boolean;
}

function materialsPath(projectId: string) {
  return '/api/v62/projects/' + encodeURIComponent(projectId) + '/training-materials';
}

function algorithmPath(projectId: string, algorithmId: string) {
  return '/api/v12/projects/' + encodeURIComponent(projectId) + '/algorithms/' + encodeURIComponent(algorithmId);
}

function post<T>(url: string, payload: Record<string, unknown>, signal?: AbortSignal) {
  return request<T>(url, {method: 'POST', body: JSON.stringify(payload), signal});
}

export function loadTrainingOptions(projectId: string, signal?: AbortSignal) {
  return request<{targets: TrainingTarget[]}>('/api/training_options?' + new URLSearchParams({project_id: projectId}), {signal});
}

export function loadTrainingRecommendation(signal?: AbortSignal) {
  return request<{
    ok: boolean;
    worker_verified: boolean;
    recommendation_source: string;
    recommendation: {device: string; model: string; epochs: number; imgsz: number; batch: number; reason: string};
  }>('/api/system/recommendation', {signal});
}

export function loadTrainingDevices(signal?: AbortSignal) {
  return request<{options: TrainingDevice[]; recommended: string}>('/api/v62/training-devices', {signal});
}

export async function loadTrainingAsset(projectId: string, algorithmId: string, signal?: AbortSignal) {
  const result = await request<{ok: boolean; algorithm: TrainingAsset}>(algorithmPath(projectId, algorithmId), {signal});
  if (result.ok !== true || result.algorithm?.id !== algorithmId) throw new Error('训练算法响应身份不一致');
  return result.algorithm;
}

export function loadTrainingBenchmark(projectId: string, algorithmId: string, signal?: AbortSignal) {
  return request<TrainingBenchmark>(algorithmPath(projectId, algorithmId) + '/benchmark-reuse', {signal});
}

export async function checkTrainingPreflight(projectId: string, algorithmId: string, signal?: AbortSignal) {
  const query = new URLSearchParams({project_id: projectId, algorithm_id: algorithmId});
  const result = await request<TrainingPreflight>('/api/v63/external-algorithm-platform/training-preflight?' + query, {signal});
  if (result.ready !== true || result.algorithm?.id !== algorithmId) {
    throw new Error('训练算法不存在、已下架或当前没有可训练的视觉分析配置');
  }
  return result;
}

export function trainingMaterialRevision(projectId: string, algorithmId: string, signal?: AbortSignal) {
  const query = new URLSearchParams({algorithm_asset_id: algorithmId});
  return request<TrainingRevision>(materialsPath(projectId) + '/revision?' + query, {signal});
}

export function listTrainingMaterials(projectId: string, payload: Record<string, unknown>, signal?: AbortSignal) {
  return post<TrainingMaterialPage>(materialsPath(projectId) + ((payload.sample_role||payload.role_view) ? '/role-page' : '/page'), payload, signal);
}

export function summarizeTrainingSelection(projectId: string, payload: Record<string, unknown>, signal?: AbortSignal) {
  return post<TrainingSelectionSummary>(materialsPath(projectId) + '/selection-summary', payload, signal);
}

export function freezeTrainingSelection(projectId: string, payload: Record<string, unknown>, signal?: AbortSignal) {
  return post<TrainingSelectionReference>(materialsPath(projectId) + '/selection-reference', {...payload, role: 'train'}, signal);
}

export function trainingSelectionRequestId() {
  const bytes = crypto.getRandomValues(new Uint8Array(16));
  bytes[6] = (bytes[6] & 0x0f) | 0x40;
  bytes[8] = (bytes[8] & 0x3f) | 0x80;
  const hex = Array.from(bytes, value => value.toString(16).padStart(2, '0')).join('');
  return [hex.slice(0, 8), hex.slice(8, 12), hex.slice(12, 16), hex.slice(16, 20), hex.slice(20)].join('-');
}

export function combineTrainingSelections(projectId: string, payload: Record<string, unknown> & {
  request_id: string;
  expected_revisions: TrainingRevision;
}, signal?: AbortSignal) {
  return post<TrainingSelectionReference>(materialsPath(projectId) + '/selection-union',payload,signal);
}

export function selectionMembership(projectId: string, payload: Record<string, unknown>, signal?: AbortSignal) {
  return post<{items: string[]}>(materialsPath(projectId) + '/selection-membership', payload, signal);
}

export function trainingCompatibility<T = Record<string, unknown>>(projectId: string, payload: Record<string, unknown>, signal?: AbortSignal) {
  return post<T>(materialsPath(projectId) + '/compatibility', payload, signal);
}

export function previewTrainingNegatives(projectId: string, payload: Record<string, unknown>, signal?: AbortSignal) {
  return post<TrainingNegativePreview>(materialsPath(projectId) + '/negative-preview', payload, signal);
}

export function confirmTrainingNegatives(projectId: string, payload: Record<string, unknown>, proofDigest: string, signal?: AbortSignal) {
  return post<{confirmed_count: number; receipt_ids: string[]; selection_ref?:string; count?:number}>(materialsPath(projectId) + '/confirm-negatives', {
    ...payload, confirmed: true, proof_digest: proofDigest,
  }, signal);
}

const trainingRevisionKeys = ['repository_revision', 'annotation_revision', 'usage_revision', 'negative_pool_revision', 'negative_confirmation_revision'] as const;

export async function verifyTrainingSelection(
  projectId: string,
  payload: Record<string, unknown> & {algorithm_asset_id: string},
  expectedRevision: Partial<TrainingRevision>,
  expectedCount: number,
  signal?: AbortSignal,
) {
  const before = await trainingMaterialRevision(projectId, payload.algorithm_asset_id, signal);
  if (trainingRevisionKeys.some(key => expectedRevision[key] != null && expectedRevision[key] !== before[key])) {
    throw new Error('素材证据版本已变化，请刷新后重新选择');
  }

  const frozen = Boolean(payload.train_selection_ref);
  const summary = await summarizeTrainingSelection(projectId, {
    ...payload, summary_only: true, validate_selection: !frozen,
  }, signal);
  if (summary.requested_count !== expectedCount || summary.matched_count !== expectedCount ||
      summary.repository_revision !== before.repository_revision || summary.annotation_revision !== before.annotation_revision) {
    throw new Error('素材数量或版本已变化，请刷新后重新选择');
  }
  if (frozen) {
    if (summary.selection_reference !== true) throw new Error('服务器未确认冻结选择，请重新选择');
  } else {
    const validation = summary.selection_validation;
    if (!validation || validation.requested_count !== expectedCount || validation.eligible_count !== expectedCount ||
        validation.excluded_count !== 0 || (payload.role === 'test' && validation.unknown_count !== 0) ||
        trainingRevisionKeys.some(key => validation[key] !== before[key])) {
      throw new Error('所选素材资格或证据版本已变化，请刷新后重新选择');
    }
  }

  const after = await trainingMaterialRevision(projectId, payload.algorithm_asset_id, signal);
  if (trainingRevisionKeys.some(key => after[key] !== before[key])) {
    throw new Error('素材证据版本已变化，请刷新后重新选择');
  }
  return summary;
}

interface TrainingCreationReceipt {
  projectId: string;
  algorithmId: string;
  taskId: string;
}

const trainingCreationReceiptKey = (projectId: string, scope?: string) => 'training-create-pending:' + (scope || projectId);
const creationReceipts = new Map<string, TrainingCreationReceipt>();

export function pendingTrainingCreation(projectId: string, scope?: string): TrainingCreationReceipt | null {
  const key = trainingCreationReceiptKey(projectId, scope);
  const current = creationReceipts.get(key);
  if (current) return current;
  try {
    const raw = sessionStorage.getItem(key);
    if (raw === null) return null;
    const saved = JSON.parse(raw);
    if (saved?.projectId === projectId && typeof saved.algorithmId === 'string' && saved.algorithmId && isCanonicalTrainingTaskId(saved.taskId)) return saved;
  } catch {
    // A corrupt or unreadable receipt cannot prove the previous request absent.
  }
  throw new Error('训练创建回执不可读取，请核验训练任务后再继续');
}

function rememberTrainingCreation(receipt: TrainingCreationReceipt, scope?: string) {
  const key = trainingCreationReceiptKey(receipt.projectId, scope);
  sessionStorage.setItem(key, JSON.stringify(receipt));
  creationReceipts.set(key, receipt);
}

function clearTrainingCreation(receipt: TrainingCreationReceipt, scope?: string) {
  if (pendingTrainingCreation(receipt.projectId, scope)?.taskId !== receipt.taskId) return;
  const key = trainingCreationReceiptKey(receipt.projectId, scope);
  creationReceipts.delete(key);
  try { sessionStorage.removeItem(key); }
  catch { /* Session storage may be unavailable. */ }
}

async function postTrainingCreation(projectId: string, payload: Record<string, unknown>) {
  const url = '/api/v12/projects/' + encodeURIComponent(projectId) + '/train/start';
  return withRequestDeadline(async signal => {
    const response = await fetch(url, {
      method: 'POST', credentials: 'same-origin', signal,
      headers: {'Content-Type': 'application/json'}, body: JSON.stringify(payload),
    });
    const body = await response.json();
    if (response.ok) return body as unknown;
    const detail = body?.detail;
    const code = body?.code || detail?.code || body?.error?.code;
    const message = body?.message || detail?.message || body?.error?.message ||
      (typeof detail === 'string' ? detail : '');
    const definiteRejection = [400, 401, 403, 404, 409, 422].includes(response.status) &&
      typeof message === 'string' && Boolean(message.trim()) && code !== 'TRAINING_CREATE_IN_PROGRESS';
    throw Object.assign(new Error(message || '训练任务创建未获明确响应'), {definiteRejection});
  }, {mutation: true});
}

function validatedTask(body: unknown, receipt: TrainingCreationReceipt, persistedLookup = false) {
  const task = validateTrainingCreatedResponse(body, receipt.taskId, {...receipt, persistedLookup});
  if (persistedLookup && String(task.algorithm_id || task.algorithm_asset_id || '') !== receipt.algorithmId) {
    throw new Error('训练创建返回的算法身份不一致，请查询任务状态');
  }
  return task;
}

export async function recoverNativeTraining(projectId: string, signal?: AbortSignal, scope?: string) {
  const receipt = pendingTrainingCreation(projectId, scope);
  if (!receipt) return null;
  const url = '/api/v62/projects/' + encodeURIComponent(projectId) + '/tasks/' + encodeURIComponent(receipt.taskId) + '?reader_view=true';
  const body = await request<{task?: unknown}>(url, {signal});
  const task = validatedTask({ok: true, task: body.task || body}, receipt, true);
  clearTrainingCreation(receipt, scope);
  return task;
}

interface NativeTrainingSubmission {
  projectId: string;
  receiptScope?: string;
  asset: TrainingAsset;
  draft: Record<string, any>;
  target: TrainingTarget;
  engine: TrainingEngine;
  devices: TrainingDevice[];
  trainSummary: TrainingSelectionSummary;
  trainRevision?: Partial<TrainingRevision>;
  testSummary?: TrainingSelectionSummary;
  testRevision?: Partial<TrainingRevision>;
  backgroundConfirmed?: boolean;
  benchmark?: TrainingBenchmark;
  stillCurrent: () => boolean;
  signal?: AbortSignal;
  fixedPreview?: any;
  fixedRequestId?: string;
}

interface CompatibilityResult {
  compatible: boolean;
  skipped?: boolean;
  issue_count?: number;
  issue_counts?: Record<string, number>;
  material_revision: number;
  annotation_revision: number;
}

export async function submitNativeTraining(options: NativeTrainingSubmission) {
  const {
    projectId, receiptScope, asset, draft, target, engine, devices, trainSummary, trainRevision,
    testSummary, testRevision, backgroundConfirmed, benchmark, stillCurrent, signal, fixedPreview, fixedRequestId,
  } = options;
  const ensureCurrent = () => {
    if (signal?.aborted || !stillCurrent()) throw new DOMException('训练配置或窗口已变化，本次检查已取消', 'AbortError');
  };
  ensureCurrent();
  if (pendingTrainingCreation(projectId, receiptScope)) throw new Error('上次训练创建结果尚未确认，请先核验任务状态');
  if (asset.id !== draft.algorithmId || target.status !== 'ready' || !target.algorithms.some(row => row.key === engine.key)) {
    throw new Error('训练算法或训练资源已变化，请重新选择');
  }

  let fresh = await loadTrainingAsset(projectId, asset.id, signal);
  if (String(fresh.source_type).toUpperCase() === 'EXTERNAL' && String(fresh.provider_type).toUpperCase() === 'CHANG_LIAN') {
    fresh = (await checkTrainingPreflight(projectId, fresh.id, signal)).algorithm;
  }
  ensureCurrent();
  const base = trainingBaseVersionFromAlgorithm(fresh);
  if (base.blocked || base.versionId !== draft.baseVersionId) throw new Error('当前可训练版本已变化，请重新核对训练配置');
  validateTrainingDevice(draft, devices, target);
  const fixed = draft.splitMode === 'fixed_zip_train_val_test';
  const blockers = collectTrainingAdmissionBlockers({draft, base, target}).filter((row: {code:string}) => !fixed || row.code !== 'materials');
  if (blockers.length) throw new Error(blockers.map((row: {message: string}) => row.message).join('；'));

  const payload = buildTrainingStartPayload({draft, target, algorithm: engine, trainingDraftToRequest});
  const fixedTest = fixed ? null : benchmarkReuseContext({asset: fresh, draft, base, benchmark});
  if (fixedTest) {
    if (draft.testMaterialIds?.length) throw new Error('复用固定评测基准时不能同时选择独立试验素材');
    delete payload.test_image_ids;
    delete payload.experiment_percent;
    payload.benchmark_source_version_id = fixedTest.sourceVersionId;
    payload.benchmark_scope_id = fixedTest.scopeId;
  }
  const supplement = fixed ? null : supplementCandidateContext({asset: fresh, draft, base});
  if (supplement?.active) payload.supplement_candidate_set_id = supplement.candidateSetId;

  const selectionContext = {
    algorithm_asset_id: asset.id, base_version_id: payload.base_version_id, model: payload.model,
    framework: payload.framework, train_labels: payload.train_labels, history_policy: payload.history_policy,
  };
  if (fixed) {
    if (!fixedPreview?.preview_digest || !fixedRequestId) throw new Error('请先预览固定 ZIP 划分');
    const frozen = await post<any>(materialsPath(projectId) + '/zip-fixed-split-freeze', {...selectionContext, zip_source_job_ids:draft.zipSourceJobIds, review_all_training_backgrounds:!!backgroundConfirmed, preview_digest:fixedPreview.preview_digest, request_id:fixedRequestId}, signal);
    ensureCurrent();
    Object.assign(payload, frozen, {split_mode:'fixed_zip_train_val_test',validation_percent:null,experiment_percent:null,admission_mode:'background'});
    delete payload.train_image_ids; delete payload.test_image_ids;
  } else {
  const testIds = (draft.testMaterialIds || []) as string[];
  const trainIds = (draft.materialIds || []) as string[];
  const reference = String(draft.trainSelectionRef || '');
  const trainCount = reference ? Number(draft.trainSelectionCount) : trainIds.length;
  const evidence = (summary: TrainingSelectionSummary, revision?: Partial<TrainingRevision>) => ({
    repository_revision: summary.repository_revision, annotation_revision: summary.annotation_revision, ...revision,
  });
  const checkedTrain = await verifyTrainingSelection(projectId, {
    ...selectionContext, role: 'train', ...(reference ? {train_selection_ref: reference} : {image_ids: trainIds}),
  }, evidence(trainSummary, trainRevision), trainCount, signal);
  if (draft.duplicateReview && (draft.duplicateReview.material_revision !== checkedTrain.repository_revision || draft.duplicateReview.annotation_revision !== checkedTrain.annotation_revision)) throw new Error('重复素材排除的证据已变化，请重新诊断并确认排除');
  if (testIds.length) {
    if (!testSummary) throw new Error('独立试验素材尚未核验');
    await verifyTrainingSelection(projectId, {...selectionContext, role: 'test', image_ids: testIds},
      evidence(testSummary, testRevision), testIds.length, signal);
    if (reference) {
      for (let offset = 0; offset < testIds.length; offset += 100) {
        const members = await selectionMembership(projectId, {
          ...selectionContext, role: 'train', selection_ref: reference, image_ids: testIds.slice(offset, offset + 100),
        }, signal);
        if (members.items.length) throw new Error('训练素材与独立试验素材不能重复');
      }
    }
  }

  if (reference && !backgroundConfirmed) throw new Error('请明确确认冻结训练范围的后台核验');
  payload.expected_material_revision = checkedTrain.repository_revision;
  payload.expected_annotation_revision = checkedTrain.annotation_revision;
  if (!reference) {
    const compatibility = await trainingCompatibility<CompatibilityResult>(projectId, {...payload, limit: 50}, signal);
    if (compatibility.material_revision !== checkedTrain.repository_revision ||
        compatibility.annotation_revision !== checkedTrain.annotation_revision) {
      throw new Error('素材证据版本已变化，请刷新后重新选择');
    }
    const issueCodes = Object.entries(compatibility.issue_counts || {})
      .filter(([, count]) => count > 0).map(([code]) => code);
    const reviewableBackground = backgroundConfirmed && issueCodes.length &&
      issueCodes.every(code => code === 'missing_annotation' || code === 'partial_review_scope');
    if (!reviewableBackground) {
      const issues = collectTrainingAdmissionBlockers({draft, base, target, compatibility: {...compatibility, ready: true}});
      if (issues.length) throw new Error(issues.map((row: {message: string}) => row.message).join('；'));
      if (compatibility.compatible !== true && compatibility.skipped !== true) throw new Error('训练准入检查尚未明确通过');
    }
  }
  }
  if (backgroundConfirmed) {
    payload.admission_mode = 'background';
    payload.review_all_training_backgrounds = true;
  }
  ensureCurrent();
  if (pendingTrainingCreation(projectId, receiptScope)) throw new Error('上次训练创建结果尚未确认，请先核验任务状态');

  const taskId = 'train_' + Array.from(crypto.getRandomValues(new Uint8Array(16)), byte => byte.toString(16).padStart(2, '0')).join('');
  const receipt = {projectId, algorithmId: asset.id, taskId};
  payload.task_id = taskId;
  rememberTrainingCreation(receipt, receiptScope);
  try {
    const body = await postTrainingCreation(projectId, payload);
    const task = validatedTask(body, receipt);
    clearTrainingCreation(receipt, receiptScope);
    return task;
  } catch (error) {
    if ((error as {definiteRejection?: boolean})?.definiteRejection === true) {
      clearTrainingCreation(receipt, receiptScope);
      throw error;
    }
    try {
      const task = await recoverNativeTraining(projectId, undefined, receiptScope);
      if (task) return task;
    } catch {
      // A failed readback does not prove that the create request was rejected.
    }
    throw new Error('训练创建结果待核验，请查询任务 ' + taskId);
  }
}

export function fixedZipSources(projectId: string, offset: number, signal?: AbortSignal) { return request<any>(materialsPath(projectId) + '/zip-fixed-sources?' + new URLSearchParams({offset:String(offset),limit:'30'}), {signal}); }
export function previewFixedZip(projectId: string, body: any, signal?: AbortSignal) { return post<any>(materialsPath(projectId) + '/zip-fixed-split-preview', body, signal); }
