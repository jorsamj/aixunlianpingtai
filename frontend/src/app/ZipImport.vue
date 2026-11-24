<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,reactive,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {legacyUrl} from './navigation';
import {projectLabels} from '../api/upload-batches';
import {mountUppyZipAdapter} from '../../../static/modules/uppy-zip-adapter.js';
import {installZipImportRuntime} from '../../../static/modules/zip-import-runtime.js';
import type {ZipImportRuntime} from '../../../static/modules/zip-import-runtime.js';

interface ZipJob {id:string;file_name?:string;status?:string;stage?:string;message?:string;
  progress?:number|null;zip_display_progress?:number;queue_position?:number|null;
  report?:{imported_images?:number;annotated_images?:number;failed?:number};
  error?:string;created_at?:string;upload_id?:string}
const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId);
const target=ref<HTMLElement|null>(null),modalRoot=ref<HTMLElement|null>(null);
const jobs=ref<ZipJob[]>([]),error=ref(''),notice=ref(''),busy=ref(false);
const labels=ref<{code:string;display_name?:string;name?:string}[]>([]);
const transfer=reactive({uploadId:'',jobId:'',phase:'',progress:0,error:''});
const transfers=ref<{key:string;uploadId:string;jobId:string;phase:string;progress:number;error:string}[]>([]);
const paused=ref(false);
const compat:Record<string,unknown>={project:{id:projectId,labels:[]},page:'数据集',labels:[],import411:null,materialBatchFilter61:''};
// One status Owner: the durable ZipImportRuntime keeps polling the existing
// v19 list/detail endpoints. This page only mirrors its in-memory snapshot, so
// the same upload task is never reconciled by two parallel list pollers.
const MIRROR_INTERVAL_MS=1000, MAX_JOBS=50;
let runtime:ZipImportRuntime|null=null,handle:{uppy:unknown;destroy:()=>void}|null=null,mirrorTimer:number|undefined;
const controller=new AbortController();
const alive=()=>!controller.signal.aborted;
const savedGlobals:{[key:string]:unknown}={};
const GLOBAL_KEYS=['modal','closeModal','setPage','refreshLabels414','reloadMaterialPage61',
  'ZipImportRuntime','doUploadZip426','doImportData'];
const STATUS:Record<string,string>={uploading:'正在上传',paused:'已暂停',merging:'服务端合并',validating:'校验与扫描',selecting:'等待标签确认',queued:'后台排队',waiting:'等待处理',running:'正在解压与入库',done:'导入完成',failed:'失败',cancelled:'已取消',unknown:'状态待核验'};
const active=computed(()=>jobs.value.some(job=>['uploading','paused','merging','validating','selecting','queued','waiting','running','unknown'].includes(String(job.status||'').toLowerCase())));
const legacy=legacyUrl(projectId,'数据集','','','material-zip');

