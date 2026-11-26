import {request} from '../app/http';

export type MaterialBatchStatus =
  | 'QUEUED' | 'WAITING_RESOURCE' | 'RUNNING' | 'CANCEL_REQUESTED'
  | 'AWAITING_CONFIRMATION' | 'SUCCEEDED' | 'PARTIAL_SUCCESS' | 'FAILED'
  | 'CANCELLED' | 'BLOCKED_BY_ENVIRONMENT' | 'BLOCKED_BY_HARDWARE';

export interface MaterialDeletionPreview {
  plan_id: string;
  confirmation_credential: string;
  selected_count?: number;
  delete_count?: number;
  gt_count: number | null;
  current_test_count: number | null;
  historical_reference_count: number | null;
  active_reference_count: number | null;
  reference_diagnostics_state?: string;
  physical_retained_count: number;
  reclaimed_bytes: number;
  reclamation_state: string;
  preview_items?: unknown[];
}

export interface MaterialBatchSelection {
  scope: 'SELECTED' | 'CURRENT_PAGE' | 'FILTERED';
  image_ids?: string[];
  filters?: Record<string, unknown>;
  excluded_image_ids?: string[];
}

export interface MaterialBatchEstimate {
  supported: boolean;
  count: number;
  selection_spec: MaterialBatchSelection;
  deletion_preview?: MaterialDeletionPreview;
  error_code?: string;
  message?: string;
  operation?: string;
  dataset_revision?: string;
}

export interface MaterialBatchTask {
  id: string;
  task_id: string;
  project_id: string;
  operation: string;
  status: MaterialBatchStatus | string;
  persisted_status?: string;
  total?: number | null;
  processed?: number;
  succeeded?: number;
  failed?: number;
  logical_removed?: number;
  physical_retained?: number;
  reclaimed_bytes?: number | null;
  reclamation_state?: string | null;
  source_labels?: string[];
  target_label?: string;
  retire_sources_on_success?: boolean;
  changed_images?: number | null;
  changed_boxes?: number | null;
  log_available?: boolean;
  results_url?: string | null;
  target_dataset_id?: string;
  target_split?: string;
  error_examples?: {error?: string}[];
  created_at?: string;
  updated_at?: string;
  finished_at?: string | null;
}

export type MaterialBatchItemState = 'pending' | 'running' | 'succeeded' | 'failed';

export interface MaterialBatchItemResult {
  image_id: string;
  item_state: MaterialBatchItemState | string;
  item_error?: string | null;
  outcome?: string;
}

export interface MaterialBatchResults {
  items?: MaterialBatchItemResult[];
  succeeded_image_ids?: string[];
  next_cursor?: string | null;
}

const batchBase = (projectId: string) =>
  `/api/v62/projects/${encodeURIComponent(projectId)}/material-batches`;

export interface MaterialAssignmentRequest {
  operation: 'MOVE_DATASET' | 'CLASSIFY_SPLIT';
  selection_spec: MaterialBatchSelection;
  options: {dataset_id?: string; split?: string; dataset_revision?: string};
  request_id?: string;
}

export function estimateMaterialAssignment(project: string, packet: MaterialAssignmentRequest, signal: AbortSignal) {
  return request<MaterialBatchEstimate>(batchBase(project) + '/estimate', {
    method: 'POST', signal, body: JSON.stringify(packet),
  });
}

export function submitMaterialAssignment(project: string, packet: MaterialAssignmentRequest, signal: AbortSignal) {
  return request<MaterialBatchTask>(batchBase(project), {method: 'POST', signal, body: JSON.stringify(packet)});
}

export function readMaterialAssignment(project: string, id: string, signal: AbortSignal) {
  return request<MaterialBatchTask>(batchBase(project) + '/by-request/' + encodeURIComponent(id), {signal});
}

export function manageMaterialBatch(project: string, taskId: string, action: 'cancel' | 'retry', signal: AbortSignal) {
  return request<MaterialBatchTask>(batchBase(project) + '/' + encodeURIComponent(taskId) + '/' + action, {
    method: 'POST', signal,
  });
}

export function markMaterialsReady(projectId:string,selection:MaterialBatchSelection,signal:AbortSignal,estimate:true):Promise<MaterialBatchEstimate>;
export function markMaterialsReady(projectId:string,selection:MaterialBatchSelection,signal:AbortSignal,estimate:false):Promise<MaterialBatchTask>;
export function markMaterialsReady(projectId:string,selection:MaterialBatchSelection,signal:AbortSignal,estimate:boolean){
  const body=JSON.stringify({operation:'MARK_CLEAN_SKIPPED',selection_spec:selection,options:{}});
  const options={method:'POST',body,signal};
  return estimate
    ?request<MaterialBatchEstimate>(batchBase(projectId)+'/estimate',options)
    :request<MaterialBatchTask>(batchBase(projectId),options);
}

export function estimateMaterialDeletion(
  projectId: string, imageIds: string[], signal: AbortSignal,
) {
  return request<MaterialBatchEstimate>(`${batchBase(projectId)}/estimate`, {
    method: 'POST', signal,
    body: JSON.stringify({
      operation: 'DELETE_INDEX',
      selection_spec: {scope: 'SELECTED', image_ids: imageIds},
      options: {},
    }),
  });
}

export function createMaterialDeletion(
  projectId: string, estimate: MaterialBatchEstimate, signal: AbortSignal,
) {
  const preview = estimate.deletion_preview;
  if (!preview?.plan_id || !preview.confirmation_credential)
    throw new Error('删除预检身份不完整，请重新预检');
  return request<MaterialBatchTask>(batchBase(projectId), {
    method: 'POST', signal,
    body: JSON.stringify({
      operation: 'DELETE_INDEX',
      selection_spec: estimate.selection_spec,
      options: {
        deletion_plan_id: preview.plan_id,
        confirmation_credential: preview.confirmation_credential,
      },
    }),
  });
}

export function getMaterialBatch(projectId: string, taskId: string, signal: AbortSignal) {
  return request<MaterialBatchTask>(
    `${batchBase(projectId)}/${encodeURIComponent(taskId)}`, {signal},
  );
}

export function getMaterialBatchResults(
  projectId: string, taskId: string, signal: AbortSignal, cursor: string | null = null,
  limit = 100,
) {
  const query = new URLSearchParams({limit: String(limit)});
  if (cursor) query.set('cursor', cursor);
  return request<MaterialBatchResults>(
    `${batchBase(projectId)}/${encodeURIComponent(taskId)}/results?${query}`, {signal},
  );
}
