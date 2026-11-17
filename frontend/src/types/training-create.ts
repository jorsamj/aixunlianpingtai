export type TrainingFact = string | number | boolean | null | undefined;
export interface TrainingCreateSnapshot {
  projectId: string;
  algorithmId?: string;
  algorithmName?: string;
  taskId?: string;
  taskName?: string;
  step: number;
  trainingMode?: string;
  precision?: string;
  loading?: boolean;
  busy?: boolean;
  error?: string;
  status?: string;
  trainCount?: number | null;
  testCount?: number | null;
  frozenCount?: number | null;
  validationPercent?: number | null;
  experimentPercent?: number | null;
  splitMode?: string;
  baseVersionName?: string;
  model?: string;
  framework?: string;
  labels?: string[];
  resource?: {name?: string; status?: string; device?: string; detail?: string} | null;
  parameters?: {name: string; value: TrainingFact; source?: string}[];
  submit?: {state?: string; message?: string; requestId?: string} | null;
}
export interface TrainingCreateContext {
  signal: AbortSignal;
  snapshot(): TrainingCreateSnapshot;
  subscribe(listener: (snapshot: TrainingCreateSnapshot) => void): () => void;
  // Original live nodes, never cloned. All IDs, events and form state remain
  // owned by the original Draft/Label/Picker/Submit runtimes.
  slots: {steps: HTMLElement[]; footer: HTMLElement};
  actions: {
    step(value: number): unknown;
    submit(): unknown;
    close(): unknown;
    legacy(): unknown;
  };
}
