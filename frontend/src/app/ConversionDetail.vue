<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {legacyUrl} from './navigation';
import {readWorkspaceSession,useWorkspace,workspaceActorKey} from './main';
import {useReadScope} from '../composables/useReadScope';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import ConversionHardwareValidation from '../components/ConversionHardwareValidation.vue';
import {browseError} from '../api/model-browse';
import {digestHex,sha256Bytes} from '../api/file-digest';
import {createNumericValidation,findNumericValidation,loadConversionJob,loadConversionLog,loadConversionNumericHistory,loadNumericValidation,newConversionRequestId,resolveNumericVerificationId,stopConversionJob} from '../api/conversion-jobs';
import type {ConversionJobDetail,ConversionJobOutput,ConversionNumericHistoryEntry} from '../types/conversion-job';
const props=defineProps<{projectId:string;jobId:string}>();
const projectId=props.projectId,jobId=props.jobId,route=useRoute(),router=useRouter();
const controller=new AbortController(),reads=useReadScope(controller);
const job=ref<ConversionJobDetail|null>(null),log=ref('');
const numericHistory=ref<ConversionNumericHistoryEntry[]|null>(null);
const numericFiles=ref<File[]>([]),confidence=ref(0.25),nmsIou=ref(0.7);
const numericDialog=ref(false),numericBusy=ref(false),numericError=ref('');
const numericResult=ref<ConversionNumericHistoryEntry|null>(null);
let pendingNumeric:{body:FormData;id:string}|null=null;
const actor=useWorkspace().actorKey;
const numericStorageKey='numeric-validation:'+JSON.stringify([actor,projectId,jobId]);
const numericUnknown=ref(false),pendingNumericId=ref(''),pendingRequestId=ref('');
interface NumericSamples {digests:string[];confidence:number;nmsIou:number}
const originalSamples=ref<NumericSamples>(),numericMissing=ref(false);
const validSampleIntent=(data:NumericSamples|undefined)=>!!data&&Array.isArray(data.digests)
  &&data.digests.length>0&&data.digests.length<=12&&data.digests.every(value=>/^[a-f0-9]{64}$/.test(value))
  &&data.confidence>0&&data.confidence<1&&data.nmsIou>0&&data.nmsIou<1;
