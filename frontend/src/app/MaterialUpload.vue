<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,reactive,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {request} from './http';
import {legacyUrl} from './navigation';
import {useWorkspace} from './main';
import {getUploadBatchReceipt,projectLabels} from '../api/upload-batches';
import {mountImageUppyView} from '../../../static/modules/uppy-image-view.js';
import {uploadMaterialFilesSequentially,requestMaterialChunkRecoverable,partitionMaterialFiles} from '../../../static/modules/material-upload-runtime.js';
import {installUploadConfirmationRuntime,uploadSessionKey} from '../../../static/modules/upload-confirmation.js';
import type {ImageUppyEvent,ImageUppyUploadOptions} from '../../../static/modules/uppy-image-view.js';
import type {UploadConfirmationRuntime} from '../../../static/modules/upload-confirmation.js';

interface StoredSession {
  projectId: string; totalFiles: number; requestIds: string[]; batchIds: string[];
  status: string; failed: number; requestSeed?: string; updatedAt?: string;
}
interface FailedFile {name: string; reason: string}

const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId),workspace=useWorkspace();
const host=ref<HTMLElement|null>(null),confirmationHost=ref<HTMLElement|null>(null);
const busy=ref(false),fallback=ref(false),error=ref(''),notice=ref('');
const labels=ref<{code: string; display_name?: string; name?: string}[]>([]);
const failedFiles=ref<FailedFile[]>([]),batchIds=ref<string[]>([]),uploadedIds=ref<string[]>([]);
const stored=ref<StoredSession|null>(null);
const summary=reactive({total:0,confirmed:0,uploaded:0,failed:0,chunks:0,chunk:0,ratio:0,loaded:0,totalBytes:0});
const stage=ref('选择图片后开始上传；网络传输完成不等于服务器入库。');
let handle:{uppy:unknown;destroy:()=>void}|null=null;
let confirmation:UploadConfirmationRuntime|null=null;
const controller=new AbortController();
const alive=()=>!controller.signal.aborted;

const recoverable=computed(()=>!!stored.value?.requestIds.length&&stored.value.status!=='SUCCEEDED');
const legacy=legacyUrl(projectId,'数据集','','','material-upload');
const pct=computed(()=>summary.total?Math.round(summary.confirmed/summary.total*100):0);

function readSession():StoredSession|null{
  try{
    const value=JSON.parse(localStorage.getItem(uploadSessionKey(projectId))||'null');
    if(!value||String(value.projectId||projectId)!==projectId)return null;
    const requestIds:string[]=Array.isArray(value.requestIds)
      ?[...new Set((value.requestIds as unknown[]).map(item=>String(item)).filter(Boolean))].slice(0,64):[];
    const ids:string[]=Array.isArray(value.batchIds)
      ?[...new Set((value.batchIds as unknown[]).map(item=>String(item)).filter(Boolean))]:[];
    return {projectId,totalFiles:Math.max(0,Number(value.totalFiles)||0),requestIds,batchIds:ids,
      status:String(value.status||'UNKNOWN'),failed:Math.max(0,Number(value.failed)||0),
      requestSeed:String(value.requestSeed||''),updatedAt:String(value.updatedAt||'')};
  }catch{return null}
}
function saveSession(value:Partial<StoredSession>):StoredSession|null{
  const previous=readSession();
  const next:StoredSession={projectId,totalFiles:value.totalFiles??previous?.totalFiles??0,
    requestIds:value.requestIds??previous?.requestIds??[],batchIds:value.batchIds??previous?.batchIds??[],
    status:value.status??previous?.status??'UNKNOWN',failed:value.failed??previous?.failed??0,
    requestSeed:value.requestSeed??previous?.requestSeed,updatedAt:new Date().toISOString()};
  try{localStorage.setItem(uploadSessionKey(projectId),JSON.stringify(next))}catch{notice.value='浏览器无法保存本次上传身份；刷新后可能无法核验原请求。'}
  stored.value=next;
  return next;
}

