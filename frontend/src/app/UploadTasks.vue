<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {request} from './http';
import {useWorkspace} from './main';
import {getUploadBatchReceipt,type UploadBatchReceipt} from '../api/upload-batches';
import {
  isUploadSessionUnresolved,listUploadSessions,readOwnedUploadSession,updateUploadIndex,
  withUploadIdentityLock,writeUploadSession,
} from '../../../static/modules/material-upload-session.js';
import type {UploadSessionRecord} from '../../../static/modules/material-upload-session.js';

interface ImageSessionRow {key:string;session:UploadSessionRecord;status:string;statusLabel:string;
  uploaded:number;failed:number;pending:number;error:string;recoverable:boolean;pendingConfirm:boolean;
  partial:boolean}
interface ZipJob {id:string;file_name?:string;status?:string;stage?:string;message?:string;
  progress?:number|null;zip_display_progress?:number;queue_position?:number|null;
  report?:{imported_images?:number;annotated_images?:number};error?:string;upload_id?:string}
interface UnifiedRow {key:string;type:'image'|'zip';title:string;status:string;statusLabel:string;
  transfer:string;stage:string;success:number|null;failed:number|null;detail:string;
  recoverable:boolean;pendingConfirm:boolean;session?:UploadSessionRecord;job?:ZipJob;requestId?:string}
const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId),workspace=useWorkspace();
const zipJobs=ref<ZipJob[]>([]),imageSessions=ref<ImageSessionRow[]>([]);
const busy=ref(false),error=ref(''),loadedAt=ref('');
const controller=new AbortController();
let timer:number|undefined;
const alive=()=>!controller.signal.aborted;
const actorKey=computed(()=>String(workspace.actorKey||workspace.username||''));
const ZIP_STATUS:Record<string,string>={uploading:'传输中',paused:'已暂停',merging:'服务端合并',validating:'校验与扫描',selecting:'等待标签确认',queued:'后台排队',waiting:'等待处理',running:'正在解压与入库',done:'导入完成',failed:'失败',cancelled:'已取消',unknown:'状态待核验'};
const rows=computed<UnifiedRow[]>(()=>{
  const result:UnifiedRow[]=[];
  for(const batch of imageSessions.value){
    result.push({key:'image:'+batch.key,type:'image',title:`图片上传批次 · ${batch.session.totalFiles} 张`,
      status:batch.status,statusLabel:batch.statusLabel,transfer:'本机 request_id 索引',
      stage:`成功 ${batch.uploaded} · 失败 ${batch.failed} · 待确认 ${batch.pending}`,
      success:batch.uploaded,failed:batch.failed,
      detail:batch.error||`request_id ${batch.session.requestIds[0]||'未提供'}`,
      recoverable:batch.recoverable,pendingConfirm:batch.pendingConfirm,session:batch.session,
      requestId:batch.session.requestIds[0]});
  }
  for(const job of zipJobs.value){
    const status=String(job.status||'').toLowerCase();
    result.push({key:'zip:'+job.id,type:'zip',title:job.file_name||'ZIP 数据集导入',status,
      statusLabel:ZIP_STATUS[status]||status||'未提供',
      transfer:['uploading','paused'].includes(status)?'浏览器分片传输中':status==='merging'?'分片已交付，服务端合并':'传输已结束',
      stage:job.stage||job.message||'阶段未提供',
      success:status==='done'?(job.report?.imported_images??0):null,
      failed:status==='failed'?1:null,
      detail:job.error||`import_job_id ${job.id}${job.queue_position?` · 队列第 ${job.queue_position} 位`:''}`,
      recoverable:['unknown','failed'].includes(status),
      pendingConfirm:status==='selecting',job});
  }
  return result;
});
const active=computed(()=>rows.value.some(row=>['uploading','paused','merging','validating','selecting','queued','waiting','running','unknown',
  'UPLOADING','INTERRUPTED','UNKNOWN'].includes(row.status)));
const imageRows=computed(()=>rows.value.filter(row=>row.type==='image'));

interface ReceiptCacheEntry {row:ImageSessionRow;fetchedAt:number;idsKey:string;complete:boolean}
const receiptCache=new Map<string,ReceiptCacheEntry>();
const MAX_RECEIPT_REQUESTS=120;
const ACTIVE_TTL=2500,PARTIAL_TTL=15000,PENDING_TTL=15000,HISTORY_TTL=60000;
let loading=false,receiptBudget=0;