function clearNumericIntent(){
  sessionStorage.removeItem(numericStorageKey);
  pendingNumeric=null;
  originalSamples.value=undefined;numericMissing.value=false;
  pendingNumericId.value='';
  pendingRequestId.value='';
  numericUnknown.value=false;
}
function restoreNumericIntent(){
  try{
    const raw=sessionStorage.getItem(numericStorageKey);
    if(!raw)return;
    const intent=JSON.parse(raw);
    if(!/^[A-Za-z0-9_-]{12,80}$/.test(intent.requestId)||!(intent.id===''||/^nv_[a-f0-9]{24}$/.test(intent.id)))throw new Error('待核验记录无效');
    if(validSampleIntent(intent.samples))originalSamples.value=intent.samples;
    pendingNumericId.value=intent.id;
    pendingRequestId.value=intent.requestId;
    numericUnknown.value=true;
    void checkPendingNumeric();
  }catch(error){numericUnknown.value=true;numericError.value=browseError(error)}
}
const ACTIVE=new Set(['queued','pending','waiting_resource','running','preparing','converting','recovering','submitted','waiting','starting','uploading','downloading','validating','stopping','cancel_requested']);
const STOPPABLE=new Set(['queued','waiting_resource','running']);
const stopDialog=ref(false),stopBusy=ref(false),stopReceipt=ref<'accepted'|'unknown'|null>(null),stopError=ref('');
const stopTarget=ref<ConversionJobDetail|null>(null);
const NUMERIC_HINTS:Record<string,string>={'consistent':'数值一致，但仍不等于正式交付准入','difference_detected':'检测到差异','not_comparable':'不可比较','unavailable':'不可用或未完成'};
let alive=true,timer:number|undefined,pollController:AbortController|null=null;
const query=(name:string)=>typeof route.query[name]==='string'?String(route.query[name]):'';
const traceText=(value:unknown)=>typeof value==='string'&&value?value:'';
const algorithmId=computed(()=>query('algorithm')||traceText(job.value?.source_trace?.algorithm_id));
const versionId=computed(()=>query('version')||traceText(job.value?.source_trace?.version_id));
const legacy=computed(()=>legacyUrl(projectId,'算法列表',algorithmId.value,versionId.value,'conversion'));
onBeforeUnmount(()=>{alive=false;stopPolling();controller.abort()});
function fact(value:unknown):string{
  if(value===null||value===undefined||value==='')return '未提供';
  if(Array.isArray(value)||typeof value==='object'){
    try{const text=JSON.stringify(value);return text.length>400?`${text.slice(0,400)}…`:text}catch{return String(value)}
  }
  return String(value);
}
function facts(value:unknown,max=60):[string,unknown][]{
  const source=value&&typeof value==='object'?Object.entries(value as Record<string,unknown>):[];
  return source.slice(0,max).map(([key,item])=>[key,fact(item)] as [string,unknown]);
}
function stopPolling(){if(timer!==undefined){window.clearInterval(timer);timer=undefined}pollController?.abort();pollController=null}
function startPolling(){
  stopPolling();
  timer=window.setInterval(()=>{void refreshSilently()},3000);
}
async function refreshSilently(){
  if(!alive||reads.busy.job)return;
  pollController?.abort();
  const current=new AbortController();
  pollController=current;
  try{
    const latest=await loadConversionJob(projectId,jobId,current.signal);
    if(!alive||current.signal.aborted||latest.id!==jobId)return;
    const wasActive=ACTIVE.has(String(job.value?.status||'').toLowerCase());
    job.value=latest;
    if(!ACTIVE.has(String(latest.status||'').toLowerCase())){
      stopPolling();
      if(wasActive)void loadLog();
    }
  }catch{/* keep the last proven state; the next tick retries */}
}
function loadJob(){
  return reads.run('job',signal=>loadConversionJob(projectId,jobId,signal),value=>{
    if(!alive||value.id!==jobId)return;
    job.value=value;
    if(ACTIVE.has(String(value.status||'').toLowerCase()))startPolling();
    else stopPolling();
  });
}
function loadLog(){
  return reads.run('log',signal=>loadConversionLog(projectId,jobId,signal),value=>{if(alive)log.value=value});
}
function loadNumericHistory(){
  numericHistory.value=null;
  return reads.run('numericHistory',signal=>loadConversionNumericHistory(projectId,jobId,signal),value=>{numericHistory.value=value});
}
const canStartNumeric=computed(()=>['done','blocked_by_hardware'].includes(String(job.value?.status||'').toLowerCase())&&
  /\.pt(?:h)?$/i.test(job.value?.source_name||'')&&
  job.value?.outputs?.some(output=>/\.onnx$/i.test(output.rel||output.name||''))&&!reads.errors.job);
const validNumericInput=computed(()=>numericFiles.value.length>=1&&numericFiles.value.length<=12&&
  numericFiles.value.every(file=>file.size>0&&file.size<=10*1024*1024&&/\.(jpe?g|png|webp|bmp)$/i.test(file.name))&&
  numericFiles.value.reduce((size,file)=>size+file.size,0)<=60*1024*1024&&
  confidence.value>0&&confidence.value<1&&nmsIou.value>0&&nmsIou.value<1);
