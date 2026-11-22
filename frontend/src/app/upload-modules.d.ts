declare module '*static/modules/uppy-image-view.js' {
  export interface ImageUppyEvent {
    type: string;
    totalFiles?: number;
    confirmedFiles?: number;
    uploadedCount?: number;
    failedCount?: number;
    chunkNumber?: number;
    chunkCount?: number;
    chunkSize?: number;
    loadedBytes?: number;
    totalBytes?: number;
    ratio?: number;
    response?: {batch_id?: string; uploaded?: unknown[]; failed?: unknown[]};
  }
  export interface ImageUppyUploadOptions {
    storageSourceId?: string;
    externalView?: boolean;
    beforeConfirmation?: () => boolean | Promise<boolean>;
    onEvent?: (event: ImageUppyEvent) => void;
    onCommitted?: (event: ImageUppyEvent & {files: File[]}) => void;
  }
  export interface ImageUploadRuntime {
    uploadFiles(files: File[], options?: ImageUppyUploadOptions): Promise<{
      totalFiles: number;
      confirmedFiles: number;
      uploaded: {id?: string; filename?: string}[];
      failed: {name?: string; filename?: string; reason?: string}[];
      batchIds: string[];
    } | null>;
  }
  export function mountImageUppyView(options: {
    target: HTMLElement;
    runtime: ImageUploadRuntime;
    projectId: string;
    getProjectId: () => string;
    storageSourceId?: string;
    retryNames?: string[] | null;
    beforeConfirmation?: (() => boolean | Promise<boolean>) | null;
    onEvent?: (event: ImageUppyEvent) => void;
    onFallback?: (error: unknown) => void;
  }): Promise<{uppy: unknown; destroy: () => void}>;
}

declare module '*static/modules/material-upload-runtime.js' {
  export interface UploadProgress {
    loadedBytes: number;
    totalBytes: number;
    ratio: number;
  }
  export interface UploadChunkContext {
    chunkIndex: number;
    chunkNumber: number;
    chunkCount: number;
    chunkSize: number;
    totalFiles: number;
    onTransfer: (progress: UploadProgress) => void;
  }
  export interface UploadEvent extends UploadChunkContext {
    type: string;
    confirmedFiles: number;
    uploadedCount: number;
    failedCount: number;
    response?: {batch_id?: string; uploaded?: unknown[]; failed?: unknown[]};
  }
  export function partitionMaterialFiles(files: File[] | ArrayLike<File>, options?: {
    maxFiles?: number; maxBytes?: number;
  }): File[][];
  export const DEFAULT_UPLOAD_CHUNK_SIZE: number;
  export const DEFAULT_UPLOAD_CHUNK_BYTES: number;
  export function uploadMaterialFilesSequentially(files: File[], options: {
    requestChunk: (chunk: File[], context: UploadChunkContext) => Promise<unknown>;
    onEvent?: (event: UploadEvent) => void;
    projectUploaded?: (item: {id?: string; filename?: string}) => {id?: string; filename?: string};
    maxFiles?: number;
    maxBytes?: number;
  }): Promise<{
    totalFiles: number;
    confirmedFiles: number;
    uploaded: {id?: string; filename?: string}[];
    failed: {name?: string; filename?: string; reason?: string}[];
    batchIds: string[];
    chunks: number;
  }>;
  export function requestMaterialChunkRecoverable(files: File[], options: {
    projectId: string;
    datasetId?: string;
    storageSourceId?: string;
    requestId?: string;
    onTransfer?: (progress: UploadProgress) => void;
    fetchImpl?: typeof fetch;
    sleep?: (ms: number) => Promise<void>;
    pollMs?: number;
    maxPolls?: number;
  }): Promise<unknown>;
  export class MaterialUploadInterruptedError extends Error {
    details?: {confirmedFiles?: number; uploaded?: unknown[]; failed?: unknown[]};
  }
}

declare module '*static/modules/uppy-zip-adapter.js' {
  import type {ZipImportRuntime} from '*static/modules/zip-import-runtime.js';
  export function mountUppyZipAdapter(options: {
    target: HTMLElement;
    runtime: ZipImportRuntime;
    projectId: string;
    loadUppy?: (target: HTMLElement) => Promise<unknown>;
    loadTimeoutMs?: number;
    onFallback?: (error?: unknown) => void;
    notify?: (message: string) => void;
  }): Promise<{uppy: unknown; destroy: () => void}>;
}

