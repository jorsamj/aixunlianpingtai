<script setup lang="ts">
import {computed,nextTick,onBeforeUnmount,onMounted,reactive,ref} from 'vue';
import {useRoute,useRouter} from 'vue-router';
import {request} from './http';
import {legacyUrl} from './navigation';
import {useWorkspace} from './main';
import {getUploadBatchReceipt,projectLabels} from '../api/upload-batches';
import {materialMediaUrl} from '../api/materials';
import {mountImageUppyView} from '../../../static/modules/uppy-image-view.js';
import {uploadMaterialFilesSequentially,requestMaterialChunkRecoverable,partitionMaterialFiles} from '../../../static/modules/material-upload-runtime.js';
import {installUploadConfirmationRuntime,uploadSessionKey} from '../../../static/modules/upload-confirmation.js';
import {
  clearUploadSession,isUploadSessionUnresolved,readOwnedUploadSession,uploadRequestIds,
  uploadSessionStorageKey,writeUploadSession,
} from '../../../static/modules/material-upload-session.js';
import type {ImageUppyEvent,ImageUppyUploadOptions,ImageUploadRuntime} from '../../../static/modules/uppy-image-view.js';
import type {UploadConfirmationRuntime} from '../../../static/modules/upload-confirmation.js';
import type {UploadSessionRecord} from '../../../static/modules/material-upload-session.js';

interface FailedFile {name: string; reason: string}
interface PreviewImage {url: string; name: string}

const route=useRoute(),router=useRouter(),projectId=String(route.params.projectId),workspace=useWorkspace();
const host=ref<HTMLElement|null>(null),confirmationHost=ref<HTMLElement|null>(null);
const busy=ref(false),fallback=ref(false),error=ref(''),notice=ref('');
const labels=ref<{code:string;display_name?:string;name?:string}[]>([]);
const failedFiles=ref<FailedFile[]>([]),batchIds=ref<string[]>([]),uploadedIds=ref<string[]>([]);
const session=ref<UploadSessionRecord|null>(null),unowned=ref<UploadSessionRecord|null>(null);
const retryNames=ref<string[]|null>(null),preview=ref<PreviewImage|null>(null);
const stage=ref('选择图片后开始上传；网络传输完成不等于服务器入库。');
const summary=reactive({total:0,confirmed:0,uploaded:0,failed:0,chunks:0,chunk:0,ratio:0,loaded:0,totalBytes:0});
let handle:{uppy:unknown;destroy:()=>void}|null=null;
let confirmation:UploadConfirmationRuntime|null=null;
let uploading=false,uploadPromise:Promise<unknown>|null=null,generation=0;
const controller=new AbortController();
const alive=()=>!controller.signal.aborted;
const actorKey=computed(()=>String(workspace.actorKey||workspace.username||''));
const unresolved=computed(()=>isUploadSessionUnresolved(session.value));
const recoverable=computed(()=>!!session.value?.requestIds.length&&unresolved.value);
const legacy=legacyUrl(projectId,'数据集','','','material-upload');
const legacyAi=computed(()=>batchIds.value.length
  ?legacyUrl(projectId,'自动标注及清洗','','','material-ai')+'&source_batch_id='+encodeURIComponent(batchIds.value[batchIds.value.length-1])
  :legacyUrl(projectId,'自动标注及清洗','','','material-ai'));
const pct=computed(()=>summary.total?Math.round(summary.confirmed/summary.total*100):0);
const sessionKey=computed(()=>uploadSessionStorageKey(actorKey.value,projectId));