function selectNumericFiles(event:Event){
  numericFiles.value=Array.from((event.target as HTMLInputElement).files||[]);
  numericError.value='';
}
async function sampleDigests(files:File[]){
  const digests:string[]=[];
  for(const file of files){
    controller.signal.throwIfAborted();
    digests.push(digestHex(await sha256Bytes(await file.arrayBuffer())));
  }
  return digests;
}
function verificationBody(files:File[],requestId:string,params:NumericSamples){
  const body=new FormData();
  for(const file of files)body.append('files',file,file.name);
  body.set('request_id',requestId);
  body.set('confidence',String(params.confidence));
  body.set('nms_iou',String(params.nmsIou));
  if(params.digests.length)body.set('sample_sha256',params.digests.join(','));
  return body;
}
async function recoverNumericFiles(){
  const samples=originalSamples.value,files=[...numericFiles.value],requestId=pendingRequestId.value,id=pendingNumericId.value;
  if(!samples||!numericMissing.value||!requestId||!validNumericInput.value||numericBusy.value||reads.busy.numericResult)return;
  if(!window.confirm('确认按原图片和原阈值重试同一验证请求？'))return;
  numericBusy.value=true;numericError.value='';
  try{
    const digests=await sampleDigests(files);
    if(digests.join(',')!==samples.digests.join(','))throw new Error('图片内容或顺序与原请求不同');
    if(!alive||pendingRequestId.value!==requestId)return;
    pendingNumeric={id,body:verificationBody(files,requestId,samples)};
  }catch(error){if(alive)numericError.value=browseError(error)}
  finally{if(alive)numericBusy.value=false}
  if(alive&&pendingNumeric)await sendNumericValidation(true);
}
async function sendNumericValidation(retrying=false){
  if(!alive||numericBusy.value||!pendingNumeric)return;
  numericBusy.value=true;
  numericError.value='';
  reads.cancel('numericResult');
  const {body,id}=pendingNumeric;
  try{
    if(!actor||workspaceActorKey(await readWorkspaceSession(controller.signal))!==actor)throw new Error('会话已变化，请重新打开转换任务');
    const value=await createNumericValidation(projectId,jobId,id,body,controller.signal);
    if(!alive)return;
    numericResult.value=value;
    clearNumericIntent();
    void loadNumericHistory();
  }catch(error){
    if(!alive)return;
    numericError.value=browseError(error);
    const httpStatus=(error as {httpStatus?:number}).httpStatus;
    if(!retrying&&httpStatus&&[400,401,403,413,422].includes(httpStatus)){
      try{clearNumericIntent()}catch{numericUnknown.value=true}
    }else numericUnknown.value=true;
  }finally{if(alive)numericBusy.value=false}
}
async function confirmNumeric(){
  if(!numericDialog.value||!canStartNumeric.value||!validNumericInput.value||pendingNumeric||numericUnknown.value||numericBusy.value)return;
  numericDialog.value=false;
  numericBusy.value=true;
  numericError.value='';
  const files=[...numericFiles.value],requestId=newConversionRequestId();
  const samples:NumericSamples={digests:[],confidence:confidence.value,nmsIou:nmsIou.value};
  try{
    samples.digests=await sampleDigests(files);
    const id=await resolveNumericVerificationId(projectId,jobId,requestId);
    if(!actor||workspaceActorKey(await readWorkspaceSession(controller.signal))!==actor)throw new Error('会话已变化，请重新打开转换任务');
    if(!alive)return;
    originalSamples.value=validSampleIntent(samples)?samples:undefined;
    sessionStorage.setItem(numericStorageKey,JSON.stringify({requestId,id,samples:originalSamples.value}));
    pendingNumeric={body:verificationBody(files,requestId,samples),id};
    pendingNumericId.value=id;
    pendingRequestId.value=requestId;
  }catch(error){if(alive)numericError.value=browseError(error)}
  finally{if(alive)numericBusy.value=false}
  if(alive&&pendingNumeric){numericResult.value=null;await sendNumericValidation()}
}
function applyNumericResult(value:ConversionNumericHistoryEntry){
  numericResult.value=value;
  if(value.id===pendingNumericId.value){
    clearNumericIntent();
    numericError.value='';
  }
}
function checkPendingNumeric(){
  const requestId=pendingRequestId.value,id=pendingNumericId.value;
  if(!requestId)return;
  return reads.run('numericResult',async signal=>{
    if(!actor||workspaceActorKey(await readWorkspaceSession(signal))!==actor)throw new Error('会话已变化，请重新打开转换任务');
    numericMissing.value=false;
    try{return await (id?loadNumericValidation(projectId,jobId,id,signal):findNumericValidation(projectId,jobId,requestId,signal))}
    catch(error){
      if(!signal.aborted&&(error as {httpStatus?:number}).httpStatus===404&&pendingRequestId.value===requestId)numericMissing.value=true;
      throw error;
    }
  },value=>{
    if(pendingRequestId.value!==requestId)return;
    numericResult.value=value;
    clearNumericIntent();
    numericError.value='';
    void loadNumericHistory();
  });
}
function readNumericResult(id:string){
  return reads.run('numericResult',signal=>loadNumericValidation(projectId,jobId,id,signal),applyNumericResult);
}
function refresh(){stopPolling();void loadJob();void loadLog()}
function cancellationRequested(value:ConversionJobDetail|null){
  return value?.cancel_requested===true ||
    [value?.status,value?.task_status,value?.durable_status].some(state=>String(state||'').toLowerCase()==='cancel_requested') ||
    String(value?.status||'').toLowerCase()==='stopping';
}
function canStopJob(value:ConversionJobDetail|null){
  return STOPPABLE.has(String(value?.status||'').toLowerCase())&&!cancellationRequested(value);
}
const canStop=computed(()=>canStopJob(job.value)&&!reads.errors.job&&!stopReceipt.value);
function openStopDialog(){
  stopTarget.value=job.value;
  stopDialog.value=true;
}
const stopNotice=computed(()=>{
  const state=String(job.value?.status||'').toLowerCase();
  if(['stopped','cancelled','canceled'].includes(state))return '转换任务已停止';
  if(stopReceipt.value&&state&&!ACTIVE.has(state))return '任务已结束，最终结果见当前任务状态。';
  if(cancellationRequested(job.value)||stopReceipt.value==='accepted')return '停止请求已登记，等待任务状态更新。';
  if(stopReceipt.value==='unknown')return '停止回执未知。请刷新并核对当前任务状态。';
  return '';
});
async function confirmStop(){
  if(!stopDialog.value||stopBusy.value||!canStop.value)return;
  stopBusy.value=true;
  stopDialog.value=false;
  stopError.value='';
  stopPolling();
  const confirmed=stopTarget.value;
  let sent=false;
  try{
    const latest=await loadConversionJob(projectId,jobId,controller.signal);
    if(!alive)return;
    job.value=latest;
    if(latest.source_id!==confirmed?.source_id||latest.target!==confirmed?.target)
      throw new Error('源模型或目标格式已变化，请核对后重新确认。');
    if(!canStopJob(latest))return;
    sent=true;
    await stopConversionJob(projectId,jobId,controller.signal);
    if(alive)stopReceipt.value='accepted';
  }catch(error){
    if(alive){
      if(sent)stopReceipt.value='unknown';
      stopError.value=browseError(error);
    }
  }finally{
    if(alive){stopBusy.value=false;refresh()}
  }
}
function back(){void router.push(algorithmId.value&&versionId.value?{name:'version-conversions',params:{projectId,algorithmId:algorithmId.value,versionId:versionId.value}}:{name:'algorithms',params:{projectId}})}
onMounted(()=>{void loadJob();void loadLog();restoreNumericIntent()});
const progress=computed(()=>{const value=Number(job.value?.progress||0);return Number.isFinite(value)?Math.max(0,Math.min(100,value)):0});
const status=computed(()=>String(job.value?.status||''));
const quality=computed(()=>job.value?.delivery_quality);
const numeric=computed(()=>job.value?.numeric_validation);
const numericLabel=computed(()=>{const value=String(job.value?.numeric_status||'');return value?`${value}（${NUMERIC_HINTS[value]||'语义以后端为准'}）`:'NOT_VERIFIED（尚无已发布的数值验证摘要）'});
const runtimeLabel=computed(()=>{
  const validation=String(job.value?.validation_status||'').toLowerCase();
  if(job.value?.runtime_verified===true)return 'VERIFIED（已记录目标 Runtime 真实加载验证）';
  if(validation==='runtime_verified')return 'VERIFIED（validation_status=runtime_verified）';
  if(validation==='hardware_verified')return 'VERIFIED（已记录目标硬件 Runtime 验收）';
  return 'NOT_VERIFIED（未记录真实 Runtime 验证）';
});
const hardwareLabel=computed(()=>{
  const acceptance=String(quality.value?.hardware_acceptance||'');
  if(acceptance)return acceptance==='VERIFIED'?'VERIFIED（目标硬件实机验收）':`${acceptance}（未完成实机验收）`;
  return job.value?.hardware_verified===true?'VERIFIED（目标硬件实机验收）':'NOT_VERIFIED（未完成实机验收）';
});
const supportsBoardVerification=computed(()=>['rockchip','rknn'].includes(String(job.value?.target||'').toLowerCase())&&
  ['done','blocked_by_hardware'].includes(status.value.toLowerCase()));
