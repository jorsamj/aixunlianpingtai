import {withRequestDeadline} from './api.js?v=20261021s';
import {unverifiedUploadTask} from './upload-task-center.js?v=66014';
import {applyExactLabelCodeMatches, bulkSetLabelMapping, buildManualLabelMapping, createLabelMappingReview, filterCanonicalLabels, labelMappingReviewPage, labelMappingReviewSummary, labelSampleOverlay, reconcileLabelMappingReview, setLabelMapping, setLabelMappingReviewPage, setLabelMappingReviewSearch, setLabelMappingSelected, setLabelMappingTargetSearch, planOriginalLabelMappings} from './label-mapping-review.js?v=4226356';

export const ACTIVE_ZIP_STATUSES = new Set(['uploading','paused','merging','validating','selecting','queued','waiting','running']);
export const IMPORT_QUEUE_ZIP_STATUSES = new Set(['selecting','queued','waiting','running']);
export const TERMINAL_ZIP_STATUSES = new Set(['done','failed','cancelled','canceled']);
export const LEGACY_START_GRACE_MS = 8000;

const status = job => String(job?.status || '').toLowerCase();
const time = value => Number.isFinite(Date.parse(value || '')) ? Date.parse(value) : 0;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const jsArg = value => esc(JSON.stringify(String(value ?? '')));
const clamp = value => Math.max(0, Math.min(100, Number(value) || 0));
export const PLATFORM_LABEL_CODE_RE = /^[A-Za-z][A-Za-z0-9_-]*$/;

export function zipLabelChoice(externalClass, labels = []) {
  const source = String(externalClass?.name || '').trim();
  void labels;
  return {mode:'unresolved', code:'', source};
}

export function orderZipJobs(jobs) {
  return [...(jobs || [])].sort((a,b) => time(a?.created_at)-time(b?.created_at) || String(a?.id||'').localeCompare(String(b?.id||'')));
}
export function activeZipJobs(jobs) { return orderZipJobs(jobs).filter(job => ACTIVE_ZIP_STATUSES.has(status(job))); }
export async function mapZipUploadsConcurrent(items,upload,limit=2) {
  const rows=[...(items||[])],results=new Array(rows.length);
  let cursor=0;
  const n=Math.min(rows.length,Math.max(1,Math.floor(Number(limit)||1)));
  await Promise.all(Array.from({length:n},async()=>{
    while(true){
      const index=cursor++;
      if(index>=rows.length)return;
      try{results[index]={status:'fulfilled',value:await upload(rows[index],index)}}
      catch(reason){results[index]={status:'rejected',reason}}
    }
  }));
  return results;
}
// A slot covers only browser transfer. Release it as soon as all parts
// arrive, without waiting for server-side merge/scan or human label review.
export function createZipTransferLimiter(limit=2) {
  const maximum=Math.max(1,Math.floor(Number(limit)||1)),waiters=[];
  let busy=0;
  return async function withSlot(work) {
    if(busy<maximum)busy++;
    else await new Promise(resolve=>waiters.push(resolve));
    let released=false;
    const release=()=>{
      if(released)return;
      released=true;
      const next=waiters.shift();
      if(next)next();
      else busy--;
    };
    try{return await work(release)}
    finally{release()}
  };
}
export function zipQueueInfo(job,jobs) {
  // Only v19 server truth determines position in the formal FIFO queue.
  // Unconfirmed ZIPs are outside that queue, even if uploaded first.
  void jobs;
  const position=Number(job?.queue_position)>0?Number(job.queue_position):null;
  const ready=status(job)==='selecting'&&!zipNeedsLabelConfirmation(job);
  return {index:position===null?-1:position-1,position,ahead:position?position-1:0,
    canStart:ready,waits:status(job)==='running'&&String(job?.phase||'')==='QUEUE'&&position>1};
}
export function pickZipJob(jobs) {
  const active=activeZipJobs(jobs), running=active.find(x=>status(x)==='running');
  if(running) return running;
  if(active.length) return active[0];
  return orderZipJobs(jobs).filter(x=>TERMINAL_ZIP_STATUSES.has(status(x))||status(x)==='unknown').sort((a,b)=>time(b?.updated_at||b?.created_at)-time(a?.updated_at||a?.created_at))[0]||null;
}
export function backendZipProgress(job) {
  const n=Number(job?.progress); return Number.isFinite(n)?clamp(n):0;
}
export function zipDisplayProgress(job) {
  const value=job?.zip_display_progress;
  return value&&typeof value==='object'?value:null;
}
export function overallZipProgress(job) {
  const display=zipDisplayProgress(job);
  const rawCanonical=display?.overall_progress;
  const canonical=rawCanonical===null||rawCanonical===undefined||rawCanonical===''?NaN:Number(rawCanonical);
  if(Number.isFinite(canonical)) return clamp(canonical);
  // The server projects historical jobs too. This raw value is only a
  // fail-safe for malformed/offline fixtures, never a second lifecycle mapper.
  const legacy=Number(job?.progress);
  if(Number.isFinite(legacy)) return clamp(legacy);
  return status(job)==='done'?100:0;
}
export function zipPhaseDetail(job) {
  if(status(job)==='unknown')return {text:'历史记录，非实时进度',phaseProgress:null,etaSeconds:null};
  const display=zipDisplayProgress(job);
  if(!display) return {text:'',phaseProgress:null,etaSeconds:null};
  const completedRaw=display.completed,totalRaw=display.total,phaseRaw=display.phase_progress,etaRaw=display.eta_seconds;
  const completed=completedRaw===null||completedRaw===undefined||completedRaw===''?NaN:Number(completedRaw);
  const total=totalRaw===null||totalRaw===undefined||totalRaw===''?NaN:Number(totalRaw);
  const phaseProgress=phaseRaw===null||phaseRaw===undefined||phaseRaw===''?NaN:Number(phaseRaw);
  const etaSeconds=etaRaw===null||etaRaw===undefined||etaRaw===''?NaN:Number(etaRaw);
  const unit=String(display.unit||'');
  const unitLabel={bytes:'字节',files:'文件',images:'图片',step:'步骤'}[unit]||unit;
  const counter=Number.isFinite(completed)&&Number.isFinite(total)&&total>0 ? `${Math.round(completed)} / ${Math.round(total)}${unitLabel?` ${unitLabel}`:''}` : '';
  const phase=Number.isFinite(phaseProgress)?`阶段 ${Math.round(clamp(phaseProgress))}%`:'';
  const eta=Number.isFinite(etaSeconds)&&etaSeconds>=0?`预计剩余 ${Math.round(etaSeconds)} 秒`:'';
  return {text:[phase,counter,eta].filter(Boolean).join(' · '),phaseProgress:Number.isFinite(phaseProgress)?clamp(phaseProgress):null,etaSeconds:Number.isFinite(etaSeconds)?etaSeconds:null};
}
export function zipView(job,jobs) {
  if(!job) return null;
  const s=status(job), q=zipQueueInfo(job,jobs), progress=overallZipProgress(job),display=zipDisplayProgress(job);
  const canonicalStage=String(display?.phase_label||'').trim(),canonicalMessage=String(display?.message||'').trim();
  if(s==='unknown')return {status:s,progress,stage:'状态无法确认',message:job?.error||job?.message||'最后记录不能代表实际执行状态。',queue:q};
  if(s==='uploading') return {status:s,progress,stage:canonicalStage||'正在上传 ZIP',message:canonicalMessage||job?.message||'正在分片上传，可断点续传。',queue:q};
  if(s==='paused') return {status:s,progress,stage:'上传已暂停',message:job?.message||'已保存分片，可选择原文件继续。',queue:q};
  if(s==='merging') return {status:s,progress,stage:canonicalStage||'正在合并 ZIP 分片',message:canonicalMessage||job?.message||'文件已上传，服务器正在合并分片。',queue:q};
  if(s==='validating') return {status:s,progress,stage:canonicalStage||'正在校验 ZIP',message:canonicalMessage||job?.message||'服务器正在校验压缩包目录结构。',queue:q};
  if(q.waits) return {status:s,progress,stage:'等待项目正式导入队列',message:`已就绪，正式执行队列第 ${q.position} 位；前面还有 ${q.ahead} 个任务。`,queue:q};
  if(zipNeedsLabelConfirmation(job)) return {status:s,progress,stage:'等待确认标注',message:`检测到 ${job.external_classes.length} 个外部标签，请统一到平台标签后再入库。`,queue:q};
  if(s==='selecting') return {status:s,progress,stage:canonicalStage||'等待启动后台导入',message:canonicalMessage||job?.message||'ZIP 已上传并完成校验，正在确认后台启动状态。',queue:q};
  if(s==='running') return {status:s,progress,stage:canonicalStage||job?.stage||'后台导入中',message:canonicalMessage||job?.message||'后台正在处理 ZIP 数据。',queue:q};
  if(s==='done') return {status:s,progress:100,stage:canonicalStage||'导入完成',message:canonicalMessage||job?.message||'ZIP 数据已完成导入。',queue:q};
  if(s==='failed') return {status:s,progress,stage:'导入失败',message:job?.error||canonicalMessage||job?.message||'ZIP 导入失败。',queue:q};
  return {status:s,progress,stage:canonicalStage||job?.stage||'ZIP 导入',message:canonicalMessage||job?.message||'',queue:q};
}
export function zipNeedsLabelConfirmation(job) {
  return status(job)==='selecting'
    && Boolean(job?.label_confirmation_required)
    && Array.isArray(job?.external_classes)
    && job.external_classes.length>0;
}
export function zipStartDisposition(job,jobs,{intent='',eligibleForMs=0,graceMs=LEGACY_START_GRACE_MS}={}) {
  if(status(job)!=='selecting') return 'none';
  // No frontend queue gate: v19 start persists FIFO admission atomically.
  void jobs;
  if(zipNeedsLabelConfirmation(job)) return 'confirm-labels';
  if(intent==='deferred') return 'start';
  if(['submitting','submitted','ambiguous'].includes(intent)) return 'observe';
  return Number(eligibleForMs)<Number(graceMs)?'confirm':'start-legacy-recovery';
}

async function json(response) {
  let body={}; try{body=await response.json()}catch(_){}
  if(!response.ok){const error=new Error(String(body?.detail||body?.message||`HTTP ${response.status}`));error.status=response.status;throw error}
  return body;
}
export async function listZipJobs(projectId,{fetchImpl=globalThis.fetch}={}) {
  return (await withRequestDeadline(async signal=>json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/jobs`,{credentials:'same-origin',signal})),{label:'ZIP任务列表'})).items||[];
}
export async function getZipJob(projectId,jobId,{fetchImpl=globalThis.fetch}={}) {
  return withRequestDeadline(async signal=>json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/jobs/${encodeURIComponent(String(jobId))}`,{credentials:'same-origin',signal})),{label:'ZIP任务状态'});
}
export async function completeZipUpload(projectId,uploadId,{fetchImpl=globalThis.fetch}={}) {
  const url=`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/uploads/${encodeURIComponent(String(uploadId))}/complete`;
  try {
    return json(await fetchImpl(url,{method:'POST',credentials:'same-origin'}));
  } catch (error) {
    // A dropped response is not proof the server rejected the completion.
    // Read the durable job before allowing a new upload or another POST.
    const networkFailure=error instanceof TypeError || /Failed to fetch|NetworkError|Load failed/i.test(String(error?.message||''));
    if(!networkFailure)throw error;
    try {
      const observed=await getZipJob(projectId,uploadId,{fetchImpl});
      if(['merging','validating','selecting','running','done','failed'].includes(status(observed)))return observed;
    } catch (_) {}
    const uncertain=new Error(`ZIP 分片已传完，但服务器的合并确认连接中断（任务 ${uploadId}）。请从右下角任务中心查看状态，不要重复上传；连接恢复后可重新选择同一 ZIP 续传。`);
    uncertain.zipCompletionUncertain=true;
    throw uncertain;
  }
}