async function fetchReceipts(ids:string[]){
  const receipts:UploadBatchReceipt[]=[];let missing=0,errorText='';
  for(let offset=0;offset<ids.length;offset+=4){
    const chunk=ids.slice(offset,offset+4);
    const results=await Promise.all(chunk.map(async requestId=>{
      try{return {receipt:await getUploadBatchReceipt(projectId,requestId,controller.signal)}}
      catch(cause){
        const status=(cause as {httpStatus?:number}).httpStatus;
        return {status,cause};
      }
    }));
    for(const result of results){
      if(result.receipt)receipts.push(result.receipt);
      else if(result.status===404)missing+=1;
      else errorText=result.cause instanceof Error?result.cause.message:'回执读取失败';
    }
  }
  return {receipts,missing,errorText};
}

async function loadImageSession(session:UploadSessionRecord,force=false):Promise<ImageSessionRow>{
  const cacheKey=session.requestIds[0]||session.createdAt;
  const idsKey=session.requestIds.join('|');
  const cached=receiptCache.get(cacheKey);
  const age=Date.now()-(cached?.fetchedAt||0);
  const ttl=!cached?.complete?PARTIAL_TTL
    :session.pendingDecision>0?PENDING_TTL
      :isUploadSessionUnresolved(session)?ACTIVE_TTL:HISTORY_TTL;
  if(!force&&cached?.idsKey===idsKey&&age<ttl)return cached.row;
  const ids=session.requestIds.slice(0,100);
  const allowed=ids.slice(0,Math.max(0,receiptBudget));
  if(!allowed.length&&cached?.idsKey===idsKey)return cached.row;
  receiptBudget-=allowed.length;
  const fetched=await fetchReceipts(allowed);
  const complete=allowed.length===session.requestIds.length&&fetched.missing===0
    &&!fetched.errorText;
  const anyFailed=fetched.receipts.some(row=>String(row.upload_request_status||'').toUpperCase()==='FAILED');
  const uploaded=fetched.receipts.reduce((sum,row)=>sum+(row.items||[]).length,0);
  const failed=fetched.receipts.reduce((sum,row)=>sum+(row.upload_failed||[]).length,0);
  const pending=fetched.receipts.reduce((sum,row)=>sum+(row.items||[]).filter(item=>
    String((item as {decision?:string}).decision||'pending')==='pending').length,0);
  const allSucceeded=complete&&fetched.receipts.length===session.requestIds.length
    &&fetched.receipts.every(row=>String(row.upload_request_status||'SUCCEEDED').toUpperCase()==='SUCCEEDED');
  const partial=!complete;
  const status=allSucceeded?'SUCCEEDED':anyFailed&&complete?'FAILED':'UNKNOWN';
  const row:ImageSessionRow={key:cacheKey,session,status,
    statusLabel:status==='SUCCEEDED'?'服务器已入库':status==='FAILED'?'失败':'待核验',
    uploaded,failed,pending,partial,
    error:fetched.errorText||(partial&&allowed.length===0?'本轮回执读取预算已用完，尚未核验':'')
      ||(session.requestIds.length>100?'该会话超过 100 个分片，仅核验前 100 个回执':''),
    recoverable:status!=='SUCCEEDED'||partial,pendingConfirm:pending>0};
  if(complete)receiptCache.set(cacheKey,{row,fetchedAt:Date.now(),idsKey,complete:true});
  else receiptCache.set(cacheKey,{row,fetchedAt:Date.now(),idsKey,complete:false});
  if(complete&&session.requestIds[0]&&(session.pendingDecision!==pending
      ||session.confirmationState!==(pending?'PENDING':'DONE'))){
    await updateUploadIndex({actorKey:actorKey.value,projectId,id:session.requestIds[0],
      patch:{pendingDecision:pending,confirmationState:pending?'PENDING':'DONE'}});
  }
  return row;
}

