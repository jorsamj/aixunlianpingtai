<script setup lang="ts">
import {computed,ref,watch,onBeforeUnmount} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {request,requestText} from './http';
import {legacyUrl} from './navigation';
import {trainingReaderApi,type TrainingTask,type TaskPage} from '../api/training-reader';
import {deleteTrainingTaskRecord,fetchTrainingRecovery,requestTrainingRecovery,runTrainingLifecycleAction,stopTrainingTask,type TrainingRecoveryTruth} from '../api/training-actions';
import {useReadScope} from '../composables/useReadScope';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import {trainingBatchActionEligible} from '../../../static/modules/training-task-runtime.js';
import {trainingDisplayStatus} from '../../../static/modules/task-runtime-truth.js';
const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId),controller=new AbortController();
const reads=useReadScope(controller),api=trainingReaderApi({projectId,get:request,memory:{}});
const page = ref<TaskPage | null>(null);
const task = ref<TrainingTask | null>(null);
const log = ref('');
const recovery = ref<TrainingRecoveryTruth | null>(null);
const stopBusy = ref(false);
const recoveryBusy = ref(false);
const actionNotice = ref('');
const stopPendingTaskId = ref('');
const recoveryPendingTaskId = ref('');
const lifecycleBusy = ref('');
const lifecycleNotice = ref('');
const lifecycleError = ref('');
let mutationController: AbortController | null = null;
const TERMINAL_STATUSES = ['CANCELLED','FAILED','SUCCEEDED','PARTIAL_SUCCESS','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE'];
let stopTimer: number | undefined;
let pollController: AbortController | null = null;
let detailEpoch = 0;
let alive = true;
const query = ref('');
const status = ref('');
const kind = ref('');
const previousCursors = new Map<string, string>();
const param = (name: string) => typeof route.query[name] === 'string' ? String(route.query[name]) : '';
const listParams = () => ({query: param('query'), status: param('status'), kind: param('kind'), cursor: param('cursor')});
onBeforeUnmount(()=>{alive=false;controller.abort();mutationController?.abort();mutationController=null;stopPolling()});