function seed(){
  const value=globalThis.crypto?.randomUUID?.().replace(/-/g,'')||Math.random().toString(16).slice(2).padEnd(24,'0');
  return ('up'+value).slice(0,32);
}
function observe(event:ImageUppyEvent){
  if(!alive())return;
  if(typeof event.totalFiles==='number')summary.total=event.totalFiles;
  if(typeof event.confirmedFiles==='number')summary.confirmed=event.confirmedFiles;
  if(typeof event.uploadedCount==='number')summary.uploaded=event.uploadedCount;
  if(typeof event.failedCount==='number')summary.failed=event.failedCount;
  if(typeof event.chunkCount==='number')summary.chunks=event.chunkCount;
  if(typeof event.chunkNumber==='number')summary.chunk=event.chunkNumber;
  if(typeof event.loadedBytes==='number')summary.loaded=event.loadedBytes;
  if(typeof event.totalBytes==='number')summary.totalBytes=event.totalBytes;
  if(typeof event.ratio==='number')summary.ratio=event.ratio;
  if(event.type==='chunk-start')stage.value=`正在上传第 ${event.chunkNumber}/${event.chunkCount} 批（${event.chunkSize} 张）`;
  else if(event.type==='transfer')stage.value=`第 ${event.chunkNumber}/${event.chunkCount} 批网络传输 ${Math.round((event.ratio||0)*100)}% · 服务器已确认 ${summary.confirmed}/${summary.total}`;
  else if(event.type==='chunk-committed')stage.value=`第 ${event.chunkNumber}/${event.chunkCount} 批服务器已确认 · 已确认 ${summary.confirmed}/${summary.total}`;
  else if(event.type==='complete')stage.value='上传交付完成；正式入库结果以下方回执为准。';
}

async function uploadFiles(files:File[],options:ImageUppyUploadOptions={}){
  const rows=Array.from(files||[]);
  if(!rows.length)return null;
  const requestSeed=seed();
  const chunks=partitionMaterialFiles(rows);
  const requestIds=chunks.map((_,index)=>`${requestSeed}-${String(index+1).padStart(4,'0')}`.slice(0,64));
  summary.total=rows.length;summary.confirmed=0;summary.uploaded=0;summary.failed=0;
  summary.chunk=0;summary.ratio=0;summary.loaded=0;summary.totalBytes=0;
  failedFiles.value=[];uploadedIds.value=[];batchIds.value=[];error.value='';notice.value='';
  saveSession({totalFiles:rows.length,requestIds,batchIds:[],status:'UPLOADING',failed:0,requestSeed});
  try{
    const aggregate=await uploadMaterialFilesSequentially(rows,{
      requestChunk:(chunk,context)=>requestMaterialChunkRecoverable(chunk,{
        projectId,storageSourceId:options.storageSourceId||'default_local',
        requestId:requestIds[context.chunkIndex],onTransfer:context.onTransfer,
      }),
      onEvent:event=>{
        observe(event);
        if(event.type==='chunk-committed'){
          const response=event.response||{};
          if(response.batch_id)batchIds.value=[...new Set([...batchIds.value,String(response.batch_id)])];
          for(const row of response.failed||[]){
            const name=String((row as {name?:string;filename?:string}).name||(row as {filename?:string}).filename||'文件');
            const reason=String((row as {reason?:string}).reason||'服务器未确认');
            if(failedFiles.value.length<50)failedFiles.value.push({name,reason});
          }
          for(const row of response.uploaded||[]){
            const image=(row as {image?:{id?:string}}).image||row as {id?:string};
            if(image?.id)uploadedIds.value=[...new Set([...uploadedIds.value,String(image.id)])];
          }
          saveSession({status:'UPLOADING',batchIds:batchIds.value,failed:event.failedCount,totalFiles:event.totalFiles});
        }
        options.onEvent?.(event);
        if(event.type==='chunk-committed')options.onCommitted?.({...event,files:chunks[event.chunkIndex]||[]});
      },
    });
    summary.confirmed=aggregate.confirmedFiles;summary.uploaded=aggregate.uploaded.length;
    summary.failed=aggregate.failed.length;summary.chunks=aggregate.chunks;
    batchIds.value=aggregate.batchIds;
    saveSession({status:'SUCCEEDED',batchIds:aggregate.batchIds,totalFiles:aggregate.totalFiles,failed:aggregate.failed.length});
    stage.value=`上传交付完成 · 服务器已确认 ${aggregate.uploaded.length} 张成功、${aggregate.failed.length} 张失败`;
    if(confirmation&&(aggregate.batchIds.length||aggregate.failed.length)){
      await confirmation.open({projectId,batchIds:aggregate.batchIds,totalFiles:aggregate.totalFiles,
        failed:aggregate.failed,requestIds});
    }
    return aggregate;
  }catch(cause){
    const details=(cause as {details?:{confirmedFiles?:number}}).details;
    saveSession({status:'INTERRUPTED',batchIds:batchIds.value,failed:summary.failed});
    error.value=`上传中断：${cause instanceof Error?cause.message:'网络或服务器响应丢失'}。`
      +`服务器已确认处理 ${details?.confirmedFiles??summary.confirmed}/${rows.length}。`
      +'为避免重复入库，系统不会自动重传未确认批次；可点击“核验原上传请求”。';
    stage.value='上传中断，等待按原请求核验';
    throw cause;
  }
}

