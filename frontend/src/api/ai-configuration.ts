import { request } from '../app/http';
import type { AiCreateModel, AiCreatePrompt } from './ai-annotation-create';

export interface ModelSettings {
  name: string;
  provider_type: string;
  provider_adapter: string;
  model_kind: string;
  model_name: string;
  base_url: string;
  detect_url: string;
  health_url: string;
  api_protocol: string;
  structured_output: string;
  coordinate_space: string;
  coordinate_order: string;
  coordinate_origin: string;
  coordinate_image_space: string;
  output_protocol: string;
  coordinate_contract_version: number;
  annotation_prompt_template: string;
  training_intervention_prompt: string;
  wevisone_label_queries?: Record<string, string> | null;
  default_for_annotation: boolean;
  default_for_training_ai: boolean;
  enabled: boolean;
  request_mode: string;
  image_field: string;
  prompt_field: string;
  threshold_field: string;
  headers_json?: Record<string, unknown> | null;
  remark: string;
}

export interface CoordinateEvidence {
  status: string;
  reason: string;
  receipt?: string;
  config_revision?: string;
  sample_sha256?: string;
}

interface Capacity { concurrency: number; evidence_status: string }
export interface ModelConfig extends AiCreateModel, Partial<Omit<ModelSettings, keyof AiCreateModel>> {
  has_api_key?: boolean;
  capabilities?: string[];
  protocol_warning?: string;
  resolved_api_protocol?: string;
  coordinate_validation?: CoordinateEvidence;
  last_test?: { status: string; checked_at?: string; code?: string };
  inference_capacity?: Capacity;
}

export interface PromptSettings {
  name: string;
  model_config_id: string;
  framework: string;
  task_type: string;
  save_format: string;
  labels: string[];
  threshold: number;
  prompt: string;
  remark: string;
  output_schema: string;
  overwrite: boolean;
}
export interface PromptConfig extends AiCreatePrompt, Partial<Omit<PromptSettings, keyof AiCreatePrompt>> {}

export interface DiagnosticResult {
  model?: string;
  latency_ms?: number;
  model_loaded?: boolean;
  parsed_boxes?: { x1: number; y1: number; x2: number; y2: number; label: string; confidence?: number }[];
  raw_preview?: string;
  coordinate_validation?: CoordinateEvidence;
  input_image_url?: string;
  image_width?: number;
  image_height?: number;
  geometry?: string;
  instances?: { label?: string; images?: Record<string, string> }[];
  images?: Record<string, string>;
}

const models = '/api/v35/model-configs';
const prompts = '/api/v35/prompt-templates';
const resource = (base: string, id: string) => `${base}/${encodeURIComponent(id)}`;

function mutate<T>(url: string, method: string, body?: unknown, signal?: AbortSignal, timeout?: number) {
  return request<T>(url, { method, signal, body: body === undefined ? undefined : JSON.stringify(body) }, timeout);
}

export const readModels = (signal: AbortSignal) => request<{ items: ModelConfig[] }>(models, { signal });
export const readPrompts = (signal: AbortSignal) => request<{ items: PromptConfig[] }>(prompts, { signal });
export const saveModel = (id: string, body: ModelSettings & { api_key?: string }, signal: AbortSignal) =>
  mutate<ModelConfig>(id ? resource(models, id) : models, id ? 'PUT' : 'POST', body, signal);
export const setModelAvailability = (id: string, enabled: boolean, signal: AbortSignal) =>
  mutate<ModelConfig>(resource(models, id) + '/availability', 'PATCH', { enabled }, signal);
export const savePrompt = (id: string, body: PromptSettings, signal: AbortSignal) =>
  mutate<PromptConfig>(id ? resource(prompts, id) : prompts, id ? 'PUT' : 'POST', body, signal);
export const deletePrompt = (id: string, signal: AbortSignal) =>
  mutate<{ ok: boolean }>(resource(prompts, id), 'DELETE', undefined, signal);
export const testModel = (id: string, signal: AbortSignal) =>
  mutate<DiagnosticResult>(resource(models, id) + '/test-annotation', 'POST', undefined, signal, 190000);
export const inspectCapacity = (id: string, signal: AbortSignal) =>
  mutate<{ policy: Capacity; message: string }>(resource(models, id) + '/capacity-check', 'POST', undefined, signal);
export const verifyCoordinates = (id: string, body: { image_base64: string; labels: string[]; operation: string }, signal: AbortSignal) =>
  mutate<DiagnosticResult>(resource(models, id) + '/verify-coordinates', 'POST', body, signal, 190000);
export const confirmCoordinates = (id: string, receipt: string, config_revision: string, sample_sha256: string, signal: AbortSignal) =>
  mutate<ModelConfig>(resource(models, id) + '/confirm-coordinates', 'POST',
    { receipt, config_revision, sample_sha256, positions_confirmed: true }, signal);