export async function startZipJob(projectId,jobId,{fetchImpl=globalThis.fetch,confirmation={}}={}) {
  const body={
    selected_paths:[],
    label_mapping:{...(confirmation?.label_mapping||{})},
  };
  return json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/jobs/${encodeURIComponent(String(jobId))}/start`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}));
}
export function uploadZipJob(projectId,file,{onTransfer=()=>{},xhrFactory=()=>new XMLHttpRequest()}={}) {
  return new Promise((resolve,reject)=>{
    const form=new FormData(); form.append('file',file); const xhr=xhrFactory();
    xhr.open('POST',`/api/v19/projects/${encodeURIComponent(String(projectId))}/datasets/default/import/jobs`,true);
    xhr.upload.onprogress=e=>{if(e.lengthComputable)onTransfer({loaded:e.loaded,total:e.total,ratio:e.total?e.loaded/e.total:0})};
    xhr.onerror=()=>reject(new Error('网络连接中断，ZIP 尚未得到服务器确认'));
    xhr.onabort=()=>reject(new Error('ZIP 上传已取消，尚未得到服务器确认'));
    xhr.onload=()=>{let body={};try{body=JSON.parse(xhr.responseText||'{}')}catch(_){};if(xhr.status<200||xhr.status>=300)return reject(new Error(String(body?.detail||xhr.responseText||`HTTP ${xhr.status}`)));if(!body?.id)return reject(new Error('服务器未返回 ZIP 导入任务 ID'));resolve(body)};
    xhr.send(form);
  });
}

export function zipPartPlan(fileSize, partSize, completedParts = []) {
  const size=Math.max(0,Number(fileSize)||0),part=Math.max(1,Number(partSize)||1),done=new Set((completedParts||[]).map(Number)),rows=[];
  for(let index=0,start=0;start<size;index+=1,start+=part){const end=Math.min(size,start+part);rows.push({index,start,end,size:end-start,completed:done.has(index)})}
  return rows;
}

function bytesToHex(bytes) { return [...new Uint8Array(bytes)].map(value=>value.toString(16).padStart(2,'0')).join(''); }
function fallbackSampleHash(bytes) {
  let hash=2166136261;
  for(const value of new Uint8Array(bytes)){hash^=value;hash=Math.imul(hash,16777619)}
  return (hash>>>0).toString(16).padStart(8,'0');
}
export async function zipFingerprint(file) {
  const size=Math.max(0,Number(file?.size)||0),span=Math.min(64*1024,size),last=Math.max(0,size-span),middle=Math.max(0,Math.floor((size-span)/2));
  const starts=[0,middle,last].filter((value,index,rows)=>rows.indexOf(value)===index);
  const buffers=[];
  for(const start of starts) buffers.push(await file.slice(start,Math.min(size,start+span)).arrayBuffer());
  const total=buffers.reduce((sum,buffer)=>sum+buffer.byteLength,0),sample=new Uint8Array(total);let offset=0;
  for(const buffer of buffers){sample.set(new Uint8Array(buffer),offset);offset+=buffer.byteLength}
  let digest='';
  if(globalThis.crypto?.subtle){digest=bytesToHex(await globalThis.crypto.subtle.digest('SHA-256',sample))}
  else digest=fallbackSampleHash(sample.buffer);
  return `v2:${file.name}:${size}:${Number(file.lastModified||0)}:${digest}`;
}

export function zipBatchDuplicateKey(fingerprint) {
  const parts=String(fingerprint||'').split(':');
  if(parts.length<5||parts[0]!=='v2')return String(fingerprint||'');
  const digest=parts.pop(),lastModified=parts.pop(),size=parts.pop(),version=parts.shift();
  void lastModified;
  return `${version}:${parts.join(':')}:${size}:${digest}`;
}

export async function createZipUploadSession(projectId,file,{fetchImpl=globalThis.fetch,expectedUploadId=''}={}) {
  const fingerprint=await zipFingerprint(file);
  return json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(String(projectId))}/datasets/default/import/uploads`,{
    method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({file_name:file.name,file_size:file.size,fingerprint,part_size:8*1024*1024,resume_upload_id:expectedUploadId||''}),
  }));
}

function uploadZipPartXHR(projectId,uploadId,part,file,{onTransfer=()=>{},xhrFactory=()=>new XMLHttpRequest(),control=null}={}) {
  return new Promise((resolve,reject)=>{
    if(control?.state&&control.state!=='active')return reject(new Error('ZIP 上传已暂停或取消'));
    const xhr=xhrFactory();
    control?.xhrs?.add(xhr);
    const settle=callback=>value=>{control?.xhrs?.delete(xhr);callback(value)};
    const succeed=settle(resolve),fail=settle(reject);
    xhr.open('PUT',`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/uploads/${encodeURIComponent(String(uploadId))}/parts/${part.index}`,true);
    xhr.setRequestHeader?.('Content-Type','application/octet-stream');
    xhr.timeout=180000;
    xhr.upload.onprogress=e=>{if(e.lengthComputable&&(!control||control.state==='active'))onTransfer({loaded:e.loaded,total:e.total,ratio:e.total?e.loaded/e.total:0})};
    xhr.onerror=()=>fail(new Error(`ZIP 分片 ${part.index+1} 网络连接中断`));
    xhr.ontimeout=()=>fail(new Error(`ZIP 分片 ${part.index+1} 网络超时，可从服务器已确认分片恢复`));
    xhr.onabort=()=>fail(new Error(`ZIP 分片 ${part.index+1} 已中断`));
    xhr.onload=()=>{let body={};try{body=JSON.parse(xhr.responseText||'{}')}catch(_){};if(xhr.status<200||xhr.status>=300)return fail(new Error(String(body?.detail||xhr.responseText||`HTTP ${xhr.status}`)));succeed(body)};
    xhr.send(file.slice(part.start,part.end));
  });
}

export async function uploadZipMultipartJob(projectId,file,{onTransfer=()=>{},onSession=()=>{},onPhase=()=>{},fetchImpl=globalThis.fetch,xhrFactory=()=>new XMLHttpRequest(),concurrency=4,retries=2,control=null}={}) {
  const session=await createZipUploadSession(projectId,file,{fetchImpl,expectedUploadId:control?.expectedUploadId||''});
  const uploadId=String(session.upload_id||'');
  if(!uploadId)throw new Error('服务器未返回 ZIP 上传会话 ID');
  onSession(session);
  if(control?.state&&control.state!=='active')throw new Error('ZIP 上传已暂停或取消');
  const plan=zipPartPlan(file.size,session.part_size,session.completed_parts);
  const pending=plan.filter(part=>!part.completed),inflight=new Map();
  let committed=plan.filter(part=>part.completed).reduce((sum,part)=>sum+part.size,0),cursor=0,acknowledgedParts=plan.length-pending.length;
  const emit=(extra={})=>{const loaded=Math.min(file.size,committed+[...inflight.values()].reduce((sum,value)=>sum+value,0));onTransfer({loaded,total:file.size,ratio:file.size?loaded/file.size:0,completedParts:acknowledgedParts,totalParts:plan.length,...extra})};
  emit();
  async function uploadOne(part){
    let attempt=0;
    while(true){
      if(control?.state&&control.state!=='active')throw new Error('ZIP 上传已暂停或取消');
      try{
        const result=await uploadZipPartXHR(projectId,uploadId,part,file,{xhrFactory,control,onTransfer:p=>{inflight.set(part.index,Math.min(part.size,Number(p.loaded)||0));emit()}});
        inflight.delete(part.index);committed+=part.size;acknowledgedParts++;emit();return result;
      }catch(error){
        inflight.delete(part.index);emit({retrying:true});
        if((control?.state&&control.state!=='active')||attempt>=retries)throw error;
        attempt+=1;await new Promise(resolve=>setTimeout(resolve,300*Math.pow(2,attempt-1)));
      }
    }
  }
  let failure=null;
  async function worker(){while(!failure){if(control?.state&&control.state!=='active')return;const index=cursor++;if(index>=pending.length)return;try{await uploadOne(pending[index])}catch(error){failure=error;for(const xhr of control?.xhrs||[])xhr.abort?.();throw error}}}
  await Promise.all(Array.from({length:Math.max(1,Math.min(Number(concurrency)||1,4,pending.length||1))},()=>worker()));
  if(control?.state&&control.state!=='active')throw new Error('ZIP 上传已暂停或取消');
  onPhase({stage:'正在合并与校验 ZIP',message:'所有分片上传完成，服务器正在合并并校验压缩包'});
  return completeZipUpload(projectId,uploadId,{fetchImpl});
}

export function isZipBootstrapReconcile(reason='') {
  return ['bootstrap', 'bootstrap-ready'].includes(String(reason || ''));
}