declare module '*static/modules/zip-import-runtime.js' {
  export interface ZipImportRuntime {
    getProjectId(): string;
    uploadBatch(input: unknown): Promise<unknown>;
    subscribeTransfers(listener: (event: Record<string, unknown>) => void): () => void;
    openTask(taskId: string): Promise<unknown>;
    cancelJob(taskId: string): Promise<unknown>;
    beforeModalClose(layer: HTMLElement): void;
    destroy(): void;
    [key: string]: unknown;
  }
  export function installZipImportRuntime(options: {
    getState?: () => Record<string, unknown>;
    projectId?: () => string;
    notify?: (message: string) => void;
    fetchImpl?: typeof fetch;
    pollMs?: number;
  }): ZipImportRuntime | null;
}

declare module '*static/modules/material-upload-session.js' {
  export interface UploadSessionRecord {
    projectId: string; owner: string; totalFiles: number; requestIds: string[]; batchIds: string[];
    status: string; failed: number; requestSeed: string; deferred: boolean;
    pendingDecision: number; confirmationState: string;
    createdAt: string; updatedAt: string; source: string; legacy: boolean; owned: boolean;
  }
  export function uploadSessionStorageKey(actorKey: string, projectId: string): string;
  export function uploadSessionLegacyKey(projectId: string): string;
  export function uploadIndexStorageKey(actorKey: string, projectId: string): string;
  export function uploadRequestIds(seed: string, chunkCount: number): string[];
  export function readOwnedUploadSession(options: {
    actorKey: string; projectId: string; storage?: Storage;
  }): {session: UploadSessionRecord | null; key: string; migrated: boolean; unowned?: UploadSessionRecord | null};
  export function isUploadSessionUnresolved(session: UploadSessionRecord | null): boolean;
  export function writeUploadSession(options: {
    actorKey: string; projectId: string; patch?: Partial<UploadSessionRecord>;
    storage?: Storage; protectCurrent?: boolean;
  }): {ok: boolean; session: UploadSessionRecord | null; indexed?: boolean};
  export function clearUploadSession(options: {
    actorKey: string; projectId: string; storage?: Storage;
  }): boolean;
  export function updateUploadIndex(options: {
    actorKey: string; projectId: string; id: string;
    patch?: Partial<UploadSessionRecord>; storage?: Storage;
  }): Promise<boolean>;
  export function withUploadIdentityLock<T>(options: {
    actorKey: string; projectId: string; wait?: boolean;
  }, work: () => Promise<T> | T): Promise<T>;
  export function isUploadSessionProtected(session: UploadSessionRecord | null): boolean;
  export function listUploadSessions(options: {
    actorKey: string; projectId: string; storage?: Storage;
  }): UploadSessionRecord[];
}

declare module '*static/modules/upload-confirmation.js' {
  export interface UploadConfirmationRuntime {
    open(value: {
      projectId: string; batchIds: string[]; totalFiles: number;
      failed?: {name?: string; reason?: string}[]; requestIds?: string[];
    }): Promise<boolean>;
    restoreForProject(projectId: string, options?: {autoOpen?: boolean}): Promise<boolean>;
    recordSession(value: Record<string, unknown>): Record<string, unknown> | null;
    mount(container?: HTMLElement): void;
    submit(decision: 'clean' | 'ready' | 'later' | 'smart'): Promise<boolean>;
    getSession(): Record<string, unknown> | null;
    destroy(): void;
  }
  export function installUploadConfirmationRuntime(options: {
    getState: () => Record<string, unknown>;
    api: (url: string, options?: RequestInit) => Promise<unknown>;
    getContainer: () => HTMLElement | null;
    previewImage?: (image: unknown) => void;
    notify?: (message: string) => void;
    storage?: Storage;
    document?: Document;
    window?: Window;
  }): UploadConfirmationRuntime;
  export function uploadSessionKey(projectId: string): string;
}