const runtime={uploadFiles};

async function mountUppy(){
  if(!host.value||!alive())return;
  handle?.destroy();host.value.replaceChildren();
  fallback.value=false;
  try{
    handle=await mountImageUppyView({
      target:host.value,runtime,projectId,getProjectId:()=>projectId,
      storageSourceId:'default_local',beforeConfirmation:()=>true,
      onEvent:event=>observe(event as ImageUppyEvent),
      onFallback:()=>{fallback.value=true;error.value='Uppy 图片上传界面加载失败；可使用本机文件选择，仍走原 request_id 上传合同。'},
    });
  }catch(cause){
    fallback.value=true;error.value=cause instanceof Error?cause.message:'图片上传界面加载失败';
  }
}
async function fallbackUpload(event:Event){
  const files=Array.from((event.target as HTMLInputElement).files||[]);
  if(!files.length)return;
  busy.value=true;
  try{await uploadFiles(files,{})}
  catch{/* error already shown */}
  finally{busy.value=false;(event.target as HTMLInputElement).value=''}
}
function retry(){
  void mountUppy();
}
async function recoverSession(){
  const value=readSession();
  if(!value?.requestIds.length)return;
  busy.value=true;error.value='';notice.value='';
  const batches:string[]=[],failed:FailedFile[]=[];const recoverUploaded:string[]=[];
  let unknown=0,missing=0;
  try{
    for(const requestId of value.requestIds){
      try{
        const receipt=await getUploadBatchReceipt(projectId,requestId,new AbortController().signal);
        const status=String(receipt.upload_request_status||'SUCCEEDED').toUpperCase();
        if(status==='SUCCEEDED'){
          batches.push(String(receipt.id||requestId));
          for(const row of receipt.items||[]){
            const id=String(row.image?.id||row.image_id||'');
            if(id&&!recoverUploaded.includes(id))recoverUploaded.push(id);
          }
          for(const row of receipt.upload_failed||[]){
            if(failed.length<50)failed.push({name:String(row.name||'文件'),reason:String(row.reason||'服务器未确认')});
          }
        }else if(status==='FAILED'){
          error.value=`原上传请求失败：${receipt.upload_request_error||'服务器已确认失败'}`;
        }
      }catch(cause){
        const status=(cause as {httpStatus?:number}).httpStatus;
        if(status===404)missing+=1;else unknown+=1;
      }
    }
    uploadedIds.value=recoverUploaded;
    batchIds.value=[...new Set(batches)];
    const allConfirmed=batchIds.value.length===value.requestIds.length;
    saveSession({status:allConfirmed?'SUCCEEDED':'INTERRUPTED',batchIds:batchIds.value,totalFiles:value.totalFiles,failed:failed.length});
    if(batchIds.value.length){
      summary.total=value.totalFiles||recoverUploaded.length;
      summary.confirmed=recoverUploaded.length+failed.length;
      summary.uploaded=recoverUploaded.length;summary.failed=failed.length;
      stage.value=`已核验 ${batchIds.value.length}/${value.requestIds.length} 个上传请求`;
      notice.value=allConfirmed
        ?'已按原 request_id 核验；不会重新上传已确认批次。'
        :`仍有 ${value.requestIds.length-batchIds.value.length} 个请求未确认（不回传缺失 ${missing}），不会自动重传。`;
      if(confirmation)await confirmation.open({projectId,batchIds:batchIds.value,totalFiles:summary.total,failed,requestIds:value.requestIds});
    }else if(unknown||missing){
      notice.value='原上传请求暂时不可读或尚未建立回执；保持待核验，不会自动重传。';
    }else{
      notice.value='未找到服务器已确认的上传批次；未自动重传。';
    }
    await mountUppy();
  }finally{busy.value=false}
}
function viewUploaded(){
  if(!uploadedIds.value.length)return;
  try{
    sessionStorage.setItem('materials.selection:'+JSON.stringify([workspace.username,projectId]),
      JSON.stringify(uploadedIds.value.slice(0,200)));
  }catch{/* selection is optional */}
  void router.push({name:'materials',params:{projectId}});
}
function fresh(){
  try{localStorage.removeItem(uploadSessionKey(projectId))}catch{/* storage optional */}
  stored.value=null;failedFiles.value=[];batchIds.value=[];uploadedIds.value=[];
  summary.total=0;summary.confirmed=0;summary.uploaded=0;summary.failed=0;summary.chunks=0;
  confirmation?.destroy();confirmation=installConfirmation();
  void mountUppy();
}

