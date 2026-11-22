import {request} from '../app/http';

export interface UploadBatchReceipt {
  id: string;
  project_id?: string;
  upload_request_status?: string;
  upload_request_error?: string | null;
  upload_material_total?: number;
  upload_elapsed_seconds?: number;
  items?: {image_id?: string; image?: {id?: string; filename?: string}; missing?: boolean}[];
  upload_failed?: {name?: string; filename?: string; reason?: string}[];
  upload_request_manifest?: unknown[];
}

export function getUploadBatchReceipt(
  projectId: string, requestId: string, signal: AbortSignal,
) {
  return request<UploadBatchReceipt>(
    `/api/v55/projects/${encodeURIComponent(projectId)}/upload-batches/${encodeURIComponent(requestId)}`,
    {signal},
  );
}

export function projectLabels(projectId: string, signal: AbortSignal) {
  return request<{
    id?: string;
    labels?: {code: string; display_name?: string; name?: string}[];
    project?: {id: string; labels?: {code: string; display_name?: string; name?: string}[]};
  }>(`/api/projects/${encodeURIComponent(projectId)}`, {signal});
}