async function load(force=false){
  if(!alive()||loading)return;
  loading=true;busy.value=true;error.value='';receiptBudget=MAX_RECEIPT_REQUESTS;
  try{
    const sessions=listUploadSessions({actorKey:actorKey.value,projectId})
      .sort((left,right)=>Number(isUploadSessionUnresolved(right))
        -Number(isUploadSessionUnresolved(left))
        ||Number(right.pendingDecision>0)-Number(left.pendingDecision>0));
    const loaded:ImageSessionRow[]=[];
    for(const session of sessions)loaded.push(await loadImageSession(session,force));
    // Pending/recovery rows stay visible before historical successes when the
    // bounded local index reaches its limit.
    loaded.sort((left,right)=>{
      const weight=(row:ImageSessionRow)=>row.recoverable||row.pendingConfirm?0:1;
      return weight(left)-weight(right)||String(right.session.updatedAt).localeCompare(String(left.session.updatedAt));
    });
    imageSessions.value=loaded;
    const zip=await request<{ok:boolean;items:ZipJob[]}>(`/api/v19/projects/${encodeURIComponent(projectId)}/import/jobs`,{signal:controller.signal});
    zipJobs.value=(zip.items||[]).slice(0,50);
    loadedAt.value=new Date().toLocaleTimeString();
  }catch(cause){if(alive())error.value=cause instanceof Error?cause.message:'上传任务读取失败'}
  finally{loading=false;busy.value=false}
}
function refresh(){void load(true)}
function openNativeUpload(){void router.push({name:'material-upload',params:{projectId}})}
async function continueSession(row:ImageSessionRow){
  let switched=false;
  try{
    await withUploadIdentityLock({actorKey:actorKey.value,projectId},async()=>{
      const current=readOwnedUploadSession({actorKey:actorKey.value,projectId}).session;
      if(current&&isUploadSessionUnresolved(current)
          &&current.requestIds[0]!==row.session.requestIds[0]){
        error.value='当前存在另一笔未核验的上传请求；请先核验它，不能覆盖其身份。';
        return;
      }
      const result=writeUploadSession({actorKey:actorKey.value,projectId,patch:{
        totalFiles:row.session.totalFiles,requestIds:row.session.requestIds,batchIds:row.session.batchIds,
        status:row.session.status,failed:row.session.failed,requestSeed:row.session.requestSeed,
        deferred:row.session.deferred,pendingDecision:row.pending,
        confirmationState:row.pending?'PENDING':'DONE',
      }});
      if(!result.ok){error.value='浏览器无法保存该上传会话身份；未切换。';return}
      switched=true;
    });
  }catch(cause){error.value=cause instanceof Error?cause.message:'另一个标签页正在修改上传身份，未切换。'}
  if(switched)void router.push({name:'material-upload',params:{projectId}});
}
async function viewImages(row:ImageSessionRow){
  const ids:string[]=[];
  for(const requestId of row.session.requestIds.slice(0,100)){
    try{
      const receipt=await getUploadBatchReceipt(projectId,requestId,controller.signal);
      for(const item of receipt.items||[]){
        const id=String(item.image?.id||item.image_id||'');
        if(id)ids.push(id);
      }
    }catch{/* the row already shows unreadable receipts */}
  }
  if(!ids.length){error.value='服务器回执没有可定位的已入库素材。';return}
  try{
    sessionStorage.setItem('materials.selection:'+JSON.stringify([workspace.username,projectId]),
      JSON.stringify([...new Set(ids)].slice(0,200)));
  }catch{/* selection is optional */}
  void router.push({name:'materials',params:{projectId}});
}
function zipProgress(job:ZipJob){const value=job.zip_display_progress??job.progress;
  return typeof value==='number'&&Number.isFinite(value)?Math.max(0,Math.min(100,Math.round(value))):0}