function installConfirmation(){
  if(!confirmationHost.value)return null;
  return installUploadConfirmationRuntime({
    getState:()=>({project:{id:projectId,labels:labels.value},page:'数据集'}),
    api:(url,options)=>request(url,options),
    getContainer:()=>confirmationHost.value,
    previewImage:()=>{},
    notify:message=>{notice.value=String(message||'')},
  });
}

onMounted(async()=>{
  stored.value=readSession();
  try{
    const detail=await projectLabels(projectId,controller.signal);
    labels.value=Array.isArray(detail.labels)?detail.labels:[];
  }catch{/* labels are only needed by the original decision panel */}
  await nextTick();
  confirmation=installConfirmation();
  if(recoverable.value)notice.value='检测到上次未完成的上传批次；请先核验原请求，不会自动重传。';
  await mountUppy();
});
onBeforeUnmount(()=>{
  controller.abort();
  handle?.destroy();handle=null;
  confirmation?.destroy();confirmation=null;
});
</script>
<template><section class="material-upload-page">
 <header class="upload-head"><div><button class="back" @click="router.push({name:'materials',params:{projectId}})">返回素材库</button><h2>上传图片</h2><p>使用原 Uppy 6.0.5 离线界面与 <code>MaterialUploadRuntime</code> 的分批、request_id 恢复合同；网络传输完成不等于正式入库。</p></div><div><a :href="legacy">原上传工作台</a></div></header>
 <el-alert v-if="error" :title="error" type="error" :closable="false"/>
 <el-alert v-if="notice" :title="notice" type="info" :closable="false"/>
 <el-alert v-if="recoverable" type="warning" :closable="false" title="存在未完成的上传批次；请按原 request_id 核验，系统不会自动重传。"><el-button size="small" :loading="busy" @click="recoverSession">核验原上传请求</el-button></el-alert>
 <section class="upload-shell"><div ref="host" class="uppy-host" aria-label="Uppy 图片上传"></div>
  <div v-if="fallback" class="fallback"><label>选择图片<input type="file" accept="image/*" multiple :disabled="busy" @change="fallbackUpload"></label><small>降级入口仍使用原 request_id 上传合同。</small></div>
  <div class="upload-progress" aria-live="polite"><div class="progress-line"><span>{{ stage }}</span><b>{{ pct }}%</b></div><el-progress :percentage="pct" :stroke-width="8" :show-text="false"/><p>服务器已确认 {{ summary.confirmed }} / {{ summary.total }} 张 · 成功 {{ summary.uploaded }} · 失败 {{ summary.failed }}<template v-if="summary.chunks"> · 第 {{ summary.chunk }}/{{ summary.chunks }} 批</template></p><p v-if="summary.totalBytes">当前批网络传输 {{ Math.round(summary.ratio*100) }}% · {{ Math.round(summary.loaded/1024) }} / {{ Math.round(summary.totalBytes/1024) }} KB</p></div>
 </section>
 <section v-if="failedFiles.length" class="failed"><h3>失败文件（{{ failedFiles.length }}）</h3><ul><li v-for="row in failedFiles" :key="row.name+row.reason"><b>{{ row.name }}</b>：{{ row.reason }}</li></ul><small>仅展示前 50 条；重试只能基于服务端已确认的失败范围。</small></section>
 <section class="after-upload"><el-button v-if="uploadedIds.length" type="primary" @click="viewUploaded">查看已上传素材（{{ uploadedIds.length }} 张）</el-button><el-button v-if="batchIds.length" @click="router.push({name:'materials',params:{projectId},query:{source_batch_id:batchIds[batchIds.length-1]}})">按批次筛选</el-button><el-button :disabled="busy" @click="fresh">再选一批</el-button><el-button v-if="!batchIds.length" @click="retry">重新加载上传界面</el-button><a :href="legacy">需要 ZIP 或原完整上传流程？进入原工作台</a></section>
 <section ref="confirmationHost" class="confirmation-host" aria-label="上传后处理"></section>