function navigate(values: Record<string, string>) {
  void router.push({
    name:'training-tasks', params:{projectId},
    query:Object.fromEntries(Object.entries(values).filter(([, value]) => value)),
  });
}
function search() {
  previousCursors.clear();
  navigate({query:query.value,status:status.value,kind:kind.value});
}
function open(id:string) {
  navigate({...listParams(), previous:param('previous'), task:id});
}
function close() {
  if (param('task')) open('');
}
function reportLink(row:TrainingTask) {
  return {name:'training-report',params:{projectId,jobId:row.report_job_id||row.task_id},query:{back:route.fullPath}};
}
function bridge(action = '', id = '') {
  const base = legacyUrl(projectId,'训练任务','','',action);
  if (!id) return base;
  return base + '&' + new URLSearchParams({...listParams(),previous:param('previous'),task_id:id});
}
function loadList() {
  return reads.run('tasks',signal=>api.tasks(listParams(),signal),value=>{page.value=value});
}
async function loadDetail() {
  const id = param('task');
  reads.cancel('detail');
  reads.cancel('log');
  reads.cancel('recovery');
  stopPolling();
  recovery.value = null;
  task.value = null;
  log.value = '';
  actionNotice.value = '';
  if(stopPendingTaskId.value&&stopPendingTaskId.value!==id)stopPendingTaskId.value='';
  if(recoveryPendingTaskId.value&&recoveryPendingTaskId.value!==id)recoveryPendingTaskId.value='';
  if (!id) return;
  const epoch = ++detailEpoch;
  await reads.run('detail',signal=>api.task(id,signal),value=>{
    if(!alive||epoch!==detailEpoch||param('task')!==id)return;
    task.value = value;
    if (value.kind === 'TRAINING') {loadLog(value.task_id); void loadRecovery(value.task_id,epoch);}
  });
}
function mutationSignal(){
  mutationController?.abort();
  mutationController=new AbortController();
  return mutationController.signal;
}
// Bounded text log read through the shared http owner (401/deadline/cancel are
// the same as every other native request; the caller's signal is abortable).
function loadLog(id:string) {
  void reads.run('log', signal => requestText(
    `/api/projects/${encodeURIComponent(projectId)}/jobs/${encodeURIComponent(id)}/log`,{signal},
  ).then(value=>value.slice(-120000)),value=>{
    if(param('task')===id&&task.value?.task_id===id)log.value=value;
  });
}
function stopPolling(){if(stopTimer!==undefined){window.clearInterval(stopTimer);stopTimer=undefined}pollController?.abort();pollController=null}
function startStatusPolling(id:string){
  stopPolling();
  stopTimer=window.setInterval(async()=>{
    if(!alive||param('task')!==id||task.value?.task_id!==id){stopPolling();return}
    try{
      pollController?.abort();
      pollController=new AbortController();
      const latest=await api.task(id,pollController.signal);
      if(!alive||param('task')!==id||task.value?.task_id!==id)return;
      task.value=latest;
      if(TERMINAL_STATUSES.includes(latest.status)){
        stopPolling();
        if(stopPendingTaskId.value===id)stopPendingTaskId.value='';
        await loadList();
        if(param('task')===id&&latest.kind==='TRAINING')await loadRecovery(id);
      }
    }catch{/* keep the last proven state; next tick retries */}
  },2000);
}
async function loadRecovery(id:string,epoch=detailEpoch){
  recovery.value=null;
  await reads.run('recovery',signal=>fetchTrainingRecovery(projectId,id,signal),value=>{
    if(!alive||epoch!==detailEpoch||param('task')!==id||task.value?.task_id!==id)return;
    if(value.task_id!==id||value.project_id!==projectId)return;
    recovery.value=value;
  });
}
async function stopTask(){
  const current=task.value;
  if(!current||!canStop(current)||stopBusy.value||stopPendingTaskId.value===current.task_id)return;
  if(!window.confirm('确认停止该训练任务？停止请求会记录到原任务，进程安全终止后才进入取消终态。'))return;
  const id=current.task_id;
  stopBusy.value=true;actionNotice.value='';
  try{
    const updated=await stopTrainingTask(projectId,id,mutationSignal());
    if(!alive||param('task')!==id||task.value?.task_id!==id)return;
    task.value=updated;
    if(TERMINAL_STATUSES.includes(updated.status)){
      actionNotice.value=`任务已停止：服务端返回${labels[updated.status]||updated.status}。`;
      stopPendingTaskId.value='';
      await loadList();
      if(updated.kind==='TRAINING'&&updated.status==='FAILED')await loadRecovery(id);
      return;
    }
    actionNotice.value='停止请求已记录，正在等待任务进入终态。';
    stopPendingTaskId.value=id;
    startStatusPolling(id);
    await loadList();
  }catch(cause){
    if(!alive||param('task')!==id||task.value?.task_id!==id)return;
    const httpStatus=(cause as {httpStatus?:number}).httpStatus;
    if(httpStatus!==undefined&&httpStatus<500){
      actionNotice.value=`停止请求未受理：${cause instanceof Error?cause.message:'请求失败'}`;
      return;
    }
    actionNotice.value='停止状态待核验：未收到服务端回执，不会重复提交；正在按原任务身份核验。';
    stopPendingTaskId.value=id;
    startStatusPolling(id);
  }finally{stopBusy.value=false}
}
const stopPending=computed(()=>!!task.value&&stopPendingTaskId.value===task.value.task_id);
const recoverable=computed(()=>{
  const current=task.value,truth=recovery.value;
  return !!current&&!!truth&&current.project_id===projectId&&truth.project_id===projectId
    &&current.task_id===truth.task_id&&current.status==='FAILED'&&truth.task_status==='FAILED'
    &&truth.available===true&&truth.recoverable===true
    &&truth.recovery_action==='revalidate_checkpoint'
    &&recoveryPendingTaskId.value!==current.task_id;
});
async function recoverResult(){
  const current=task.value;
  if(!current||!recoverable.value||recoveryBusy.value)return;
  const id=current.task_id;
  if(!window.confirm('对该任务执行“恢复结果校验”？这会核验既有检查点，不会继续训练，也不会新建训练任务。'))return;
  recoveryBusy.value=true;actionNotice.value='';
  try{
    const result=await requestTrainingRecovery(projectId,id,'revalidate_checkpoint',mutationSignal());
    if(!alive||param('task')!==id||task.value?.task_id!==id)return;
    if(result.task_id!==id){actionNotice.value='恢复受理回执与当前任务不一致，已停止采信。';return}
    await loadDetail();
    if(!alive||param('task')!==id||task.value?.task_id!==id)return;
    actionNotice.value=`恢复请求已受理（状态 ${result.status}），等待原任务更新。`;
    recoveryPendingTaskId.value=id;
    startStatusPolling(id);
  }catch(cause){
    if(!alive||param('task')!==id||task.value?.task_id!==id)return;
    const httpStatus=(cause as {httpStatus?:number}).httpStatus;
    if(httpStatus!==undefined&&httpStatus<500){
      actionNotice.value=`恢复请求未受理：${cause instanceof Error?cause.message:'请求失败'}`;
    }else{
      actionNotice.value='恢复请求结果待核验：未收到服务端回执，不会重复提交；请核验原任务与恢复证据。';
      recoveryPendingTaskId.value=id;
      startStatusPolling(id);
    }
    await loadRecovery(id);
  }finally{recoveryBusy.value=false}
}
async function verifyRecovery(){
  const id=task.value?.task_id;
  if(!id||param('task')!==id)return;
  await loadDetail();
}
function refresh() {
  void loadList();
  loadDetail();
}
watch(()=>[param('query'),param('status'),param('kind'),param('cursor')].join('\0'),()=>{
  ({query:query.value,status:status.value,kind:kind.value}=listParams());
  page.value = null;
  void loadList();
},{immediate:true});
watch(()=>param('task'),loadDetail,{immediate:true});
function prev() {
  const cursor = previousCursors.get(param('cursor')) || param('previous');
  navigate({...listParams(),cursor,previous:previousCursors.get(cursor)||''});
}
function next() {
  const nextCursor = page.value?.next_cursor;
  if (!nextCursor) return;
  const previous = param('cursor');
  previousCursors.set(nextCursor,previous);
  navigate({...listParams(),cursor:nextCursor,previous});
}
const labels:Record<string,string> = {
  QUEUED:'排队中', WAITING_RESOURCE:'等待资源', RUNNING:'运行中', PAUSED:'已暂停',
  AWAITING_CONFIRMATION:'等待确认', CANCEL_REQUESTED:'已请求取消', CANCELLED:'已取消',
  FAILED:'失败', SUCCEEDED:'成功', PARTIAL_SUCCESS:'部分成功',
  BLOCKED_BY_ENVIRONMENT:'环境阻断', BLOCKED_BY_HARDWARE:'硬件阻断',
};
const kinds:Record<string,string> = {TRAINING:'训练',TRAINING_PREPARE:'训练准备'};
function canStop(row:TrainingTask) {
  return row.kind==='TRAINING' && ['QUEUED','WAITING_RESOURCE','RUNNING','PAUSED'].includes(row.status) &&
    !['cancelling','stopping','starting','pausing','resuming','cleaning_training_process','process_cleanup_blocked'].includes(row.phase||'');
}
const transitionalPhase=(row:TrainingTask|null)=>!!row&&['cancelling','stopping','starting','pausing','resuming','cleaning_training_process','process_cleanup_blocked'].includes(row.phase||'');
// Reuse the original task-wall eligibility projection for real v48 lifecycle
// actions, and render delete only for terminal tasks (v12 endpoint contract).
const canPause=computed(()=>!!task.value&&task.value.kind==='TRAINING'&&trainingBatchActionEligible(task.value,'pause')&&!transitionalPhase(task.value));
const canResume=computed(()=>!!task.value&&task.value.kind==='TRAINING'&&trainingBatchActionEligible(task.value,'resume')&&!transitionalPhase(task.value));
const canPromote=computed(()=>!!task.value&&task.value.kind==='TRAINING'&&['queued','waiting','pending'].includes(trainingDisplayStatus(task.value))&&!transitionalPhase(task.value));
const canDeleteRecord=computed(()=>!!task.value&&trainingBatchActionEligible(task.value,'delete'));
function lifecycleFailure(kind:string,error:unknown){
  const httpStatus=(error as {httpStatus?:number}).httpStatus;
  if(httpStatus!==undefined&&httpStatus<500){lifecycleError.value=`${kind}请求未受理：${error instanceof Error?error.message:'请求失败'}`;return}
  lifecycleError.value='';
  lifecycleNotice.value=`${kind}结果待核验：未收到服务端确认回执；不会重复提交，已按原任务身份核验状态。`;
}
async function lifecycleAction(action:'pause'|'resume'|'promote'){
  const current=task.value;
  if(!current||lifecycleBusy.value)return;
  if((action==='pause'&&!canPause.value)||(action==='resume'&&!canResume.value)||(action==='promote'&&!canPromote.value))return;
  const id=current.task_id;
  lifecycleBusy.value=action;lifecycleNotice.value='';lifecycleError.value='';actionNotice.value='';
  const signal=mutationSignal();
  try{
    await runTrainingLifecycleAction(projectId,id,action,signal);
    if(!alive||param('task')!==id)return;
    await loadDetail();
    if(!alive||param('task')!==id||task.value?.task_id!==id)return;
    lifecycleNotice.value=action==='pause'?'暂停请求已受理，任务状态与进程以服务端为准。'
      :action==='resume'?'继续训练请求已受理，任务状态与进程以服务端为准。'
      :'已请求将任务排到当前训练资源队列最前。';
    await loadList();
  }catch(error){
    if(signal.aborted||!alive)return;
    lifecycleFailure(action==='pause'?'暂停':action==='resume'?'继续训练':'插队',error);
    await loadDetail().catch(()=>{});
    if(lifecycleNotice.value)startStatusPolling(id);
  }finally{lifecycleBusy.value=''}
}
async function deleteTask(){
  const current=task.value;
  if(!current||!canDeleteRecord.value||lifecycleBusy.value)return;
  if(!window.confirm('确认删除这条已结束训练任务记录？已经生成的算法版本不会删除。'))return;
  const id=current.task_id;
  lifecycleBusy.value='delete';lifecycleNotice.value='';lifecycleError.value='';actionNotice.value='';
  const signal=mutationSignal();
  try{
    await deleteTrainingTaskRecord(projectId,id,signal);
    if(!alive)return;
    lifecycleNotice.value='已结束的训练任务记录已删除；已生成的算法版本不受影响。';
    close();
    await loadList();
  }catch(error){
    if(signal.aborted||!alive)return;
    lifecycleFailure('删除任务记录',error);
    await loadList().catch(()=>{});
  }finally{lifecycleBusy.value=''}
}
</script>
<template><section class="training-tasks"><header><div><span>任务列表</span></div><div><a :href="bridge('')">原完整训练任务页</a>　<router-link :to="{name:'training-create',params:{projectId}}">新建训练</router-link></div></header>
<form @submit.prevent="search"><el-input v-model="query" placeholder="搜索任务 ID 或阶段"/><el-select v-model="status" placeholder="状态"><el-option label="全部状态" value=""/><el-option v-for="v in page?.filter_options.status||[]" :key="v" :label="labels[v]||v" :value="v"/></el-select><el-select v-model="kind" placeholder="类型"><el-option label="全部类型" value=""/><el-option v-for="v in page?.filter_options.kind||[]" :key="v" :label="kinds[v]||v" :value="v"/></el-select><el-button native-type="submit" type="primary">查询</el-button><el-button @click="refresh">刷新</el-button></form>
<el-alert v-if="reads.errors.tasks" :title="reads.errors.tasks" type="error" :closable="false"/><el-alert v-if="lifecycleError" :title="lifecycleError" type="error" :closable="false"/><el-alert v-if="lifecycleNotice" :title="lifecycleNotice" type="info" :closable="false"/><el-table v-loading="reads.busy.tasks" :data="page?.items||[]" row-key="task_id" empty-text="暂无任务"><el-table-column prop="task_id" label="任务 ID" min-width="200"/><el-table-column label="类型"><template #default="{row}">{{ kinds[row.kind]||row.kind }}</template></el-table-column><el-table-column label="状态"><template #default="{row}">{{labels[row.status]||row.status}}</template></el-table-column><el-table-column label="进度 / 阶段" min-width="150"><template #default="{row}">{{row.progress_percent==null?'未提供':row.progress_percent+'%'}} · {{row.phase||'—'}}</template></el-table-column><el-table-column prop="created_at" label="创建时间" min-width="170"/><el-table-column label="操作" min-width="145"><template #default="{row}"><el-button link type="primary" @click="open(row.task_id)">详情</el-button> <router-link v-if="row.kind==='TRAINING'" :to="reportLink(row)">训练报告</router-link></template></el-table-column></el-table><footer><span>本页 {{page?.items.length||0}} 条</span><el-button :disabled="!param('cursor')" @click="prev">上一页</el-button><el-button :disabled="!page?.next_cursor" @click="next">下一页</el-button></footer>
<el-drawer :model-value="!!param('task')" title="任务详情" size="min(680px,100vw)" @close="close"><el-skeleton v-if="reads.busy.detail" :rows="8" animated/><el-alert v-else-if="reads.errors.detail" :title="reads.errors.detail" type="error" :closable="false"/><div v-else-if="task"><el-button @click="loadDetail">刷新详情</el-button>　<router-link v-if="task.kind==='TRAINING'" :to="reportLink(task)">训练报告</router-link><h3>身份与状态</h3><ReadOnlyFacts :fields="[['任务 ID',task.task_id],['类型',task.kind],['状态',`${labels[task.status]||task.status} (${task.status})`],['持久状态',task.persisted_status],['进度（%）',task.progress_percent],['阶段',task.phase],['算法',task.algorithm_name||task.algorithm_id],['版本',task.version_id]]"/><p v-if="task.related_task_id">关联任务：<el-button link type="primary" @click="open(task.related_task_id!)">{{task.related_task_id}}</el-button></p><h3>执行与资源</h3><ReadOnlyFacts :fields="[['创建',task.created_at],['开始',task.started_at],['结束',task.finished_at],['Worker',task.worker_id],['资源',task.resource_key],['等待原因',task.resource_wait_reason],...Object.entries(task.execution||{})]"/><h3>配置</h3><ReadOnlyFacts :fields="Object.entries(task.configuration||{})"/><h4>请求的执行配置</h4><ReadOnlyFacts :fields="Object.entries(task.requested_execution||{})"/><h3>失败信息</h3><ReadOnlyFacts :fields="[['原因',task.error]]"/><template v-if="task.kind==='TRAINING'"><h3>训练日志</h3><el-button @click="loadLog(task.task_id)">刷新日志</el-button><p v-if="reads.errors.log">{{reads.errors.log}}</p><pre>{{log||'暂无日志'}}</pre></template><p v-if="actionNotice" role="status">{{ actionNotice }}</p><p><el-button v-if="canPause" size="small" :loading="lifecycleBusy==='pause'" :disabled="!!lifecycleBusy" @click="lifecycleAction('pause')">暂停训练</el-button> <el-button v-if="canResume" size="small" :loading="lifecycleBusy==='resume'" :disabled="!!lifecycleBusy" @click="lifecycleAction('resume')">继续训练</el-button> <el-button v-if="canPromote" size="small" :loading="lifecycleBusy==='promote'" :disabled="!!lifecycleBusy" @click="lifecycleAction('promote')">插队（排到最前）</el-button> <el-button v-if="canStop(task)" type="danger" plain size="small" :loading="stopBusy" :disabled="stopPending" @click="stopTask()">{{ stopPending ? '停止待核验' : '停止任务' }}</el-button> <el-button v-if="canDeleteRecord" type="danger" text size="small" :loading="lifecycleBusy==='delete'" :disabled="!!lifecycleBusy" @click="deleteTask()">删除任务记录</el-button> <el-button v-if="recoverable" type="primary" plain size="small" :loading="recoveryBusy" @click="recoverResult()">恢复结果校验</el-button> <el-button v-if="task.kind==='TRAINING'&&(recoveryPendingTaskId===task.task_id||(recovery&&!recoverable))" size="small" @click="verifyRecovery()">核验恢复状态</el-button></p><p v-if="recovery">恢复证据：{{ recovery.available ? '服务端确认可恢复' : '当前不可恢复' }}{{ recovery.task_status ? ' · 任务状态 ' + recovery.task_status : '' }}{{ recovery.failure_stage ? ' · 阶段 ' + recovery.failure_stage : '' }}</p><p><a v-if="task.kind==='TRAINING'" :href="bridge('task-detail',task.task_id)">原工作台 · 操作与恢复</a>　<a v-if="canStop(task)" :href="bridge('task-stop',task.task_id)">原工作台 · 停止任务</a></p></div></el-drawer></section></template>
<style scoped>.training-tasks{padding:24px}header,form,footer{display:flex;align-items:center;gap:12px;flex-wrap:wrap}header{justify-content:space-between}form{margin:20px 0}form .el-input{max-width:300px}form .el-select{width:160px}footer{justify-content:flex-end;margin-top:16px}pre{white-space:pre-wrap;overflow:auto;max-height:300px;background:#f5f7fa;padding:12px}</style>