function loadSession(){
  const value=readOwnedUploadSession({actorKey:actorKey.value,projectId});
  session.value=value.session;unowned.value=value.unowned||null;
  failedFiles.value=[];batchIds.value=[...value.session?.batchIds||[]];uploadedIds.value=[];
  summary.total=value.session?.totalFiles||0;summary.confirmed=0;
  summary.uploaded=0;summary.failed=value.session?.failed||0;
  return value.session;
}
function saveSession(patch:Partial<UploadSessionRecord>,{silent=false,protectCurrent=false}={}):boolean{
  const result=writeUploadSession({actorKey:actorKey.value,projectId,patch,protectCurrent});
  if(!result.ok){
    if(!silent)error.value='浏览器无法保存上传请求身份，已停止；请允许站点存储后再试。';
    return false;
  }
  session.value=result.session;
  return true;
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

function uploadLockName(){
  return `material-upload:${actorKey.value}:${projectId}`;
}
async function withUploadLock<T>(work:()=>Promise<T>):Promise<T>{
  const manager=(navigator as unknown as {locks?:{request:(name:string,options:{ifAvailable:boolean},
    callback:(lock:unknown)=>Promise<void>)=>Promise<void>}}).locks;
  if(!manager?.request)return work();
  let denied=false;
  let result:T|undefined;
  await manager.request(uploadLockName(),{ifAvailable:true},async lock=>{
    if(!lock){denied=true;return}
    result=await work();
  });
  if(denied){
    notice.value='另一个标签页正在为同一账号和项目上传；已停止新请求，避免覆盖恢复记录。';
    throw new Error('另一个标签页正在上传，请等待其完成或先核验原请求');
  }
  return result as T;
}

async function uploadFiles(files:File[],options:ImageUppyUploadOptions={}){
  const rows=Array.from(files||[]);
  if(!rows.length)return null;
  if(uploading||uploadPromise){notice.value='已有图片上传正在进行，请等待当前批次结束。';return null}
  return withUploadLock(()=>runUpload(rows,options));
}

async function runUpload(rows:File[],options:ImageUppyUploadOptions){
  const current=loadSession();
  if(isUploadSessionUnresolved(current)){
    notice.value='存在未核验的原上传请求，已禁止新上传覆盖；请先核验原 request_id。';
    throw new Error('原上传请求尚未核验，已停止新上传');
  }
  const requestSeed=seed();
  const chunks=partitionMaterialFiles(rows);
  const requestIds=uploadRequestIds(requestSeed,chunks.length);
  summary.total=rows.length;summary.confirmed=0;summary.uploaded=0;summary.failed=0;
  summary.chunk=0;summary.ratio=0;summary.loaded=0;summary.totalBytes=0;
  failedFiles.value=[];uploadedIds.value=[];batchIds.value=[];error.value='';notice.value='';
  // The identity is durable before the first POST.  If the browser cannot
  // persist it, no upload request may be sent.
  if(!saveSession({totalFiles:rows.length,requestIds,batchIds:[],status:'UPLOADING',failed:0,
    requestSeed,createdAt:new Date().toISOString(),deferred:false,pendingDecision:0,confirmationState:''})){
    throw new Error('浏览器无法保存上传身份，未发送任何上传请求');
  }
  const ticket=++generation;
  let persistenceLost=false;
  uploading=true;
  uploadPromise=(async()=>{
    try{
      const aggregate=await uploadMaterialFilesSequentially(rows,{
        requestChunk:(chunk,context)=>{
          if(ticket!==generation||!alive())throw new Error('上传身份已被新的页面操作取代');
          if(persistenceLost)throw new Error('浏览器已丢失上传身份，已停止后续批次');
          return requestMaterialChunkRecoverable(chunk,{
            projectId,storageSourceId:options.storageSourceId||'default_local',
            requestId:requestIds[context.chunkIndex],onTransfer:context.onTransfer,
          });
        },
        onEvent:event=>{
          if(ticket!==generation||!alive())return;
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
            if(!saveSession({status:'UPLOADING',batchIds:batchIds.value,failed:event.failedCount,
              totalFiles:event.totalFiles},{silent:true,protectCurrent:true})){
              persistenceLost=true;
              error.value='浏览器上传身份存储失败：当前批已由服务器处理，但不会继续发送后续批次；请保持页面并核验。';
            }
          }
          options.onEvent?.(event);
          if(event.type==='chunk-committed')options.onCommitted?.({...event,files:chunks[event.chunkIndex]||[]});
        },
      });
      summary.confirmed=aggregate.confirmedFiles;summary.uploaded=aggregate.uploaded.length;
      summary.failed=aggregate.failed.length;summary.chunks=aggregate.chunks;
      batchIds.value=aggregate.batchIds;
      const proven=saveSession({status:'SUCCEEDED',batchIds:aggregate.batchIds,
        totalFiles:aggregate.totalFiles,failed:aggregate.failed.length,deferred:false,
        pendingDecision:aggregate.uploaded.length,
        confirmationState:aggregate.uploaded.length?'PENDING':''},{protectCurrent:true});
      stage.value=`上传交付完成 · 服务器已确认 ${aggregate.uploaded.length} 张成功、${aggregate.failed.length} 张失败`;
      if(!proven)error.value='上传已完成，但浏览器未能保存回执身份；刷新后可能无法恢复待确认素材。';
      if(confirmation&&(aggregate.batchIds.length||aggregate.failed.length)){
        await confirmation.open({projectId,batchIds:aggregate.batchIds,totalFiles:aggregate.totalFiles,
          failed:aggregate.failed,requestIds});
      }
      return aggregate;
    }catch(cause){
      const details=(cause as {details?:{confirmedFiles?:number}}).details;
      saveSession({status:'INTERRUPTED',batchIds:batchIds.value,failed:summary.failed},
        {silent:true,protectCurrent:true});
      error.value=`上传中断：${cause instanceof Error?cause.message:'网络或服务器响应丢失'}。`
        +`服务器已确认处理 ${details?.confirmedFiles??summary.confirmed}/${rows.length}。`
        +'为避免重复入库，系统不会自动重传未确认批次；请核验原 request_id。';
      stage.value='上传中断，等待按原请求核验';
      throw cause;
    }finally{
      if(ticket===generation)uploading=false;
    }
  })();
  try{return await uploadPromise}
  finally{uploadPromise=null}
}

