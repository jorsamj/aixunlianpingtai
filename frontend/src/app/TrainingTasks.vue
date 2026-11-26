<script setup lang="ts">
import {computed,ref,watch,onBeforeUnmount} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {request,requestText} from './http';
import {legacyUrl} from './navigation';
import {trainingReaderApi,type TrainingTask,type TaskPage} from '../api/training-reader';
import {deleteTrainingTaskRecord,deleteTrainingTaskRecords,fetchTrainingRecovery,readTrainingDeletionStatus,requestTrainingRecovery,runTrainingLifecycleAction,stopTrainingTask,type TrainingRecoveryTruth} from '../api/training-actions';
import {useReadScope} from '../composables/useReadScope';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import TaskStatusTag from '../components/TaskStatusTag.vue';
import {trainingBatchActionEligible} from '../../../static/modules/training-task-runtime.js';
import {useWorkspace} from './main';
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
// Batch record deletion reuses the existing v48 endpoint. The server deletes the
// task record, keeps algorithm versions, and retains protected evidence only when
// its own evidence rules require it, so the receipt is reported per category
// instead of promising that every artifact survives.
const tableRef=ref<{clearSelection:()=>void}>(),batchSelected=ref<string[]>([]);
const batchBusy=ref(false),batchNotice=ref(''),batchError=ref('');
const pendingBatch=ref<{ids:string[];requestedAt:string;actor:string;project:string}|null>(null);
const batchVerifyBusy=ref(false),batchVerifyResult=ref<Record<string,number>|null>(null);
const workspace=useWorkspace();
const actorKey=computed(()=>workspace.actorKey||'');
const pendingBatchKey=computed(()=>`training-batch-delete:${projectId}:${actorKey.value||'anonymous'}`);
const deletableRow=(row:TrainingTask)=>row.kind==='TRAINING'&&trainingBatchActionEligible(row as unknown as Record<string,unknown>,'delete');
// A batch request in flight blocks every training write; an unverified result
// only blocks the operations that would touch the same records.
const batchInFlight=computed(()=>batchBusy.value);
const otherMutationBusy=computed(()=>!!lifecycleBusy.value||stopBusy.value||recoveryBusy.value);
const pendingIds=computed(()=>new Set(pendingBatch.value?.ids||[]));
function onBatchSelection(rows:TrainingTask[]){batchSelected.value=rows.map(row=>row.task_id)}
function clearBatchSelection(){batchSelected.value=[];tableRef.value?.clearSelection()}
function readPendingBatch(){
  try{
    const raw=JSON.parse(sessionStorage.getItem(pendingBatchKey.value)||'null');
    if(!raw||!Array.isArray(raw.ids)||!raw.ids.length){pendingBatch.value=null;return}
    // Only a record that this actor and project wrote may be restored; an
    // anonymous or foreign record is ignored instead of adopted.
    if(String(raw.actor||'')!==actorKey.value||String(raw.project||'')!==projectId||!actorKey.value){
      pendingBatch.value=null;return;
    }
    pendingBatch.value={ids:raw.ids.filter((id:unknown)=>typeof id==='string'),
      requestedAt:String(raw.requestedAt||''),actor:actorKey.value,project:projectId};
  }catch{pendingBatch.value=null}
}
function writePendingBatch(value:{ids:string[];requestedAt:string;actor:string;project:string}|null){
  try{
    if(value)sessionStorage.setItem(pendingBatchKey.value,JSON.stringify(value));
    else sessionStorage.removeItem(pendingBatchKey.value);
  }catch{return false}
  pendingBatch.value=value;
  return true;
}
// Switching the confirmed actor invalidates any previous verification result so a
// stale count can never be reused in another scope.
watch(()=>workspace.actorKey,()=>{
  batchVerifyResult.value=null;batchNotice.value='';batchError.value='';
  readPendingBatch();
},{immediate:true});
function batchMessage(result:Awaited<ReturnType<typeof deleteTrainingTaskRecords>>){
  const parts=[`记录已删除 ${result.deleted} 条`];
  if(result.audit_retained_ids.length)parts.push(`其中 ${result.audit_retained_ids.length} 条按原证据规则保留受保护训练证据/产物，其余按原清理规则处理`);
  else parts.push('按原证据规则本次没有需要保留的受保护证据');
  parts.push(`跳过执行中 ${result.skipped_active} 条`,`未找到 ${result.missing} 条`);
  if(result.failures.length)parts.push(`失败 ${result.failures.length} 条`);
  parts.push('算法版本不受影响');
  return parts.join('；')+'。';
}
async function batchDelete(){
  // Batch deletion is mutually exclusive with every single-task write, in both
  // directions, so one action can never overwrite another's receipt.
  if(!batchSelected.value.length||batchBusy.value||pendingBatch.value||otherMutationBusy.value)return;
  if(!actorKey.value){batchError.value='当前会话身份未确认，不能提交批量删除。';return}
  const ids=[...batchSelected.value];
  if(!window.confirm(`确认删除 ${ids.length} 条已结束训练任务记录？记录删除后不可恢复，算法版本与按原规则保留的证据不受影响。`))return;
  batchBusy.value=true;batchError.value='';batchNotice.value='';batchVerifyResult.value=null;
  const scopeKey=pendingBatchKey.value,actor=actorKey.value;
  // The pending record must exist before the request; if it cannot be persisted
  // the submission is refused so a lost response can never be unverifiable.
  if(!writePendingBatch({ids,requestedAt:new Date().toISOString(),actor,project:projectId})){
    batchBusy.value=false;
    batchError.value='浏览器无法保存待核验记录，已取消提交；请允许会话存储或改用原工作台。';
    return;
  }
  const controller=new AbortController();
  try{
    const result=await deleteTrainingTaskRecords(projectId,ids,controller.signal);
    if(scopeKey!==pendingBatchKey.value)return;
    if(!writePendingBatch(null)){
      batchNotice.value=batchMessage(result);
      batchError.value='删除已执行，但浏览器无法清除本地待核验记录；请核对后使用“结束本次核验”。';
      return;
    }
    batchNotice.value=batchMessage(result);
    clearBatchSelection();
    await loadList();
  }catch(error){
    if(scopeKey!==pendingBatchKey.value)return;
    const status=(error as {httpStatus?:number}).httpStatus;
    // v48 rejects invalid/oversized payloads and unknown projects before any
    // deletion, so those responses are a definite "not executed".
    if(status===400||status===404||status===422){
      writePendingBatch(null);
      batchError.value=(error as Error).message;
    }else{
      batchError.value=`删除结果未知：${(error as Error).message}。已保留原提交记录，请先核对再决定后续操作。`;
    }
  }finally{batchBusy.value=false}
}
async function verifyBatchDeletion(){
  const pending=pendingBatch.value;
  if(!pending||batchVerifyBusy.value||batchBusy.value)return;
  const scopeKey=pendingBatchKey.value,actor=actorKey.value,expected=[...pending.ids];
  batchVerifyBusy.value=true;batchError.value='';
  const controller=new AbortController();
  try{
    const result=await readTrainingDeletionStatus(projectId,expected,controller.signal);
    // A response that arrives after the actor/project or pending identity changed
    // must not write into the new scope.
    const current=pendingBatch.value;
    if(scopeKey!==pendingBatchKey.value||actor!==actorKey.value||!current
      ||current.ids.length!==expected.length||current.ids.some(id=>!expected.includes(id)))return;
    batchVerifyResult.value=result.counts;
    const deleted=result.counts.deleted||0;
    if(deleted===expected.length){
      if(!writePendingBatch(null)){
        batchNotice.value=`已核对：${deleted} 条记录均已删除；但浏览器无法清除本地待核验记录，请稍后重试结束核验。`;
        return;
      }
      batchNotice.value=`已核对：${deleted} 条记录均已删除；受保护证据与产物是否保留以原任务证据为准，算法版本不受影响。`;
      clearBatchSelection();
      await loadList();
    }else{
      const remaining=result.items.filter(row=>row.state!=='deleted')
        .map(row=>`${row.job_id}（${({terminal:'记录仍在',active:'执行中',missing:'未找到',invalid:'ID 无效'} as Record<string,string>)[row.state]||row.state}）`);
      batchNotice.value=`核对结果：已删除 ${deleted} 条；未确认 ${remaining.length} 条：${remaining.slice(0,10).join('、')}${remaining.length>10?' 等':''}。本次核对不会自动重试；确认无误后可“结束本次核验”。`;
    }
  }catch(error){batchError.value=`核对失败：${(error as Error).message}`}
  finally{batchVerifyBusy.value=false}
}
// Ending the verification is not a success claim: it needs a trusted per-item
// result, an explicit confirmation and a persisted clear, and it never retries.
function endBatchVerification(){
  if(!pendingBatch.value||batchBusy.value||batchVerifyBusy.value)return;
  const pending=pendingBatch.value,counts=batchVerifyResult.value;
  if(!counts){
    batchError.value='尚未取得可信的逐项核对结果，不能结束本次核验。请先“核对删除状态”。';
    return;
  }
  const deleted=counts.deleted||0,remaining=pending.ids.length-deleted;
  const message=remaining
    ?`已核对：已删除 ${deleted} 条，未确认 ${remaining} 条。结束核验只解除本次保护，不代表这些记录已删除。确认结束？`
    :`已核对 ${deleted} 条记录均已删除，确认结束本次核验？`;
  if(!window.confirm(message))return;
  if(!writePendingBatch(null)){
    batchError.value='浏览器无法清除本地待核验记录，未解除保护；请稍后重试。';
    return;
  }
  batchNotice.value=remaining
    ?`已结束本次核验：已删除 ${deleted} 条，未确认 ${remaining} 条（未做任何自动重试）。如需清理，请重新核对资格后发起新操作。`
    :`已结束本次核验：${deleted} 条记录均已删除。`;
  batchVerifyResult.value=null;
}// Bounded text log read through the shared http owner (401/deadline/cancel are
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
  if(batchInFlight.value){batchError.value='批量删除正在执行，请稍后再操作。';return}
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
  if(batchInFlight.value||(current&&pendingIds.value.has(current.task_id))){
    batchError.value='该任务存在未核验的批量删除或批量删除正在执行，请先核对后再做恢复校验。';return;
  }
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
  if(batchInFlight.value||pendingIds.value.has(id)){
    batchError.value='该任务存在未核验的批量删除或批量删除正在执行，请先核对后再核验恢复状态。';return;
  }
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
  FAILED:'失败', SUCCEEDED:'已完成', PARTIAL_SUCCESS:'部分成功',
  BLOCKED_BY_ENVIRONMENT:'环境阻断', BLOCKED_BY_HARDWARE:'硬件阻断',
};
const kinds:Record<string,string> = {TRAINING:'训练',TRAINING_PREPARE:'训练准备'};
function duration(milliseconds:number){
  const minutes=Math.floor(milliseconds/60000);
  if(minutes<1)return '不足 1 分钟';
  const hours=Math.floor(minutes/60),days=Math.floor(hours/24);
  if(days>0)return `${days} 天 ${hours%24} 小时`;
  if(hours>0)return `${hours} 小时 ${minutes%60} 分`;
  return `${minutes} 分钟`;
}
// Only the server timeline is evidence: started_at/finished_at plus the status.
// A running task has no confirmed training duration, so it is labelled as the
// natural elapsed time since start; a terminal task without finished_at must not
// keep growing through Date.now().
function elapsed(row:TrainingTask){
  if(!row.started_at)return ['QUEUED','WAITING_RESOURCE'].includes(row.status)?'尚未开始':'缺少开始时间';
  const start=Date.parse(row.started_at);
  if(!Number.isFinite(start))return '缺少开始时间';
  if(row.finished_at){
    const end=Date.parse(row.finished_at);
    if(!Number.isFinite(end)||end<start)return '结束时间无效';
    return '终态 '+duration(end-start);
  }
  if(TERMINAL_STATUSES.includes(row.status))return '缺少结束时间';
  return '自然 '+duration(Date.now()-start);
}
function elapsedHint(row:TrainingTask){
  if(!row.started_at)return '服务端尚未记录开始时间';
  if(row.finished_at)return '开始至结束的终态耗时';
  if(TERMINAL_STATUSES.includes(row.status))return '终态缺少结束时间，不做推算';
  return '开始至本次读取的自然经过时间，含排队后等待与暂停，非已确认有效训练时长';
}
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
  if(batchInFlight.value){batchError.value='批量删除正在执行，请稍后再操作。';return}
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
  // Only a pending record that covers this task conflicts with deleting it; an
  // unrelated pending batch must not block other records.
  if(current&&pendingIds.value.has(current.task_id)){batchError.value='该任务存在未核验的批量删除，请先核对后再删除记录。';return}
  if(batchInFlight.value){batchError.value='批量删除正在执行，请稍后再操作。';return}
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
<el-alert v-if="reads.errors.tasks" :title="reads.errors.tasks" type="error" :closable="false"/><el-alert v-if="lifecycleError" :title="lifecycleError" type="error" :closable="false"/><el-alert v-if="lifecycleNotice" :title="lifecycleNotice" type="info" :closable="false"/><div v-if="pendingBatch" class="training-batch-bar training-batch-pending" role="alert"><span>批量删除结果待核验：{{pendingBatch.ids.length}} 条记录（提交于 {{pendingBatch.requestedAt}}）</span><el-button size="small" type="primary" :loading="batchVerifyBusy" :disabled="batchBusy" @click="verifyBatchDeletion">核对删除状态</el-button><span v-if="batchVerifyResult">已删除 {{batchVerifyResult.deleted||0}} · 仍存在 {{batchVerifyResult.terminal||0}} · 执行中 {{batchVerifyResult.active||0}} · 未找到 {{batchVerifyResult.missing||0}}</span><el-button size="small" :disabled="batchBusy||batchVerifyBusy" @click="endBatchVerification">结束本次核验</el-button></div><div v-if="batchSelected.length" class="training-batch-bar" role="status"><span>已选 {{batchSelected.length}} 条已结束记录</span><el-button size="small" type="danger" plain :loading="batchBusy" :disabled="!!pendingBatch||batchInFlight" @click="batchDelete">删除所选训练记录</el-button><el-button size="small" :disabled="batchBusy" @click="clearBatchSelection">清空选择</el-button></div><p v-if="batchNotice" role="status">{{batchNotice}}</p><p v-if="batchError" role="alert">{{batchError}}</p><el-table ref="tableRef" v-loading="reads.busy.tasks" :data="page?.items||[]" row-key="task_id" empty-text="暂无任务" @selection-change="onBatchSelection"><el-table-column type="selection" width="44" :selectable="deletableRow"/><el-table-column prop="task_id" label="任务 ID" min-width="190"/><el-table-column label="类型" min-width="88"><template #default="{row}">{{ kinds[row.kind]||row.kind }}</template></el-table-column><el-table-column label="状态" min-width="100"><template #default="{row}"><TaskStatusTag :status="row.status"/></template></el-table-column><el-table-column label="进度 / 阶段" min-width="150"><template #default="{row}">{{row.progress_percent==null?'未提供':row.progress_percent+'%'}} · {{row.phase||'—'}}<small v-if="row.error" class="task-error">{{row.error}}</small></template></el-table-column><el-table-column label="算法 / 版本" min-width="165"><template #default="{row}">{{row.algorithm_name||row.algorithm_id||'—'}}<small v-if="row.version_id" class="task-version">{{row.version_id}}</small></template></el-table-column><el-table-column label="运行设备" min-width="105"><template #default="{row}">{{row.worker_id||row.resource_key||'未提供'}}</template></el-table-column><el-table-column label="耗时" min-width="118"><template #default="{row}"><span :title="elapsedHint(row)">{{elapsed(row)}}</span></template></el-table-column><el-table-column prop="created_at" label="创建时间" min-width="170"/><el-table-column label="操作" min-width="145"><template #default="{row}"><el-button link type="primary" @click="open(row.task_id)">详情</el-button> <router-link v-if="row.kind==='TRAINING'" :to="reportLink(row)">训练报告</router-link></template></el-table-column></el-table><footer><span>本页 {{page?.items.length||0}} 条</span><el-button :disabled="!param('cursor')" @click="prev">上一页</el-button><el-button :disabled="!page?.next_cursor" @click="next">下一页</el-button></footer>
<el-drawer :model-value="!!param('task')" title="任务详情" size="min(680px,100vw)" @close="close"><el-skeleton v-if="reads.busy.detail" :rows="8" animated/><el-alert v-else-if="reads.errors.detail" :title="reads.errors.detail" type="error" :closable="false"/><div v-else-if="task"><el-button @click="loadDetail">刷新详情</el-button>　<router-link v-if="task.kind==='TRAINING'" :to="reportLink(task)">训练报告</router-link><h3>身份与状态</h3><ReadOnlyFacts :fields="[['任务 ID',task.task_id],['类型',task.kind],['状态',`${labels[task.status]||task.status} (${task.status})`],['持久状态',task.persisted_status],['进度（%）',task.progress_percent],['阶段',task.phase],['算法',task.algorithm_name||task.algorithm_id],['版本',task.version_id]]"/><p v-if="task.related_task_id">关联任务：<el-button link type="primary" @click="open(task.related_task_id!)">{{task.related_task_id}}</el-button></p><h3>执行与资源</h3><ReadOnlyFacts :fields="[['创建',task.created_at],['开始',task.started_at],['结束',task.finished_at],['耗时',elapsed(task)+'（'+elapsedHint(task)+'）'],['算法 / 版本',(task.algorithm_name||task.algorithm_id||'未提供')+(task.version_id?' / '+task.version_id:'')],['Worker',task.worker_id],['资源',task.resource_key],['等待原因',task.resource_wait_reason],...Object.entries(task.execution||{})]"/><h3>配置</h3><ReadOnlyFacts :fields="Object.entries(task.configuration||{})"/><h4>请求的执行配置</h4><ReadOnlyFacts :fields="Object.entries(task.requested_execution||{})"/><h3>失败信息</h3><ReadOnlyFacts :fields="[['原因',task.error]]"/><template v-if="task.kind==='TRAINING'"><h3>训练日志</h3><el-button @click="loadLog(task.task_id)">刷新日志</el-button><p v-if="reads.errors.log">{{reads.errors.log}}</p><pre>{{log||'暂无日志'}}</pre></template><p v-if="actionNotice" role="status">{{ actionNotice }}</p><p><el-button v-if="canPause" size="small" :loading="lifecycleBusy==='pause'" :disabled="!!lifecycleBusy" @click="lifecycleAction('pause')">暂停训练</el-button> <el-button v-if="canResume" size="small" :loading="lifecycleBusy==='resume'" :disabled="!!lifecycleBusy" @click="lifecycleAction('resume')">继续训练</el-button> <el-button v-if="canPromote" size="small" :loading="lifecycleBusy==='promote'" :disabled="!!lifecycleBusy" @click="lifecycleAction('promote')">插队（排到最前）</el-button> <el-button v-if="canStop(task)" type="danger" plain size="small" :loading="stopBusy" :disabled="stopPending" @click="stopTask()">{{ stopPending ? '停止待核验' : '停止任务' }}</el-button> <el-button v-if="canDeleteRecord" type="danger" text size="small" :loading="lifecycleBusy==='delete'" :disabled="!!lifecycleBusy" @click="deleteTask()">删除任务记录</el-button> <el-button v-if="recoverable" type="primary" plain size="small" :loading="recoveryBusy" @click="recoverResult()">恢复结果校验</el-button> <el-button v-if="task.kind==='TRAINING'&&(recoveryPendingTaskId===task.task_id||(recovery&&!recoverable))" size="small" @click="verifyRecovery()">核验恢复状态</el-button></p><p v-if="recovery">恢复证据：{{ recovery.available ? '服务端确认可恢复' : '当前不可恢复' }}{{ recovery.task_status ? ' · 任务状态 ' + recovery.task_status : '' }}{{ recovery.failure_stage ? ' · 阶段 ' + recovery.failure_stage : '' }}</p><p><a v-if="task.kind==='TRAINING'" :href="bridge('task-detail',task.task_id)">原工作台 · 操作与恢复</a>　<a v-if="canStop(task)" :href="bridge('task-stop',task.task_id)">原工作台 · 停止任务</a></p></div></el-drawer></section></template>
<style scoped>
.training-tasks{padding:0}
header,form,footer{display:flex;align-items:center;gap:8px;flex-wrap:wrap}
header{justify-content:space-between}
header span{font-size:16px;font-weight:650}
form{margin:12px 0;padding:12px;background:var(--workspace-surface);border:1px solid var(--workspace-line);border-radius:var(--workspace-radius)}
form .el-input{max-width:280px}
form .el-select{width:150px}
footer{justify-content:flex-end;margin-top:12px;color:var(--workspace-muted);font-size:12px}
.training-batch-bar{display:flex;align-items:center;flex-wrap:wrap;gap:8px;margin:0 0 8px;padding:8px 12px;background:var(--workspace-hover);border-radius:6px;font-size:12px;color:var(--workspace-ink)}
.training-batch-pending{background:var(--el-color-warning-light-9);border:1px solid var(--el-color-warning-light-7)}
.task-error{display:block;margin-top:2px;color:var(--el-color-danger);font-size:12px;overflow-wrap:anywhere}
.task-version{display:block;color:var(--workspace-subtle);font-size:11px;overflow-wrap:anywhere}
pre{white-space:pre-wrap;overflow:auto;max-height:300px;background:var(--workspace-page);padding:12px;border:1px solid var(--workspace-line);border-radius:6px}
</style>
