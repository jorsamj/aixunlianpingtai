import {request} from '../app/http';
import type {MaterialBatchTask} from './material-batches';

export interface CleaningTask {
  id:string; name:string; status:string; status_text?:string; stage?:string;
  progress:number; processed_images:number; total_images:number; flagged_images:number;
  created_at?:string; finished_at?:string; current_item?:string; worker_id?:string;
  resource_wait_reason?:string; execution_mode?:string;
  resource_queue_position?:number;resource_queue_position_exact?:boolean;
}
export interface CleaningRuntime {
  selected_count:number; agent_available:boolean; reason?:string;
  eligible_nodes?:{node_id:string; display_name?:string; name?:string; idle?:boolean; preemptible?:boolean}[];
  label_counts?:Record<string,{images:number}>;
}
export interface CleaningIssue { code?:string; name?:string; message?:string }
export interface CleaningItem {
  image_id:string; name?:string; filename?:string; url?:string; status?:string;
  item_state?:string; item_error?:string; issues?:CleaningIssue[]; suggest_delete?:boolean;
}
export interface CleaningAudit {
  enabled?:boolean; audited_images?:number; review_images?:number; warning_count?:number;
  issue_counts?:Record<string,number>; provenance_counts?:Record<string,number>;
  class_balance?:{label:string; count?:number; share?:number}[];
  heatmap?:{cells?:number[]}; items?:CleaningItem[];
}
export interface CleaningResult { task:CleaningTask; result:{items:CleaningItem[]; annotation_audit?:CleaningAudit} }

export function cleaningApi(projectId:string, signal:AbortSignal) {
  const root='/api/v47/projects/'+encodeURIComponent(projectId);
  const tasks=root+'/clean-tasks';
  const task=(id:string)=>tasks+'/'+encodeURIComponent(id);
  const post=<T>(url:string,body?:object)=>request<T>(url,{
    method:'POST', signal, ...(body===undefined?{}:{body:JSON.stringify(body)}),
  });
  return {
    list:()=>request<{items:CleaningTask[]}>(tasks,{signal}),
    preflight:(selection:object)=>post<CleaningRuntime>(root+'/clean-runtime/preflight',selection),
    create:(body:object)=>post<CleaningTask>(tasks,body),
    result:(id:string)=>request<CleaningResult>(task(id)+'/result',{signal}),
    audit:(id:string,page:number)=>request<CleaningAudit>(task(id)+'/annotation-audit?page='+page+'&page_size=20',{signal}),
    stop:(id:string)=>post<{ok:boolean}>(task(id)+'/stop'),
    retry:async(id:string)=>{
      const value=await post<MaterialBatchTask>('/api/v62/projects/'+encodeURIComponent(projectId)+'/material-batches/'+encodeURIComponent(id)+'/retry');
      if(value.task_id!==id||value.project_id!==projectId||value.operation!=='CLEAN')throw new Error('清洗重试回执身份不一致');
      return value;
    },
    confirm:(id:string,excluded:string[])=>post<{ok:boolean; processed_ids:string[]}>(
      task(id)+'/confirm',{delete_ids:[],skip_image_ids:excluded}),
  };
}
