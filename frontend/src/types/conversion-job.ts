// Native conversion task projections. Every field below already exists on the
// existing v39 conversion API; this file only describes those responses and
// never becomes a second conversion/admission owner.
export type ConversionFact = string | number | boolean | null | undefined;

export interface ConversionAdvancedField {
  key: string;
  label: string;
  type: 'number' | 'text' | 'checkbox' | string;
  default?: ConversionFact;
  locked?: boolean;
}

export interface ConversionTemplate {
  id: string;
  name: string;
  adapter: string;
  version?: number;
  implemented?: boolean;
  default_precision?: string;
  advanced_fields?: ConversionAdvancedField[];
}

export interface ConversionCatalogVendor {
  id: string;
  name: string;
  template_id: string;
  enabled?: boolean;
}

export interface ConversionCatalogChip {
  id: string;
  vendor_id: string;
  name: string;
  code?: string;
  sdk_code?: string;
  enabled?: boolean;
  constraint_id?: string;
}

export interface ConversionChipCapabilityResource {
  resource_id?: string;
  resource_name?: string;
  status?: string;
  status_label?: string;
  detection_state?: string;
  last_checked_at?: string;
  errors?: string[];
  message?: string;
}

export interface ConversionChipCapability {
  sdk_ready?: boolean;
  status?: string;
  status_label?: string;
  allowed_precisions?: string[];
  errors?: string[];
  resources?: ConversionChipCapabilityResource[];
  constraint_id?: string;
}

export interface ConversionCscCapability {
  target?: string;
  capability?: string;
  presets?: string[];
  input_formats?: string[];
  modes?: string[];
  embedded_supported?: boolean;
  execution_location?: string;
  device_observed?: string;
  board_verification?: string;
}

export interface ConversionCatalog {
  ok?: boolean;
  vendors: ConversionCatalogVendor[];
  chips: ConversionCatalogChip[];
  templates: ConversionTemplate[];
  revision?: unknown;
  chip_capabilities?: Record<string, ConversionChipCapability>;
  csc_capabilities_by_target?: Record<string, ConversionCscCapability>;
  constraint_ids?: string[];
}

export interface DeployResourceDetection {
  state?: string;
  checked_at?: string;
  reason?: string;
  error?: string;
  run_id?: string;
}

export interface DeployResource {
  id: string;
  name?: string;
  kind?: string;
  mode?: string;
  status?: string;
  targets?: string[];
  supported_chips?: string[];
  supported_precisions?: string[];
  detection?: DeployResourceDetection | null;
  message?: string;
  solution?: string;
  version?: string;
  builtin?: boolean;
  base_url?: string;
  has_api_key?: boolean;
  python_path?: string;
  ultralytics_python?: string;
  paddledet_dir?: string;
  paddle2onnx_path?: string;
  tool_root?: string;
  trtexec_path?: string;
  atc_path?: string;
  env_script?: string;
  remark?: string;
  last_checked_at?: string;
  agent_nodes?: {node_id?:string;display_name?:string}[];
}

export interface ConversionSource {
  id: string;
  kind?: string;
  name?: string;
  label?: string;
  path?: string;
  type?: string;
  framework?: string;
  size_mb?: number;
  job_id?: string;
  algorithm_id?: string;
  algorithm_name?: string;
  version_id?: string;
  version_name?: string;
  is_current_version?: boolean;
}

export interface ConversionChipOption {
  id: string;
  name: string;
  enabled?: boolean;
  status?: string;
  status_label?: string;
  reason?: string;
}

export interface ConversionContractResult {
  ready: boolean;
  status: string;
  errors?: string[];
  params?: Record<string, unknown>;
  parameter_sources?: Record<string, string>;
  chip_options?: ConversionChipOption[];
  template?: ConversionTemplate;
  allowed_precisions?: string[];
  precision_adjusted?: boolean;
  precision_adjustment_reason?: string;
  calibration_required?: boolean;
  csc_capabilities?: ConversionCscCapability;
  resource_detection?: DeployResourceDetection;
  source_input_shapes?: number[][];
  source_metadata?: Record<string, unknown>;
}

export interface ConversionJobRequest {
  source_id: string;
  target: string;
  resource_id: string;
  params: Record<string, unknown>;
  dataset_id?: string;
  calibration_split?: string;
  calibration_count?: number;
  request_id?: string;
}

