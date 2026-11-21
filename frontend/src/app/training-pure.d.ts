declare module '*static/modules/training-draft.js' {
 export function trainingConfigurationDefaults():any;
 export function createTrainingDraft(values?:any):any;
 export function trainingInheritedDefaults(algorithm?:any):any;
 export function trainingBaseVersionFromAlgorithm(algorithm?:any):any;
 export function trainingDraftToRequest(draft:any,parameters?:any):any;
}
declare module '*static/modules/training-submit.js' {
 export function benchmarkReuseContext(options?:any):any;
 export function collectTrainingAdmissionBlockers(options?:any):any;
 export function isCanonicalTrainingTaskId(value:any):boolean;
 export function supplementCandidateContext(options?:any):any;
 export function validateTrainingDevice(draft:any,devices?:any[],target?:any):any;
 export function trainingModePreset(mode:string,hasPrevious?:boolean):any;
 export function buildTrainingStartPayload(options:any):any;
 export function validateTrainingCreatedResponse(body:any,taskId?:string,identity?:any):any;
}

declare module '*static/modules/training-material-summary-runtime.js' {
 export function removeResolvedTrainingMaterials(runtime:any,draft:any,imageIds:any[],diagnosis?:any):any;
}