export function installZipImportRuntime({getState=()=>({}),projectId=()=>getState()?.project?.id,notify=m=>window.toast?.(m),fetchImpl=globalThis.fetch,pollMs=1000}={}) {
  if(typeof window==='undefined'||typeof document==='undefined') return null;
  let jobs=[],current=null,timer=null,busy=false,destroyed=false,uploading=null,uploadControl=null,resumeFile=null;
  let selectedJobId='';
  // UI-only ownership. Durable jobs and start receipts remain the existing owners.
  let presentation=null,activeUploadView=null,closingPresentation='';
  const uploadViews=new Map(),autoReviewCandidates=new Map();
  const topModal=()=>[...(document.querySelectorAll?.('.modal:not(.hidden)')||[])].at(-1)||null;
  const reviewUiKey=(project,id)=>`mc_zip_review_ui_v1:${project}:${id}`;
  function reviewUi(project,id,value){
    try{if(value)sessionStorage.setItem(reviewUiKey(project,id),value);return sessionStorage.getItem(reviewUiKey(project,id))||''}catch(_){return ''}
  }
  const shownReviews=new Set();
  function registerUploadView({projectId:project=pid(),layer,onHandoff}={}){
    if(!layer||String(project)!==pid())return null;
    let source=uploadViews.get(layer);
    if(!source){source={projectId:String(project),layer,closed:false,onHandoff};uploadViews.set(layer,source)}
    if(onHandoff)source.onHandoff=onHandoff;
    activeUploadView=source;return source;
  }
  function beforeModalClose(layer){
    const source=uploadViews.get(layer);
    if(source&&closingPresentation!=='handoff')source.closed=true;
    if(presentation?.layer!==layer)return;
    if(!closingPresentation&&presentation.jobId){
      shownReviews.add(`${presentation.projectId}:${presentation.jobId}`);
      reviewUi(presentation.projectId,presentation.jobId,'dismissed');
    }
    presentation=null;
  }
  function closeOwnedLayer(layer,reason){
    if(!layer)return false;
    closingPresentation=reason;
    try{
      if(window.closeModalLayer424)return window.closeModalLayer424(layer);
      if(topModal()===layer){window.closeModal?.();beforeModalClose(layer);return true}
      return false;
    }finally{closingPresentation=''}
  }
  function acceptedReview(id){return readIntent(pid(),id)==='submitted'}
  function autoPresentReview(){
    if(destroyed||!pid()||submittingLabelJobs.size)return false;
    if(presentation){
      const live=presentation.projectId===pid()&&presentation.layer?.isConnected!==false&&!presentation.layer?.classList?.contains('hidden');
      if(live){
        const shown=jobs.find(row=>String(row.id)===presentation.jobId);
        if(shown&&zipNeedsLabelConfirmation(shown)&&!acceptedReview(String(shown.id))&&!presentation.reviewMounted){if(topModal()!==presentation.layer)return false;selectedJobId=String(shown.id);current=shown;patchState(shown);return open()}
        return false;
      }
      beforeModalClose(presentation.layer);
    }
    const next=orderZipJobs(jobs).find(job=>{
      const id=String(job.id||''),source=autoReviewCandidates.get(id);
      return source?.projectId===pid()&&!source.closed&&zipNeedsLabelConfirmation(job)&&!acceptedReview(id)
        &&!shownReviews.has(`${pid()}:${id}`)&&!reviewUi(pid(),id);
    });
    if(!next)return false;
    const id=String(next.id),source=autoReviewCandidates.get(id),top=topModal();
    if(top&&top!==source.layer)return false;
    if(top){source.onHandoff?.();if(!closeOwnedLayer(top,'handoff'))return false;uploadViews.delete(top);source.layer=null;source.onHandoff=null}
    if(!isCurrentProject(source.projectId))return false;
    selectedJobId=id;current=next;patchState(next);return open();
  }

  const batchTransfers=new Map(),batchFiles=new Map(),withBatchSlot=createZipTransferLimiter(2);
  const transferObservers=new Set();
  const subscribeTransfers=listener=>{if(typeof listener!=='function')throw new TypeError('传输观察者必须是函数');transferObservers.add(listener);return ()=>transferObservers.delete(listener)};
  function publishTransfer(type,control,detail={}){
    if(destroyed||!control||String(control.project)!==pid())return;
    const event={type,projectId:control.project,file:control.file,transferId:control.transferId||control.uploadId||'',uploadId:control.uploadId||'',total:Number(control.file?.size||0),...detail};
    for(const listener of [...transferObservers])try{listener(event)}catch(error){transferObservers.delete(listener);console.warn('ZIP传输界面观察者已解除，原上传继续',error?.message||'')}
  }
  let localUploadSequence=0,queueSequence=0;
  const eligibleSince=new Map(),started=new Set(),knownJobs=new Map(),completionEffects=new Set(),foregroundImports=new Set(),labelReviews=new Map(),classSampleCache=new Map(),cancellingJobs=new Set();
  const pid=()=>String(projectId?.()||'');
  const localUploadId=()=>`local-${Date.now().toString(36)}-${(++localUploadSequence).toString(36)}`;
  function refreshQueuedUploadPositions(){
    const project=pid();
    const queued=[...batchTransfers.entries()]
      .filter(([,control])=>control?.localOnly&&control.project===project&&control.state==='queued')
      .sort((a,b)=>Number(a[1].queueSequence||0)-Number(b[1].queueSequence||0));
    queued.forEach(([id,control],index)=>{
      window.UploadTaskCenterRuntime?.upsert?.({
        id:`zip:${id}`,kind:'zip',title:control.file.name,status:'WAITING_UPLOAD',progress:0,
        stage:`等待上传 · 第 ${index+1} 位`,detail:'已受理，等待浏览器上传槽位',
        fileSize:Number(control.file.size||0),queuePosition:index+1,localOnly:true,
        browserTransfer:false,resumeRequired:false,pollOwner:'zip-import-runtime',
      });
    });
  }
  function trackTransferStop(control){
    control.stopped=new Promise(resolve=>{control.finish=()=>{control.stoppedComplete=true;resolve()}});
    return control;
  }
  function registerQueuedUpload(project,file,index){
    const id=localUploadId();
    const control=trackTransferStop({state:'queued',localOnly:true,project,file,transferId:id,xhrs:new Set(),uploadId:'',progress:0,message:'等待上传',queueSequence:++queueSequence,selectionIndex:index});
    batchTransfers.set(id,control);batchFiles.set(id,file);
    publishTransfer('queued',control);
    window.UploadTaskCenterRuntime?.upsert?.({
      id:`zip:${id}`,kind:'zip',title:file.name||`ZIP ${index+1}`,status:'WAITING_UPLOAD',progress:0,
      stage:'等待上传',detail:'文件已受理，正在进入上传队列',fileSize:Number(file.size||0),
      queuePosition:index+1,localOnly:true,browserTransfer:false,resumeRequired:false,pollOwner:'zip-import-runtime',
    });
    return {id,file,control,index};
  }
  function failLocalUpload(entry,message){
    entry.control.state='failed';batchTransfers.delete(entry.id);batchFiles.delete(entry.id);
    publishTransfer('error',entry.control,{error:new Error(message),message:String(message)});
    window.UploadTaskCenterRuntime?.upsert?.({
      id:`zip:${entry.id}`,kind:'zip',title:entry.file.name||'ZIP 文件',status:'FAILED',progress:0,
      stage:'无法受理',detail:String(message||'文件不可用'),fileSize:Number(entry.file.size||0),
      queuePosition:null,localOnly:true,browserTransfer:false,resumeRequired:false,pollOwner:'',
    });
    refreshQueuedUploadPositions();
  }
  function cancelQueuedUpload(id=''){
    const key=String(id||'').replace(/^zip:/,'');
    const control=batchTransfers.get(key);
    if(!control?.localOnly||!['queued','preparing','active'].includes(control.state))return false;
    control.state='cancelled';for(const xhr of control.xhrs||[])xhr.abort?.();
    publishTransfer('cancelled',control);
    batchTransfers.delete(key);batchFiles.delete(key);
    window.UploadTaskCenterRuntime?.upsert?.({
      id:`zip:${key}`,kind:'zip',title:control.file?.name||'ZIP 文件',status:'CANCELLED',progress:control.progress||0,
      stage:'已取消',detail:'已停止该文件；尚未提交的临时会话会按安全边界清理。',fileSize:Number(control.file?.size||0),
      queuePosition:null,localOnly:true,browserTransfer:false,resumeRequired:false,pollOwner:'',
    });
    refreshQueuedUploadPositions();notify?.(`${control.file?.name||'ZIP 文件'} 已取消`);return true;
  }
  let runtimeProject='';
  function resetProjectState(project){
    const next=String(project||'');
    if(runtimeProject===next)return;
    if(runtimeProject&&runtimeProject!==next){
      for(const control of batchTransfers.values()){
        control.state='project-switched';
        for(const xhr of control.xhrs||[])xhr.abort?.();
      }
      batchTransfers.clear();batchFiles.clear();
    }
    runtimeProject=next;jobs=[];current=null;selectedJobId='';uploading=null;resumeFile=null;presentation=null;activeUploadView=null;uploadViews.clear();autoReviewCandidates.clear();shownReviews.clear();
    eligibleSince.clear();started.clear();knownJobs.clear();completionEffects.clear();foregroundImports.clear();labelReviews.clear();classSampleCache.clear();cancellingJobs.clear();
  }
  const isCurrentProject=project=>!destroyed&&Boolean(project)&&runtimeProject===String(project)&&pid()===String(project);
  const intentKey=(p,id)=>`mc_zip_import_start_v1:${p}:${id}`;
  const readIntent=(p,id)=>{try{return localStorage.getItem(intentKey(p,id))||''}catch(_){return''}};
  const writeIntent=(p,id,v)=>{try{v?localStorage.setItem(intentKey(p,id),v):localStorage.removeItem(intentKey(p,id))}catch(_){}};
  const seconds=v=>Number.isFinite(Number(v))?`${Number(v).toFixed(1)} 秒`:'-';
  const bytes=v=>{const n=Math.max(0,Number(v)||0);return n>=1048576?`${(n/1048576).toFixed(1)} MB`:`${(n/1024).toFixed(1)} KB`};
  const mergeJobs=server=>{
    const byId=new Map((server||[]).map(job=>[String(job?.id||''),{...knownJobs.get(String(job?.id||'')),...job}]));
    for(const [id,job] of knownJobs){
      if(!byId.has(id)||(status(job)!=='unknown'&&readIntent(pid(),id)==='submitted'&&zipNeedsLabelConfirmation(byId.get(id))&&!zipNeedsLabelConfirmation(job)))byId.set(id,job);
    }
    return orderZipJobs([...byId.values()].filter(job=>job?.id&&!job.history_hidden));
  };
  function markUnknown(job,error=null){
    const row=unverifiedUploadTask({id:'zip:'+job.id,progress:overallZipProgress(job),updatedAt:job.updated_at},error);
    return {...job,status:'unknown',progress:row.progress,verificationReason:row.verificationReason,nextVerifyAt:row.nextVerifyAt,error:row.detail};
  }
  function recoverCachedJobs(){
    for(const row of window.UploadTaskCenterRuntime?.list?.()||[]){
      const id=String(row.id||'').replace(/^zip:/,'');
      if(row.kind!=='zip'||row.localOnly||row.browserTransfer||knownJobs.has(id)||!['UNKNOWN',...Array.from(ACTIVE_ZIP_STATUSES,s=>s.toUpperCase())].includes(String(row.status)))continue;
      knownJobs.set(id,{id,status:'unknown',file_name:row.title,progress:row.progress,updated_at:row.updatedAt,created_at:row.createdAt,nextVerifyAt:Number(row.nextVerifyAt||0),error:row.detail});
    }
  }
  function labelItems(){
    const state=getState()||{},rows=Array.isArray(state.labels)?state.labels:[];
    const normalized=rows.map(row=>typeof row==='string'?{code:String(row),display_name:String(row),status:'active'}:row).filter(row=>row?.code&&String(row.status||'active').toLowerCase()==='active');
    const fromProject=(Array.isArray(state.project?.labels)?state.project.labels:[]).map(row=>typeof row==='string'?{code:String(row),display_name:String(row),status:'active'}:row).filter(row=>row?.code);
    const byCode=new Map();
    for(const row of [...normalized,...fromProject])if(!byCode.has(String(row.code)))byCode.set(String(row.code),row);
    return [...byCode.values()];
  }
  function mappingReview(job){
    const id=String(job?.id||''),classes=job?.external_classes||[];
    const existing=labelReviews.get(id);
    const review=existing?reconcileLabelMappingReview(existing,classes):createLabelMappingReview(classes);
    review.pendingCreate=Object.fromEntries(Object.entries(existing?.pendingCreate||{})
      .filter(([classId,code])=>review.rows.some(row=>row.classId===classId)&&review.mapping[classId]===code));
    if(!existing)applyExactLabelCodeMatches(review,labelItems());
    labelReviews.set(id,review);
    return review;
  }

  function labelMappingMarkup(job){
    if(!zipNeedsLabelConfirmation(job)||acceptedReview(String(job.id||'')))return '';
    const id=String(job.id||''),review=mappingReview(job),page=labelMappingReviewPage(review),summary=labelMappingReviewSummary(review),labels=labelItems();
    const keepCodes=page.rows.map(row=>row.code).filter(Boolean);
    const visibleLabels=filterCanonicalLabels(labels,review.targetQuery,keepCodes);
    const options=(selected,classId)=>['<option value="">选择平台标签</option>',...(
      review.pendingCreate?.[classId]===selected && !labels.some(label=>String(label.code)===selected)
        ? [`<option value="${esc(selected)}" selected>待新建 · ${esc(selected)}</option>`] : []
    ),...visibleLabels.map(label=>{
      const code=String(label.code);return `<option value="${esc(code)}" ${String(selected||'')===code?'selected':''}>${esc(label.display_name||code)} · ${esc(code)}</option>`;
    })].join('');
    const rows=page.rows.map(row=>{
      const source=String(row.name||''),mapped=String(row.code||'');
      const codeLabel=mapped?esc(mapped):'<span class="zip-label-unmapped">待确认</span>';
      return `<div class="zip-label-item label-mapping-review-row" data-zip-class="${esc(row.classId)}" data-source-name="${esc(source)}">
        <button type="button" class="zip-label-source" onclick="window.ZipImportRuntime?.showLabelSamples(${jsArg(id)},${jsArg(row.classId)},${jsArg(encodeURIComponent(source))})"><strong>${esc(source||('class_'+row.classId))}</strong><small>class_id ${esc(row.classId)} · ${Number(row.imageCount||0)} 图 / ${Number(row.boxCount||0)} 框</small></button>
        <span class="zip-label-arrow">→</span><div class="zip-label-destination"><b>${codeLabel}</b>
        <select class="select zip-label-target-select" data-zip-target onchange="window.ZipImportRuntime?.setLabelMapping(${jsArg(id)},${jsArg(row.classId)},this.value)">${options(row.code,row.classId)}</select>
        </div><div class="zip-label-row-actions"><button type="button" class="btn mini" onclick="window.ZipImportRuntime?.useSourceLabel(${jsArg(id)},${jsArg(row.classId)})">使用原标签</button><button type="button" class="btn mini" onclick="window.openInlineLabelCreate414?.('zip',${jsArg(encodeURIComponent(String(row.classId)))})">新建平台标签</button>
        <label class="label-mapping-review-check"><input type="checkbox" ${row.selected?'checked':''} onchange="window.ZipImportRuntime?.toggleLabelRow(${jsArg(id)},${jsArg(row.classId)},this.checked)">批量选择</label></div></div>`;
    }).join('');
    const activeCodes=new Set(labels.map(label=>String(label.code)));
    const pendingCodes=[...new Set(Object.entries(review.pendingCreate||{})
      .filter(([classId,code])=>review.mapping[classId]===code&&!activeCodes.has(code))
      .map(([,code])=>code))];
    const planned=pendingCodes.length?`<div class="zip-label-pending" role="status"><b>确认导入时将新建 ${pendingCodes.length} 个平台标签</b><span>${pendingCodes.map(code=>`<code>${esc(code)}</code>`).join('')}</span><small>现在只是待确认的映射，不会提前写入平台标签库。</small></div>`:'';
    const bulkOptions=['<option value="">批量映射到…</option>',...filterCanonicalLabels(labels,review.targetQuery).map(label=>`<option value="${esc(label.code)}">${esc(label.display_name||label.code)} · ${esc(label.code)}</option>`)].join('');
    return `<div class="storage61-import-mapping zip-label-confirm label-mapping-review ${review.manualExpanded?'manual-expanded':''}" data-zip-label-mapping data-review-key="${esc(id)}">
      <header class="zip-label-heading"><div><h2>确认素材标签</h2><p>${esc(job.file_name||'ZIP 素材')}</p><small data-zip-review-order>待确认第 ${Math.max(1,orderZipJobs(jobs).filter(row=>zipNeedsLabelConfirmation(row)&&!acceptedReview(String(row.id))).findIndex(row=>String(row.id)===id)+1)} / ${orderZipJobs(jobs).filter(row=>zipNeedsLabelConfirmation(row)&&!acceptedReview(String(row.id))).length} 个 · 任务 ${esc(id)}</small></div><span class="pill ${summary.unmapped?'warn':'ok'}">${summary.mapped}/${summary.total} 已匹配</span></header>
      <div class="zip-label-metrics"><span>图片 <b>${Number(job.image_count||0)}</b></span><span>原始标签 <b>${summary.total}</b></span><span>已匹配 <b>${summary.mapped}</b></span><span>待确认 <b>${summary.unmapped}</b></span></div>
      <div class="zip-label-actions"><button class="btn" onclick="window.ZipImportRuntime?.matchExistingLabels('${esc(id)}')">匹配已有标签</button><span class="zip-label-actions-hint">每行可以直接修改目标标签，无需进入手动模式</span></div>
      ${planned}
      <div class="zip-label-workspace"><div class="zip-label-source-column"><div class="zip-label-column-head"><b>原始标签 → 平台标签</b><small>点击名称查看图片</small></div><div class="label-mapping-review-rows">${rows||'<div class="empty">暂无外部标签</div>'}</div></div>
      <div class="zip-label-preview-column"><div class="zip-label-column-head"><b>真实图片与标注框</b></div><div class="label-mapping-sample-panel" data-zip-class-samples>点击左侧原始标签查看对应图片及真实标注框</div></div></div>
      <details class="zip-label-advanced" ${review.advancedExpanded?'open':''} ontoggle="window.ZipImportRuntime?.setAdvancedExpanded('${esc(id)}',this.open)"><summary>高级筛选与批量映射</summary>
        <div class="label-mapping-review-tools"><input class="input" value="${esc(review.query)}" placeholder="搜索原始标签 / class_id" onchange="window.ZipImportRuntime?.setReviewSearch('${esc(id)}',this.value)"><input class="input" value="${esc(review.targetQuery)}" placeholder="搜索平台编码或名称" onchange="window.ZipImportRuntime?.setTargetSearch('${esc(id)}',this.value)"><select class="select" data-zip-bulk-target>${bulkOptions}</select><button class="btn mini" onclick="window.ZipImportRuntime?.bulkMapLabels('${esc(id)}')">映射选中项</button></div>
        <div class="label-mapping-review-page-info">当前 ${page.rows.length} / ${page.filtered} 条 · 第 ${page.page}/${page.pageCount} 页</div><div data-zip-label-pagination></div>
      </details>
      <div class="zip-label-footer"><small data-zip-confirm-status>${summary.unmapped?'还剩 '+summary.unmapped+' 个标签需人工确认':'全部标签已匹配'}</small><div class="zip-label-footer-actions"><button class="btn danger zip-label-cancel" data-zip-cancel-button aria-label="取消当前 ZIP 导入任务" ${cancellingJobs.has(id)||job.cancel_requested?'disabled':''} onclick="window.ZipImportRuntime?.cancelJob('${esc(id)}')">${cancellingJobs.has(id)||job.cancel_requested?'正在取消…':'取消此 ZIP 任务'}</button><button class="btn" ${cancellingJobs.has(id)||job.cancel_requested?'disabled':''} onclick="window.ZipImportRuntime?.previewOriginalLabels('${esc(id)}')">一键使用原始标签</button><button class="btn primary" data-zip-confirm-button ${summary.unmapped||cancellingJobs.has(id)||job.cancel_requested?'disabled':''} onclick="window.ZipImportRuntime?.confirmLabels('${esc(id)}')">${pendingCodes.length?'创建标签并导入':'确认标签并导入'}</button></div></div>
    </div>`;
  }

  function dock(){let n=document.getElementById('zipImportDurableDock');if(!n){n=document.createElement('button');n.id='zipImportDurableDock';n.type='button';n.className='import411-dock hidden';n.onclick=()=>open();document.body.appendChild(n)}return n}
  function resultMarkup(job){const s=status(job),r=job?.report||{};if(s==='unknown')return `<div class="alert warn">${esc(zipView(job,jobs).message)}<br>任务 ID：${esc(job.id)} · 最后服务器记录：${esc(job.updated_at||'未记录')}<button class="btn" onclick="window.ZipImportRuntime?.openTask('${esc(job.id)}')">重新核验状态</button></div>`;if(s==='done'){const warns=(r.warnings||[]).map(x=>`<li>${esc(x)}</li>`).join('');return `<div class="alert ok"><b>导入完成</b>：${Number(r.imported_images||0)} 张图片，其中 ${Number(r.annotated_images||0)} 张带标注，${Number(r.boxes||0)} 个框。</div>${warns?`<ul class="zip410-warn">${warns}</ul>`:''}`}if(s==='failed'&&job?.cleanup_status==='failed')return `<div class="alert err"><b>取消清理失败，可重试</b>：${esc(job?.cleanup_error||job?.error||'临时缓存尚未清理完成')}</div>`;if(s==='failed')return `<div class="alert err"><b>导入失败</b>：${esc(job?.error||job?.message||'未知错误')}</div>`;if(s==='cancelled'||s==='canceled')return '<div class="alert warn">本次 ZIP 导入已中断；未提交的缓存已由后台按安全边界清理。</div>';return''}
  function setZipProgressBar(node,value){
    if(!node)return;
    const progress=clamp(value);
    node.dataset.progress=progress.toFixed(2);
    node.style.transform=`scaleX(${(progress/100).toFixed(4)})`;
  }
  function patchState(job){
    if(!job)return;
    const v=zipView(job,jobs),s=getState()||{},previous=s.import411||{},same=String(previous.jobId||'')===String(job.id||'');
    const previousResult=same?String(previous.resultHtml||''):'';
    const nextResult=TERMINAL_ZIP_STATUSES.has(v.status)&&previousResult.includes('review412-btn')?previousResult:resultMarkup(job);
    const phase=zipPhaseDetail(job);
    s.import411={...(same?previous:{}),active:ACTIVE_ZIP_STATUSES.has(v.status),jobId:String(job.id||''),fileName:job.file_name||previous.fileName||'ZIP 数据导入',fileSize:Number(job.uploaded_bytes||previous.fileSize||0),stage:v.stage,message:v.message,progress:v.progress,eta:phase.etaSeconds??job.eta_seconds??null,uploadSeconds:job.upload_seconds??previous.uploadSeconds??null,processSeconds:job.processing_seconds??job.scan_seconds??previous.processSeconds??null,serverStatus:v.status,queuePosition:v.queue.position,resultHtml:nextResult};
  }
  function body(job){
    const s=status(job),v=zipView(job,jobs),phase=zipPhaseDetail(job),active=activeZipJobs(jobs);
    const queue=v.queue.waits?`正式队列第 ${v.queue.position} 位 · 前面 ${v.queue.ahead} 个任务`:(active.length>1?`当前 ${active.length} 个活动 ZIP 导入任务`:'后台任务状态以服务器为准');
    const stateResult=String((getState()||{}).import411?.resultHtml||resultMarkup(job));
    const cancellationPending=cancellingJobs.has(String(job.id||''))||Boolean(job.cancel_requested&&s!=='failed');
    const cleanupRetry=s==='failed'&&job?.cleanup_status==='failed';
    const cancelButton=`<button class="btn danger" data-zip-cancel-button aria-label="取消当前 ZIP 导入任务" ${cancellationPending?'disabled':''} onclick="window.ZipImportRuntime?.cancelJob('${esc(job.id)}')">${cancellationPending?'正在取消…':(cleanupRetry?'重试取消清理':'取消此 ZIP 任务')}</button>`;
    const lifecycleActions=(ACTIVE_ZIP_STATUSES.has(s)||cleanupRetry)&&!zipNeedsLabelConfirmation(job)&&String(job?.phase||'')!=='DB_COMMIT'?`<div class="row end zip-lifecycle-actions">${cancelButton}</div>`:'';
    const uploadActions=(s==='uploading'||s==='paused')?`<div class="row end zip-lifecycle-actions"><button class="btn" onclick="window.ZipImportRuntime?.pauseUpload('${esc(job.id)}')" ${s==='paused'||cancellationPending?'disabled':''}>暂停上传</button><button class="btn primary" onclick="window.ZipImportRuntime?.promptResume('${esc(job.id)}')" ${cancellationPending?'disabled':''}>继续上传</button>${cancelButton}<input id="zipResumeFile" data-file426="1" type="file" accept=".zip" style="display:none" onchange="window.ZipImportRuntime?.resumeFromFile(this,'${esc(job.id)}')"></div>`:'';
    const cancelAll=active.length>1?`<button class="btn danger ghost" onclick="window.ZipImportRuntime?.cancelAllActive()">取消全部活动 ZIP</button>`:'';
    return `<div class="zip411" data-zip-runtime="1" data-zip-project="${esc(pid())}" data-zip-job="${esc(job.id)}"><section class="zip411-head"><div><b>${esc(job?.file_name||(getState()||{}).import411?.fileName||'ZIP 数据导入')}</b><span>${bytes(job?.uploaded_bytes||(getState()||{}).import411?.fileSize||0)}</span></div><div class="row">${cancelAll}<button class="btn" onclick="closeModal()">关闭窗口</button></div></section><div class="zip411-main"><div class="zip411-progress"><div><span id="zipDurableStage">${esc(v.stage)}</span><b id="zipDurablePct">${s==='unknown'?'最后记录 '+v.progress+'%':Math.round(v.progress)+'%'}</b></div><i><em id="zipDurableBar" data-progress="${Number(v.progress).toFixed(2)}" style="transform:scaleX(${(Number(v.progress)/100).toFixed(4)})"></em></i><p id="zipDurableMsg">${esc(v.message)}</p><small id="zipDurablePhaseMeta" class="item-sub">${esc(phase.text)}</small></div><div id="zipDurableQueue" class="alert ${v.queue.waits?'warn':'ok'}">${esc(queue)}</div><div class="zip411-times"><div><span>上传时间</span><b>${seconds(job?.upload_seconds)}</b></div><div><span>ZIP扫描</span><b>${seconds(job?.scan_seconds)}</b></div><div><span>后台处理</span><b>${seconds(job?.processing_seconds)}</b></div></div><div id="zip411Result">${stateResult}</div>${labelMappingMarkup(job)}${uploadActions||(zipNeedsLabelConfirmation(job)?'':lifecycleActions)}</div></div>`;
  }
  function uploadBody(){return `<div class="zip411" data-zip-runtime="1"><div class="zip411-main"><div class="zip411-progress"><div><span>正在上传 ZIP</span><b id="zipDurableUploadPct">${Math.round(uploading?.progress||0)}%</b></div><i><em id="zipDurableUploadBar" data-progress="${Number(uploading?.progress||0).toFixed(2)}" style="transform:scaleX(${(Number(uploading?.progress||0)/100).toFixed(4)})"></em></i><p id="zipDurableUploadMsg">${esc(uploading?.message||'准备上传')}</p></div><div class="alert warn">这里仅显示当前网络上传的真实进度；上传完成后，合并、校验、扫描、解压和入库均以服务器任务状态为准。</div><div class="row end"><button class="btn" onclick="window.ZipImportRuntime?.pauseUpload()">暂停上传</button><button class="btn danger" data-zip-cancel-button onclick="window.ZipImportRuntime?.cancelJob()">取消此 ZIP 任务</button></div></div></div>`}
  function replaceOpenRuntime(html){
    const currentRoot=presentation?.projectId===pid()&&presentation.layer===topModal()?presentation.layer.querySelector('.zip411[data-zip-runtime="1"]'):null;
    if(!currentRoot)return false;
    const shell=document.createElement('div');shell.innerHTML=html;const next=shell.firstElementChild;
    if(next){currentRoot.replaceWith(next);return true}
    return false;
  }
  function mountLabelReviewPagination(jobId) {
    const id=String(jobId||''),root=document.querySelector('.zip-label-confirm[data-review-key]');
    if(!id||!root||String(root.getAttribute('data-review-key')||'')!==id)return false;
    const pager=root.querySelector('[data-zip-label-pagination]');
    if(!pager)return false;
    const review=mappingReview(reviewJob(id)),page=labelMappingReviewPage(review);
    window.PlatformCore?.pagination?.mountPagination?.(pager,{
      page:page.page,pageSize:page.pageSize,total:page.filtered,totalPages:page.pageCount,
    },{
      label:'ZIP 外部标签映射分页',showPageSize:true,pageSizes:[10,20,50,100],
      onPageChange:nextPage=>setReviewPage(id,nextPage),
      onPageSizeChange:size=>{
        review.pageSize=Math.max(10,Math.min(100,Number(size)||50));
        review.page=1;
        rerenderLabelMapping(id);
      },
    });
    return true;
  }
  function restoreImportModal(){
    const layer=document.querySelector('.zip411[data-zip-runtime="1"]')?.closest('.modal.import350-minimized');
    if(!layer)return;
    layer.classList.remove('import350-minimized');
    const toggle=layer.querySelector('[data-import-minimize]');
    if(toggle){toggle.textContent='最小化';toggle.setAttribute('aria-label','最小化导入窗口')}
  }
  function open(){
    const showSingleUpload=uploading&&(!selectedJobId||String(uploading.uploadId||'')===selectedJobId);
    const html=showSingleUpload?uploadBody():(current?body(current):'');
    if(!html)return false;
    if(!replaceOpenRuntime(html))window.modal?.('ZIP 数据导入',html,true);
    const layer=topModal();
    if(layer){presentation={projectId:pid(),jobId:String(current?.id||selectedJobId||''),layer,reviewMounted:Boolean(current&&zipNeedsLabelConfirmation(current)&&!acceptedReview(String(current.id)))};if(current&&zipNeedsLabelConfirmation(current)&&!acceptedReview(String(current.id))){shownReviews.add(`${pid()}:${current.id}`);reviewUi(pid(),current.id,'shown')}}
    restoreImportModal();
    if(current)mountLabelReviewPagination(current.id);
    return true;
  }
  function updateOpenModal(job,active){
    if(!job||presentation?.projectId!==pid()||presentation?.jobId!==String(job.id))return;
    const v=zipView(job,jobs),phase=zipPhaseDetail(job),stage=document.getElementById('zipDurableStage'),pct=document.getElementById('zipDurablePct'),bar=document.getElementById('zipDurableBar'),msg=document.getElementById('zipDurableMsg'),phaseMeta=document.getElementById('zipDurablePhaseMeta'),q=document.getElementById('zipDurableQueue'),result=document.getElementById('zip411Result');
    const transfer=batchTransfers.get(String(job.id||''));
    const progress=transfer?.state==='active'?transfer.progress:v.progress;
    if(stage)stage.textContent=transfer?.state==='active'?'正在上传 ZIP':v.stage;
    if(pct)pct.textContent=status(job)==='unknown'?`最后记录 ${progress}%`:`${Math.round(progress)}%`;
    if(bar)bar.style.opacity=status(job)==='unknown'?'0.35':'1';
    setZipProgressBar(bar,progress);
    if(msg)msg.textContent=transfer?.state==='active'?transfer.message:v.message;
    if(phaseMeta)phaseMeta.textContent=transfer?.state==='active'?'其他文件进度在右下角任务中心查看':phase.text;
    if(q)q.textContent=v.queue.waits?`正式队列第 ${v.queue.position} 位 · 前面 ${v.queue.ahead} 个任务`:(active.length>1?`当前 ${active.length} 个活动 ZIP 导入任务`:'后台任务状态以服务器为准');
    if(result)result.innerHTML=String((getState()||{}).import411?.resultHtml||resultMarkup(job));
  }
  function updateDockContent(node,title,detail){
    // Keep the existing nodes during each progress tick; replacing innerHTML
    // causes visible repaint/flicker on the legacy fallback dock.
    if(!node.querySelector('[data-zip-dock-title]')){
      node.innerHTML='<span><b data-zip-dock-title></b><small data-zip-dock-detail></small></span><strong>展开</strong>';
    }
    const heading=node.querySelector('[data-zip-dock-title]'),subtitle=node.querySelector('[data-zip-dock-detail]');
    if(heading&&heading.textContent!==title)heading.textContent=title;
    if(subtitle&&subtitle.textContent!==detail)subtitle.textContent=detail;
  }
  function render(){
    const d=dock(),active=activeZipJobs(jobs);
    const source=uploadViews.get(topModal());
    if(!presentation&&source?.projectId===pid()&&!source.closed&&source.layer.querySelector?.('.zip411[data-zip-runtime="1"]'))presentation={projectId:pid(),jobId:String(current?.id||selectedJobId||''),layer:source.layer};
    if(window.UploadTaskCenterRuntime)d.classList.add('hidden');
    if(uploading&&(!selectedJobId||String(uploading.uploadId||'')===selectedJobId)){
      if(!window.UploadTaskCenterRuntime)d.classList.remove('hidden');
      updateDockContent(d,'正在上传 ZIP',`${Math.round(uploading.progress)}% · ${uploading.message}`);
      const pct=document.getElementById('zipDurableUploadPct'),bar=document.getElementById('zipDurableUploadBar'),msg=document.getElementById('zipDurableUploadMsg');
      if(pct)pct.textContent=`${Math.round(uploading.progress)}%`;
      setZipProgressBar(bar,uploading.progress);
      if(msg)msg.textContent=uploading.message;
      return;
    }
    current=jobs.find(job=>String(job?.id||'')===selectedJobId)||pickZipJob(jobs);
    if(!active.length)d.classList.add('hidden');
    else{
      const v=zipView(current,jobs);
      if(!window.UploadTaskCenterRuntime)d.classList.remove('hidden');
      updateDockContent(d,v.stage,`${Math.round(v.progress)}% · ${active.length} 个活动任务`);
    }
    updateOpenModal(current,active);
    autoPresentReview();
  }
  function clearPoll(){if(window.PollRegistryRuntime?.clear)window.PollRegistryRuntime.clear('zip-import-runtime');else if(timer)clearTimeout(timer);timer=null}
  function arm(){clearPoll();const unknown=jobs.filter(job=>status(job)==='unknown');if(destroyed||(!activeZipJobs(jobs).length&&!unknown.length))return;const delay=activeZipJobs(jobs).length?pollMs:Math.max(pollMs,Math.min(...unknown.map(job=>Number(job.nextVerifyAt||0)-Date.now())));const callback=()=>reconcile('poll').catch(()=>{});if(window.PollRegistryRuntime?.startTimeout){timer=window.PollRegistryRuntime.startTimeout('zip-import-runtime',[String((getState()||{}).page||'数据集')],callback,delay)}else timer=setTimeout(callback,delay)}
  async function refreshKnown(project,server){
    const listed=new Map(server.map(job=>[String(job.id),job]));
    const ids=[...knownJobs.keys()];
    for(const id of ids){
      if(!isCurrentProject(project))return false;
      const prior=knownJobs.get(id),observed=listed.get(id);
      // A stale list may still carry selecting after a confirmed start. Only
      // the original submitted receipt permits a targeted detail verification.
      const staleReview=observed&&readIntent(project,id)==='submitted'&&zipNeedsLabelConfirmation(observed)&&!zipNeedsLabelConfirmation(prior);
      if(observed&&!staleReview){knownJobs.set(id,{...prior,...observed,verificationReason:status(observed)==='unknown'?'UNAVAILABLE':'',nextVerifyAt:status(observed)==='unknown'?Date.now()+15000:0,error:observed.error||''});continue}
      if(!staleReview&&Number(prior.nextVerifyAt||0)>Date.now())continue;
      try{const detail=await getZipJob(project,id,{fetchImpl});if(!isCurrentProject(project))return false;if(detail?.id)knownJobs.set(id,{...prior,...detail,verificationReason:'',nextVerifyAt:0,error:detail.error||''})}
      catch(error){if(!isCurrentProject(project))return false;knownJobs.set(id,markUnknown(prior,error));const at=server.findIndex(job=>String(job.id)===id);if(at>=0)server.splice(at,1)}
    }
    return true;
  }
  async function createPlatformLabel(project,code,displayName=''){
    const labelCode=String(code||'').trim();
    if(!isCurrentProject(project))throw new Error('当前项目已切换，已停止本次标签确认');
    if(!PLATFORM_LABEL_CODE_RE.test(labelCode))throw new Error(`文件标签“${labelCode}”不能直接作为平台英文标签，请手动新建一个合法英文标签后映射`);
    try{
      await json(await fetchImpl(`/api/projects/${encodeURIComponent(project)}/labels`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:labelCode,display_name:String(displayName||labelCode)})}));
    }catch(error){
      if(!isCurrentProject(project))throw new Error('当前项目已切换，已停止本次标签确认');
      await window.refreshLabels414?.(false);
      if(!(getState()?.labels||[]).some(row=>String(row?.code||row)===labelCode))throw error;
      return labelCode;
    }
    if(!isCurrentProject(project))throw new Error('当前项目已切换，已停止本次标签确认');
    await window.refreshLabels414?.(false);
    return labelCode;
  }
  async function assertLabelConfirmationOpen(project,id){
    if(!isCurrentProject(project))throw new Error('当前项目已切换，已停止本次标签确认');
    const detail=await getZipJob(project,id,{fetchImpl});
    if(!isCurrentProject(project))throw new Error('当前项目已切换，已停止本次标签确认');
    if(status(detail)!=='selecting'||detail?.cancel_requested)throw new Error('该 ZIP 已不在待确认状态，不能继续创建标签或启动导入');
    knownJobs.set(id,{...(knownJobs.get(id)||{}),...detail});
    return detail;
  }
  function reviewJob(jobId){const id=String(jobId||'');return jobs.find(row=>String(row?.id||'')===id)||knownJobs.get(id)}
  function rerenderLabelMapping(jobId){
    const id=String(jobId||''),job=reviewJob(id),node=document.querySelector('.zip-label-confirm[data-review-key]');
    if(!job||!node||String(node.getAttribute('data-review-key')||'')!==id)return false;
    // Preserve the original evidence panel while the mapping form re-renders;
    // choosing a canonical label must not erase the picture being reviewed.
    const oldPanel=node.querySelector('[data-zip-class-samples]');
    const listScroll=node.querySelector('.label-mapping-review-rows')?.scrollTop||0;
    if(oldPanel)oldPanel.remove();
    node.outerHTML=labelMappingMarkup(job);
    const next=document.querySelector('.zip-label-confirm[data-review-key]');
    if(oldPanel&&next&&String(next.getAttribute('data-review-key')||'')===id){
      next.querySelector('[data-zip-class-samples]')?.replaceWith(oldPanel);
    }
    if(next)next.querySelector('.label-mapping-review-rows').scrollTop=listScroll;
    mountLabelReviewPagination(id);
    return true;
  }

  function sampleCardsMarkup(classId,name,samples){
    const cards=(samples||[]).map((sample,index)=>{
      const overlays=(Array.isArray(sample.bboxes)&&sample.bboxes.length?sample.bboxes:[sample.bbox]).slice(0,256).map(bbox=>{
        const box=labelSampleOverlay(bbox||{});
        const style=`left:${box.left.toFixed(3)}%;top:${box.top.toFixed(3)}%;width:${box.width.toFixed(3)}%;height:${box.height.toFixed(3)}%`;
        return `<i class="label-mapping-sample-box" style="${style}"></i>`;
      }).join('');
      const url=String(sample.preview_url||'');
      return `<article class="label-mapping-sample-card"><a href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="查看原图"><span class="label-mapping-sample-image"><img loading="lazy" decoding="async" src="${esc(url)}" alt="${esc(name)} 第 ${index+1} 张">${overlays}</span></a><footer><b>${esc(sample.filename||'ZIP 原图')}</b><span>红框为该外部类别的原始标注</span></footer></article>`;
    }).join('');
    return `<div class="row between"><b>外部类别 ${esc(name||('class_'+classId))} · 原图与标注框</b><button class="btn mini" onclick="this.closest('[data-zip-class-samples]').hidden=true">收起</button></div><div class="label-mapping-sample-grid">${cards||'<div class="empty">当前类别未找到可展示的图片与框；请核对 ZIP 原始数据后再决定映射。</div>'}</div>`;
  }

  async function showLabelSamples(jobId,classId,encodedName=''){
    const id=String(jobId||''),project=pid(),root=document.querySelector('.zip-label-confirm[data-review-key]');
    const panel=root?.querySelector('[data-zip-class-samples]');
    if(!project||!panel||String(root.getAttribute('data-review-key')||'')!==id)return null;
    const name=decodeURIComponent(String(encodedName||''));
    panel.hidden=false;
    panel.dataset.sampleClass=String(classId);
    panel.innerHTML='<div class="skeleton-shimmer label-mapping-sample-loading">正在读取原图…</div>';
    const key=`${project}:${id}:${classId}`;
    try{
      let cached=classSampleCache.get(key);
      if(!cached){
        cached=await json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(project)}/import/jobs/${encodeURIComponent(id)}/classes/${encodeURIComponent(String(classId))}/samples`,{credentials:'same-origin'}));
        if(!isCurrentProject(project))return null;
        classSampleCache.set(key,cached);
      }
      if(isCurrentProject(project)&&panel.isConnected&&panel.dataset.sampleClass===String(classId)){
         panel.innerHTML=sampleCardsMarkup(classId,name,cached.samples||[]);
         panel.querySelectorAll('.label-mapping-sample-image img').forEach(img=>img.addEventListener('error',()=>{
           if(!panel.isConnected||panel.dataset.sampleClass!==String(classId))return;
           const card=img.closest('.label-mapping-sample-card'),frame=card?.querySelector('.label-mapping-sample-image');
           if(!frame)return;
           frame.classList.add('label-mapping-sample-load-error');
           frame.textContent='原图读取失败，无法核对标注框';
           card?.querySelector('a')?.removeAttribute('href');
           const note=card?.querySelector('footer span');
           if(note)note.textContent='请核查 ZIP 原始文件后再决定映射';
         },{once:true}));
       }
      return cached;
    }catch(error){
      if(isCurrentProject(project)&&panel.isConnected&&panel.dataset.sampleClass===String(classId))panel.innerHTML=`<div class="alert err">原图读取失败：${esc(error.message||error)}。请勿在无法确认类别含义时盲目映射。</div>`;
      return null;
    }
  }
  function useSourceLabel(jobId,classId){
    const job=reviewJob(jobId),review=mappingReview(job),row=review.rows.find(item=>String(item.classId)===String(classId));
    if(!row)return notify?.('外部标签不存在');
    const source=String(row.name||'').trim();
    if(!PLATFORM_LABEL_CODE_RE.test(source)||/^(?:class|label)[_-]?\d+$/i.test(source)||/^unknown$/i.test(source))return notify?.('原标签无法直接作为平台编码，请在右侧下拉框选择已有标签或新建合法标签');
    const existing=labelItems().find(label=>String(label.code).toLowerCase()===source.toLowerCase());
    setLabelMapping(review,classId,existing?.code||source);
    if(existing)delete review.pendingCreate[String(classId)];
    else review.pendingCreate[String(classId)]=source;
    rerenderLabelMapping(jobId);
  }
  function previewOriginalLabels(jobId){
    const id=String(jobId||''),review=mappingReview(reviewJob(id));
    const plan=planOriginalLabelMappings(review,labelItems());
    for(const item of [...plan.reuse,...plan.create])setLabelMapping(review,item.classId,item.code);
    for(const item of plan.create)review.pendingCreate[item.classId]=item.code;
    review.sourcePlan=null;
    rerenderLabelMapping(id);
    if(plan.manual.length)notify?.('已匹配可直接沿用的标签；其余 '+plan.manual.length+' 个类别需人工确认');
    return plan;
  }
  function cancelOriginalLabels(jobId){
    const id=String(jobId||''),review=mappingReview(reviewJob(id));
    for(const [classId,code] of Object.entries(review.pendingCreate||{})){
      if(review.mapping[classId]===code)delete review.mapping[classId];
    }
    review.pendingCreate={};
    rerenderLabelMapping(id);
  }
  async function confirmOriginalLabels(jobId){
    return confirmLabels(jobId);
  }
  function matchExistingLabels(jobId){
    const id=String(jobId||''),review=mappingReview(reviewJob(id));
    review.sourcePlan=null;applyExactLabelCodeMatches(review,labelItems());rerenderLabelMapping(id);
  }
  function toggleManualLabels(jobId){
    const id=String(jobId||''),review=mappingReview(reviewJob(id));
    review.manualExpanded=!review.manualExpanded;review.sourcePlan=null;rerenderLabelMapping(id);
  }
  function setAdvancedExpanded(jobId,expanded){
    const review=mappingReview(reviewJob(jobId));review.advancedExpanded=Boolean(expanded);
  }
  function setReviewSearch(jobId,value){const review=mappingReview(reviewJob(jobId));setLabelMappingReviewSearch(review,value);rerenderLabelMapping(jobId)}
  function setTargetSearch(jobId,value){const review=mappingReview(reviewJob(jobId));setLabelMappingTargetSearch(review,value);rerenderLabelMapping(jobId)}
  function setReviewPage(jobId,page){const review=mappingReview(reviewJob(jobId));setLabelMappingReviewPage(review,page);rerenderLabelMapping(jobId)}
  function toggleLabelRow(jobId,classId,selected){const review=mappingReview(reviewJob(jobId));setLabelMappingSelected(review,classId,selected)}
  function setReviewLabelMapping(jobId,classId,code){const review=mappingReview(reviewJob(jobId));setLabelMapping(review,classId,code);delete review.pendingCreate[String(classId)];review.sourcePlan=null;rerenderLabelMapping(jobId)}
  function bulkMapLabels(jobId){try{const id=String(jobId||''),review=mappingReview(reviewJob(id)),code=String(document.querySelector('.zip-label-confirm [data-zip-bulk-target]')?.value||'').trim();bulkSetLabelMapping(review,code);rerenderLabelMapping(id)}catch(error){notify?.(error?.message||error)}}

  const submittingLabelJobs=new Set();
  async function confirmLabels(jobId){
    const project=pid(),id=String(jobId||''),job=jobs.find(row=>String(row?.id||'')===id)||knownJobs.get(id);
    if(!project||!job||!zipNeedsLabelConfirmation(job)||submittingLabelJobs.has(id)||acceptedReview(id))return null;
    submittingLabelJobs.add(id);
    const owned=presentation?.projectId===project&&presentation.jobId===id?presentation.layer:null;
    const ownedContent=owned?.querySelector('.zip411[data-zip-runtime="1"]');
    let accepted=false;
    const button=document.querySelector('.zip-label-confirm [data-zip-confirm-button]'),statusNode=document.querySelector('.zip-label-confirm [data-zip-confirm-status]'),review=mappingReview(job);
    const existing=new Set(labelItems().map(row=>String(row.code)));
    if(button){button.disabled=true;button.textContent='正在确认…'}
    document.querySelectorAll('.zip-label-confirm select,.zip-label-confirm input').forEach(input=>{input.disabled=true});
    try{
      await assertLabelConfirmationOpen(project,id);
      const label_mapping=buildManualLabelMapping(review);
      const toCreate=new Map();
      for(const row of review.rows){
        const code=String(label_mapping[row.classId]||'');
        if(existing.has(code))continue;
        if(review.pendingCreate?.[row.classId]!==code||!PLATFORM_LABEL_CODE_RE.test(code)){
          throw new Error(`平台标签 ${code} 不存在，请重新选择已有标签或点击“使用原标签”`);
        }
        toCreate.set(code,String(row.name||code));
      }
      if(toCreate.size&&statusNode)statusNode.textContent=`正在正式创建 ${toCreate.size} 个平台标签…`;
      for(const [code,name] of toCreate){
        if(cancellingJobs.has(id))throw new Error('该 ZIP 已请求取消，已停止创建后续标签');
        await assertLabelConfirmationOpen(project,id);
        await createPlatformLabel(project,code,name);
      }
      if(cancellingJobs.has(id))throw new Error('该 ZIP 已请求取消，不再启动正式导入');
      await assertLabelConfirmationOpen(project,id);
      const verified=new Set(labelItems().map(row=>String(row.code)));
      for(const code of Object.values(label_mapping)){
        if(!verified.has(String(code)))throw new Error(`平台标签 ${code} 创建或刷新失败，尚未提交导入`);
      }
      if(statusNode)statusNode.textContent='标签已确认，正在启动后台导入…';
      foregroundImports.add(id);started.add(id);writeIntent(project,id,'submitting');
      const response=await startZipJob(project,id,{fetchImpl,confirmation:{label_mapping}});
      accepted=true;writeIntent(project,id,'submitted');
      if(!isCurrentProject(project))return response;
      knownJobs.set(id,{...job,...response});
      // The base modal node can be reused by a newer business window.
      if(ownedContent?.isConnected&&ownedContent.closest('.modal')===owned)closeOwnedLayer(owned,'accepted');
      await reconcile('label-confirmation').catch(error=>notify?.('标签已确认，任务列表同步失败：'+String(error.message||error)));
      return response;
    }catch(error){
      if(!accepted){started.delete(id);writeIntent(project,id,'')}
      if(!isCurrentProject(project))throw error;
      if(button){button.disabled=false;button.textContent='确认标签并导入'}
      document.querySelectorAll('.zip-label-confirm select,.zip-label-confirm input').forEach(input=>{input.disabled=false});
      if(statusNode)statusNode.textContent=String(error?.message||error);
      notify?.(error?.message||error);throw error;
    }finally{submittingLabelJobs.delete(id);if(isCurrentProject(project))autoPresentReview()}
  }
  async function maybeStart(project){const next=orderZipJobs(jobs).find(row=>status(row)==='selecting'&&!zipNeedsLabelConfirmation(row)&&!started.has(String(row.id||'')));if(!next||!isCurrentProject(project))return false;const id=String(next.id||'');if(started.has(id))return false;const now=Date.now();if(!eligibleSince.has(id))eligibleSince.set(id,now);const action=zipStartDisposition(next,jobs,{intent:readIntent(project,id),eligibleForMs:now-eligibleSince.get(id)});if(!['start','start-legacy-recovery'].includes(action))return false;started.add(id);writeIntent(project,id,'submitting');try{await startZipJob(project,id,{fetchImpl});if(!isCurrentProject(project))return false;writeIntent(project,id,'submitted');return true}catch(e){if(isCurrentProject(project))started.delete(id);writeIntent(project,id,'ambiguous');throw e}}
  async function applyCompletion(project,job,reason){
    if(!job||status(job)!=='done')return;const id=String(job.id||'');
    // Recovered jobs must never auto-open a finished import or cleaning modal.
    if(!foregroundImports.has(id)||completionEffects.has(id))return;
    completionEffects.add(id);foregroundImports.delete(id);
    window.completeZipImportReview412?.(id,{autoOpen:false});window.invalidateQuality411?.();await window.refreshLabels414?.(false);if(!isCurrentProject(project))return;if((getState()||{}).page==='数据集')await window.reloadMaterialPage61?.();if(isCurrentProject(project))notify?.(`后台导入完成：${Number(job?.report?.imported_images||0)} 张图片`);
  }
  function publishTaskCenterJob(project,job){
    const v=zipView(job,jobs),s=status(job),localUpload=Boolean(uploading?.uploadId)&&String(uploading.uploadId)===String(job.id||'');
    const transfer=batchTransfers.get(String(job.id||''));
    const transferActive=s==='uploading'&&transfer?.state==='active';
    const legacyActive=s==='uploading'&&localUpload&&!uploading?.processing;
    const browserProgress=transferActive?transfer.progress:legacyActive?uploading.progress:null;
    const task={id:`zip:${job.id}`,kind:'zip',title:job.file_name||'ZIP 数据导入',status:String(job.status||'').toUpperCase(),progress:browserProgress??v.progress,progressKnown:s!=='unknown',verificationReason:job.verificationReason||'',nextVerifyAt:job.nextVerifyAt||0,updatedAt:job.updated_at,createdAt:job.created_at,stage:(transferActive||legacyActive)?'正在上传 ZIP':v.stage,detail:transferActive?transfer.message:legacyActive?uploading.message:v.message,serverUrl:`/api/v19/projects/${encodeURIComponent(project)}/import/jobs/${encodeURIComponent(String(job.id))}`,pollOwner:'zip-import-runtime',localOnly:false,queuePosition:null,fileSize:Number(transfer?.file?.size||job?.file_size||job?.uploaded_bytes||0)};
    if(s==='uploading'&&((localUpload&&uploading?.processing)||transfer?.state==='post-upload')){task.status='MERGING';task.progress=null;task.stage='正在合并与校验 ZIP';task.detail='网络上传完成，等待服务器合并与校验结果';task.browserTransfer=false;task.resumeRequired=false}
    else if(s==='uploading'&&(localUpload||batchTransfers.get(String(job.id||''))?.state==='active')){task.browserTransfer=true;task.resumeRequired=false}
    else if(s!=='uploading'){task.browserTransfer=false;task.resumeRequired=false}
    window.UploadTaskCenterRuntime?.upsert?.(task);
  }
  async function reconcile(reason='manual'){
    if(busy||destroyed)return current;const project=pid();if(!project)return null;resetProjectState(project);busy=true;
    try{
      recoverCachedJobs();
      let server=await listZipJobs(project,{fetchImpl});if(!isCurrentProject(project))return null;
      // Remember previously observed server jobs too, including those that did
      // not originate in this browser. Absence is verified by task ID, not by
      // scanning material or assuming that an omitted list row is completed.
      for(const job of jobs)if(!knownJobs.has(String(job.id)))knownJobs.set(String(job.id),job);
      for(const job of server)if(!knownJobs.has(String(job.id)))knownJobs.set(String(job.id),job);
      await refreshKnown(project,server);if(!isCurrentProject(project))return null;
      // Another tab may dismiss a completed job before this tab observes its
      // terminal state. Directly recovered archived evidence must still settle
      // the existing task-center row, even though it is absent from the list.
      for(const job of knownJobs.values())if(job.history_hidden)publishTaskCenterJob(project,job);
      jobs=mergeJobs(server);const startedNow=await maybeStart(project);if(!isCurrentProject(project))return null;if(!isZipBootstrapReconcile(reason)&&startedNow){server=await listZipJobs(project,{fetchImpl});if(!isCurrentProject(project))return null}jobs=mergeJobs(server);for(const job of jobs)publishTaskCenterJob(project,job);current=jobs.find(job=>String(job?.id||'')===selectedJobId)||pickZipJob(jobs);
      if(current){patchState(current);if(TERMINAL_ZIP_STATUSES.has(status(current))){if(readIntent(project,current.id)!=='submitted')writeIntent(project,current.id,'');eligibleSince.delete(String(current.id||''))}}
      render();for(const job of jobs){if(!isCurrentProject(project))return null;await applyCompletion(project,job,reason)}return current;
    }catch(error){if(isCurrentProject(project)){for(const [id,job] of knownJobs)if(!TERMINAL_ZIP_STATUSES.has(status(job)))knownJobs.set(id,markUnknown(job,error));jobs=mergeJobs([]);for(const job of jobs)publishTaskCenterJob(project,job);render()}throw error}
    finally{busy=false;if(pid()!==project&&!destroyed)queueMicrotask(()=>reconcile('project-switch').catch(()=>{}));else arm()}
  }
  const uploadActionUrl=(project,id,action)=>`/api/v19/projects/${encodeURIComponent(project)}/import/uploads/${encodeURIComponent(id)}/${action}`;
  async function uploadAction(project,id,action){return json(await fetchImpl(uploadActionUrl(project,id,action),{method:'POST',credentials:'same-origin'}))}
  async function pauseUpload(id=''){
    const project=pid();resetProjectState(project);
    const uploadId=String(id||(uploading?uploading.uploadId:current?.id)||'');
    if(!uploadId){notify?.('上传会话正在创建，尚不能暂停');return false}
    const batchControl=batchTransfers.get(uploadId);
    const control=batchControl||(uploadControl?.uploadId===uploadId?uploadControl:null);
    if(control){control.state='paused';for(const xhr of control.xhrs)xhr.abort?.()}
    try{
      await uploadAction(project,uploadId,'pause');
      // An aborted XHR can still be unwinding retry backoff. Resume only after
      // the original owner has released its transfer identity and slot.
      await control?.stopped;
      publishTransfer('paused',control);
      if(!isCurrentProject(project))return true;
      uploading=null;await reconcile('pause');
      if(isCurrentProject(project)&&!control?.externalView)open();
      return true;
    }catch(error){
      await control?.stopped;
      publishTransfer('error',control,{error,message:String(error.message||error)});
      if(isCurrentProject(project)){notify?.(error.message||error);await reconcile('pause-error')}
      return false;
    }
  }
  function clearCancelledJobCaches(project,jobId){
    const id=String(jobId||'');labelReviews.delete(id);eligibleSince.delete(id);started.delete(id);foregroundImports.delete(id);batchFiles.delete(id);
    for(const key of [...classSampleCache.keys()])if(String(key).startsWith(`${project}:${id}:`))classSampleCache.delete(key);
    writeIntent(project,id,'');
  }
  async function cancelJob(id='',skipConfirm=false){
    const project=pid();resetProjectState(project);
    const jobId=String(id||(uploading?uploading.uploadId:current?.id)||uploadControl?.uploadId||'');
    if(!skipConfirm&&!window.confirm?.('确定取消此 ZIP 任务？服务器只会清理该任务尚未提交的 ZIP、分片与临时解析缓存；已正式入库的数据和平台标签不会被删除。'))return false;
    const localControl=batchTransfers.get(jobId),cancelledControl=localControl||(uploadControl?.uploadId===jobId?uploadControl:null);
    if(localControl){localControl.state='cancelled';for(const xhr of localControl.xhrs)xhr.abort?.()}
    if(uploadControl&&(!jobId||uploadControl.uploadId===jobId)){uploadControl.state='cancelled';for(const xhr of uploadControl.xhrs)xhr.abort?.()}
    if(!jobId){uploading=null;resumeFile=null;uploadControl=null;window.closeModal?.();return true}
    if(cancellingJobs.has(jobId))return false;
    cancellingJobs.add(jobId);render();
    try{
      const response=await json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(project)}/import/jobs/${encodeURIComponent(jobId)}/cancel`,{method:'POST',credentials:'same-origin'}));
      publishTransfer('cancelled',cancelledControl);clearCancelledJobCaches(project,jobId);
      if(!isCurrentProject(project))return response.cleanup_status!=='failed';
      knownJobs.set(jobId,{...(knownJobs.get(jobId)||jobs.find(row=>String(row?.id||'')===jobId)||{}),...response});
      if(uploading?.uploadId===jobId)uploading=null;
      if(uploadControl?.uploadId===jobId)uploadControl=null;
      resumeFile=null;
      await reconcile('cancel-confirmed');
      if(document.querySelector('.zip411[data-zip-runtime="1"]'))open();
      if(response.cleanup_status==='failed')notify?.(response.cleanup_error||'取消请求已收到，但临时缓存清理失败，可重试');
      else notify?.(TERMINAL_ZIP_STATUSES.has(status(response))?'ZIP 任务已取消，未提交缓存已清理':'服务器已确认取消请求，正在安全停止当前阶段');
      return response.cleanup_status!=='failed';
    }catch(error){if(isCurrentProject(project)){notify?.(error.message||error);await reconcile('cancel-error')}return false}
    finally{cancellingJobs.delete(jobId);if(isCurrentProject(project))render()}
  }
  async function cancelAllActive(){
    const targets=activeZipJobs(jobs).filter(job=>String(job?.phase||'')!=='DB_COMMIT'&&!job.cancel_requested);
    if(!targets.length){notify?.('当前没有可取消的 ZIP 任务');return []}
    if(!window.confirm?.(`确定取消 ${targets.length} 个活动 ZIP 任务？每个任务将独立确认和清理，互不影响。`))return [];
    return Promise.allSettled(targets.map(job=>cancelJob(String(job.id||''),true)));
  }
  const cancelUpload=id=>cancelJob(id);
  const stopImport=id=>cancelJob(id);
  function promptResume(id){
    const target=String(id||'');
    const file=batchFiles.get(target);
    if(file&&!batchTransfers.has(target)){
      const dialog=document.querySelector('.zip411[data-zip-runtime="1"]')?.closest('.modal')||null;
      return upload({files:[file],value:'',closest:()=>dialog},target).then(result=>{if(result)batchFiles.delete(target);return result}).catch(()=>{});
    }
    if(resumeFile&&uploadControl?.uploadId===target){
      const dialog=document.querySelector('.zip411[data-zip-runtime="1"]')?.closest('.modal')||null;
      return upload({files:[resumeFile],value:'',closest:()=>dialog},target).catch(()=>{});
    }
    document.getElementById('zipResumeFile')?.click();return null;
  }
  function resumeFromFile(input,id){return upload(input,String(id||'')).catch(()=>null)}
  async function upload(input,expectedUploadId=''){
    const projectAtStart=pid();
    return withBatchSlot(release=>{
      if(pid()!==projectAtStart)throw new Error('项目已切换，请从原项目任务中心恢复');
      return uploadInSlot(input,expectedUploadId,release);
    });
  }
  const resumeTransfer=(file,uploadId)=>uploadBatch({files:[file],value:'',externalView:true,resumeUploadId:String(uploadId||'')});
  async function uploadInSlot(input,expectedUploadId='',releaseSlot=()=>{}){
    const file=input?.files?.[0];if(!file)return null;if(!/\.zip$/i.test(file.name||'')){notify?.('请选择 ZIP 压缩包');input.value='';return null}const project=pid();if(!project){notify?.('当前项目未加载，请刷新后重试');return null}resetProjectState(project);
    if(batchTransfers.get(String(expectedUploadId||''))?.state==='active')return notify?.('该 ZIP 正在上传，请勿重复提交');
    if(uploadControl?.state==='active')return notify?.('另一个 ZIP 正在恢复上传，请从任务中心查看');
    const control=trackTransferStop({state:'active',project,externalView:Boolean(input.externalView),xhrs:new Set(),uploadId:'',file,expectedUploadId});
    uploadControl=control;resumeFile=file;
    let multipartTaskId='';uploading={progress:0,message:'准备上传',uploadId:''};
    // The chooser already owns a modal. Replace that modal's content instead
    // of closing it asynchronously and stacking a second, inert dialog.
    const chooser=input.closest?.('.modal')||null;
    const reviewSource=(chooser?registerUploadView({projectId:project,layer:chooser}):activeUploadView)||{projectId:project,layer:null,closed:false};
    const chooserBody=chooser?.querySelector('.modal-body');
    if(chooserBody){
      if(window.ModalContentRuntime?.replace)window.ModalContentRuntime.replace(chooserBody,uploadBody());
      else chooserBody.innerHTML=uploadBody();
      const title=chooserBody.closest('.modal')?.querySelector('.modal-title');
      if(title)title.textContent='ZIP 数据导入';
    }else if(!control.externalView)open();
    render();
    try{
      const response=await uploadZipMultipartJob(project,file,{fetchImpl,control,onSession:session=>{multipartTaskId=String(session.upload_id||'');if(expectedUploadId&&multipartTaskId!==expectedUploadId)throw new Error('原 ZIP 身份未匹配历史会话，已阻止向新会话发送数据；请确认文件名、大小和修改时间');control.uploadId=multipartTaskId;publishTransfer('session',control);if(!isCurrentProject(project))return;const resumedUpload=Math.max(0,Math.min(100,Number(session.upload_progress)||0));uploading={...uploading,uploadId:multipartTaskId,progress:resumedUpload};window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${session.upload_id}`,kind:'zip',title:file.name,status:'UPLOADING',progress:resumedUpload,stage:'正在上传 ZIP',detail:`已完成 ${(session.completed_parts||[]).length}/${session.total_parts||0} 个分片`,serverUrl:`/api/v19/projects/${encodeURIComponent(project)}/import/jobs/${encodeURIComponent(String(session.upload_id))}`,browserTransfer:true,resumeRequired:false,pollOwner:'zip-import-runtime'})},onTransfer:e=>{publishTransfer('progress',control,e);if(control.state!=='active'||!uploading||!isCurrentProject(project))return;const networkPercent=Math.round(e.ratio*1000)/10;uploading={...uploading,progress:networkPercent,message:`${e.retrying?'分片传输中断，按实际字节重算 · ':''}网络上传 ${networkPercent}% · ${bytes(e.loaded)} / ${bytes(e.total)}`};window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${multipartTaskId}`,kind:'zip',title:file.name,status:'UPLOADING',progress:networkPercent,stage:'正在上传 ZIP',detail:uploading.message,browserTransfer:true,resumeRequired:false,pollOwner:'zip-import-runtime'});render()},onPhase:phase=>{releaseSlot();publishTransfer('processing',control,phase);if(!isCurrentProject(project))return;uploading={...uploading,progress:100,processing:true,message:phase.message};window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${multipartTaskId}`,kind:'zip',title:file.name,status:'MERGING',progress:null,stage:phase.stage,detail:phase.message,browserTransfer:false,resumeRequired:false,pollOwner:'zip-import-runtime'});render()}});if(isCurrentProject(project)){uploading=null;resumeFile=null}if(uploadControl===control)uploadControl=null;
      if(!isCurrentProject(project))return response;
      if(!response.id)throw new Error('ZIP交付身份不完整，请从任务中心核验');
      publishTransfer('success',control,{jobId:String(response.id),response});
      const provisional={...response,id:String(response.id),status:response.status||'selecting',stage:response.stage||'上传与校验完成',message:response.message||'上传与ZIP校验完成，等待开始后台导入',progress:Number(response.progress||0),file_name:response.file_name||file.name,uploaded_bytes:Number(response.uploaded_bytes||file.size||0),created_at:response.created_at||new Date().toISOString()};window.UploadTaskCenterRuntime?.rekey?.('zip:'+multipartTaskId,'zip:'+provisional.id);knownJobs.set(String(provisional.id),provisional);if(presentation?.layer===reviewSource.layer&&uploadViews.get(reviewSource.layer)===reviewSource)presentation=null;autoReviewCandidates.set(String(provisional.id),reviewSource);foregroundImports.add(String(provisional.id));writeIntent(project,provisional.id,'deferred');
      try {
        await reconcile('upload');
      } catch (refreshError) {
        // Completion is already accepted. A failed follow-up GET must not
        // turn the upload into a new failed transfer or invite duplicate import.
        jobs=mergeJobs([...jobs,provisional]);
        current=pickZipJob(jobs);
        if(current)patchState(current);
        publishTaskCenterJob(project,provisional);
        render();arm();
        notify?.('ZIP 已由服务器受理，但状态刷新暂时中断；可从右下角任务中心继续查看，请勿重复上传。');
      }
      return response;
    }catch(e){const lastUploadProgress=Number(uploading?.progress||0);if(isCurrentProject(project))uploading=null;
      // A failed browser transfer must relinquish its active controller; otherwise
      // choosing the same ZIP again is permanently blocked as "already uploading".
      if(uploadControl===control&&control.state==='active')uploadControl=null;
      if(control.state==='paused'||control.state==='cancelled')return null;
      if(!isCurrentProject(project))return null;
      publishTransfer('error',control,{error:e,message:String(e.message||e)});
      if(multipartTaskId){
        // A browser transport failure does not mean the server lost its parts.
        // Yield to the task center until the canonical runtime can reconnect.
        window.UploadTaskCenterRuntime?.upsert?.({
          id:`zip:${multipartTaskId}`,kind:'zip',title:file.name,status:'WAITING',
          progress:Math.max(0,lastUploadProgress),
          stage:e?.zipCompletionUncertain?'等待服务器确认':'上传中断，等待续传',
          detail:String(e?.message||e),serverUrl:`/api/v19/projects/${encodeURIComponent(project)}/import/jobs/${encodeURIComponent(multipartTaskId)}`,
          browserTransfer:false,resumeRequired:true,pollOwner:'',
        });
      }
      const html=`<div class="zip411" data-zip-runtime="1"><div class="alert err">${esc(e.message||e)}</div><div class="row end"><button class="btn" onclick="closeModal()">关闭</button></div></div>`;
      if(!control.externalView&&!replaceOpenRuntime(html))window.modal?.('ZIP 数据导入',html,true);
      notify?.(e.message||e);throw e
    }finally{input.value='';control.finish()}
  }

  async function uploadBatch(input,expectedUploadId=''){
    if(expectedUploadId)return upload(input,expectedUploadId);
    const files=Array.from(input?.files||[]);
    if(!files.length)return null;
    const project=pid();
    if(!project){notify?.('当前项目未加载');return null}
    resetProjectState(project);
    const chooser=input.closest?.('.modal')||null;
    const reviewSource=(chooser?registerUploadView({projectId:project,layer:chooser}):activeUploadView)||{projectId:project,layer:null,closed:false};
    const entries=files.map((file,index)=>registerQueuedUpload(project,file,index));
    for(const entry of entries)entry.control.externalView=Boolean(input.externalView);
    const validEntries=[];
    for(const entry of entries){
      if(!/\.zip$/i.test(entry.file.name||''))failLocalUpload(entry,'仅支持 ZIP 压缩包');
      else if(!Number(entry.file.size||0))failLocalUpload(entry,'文件为空，无法上传');
      else validEntries.push(entry);
    }
    refreshQueuedUploadPositions();
    if(!validEntries.length){notify?.('所选文件均无法受理，请查看上传任务中心');if(input&&'value' in input)input.value='';return null}
    // Registration above is synchronous: hashing can never delay user feedback.
    // All limiter reservations below are also made in selection order, so later
    // batches join the same FIFO instead of racing a second queue.
    const fingerprintPromises=validEntries.map(async entry=>{
      try{return {entry,fingerprint:await zipFingerprint(entry.file),error:null}}
      catch(error){return {entry,fingerprint:'',error}}
    });
    const fingerprintManifest=Promise.all(fingerprintPromises).then(rows=>{
      const ownerByFingerprint=new Map(),byId=new Map();
      for(const row of rows){
        const duplicateKey=zipBatchDuplicateKey(row.fingerprint);
        if(!row.error&&ownerByFingerprint.has(duplicateKey))row.duplicateOf=ownerByFingerprint.get(duplicateKey);
        else if(!row.error)ownerByFingerprint.set(duplicateKey,row.entry.id);
        byId.set(row.entry.id,row);
      }
      return byId;
    });
    try{
      let selectionMounted=false;
      // Every archive receives its own durable session. A failing session or
      // a review awaiting human input cannot hold the other browser uploads.
      const results=await mapZipUploadsConcurrent(validEntries,async entry=>withBatchSlot(async releaseSlot=>{
        const {file,control}=entry;
        if(control.state==='cancelled')return null;
        if(!isCurrentProject(project))throw new Error('项目已切换，请从原项目任务中心恢复');
        control.state='preparing';control.message='正在校验文件指纹';refreshQueuedUploadPositions();
        window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${entry.id}`,kind:'zip',title:file.name,status:'UPLOADING',progress:0,stage:'正在准备上传',detail:'正在校验文件身份并创建安全上传会话',fileSize:Number(file.size||0),queuePosition:null,localOnly:true,browserTransfer:true,resumeRequired:false,pollOwner:'zip-import-runtime'});
        const fingerprintRow=(await fingerprintManifest).get(entry.id);
        if(control.state==='cancelled')return null;
        if(fingerprintRow?.error){failLocalUpload(entry,`文件指纹计算失败：${fingerprintRow.error?.message||fingerprintRow.error}`);return null}
        if(fingerprintRow?.duplicateOf){failLocalUpload(entry,'本批次已选择内容相同的 ZIP 文件');return null}
        let item=null;
        try{
            const session=await createZipUploadSession(project,file,{fetchImpl,expectedUploadId:String(input.resumeUploadId||'')});
            const id=String(session.upload_id||'');
            if(!id)throw new Error('服务器未返回 ZIP 上传会话 ID');
            if(input.resumeUploadId&&id!==String(input.resumeUploadId))throw new Error('原ZIP身份未匹配历史会话，未发送任何分片');
            if(control.state==='cancelled'){
              try{await json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(project)}/import/jobs/${encodeURIComponent(id)}/cancel`,{method:'POST',credentials:'same-origin'}))}catch(cleanupError){notify?.(`取消后的临时上传会话清理失败：${cleanupError?.message||cleanupError}`)}
              return null;
            }
            if(!isCurrentProject(project))throw new Error('项目已切换，请从原项目任务中心恢复');
            if(batchTransfers.has(id)||(uploadControl?.uploadId===id&&!uploadControl.stoppedComplete))throw new Error('选中的 ZIP 已在上传，请勿重复提交');
            item={id,file};entry.serverId=id;
            batchTransfers.delete(entry.id);batchFiles.delete(entry.id);
            control.state='active';control.localOnly=false;control.uploadId=id;control.expectedUploadId=id;control.progress=0;control.message='准备网络上传';
            batchTransfers.set(id,control);batchFiles.set(id,file);
            window.UploadTaskCenterRuntime?.rekey?.(`zip:${entry.id}`,`zip:${id}`);
            window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${id}`,kind:'zip',title:file.name,status:'UPLOADING',progress:0,stage:'正在上传 ZIP',detail:'安全上传会话已建立',fileSize:Number(file.size||0),queuePosition:null,localOnly:false,serverUrl:`/api/v19/projects/${encodeURIComponent(project)}/import/jobs/${encodeURIComponent(id)}`,browserTransfer:true,resumeRequired:false,pollOwner:'zip-import-runtime'});
            const fallback={id,file_name:file.name,status:'uploading',created_at:new Date().toISOString(),uploaded_bytes:0,file_size:Number(file.size||0)};
            knownJobs.set(id,fallback);
            if(isCurrentProject(project))publishTaskCenterJob(project,fallback);
            publishTransfer('session',control);
            if(control.state==='paused'||control.state==='cancelled')return null;
            if(!selectionMounted&&isCurrentProject(project)){
              selectionMounted=true;selectedJobId=id;jobs=mergeJobs(jobs);
              current=jobs.find(x=>String(x.id||'')===selectedJobId)||null;
              if(current)patchState(current);
              const chooserBody=chooser?.querySelector('.modal-body');
              if(chooserBody){
                const html=current?body(current):'';
                if(window.ModalContentRuntime?.replace)window.ModalContentRuntime.replace(chooserBody,html);
                else chooserBody.innerHTML=html;
                const title=chooser.querySelector('.modal-title');if(title)title.textContent='ZIP 数据导入';
              }
              render();
            }
            const response=await uploadZipMultipartJob(project,item.file,{
              fetchImpl,control,
              onSession:session=>{
                if(String(session.upload_id||'')!==item.id)throw new Error('ZIP 续传身份不符，禁止覆盖其他文件');
              },
              onTransfer:event=>{
                if(control.state!=='active')return;
                publishTransfer('progress',control,event);
                control.progress=Math.round(event.ratio*1000)/10;
                control.message=(event.retrying?'分片传输中断，按实际字节重算 · ':'')+'网络上传 '+control.progress+'% · '+bytes(event.loaded)+' / '+bytes(event.total);
                if(isCurrentProject(project)){
                  window.UploadTaskCenterRuntime?.upsert?.({id:'zip:'+item.id,kind:'zip',title:item.file.name,status:'UPLOADING',progress:control.progress,stage:'正在上传 ZIP',detail:control.message,fileSize:Number(item.file.size||0),queuePosition:null,localOnly:false,serverUrl:'/api/v19/projects/'+encodeURIComponent(project)+'/import/jobs/'+encodeURIComponent(item.id),browserTransfer:true,resumeRequired:false,pollOwner:'zip-import-runtime'});
                  if(selectedJobId===item.id)render();
                }
              },
              onPhase:phase=>{
                publishTransfer('processing',control,phase);
                // Scanning/label decisions never consume a browser transfer slot.
                control.state='post-upload';releaseSlot();refreshQueuedUploadPositions();
                control.progress=100;control.message=phase.message;
                if(isCurrentProject(project))window.UploadTaskCenterRuntime?.upsert?.({id:'zip:'+item.id,kind:'zip',title:item.file.name,status:'MERGING',progress:null,stage:phase.stage,detail:phase.message,fileSize:Number(item.file.size||0),queuePosition:null,localOnly:false,browserTransfer:false,resumeRequired:false,pollOwner:'zip-import-runtime'});
              },
            });
            // Multipart upload ID and the durable import job ID are distinct
            // identities. Completion must move all post-upload ownership to
            // the server-returned job ID; otherwise the job never starts and
            // the imported material completion cannot be observed.
            const jobId=String(response.id||'');
            if(!jobId)throw new Error('ZIP 合并完成但未返回正式导入任务 ID，请在任务中心核对，勿重复上传');
            publishTransfer('success',control,{jobId,response});
            const provisional={...response,id:jobId,file_name:response.file_name||item.file.name,status:response.status||'selecting',created_at:response.created_at||new Date().toISOString()};
            if(isCurrentProject(project)){
              if(jobId!==item.id){
                knownJobs.delete(item.id);
                jobs=jobs.filter(row=>String(row?.id||'')!==item.id);
                window.UploadTaskCenterRuntime?.rekey?.('zip:'+item.id,'zip:'+jobId);
              }
              knownJobs.set(jobId,provisional);
              if(presentation?.layer===reviewSource.layer&&uploadViews.get(reviewSource.layer)===reviewSource)presentation=null;
              autoReviewCandidates.set(jobId,reviewSource);
              foregroundImports.add(jobId);
              writeIntent(project,jobId,'deferred');
              if(selectedJobId===item.id)selectedJobId=jobId;
              await reconcile('upload').catch(()=>{});
            }
            batchFiles.delete(item.id);
            return response;
          }catch(error){
            if(control.state==='paused'||control.state==='cancelled')return null;
            publishTransfer('error',control,{error,message:String(error?.message||error)});
            if(item?.id&&isCurrentProject(project))window.UploadTaskCenterRuntime?.upsert?.({
              id:'zip:'+item.id,kind:'zip',title:item.file.name,status:'WAITING',progress:control.progress,
              stage:error?.zipCompletionUncertain?'等待服务器确认':'上传中断，等待续传',
              detail:String(error?.message||error),fileSize:Number(item.file.size||0),queuePosition:null,localOnly:false,serverUrl:'/api/v19/projects/'+encodeURIComponent(project)+'/import/jobs/'+encodeURIComponent(item.id),
              browserTransfer:false,resumeRequired:true,pollOwner:'',
            });
            else if(isCurrentProject(project))failLocalUpload(entry,`上传会话创建失败：${error?.message||error}`);
            throw error;
          }finally{
            const transferId=item?.id||entry.id;
            if(batchTransfers.get(transferId)===control)batchTransfers.delete(transferId);
            refreshQueuedUploadPositions();
            if(isCurrentProject(project))render();
            control.finish();
          }
      }),validEntries.length);
      const incomplete=entries.filter(entry=>['failed','active'].includes(entry.control.state)).length;
      if(incomplete&&isCurrentProject(project))notify?.('有 '+incomplete+' 个 ZIP 未完成，其他文件不受影响；请查看任务中心详情');
      if(isCurrentProject(project))await reconcile('batch-finished').catch(()=>{});
      return results.filter(x=>x.status==='fulfilled'&&x.value).at(-1)?.value||null;
    }catch(error){
      for(const entry of entries)if(['queued','preparing'].includes(entry.control.state))failLocalUpload(entry,`批次处理失败：${error?.message||error}`);
      if(isCurrentProject(project)){notify?.('ZIP 批次处理失败：'+String(error?.message||error));await reconcile('batch-interrupted').catch(()=>{})}
      return null;
    }finally{if(input&&'value' in input)input.value=''}
  }
  function forgetTerminal(ids=null){
    const project=pid(),removed=new Set();
    const allowed=ids===null?null:new Set(ids.map(String));
    for(const job of jobs){
      if(TERMINAL_ZIP_STATUSES.has(status(job))&&(!allowed||allowed.has(String(job.id))))removed.add(String(job.id||''));
    }
    for(const [id,job] of [...knownJobs.entries()]){
      if(TERMINAL_ZIP_STATUSES.has(status(job))&&(!allowed||allowed.has(String(id)))){removed.add(String(id));knownJobs.delete(id)}
    }
    for(const id of removed){
      eligibleSince.delete(id);started.delete(id);completionEffects.delete(id);foregroundImports.delete(id);batchFiles.delete(id);batchTransfers.delete(id);writeIntent(project,id,'');
    }
    jobs=jobs.filter(job=>!removed.has(String(job?.id||'')));
    current=pickZipJob(jobs);
    const state=getState()||{},activeImport=String(state.import411?.jobId||'');
    if(activeImport&&removed.has(activeImport))state.import411=null;
    render();arm();
    return removed.size;
  }

  async function openTask(taskId){
    const id=String(taskId||'').replace(/^zip:/,'');
    let job=jobs.find(row=>String(row?.id||'')===id)||knownJobs.get(id);
    if(!job){await reconcile('open-task');job=jobs.find(row=>String(row?.id||'')===id)||knownJobs.get(id)}
    if(!job){notify?.('该导入任务已结束或不存在');return null}
    const project=pid();
    if(!batchTransfers.get(id)?.localOnly){
      try{const detail=await getZipJob(project,id,{fetchImpl});if(!isCurrentProject(project))return null;if(detail?.id){job={...job,...detail};knownJobs.set(id,job);jobs=mergeJobs(jobs.filter(row=>String(row.id)!==id))}}
      catch(error){if(!isCurrentProject(project))return null;job=markUnknown(job,error);knownJobs.set(id,job);jobs=mergeJobs(jobs.filter(row=>String(row.id)!==id));publishTaskCenterJob(project,job)}
    }
    const source=autoReviewCandidates.get(id);
    if(source?.projectId===project&&topModal()===source.layer&&!source.closed){const layer=source.layer;source.onHandoff?.();closeOwnedLayer(layer,'handoff');uploadViews.delete(layer);source.layer=null;source.onHandoff=null}
    selectedJobId=id;current=job;patchState(job);open();arm();return job;
  }

  const reportUploadBatchError=error=>{notify?.(`ZIP 批次处理失败：${error?.message||error}`);return null};
  const runtime={registerUploadView,beforeModalClose,upload,uploadBatch,subscribeTransfers,resumeTransfer,getProjectId:pid,previewOriginalLabels,confirmOriginalLabels,cancelOriginalLabels,matchExistingLabels,toggleManualLabels,setAdvancedExpanded,pauseUpload,cancelUpload,cancelQueuedUpload,stopImport,cancelJob,cancelAllActive,promptResume,resumeFromFile,reconcile,open,openTask,confirmLabels,forgetTerminal,showLabelSamples,useSourceLabel,setReviewSearch,setTargetSearch,setReviewPage,toggleLabelRow,setLabelMapping:setReviewLabelMapping,bulkMapLabels,snapshot:()=>({jobs:[...jobs],current,labelReviews,busy}),destroy(){destroyed=true;presentation=null;activeUploadView=null;uploadViews.clear();autoReviewCandidates.clear();shownReviews.clear();transferObservers.clear();clearPoll();document.getElementById('zipImportDurableDock')?.remove()}};
  window.ZipImportRuntime=runtime;
  window.doUploadZip426=input=>uploadBatch(input).catch(reportUploadBatchError);
  window.doImportData=()=>{const input=document.getElementById('importFile');if(!input?.files?.length){notify?.('请选择 ZIP 压缩包');return null}return uploadBatch(input).catch(reportUploadBatchError)};
  const initialProject=pid();
  reconcile('bootstrap').catch(()=>{});
  if(!initialProject&&window.__v53InitPromise){
    Promise.resolve(window.__v53InitPromise).then(()=>reconcile('bootstrap-ready')).catch(()=>{});
  }
  return runtime;
}
