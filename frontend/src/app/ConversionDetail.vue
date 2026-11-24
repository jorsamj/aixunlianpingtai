<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {legacyUrl} from './navigation';
import {useReadScope} from '../composables/useReadScope';
import ReadOnlyFacts from '../components/ReadOnlyFacts.vue';
import {browseError} from '../api/model-browse';
import {loadConversionJob,loadConversionLog} from '../api/conversion-jobs';
import type {ConversionJobDetail,ConversionJobOutput} from '../types/conversion-job';
const props=defineProps<{projectId:string;jobId:string}>();
const projectId=props.projectId,jobId=props.jobId,route=useRoute(),router=useRouter();
const controller=new AbortController(),reads=useReadScope(controller);
const job=ref<ConversionJobDetail|null>(null),log=ref('');
const ACTIVE=new Set(['queued','pending','waiting_resource','running','preparing','converting','recovering','submitted','waiting','starting','uploading','downloading','validating','stopping']);
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
function refresh(){stopPolling();void loadJob();void loadLog()}
function back(){void router.push(algorithmId.value&&versionId.value?{name:'version-conversions',params:{projectId,algorithmId:algorithmId.value,versionId:versionId.value}}:{name:'algorithms',params:{projectId}})}
onMounted(()=>{void loadJob();void loadLog()});
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
 <header class="detail-head"><div><button class="back" @click="back">返回转换记录</button><h2>转换任务详情</h2><p>状态、产物、日志与质量投影均来自后端既有返回；本页只读，不提供执行转换、外部发布或设备激活操作。</p></div><div class="head-actions"><el-button :loading="reads.busy.job" @click="refresh">刷新</el-button><a :href="legacy">原任务操作与验证</a></div></header>
 <el-alert v-if="reads.errors.job" :title="reads.errors.job" type="error" :closable="false"/>
 <el-alert v-if="job&&reads.errors.job" title="以下为上次成功读取的快照，不能作为最新状态。" type="warning" :closable="false"/>
 <el-skeleton v-if="reads.busy.job&&!job" :rows="10" animated/>
 <template v-else-if="job">
  <section class="card" aria-label="转换任务状态与进度">
   <header class="card-head"><h3>任务状态与进度</h3><el-tag :type="tagType" effect="plain">{{ job.status||'未提供' }}</el-tag></header>
   <div class="status-line"><strong>{{ job.stage||'阶段未提供' }}</strong><span v-if="job.task_status">任务状态 {{ job.task_status }}</span><span v-if="job.durable_status">持久状态 {{ job.durable_status }}</span></div>
   <el-progress :percentage="progress" :stroke-width="10"/>
   <ReadOnlyFacts :fields="statusFacts"/>
   <el-alert v-if="job.error" :title="`转换错误：${job.error}`" type="error" :closable="false"/>
   <el-alert v-else-if="job.message" :title="job.message" type="info" :closable="false"/>
  </section>
  <section class="card" aria-label="质量与验证投影">
   <h3>质量 / 验证投影（只读）</h3>
   <ReadOnlyFacts :fields="qualityFacts"/>
   <ul v-if="quality?.reasons?.length" class="reasons"><li v-for="(reason,index) in quality.reasons" :key="index">{{ reason }}</li></ul>
   <h4 v-if="hardwareFacts.length">目标硬件验收字段</h4>
   <ReadOnlyFacts v-if="hardwareFacts.length" :fields="hardwareFacts"/>
   <p class="evidence-note">数值一致、Runtime 加载与目标硬件验收分别记录、互不代替；未知或未记录一律显示 NOT_VERIFIED。数值状态不会单独构成正式交付准入。</p>
  </section>
  <section class="card" aria-label="Manifest 摘要">
   <h3>Manifest 摘要</h3>
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
    <el-table-column label="" width="80"><template #default="{row}"><a v-if="downloadUrl(row)" :href="downloadUrl(row)">下载</a></template></el-table-column>
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
</section>
</template>
<style scoped>
.conversion-detail-page{padding:24px;min-width:0}.detail-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}.detail-head h2{margin:8px 0 6px;font-size:22px}.detail-head p{margin:0;color:#64748b;line-height:1.7;max-width:860px}.head-actions{display:flex;align-items:center;gap:12px;flex-shrink:0}.back{border:0;background:transparent;color:#2563eb;cursor:pointer;padding:0}.card{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin-bottom:16px;min-width:0}.card h3{margin:0 0 14px;font-size:17px}.card h4{margin:18px 0 10px;font-size:14px}.card-head{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:12px}.card-head h3{margin:0}.status-line{display:flex;flex-wrap:wrap;gap:12px;align-items:center;font-size:13px;color:#475569;margin-bottom:12px}.status-line strong{color:#0f172a}.card :deep(.readonly-facts){grid-template-columns:minmax(120px,.8fr) minmax(0,1.6fr);font-size:13px;gap:8px}.evidence-note{color:#64748b;font-size:12px;line-height:1.7;margin:10px 0 0}.reasons{margin:10px 0;padding-left:20px;color:#b45309;font-size:13px;line-height:1.7;overflow-wrap:anywhere}.log{white-space:pre-wrap;overflow:auto;max-height:360px;background:#f8fafc;padding:12px;border-radius:8px;font-size:12px}.card small{display:block;color:#64748b;font-size:11px;line-height:1.5}details{margin-top:10px}summary{cursor:pointer;font-size:13px;color:#334155;margin-bottom:8px}code{font-size:11px;overflow-wrap:anywhere}@media(max-width:760px){.detail-head{flex-wrap:wrap}.head-actions{flex-wrap:wrap}}
</style>