function closeModal(){
  const root=modalRoot.value;if(!root)return;
  const layers=root.querySelectorAll('.modal');
  const layer=layers.item(layers.length-1);
  if(layer){try{runtime?.beforeModalClose(layer as HTMLElement)}catch{/* owner already closed */}layer.remove()}
}
function openModal(title:string,html:string){
  const root=modalRoot.value;if(!root)return;
  root.replaceChildren();
  const layer=document.createElement('div');layer.className='modal native-zip-modal';
  layer.innerHTML=`<div class="modal-title"><b>${String(title||'ZIP 数据导入')}</b><button type="button" data-native-zip-close aria-label="关闭">关闭</button></div><div class="modal-body">${html}</div>`;
  root.appendChild(layer);
  layer.querySelector('[data-native-zip-close]')?.addEventListener('click',closeModal);
}
async function loadLabels(){
  try{
    const detail=await projectLabels(projectId,controller.signal);
    const rows=detail.project?.labels??detail.labels;
    labels.value=Array.isArray(rows)?rows:[];
    compat.labels=labels.value;
    (compat.project as {labels?:unknown}).labels=labels.value;
  }catch{/* the original label UI tells the user when nothing matches */}
}
async function loadJobs(reason='native-page-refresh'){
  if(!alive())return;
  try{await runtime?.reconcile?.(reason)}
  catch(cause){if(alive()&&!jobs.value.length)error.value=cause instanceof Error?cause.message:'导入任务读取失败'}
  finally{syncJobs()}
}
function syncJobs(){
  if(!alive())return;
  const snapshot=runtime?.snapshot?.();
  jobs.value=Array.isArray(snapshot?.jobs)?snapshot.jobs.slice(0,MAX_JOBS):[];
}
function jobStatus(job:ZipJob){return STATUS[String(job.status||'').toLowerCase()]||String(job.status||'未提供')}
function jobProgress(job:ZipJob){
  const value=job.zip_display_progress??job.progress;
  return typeof value==='number'&&Number.isFinite(value)?Math.max(0,Math.min(100,Math.round(value))):0;
}
async function openJob(job:ZipJob){
  busy.value=true;
  try{await runtime?.openTask?.(job.id);syncJobs()}
  catch(cause){error.value=cause instanceof Error?cause.message:'打开 ZIP 任务失败'}
  finally{busy.value=false}
}
async function cancelJob(job:ZipJob){
  if(!runtime)return;
  busy.value=true;
  try{await runtime.cancelJob?.(job.id);syncJobs()}
  catch(cause){error.value=cause instanceof Error?cause.message:'取消 ZIP 任务失败'}
  finally{busy.value=false}
}
function viewImported(job:ZipJob){
  void router.push({name:'materials',params:{projectId},query:{source_batch_id:job.id}});
}
function goLegacy(){location.assign(legacy)}
function installShims(){
  const globalWindow=globalThis as unknown as Record<string,unknown>;
  for(const key of GLOBAL_KEYS)savedGlobals[key]=globalWindow[key];
  globalWindow.modal=openModal;
  globalWindow.closeModal=closeModal;
  globalWindow.setPage=(page:string)=>{compat.page=String(page||'数据集')};
  globalWindow.refreshLabels414=async()=>{await loadLabels();return true};
  globalWindow.reloadMaterialPage61=async()=>{await loadJobs();return true};
}
function restoreShims(){
  const globalWindow=globalThis as unknown as Record<string,unknown>;
  for(const [key,value] of Object.entries(savedGlobals)){
    if(value===undefined)delete globalWindow[key];else globalWindow[key]=value;
  }
  const saved=savedGlobals.ZipImportRuntime as {__nativeVueZipRuntime?:boolean}|undefined;
  if(saved?.__nativeVueZipRuntime){
    // Never reattach a destroyed runtime from the previous visit.
    delete globalWindow.ZipImportRuntime;
    delete globalWindow.doUploadZip426;
    delete globalWindow.doImportData;
  }
}
function upsertTransfer(event:Record<string,unknown>){
  const uploadId=String(event.uploadId||'');
  const jobId=String(event.jobId||'');
  const file=(event.file as {name?:string})?.name||'';
  const key=uploadId||jobId||file||String(Date.now());
  const existing=transfers.value.find(row=>row.key===key);
  const next={key,uploadId:uploadId||existing?.uploadId||'',jobId:jobId||existing?.jobId||'',
    phase:String(event.stage||event.message||existing?.phase||''),
    progress:event.type==='progress'?Math.round(Number(event.ratio||0)*100):(existing?.progress||0),
    error:event.type==='error'?String((event.error as Error)?.message||event.message||'ZIP 上传失败'):(existing?.error||'')};
  transfers.value=existing
    ?transfers.value.map(row=>row.key===key?next:row)
    :[...transfers.value,next].slice(-10);
}
async function pauseTransfer(){
  if(!runtime||!transfer.uploadId)return;
  busy.value=true;
  try{
    await runtime.pauseUpload?.(transfer.uploadId);
    paused.value=true;transfer.phase='已暂停传输';
    notice.value='传输已暂停；服务端已确认分片不会重复传输。';
  }catch(cause){error.value=cause instanceof Error?cause.message:'暂停 ZIP 传输失败'}
  finally{busy.value=false}
}
async function resumeTransfer(){
  if(!runtime||!transfer.uploadId)return;
  const uppy=(handle?.uppy as {getFiles?:()=>{data?:File}[]}|undefined);
  const file=uppy?.getFiles?.().map(row=>row.data).find(Boolean);
  if(!file){error.value='无法恢复原 ZIP 文件对象；请使用任务列表中的“重新选择原文件继续”。';return}
  busy.value=true;
  try{
    await runtime.resumeTransfer?.(file,transfer.uploadId);
    paused.value=false;transfer.phase='继续传输原 ZIP 会话';
  }catch(cause){error.value=cause instanceof Error?cause.message:'继续 ZIP 传输失败'}
  finally{busy.value=false}
}
async function resumeJob(job:ZipJob,event:Event){  const input=event.target as HTMLInputElement;
  if(!input.files?.length)return;
  const owner=runtime as unknown as {resumeFromFile?:(input:HTMLInputElement,id:string)=>Promise<unknown>};
  busy.value=true;
  try{await owner.resumeFromFile?.(input,String(job.upload_id||job.id));syncJobs()}
  catch(cause){error.value=cause instanceof Error?cause.message:'ZIP 续传失败'}
  finally{busy.value=false;input.value=''}
}
onMounted(async()=>{
  await loadLabels();
  const existing=(globalThis as unknown as {ZipImportRuntime?:ZipImportRuntime&{__nativeVueZipRuntime?:boolean}}).ZipImportRuntime;
  if(existing?.__nativeVueZipRuntime)try{existing.destroy?.()}catch{/* previous page owner is replaced below */}
  installShims();
  runtime=installZipImportRuntime({getState:()=>compat,projectId:()=>projectId,
    notify:message=>{notice.value=String(message||'')}});
  if(runtime)(runtime as unknown as {__nativeVueZipRuntime?:boolean}).__nativeVueZipRuntime=true;
  await nextTick();
  if(target.value){
    try{
      handle=await mountUppyZipAdapter({target:target.value,runtime:runtime!,
        projectId,onFallback:()=>{error.value='ZIP 组件加载失败，请使用原上传界面。'},notify:message=>{notice.value=String(message||'')}});
    }catch(cause){error.value=cause instanceof Error?cause.message:'ZIP 上传界面加载失败'}
  }
  runtime?.subscribeTransfers?.((event:Record<string,unknown>)=>{
    if(String(event.projectId||'')!==projectId)return;
    upsertTransfer(event);
    if(event.type==='session')transfer.uploadId=String(event.uploadId||'');
    if(event.type==='progress')transfer.progress=Math.round(Number(event.ratio||0)*100);
    if(event.type==='processing')transfer.phase=String(event.stage||event.message||'服务端处理中');
    if(event.type==='success'){transfer.jobId=String(event.jobId||'');transfer.phase='服务器已受理导入任务';syncJobs()}
    if(event.type==='error')transfer.error=String((event.error as Error)?.message||event.message||'ZIP 上传失败');
  });
  await loadJobs('native-page-bootstrap');
  const requested=String(route.query.job||'').trim();
  if(requested){await runtime?.openTask?.(requested);syncJobs()}
  mirrorTimer=window.setInterval(syncJobs,MIRROR_INTERVAL_MS);
});
onBeforeUnmount(()=>{
  controller.abort();if(mirrorTimer!==undefined){window.clearInterval(mirrorTimer);mirrorTimer=undefined}
  handle?.destroy();handle=null;
  runtime?.destroy?.();runtime=null;
  restoreShims();
});
</script>
<template><section class="zip-native">
 <header class="zip-head"><div><button class="back" @click="router.push({name:'materials',params:{projectId}})">返回素材库</button><h2>ZIP 数据集导入</h2><p>复用原 Uppy 6.0.5 视图、<code>ZipImportRuntime</code> 分片/暂停/恢复与标签确认 Owner。浏览器上传完成不等于后台解压入库完成。</p></div><div><a :href="legacy">原 ZIP 上传入口</a></div></header>
 <el-alert v-if="error" :title="error" type="error" :closable="false"/><el-alert v-if="notice" :title="notice" type="info" :closable="false"/>
 <section class="zip-upload-shell"><div ref="target" class="zip-uppy" aria-label="Uppy ZIP 上传"></div>
  <div class="zip-transfer" aria-live="polite"><p><b>上传会话 upload_id：</b>{{ transfer.uploadId||'尚未建立' }}</p><p><b>正式导入任务 import_job_id：</b>{{ transfer.jobId||'尚未生成' }}</p><p v-if="transfer.phase">阶段：{{ transfer.phase }}</p><p v-if="transfer.progress">当前 ZIP 网络传输 {{ transfer.progress }}%</p><p v-if="transfer.error" class="zip-error">{{ transfer.error }}</p><div class="zip-transfer-actions"><el-button v-if="transfer.uploadId&&!paused" data-zip-pause size="small" :loading="busy" @click="pauseTransfer">暂停传输</el-button><el-button v-if="paused" data-zip-resume size="small" type="primary" :loading="busy" @click="resumeTransfer">继续传输</el-button></div><small>关闭此页面不会取消已受理的后台任务；取消必须使用任务操作。</small></div>
 </section>
 <div v-if="transfers.length" class="zip-live"><h4>活动传输（{{ transfers.length }}）</h4><ul><li v-for="row in transfers" :key="row.key" :data-transfer-key="row.key"><b>{{ row.phase||'传输中' }}</b><small>upload_id {{ row.uploadId||'待建立' }} · import_job_id {{ row.jobId||'待生成' }} · {{ row.progress }}%</small><small v-if="row.error" class="zip-error">{{ row.error }}</small></li></ul></div>
 <section class="zip-jobs"><header><h3>导入任务（{{ jobs.length }}）</h3><el-button size="small" :loading="busy" @click="loadJobs('native-page-manual')">刷新任务</el-button></header><el-table :data="jobs" row-key="id" empty-text="当前项目没有 ZIP 导入任务"><el-table-column label="文件 / 任务" min-width="200"><template #default="{row}"><b>{{ row.file_name||'ZIP 数据导入' }}</b><small>{{ row.id }}</small><small v-if="row.upload_id&&row.upload_id!==row.id">上传会话 {{ row.upload_id }}</small></template></el-table-column><el-table-column label="传输 / 服务端阶段" min-width="220"><template #default="{row}"><el-tag type="info">{{ jobStatus(row) }}</el-tag><el-progress :percentage="jobProgress(row)" :stroke-width="8"/><small>{{ row.stage||'阶段未提供' }}<template v-if="row.message"> · {{ row.message }}</template></small><small v-if="row.queue_position">队列第 {{ row.queue_position }} 位</small></template></el-table-column><el-table-column label="入库结果" min-width="150"><template #default="{row}"><p v-if="row.status==='done'">已入库 {{ row.report?.imported_images??0 }} 张</p><p v-else-if="row.status==='failed'">{{ row.error||'失败' }}</p><p v-else>尚未到正式入库终态</p></template></el-table-column><el-table-column label="操作" min-width="230"><template #default="{row}"><div class="zip-actions"><el-button link type="primary" :disabled="busy" @click="openJob(row)">查看 / 标签确认</el-button><el-button v-if="['selecting','queued','waiting','running','uploading','paused','validating','merging'].includes(String(row.status))" link type="danger" :disabled="busy" @click="cancelJob(row)">取消任务</el-button><el-button v-if="row.status==='done'" link @click="viewImported(row)">查看入库素材</el-button><label v-if="row.status==='paused'" class="zip-resume">重新选择原文件继续<input type="file" accept=".zip,application/zip" @change="resumeJob(row,$event)"></label></div></template></el-table-column></el-table><p class="zip-note">一次最多两个 ZIP 并发上传，单个 ZIP 最多 4 个分片并发；暂停后需重新选择原文件继续。任务数量较多时仅列出最近 50 条。</p></section>
 <div ref="modalRoot" id="native-zip-modal-root" aria-live="polite"></div>
