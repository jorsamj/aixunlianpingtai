<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,shallowRef} from 'vue';
import {browseError} from '../api/model-browse';
import {createHardwareTest,hardwareReportDownload,loadHardwarePreflight,loadHardwareReport,loadHardwareTask,readHardwareRequest} from '../api/conversion-hardware';
import type {HardwareRequest,HardwareTask} from '../api/conversion-hardware';
import {digestHex,sha256Bytes} from '../api/file-digest';
import {readWorkspaceSession,useWorkspace,workspaceActorKey} from '../app/main';
import {useReadScope} from '../composables/useReadScope';
import ReadOnlyFacts from './ReadOnlyFacts.vue';

const props=defineProps<{projectId:string;jobId:string;verified:boolean;stale:boolean}>();
const emit=defineEmits<{refresh:[]}>();
const {projectId,jobId}=props;
const actor=useWorkspace().actorKey;
const storageKey='rknn-hardware-test:'+JSON.stringify([actor,projectId,jobId]);
const controller=new AbortController();
const reads=useReadScope(controller);
const preflight=shallowRef<Awaited<ReturnType<typeof loadHardwarePreflight>>>();
const report=shallowRef<Awaited<ReturnType<typeof loadHardwareReport>>>();
const task=shallowRef<HardwareTask>();
const file=shallowRef<File>();
const confirmOpen=shallowRef(false);
const writeBusy=shallowRef(false),writeError=shallowRef('');
type SavedReceipt={chip:string;taskId:string;request?:HardwareRequest};
const receipt=shallowRef<SavedReceipt>();
const canReplay=shallowRef(false);
const storageError=shallowRef('');
const sessionChecked=shallowRef(false);
const ACTIVE=new Set(['QUEUED','WAITING_RESOURCE','RUNNING','RECOVERING','CANCEL_REQUESTED','PAUSED']);
const FAILED=new Set(['FAILED','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE','CANCELLED']);
const unknown=computed(()=>Boolean(receipt.value&&!receipt.value.taskId));
const canStart=computed(()=>Boolean(preflight.value?.ready&&file.value?.size&&actor&&!receipt.value&&!props.verified&&!report.value&&
  !props.stale&&!storageError.value&&!writeBusy.value&&!reads.busy.preflight&&!reads.errors.preflight));
let timer:number|undefined;

function saveReceipt(value:SavedReceipt){
  sessionStorage.setItem(storageKey,JSON.stringify(value));
  receipt.value=value;
}
async function checkActor(signal:AbortSignal){
  if(!actor||workspaceActorKey(await readWorkspaceSession(signal))!==actor)
    throw new Error('会话已变化，请重新打开转换任务');
}
function readReport(){
  void reads.run('report',signal=>loadHardwareReport(projectId,jobId,signal),value=>{report.value=value});
}
function readPreflight(){
  preflight.value=undefined;
  void reads.run('preflight',signal=>loadHardwarePreflight(projectId,jobId,signal),value=>{
    preflight.value=value;
    if(value.already_verified)readReport();
  });
}
function clearTimer(){
  if(timer!==undefined)window.clearTimeout(timer);
  timer=undefined;
}
async function refreshTask(){
  clearTimer();
  const saved=receipt.value;
  if(!saved?.taskId||!sessionChecked.value||controller.signal.aborted||writeBusy.value)return;
  await reads.run('task',signal=>saved.request?readHardwareRequest(projectId,jobId,saved.chip,saved.request,signal):
    loadHardwareTask(projectId,saved.taskId,saved.chip,signal),value=>{
    if(value.task_id!==saved.taskId)throw new Error('板端任务身份已变化');
    const previous=task.value;
    task.value=value;
    if(value.status==='SUCCEEDED'&&previous?.status!=='SUCCEEDED'){
      readReport();
      emit('refresh');
    }
  });
  if(!controller.signal.aborted&&!document.hidden&&task.value&&ACTIVE.has(task.value.status))
    timer=window.setTimeout(()=>{void refreshTask()},3000);
}
function checkSessionAndRefreshTask(){
  sessionChecked.value=false;
  clearTimer();
  reads.cancel('task');
  void reads.run('session',checkActor,()=>{
    sessionChecked.value=true;
    if(receipt.value?.taskId)void refreshTask();
    else if(receipt.value?.request)void verifyRequest();
  });
}
function onVisibility(){
  if(document.hidden){clearTimer();reads.cancel('task')}
  else if(receipt.value?.taskId&&!writeBusy.value)checkSessionAndRefreshTask();
}
onMounted(()=>{
  try{
    const raw=actor?sessionStorage.getItem(storageKey):null;
    if(raw){
      const saved=JSON.parse(raw);
      if(!['rk3568','rk3576'].includes(saved?.chip)||!(saved?.taskId===''||/^(?:[a-f0-9]{12}|[a-f0-9]{32})$/.test(saved?.taskId))
        ||saved.request&&(!/^[a-f0-9]{32}$/.test(saved.request.request_id)
          ||!(/^[a-f0-9]{64}$/.test(saved.request.model_sha256)&&/^[a-f0-9]{64}$/.test(saved.request.input_sha256))))
        throw new Error('板端验证回执记录无效');
      receipt.value=saved;
      if(saved.taskId||saved.request)checkSessionAndRefreshTask();
    }
  }catch(error){storageError.value=browseError(error)}
  document.addEventListener('visibilitychange',onVisibility);
});
onBeforeUnmount(()=>{
  controller.abort();
  clearTimer();
  document.removeEventListener('visibilitychange',onVisibility);
});

