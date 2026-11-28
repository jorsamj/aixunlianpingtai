<script setup lang="ts">
import {computed,onBeforeUnmount,ref,shallowRef,watch} from 'vue';
import {readWorkspaceSession,workspaceActorKey} from '../app/main';
import {browseError} from '../api/model-browse';
import {
  estimateMaterialAssignment,getMaterialBatchResults,manageMaterialBatch,
  readMaterialAssignment,submitMaterialAssignment,
} from '../api/material-batches';
import type {MaterialAssignmentRequest,MaterialBatchEstimate,MaterialBatchItemResult,MaterialBatchTask} from '../api/material-batches';
import type {MaterialFilters} from '../types/materials';

const props=defineProps<{
  projectId:string;actorKey:string;visible:boolean;ids:string[];filters:MaterialFilters;
  operation:MaterialAssignmentRequest['operation'];target:string;
}>();
const emit=defineEmits<{changed:[]}>();
const controller=new AbortController();
const signal=controller.signal;
const key='material-assignment:'+JSON.stringify([props.actorKey,props.projectId,props.operation]);
const scope=ref<'selected'|'filtered'|'excluded'>('selected');
const estimate=shallowRef<MaterialBatchEstimate>(),task=shallowRef<MaterialBatchTask>();
const pending=shallowRef<MaterialAssignmentRequest>();
const error=ref(''),busy=ref(false),canReplay=ref(false);
const items=shallowRef<MaterialBatchItemResult[]>([]),cursor=ref<string|null>(null);
const filterAllowed=computed(()=>props.filters.annotation_state!=='partial');
const ready=computed(()=>!!props.target&&(scope.value==='selected'?!!props.ids.length:filterAllowed.value));
const statusText:Record<string,string>={QUEUED:'排队中',WAITING_RESOURCE:'等待资源',RUNNING:'执行中',SUCCEEDED:'完成',
  PARTIAL_SUCCESS:'部分成功',FAILED:'失败',CANCEL_REQUESTED:'正在取消',CANCELLED:'已取消',
  BLOCKED_BY_ENVIRONMENT:'环境阻断',BLOCKED_BY_HARDWARE:'硬件阻断'};
const outcomeText:Record<string,string>={updated:'已更新',unchanged:'已满足目标',conflict:'冲突',failed:'失败',
  pending:'待处理',unknown:'待核验',cancelled:'已取消'};
const terminal=computed(()=>['SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE'].includes(task.value?.status||''));

