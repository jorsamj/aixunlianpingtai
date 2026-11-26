import {request} from '../app/http';
import type {MaterialBox} from '../types/materials';
import type {AiTask} from '../types/ai-tasks';

export interface AiCreateModel {id:string;name?:string;model_name?:string;provider_type?:string;provider_adapter?:string;enabled?:boolean;prompt_template_id?:string;default_for_annotation?:boolean;annotation_prompt_template?:string;wevisone_label_queries?:Record<string,string>}
export interface AiCreatePrompt {id:string;name:string;prompt?:string;enabled?:boolean;version?:number;model_config_id?:string;labels?:string[]}
export interface AiCreateBody {
  image_ids:string[];selection_ref?:string;excluded_image_ids?:string[];source_batch_id?:string;
  labels_text:string;reference_image_ids:string[];threshold:number;overwrite:boolean;task_name:string;
  model_config_id:string;prompt_template_id:string|null;prompt_override:string;business_instruction:string;
  request_id?:string;
}
export interface SelectionInput {image_ids:string[];previous_ref?:string;excluded_image_ids:string[]}
interface Summary {count:number;state_counts:Record<string,number>;repository_revision:number}
export interface CreatePreview {
  image:{id:string;filename:string;width:number;height:number};boxes:MaterialBox[];
  preview_only:boolean;latency_ms:number;
}
const root=(project:string)=>`/api/v60/projects/${encodeURIComponent(project)}`;
function post<T>(url:string,body:unknown,signal?:AbortSignal){
  return request<T>(url,{method:'POST',body:JSON.stringify(body),signal});
}
export function aiCreateInputs(signal:AbortSignal){
  return Promise.all([
    request<{items:AiCreateModel[]}>('/api/v35/model-configs',{signal}),
    request<{items:AiCreatePrompt[]}>('/api/v35/prompt-templates',{signal}),
  ]);
}
export function renderAiPrompt(input:{prompt:string;labels:{code:string;display_name_zh:string}[];image_width:number;image_height:number;business_instruction:string},signal:AbortSignal){
  return post<{rendered_prompt:string}>('/api/v35/prompt-templates/preview',input,signal);
}
export async function freezeAiMaterials(project:string,filters:{query:string;labels:string[];annotation_state:string|null},current:SelectionInput,signal:AbortSignal){
  const result=await post<Summary&{selection_ref:string}>(root(project)+'/annotation-selections',{...filters,...current},signal);
  if(!result.selection_ref||!Number.isSafeInteger(result.count)||result.count<1)throw new Error('未取得有效的冻结范围');
  return result;
}
export function summarizeAiMaterials(project:string,current:SelectionInput,signal:AbortSignal){
  return post<Summary>(root(project)+'/annotation-selections/summary',current,signal);
}
export async function aiMaterialMembership(project:string,ref:string,ids:string[],signal:AbortSignal){
  const result=await post<{items:string[]}>(root(project)+'/annotation-selections/membership',{selection_ref:ref,image_ids:ids},signal);
  if(!Array.isArray(result.items)||result.items.some(id=>!ids.includes(id)))throw new Error('冻结范围成员响应无效');
  return result.items;
}
export async function previewAiImage(project:string,body:AiCreateBody,id:string,signal:AbortSignal){
  const {labels_text,model_config_id,prompt_template_id,prompt_override,business_instruction,threshold,reference_image_ids,overwrite}=body;
  const result=await request<CreatePreview>(root(project)+'/annotation-preview',{method:'POST',signal,
    body:JSON.stringify({image_ids:[id],labels_text,model_config_id,prompt_template_id,prompt_override,business_instruction,
      threshold,overwrite,...(reference_image_ids.length?{reference_image_ids}:{})})},190000);
  if(result.preview_only!==true||result.image?.id!==id||!Array.isArray(result.boxes))throw new Error('试跑结果与所选素材不一致');
  return result;
}
function checkedTask(task:AiTask,project:string){
  if(!task.id||task.project_id!==project)throw new Error('创建回执任务或项目身份不一致');
  return task;
}
export async function createAiTask(project:string,body:AiCreateBody){
  return checkedTask(await post<AiTask>(root(project)+'/annotation-tasks',body),project);
}
export async function readAiCreateReceipt(project:string,id:string,signal:AbortSignal){
  return checkedTask(await request<AiTask>(root(project)+'/annotation-tasks/by-request/'+encodeURIComponent(id),{signal,cache:'no-store'}),project);
}
