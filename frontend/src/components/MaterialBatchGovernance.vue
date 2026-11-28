<script setup lang="ts">
import {computed,onBeforeUnmount,ref,shallowRef,watch} from 'vue';
import MaterialAssignmentPanel from './MaterialAssignmentPanel.vue';
import {readWorkspaceSession,workspaceActorKey} from '../app/main';
import {getMaterialBatch,markMaterialsReady} from '../api/material-batches';
import type {MaterialBatchEstimate,MaterialBatchSelection,MaterialBatchTask} from '../api/material-batches';
import type {MaterialFilters} from '../types/materials';
import {browseError} from '../api/model-browse';

const props=defineProps<{projectId:string;actorKey:string;ids:string[];filters:MaterialFilters}>();
const open=defineModel<boolean>('open',{required:true});
const emit=defineEmits<{changed:[]}>();
const signal=new AbortController();
const key='material-governance:'+JSON.stringify([props.actorKey,props.projectId]);
const operation=ref<'usage'|'ready'>('usage'),scope=ref<'SELECTED'|'FILTERED'>('SELECTED'),split=ref('');
const estimate=shallowRef<MaterialBatchEstimate>(),task=shallowRef<MaterialBatchTask>();
const pending=ref(''),error=ref(''),note=ref(''),busy=ref(false);
const statusText:Record<string,string>={QUEUED:'排队中',WAITING_RESOURCE:'等待资源',RUNNING:'执行中',SUCCEEDED:'完成',
  PARTIAL_SUCCESS:'部分成功',FAILED:'失败',CANCEL_REQUESTED:'正在取消',CANCELLED:'取消',
  BLOCKED_BY_ENVIRONMENT:'环境阻断',BLOCKED_BY_HARDWARE:'硬件阻断'};
