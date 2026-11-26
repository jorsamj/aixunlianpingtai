export interface AiAnnotationCreateSnapshot {
  projectId: string;
  step: number;
  taskName?: string;
  modelName?: string;
  providerName?: string;
  inferenceProtocol?: 'wevisone_detection' | 'generic_prompt' | 'unknown';
  labelCodes?: string[];
  selectedCount?: number | null;
  confirmedCount?: number | null;
  selectionRef?: string;
  frozenCount?: number | null;
  excludedCount?: number | null;
  referenceCount?: number | null;
  threshold?: number | null;
  detectionQueries?: {code: string; query: string; source?: string}[];
  busy?: boolean;
  loading?: boolean;
  error?: string;
  status?: string;
  confirmationReady?: boolean;
  pending?: {requestId?: string; state?: string; message?: string} | null;
}
export interface AiAnnotationCreateContext {
  signal: AbortSignal;
  snapshot(): AiAnnotationCreateSnapshot;
  subscribe(listener: (snapshot: AiAnnotationCreateSnapshot) => void): () => void;
  // Original live controls retain their IDs/events and authoritative state.
  // The runtime restores these same nodes after presentation is released.
  slots?: {
    configuration: HTMLElement;
    materials: HTMLElement;
    advanced?: HTMLElement;
    hydration?: HTMLElement;
    confirmation: HTMLElement;
    footer: HTMLElement;
    recovery?: HTMLElement;
  };
  actions: {step(value: number): unknown; close(): unknown; legacy(): unknown};
}