export interface ConversionJobOutput {
  name?: string;
  path?: string;
  rel?: string;
  size_bytes?: number;
  size_mb?: number;
  sha256?: string;
  validation_status?: string;
}

export interface ConversionDeliveryArtifact {
  artifact_id?: string;
  target?: string;
  file_name?: string;
  sha256?: string;
  formal_activation_eligible?: boolean;
  present_as_formal_activation?: boolean;
  delivery_presentation?: string;
  hardware_acceptance?: string;
  present_as_hardware_accepted?: boolean;
  attachment_delivery_allowed?: boolean;
  numeric_status_alone_is_sufficient?: boolean;
  code?: string;
  reasons?: string[];
}

export interface ConversionUnregisteredOutput {
  name?: string;
  rel?: string;
  sha256?: string;
  archive_download_allowed?: boolean;
  delivery_presentation?: string;
  formal_activation_eligible?: boolean;
  hardware_acceptance?: string;
}

// Read-only delivery/quality projection computed by the backend on every job
// read (app.py `_conversion_delivery_quality_projection`). Absent fields are
// rendered as NOT_VERIFIED, never as a pass.
export interface ConversionDeliveryQuality {
  schema?: string;
  conversion_job_id?: string;
  project_id?: string;
  dry_run?: boolean;
  device_calls?: boolean;
  external_platform_calls?: boolean;
  numeric_status_alone_is_sufficient?: boolean;
  hardware_verified?: boolean;
  hardware_acceptance?: string;
  present_as_hardware_accepted?: boolean;
  archive_download_allowed?: boolean;
  attachment_delivery_allowed?: boolean;
  formal_activation_eligible?: boolean;
  present_as_formal_activation?: boolean;
  delivery_presentation?: string;
  artifacts?: ConversionDeliveryArtifact[];
  unregistered_outputs?: ConversionUnregisteredOutput[];
  reasons?: string[];
}

export interface ConversionNumericValidation {
  verification_id?: string;
  request_verification_id?: string;
  status?: string;
  verdict?: string;
  raw_verdict?: string;
  detection_status?: string;
  sample_count?: number;
  protocol?: string;
  hardware_verified?: boolean;
  ground_truth_used?: boolean;
  completed_at?: string;
  result_ref?: string;
  evidence_ref?: string;
  content_digest?: string;
  identity_digest?: string;
  identity_status?: string;
  binding_status?: string;
  stale_reason?: string;
  error?: string;
  summary?: Record<string, unknown>;
  parameters?: Record<string, unknown>;
  sample_set?: Record<string, unknown>;
  identity?: Record<string, unknown>;
}

export interface ConversionNumericHistoryEntry {
  id: string;
  conversion_job_id: string;
  created_at?: string;
  task: {task_id:string; project_id:string; kind:string; status?:string; phase?:string; error?:string};
  result: ConversionNumericValidation | null;
}

// One conversion job exactly as `GET /api/v39/projects/{p}/deploy/jobs/{id}`
// returns it, including the read-only `delivery_quality` projection.
export interface ConversionJobDetail {
  id: string;
  project_id?: string;
  source_id?: string;
  source_name?: string;
  target?: string;
  target_name?: string;
  status?: string;
  stage?: string;
  progress?: number;
  message?: string;
  error?: string;
  error_code?: string;
  solution?: string;
  task_id?: string;
  task_status?: string;
  durable_status?: string;
  cancel_requested?: boolean;
  worker_id?: string;
  resource_id?: string;
  resource?: { id?: string; name?: string; kind?: string; mode?: string };
  dataset_id?: string;
  calibration_split?: string;
  params?: Record<string, unknown>;
  requested_params?: Record<string, unknown>;
  source_trace?: Record<string, unknown>;
  source_meta?: Record<string, unknown>;
  outputs?: ConversionJobOutput[];
  conversion_status?: string;
  validation_status?: string;
  runtime_verified?: boolean;
  hardware_verified?: boolean;
  hardware_verification?: Record<string, unknown>;
  numeric_status?: string;
  publication_status?: string;
  numeric_validation?: ConversionNumericValidation;
  manifest_path?: string;
  manifest_digest?: string;
  manifest_integrity?: Record<string, unknown>;
  source_sha256_recheck?: string;
  execution_evidence?: Record<string, unknown>;
  created_at?: string;
  updated_at?: string;
  started_at?: string;
  finished_at?: string;
  delivery_quality?: ConversionDeliveryQuality;
  [key: string]: unknown;
}
