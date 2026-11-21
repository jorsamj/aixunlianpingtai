export type ConversionFact = string | number | boolean | null | undefined;
export interface ConversionCreateSnapshot {
  projectId: string;
  algorithmId?: string;
  versionId?: string;
  sourceName?: string;
  algorithmName?: string;
  versionName?: string;
  sourceReady?: boolean | null;
  catalogState?: string;
  resourcesCurrent?: boolean | null;
  target?: string;
  precision?: string;
  inputSize?: string | number | null;
  resourceName?: string;
  resourceStatus?: string;
  sdkVersion?: string;
  chip?: string;
  busy?: boolean;
  error?: string;
  status?: string;
  contractReady?: boolean | null;
  contractErrors?: string[];
  parameters?: {name: string; value: ConversionFact; source?: string}[];
  pending?: {requestId?: string; state?: string; message?: string} | null;
  artifactStatus?: string;
  numericStatus?: string;
  hardwareStatus?: string;
  publicationStatus?: string;
}
export interface ConversionCreateContext {
  signal: AbortSignal;
  snapshot(): ConversionCreateSnapshot;
  subscribe(listener: (snapshot: ConversionCreateSnapshot) => void): () => void;
  // Sole original live controls: never clone, rebuild, or bind Vue models to them.
  slots: {body: HTMLElement; footer?: HTMLElement};
  actions: {close(): unknown; legacy(): unknown};
}