function selectFile(event:Event){file.value=(event.target as HTMLInputElement).files?.[0]}
async function hashFile(selected:File){
  if(!selected.size)throw new Error('请选择有效的测试图片');
  return digestHex(await sha256Bytes(await selected.arrayBuffer()));
}
async function verifyRequest(retry=false){
  const saved=receipt.value,identity=saved?.request,signal=controller.signal;
  if(!saved||!identity||writeBusy.value)return;
  writeBusy.value=true;writeError.value='';canReplay.value=false;
  try{
    await checkActor(signal);sessionChecked.value=true;
    const value=await readHardwareRequest(projectId,jobId,saved.chip,identity,signal,retry);
    if(saved.taskId&&saved.taskId!==value.task_id)throw new Error('板端任务身份已变化');
    saveReceipt({...saved,taskId:value.task_id});task.value=value;
    if(value.status==='SUCCEEDED'){readReport();emit('refresh')}
  }catch(error){
    if(!signal.aborted){
      if(!saved.taskId&&!retry&&(error as {httpStatus?:number}).httpStatus===404)canReplay.value=true;
      else writeError.value=browseError(error);
    }
  }finally{
    if(!signal.aborted){writeBusy.value=false;void refreshTask()}
  }
}
async function replayRequest(){
  const saved=receipt.value,identity=saved?.request,selected=file.value,signal=controller.signal;
  if(!saved||!identity||!selected||!canReplay.value||writeBusy.value)return;
  writeBusy.value=true;writeError.value='';canReplay.value=false;
  try{
    await checkActor(signal);sessionChecked.value=true;
    if(await hashFile(selected)!==identity.input_sha256){canReplay.value=true;throw new Error('测试图片与原请求不一致')}
    const value=await createHardwareTest(projectId,jobId,saved.chip,selected,identity,signal);
    saveReceipt({...saved,taskId:value.task_id});task.value=value;file.value=undefined;
  }catch(error){if(!signal.aborted)writeError.value=browseError(error)}
  finally{if(!signal.aborted){writeBusy.value=false;void refreshTask()}}
}
async function confirm(){
  const checked=preflight.value,selectedFile=file.value;
  if(!confirmOpen.value||!canStart.value||!checked||!selectedFile)return;
  confirmOpen.value=false;
  writeBusy.value=true;
  writeError.value='';
  const signal=controller.signal;
  let sent=false;
  try{
    await checkActor(signal);
    sessionChecked.value=true;
    const latest=await loadHardwarePreflight(projectId,jobId,signal);
    preflight.value=latest;
    if(!latest.ready||latest.chip!==checked.chip||latest.model.sha256!==checked.model.sha256)
      throw new Error(latest.reason||'板端准入或模型身份已变化，请重新确认');
    const request_id=Array.from(crypto.getRandomValues(new Uint8Array(16)),byte=>byte.toString(16).padStart(2,'0')).join('');
    const identity={request_id,model_sha256:latest.model.sha256,input_sha256:await hashFile(selectedFile)};
    if(signal.aborted)return;
    saveReceipt({chip:latest.chip,taskId:'',request:identity});
    sent=true;
    const value=await createHardwareTest(projectId,jobId,latest.chip,selectedFile,identity,signal);
    task.value=value;
    const knownReceipt={chip:latest.chip,taskId:value.task_id,request:identity};
    receipt.value=knownReceipt;
    saveReceipt(knownReceipt);
    file.value=undefined;
  }catch(error){
    if(signal.aborted)return;
    writeError.value=browseError(error);
    const status=(error as {httpStatus?:number}).httpStatus;
    const rejected=Boolean(status&&[400,401,403,404,409,413,422].includes(status));
    if(sent&&rejected){
      try{sessionStorage.removeItem(storageKey);receipt.value=undefined}
      catch(storageFailure){storageError.value=browseError(storageFailure)}
    }
  }finally{
    if(!signal.aborted){writeBusy.value=false;void refreshTask()}
  }
}
const reportFields=computed<[string,unknown][]>(()=>{
  const value=report.value;
  if(!value)return [];
  return [
    ['硬件验证',value.hardware_acceptance],['芯片',value.target.chip],['精度',value.target.precision],
    ['板端节点',value.board.node_id],['RKNNLite',value.board.rknn_lite_version],['产物',value.model.file_name],
    ['产物 SHA256',value.model.sha256],['测试图 SHA256',value.verification.input.sha256],
    ['验证任务',value.verification.task_id],['执行代数',value.verification.execution_generation],
    ['验证时间',value.verification.verified_at],['推理耗时（ms）',value.verification.inference_ms],
    ['输出数量',value.verification.output_count],['输出形状',JSON.stringify(value.verification.output_shapes)],
  ];
});
</script>

