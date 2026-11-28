import {request} from '../app/http';
export interface ProjectLabel {
  class_id:number; code:string; display_name?:string; color?:string; hotkey?:string;
  aliases?:string[]; status?:string; active?:boolean;
  usage_images?:number; usage_boxes?:number; scope_images?:number; affected_images?:number;
}
export interface LabelFields {code:string;display_name:string;color:string;hotkey:string;aliases:string[]}
export interface LabelCatalog {ok:boolean;items:ProjectLabel[];governance?:ProjectLabel[]}
export interface LabelImpact {ok:boolean;source_labels:string[];positive_images:number;scope_images:number;boxes:number;affected_images:number}
const root=(projectId:string)=>`/api/v54/projects/${encodeURIComponent(projectId)}`;
export async function readLabels(projectId:string,signal:AbortSignal,usage=false){
  const result=await request<LabelCatalog>(usage?`${root(projectId)}/label-schema`:`/api/v12/projects/${encodeURIComponent(projectId)}/labels`,{signal});
  if(!result.ok||!Array.isArray(result.items)||result.items.some(row=>!Number.isSafeInteger(row.class_id)||!row.code))throw new Error('标签目录响应无效');
  return result;
}
export async function writeLabel(projectId:string,classId:number|null,fields:LabelFields){
  const base=`/api/projects/${encodeURIComponent(projectId)}/labels`;
  const result=await request<{ok:boolean}>(classId===null?base:`/api/v12/projects/${encodeURIComponent(projectId)}/labels/${classId}`,{
    method:classId===null?'POST':'PUT',body:JSON.stringify(classId===null?{label:fields.code,display_name:fields.display_name,color:fields.color,aliases:fields.aliases}:fields),
  });
  if(result.ok!==true)throw new Error('标签保存结果尚未确认');
}
export async function removeLabel(projectId:string,classId:number){
  const result=await request<{ok:boolean}>(`/api/v12/projects/${encodeURIComponent(projectId)}/labels/${classId}`,{method:'DELETE'});
  if(result.ok!==true)throw new Error('标签删除结果尚未确认');
}
export function previewLabelUnify(projectId:string,ids:number[],signal:AbortSignal){
  return request<LabelImpact>(`${root(projectId)}/labels/unify/preview`,{method:'POST',signal,body:JSON.stringify({source_class_ids:ids})});
}
export function createLabelUnify(projectId:string,ids:number[],target:string){
  return request<import('./material-batches').MaterialBatchTask>(`${root(projectId)}/labels/unify`,{method:'POST',body:JSON.stringify({source_class_ids:ids,target_label:target})});
}