</section></template>
<style scoped>
.zip-native{padding:24px;min-width:0}.zip-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}.zip-head h2{margin:8px 0 6px;font-size:22px}.zip-head p{margin:0;color:#64748b;line-height:1.7;max-width:860px}.zip-head code{background:#f1f5f9;padding:1px 5px;border-radius:4px}.back{border:0;background:transparent;color:#2563eb;cursor:pointer;padding:0}.zip-upload-shell{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin:16px 0}.zip-uppy{min-height:390px}.zip-transfer{margin-top:14px;border-top:1px solid #eef2f7;padding-top:12px;font-size:13px;color:#334155;overflow-wrap:anywhere}.zip-transfer p{margin:4px 0}.zip-transfer small{display:block;margin-top:8px;color:#64748b}.zip-error{color:#b42318}.zip-transfer-actions{margin:8px 0}.zip-live{margin-top:12px;border-top:1px solid #eef2f7;padding-top:10px}.zip-live h4{margin:0 0 6px;font-size:14px}.zip-live ul{list-style:none;margin:0;padding:0;display:grid;gap:6px}.zip-live li{border:1px solid #e2e8f0;border-radius:8px;padding:8px;font-size:13px;display:grid;gap:3px}.zip-live small{color:#64748b}.zip-resume{display:grid;gap:4px;font-size:12px;color:#475569}.zip-resume input{max-width:190px}.zip-jobs{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px}.zip-jobs header{display:flex;justify-content:space-between;align-items:center;gap:12px}.zip-jobs h3{margin:0 0 12px;font-size:17px}.zip-jobs small{display:block;color:#64748b;line-height:1.6;overflow-wrap:anywhere}.zip-jobs p{margin:4px 0}.zip-actions{display:flex;flex-direction:column;align-items:flex-start;gap:4px}.zip-actions :deep(.el-button){margin:0}.zip-note{font-size:12px;color:#64748b;line-height:1.7;margin:10px 0 0}
</style>
<style>
#native-zip-modal-root{position:fixed;inset:0;z-index:3000;pointer-events:none}#native-zip-modal-root:empty{display:none}#native-zip-modal-root .modal{pointer-events:auto;position:absolute;inset:4vh 6vw;background:#fff;border:1px solid #dbe4ef;border-radius:14px;box-shadow:0 24px 80px rgba(15,23,42,.28);display:flex;flex-direction:column;overflow:hidden}#native-zip-modal-root .modal-title{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:14px 18px;border-bottom:1px solid #e8eef5;font-size:16px}#native-zip-modal-root .modal-title button{border:0;background:#eef2f7;border-radius:6px;padding:6px 10px;cursor:pointer}#native-zip-modal-root .modal-body{padding:18px;overflow:auto;flex:1;min-height:0}#native-zip-modal-root .modal-body h2{font-size:18px;margin:0 0 10px}#native-zip-modal-root .modal-body h3{font-size:15px;margin:14px 0 8px}#native-zip-modal-root .modal-body p{margin:6px 0;line-height:1.7}#native-zip-modal-root .modal-body table{width:100%;border-collapse:collapse}#native-zip-modal-root .modal-body th,#native-zip-modal-root .modal-body td{border-bottom:1px solid #edf1f6;padding:8px;text-align:left;vertical-align:top;font-size:13px}#native-zip-modal-root .modal-body select,#native-zip-modal-root .modal-body input{max-width:100%;padding:5px;border:1px solid #cbd5e1;border-radius:5px;background:#fff}#native-zip-modal-root .modal-body .btn{padding:6px 10px;border:1px solid #cbd5e1;border-radius:6px;background:#fff;cursor:pointer;margin:2px}#native-zip-modal-root .modal-body .btn.primary{background:#2563eb;border-color:#2563eb;color:#fff}#native-zip-modal-root .modal-body .btn.danger{color:#b42318;border-color:#f3b4ad}#native-zip-modal-root .modal-body .row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}#native-zip-modal-root .modal-body .alert{padding:10px 12px;border-radius:8px;background:#f1f5f9;margin:8px 0}#native-zip-modal-root .modal-body .alert.err{background:#fef3f2;color:#b42318}#native-zip-modal-root .modal-body .alert.warn{background:#fffaeb;color:#93370d}#native-zip-modal-root .modal-body .alert.ok{background:#ecfdf3;color:#067647}#native-zip-modal-root .modal-body .hidden{display:none}#native-zip-modal-root .modal-body .zip-label-confirm{margin-top:12px}#native-zip-modal-root .modal-body .zip-label-footer{display:flex;justify-content:space-between;gap:12px;align-items:center;flex-wrap:wrap;margin-top:14px}#native-zip-modal-root .modal-body .zip-label-row{display:grid;grid-template-columns:minmax(160px,1fr) minmax(180px,1fr) auto;gap:10px;align-items:start;padding:10px 0;border-bottom:1px solid #edf1f6}#native-zip-modal-root .modal-body .zip-label-source{text-align:left;background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:8px;cursor:pointer}#native-zip-modal-root .modal-body .zip-label-source small{display:block;color:#64748b;margin-top:4px}
</style>
