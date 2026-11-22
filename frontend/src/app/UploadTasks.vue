<script setup lang="ts">
import {computed,onBeforeUnmount,onMounted,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {request} from './http';
import {getUploadBatchReceipt,type UploadBatchReceipt} from '../api/upload-batches';
import {uploadSessionKey} from '../../../static/modules/upload-confirmation.js';

interface ImageBatch {requestId:string;status:string;uploaded:number;failed:number;error:string}
interface ZipJob {id:string;file_name?:string;status?:string;stage?:string;message?:string;
  progress?:number|null;zip_display_progress?:number;queue_position?:number|null;
  report?:{imported_images?:number;annotated_images?:number};error?:string;upload_id?:string}
interface UnifiedRow {key:string;type:'image'|'zip';title:string;status:string;statusLabel:string;
  transfer:string;stage:string;success:number|null;failed:number|null;detail:string;
  recoverable:boolean;pendingConfirm:boolean;job?:ZipJob;requestId?:string}
const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId);
const zipJobs=ref<ZipJob[]>([]),imageBatches=ref<ImageBatch[]>([]),sessionStatus=ref('');
const busy=ref(false),error=ref(''),loadedAt=ref('');
const controller=new AbortController();
let timer:number|undefined;
const alive=()=>!controller.signal.aborted;
const ZIP_STATUS:Record<string,string>={uploading:'传输中',paused:'已暂停',merging:'服务端合并',validating:'校验与扫描',selecting:'等待标签确认',queued:'后台排队',waiting:'等待处理',running:'正在解压与入库',done:'导入完成',failed:'失败',cancelled:'已取消',unknown:'状态待核验'};
const rows=computed<UnifiedRow[]>(()=>{
  const result:UnifiedRow[]=[];
  for(const batch of imageBatches.value){
    const status=batch.status.toUpperCase();
    result.push({key:'image:'+batch.requestId,type:'image',title:'图片上传批次',status,
      statusLabel:status==='SUCCEEDED'?'服务器已入库':status==='FAILED'?'失败':status==='UNKNOWN'?'待核验':'处理中',
      transfer:sessionStatus.value==='UPLOADING'?'浏览器上传会话未结束':sessionStatus.value==='INTERRUPTED'?'上传中断':'已结束',
      stage:`已确认 ${batch.uploaded} 张成功${batch.failed?` · ${batch.failed} 张失败`:''}`,
      success:batch.uploaded,failed:batch.failed,
      detail:batch.error||`request_id ${batch.requestId}`,recoverable:status!=='SUCCEEDED',
      pendingConfirm:false,requestId:batch.requestId});
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
const active=computed(()=>rows.value.some(row=>['uploading','paused','merging','validating','selecting','queued','waiting','running','unknown','PROCESSING','UPLOADING'].includes(row.status)||['UPLOADING','INTERRUPTED'].includes(row.status)));
const imageRows=computed(()=>rows.value.filter(row=>row.type==='image'));

function readSession(){try{return JSON.parse(localStorage.getItem(uploadSessionKey(projectId))||'null')}catch{return null}}
async function load(){
  if(!alive())return;
  busy.value=true;error.value='';
  try{
    const session=readSession();
    sessionStatus.value=String(session?.status||'');
    const requestIds:string[]=Array.isArray(session?.requestIds)
      ?[...new Set((session.requestIds as unknown[]).map(String).filter(Boolean))].slice(0,16):[];
    const batches:ImageBatch[]=[];
    for(const requestId of requestIds){
      let receipt:UploadBatchReceipt|null=null;
      try{receipt=await getUploadBatchReceipt(projectId,requestId,controller.signal)}
      catch(cause){
        const status=(cause as {httpStatus?:number}).httpStatus;
        batches.push({requestId,status:status===404?'UNKNOWN':'UNKNOWN',uploaded:0,failed:0,
          error:status===404?'服务器尚无该请求回执':'回执读取失败'});
        continue;
      }
      const status=String(receipt.upload_request_status||'SUCCEEDED').toUpperCase();
      batches.push({requestId,status,uploaded:(receipt.items||[]).length,
        failed:(receipt.upload_failed||[]).length,error:String(receipt.upload_request_error||'')});
    }
    imageBatches.value=batches;
    const zip=await request<{ok:boolean;items:ZipJob[]}>(`/api/v19/projects/${encodeURIComponent(projectId)}/import/jobs`,{signal:controller.signal});
    zipJobs.value=(zip.items||[]).slice(0,50);
    loadedAt.value=new Date().toLocaleTimeString();
  }catch(cause){error.value=cause instanceof Error?cause.message:'上传任务读取失败'}
  finally{busy.value=false}
}
function openNativeUpload(){void router.push({name:'material-upload',params:{projectId}})}
function zipProgress(job:ZipJob){const value=job.zip_display_progress??job.progress;
  return typeof value==='number'&&Number.isFinite(value)?Math.max(0,Math.min(100,Math.round(value))):0}
function openNativeZip(){void router.push({name:'material-zip-import',params:{projectId}})}
function openJob(job?:ZipJob){void router.push({name:'material-zip-import',params:{projectId},query:job?{job:job.id}:{}})}
function viewMaterials(job?:ZipJob){void router.push({name:'materials',params:{projectId},query:job?{source_batch_id:job.id}:{}})}
onMounted(()=>{void load();timer=window.setInterval(()=>{if(active.value)void load()},3000)});
onBeforeUnmount(()=>{controller.abort();if(timer!==undefined)window.clearInterval(timer)});
</script>
<template><section class="upload-tasks"><header class="tasks-head"><div><button class="back" @click="router.push({name:'materials',params:{projectId}})">返回素材库</button><h2>上传任务</h2><p>统一查看当前项目的图片上传回执与 ZIP 导入任务。传输进度、后台处理与正式入库分别展示，不把网络完成当作入库完成。</p></div><div class="head-actions"><el-button type="primary" @click="openNativeUpload">上传图片（原生）</el-button><el-button @click="openNativeZip">ZIP 数据集（原生）</el-button><el-button :loading="busy" @click="load">刷新</el-button></div></header>
 <el-alert v-if="error" :title="error" type="error" :closable="false"/>
 <el-alert v-if="!rows.length&&!busy" title="当前项目没有可核验的上传批次；图片批次只读取本机保存的原 request_id，不会扫描其他浏览器。" type="info" :closable="false"/>
 <section class="task-section"><header><div><h3>图片上传回执</h3><p>仅展示本机保存的原 request_id；服务器回执是入库依据。</p></div><small v-if="loadedAt">更新于 {{ loadedAt }}</small></header><el-table :data="imageRows" row-key="key" empty-text="本机没有未清除的图片上传批次"><el-table-column label="批次" min-width="220"><template #default="{row}"><b>{{ row.title }}</b><small>{{ row.requestId }}</small></template></el-table-column><el-table-column label="状态" min-width="140"><template #default="{row}"><el-tag type="info">{{ row.statusLabel }}</el-tag><small v-if="row.pendingConfirm">待人工确认</small><small v-if="row.recoverable">可重新核验</small><small>{{ row.transfer }}</small></template></el-table-column><el-table-column label="服务端回执" min-width="220"><template #default="{row}">{{ row.stage }}<small>{{ row.detail }}</small></template></el-table-column><el-table-column label="操作" min-width="150"><template #default><el-button link type="primary" @click="openNativeUpload">核验 / 继续处理</el-button></template></el-table-column></el-table></section>
 <section class="task-section"><header><div><h3>ZIP 导入任务</h3><p>upload_id 与 import_job_id 分开显示；只有服务端终态才代表导入完成。</p></div><small>最多展示最近 50 条</small></header><el-table :data="zipJobs" row-key="id" empty-text="当前项目没有 ZIP 导入任务"><el-table-column label="文件 / 任务" min-width="220"><template #default="{row}"><b>{{ row.file_name||'ZIP 数据集导入' }}</b><small>import_job_id {{ row.id }}</small><small v-if="row.upload_id&&row.upload_id!==row.id">upload_id {{ row.upload_id }}</small></template></el-table-column><el-table-column label="传输 / 阶段" min-width="220"><template #default="{row}"><el-tag type="info">{{ ZIP_STATUS[String(row.status||'').toLowerCase()]||row.status||'未提供' }}</el-tag><small v-if="row.pendingConfirm">待人工确认</small><small v-if="row.recoverable">可重新核验</small><el-progress :percentage="zipProgress(row)" :stroke-width="8"/><small>{{ row.stage||row.message||'阶段未提供' }}</small><small v-if="row.queue_position">队列第 {{ row.queue_position }} 位</small></template></el-table-column><el-table-column label="入库结果" min-width="150"><template #default="{row}"><span v-if="row.status==='done'">已入库 {{ row.report?.imported_images??0 }} 张</span><span v-else-if="row.status==='failed'">{{ row.error||'失败' }}</span><span v-else>未到正式终态</span></template></el-table-column><el-table-column label="操作" min-width="230"><template #default="{row}"><el-button link type="primary" @click="openJob(row)">查看 / 标签确认</el-button><el-button v-if="row.status==='done'" link @click="viewMaterials(row)">查看入库素材</el-button></template></el-table-column></el-table></section>
 <p class="footnote">图片上传：本机 request_id 回执可恢复；不要为同一批次重复提交。ZIP：关闭视图不会取消后台任务，取消必须从任务操作明确发起。</p>
</section></template>
<style scoped>
.upload-tasks{padding:24px;min-width:0}.tasks-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}.tasks-head h2{margin:8px 0 6px;font-size:22px}.tasks-head p{margin:0;color:#64748b;line-height:1.7;max-width:760px}.back{border:0;background:transparent;color:#2563eb;cursor:pointer;padding:0}.head-actions{display:flex;gap:8px;flex-wrap:wrap}.task-section{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin:16px 0}.task-section header{display:flex;justify-content:space-between;gap:12px;align-items:flex-start}.task-section h3{margin:0 0 4px;font-size:17px}.task-section p{margin:0 0 12px;color:#64748b;font-size:13px}.task-section small{display:block;color:#64748b;line-height:1.6;overflow-wrap:anywhere}.footnote{font-size:12px;color:#64748b;line-height:1.8;margin:14px 0 0}@media(max-width:720px){.upload-tasks{padding:14px}.tasks-head{flex-direction:column}}
</style>
