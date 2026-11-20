import {request} from '../app/http';
import type {AiEditorBox} from '../types/ai-editor';
import type {MaterialBox} from '../types/materials';

export const reviewFilters = [
  ['all', '全部'], ['clean_boxes', '有框 · 无歧义'], ['ambiguous', '有歧义'], ['zero', '零框'],
  ['failed', '失败'], ['committed', '已入库'], ['edited', '已修改'], ['rejected', '已拒绝'],
  ['transferred', '已转池'], ['blocked', '已阻断'], ['with_boxes', '全部有框'],
  ['low', '低置信度'], ['hard', '困难样本'], ['unreviewed', '未审核'], ['remaining', '待处理'],
] as const;
export type ReviewFilter = typeof reviewFilters[number][0];
export interface ReviewAddress {projectId:string;taskId:string}
export interface ReviewTask {
  id:string;project_id:string;name?:string;status:string;persisted_status?:string;
  error?:string;phase?:string;total_count?:number|null;generation_interruption_code?:string;
}
export interface ReviewCandidate {
  image_id:string;filename?:string;width?:number;height?:number;status:string;boxes?:MaterialBox[];
  source_content_sha256?:string;content_sha256?:string;original_boxes?:MaterialBox[];review_state?:string;gt_committed?:boolean;manual_review_required?:boolean;
  draft_revision?:number;accepted?:boolean|null;error?:string;error_code?:string;error_stage?:string;
  http_status?:number;attempt_count?:number;retry_suggestion?:string;review_scope?:string[];
  selection_member?:boolean;review_scope_policy?:string;missing_review_scope?:string[];draft?:{auto_resolution?:boolean};
  review_conflicts?:{labels?:string[];iou?:number}[];
}
export interface ReviewPage {
  items:ReviewCandidate[];total:number;next_cursor:string|null;review_revision:number;
  selection_stale?:boolean;summary:Partial<Record<string,number>>;task_error?:{message:string;code?:string;stage?:string};
}
export interface ReviewDiagnostics {
  image_id:string;status:string;diagnostics?:null|{model_name?:string;model?:string;provider?:string;adapter?:string;
    latency_ms?:number;status?:string;contract?:{coordinate_space?:string;coordinate_order?:string;output_protocol?:string};
    counts?:Partial<Record<'raw'|'invalid'|'threshold_filtered'|'nms_filtered'|'final',number>>};
}
const enc=encodeURIComponent;
const root=({projectId,taskId}:ReviewAddress)=>`/api/v60/projects/${enc(projectId)}/annotation-tasks/${enc(taskId)}`;
export const reviewPageSize=24;

export async function getReviewTask(scope:ReviewAddress, signal:AbortSignal) {
  const result=await request<{project_id:string;task:ReviewTask}>(root(scope)+'?reader_view=true',{signal});
  if(result.project_id!==scope.projectId||result.task?.project_id!==scope.projectId||result.task.id!==scope.taskId)
    throw new Error('审核任务与当前项目或任务编号不一致');
  return result.task;
}
export function getReviewPage(scope:ReviewAddress, filter:ReviewFilter, cursor:string|null, signal:AbortSignal, selectionId?:string) {
  const query=new URLSearchParams({filter,limit:String(reviewPageSize)});
  if(cursor!==null)query.set('cursor',cursor);
  if(selectionId)query.set('selection_id',selectionId);
  return request<ReviewPage>(root(scope)+'/candidates?'+query,{signal});
}
export interface ReviewSelection {
  selection_id:string;filter:ReviewFilter;purpose:'gt';review_revision:number;
  filtered_total:number;count:number;reasons:Record<string,number>;
}
export function freezeReviewSelection(scope:ReviewAddress, filter:ReviewFilter, revision:number, signal:AbortSignal) {
  return request<ReviewSelection>(root(scope)+'/review-selection',{
    method:'POST',body:JSON.stringify({filter,purpose:'gt',review_revision:revision}),signal,
  });
}
export async function getReviewCandidateDetail(scope:ReviewAddress, id:string, signal:AbortSignal) {
  const result=await request<{item:ReviewCandidate;review_revision:number}>(root(scope)+'/candidates/'+enc(id),{signal});
  if(result.item?.image_id!==id)throw new Error('候选图片身份不一致');
  return result;
}
export async function getReviewCandidate(scope:ReviewAddress, id:string, signal:AbortSignal) {
  return (await getReviewCandidateDetail(scope,id,signal)).item;
}
export async function getReviewDiagnostics(scope:ReviewAddress, id:string, signal:AbortSignal) {
  const result=await request<ReviewDiagnostics>(root(scope)+'/candidates/'+enc(id)+'/diagnostics',{signal});
  if(result.image_id!==id)throw new Error('诊断图片身份不一致');
  return result;
}

export interface ReviewLabel {code:string;class_id:number;display_name?:string}
export interface CandidateDraft {
  boxes:AiEditorBox[];revision:number;request_id:string;source_content_sha256?:string;
}
export async function getReviewLabels(projectId:string,signal:AbortSignal){
  const result=await request<{items:ReviewLabel[]}>(`/api/v12/projects/${enc(projectId)}/labels`,{signal});
  return result.items;
}
export async function saveReviewDraft(scope:ReviewAddress,imageId:string,draft:CandidateDraft,signal:AbortSignal){
  const result=await request<{image_id:string;revision:number}>(root(scope)+'/candidates/'+enc(imageId)+'/draft',{
    method:'PUT',body:JSON.stringify(draft),signal,
  });
  if(result.image_id!==imageId||result.revision!==draft.revision+1)
    throw new Error('草稿回执身份或版本不一致');
  return result;
}

export interface SingleDecision {
  single_candidate:true; decisions:[{image_id:string;accepted:boolean;review_scope?:string[]}];
  commit:false;commit_selected:false;accept_unmentioned:false;reject_unmentioned:false;
  label_mapping:Record<string,never>;request_id:string;review_revision:number;
}
export interface CompletedDecision {
  status:'completed';request_id:string;image_id:string;accepted:boolean;review_revision:number;
}
type PendingDecision={status:'pending';request_id:string};
type RejectedDecision={status:'rejected';request_id:string;detail?:string|{message?:string}};
export type DecisionReceipt=PendingDecision|RejectedDecision|{status:'completed';request_id:string;result:CompletedDecision};
export function sendSingleDecision(scope:ReviewAddress, body:SingleDecision, signal:AbortSignal) {
  return request<CompletedDecision|PendingDecision>(root(scope)+'/decisions',{
    method:'POST',body:JSON.stringify(body),signal,
  });
}
export function getDecisionReceipt(scope:ReviewAddress, requestId:string, signal:AbortSignal) {
  return request<DecisionReceipt>(root(scope)+'/decisions/by-request/'+enc(requestId),{signal});
}