const terminal=computed(()=>!!task.value&&['SUCCEEDED','PARTIAL_SUCCESS','FAILED','CANCELLED','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE'].includes(task.value.status));
const locked=computed(()=>busy.value||!!pending.value||!!task.value);
const filteredAvailable=computed(()=>props.filters.annotation_state!=='partial');
const total=computed(()=>props.ids.length);
function batchFilters(){
  const {label,storage_source_id,...values}=props.filters;
  return {...Object.fromEntries(Object.entries(values).filter(([,value])=>!!value.trim())),
    ...(label.trim()?{labels:[label.trim()]}:{}),...(storage_source_id.trim()?{storage_source_ids:[storage_source_id.trim()]}:{})};
}
function remember(value:string){
  if(value)sessionStorage.setItem(key,value);
  else sessionStorage.removeItem(key);
  pending.value=value;
}
async function identity(){
  if(!props.actorKey||workspaceActorKey(await readWorkspaceSession(signal.signal))!==props.actorKey)
    throw new Error('会话已切换，请重新打开素材库');
}
function valid(record:MaterialBatchTask,id=record.task_id){
  return record.task_id===id&&record.project_id===props.projectId&&record.operation==='MARK_CLEAN_SKIPPED'&&!!id;
}
async function check(){
  if(busy.value||!pending.value||pending.value==='unknown')return;
  busy.value=true;error.value='';
  try{
    const value=await getMaterialBatch(props.projectId,pending.value,signal.signal);
    if(!valid(value,pending.value))throw new Error('后台任务身份不一致');
    task.value=value;
    if(terminal.value)emit('changed');
  }catch(cause){if(!signal.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false}
}
watch(open,value=>{
  if(!value)return;
  error.value='';estimate.value=undefined;note.value='';
  try{pending.value=sessionStorage.getItem(key)||'';if(pending.value)void check()}
  catch(cause){pending.value='unknown';error.value=browseError(cause)}
});
watch([operation,scope],()=>{estimate.value=undefined;error.value=''});
async function preflight(){
  if(locked.value||(scope.value==='SELECTED'&&!total.value)||(scope.value==='FILTERED'&&!filteredAvailable.value))return;
  busy.value=true;error.value='';estimate.value=undefined;
  try{
    const selection:MaterialBatchSelection=scope.value==='SELECTED'
      ?{scope:'SELECTED',image_ids:[...props.ids]}:{scope:'FILTERED',filters:batchFilters()};
    const value=await markMaterialsReady(props.projectId,selection,signal.signal,true);
    if(!value.supported||value.operation!=='MARK_CLEAN_SKIPPED'||!value.count
      ||value.selection_spec.scope!==selection.scope||(selection.scope==='SELECTED'&&value.count!==total.value))
      throw new Error('可操作范围与预检范围不一致，请刷新素材');
    estimate.value=value;
  }catch(cause){if(!signal.signal.aborted)error.value=browseError(cause)}
  finally{busy.value=false}
}
async function submit(){
  const preview=estimate.value;
  if(locked.value||!preview)return;
  busy.value=true;error.value='';note.value='';
  let sent=false;
  try{
    await identity();
    remember('unknown');sent=true;
    const value=await markMaterialsReady(props.projectId,preview.selection_spec,signal.signal,false);
    if(!valid(value)||value.total!==preview.count)throw new Error('后台回执身份或范围不一致');
    remember(value.task_id);task.value=value;estimate.value=undefined;
  }catch(cause){
    const status=(cause as {httpStatus?:number})?.httpStatus;
    if(sent&&status&&status>=400&&status<500)remember('');
    if(!signal.signal.aborted)error.value=browseError(cause);
  }finally{busy.value=false}
}
function clear(){
  if(!terminal.value&&pending.value!=='unknown')return;
  if(pending.value==='unknown'&&!window.confirm('请先在任务历史或素材列表核对结果。清除待核验记录后可以开始新的操作。'))return;
  try{remember('');task.value=undefined;emit('changed')}
  catch(cause){error.value=browseError(cause)}
}
onBeforeUnmount(()=>signal.abort());
</script>

<template>
 <el-dialog v-model="open" title="素材批量治理" width="min(560px,94vw)" :close-on-click-modal="false" :show-close="!busy" :close-on-press-escape="!busy">
  <el-alert v-if="error" type="error" :title="error" :closable="false" />
  <p v-if="note" role="status">{{note}}</p>
  <template v-if="task||pending">
   <p v-if="task" role="status">{{statusText[task.status] || task.status}} · 成功 {{task.succeeded ?? '待核对'}} / {{task.total ?? '待核对'}} 张 · 失败 {{task.failed ?? '待核对'}}</p>
   <p v-if="pending==='unknown'">提交结果待确认，请核对原任务或刷新素材。</p>
   <p v-else>任务 {{pending}}</p>
   <el-button v-if="pending!=='unknown'" :loading="busy" @click="check">刷新原任务</el-button>
   <el-button v-if="terminal||pending==='unknown'" :disabled="busy" @click="clear">完成核对</el-button>
  </template>
  <el-form v-else label-position="top" :disabled="busy">
   <el-form-item label="操作"><el-radio-group v-model="operation">
    <el-radio value="usage">调整用途</el-radio><el-radio value="ready">确认无需清洗</el-radio>
   </el-radio-group></el-form-item>
   <el-form-item v-if="operation==='usage'" label="目标用途"><el-select v-model="split">
    <el-option label="未分配" value="unassigned" /><el-option label="训练集" value="train" />
    <el-option label="验证集" value="val" /><el-option label="评测集" value="test" />
   </el-select></el-form-item>
   <el-form-item v-else label="处理范围"><el-radio-group v-model="scope">
    <el-radio value="SELECTED">已选 {{total}} 张</el-radio>
    <el-radio value="FILTERED" :disabled="!filteredAvailable">全部筛选结果</el-radio>
   </el-radio-group></el-form-item>
   <template v-if="operation==='ready'">
    <p v-if="scope==='SELECTED'">本次操作范围为已选 {{total}} 张。</p>
    <p v-if="estimate" role="status">服务端预检 {{estimate.count}} 张。</p>
    <el-button :disabled="scope==='SELECTED'&&!total" @click="preflight">预检范围</el-button>
    <el-button type="primary" :disabled="!estimate" @click="submit">确认执行</el-button>
   </template>
  </el-form>
  <MaterialAssignmentPanel v-if="operation==='usage'" :visible="open" :project-id="projectId" :actor-key="actorKey"
   :ids="ids" :filters="filters" operation="CLASSIFY_SPLIT" :target="split" @changed="emit('changed')" />
 </el-dialog>
</template>