const eligibilityLabel=computed(()=>quality.value?.formal_activation_eligible===true?'允许正式交付/激活':'不允许（未满足正式交付准入）');
const tagType=computed<'success'|'warning'|'danger'|'info'>(()=>{
  const value=status.value.toLowerCase();
  if(value==='done')return 'success';
  if(['failed','stopped','cancelled','blocked_by_hardware','blocked_by_environment'].includes(value))return 'danger';
  if(['queued','waiting_resource','pending','waiting'].includes(value))return 'warning';
  return 'info';
});
const statusFacts=computed<[string,unknown][]>(()=>[
  ['转换任务 ID',job.value?.id],['Durable Task ID',job.value?.task_id],['转换状态',job.value?.status],
  ['任务状态',job.value?.task_status],['持久状态',job.value?.durable_status],['阶段',job.value?.stage],
  ['进度',`${progress.value}%`],['目标格式',job.value?.target],['源模型',job.value?.source_name],
  ['转换资源',job.value?.resource?.name||job.value?.resource_id],['执行模式',job.value?.resource?.mode],
  ['Worker',job.value?.worker_id],['等待原因',job.value?.resource_wait_reason],
  ['创建时间',job.value?.created_at],['开始时间',job.value?.started_at],['完成时间',job.value?.finished_at],
  ['错误代码',job.value?.error_code],['错误',job.value?.error],['消息',job.value?.message],['建议',job.value?.solution],
]);
const qualityFacts=computed<[string,unknown][]>(()=>[
  ['转换执行状态',job.value?.status],['转换完成状态',job.value?.conversion_status],['产物完整性状态',job.value?.validation_status],
  ['数值质量状态',numericLabel.value],['数值验证结论',numeric.value?.verdict],['数值验证绑定',numeric.value?.binding_status],
  ['数值验证样本数',numeric.value?.sample_count],['数值验证完成时间',numeric.value?.completed_at],
  ['Runtime 验证',runtimeLabel.value],['目标硬件验收',hardwareLabel.value],
  ['发布准入',eligibilityLabel.value],['交付呈现',quality.value?.delivery_presentation],
  ['发布状态字段',job.value?.publication_status],['附件交付',quality.value?.attachment_delivery_allowed===true?'允许':'不允许'],
  ['数值状态单独充分',quality.value?.numeric_status_alone_is_sufficient===false?'否（不会单独作为准入依据）':'未提供'],
]);
const manifestName=computed(()=>{const path=String(job.value?.manifest_path||'');return path?path.split(/[\\/]/).pop()||'':''});
const manifestFacts=computed<[string,unknown][]>(()=>[
  ['Manifest 文件',manifestName.value||'未提供'],['Manifest 摘要',job.value?.manifest_digest],
  ['源模型 SHA256 复核',job.value?.source_sha256_recheck],
  ...facts(job.value?.manifest_integrity,20),
]);
const sourceFacts=computed<[string,unknown][]>(()=>[
  ['源模型 ID',job.value?.source_trace?.source_id||job.value?.source_id],
  ['算法 ID',job.value?.source_trace?.algorithm_id],
  ['版本 ID',job.value?.source_trace?.version_id],
  ['源模型 SHA256',job.value?.source_trace?.sha256],
]);
const executionFacts=computed<[string,unknown][]>(()=>facts(job.value?.execution_evidence,40));
const hardwareFacts=computed<[string,unknown][]>(()=>facts(job.value?.hardware_verification,20));
const paramFacts=computed<[string,unknown][]>(()=>facts(job.value?.params,80));
const requestedParamFacts=computed<[string,unknown][]>(()=>facts(job.value?.requested_params,80));
const outputs=computed(()=>job.value?.outputs||[]);
const artifacts=computed(()=>quality.value?.artifacts||[]);
const unregistered=computed(()=>quality.value?.unregistered_outputs||[]);
function downloadUrl(output:ConversionJobOutput){
  const rel=String(output.rel||'');
  if(!rel)return '';
  const extension=(rel.split('.').pop()||'').toLowerCase();
  if(['py','md'].includes(extension))return '';
  return `/api/v39/projects/${encodeURIComponent(projectId)}/deploy/jobs/${encodeURIComponent(jobId)}/artifact?rel=${encodeURIComponent(rel)}`;
}
</script>
<template>
<section class="conversion-detail-page">
 <header class="detail-head"><div><button class="back" @click="back">返回转换记录</button><h2>转换任务详情</h2></div><div class="head-actions"><el-button :loading="reads.busy.job" :disabled="stopBusy" @click="refresh">刷新</el-button><a :href="legacy">原任务操作与验证</a></div></header>
 <el-alert v-if="reads.errors.job" :title="reads.errors.job" type="error" :closable="false"/>
 <el-alert v-if="job&&reads.errors.job" title="以下为上次成功读取的快照，不能作为最新状态。" type="warning" :closable="false"/>
 <el-skeleton v-if="reads.busy.job&&!job" :rows="10" animated/>
 <template v-else-if="job">
  <section class="card" aria-label="转换任务状态与进度">
   <header class="card-head"><h3>任务状态与进度</h3><el-tag :type="tagType" effect="plain">{{ job.status||'未提供' }}</el-tag></header>
   <div class="status-line"><strong>{{ job.stage||'阶段未提供' }}</strong><span v-if="job.task_status">任务状态 {{ job.task_status }}</span><span v-if="job.durable_status">持久状态 {{ job.durable_status }}</span></div>
   <el-progress :percentage="progress" :stroke-width="10"/>
   <ReadOnlyFacts :fields="statusFacts"/>
   <el-button v-if="canStop" type="danger" plain :loading="stopBusy" :disabled="reads.busy.job" @click="openStopDialog">停止转换</el-button>
   <p v-if="stopNotice" role="status">{{ stopNotice }}</p>
   <p v-if="stopError&&(!stopReceipt||(stopReceipt==='unknown'&&ACTIVE.has(status.toLowerCase())&&!cancellationRequested(job)))" role="alert">{{ stopError }}</p>
   <el-alert v-if="job.error" :title="`转换错误：${job.error}`" type="error" :closable="false"/>
   <el-alert v-else-if="job.message" :title="job.message" type="info" :closable="false"/>
  </section>
  <section class="card" aria-label="质量与验证投影">
   <h3>质量与验证</h3>
   <ReadOnlyFacts :fields="qualityFacts"/>
   <ul v-if="quality?.reasons?.length" class="reasons"><li v-for="(reason,index) in quality.reasons" :key="index">{{ reason }}</li></ul>
   <h4 v-if="hardwareFacts.length">目标硬件验收字段</h4>
   <ReadOnlyFacts v-if="hardwareFacts.length" :fields="hardwareFacts"/>
   <p class="evidence-note">数值一致、Runtime 加载与目标硬件验收分别记录、互不代替；未知或未记录一律显示 NOT_VERIFIED。数值状态不会单独构成正式交付准入。</p>
   <ConversionHardwareValidation v-if="supportsBoardVerification" :project-id="projectId" :job-id="jobId" :verified="job.hardware_verified===true" :stale="!!reads.errors.job" @refresh="refresh"/>
   <section v-if="canStartNumeric" aria-label="发起数值验证">
    <h4>PT／ONNX 数值验证</h4>
    <p class="evidence-note">选择 1～12 张真实图片，单图最多 10 MB，整批最多 60 MB。</p>
    <fieldset :disabled="numericBusy||numericUnknown||numericDialog">
     <label>验证图片 <input type="file" multiple accept=".jpg,.jpeg,.png,.webp,.bmp" @change="selectNumericFiles"></label>
     <label>置信度 <input v-model.number="confidence" type="number" min="0.001" max="0.999" step="0.001"></label>
     <label>NMS IoU <input v-model.number="nmsIou" type="number" min="0.001" max="0.999" step="0.001"></label>
     <el-button :disabled="!validNumericInput" @click="numericDialog=true">开始数值验证</el-button>
    </fieldset>
   </section>
   <p v-if="numericError" role="alert">{{ numericError }}</p>
   <div v-if="numericUnknown" role="status">
    <p>数值验证提交回执未知。</p>
    <el-button v-if="pendingRequestId" :loading="reads.busy.numericResult" @click="checkPendingNumeric">核对原验证请求</el-button>
    <el-button v-if="pendingNumeric && (!pendingNumericId||reads.errors.numericResult)" :loading="numericBusy" :disabled="reads.busy.numericResult" @click="sendNumericValidation(true)">重试同一请求</el-button>
    <template v-else-if="originalSamples&&numericMissing">
     <label>按原顺序重选验证图片 <input type="file" multiple accept=".jpg,.jpeg,.png,.webp,.bmp" :disabled="numericBusy" @change="selectNumericFiles"></label>
     <el-button :disabled="!validNumericInput||reads.busy.numericResult" :loading="numericBusy" @click="recoverNumericFiles">核对图片并重试原请求</el-button>
    </template>
   </div>
   <el-alert v-if="reads.errors.numericResult" :title="reads.errors.numericResult" type="error" :closable="false"/>
   <div v-if="numericResult">
    <ReadOnlyFacts :fields="[['验证任务 ID',numericResult.id],['验证任务状态',numericResult.task.status],['阶段',numericResult.task.phase],['原始张量结论',numericResult.result?.raw_verdict],['检测框比较',numericResult.result?.detection_status],['报告结论',numericResult.result?.verdict],['实际样本数',numericResult.result?.sample_count],['错误',numericResult.result?.error||numericResult.task.error]]"/>
    <p v-if="numericResult.result?.detection_status==='unavailable'" class="evidence-note">当前报告仅提供数值对照，检测框一致性未验证。</p>
    <el-button :loading="reads.busy.numericResult" @click="readNumericResult(numericResult.id)">刷新验证报告</el-button>
   </div>
   <header class="card-head numeric-history-head">
    <h4>数值验证历史</h4>
    <el-button size="small" :loading="reads.busy.numericHistory" @click="loadNumericHistory">{{numericHistory?'刷新数值验证历史':'读取数值验证历史'}}</el-button>
   </header>
   <el-alert v-if="reads.errors.numericHistory" :title="reads.errors.numericHistory" type="error" :closable="false"/>
   <p v-if="numericHistory" class="evidence-note">最多显示 20 条近期记录。当前产物的有效绑定与交付准入见本节上方。</p>
   <el-table v-if="numericHistory" :data="numericHistory" row-key="id" max-height="400" empty-text="近期范围内没有数值验证记录">
    <el-table-column prop="id" label="验证任务 ID" min-width="180"/>
    <el-table-column label="创建时间" min-width="160"><template #default="{row}">{{row.created_at||'未提供'}}</template></el-table-column>
    <el-table-column label="任务状态" min-width="130"><template #default="{row}">{{row.task.status||'未提供'}}</template></el-table-column>
    <el-table-column label="历史报告结论" min-width="140"><template #default="{row}">{{row.result?.verdict||'未提供'}}</template></el-table-column>
    <el-table-column label="样本数" min-width="90"><template #default="{row}">{{row.result?.sample_count??'未提供'}}</template></el-table-column>
    <el-table-column label="任务错误" min-width="150"><template #default="{row}">{{row.task.error||row.result?.error||'未提供'}}</template></el-table-column>
    <el-table-column label="报告" width="100"><template #default="{row}"><el-button link @click="readNumericResult(row.id)">查看报告</el-button></template></el-table-column>
   </el-table>
  </section>
  <section class="card" aria-label="Manifest 摘要">
   <h3>Manifest 摘要</h3>
   <h4>源模型身份</h4>
   <ReadOnlyFacts :fields="sourceFacts"/>
   <ReadOnlyFacts :fields="manifestFacts"/>
   <p class="evidence-note">本页只投影转换任务记录中的 manifest 身份与完整性字段；后端当前没有独立的 manifest 汇总读取接口，完整 manifest 内容仍由原转换任务目录与原管理入口持有。</p>
   <template v-if="executionFacts.length"><h4>执行证据</h4><ReadOnlyFacts :fields="executionFacts"/></template>
  </section>
  <section class="card" aria-label="转换产物">
   <h3>转换产物</h3>
   <p v-if="!outputs.length" class="evidence-note">没有提供产物证据，不能据此生成下载链接。</p>
   <el-table v-else :data="outputs.slice(0,20)" empty-text="没有提供产物证据">
    <el-table-column label="产物" min-width="200"><template #default="{row}"><strong>{{ row.name||'名称未提供' }}</strong><small>{{ row.rel||'相对路径未提供' }}</small></template></el-table-column>
    <el-table-column label="大小" min-width="90"><template #default="{row}">{{ row.size_mb!=null?row.size_mb+' MB':row.size_bytes!=null?row.size_bytes+' B':'未提供' }}</template></el-table-column>
    <el-table-column label="SHA256" min-width="170"><template #default="{row}"><code :title="row.sha256">{{ row.sha256?String(row.sha256).slice(0,16)+'…':'未提供' }}</code></template></el-table-column>
    <el-table-column label="完整性记录" min-width="120"><template #default="{row}">{{ row.validation_status||'未提供' }}</template></el-table-column>
    <el-table-column label="" width="110"><template #default="{row}"><a v-if="downloadUrl(row)" :href="downloadUrl(row)">归档下载</a></template></el-table-column>
   </el-table>
   <template v-if="artifacts.length"><h4>已登记模型资产（交付质量投影）</h4><el-table :data="artifacts" max-height="360"><el-table-column prop="artifact_id" label="Artifact ID" min-width="150"/><el-table-column label="文件" min-width="160"><template #default="{row}">{{ row.file_name||'未提供' }}</template></el-table-column><el-table-column label="交付呈现" min-width="150"><template #default="{row}">{{ row.delivery_presentation||'未提供' }}</template></el-table-column><el-table-column label="正式交付准入" min-width="110"><template #default="{row}">{{ row.formal_activation_eligible===true?'允许':'不允许' }}</template></el-table-column><el-table-column label="硬件验收" min-width="110"><template #default="{row}">{{ row.hardware_acceptance||'NOT_VERIFIED' }}</template></el-table-column><el-table-column label="原因" min-width="200"><template #default="{row}">{{ (row.reasons||[]).join('；')||'未提供' }}</template></el-table-column></el-table></template>
   <template v-if="unregistered.length"><h4>未登记为模型资产的原始输出</h4><ReadOnlyFacts :fields="unregistered.slice(0,20).map(row=>[row.name||row.rel||'输出',`${row.delivery_presentation||'未提供'}${row.archive_download_allowed?' · 允许归档下载':' · 不可下载'}`])"/></template>
  </section>
  <section class="card" aria-label="转换日志">
   <header class="card-head"><h3>转换日志</h3><el-button size="small" :loading="reads.busy.log" @click="loadLog">刷新日志</el-button></header>
   <el-alert v-if="reads.errors.log" :title="reads.errors.log" type="error" :closable="false"/>
   <pre class="log">{{ log||'暂无转换日志' }}</pre>
  </section>
  <section class="card" aria-label="转换参数">
   <h3>转换参数</h3>
   <details :open="paramFacts.length<=12"><summary>实际转换参数</summary><ReadOnlyFacts :fields="paramFacts"/><p v-if="paramFacts.length>=80" class="evidence-note">仅展示前 80 个字段，完整参数以原任务记录为准。</p></details>
   <details><summary>原请求参数</summary><ReadOnlyFacts :fields="requestedParamFacts"/></details>
  </section>
 </template>
 <el-empty v-else-if="!reads.busy.job" description="没有读取到转换任务记录"/>
 <el-dialog v-model="stopDialog" title="停止转换" width="min(520px, 92vw)">
  <p>停止任务 {{ jobId }}，源模型 {{ stopTarget?.source_name||stopTarget?.source_id||'未提供' }}，目标格式 {{ stopTarget?.target_name||stopTarget?.target||'未提供' }}？</p>
  <template #footer>
   <el-button @click="stopDialog=false">返回</el-button>
   <el-button type="danger" :disabled="!canStop" @click="confirmStop">确认停止转换</el-button>
  </template>
 </el-dialog>
 <el-dialog v-model="numericDialog" title="确认数值验证" width="min(520px, 92vw)">
  <p>转换任务 {{ jobId }} · {{ job?.source_name||job?.source_id||'源模型未提供' }} · {{ job?.target_name||job?.target||'目标格式未提供' }}</p>
  <p>使用 {{ numericFiles.length }} 张真实图片对照冻结的 PT 源模型与 ONNX 产物，置信度 {{ confidence }}，NMS IoU {{ nmsIou }}。</p>
  <template #footer>
   <el-button @click="numericDialog=false">返回</el-button>
   <el-button type="primary" :disabled="!canStartNumeric||!validNumericInput" @click="confirmNumeric">确认发起验证</el-button>
  </template>
 </el-dialog>
