declare module '*static/modules/storage.js' {
  export const STORAGE_TYPE_LABELS: Readonly<Record<string, string>>;
  export function buildStorageSourcePayload(values: Record<string, unknown>): {
    name: string; type: string; config: Record<string, unknown>; enabled: boolean;
    credentials?: Record<string, string>;
  };
}