function selection():MaterialAssignmentRequest['selection_spec']{
  if(scope.value==='selected')return {scope:'SELECTED',image_ids:[...props.ids]};
  const {label,storage_source_id,...values}=props.filters;
  return {scope:'FILTERED',filters:{
    ...Object.fromEntries(Object.entries(values).filter(([,value])=>!!value.trim())),
    ...(label.trim()?{labels:[label.trim()]}:{}),
    ...(storage_source_id.trim()?{storage_source_ids:[storage_source_id.trim()]}:{}),
  },...(scope.value==='excluded'?{excluded_image_ids:[...props.ids]}:{})};
}
function targetOptions():MaterialAssignmentRequest['options']{
  return props.operation==='MOVE_DATASET'?{dataset_id:props.target}:{split:props.target};
}
function newId(){
  const bytes=crypto.getRandomValues(new Uint8Array(16));
  bytes[6]=(bytes[6]&15)|64;bytes[8]=(bytes[8]&63)|128;
  const hex=Array.from(bytes,byte=>byte.toString(16).padStart(2,'0')).join('');
  return [hex.slice(0,8),hex.slice(8,12),hex.slice(12,16),hex.slice(16,20),hex.slice(20)].join('-');
}
async function run(action:()=>Promise<void>){
  if(busy.value)return;
  busy.value=true;error.value='';
  try{
    if(!props.actorKey||workspaceActorKey(await readWorkspaceSession(signal))!==props.actorKey)
      throw new Error('登录已变化，请重新打开素材库');
    await action();
  }catch(cause){if(!signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false}
}
function accept(record:MaterialBatchTask, packet:MaterialAssignmentRequest){
  if(record.project_id!==props.projectId||record.operation!==props.operation||!record.task_id
    ||(task.value&&record.task_id!==task.value.task_id)
    ||(packet.options.dataset_id&&record.target_dataset_id!==packet.options.dataset_id)
    ||(packet.options.split&&record.target_split!==packet.options.split))
    throw new Error('后台回执身份不一致');
  const previous=task.value?.succeeded||0;
  task.value=record;
  if((record.succeeded||0)>previous)emit('changed');
}
function preflight(){
  if(!ready.value||pending.value)return;
  const packet={operation:props.operation,selection_spec:selection(),options:targetOptions()};
  void run(async()=>{
    const value=await estimateMaterialAssignment(props.projectId,packet,signal);
    if(!value.supported||value.operation!==props.operation||!value.count
      ||value.selection_spec.scope!==packet.selection_spec.scope
      ||(packet.selection_spec.scope==='SELECTED'&&value.count!==props.ids.length)
      ||(props.operation==='MOVE_DATASET'&&!value.dataset_revision))
      throw new Error('可处理范围与预检不一致，请刷新素材');
    estimate.value=value;
  });
}
function submit(){
  const preview=estimate.value;
  if(!preview||pending.value)return;
  const packet:MaterialAssignmentRequest={operation:props.operation,selection_spec:preview.selection_spec,
    options:{...targetOptions(),...(preview.dataset_revision?{dataset_revision:preview.dataset_revision}:{})},
    request_id:newId()};
  void run(async()=>{
    sessionStorage.setItem(key,JSON.stringify(packet));
    pending.value=packet;estimate.value=undefined;
    try{accept(await submitMaterialAssignment(props.projectId,packet,signal),packet)}
    catch(cause){
      const status=(cause as {httpStatus?:number}).httpStatus;
      if(status&&status>=400&&status<500&&status!==408&&status!==429){
        sessionStorage.removeItem(key);pending.value=undefined;
      }
      throw cause;
    }
  });
}
function refresh(){
  const packet=pending.value;
  if(!packet?.request_id)return;
  const id=packet.request_id;
  void run(async()=>{
    canReplay.value=false;
    try{accept(await readMaterialAssignment(props.projectId,id,signal),packet)}
    catch(cause){
      if((cause as {httpStatus?:number}).httpStatus===404&&!task.value){canReplay.value=true;return}
      throw cause;
    }
  });
}
function replay(){
  const packet=pending.value;
  if(!canReplay.value||!packet)return;
  void run(async()=>{
    canReplay.value=false;
    accept(await submitMaterialAssignment(props.projectId,packet,signal),packet);
  });
}
function manage(action:'cancel'|'retry'){
  const packet=pending.value,id=task.value?.task_id;
  if(!packet||!id)return;
  void run(async()=>{accept(await manageMaterialBatch(props.projectId,id,action,signal),packet)});
}
function readResults(next=false){
  const id=task.value?.task_id;
  if(!id)return;
  void run(async()=>{
    const result=await getMaterialBatchResults(props.projectId,id,signal,next?cursor.value:null,50);
    items.value=result.items||[];cursor.value=result.next_cursor||null;
  });
}
function clear(){
  try{
    sessionStorage.removeItem(key);pending.value=undefined;task.value=undefined;
    items.value=[];cursor.value=null;
  }catch(cause){error.value=browseError(cause)}
}
watch(()=>props.visible,value=>{
  if(!value)return;
  estimate.value=undefined;
  try{
    const stored=sessionStorage.getItem(key);
    if(stored){
      const packet=JSON.parse(stored) as MaterialAssignmentRequest;
      if(packet.operation!==props.operation||!packet.request_id)throw new Error('恢复记录身份不一致');
      pending.value=packet;refresh();
    }
  }catch(cause){error.value=browseError(cause)}
},{immediate:true});
watch([scope,()=>props.target,()=>props.ids,()=>props.filters],()=>{estimate.value=undefined});
onBeforeUnmount(()=>controller.abort());
</script>

<template>
 <el-alert v-if="error" type="error" :title="error" :closable="false" />
 <template v-if="pending">
  <p v-if="task" role="status">{{statusText[task.status] || task.status}} · 已处理 {{task.processed ?? 0}} / {{task.total ?? '待核验'}} 张 · 成功 {{task.succeeded ?? 0}} · 冲突或失败 {{task.failed ?? 0}}</p>
  <p v-else role="status">{{canReplay?'尚未查询到任务，可按原请求继续提交。':'正在核对原提交。'}}</p>
  <el-button :loading="busy" @click="refresh">刷新任务</el-button>
  <el-button v-if="canReplay" :disabled="busy" @click="replay">按原请求提交</el-button>
  <el-button v-if="task && !terminal && task.status!=='CANCEL_REQUESTED'" :disabled="busy" @click="manage('cancel')">取消任务</el-button>
  <el-button v-if="terminal && (task?.status==='CANCELLED'||task?.status==='FAILED')" :disabled="busy" @click="manage('retry')">继续未处理项</el-button>
  <el-button v-if="task" :disabled="busy" @click="readResults()">查看结果</el-button>
  <el-button v-if="terminal" :disabled="busy" @click="clear">完成核对</el-button>
  <el-table v-if="items.length" :data="items" max-height="220" aria-label="处理结果">
   <el-table-column label="素材 ID" prop="image_id" min-width="180" />
   <el-table-column label="结果" min-width="120"><template #default="{row}">{{outcomeText[row.outcome] || row.outcome}}</template></el-table-column>
   <el-table-column label="原因" prop="item_error" min-width="170" />
  </el-table>
  <el-button v-if="cursor" :disabled="busy" @click="readResults(true)">下一页</el-button>
 </template>
 <template v-else>
  <el-radio-group v-model="scope" aria-label="处理范围" :disabled="busy">
   <el-radio value="selected">已选 {{ids.length}} 张</el-radio>
   <el-radio value="filtered" :disabled="!filterAllowed">全部筛选结果</el-radio>
   <el-radio value="excluded" :disabled="!filterAllowed || !ids.length || ids.length>500">筛选结果，排除已选</el-radio>
  </el-radio-group>
  <p v-if="estimate" role="status">将处理 {{estimate.count}} 张素材。</p>
  <el-button :disabled="!ready || busy" @click="preflight">预检范围</el-button>
  <el-button type="primary" :disabled="!estimate || busy" @click="submit">确认执行</el-button>
 </template>
</template>