</section>
</template>
<style scoped>
.conversion-detail-page{padding:24px;min-width:0}.detail-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}.detail-head h2{margin:8px 0 6px;font-size:22px}.detail-head p{margin:0;color:#64748b;line-height:1.7;max-width:860px}.head-actions{display:flex;align-items:center;gap:12px;flex-shrink:0}.back{border:0;background:transparent;color:#2563eb;cursor:pointer;padding:0}.card{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin-bottom:16px;min-width:0}.card h3{margin:0 0 14px;font-size:17px}.card h4{margin:18px 0 10px;font-size:14px}.card-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}.card-head h3{margin:0}.status-line{display:flex;flex-wrap:wrap;gap:12px;align-items:center;font-size:13px;color:#475569;margin-bottom:12px}.status-line strong{color:#0f172a}.card :deep(.readonly-facts){grid-template-columns:minmax(120px,.8fr) minmax(0,1.6fr);font-size:13px;gap:8px}.evidence-note{color:#64748b;font-size:12px;line-height:1.7;margin:10px 0 0}.reasons{margin:10px 0;padding-left:20px;color:#b45309;font-size:13px;line-height:1.7;overflow-wrap:anywhere}.log{white-space:pre-wrap;overflow:auto;max-height:360px;background:#f8fafc;padding:12px;border-radius:8px;font-size:12px}.card small{display:block;color:#64748b;font-size:11px;line-height:1.5}details{margin-top:10px}summary{cursor:pointer;font-size:13px;color:#334155;margin-bottom:8px}code{font-size:11px;overflow-wrap:anywhere}@media(max-width:760px){.detail-head{flex-wrap:wrap}.head-actions{flex-wrap:wrap}}
</style>