</section></template>
<style scoped>
.material-upload-page{padding:24px;min-width:0}.upload-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}.upload-head h2{margin:8px 0 6px;font-size:22px}.upload-head p{margin:0;color:#64748b;line-height:1.7;max-width:820px}.upload-head code{background:#f1f5f9;padding:1px 5px;border-radius:4px}.back{border:0;background:transparent;color:#2563eb;cursor:pointer;padding:0}.upload-shell{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin:16px 0}.uppy-host{min-height:390px}.uppy-host :deep(.uppy-Dashboard-inner){border-color:#dbe4ef;border-radius:10px}.upload-progress{margin-top:16px}.progress-line{display:flex;justify-content:space-between;gap:12px;margin-bottom:8px;font-size:14px}.upload-progress p{margin:8px 0 0;color:#475569;font-size:13px}.fallback{margin-top:12px;padding:12px;border:1px dashed #cbd5e1;border-radius:8px;display:grid;gap:8px}.failed{margin:16px 0;background:#fff7ed;border:1px solid #fed7aa;border-radius:10px;padding:14px}.failed h3{margin:0 0 8px;font-size:15px}.failed ul{margin:0;padding-left:20px;max-height:220px;overflow:auto}.failed li{margin:4px 0;overflow-wrap:anywhere}.failed small{display:block;margin-top:8px;color:#9a3412}.after-upload{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:16px 0}.after-upload a{color:#2563eb;font-size:13px}.confirmation-host:empty{display:none}@media(max-width:720px){.material-upload-page{padding:14px}.upload-head{flex-direction:column}}
</style>
