import {request} from '../app/http';

export type LifecycleTarget = {
 algorithmId:string;
 algorithmName:string;
} & (
 {action:'version-delete';versionId:string;versionName:string} |
 {action:'rollback';versionId:string;versionName:string;currentVersionId:string}
);

export type VersionOperation = {
 operation_id:string;
 algorithm_id:string;
 action:'delete_version'|'rollback_and_delete';
 deleted_version_id:string;
 previous_current_version_id?:string;
 current_version_id?:string;
 cleanup_status:'cleanup_completed'|'cleanup_pending'|'cleanup_failed';
 cleanup_errors?:string[];
};

function algorithmUrl(projectId:string,algorithmId:string){
 return `/api/v12/projects/${encodeURIComponent(projectId)}/algorithms/${encodeURIComponent(algorithmId)}`;
}

export function deletedVersion(target:LifecycleTarget){
 return target.action==='rollback'?target.currentVersionId:target.versionId;
}

function matches(target:LifecycleTarget,value:VersionOperation){
 return value?.algorithm_id===target.algorithmId&&!!value.operation_id&&value.deleted_version_id===deletedVersion(target)
  &&(target.action==='rollback'
   ?value.action==='rollback_and_delete'&&value.previous_current_version_id===target.currentVersionId&&value.current_version_id===target.versionId
   :value.action==='delete_version');
}

export async function retryVersionCleanup(projectId:string,receipt:VersionOperation){
 const url=algorithmUrl(projectId,receipt.algorithm_id);
 const result=await request<Pick<VersionOperation,'algorithm_id'|'operation_id'|'deleted_version_id'|'cleanup_status'|'cleanup_errors'>>(
  `${url}/version-operations/${encodeURIComponent(receipt.operation_id)}/retry-cleanup`,{method:'POST'});
 if(result.algorithm_id!==receipt.algorithm_id||result.operation_id!==receipt.operation_id||
  result.deleted_version_id!==receipt.deleted_version_id)throw new Error('清理回执身份不一致');
 return {...receipt,...result};
}

export async function submitLifecycle(projectId:string,target:LifecycleTarget) {
 const url=algorithmUrl(projectId,target.algorithmId);
 const versionUrl=`${url}/versions/${encodeURIComponent(target.versionId)}`;
 const result=await (target.action==='rollback'
  ?request<VersionOperation>(versionUrl+'/rollback',{method:'POST',body:JSON.stringify({
   delete_current_version:true,expected_current_version_id:target.currentVersionId,
  })})
  :request<VersionOperation>(versionUrl,{method:'DELETE'}));
 if(!matches(target,result))throw new Error('版本操作响应无法核验');
 return result;
}

export async function verifyLifecycle(projectId:string,target:LifecycleTarget,signal:AbortSignal){
 const url=algorithmUrl(projectId,target.algorithmId);
 const result=await request<{ok:boolean;algorithm:{id:string;version_operations?:Array<{
  id:string;algorithm_id:string;action:VersionOperation['action'];deleted_version_id:string;
  from_version_id?:string;to_version_id?:string;cleanup_status:VersionOperation['cleanup_status'];
  cleanup_errors?:string[];
 }>}}>(url,{signal});
 if(result.ok===true&&result.algorithm?.id===target.algorithmId){
  for(const operation of result.algorithm.version_operations||[]){
   const receipt={...operation,operation_id:operation.id,previous_current_version_id:operation.from_version_id,current_version_id:operation.to_version_id};
   if(matches(target,receipt))return receipt;
  }
 }
 throw new Error('尚未读取到匹配的服务端操作记录');
}