function openNativeZip(){void router.push({name:'material-zip-import',params:{projectId}})}
function openJob(job?:ZipJob){void router.push({name:'material-zip-import',params:{projectId},query:job?{job:job.id}:{}})}
function viewMaterials(job?:ZipJob){void router.push({name:'materials',params:{projectId},query:job?{source_batch_id:job.id}:{}})}
onMounted(()=>{void load();timer=window.setInterval(()=>{if(active.value)void load()},3000)});
onBeforeUnmount(()=>{controller.abort();if(timer!==undefined)window.clearInterval(timer)});
</script>
<template><section class="upload-tasks"><header class="tasks-head"><div><button class="back" @click="router.push({name:'materials',params:{projectId}})">返回素材库</button><h2>上传任务</h2><p>统一查看当前账号与项目的图片上传回执、待确认素材和 ZIP 导入任务。传输、后台处理与正式入库分别展示。</p></div><div class="head-actions"><el-button type="primary" @click="openNativeUpload">上传图片（原生）</el-button><el-button @click="openNativeZip">ZIP 数据集（原生）</el-button><el-button :loading="busy" @click="refresh">刷新</el-button></div></header>
 <el-alert v-if="error" :title="error" type="error" :closable="false"/>
 <el-alert v-if="!rows.length&&!busy" title="当前账号与项目没有可核验的上传批次；不会扫描其他账号或其他浏览器的本地记录。" type="info" :closable="false"/>
 <section class="task-section"><header><div><h3>图片上传回执</h3><p>按本机账号/项目索引找回原 request_id；服务器回执是入库依据。</p></div><small v-if="loadedAt">更新于 {{ loadedAt }}</small></header><el-table :data="imageRows" row-key="key" empty-text="本机没有可核验的图片上传批次"><el-table-column label="批次" min-width="220"><template #default="{row}"><b>{{ row.title }}</b><small>{{ row.requestId }}</small><small v-if="row.partial">请求较多，仅核验前 100 个分片回执；未核验部分保持待确认。</small></template></el-table-column><el-table-column label="状态" min-width="150"><template #default="{row}"><el-tag type="info">{{ row.statusLabel }}</el-tag><small v-if="row.pendingConfirm">待人工确认</small><small v-if="row.recoverable">待核验</small><small>{{ row.transfer }}</small></template></el-table-column><el-table-column label="服务端回执" min-width="220"><template #default="{row}">{{ row.stage }}<small>{{ row.detail }}</small></template></el-table-column><el-table-column label="操作" min-width="210"><template #default="{row}"><div class="row-actions"><el-button v-if="row.recoverable" link type="primary" @click="continueSession(row)">核验 / 继续处理</el-button><el-button v-if="row.pendingConfirm" link type="primary" @click="continueSession(row)">继续上传确认</el-button><el-button v-if="row.uploaded" link @click="viewImages(row)">查看已入库素材</el-button></div></template></el-table-column></el-table></section>
 <section class="task-section"><header><div><h3>ZIP 导入任务</h3><p>upload_id 与 import_job_id 分开显示；只有服务端终态才代表导入完成。</p></div><small>最多展示最近 50 条</small></header><el-table :data="zipJobs" row-key="id" empty-text="当前项目没有 ZIP 导入任务"><el-table-column label="文件 / 任务" min-width="220"><template #default="{row}"><b>{{ row.file_name||'ZIP 数据集导入' }}</b><small>import_job_id {{ row.id }}</small><small v-if="row.upload_id&&row.upload_id!==row.id">upload_id {{ row.upload_id }}</small></template></el-table-column><el-table-column label="传输 / 阶段" min-width="220"><template #default="{row}"><el-tag type="info">{{ ZIP_STATUS[String(row.status||'').toLowerCase()]||row.status||'未提供' }}</el-tag><small v-if="row.pendingConfirm">待人工确认</small><small v-if="row.recoverable">可重新核验</small><el-progress :percentage="zipProgress(row)" :stroke-width="8"/><small>{{ row.stage||row.message||'阶段未提供' }}</small><small v-if="row.queue_position">队列第 {{ row.queue_position }} 位</small></template></el-table-column><el-table-column label="入库结果" min-width="150"><template #default="{row}"><span v-if="row.status==='done'">已入库 {{ row.report?.imported_images??0 }} 张</span><span v-else-if="row.status==='failed'">{{ row.error||'失败' }}</span><span v-else>未到正式终态</span></template></el-table-column><el-table-column label="操作" min-width="230"><template #default="{row}"><el-button link type="primary" @click="openJob(row)">查看 / 标签确认</el-button><el-button v-if="row.status==='done'" link @click="viewMaterials(row)">查看入库素材</el-button></template></el-table-column></el-table></section>
 <p class="footnote">图片上传：按原 request_id 查询，不自动重复提交。ZIP：关闭视图不会取消后台任务，取消必须从任务操作明确发起。</p>
</section></template>
<style scoped>
.upload-tasks{padding:24px;min-width:0}.tasks-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}.tasks-head h2{margin:8px 0 6px;font-size:22px}.tasks-head p{margin:0;color:#64748b;line-height:1.7;max-width:760px}.back{border:0;background:transparent;color:#2563eb;cursor:pointer;padding:0}.head-actions{display:flex;gap:8px;flex-wrap:wrap}.task-section{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin:16px 0}.task-section header{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.task-section h3{margin:0 0 4px;font-size:17px}.task-section p{margin:0 0 12px;color:#64748b;font-size:13px}.task-section small{display:block;color:#64748b;line-height:1.6;overflow-wrap:anywhere}.row-actions{display:flex;flex-direction:column;align-items:flex-start;gap:4px}.row-actions :deep(.el-button){margin:0}.footnote{font-size:12px;color:#64748b;line-height:1.8;margin:14px 0 0}@media(max-width:720px){.upload-tasks{padding:14px}.tasks-head{flex-direction:column}}
</style>
