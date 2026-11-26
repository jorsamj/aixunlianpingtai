import {request} from '../app/http';

export interface IterationAddress {projectId:string;algorithmId:string;versionId:string}
export interface IterationAction {
  action_id:string;action:'continue_training'|'supplement_data';status:string;automatic_execution:boolean;
  source:{decision_id:string;evaluation_id:string;algorithm_id:string;version_id:string;dataset_revision_id:string;snapshot_id:string};
  training_draft?:{task_id?:string};
}
export interface IterationView {
  ok:boolean;project_id:string;algorithm_id:string;version_id:string;current_version_id:string;
  model_sha256:string;evaluation_id:string;
  decision:{decision_id?:string;decision?:string;weak_labels?:string[]};
  action:IterationAction|null;candidate_set:{candidate_set_id:string;material_ids:string[]}|null;
}
export interface MiningSample {image_id:string;filename?:string;content_sha256:string}
export interface ReviewedSample {image_id:string;eligible:boolean;reason?:string;input_sha256?:string;candidate_digest?:string}
export interface FeedbackSample {feedback_id:string;material_id?:string;eligible:boolean;reason_codes:string[];candidate_digest:string}
export interface IterationSource extends IterationAddress {actionId:string;evaluationId:string;candidateSetId:string}

const enc=encodeURIComponent;
const base=(version:IterationAddress,api='v12')=>`/api/${api}/projects/${enc(version.projectId)}/algorithms/${enc(version.algorithmId)}/versions/${enc(version.versionId)}`;
const write=<T>(url:string,data:unknown,signal:AbortSignal)=>request<T>(url,{method:'POST',body:JSON.stringify(data),signal});
export const isDigest=(s:unknown):s is string=>typeof s==='string'&&/^[a-f0-9]{64}$/.test(s);

export async function readIteration(address:IterationAddress,signal:AbortSignal){
  const value=await request<IterationView>(base(address)+'/evaluation/report?reader_view=true&section=iteration',{signal});
  if(value.ok!==true||value.project_id!==address.projectId||value.algorithm_id!==address.algorithmId||value.version_id!==address.versionId)
    throw new Error('迭代评测的算法或版本响应不一致');
  return value;
}
export function readTrainingSource(view:IterationView,source:IterationSource){
  const action=view.action;
  if(!action||view.current_version_id!==source.versionId||action.action_id!==source.actionId||
    action.status!=='confirmed'||action.automatic_execution!==false||!isDigest(view.model_sha256)||
    action.source.algorithm_id!==source.algorithmId||action.source.version_id!==source.versionId||
    action.source.decision_id!==view.decision.decision_id||action.source.evaluation_id!==view.evaluation_id||
    view.evaluation_id!==source.evaluationId)throw new Error('来源评测或确认动作已变化，请从评测重新进入');
  if(source.candidateSetId){
    if(action.action!=='supplement_data'||view.candidate_set?.candidate_set_id!==source.candidateSetId
      ||!view.candidate_set.material_ids.length||view.candidate_set.material_ids.length>500)
      throw new Error('冻结的补数范围已变化，请重新核验');
  }else if(action.action!=='continue_training'||!/^train_[a-f0-9]{24}$/.test(action.training_draft?.task_id||'')){
    throw new Error('原继续训练动作缺少可信固定任务 ID');
  }
  return action;
}
export function confirmIteration(address:IterationAddress, action:IterationAction['action'], decision_id:string, signal:AbortSignal){
  return write(base(address)+'/iteration-actions/confirm',{action,decision_id},signal);
}
export function loadMiningMaterials(address:IterationAddress,signal:AbortSignal){
  return request<{items:string[];display_items:MiningSample[]}>(base(address,'v64')+'/hard-sample-mining/eligible?limit=100',{signal});
}
export function startMining(address:IterationAddress,body:Record<string,unknown>,signal:AbortSignal){
  return write<{id:string;task_id?:string}>(base(address,'v64')+'/hard-sample-mining',body,signal);
}
export function readReviewed(address:IterationAddress,taskId:string,offset:number,signal:AbortSignal){
  return request<{ok:boolean;items:ReviewedSample[];has_more:boolean}>(base(address)+`/hard-sample-mining/${enc(taskId)}/reviewed?offset=${offset}&limit=24`,{signal});
}
export function adoptReviewed(address:IterationAddress,taskId:string,rows:{image_id:string;candidate_digest:string}[],signal:AbortSignal){
  return write(base(address)+`/hard-sample-mining/${enc(taskId)}/adopt`,{candidates:rows,confirmed:true},signal);
}
export function readFeedbackCandidates(address:IterationAddress,signal:AbortSignal){
  return request<{action_id:string;items:FeedbackSample[];truncated:boolean}>(base(address,'v63')+'/supplement-data-candidates',{signal});
}
export function freezeFeedbackCandidates(address:IterationAddress,rows:{feedback_id:string;candidate_digest:string}[],signal:AbortSignal){
  return write(base(address,'v63')+'/supplement-data-candidates/freeze',{candidates:rows},signal);
}
