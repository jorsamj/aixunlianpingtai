export interface MaterialImportTask {
  id: string;kind: string;title: string;status: string;stage: string;detail: string;
  progress: number|null;createdAt: string;updatedAt: string;localOnly: boolean;
  browserTransfer: boolean;resumeRequired: boolean;verificationReason: string;queuePosition: number|null;
}
export interface MaterialImportSnapshot {
  projectId: string;tasks: MaterialImportTask[];total: number;truncated: boolean;
  confirmationAvailable: boolean;busy: boolean;error: string;updatedAt: string;
  capabilities: {images: boolean;zip: boolean;confirmation: boolean;governance: boolean};
}
export interface MaterialImportGovernanceContext {
  projectId: string;signal: AbortSignal;snapshot():MaterialImportSnapshot;
  subscribe(listener:(snapshot:MaterialImportSnapshot)=>void):()=>void;
  actions: {images():unknown;zip():unknown;refresh():unknown;confirmation():unknown;
    task(id:string,action:'open'|'pause'|'resume'|'cancel'|'verify'):unknown;
    navigate(key:string):unknown};
}