const runtime={uploadFiles} as unknown as ImageUploadRuntime;

async function mountUppy(){
  if(!host.value||!alive())return;
  handle?.destroy();handle=null;host.value.replaceChildren();
  fallback.value=false;
  if(unresolved.value){
    stage.value='原上传请求尚未核验，已暂停新上传';
    return;
  }
  try{
    handle=await mountImageUppyView({
      target:host.value,runtime,projectId,getProjectId:()=>projectId,
      storageSourceId:'default_local',retryNames:retryNames.value,beforeConfirmation:()=>true,
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
function retryFailed(){
  const names=[...new Set(failedFiles.value.map(row=>row.name).filter(Boolean))];
  if(!names.length)return;
  retryNames.value=names;
  notice.value='仅允许重试服务器已确认失败的文件名；无法区分的同名文件不会被猜测。';
  void mountUppy();
}
function retry(){void mountUppy()}

async function recoverSession(){
  const value=loadSession();
  if(!value?.requestIds.length)return;
  busy.value=true;error.value='';notice.value='';
  const batches:string[]=[],failed:FailedFile[]=[];const recoverUploaded:string[]=[];
  let unknown=0,missing=0,pending=0;
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
            if(String((row as {decision?:string}).decision||'pending')==='pending')pending+=1;
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
    failedFiles.value=failed;
    const allConfirmed=batchIds.value.length===value.requestIds.length;
    saveSession({status:allConfirmed?'SUCCEEDED':'INTERRUPTED',batchIds:batchIds.value,
      totalFiles:value.totalFiles,failed:failed.length,pendingDecision:pending,
      confirmationState:pending?'PENDING':'DONE'},{protectCurrent:true});
    if(batchIds.value.length){
      summary.total=value.totalFiles||recoverUploaded.length;
      summary.confirmed=recoverUploaded.length+failed.length;
      summary.uploaded=recoverUploaded.length;summary.failed=failed.length;
      stage.value=`已核验 ${batchIds.value.length}/${value.requestIds.length} 个上传请求`;
      notice.value=allConfirmed
        ?'已按原 request_id 核验；不会重新上传已确认批次。'
        :`仍有 ${value.requestIds.length-batchIds.value.length} 个请求未确认（404 ${missing}），不会自动重传。`;
      if(confirmation)await confirmation.open({projectId,batchIds:batchIds.value,totalFiles:summary.total,
        failed,requestIds:value.requestIds});
    }else if(unknown||missing){
      notice.value='原上传请求暂时不可读或服务器没有回执；保持待核验，不会自动重传。';
    }else{
      notice.value='未找到服务器已确认的上传批次；未自动重传。';
    }
    if(!unresolved.value)await mountUppy();
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
  if(uploading||unresolved.value){
    notice.value='存在未核验的原上传请求，不能直接清除；“再选一批”不会覆盖或删除原身份。';
    return;
  }
  clearUploadSession({actorKey:actorKey.value,projectId});
  session.value=null;failedFiles.value=[];batchIds.value=[];uploadedIds.value=[];
  summary.total=0;summary.confirmed=0;summary.uploaded=0;summary.failed=0;summary.chunks=0;
  retryNames.value=null;
  confirmation?.destroy();confirmation=installConfirmation();
  void mountUppy();
}
function continueConfirmation(){
  if(!session.value?.batchIds.length)return;
  if(confirmation)void confirmation.restoreForProject(projectId,{autoOpen:true});
}
function previewImage(image:unknown){
  const row=image as {id?:string;filename?:string;content_url?:string;thumbnail_url?:string};
  const id=String(row?.id||'');
  const url=materialMediaUrl(row?.content_url,projectId,id,'content')
    ||materialMediaUrl(row?.thumbnail_url,projectId,id,'thumbnail')
    ||(id?`/api/v61/projects/${encodeURIComponent(projectId)}/materials/${encodeURIComponent(id)}/content`:'');
  if(!url){notice.value='原图地址不可用，无法打开预览；请在原工作台查看。';return}
  preview.value={url,name:String(row?.filename||id||'素材预览')};
}

const savedGlobals:{[key:string]:unknown}={};
let previousConfirmation:unknown=undefined;
function legacyAction(action:string,page:string,extra:Record<string,string>={}){
  const raw=legacyUrl(projectId,page,'','',action);
  const params=new URLSearchParams(raw.split('?')[1]||'');
  for(const [key,value] of Object.entries(extra))params.set(key,value);
  location.assign('/?'+params.toString());
}
function installBridges(){
  const target=globalThis as unknown as Record<string,unknown>;
  for(const key of ['setPage','openAnnotation','ImageUppyView','showTaskProgress427',
    'openSmartMaterialAudit','renderDatasets424','refreshLabels414','reloadMaterialPage61'])
    savedGlobals[key]=target[key];
  target.setPage=(page:string)=>{void page;/* confirmation must stay on this page */};
  target.openAnnotation=(id:string)=>{
    if(!id)return;
    legacyAction('material-annotate','数据集',{material_id:id});
  };
  target.ImageUppyView={open:(options:{retryNames?:string[]}={})=>{
    const names=Array.isArray(options?.retryNames)?[...new Set(options.retryNames.map(String))]:null;
    if(names?.length){retryNames.value=names;notice.value='仅允许重试服务器已确认失败的文件名。'}
    void mountUppy();
  }};
  target.showTaskProgress427=(kind:string,id:string)=>{
    if(kind!=='clean'||!id){notice.value='该后台任务详情请在原任务中心查看。';return}
    legacyAction('material-clean-task','自动标注及清洗',{task_id:String(id)});
  };
  target.openSmartMaterialAudit=(options?:{imageIds?:string[];source?:string})=>{
    const ids=(options?.imageIds||[]).map(value=>String(value||'')).filter(Boolean).slice(0,500);
    if(!ids.length){notice.value='没有可提交智能质检的素材范围，请重新选择。';return}
    legacyAction('material-smart-audit','数据集',{image_ids:ids.join(','),source:String(options?.source||'upload')});
  };
  target.renderDatasets424=()=>{};
  target.refreshLabels414=async()=>{await loadLabels();return true};
  target.reloadMaterialPage61=async()=>{};
}
function restoreBridges(){
  const target=globalThis as unknown as Record<string,unknown>;
  for(const [key,value] of Object.entries(savedGlobals)){
    if(value===undefined)delete target[key];else target[key]=value;
  }
}
async function loadLabels(){
  try{
    const detail=await projectLabels(projectId,controller.signal);
    const rows=detail.project?.labels??detail.labels;
    labels.value=Array.isArray(rows)?rows:[];
  }catch{/* original confirmation explains missing labels */}
}
function scopedStorage():Storage{
  const legacyKey=uploadSessionKey(projectId);
  return {
    get length(){return localStorage.length},
    clear(){/* never clear unrelated browser storage */},
    key:(index:number)=>localStorage.key(index),
    getItem:(key:string)=>localStorage.getItem(key===legacyKey?sessionKey.value:key),
    setItem:(key:string,value:string)=>localStorage.setItem(key===legacyKey?sessionKey.value:key,value),
    removeItem:(key:string)=>localStorage.removeItem(key===legacyKey?sessionKey.value:key),
  } as Storage;
}
function installConfirmation(){
  if(!confirmationHost.value)return null;
  return installUploadConfirmationRuntime({
    getState:()=>({project:{id:projectId,labels:labels.value},labels:labels.value,
      page:'数据集',actorKey:actorKey.value}),
    api:(url,options)=>request(url,options),
    getContainer:()=>confirmationHost.value,
    previewImage,
    notify:message=>{notice.value=String(message||'')},
    storage:scopedStorage(),
  });
}

onMounted(async()=>{
  loadSession();
  await loadLabels();
  await nextTick();
  installBridges();
  previousConfirmation=(globalThis as unknown as {UploadConfirmationRuntime?:unknown}).UploadConfirmationRuntime;
  confirmation=installConfirmation();
  if(unresolved.value)notice.value='存在未完成的上传请求；已禁止新上传覆盖，请先核验原 request_id。';
  else if(session.value?.batchIds.length)notice.value='上次上传已由服务器确认；可继续处理待确认素材或开始新批次。';
  else if(unowned.value)notice.value='发现归属无法确认的旧版本上传记录，未自动归属到当前账号；请使用原账号或原工作台上传入口核验。';
  if(session.value?.batchIds.length&&confirmation)
    await confirmation.restoreForProject(projectId,{autoOpen:false});
  await mountUppy();
});
onBeforeUnmount(()=>{
  generation+=1;controller.abort();
  handle?.destroy();handle=null;
  const current=(globalThis as unknown as {UploadConfirmationRuntime?:unknown}).UploadConfirmationRuntime;
  if(confirmation&&current===confirmation){
    const target=globalThis as unknown as Record<string,unknown>;
    if(previousConfirmation===undefined)delete target.UploadConfirmationRuntime;
    else target.UploadConfirmationRuntime=previousConfirmation;
  }
  confirmation?.destroy();confirmation=null;
  restoreBridges();
});
</script>
<template><section class="material-upload-page">
 <header class="upload-head"><div><button class="back" @click="router.push({name:'materials',params:{projectId}})">返回素材库</button><h2>上传图片</h2><p>使用原 Uppy 6.0.5 离线界面与原 <code>MaterialUploadRuntime</code> 分批、request_id 恢复合同；网络传输完成不等于正式入库。</p></div><div><a :href="legacy">原上传工作台</a></div></header>
 <el-alert v-if="error" :title="error" type="error" :closable="false"/>
 <el-alert v-if="notice" :title="notice" type="info" :closable="false"/>
 <el-alert v-if="recoverable" type="warning" :closable="false" title="存在未完成的上传请求；已禁止新上传覆盖原 request_id。"><el-button size="small" :loading="busy" @click="recoverSession">核验原上传请求</el-button></el-alert>
 <section class="upload-shell"><div v-if="!unresolved" ref="host" class="uppy-host" aria-label="Uppy 图片上传"></div><div v-else class="blocked"><b>原上传请求尚未核验</b><p>为避免重复入库和身份覆盖，新上传已暂停。请先核验原 request_id；服务器回执是唯一成功依据。</p><el-button :loading="busy" @click="recoverSession">核验原上传请求</el-button></div>
  <div v-if="fallback&&!unresolved" class="fallback"><label>选择图片<input type="file" accept="image/*" multiple :disabled="busy" @change="fallbackUpload"></label><small>降级入口仍使用原 request_id 上传合同。</small></div>
  <div class="upload-progress" aria-live="polite"><div class="progress-line"><span>{{ stage }}</span><b>{{ pct }}%</b></div><el-progress :percentage="pct" :stroke-width="8" :show-text="false"/><p>服务器已确认 {{ summary.confirmed }} / {{ summary.total }} 张 · 成功 {{ summary.uploaded }} · 失败 {{ summary.failed }}<template v-if="summary.chunks"> · 第 {{ summary.chunk }}/{{ summary.chunks }} 批</template></p><p v-if="summary.totalBytes">当前批网络传输 {{ Math.round(summary.ratio*100) }}% · {{ Math.round(summary.loaded/1024) }} / {{ Math.round(summary.totalBytes/1024) }} KB</p></div>
 </section>
 <section v-if="failedFiles.length" class="failed"><h3>失败文件（{{ failedFiles.length }}）</h3><ul><li v-for="row in failedFiles" :key="row.name+row.reason"><b>{{ row.name }}</b>：{{ row.reason }}</li></ul><small>仅展示前 50 条；重试只能基于服务器已确认的失败范围。</small><el-button size="small" @click="retryFailed">重试失败文件</el-button></section>
 <section class="after-upload"><el-button v-if="uploadedIds.length" type="primary" @click="viewUploaded">查看已上传素材（{{ uploadedIds.length }} 张）</el-button><el-button v-if="batchIds.length" @click="continueConfirmation">继续处理上传确认</el-button><el-button v-if="batchIds.length" @click="router.push({name:'materials',params:{projectId},query:{source_batch_id:batchIds[batchIds.length-1]}})">按批次筛选</el-button><a v-if="batchIds.length" :href="legacyAi">AI 预标注（原工作台 · 本批次）</a><el-button :disabled="busy||unresolved" @click="fresh">再选一批</el-button><el-button v-if="!batchIds.length" @click="retry">重新加载上传界面</el-button><a :href="legacy">需要 ZIP 或原完整上传流程？进入原工作台</a></section>
 <section ref="confirmationHost" class="confirmation-host" aria-label="上传后处理"></section>
 <el-dialog :model-value="!!preview" :title="preview?.name||'素材预览'" width="min(960px,94vw)" @close="preview=null"><img v-if="preview" :src="preview.url" :alt="preview.name" class="preview-image"></el-dialog>
</section></template>
<style scoped>
.material-upload-page{padding:24px;min-width:0}.upload-head{display:flex;justify-content:space-between;gap:16px;align-items:flex-start;margin-bottom:16px}.upload-head h2{margin:8px 0 6px;font-size:22px}.upload-head p{margin:0;color:#64748b;line-height:1.7;max-width:820px}.upload-head code{background:#f1f5f9;padding:1px 5px;border-radius:4px}.back{border:0;background:transparent;color:#2563eb;cursor:pointer;padding:0}.upload-shell{background:white;border:1px solid #e2e8f0;border-radius:12px;padding:16px;margin:16px 0}.uppy-host{min-height:390px}.uppy-host :deep(.uppy-Dashboard-inner){border-color:#dbe4ef;border-radius:10px}.blocked{padding:28px;border:1px dashed #f3b4ad;border-radius:10px;background:#fff7f6;color:#7a271a}.blocked p{line-height:1.7}.upload-progress{margin-top:16px}.progress-line{display:flex;justify-content:space-between;gap:12px;margin-bottom:8px;font-size:14px}.upload-progress p{margin:8px 0 0;color:#475569;font-size:13px}.fallback{margin-top:12px;padding:12px;border:1px dashed #cbd5e1;border-radius:8px;display:grid;gap:8px}.failed{margin:16px 0;background:#fff7ed;border:1px solid #fed7aa;border-radius:10px;padding:14px}.failed h3{margin:0 0 8px;font-size:15px}.failed ul{margin:0 0 8px;padding-left:20px;max-height:220px;overflow:auto}.failed li{margin:4px 0;overflow-wrap:anywhere}.failed small{display:block;margin-bottom:8px;color:#9a3412}.after-upload{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:16px 0}.after-upload a{color:#2563eb;font-size:13px}.confirmation-host:empty{display:none}.preview-image{display:block;max-width:100%;max-height:75vh;margin:0 auto;object-fit:contain}@media(max-width:720px){.material-upload-page{padding:14px}.upload-head{flex-direction:column}}
</style>
<style>
/* The original confirmation hides a broken thumbnail; keep its preview button
   tappable so the user can still open the real content URL. */
.confirmation-host .uc-card button[data-preview]{display:block;min-height:150px;background:#f1f5f9}
</style>