<template>
  <section aria-label="RKNN 板端验证" class="hardware">
    <h4>RKNN 板端验证</h4>
    <div class="actions">
      <el-button v-if="!verified&&!report" :disabled="writeBusy" :loading="reads.busy.preflight" @click="readPreflight">检查板端条件</el-button>
      <el-button v-if="verified||unknown||task?.status==='SUCCEEDED'||report" :loading="reads.busy.report" @click="readReport">读取验收报告</el-button>
      <el-button v-if="receipt?.taskId" :disabled="writeBusy" :loading="reads.busy.task||reads.busy.session" @click="checkSessionAndRefreshTask">核对原验证任务</el-button>
      <el-button v-if="unknown&&receipt?.request" :loading="writeBusy" @click="verifyRequest()">核对原验证请求</el-button>
    </div>
    <p v-if="storageError||writeError||reads.errors.session" role="alert">{{ storageError||writeError||reads.errors.session }}</p>
    <p v-if="reads.errors.preflight" role="alert">{{ reads.errors.preflight }}</p>
    <p v-if="reads.errors.task" role="alert">{{ reads.errors.task }}</p>
    <p v-if="reads.errors.report" role="alert">{{ reads.errors.report }}</p>
    <p v-if="unknown" role="status">{{receipt?.request?'板端验证回执待核对。':'此历史请求没有回查编号，可读取当前产物的验收报告。'}}</p>
    <div v-if="canReplay" class="actions">
      <label>原测试图片 <input type="file" accept="image/*" :disabled="writeBusy" @change="selectFile"></label>
      <el-button :disabled="!file||writeBusy" @click="replayRequest">按原请求提交</el-button>
    </div>
    <template v-if="preflight">
      <ReadOnlyFacts :fields="[['目标芯片',preflight.chip],['模型',preflight.model.file_name],['模型 SHA256',preflight.model.sha256]]"/>
      <p v-if="preflight.reason">{{ preflight.reason }} {{ preflight.solution }}</p>
      <div v-if="preflight.ready">
        <p>系统会自动调度以下匹配板卡。</p>
        <ul><li v-for="board in preflight.board_nodes" :key="board.node_id">{{ board.display_name||board.node_id }} · {{ board.rknn_lite_version||'未记录 RKNNLite 版本' }}</li></ul>
        <div v-if="!receipt&&!verified&&!report" class="actions">
          <label>测试图片 <input type="file" accept="image/*" :disabled="writeBusy||confirmOpen" @change="selectFile"></label>
          <el-button :disabled="!canStart" @click="confirmOpen=true">开始板端验证</el-button>
        </div>
      </div>
    </template>
    <div v-if="task" class="task">
      <ReadOnlyFacts :fields="[['验证任务',task.task_id],['任务状态',task.status],['阶段',task.phase],['执行次数',task.attempt],['等待原因',task.resource_wait_reason],['失败原因',task.error]]"/>
      <el-progress :percentage="task.progress_percent" :stroke-width="8"/>
      <el-button v-if="receipt?.request&&task.attempt===0&&['CANCELLED','FAILED'].includes(task.status)" :loading="writeBusy"
        @click="verifyRequest(true)">恢复未启动验证</el-button>
      <p v-else-if="FAILED.has(task.status)">已保留原验证任务及失败证据。</p>
    </div>
    <div v-if="report" class="task">
      <ReadOnlyFacts :fields="reportFields"/>
      <p>{{ report.statement }}</p>
      <a :href="hardwareReportDownload(projectId,jobId)">下载实机验收报告（JSON）</a>
    </div>
    <el-dialog v-model="confirmOpen" title="确认板端验证" width="min(560px, 92vw)">
      <p>使用 {{ file?.name }} 在匹配的 {{ preflight?.chip }} 板卡上执行 {{ preflight?.model.file_name }} 的 RKNNLite 推理。</p>
      <template #footer>
        <el-button @click="confirmOpen=false">返回</el-button>
        <el-button type="primary" :disabled="!canStart" @click="confirm">确认</el-button>
      </template>
    </el-dialog>
  </section>
</template>

<style scoped>
.hardware{border-top:1px solid var(--el-border-color-light);margin-top:16px;padding-top:2px}
.actions{display:flex;flex-wrap:wrap;align-items:center;gap:8px;margin-bottom:12px}
.actions :deep(.el-button){margin-left:0}
.task{margin-top:12px;display:grid;gap:8px}
[role=alert]{color:var(--el-color-danger)}
</style>
