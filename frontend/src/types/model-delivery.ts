export interface DeliveryAsset {
  fileName?: string;
  target?: string;
  artifactId?: string;
  weightId?: string;
  status?: string;
  storageStatus?: string;
  role?: string;
  reviewRequired?: boolean;
  identityStatus?: string;
  sizeBytes?: number | null;
  sha256?: string;
  computePlatformId?: string;
  chipCode?: string;
  metadataStatus?: string;
  note?: string;
  lastError?: string;
  metadata?: {width?: number; height?: number; yoloVersion?: string; tags?: string[] | null};
  frozenTags?: string[] | null;
  localTags?: string[] | null;
  preparedTags?: string[] | null;
  requestTags?: string[] | null;
  confirmedTags?: string[] | null;
  remoteTags?: string[] | null;
  remoteTagsStatus?: string;
}
export interface ModelDeliverySnapshot {
  projectId: string;
  algorithmId: string;
  versionId: string;
  algorithmName?: string;
  versionName?: string;
  mode?: string;
  busy?: string | boolean;
  error?: string;
  message?: string;
  uncertain?: boolean;
  awaitingReadback?: boolean;
  preflight?: {ready: boolean; message?: string};
  canPublish?: boolean;
  requiresSync?: boolean;
  versionStatus?: string;
  weightStatus?: string;
  current: DeliveryAsset[];
  historical: DeliveryAsset[];
  currentTotal?: number;
  historicalTotal?: number;
  truncated?: boolean;
}
export interface ModelDeliveryContext {
  signal: AbortSignal;
  snapshot(): ModelDeliverySnapshot;
  subscribe(listener: (snapshot: ModelDeliverySnapshot) => void): () => void;
  actions: {
    refresh(): unknown;
    publish(): unknown;
    close(): unknown;
    legacy(): unknown;
    configure?(): unknown;
    storage?(): unknown;
  };
}
