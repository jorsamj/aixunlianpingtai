import type {FormalDecision, FormalReceipt, ReviewAddress} from '../api/ai-review';
import {validRevision} from './ai-review-decision';

export type FormalScope = ReviewAddress & {actorKey:string};
export interface FormalOperation {
  scope:FormalScope;
  body:FormalDecision;
  digest:string;
  receipt?:FormalReceipt;
}

export function formalKey({actorKey,projectId,taskId}:FormalScope){
  return 'ai-review-formal:v1:'+JSON.stringify([actorKey,projectId,taskId]);
}

// Claim and update the task's single recovery record across browser tabs.
export function withFormalStorage<T>(scope:FormalScope,signal:AbortSignal,action:()=>T){
  if(!navigator.locks)throw new Error('当前浏览器无法锁定正式入库恢复记录。');
  return navigator.locks.request(formalKey(scope),{signal},action);
}

export function formalBody(ids:string[],revision:number,requestId:string):FormalDecision{
  return {commit:true,commit_selected:true,single_candidate:false,accept_unmentioned:false,
    reject_unmentioned:false,label_mapping:{},review_revision:revision,request_id:requestId,
    decisions:ids.map(image_id=>({image_id,accepted:true}))};
}

export async function bodyDigest(scope:FormalScope,body:FormalDecision){
  if(!crypto.subtle)throw new Error('正式入库需要 HTTPS 或 localhost，以核验请求摘要。');
  const digest=await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify([formalKey(scope),body])));
  return Array.from(new Uint8Array(digest),byte=>byte.toString(16).padStart(2,'0')).join('');
}

export function matchesFormalReceipt(operation:FormalOperation, receipt:FormalReceipt){
  if(receipt?.request_id!==operation.body.request_id)return false;
  if(receipt.status==='pending'||receipt.status==='rejected')return true;
  if(receipt.status!=='completed')return false;
  const result=receipt.result, completed=result?.completed_image_ids;
  const ids=new Set(operation.body.decisions.map(row=>row.image_id));
  return result?.committed_selected===true&&result.queued_for_commit===false
    &&result.task?.project_id===operation.scope.projectId&&result.task?.id===operation.scope.taskId
    &&Array.isArray(completed)&&completed.length===ids.size
    &&new Set(completed).size===ids.size&&completed.every(id=>ids.has(id));
}

export async function loadFormalOperation(scope:FormalScope){
  const raw=localStorage.getItem(formalKey(scope));
  if(raw===null)return;
  const record=JSON.parse(raw) as FormalOperation;
  const body=record?.body;
  const ids=body?.decisions?.map(row=>row.image_id);
  if(!ids||!ids.length||ids.length>100||ids.some(id=>typeof id!=='string'||!id)
    ||new Set(ids).size!==ids.length||!validRevision(body.review_revision)
    ||typeof body.request_id!=='string'||!/^[A-Za-z0-9_-]{12,80}$/.test(body.request_id)
    ||formalKey(record.scope)!==formalKey(scope)
    ||JSON.stringify(body)!==JSON.stringify(formalBody(ids,body.review_revision,body.request_id))
    ||await bodyDigest(scope,body)!==record.digest
    ||(record.receipt&&!matchesFormalReceipt(record,record.receipt))){
    throw new Error('正式入库恢复记录无效，请核对后再操作。');
  }
  return record;
}

export async function readSelected<T>(ids:string[],read:(id:string)=>Promise<T>){
  const rows:T[]=[];
  for(let offset=0;offset<ids.length;offset+=4){
    rows.push(...await Promise.all(ids.slice(offset,offset+4).map(read)));
  }
  return rows;
}
