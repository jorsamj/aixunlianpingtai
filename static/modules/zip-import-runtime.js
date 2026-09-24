export const ACTIVE_ZIP_STATUSES = new Set(['uploading','merging','validating','selecting','queued','waiting','running']);
export const IMPORT_QUEUE_ZIP_STATUSES = new Set(['selecting','queued','waiting','running']);
export const TERMINAL_ZIP_STATUSES = new Set(['done','failed','cancelled','canceled']);
export const LEGACY_START_GRACE_MS = 8000;

const status = job => String(job?.status || '').toLowerCase();
const time = value => Number.isFinite(Date.parse(value || '')) ? Date.parse(value) : 0;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const clamp = value => Math.max(0, Math.min(100, Number(value) || 0));
export const PLATFORM_LABEL_CODE_RE = /^[A-Za-z][A-Za-z0-9_-]*$/;

export function zipLabelChoice(externalClass, labels = []) {
  const source = String(externalClass?.name || '').trim();
  const rows = (Array.isArray(labels) ? labels : [])
    .map(row => typeof row === 'string' ? {code:row, status:'active'} : row)
    .filter(row => row?.code && String(row.status || 'active').toLowerCase() === 'active');
  const byCode = new Map(rows.map(row => [String(row.code), row]));
  const suggested = String(externalClass?.target_label_code || '').trim();
  if (suggested && byCode.has(suggested)) return {mode:'existing', code:suggested, source};
  if (source && byCode.has(source)) return {mode:'existing', code:source, source};
  if (source && PLATFORM_LABEL_CODE_RE.test(source)) return {mode:'create', code:source, source};
  return {mode:'unresolved', code:'', source};
}

export function orderZipJobs(jobs) {
  return [...(jobs || [])].sort((a,b) => time(a?.created_at)-time(b?.created_at) || String(a?.id||'').localeCompare(String(b?.id||'')));
}
export function activeZipJobs(jobs) { return orderZipJobs(jobs).filter(job => ACTIVE_ZIP_STATUSES.has(status(job))); }
export function zipQueueInfo(job,jobs) {
  const active=orderZipJobs(jobs).filter(row=>IMPORT_QUEUE_ZIP_STATUSES.has(status(row))), index=active.findIndex(x=>String(x?.id||'')===String(job?.id||''));
  return {index, position:index>=0?index+1:null, ahead:index>0?index:0, canStart:status(job)==='selecting'&&index===0, waits:status(job)==='selecting'&&index>0};
}
export function pickZipJob(jobs) {
  const active=activeZipJobs(jobs), running=active.find(x=>status(x)==='running');
  if(running) return running;
  if(active.length) return active[0];
  return orderZipJobs(jobs).filter(x=>TERMINAL_ZIP_STATUSES.has(status(x))).sort((a,b)=>time(b?.updated_at||b?.created_at)-time(a?.updated_at||a?.created_at))[0]||null;
}
export function backendZipProgress(job) {
  const n=Number(job?.progress); return Number.isFinite(n)?clamp(n):0;
}
export function overallZipProgress(job) {
  const s=status(job), backend=backendZipProgress(job), upload=clamp(job?.upload_progress);
  if(s==='uploading') return Math.round(upload*3.5)/10;
  if(s==='merging') return 36;
  if(s==='validating') return 37;
  if(['selecting','queued','waiting'].includes(s)) return 38;
  if(s==='running') return Math.round((3800+backend*61)/10)/10;
  if(s==='done') return 100;
  if(s==='failed') {
    if(upload>0&&upload<100) return Math.round(upload*3.5)/10;
    return backend>0 ? Math.round((3800+backend*61)/10)/10 : 38;
  }
  return backend;
}
export function zipView(job,jobs) {
  if(!job) return null;
  const s=status(job), q=zipQueueInfo(job,jobs), progress=overallZipProgress(job);
  if(s==='uploading') return {status:s,progress,stage:'正在上传 ZIP',message:job?.message||'正在分片上传，可断点续传。',queue:q};
  if(s==='merging') return {status:s,progress,stage:'正在合并 ZIP 分片',message:job?.message||'文件已上传，服务器正在合并分片。',queue:q};
  if(s==='validating') return {status:s,progress,stage:'正在校验 ZIP',message:job?.message||'服务器正在校验压缩包目录结构。',queue:q};
  if(s==='selecting'&&q.waits) return {status:s,progress,stage:'等待前序 ZIP 导入任务',message:`前面还有 ${q.ahead} 个导入任务；同一项目 ZIP 导入按后台顺序串行执行。`,queue:q};
  if(zipNeedsLabelConfirmation(job)) return {status:s,progress,stage:'等待确认标注',message:`检测到 ${job.external_classes.length} 个外部标签，请统一到平台标签后再入库。`,queue:q};
  if(s==='selecting') return {status:s,progress,stage:'等待启动后台导入',message:job?.message||'ZIP 已上传并完成校验，正在确认后台启动状态。',queue:q};
  if(s==='running') return {status:s,progress,stage:job?.stage||'后台导入中',message:job?.message||'后台正在处理 ZIP 数据。',queue:q};
  if(s==='done') return {status:s,progress:100,stage:'导入完成',message:job?.message||'ZIP 数据已完成导入。',queue:q};
  if(s==='failed') return {status:s,progress,stage:'导入失败',message:job?.error||job?.message||'ZIP 导入失败。',queue:q};
  return {status:s,progress,stage:job?.stage||'ZIP 导入',message:job?.message||'',queue:q};
}
export function zipNeedsLabelConfirmation(job) {
  return status(job)==='selecting'
    && Boolean(job?.label_confirmation_required)
    && Array.isArray(job?.external_classes)
    && job.external_classes.length>0;
}
export function zipStartDisposition(job,jobs,{intent='',eligibleForMs=0,graceMs=LEGACY_START_GRACE_MS}={}) {
  if(status(job)!=='selecting') return 'none';
  if(!zipQueueInfo(job,jobs).canStart) return 'wait';
  if(zipNeedsLabelConfirmation(job)) return 'confirm-labels';
  if(intent==='deferred') return 'start';
  if(['submitting','submitted','ambiguous'].includes(intent)) return 'observe';
  return Number(eligibleForMs)<Number(graceMs)?'confirm':'start-legacy-recovery';
}

async function json(response) {
  let body={}; try{body=await response.json()}catch(_){}
  if(!response.ok) throw new Error(String(body?.detail||body?.message||`HTTP ${response.status}`));
  return body;
}
export async function listZipJobs(projectId,{fetchImpl=globalThis.fetch}={}) {
  return (await json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/jobs`,{credentials:'same-origin'}))).items||[];
}
export async function getZipJob(projectId,jobId,{fetchImpl=globalThis.fetch}={}) {
  return json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/jobs/${encodeURIComponent(String(jobId))}`,{credentials:'same-origin'}));
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

async function createZipUploadSession(projectId,file,{fetchImpl=globalThis.fetch}={}) {
  const fingerprint=await zipFingerprint(file);
  return json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(String(projectId))}/datasets/default/import/uploads`,{
    method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({file_name:file.name,file_size:file.size,fingerprint,part_size:8*1024*1024}),
  }));
}

function uploadZipPartXHR(projectId,uploadId,part,file,{onTransfer=()=>{},xhrFactory=()=>new XMLHttpRequest()}={}) {
  return new Promise((resolve,reject)=>{
    const xhr=xhrFactory();
    xhr.open('PUT',`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/uploads/${encodeURIComponent(String(uploadId))}/parts/${part.index}`,true);
    xhr.setRequestHeader?.('Content-Type','application/octet-stream');
    xhr.upload.onprogress=e=>{if(e.lengthComputable)onTransfer({loaded:e.loaded,total:e.total,ratio:e.total?e.loaded/e.total:0})};
    xhr.onerror=()=>reject(new Error(`ZIP 分片 ${part.index+1} 网络连接中断`));
    xhr.onabort=()=>reject(new Error(`ZIP 分片 ${part.index+1} 已取消`));
    xhr.onload=()=>{let body={};try{body=JSON.parse(xhr.responseText||'{}')}catch(_){};if(xhr.status<200||xhr.status>=300)return reject(new Error(String(body?.detail||xhr.responseText||`HTTP ${xhr.status}`)));resolve(body)};
    xhr.send(file.slice(part.start,part.end));
  });
}

export async function uploadZipMultipartJob(projectId,file,{onTransfer=()=>{},onSession=()=>{},onPhase=()=>{},fetchImpl=globalThis.fetch,xhrFactory=()=>new XMLHttpRequest(),concurrency=4,retries=2}={}) {
  const session=await createZipUploadSession(projectId,file,{fetchImpl});
  const uploadId=String(session.upload_id||'');
  if(!uploadId)throw new Error('服务器未返回 ZIP 上传会话 ID');
  onSession(session);
  const plan=zipPartPlan(file.size,session.part_size,session.completed_parts);
  const pending=plan.filter(part=>!part.completed),inflight=new Map();
  let committed=plan.filter(part=>part.completed).reduce((sum,part)=>sum+part.size,0),cursor=0;
  const emit=()=>{const loaded=Math.min(file.size,committed+[...inflight.values()].reduce((sum,value)=>sum+value,0));onTransfer({loaded,total:file.size,ratio:file.size?loaded/file.size:0,completedParts:plan.length-pending.length+Math.min(cursor,pending.length),totalParts:plan.length})};
  emit();
  async function uploadOne(part){
    let attempt=0;
    while(true){
      try{
        const result=await uploadZipPartXHR(projectId,uploadId,part,file,{xhrFactory,onTransfer:p=>{inflight.set(part.index,Math.min(part.size,Number(p.loaded)||0));emit()}});
        inflight.delete(part.index);committed+=part.size;emit();return result;
      }catch(error){
        inflight.delete(part.index);emit();
        if(attempt>=retries)throw error;
        attempt+=1;await new Promise(resolve=>setTimeout(resolve,300*Math.pow(2,attempt-1)));
      }
    }
  }
  async function worker(){while(true){const index=cursor++;if(index>=pending.length)return;await uploadOne(pending[index])}}
  await Promise.all(Array.from({length:Math.max(1,Math.min(Number(concurrency)||1,4,pending.length||1))},()=>worker()));
  onPhase({stage:'正在合并与校验 ZIP',message:'所有分片上传完成，服务器正在合并并校验压缩包'});
  return json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/uploads/${encodeURIComponent(uploadId)}/complete`,{method:'POST',credentials:'same-origin'}));
}

export function isZipBootstrapReconcile(reason='') {
  return ['bootstrap', 'bootstrap-ready'].includes(String(reason || ''));
}

export function installZipImportRuntime({getState=()=>({}),projectId=()=>getState()?.project?.id,notify=m=>window.toast?.(m),fetchImpl=globalThis.fetch,pollMs=1000}={}) {
  if(typeof window==='undefined'||typeof document==='undefined') return null;
  let jobs=[],current=null,timer=null,busy=false,destroyed=false,uploading=null;
  const eligibleSince=new Map(),started=new Set(),knownJobs=new Map(),completionEffects=new Set();
  const pid=()=>String(projectId?.()||'');
  const intentKey=(p,id)=>`mc_zip_import_start_v1:${p}:${id}`;
  const readIntent=(p,id)=>{try{return localStorage.getItem(intentKey(p,id))||''}catch(_){return''}};
  const writeIntent=(p,id,v)=>{try{v?localStorage.setItem(intentKey(p,id),v):localStorage.removeItem(intentKey(p,id))}catch(_){}};
  const seconds=v=>Number.isFinite(Number(v))?`${Number(v).toFixed(1)} 秒`:'-';
  const bytes=v=>{const n=Math.max(0,Number(v)||0);return n>=1048576?`${(n/1048576).toFixed(1)} MB`:`${(n/1024).toFixed(1)} KB`};
  const mergeJobs=server=>{const byId=new Map((server||[]).map(job=>[String(job?.id||''),job]));for(const [id,job] of knownJobs){if(!byId.has(id))byId.set(id,job)}return orderZipJobs([...byId.values()].filter(job=>job?.id))};
  function labelItems(){
    const state=getState()||{},rows=Array.isArray(state.labels)?state.labels:[];
    const normalized=rows.map(row=>typeof row==='string'?{code:String(row),display_name:String(row),status:'active'}:row).filter(row=>row?.code&&String(row.status||'active').toLowerCase()==='active');
    const fromProject=(Array.isArray(state.project?.labels)?state.project.labels:[]).map(row=>typeof row==='string'?{code:String(row),display_name:String(row),status:'active'}:row).filter(row=>row?.code);
    const byCode=new Map();
    for(const row of [...normalized,...fromProject])if(!byCode.has(String(row.code)))byCode.set(String(row.code),row);
    return [...byCode.values()];
  }
  function labelMappingMarkup(job){
    if(!zipNeedsLabelConfirmation(job))return '';
    const labels=labelItems(),classes=job.external_classes||[];
    const options=(choice,source)=>{
      const rows=['<option value="">选择平台标签</option>'];
      for(const label of labels){const code=String(label.code);rows.push(`<option value="${esc(code)}" ${choice.mode==='existing'&&choice.code===code?'selected':''}>${esc(label.display_name||code)} · ${esc(code)}</option>`)}
      if(choice.mode==='create')rows.push(`<option value="__create__" selected>＋ 使用文件标签“${esc(source)}”并新增</option>`);
      return rows.join('');
    };
    const rows=classes.map(row=>{
      const choice=zipLabelChoice(row,labels),source=String(row.name||''),badge=choice.mode==='existing'?'<span class="pill ok">自动匹配</span>':choice.mode==='create'?'<span class="pill blue">将新增</span>':'<span class="pill warn">待选择</span>';
      return `<div class="storage61-mapping-row" data-zip-class="${esc(row.class_id)}" data-source-name="${esc(source)}"><span><b>${esc(source||`类别 ${row.class_id}`)}</b><small>${Number(row.image_count||0)} 张 · ${Number(row.box_count||0)} 框</small>${badge}</span><div class="row"><select class="select" data-zip-target>${options(choice,source)}</select><button type="button" class="btn mini" onclick="window.openInlineLabelCreate414?.('zip','${encodeURIComponent(String(row.class_id))}')">＋ 新建平台标签</button></div></div>`;
    }).join('');
    return `<div class="storage61-import-mapping zip-label-confirm" data-zip-label-mapping><div class="row between"><div><b>标注入库确认</b><div class="item-sub">英文编码与标签库完全一致时自动复用；不存在且文件标签是合法英文编码时，可直接新增后再入库。</div></div><span class="pill warn">${classes.length} 个外部标签</span></div>${rows}<div class="item-sub" data-zip-confirm-status>确认后会先完成必要的标签创建，再启动后台导入；不会把未确认的外部标签直接写入正式标注。</div><div class="row end"><button class="btn" onclick="setPage('标签管理')">管理标签</button><button class="btn primary" data-zip-confirm-button onclick="window.ZipImportRuntime?.confirmLabels('${esc(job.id)}')">确认标签并开始导入</button></div></div>`;
  }

  function dock(){let n=document.getElementById('zipImportDurableDock');if(!n){n=document.createElement('button');n.id='zipImportDurableDock';n.type='button';n.className='import411-dock hidden';n.onclick=()=>open();document.body.appendChild(n)}return n}
  function resultMarkup(job){const s=status(job),r=job?.report||{};if(s==='done'){const warns=(r.warnings||[]).map(x=>`<li>${esc(x)}</li>`).join('');return `<div class="alert ok"><b>导入完成</b>：${Number(r.imported_images||0)} 张图片，其中 ${Number(r.annotated_images||0)} 张带标注，${Number(r.boxes||0)} 个框。</div>${warns?`<ul class="zip410-warn">${warns}</ul>`:''}`}if(s==='failed')return `<div class="alert err"><b>导入失败</b>：${esc(job?.error||job?.message||'未知错误')}</div>`;return''}
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
    s.import411={...(same?previous:{}),active:ACTIVE_ZIP_STATUSES.has(v.status),jobId:String(job.id||''),fileName:job.file_name||previous.fileName||'ZIP 数据导入',fileSize:Number(job.uploaded_bytes||previous.fileSize||0),stage:v.stage,message:v.message,progress:v.progress,eta:job.eta_seconds??null,uploadSeconds:job.upload_seconds??previous.uploadSeconds??null,processSeconds:job.processing_seconds??job.scan_seconds??previous.processSeconds??null,serverStatus:v.status,queuePosition:v.queue.position,resultHtml:nextResult};
  }
  function body(job){const v=zipView(job,jobs),active=activeZipJobs(jobs),queue=v.queue.waits?`队列第 ${v.queue.position} 位 · 前面 ${v.queue.ahead} 个任务`:(active.length>1?`当前 ${active.length} 个活动 ZIP 导入任务`:'后台任务状态以服务器为准');const stateResult=String((getState()||{}).import411?.resultHtml||resultMarkup(job));return `<div class="zip411" data-zip-runtime="1"><section class="zip411-head"><div><b>${esc(job?.file_name||(getState()||{}).import411?.fileName||'ZIP 数据导入')}</b><span>${bytes(job?.uploaded_bytes||(getState()||{}).import411?.fileSize||0)}</span></div><button class="btn" onclick="closeModal()">关闭窗口</button></section><div class="zip411-main"><div class="zip411-progress"><div><span id="zipDurableStage">${esc(v.stage)}</span><b id="zipDurablePct">${Math.round(v.progress)}%</b></div><i><em id="zipDurableBar" data-progress="${Number(v.progress).toFixed(2)}" style="transform:scaleX(${(Number(v.progress)/100).toFixed(4)})"></em></i><p id="zipDurableMsg">${esc(v.message)}</p></div><div id="zipDurableQueue" class="alert ${v.queue.waits?'warn':'ok'}">${esc(queue)}</div><div class="zip411-times"><div><span>上传时间</span><b>${seconds(job?.upload_seconds)}</b></div><div><span>ZIP扫描</span><b>${seconds(job?.scan_seconds)}</b></div><div><span>后台处理</span><b>${seconds(job?.processing_seconds)}</b></div></div><div id="zip411Result">${stateResult}</div>${labelMappingMarkup(job)}</div></div>`}
  function uploadBody(){return `<div class="zip411" data-zip-runtime="1"><div class="zip411-main"><div class="zip411-progress"><div><span>正在上传 ZIP</span><b id="zipDurableUploadPct">${Math.round(uploading?.progress||0)}%</b></div><i><em id="zipDurableUploadBar" data-progress="${Number(uploading?.progress||0).toFixed(2)}" style="transform:scaleX(${(Number(uploading?.progress||0)/100).toFixed(4)})"></em></i><p id="zipDurableUploadMsg">${esc(uploading?.message||'准备上传')}</p></div><div class="alert warn">这里显示整条 ZIP 导入流程进度；网络上传完成后还会继续合并、校验和后台导入。</div></div></div>`}
  function replaceOpenRuntime(html){
    const currentRoot=document.querySelector('.zip411[data-zip-runtime="1"]');
    if(!currentRoot)return false;
    const shell=document.createElement('div');shell.innerHTML=html;const next=shell.firstElementChild;
    if(next){currentRoot.replaceWith(next);return true}
    return false;
  }
  function open(){
    const html=uploading?uploadBody():(current?body(current):'');
    if(!html)return false;
    if(replaceOpenRuntime(html))return true;
    window.modal?.('ZIP 数据导入',html,true);return true;
  }
  function updateOpenModal(job,active){
    if(!job)return;const v=zipView(job,jobs),stage=document.getElementById('zipDurableStage'),pct=document.getElementById('zipDurablePct'),bar=document.getElementById('zipDurableBar'),msg=document.getElementById('zipDurableMsg'),q=document.getElementById('zipDurableQueue'),result=document.getElementById('zip411Result');
    if(stage)stage.textContent=v.stage;if(pct)pct.textContent=`${Math.round(v.progress)}%`;setZipProgressBar(bar,v.progress);if(msg)msg.textContent=v.message;
    if(q)q.textContent=v.queue.waits?`队列第 ${v.queue.position} 位 · 前面 ${v.queue.ahead} 个任务`:(active.length>1?`当前 ${active.length} 个活动 ZIP 导入任务`:'后台任务状态以服务器为准');
    if(result)result.innerHTML=String((getState()||{}).import411?.resultHtml||resultMarkup(job));
  }
  function render(){
    const d=dock(),active=activeZipJobs(jobs);
    if(window.UploadTaskCenterRuntime)d.classList.add('hidden');
    if(uploading){if(!window.UploadTaskCenterRuntime)d.classList.remove('hidden');d.innerHTML=`<span><b>正在上传 ZIP</b><small>${Math.round(uploading.progress)}% · ${esc(uploading.message)}</small></span><strong>展开</strong>`;const pct=document.getElementById('zipDurableUploadPct'),bar=document.getElementById('zipDurableUploadBar'),msg=document.getElementById('zipDurableUploadMsg');if(pct)pct.textContent=`${Math.round(uploading.progress)}%`;setZipProgressBar(bar,uploading.progress);if(msg)msg.textContent=uploading.message;return}
    current=pickZipJob(jobs);
    if(!active.length)d.classList.add('hidden');else{const v=zipView(current,jobs);if(!window.UploadTaskCenterRuntime)d.classList.remove('hidden');d.innerHTML=`<span><b>${esc(v.stage)}</b><small>${Math.round(v.progress)}% · ${active.length} 个活动任务</small></span><strong>展开</strong>`}
    updateOpenModal(current,active);
  }
  function clearPoll(){if(window.PollRegistryRuntime?.clear)window.PollRegistryRuntime.clear('zip-import-runtime');else if(timer)clearTimeout(timer);timer=null}
  function arm(){clearPoll();if(destroyed||!activeZipJobs(jobs).length)return;const callback=()=>reconcile('poll').catch(()=>{});if(window.PollRegistryRuntime?.startTimeout){timer=window.PollRegistryRuntime.startTimeout('zip-import-runtime',[String((getState()||{}).page||'数据集')],callback,pollMs)}else timer=setTimeout(callback,pollMs)}
  async function refreshKnown(project){
    const ids=[...knownJobs.keys()];
    for(const id of ids){
      const intent=readIntent(project,id);if(!['submitted','ambiguous'].includes(intent))continue;
      try{const detail=await getZipJob(project,id,{fetchImpl});if(detail?.id)knownJobs.set(id,{...knownJobs.get(id),...detail})}catch(_){}
    }
  }
  async function createPlatformLabel(code,displayName=''){
    const project=pid(),labelCode=String(code||'').trim();
    if(!PLATFORM_LABEL_CODE_RE.test(labelCode))throw new Error(`文件标签“${labelCode}”不能直接作为平台英文标签，请手动新建一个合法英文标签后映射`);
    try{
      await json(await fetchImpl(`/api/projects/${encodeURIComponent(project)}/labels`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({label:labelCode,display_name:String(displayName||labelCode)})}));
    }catch(error){
      await window.refreshLabels414?.(false);
      if(!(getState()?.labels||[]).some(row=>String(row?.code||row)===labelCode))throw error;
      return labelCode;
    }
    await window.refreshLabels414?.(false);
    return labelCode;
  }
  async function confirmLabels(jobId){
    const project=pid(),id=String(jobId||''),job=jobs.find(row=>String(row?.id||'')===id)||knownJobs.get(id);
    if(!project||!job||!zipNeedsLabelConfirmation(job))return null;
    const rows=[...document.querySelectorAll('.zip-label-confirm [data-zip-class]')],button=document.querySelector('.zip-label-confirm [data-zip-confirm-button]'),statusNode=document.querySelector('.zip-label-confirm [data-zip-confirm-status]');
    if(!rows.length)throw new Error('标签确认界面已失效，请重新打开该导入任务');
    const label_mapping={},existing=new Set(labelItems().map(row=>String(row.code)));
    if(button){button.disabled=true;button.textContent='正在确认…'}
    rows.forEach(row=>{const select=row.querySelector('[data-zip-target]');if(select)select.disabled=true});
    try{
      for(const row of rows){
        const externalId=String(row.getAttribute('data-zip-class')||''),sourceName=String(row.getAttribute('data-source-name')||'').trim();
        let code=String(row.querySelector('[data-zip-target]')?.value||'').trim();
        if(!externalId||!code)throw new Error('请为每个外部标签选择平台标签');
        if(code==='__create__'){
          if(!PLATFORM_LABEL_CODE_RE.test(sourceName))throw new Error(`文件标签“${sourceName||externalId}”不是合法英文编码，请点击“新建平台标签”后再确认`);
          if(statusNode)statusNode.textContent=`正在创建平台标签 ${sourceName}…`;
          if(!existing.has(sourceName)){await createPlatformLabel(sourceName,sourceName);existing.add(sourceName)}
          code=sourceName;
        }
        if(!existing.has(code)&&!(getState()?.labels||[]).some(item=>String(item?.code||item)===code))throw new Error(`平台标签 ${code} 不存在，请重新选择`);
        label_mapping[externalId]=code;
      }
      if(statusNode)statusNode.textContent='标签已确认，正在启动后台导入…';
      started.add(id);writeIntent(project,id,'submitting');
      const response=await startZipJob(project,id,{fetchImpl,confirmation:{label_mapping}});
      knownJobs.set(id,{...job,...response});writeIntent(project,id,'submitted');
      await reconcile('label-confirmation');open();return response;
    }catch(error){
      started.delete(id);writeIntent(project,id,'');
      if(button){button.disabled=false;button.textContent='确认标签并开始导入'}
      rows.forEach(row=>{const select=row.querySelector('[data-zip-target]');if(select)select.disabled=false});
      if(statusNode)statusNode.textContent=String(error?.message||error);
      notify?.(error?.message||error);throw error;
    }
  }
  async function maybeStart(project){const next=orderZipJobs(jobs).find(row=>status(row)==='selecting'&&zipQueueInfo(row,jobs).canStart);if(!next)return;const id=String(next.id||'');if(started.has(id))return;const now=Date.now();if(!eligibleSince.has(id))eligibleSince.set(id,now);const action=zipStartDisposition(next,jobs,{intent:readIntent(project,id),eligibleForMs:now-eligibleSince.get(id)});if(!['start','start-legacy-recovery'].includes(action))return;started.add(id);writeIntent(project,id,'submitting');try{await startZipJob(project,id,{fetchImpl});writeIntent(project,id,'submitted')}catch(e){started.delete(id);writeIntent(project,id,'ambiguous');throw e}}
  async function applyCompletion(job,reason){
    if(!job||status(job)!=='done'||reason==='bootstrap')return;const id=String(job.id||'');if(completionEffects.has(id))return;completionEffects.add(id);
    window.completeZipImportReview412?.(id);window.invalidateQuality411?.();await window.refreshLabels414?.(false);if((getState()||{}).page==='数据集')await window.reloadMaterialPage61?.();notify?.(`后台导入完成：${Number(job?.report?.imported_images||0)} 张图片`);
  }
  function publishTaskCenterJob(project,job){
    const v=zipView(job,jobs),s=status(job),localUpload=Boolean(uploading?.uploadId)&&String(uploading.uploadId)===String(job.id||'');
    const task={id:`zip:${job.id}`,kind:'zip',title:job.file_name||'ZIP 数据导入',status:String(job.status||'').toUpperCase(),progress:v.progress,stage:v.stage,detail:v.message,serverUrl:`/api/v19/projects/${encodeURIComponent(project)}/import/jobs/${encodeURIComponent(String(job.id))}`};
    if(s==='uploading'&&localUpload){task.browserTransfer=true;task.resumeRequired=false}
    else if(s!=='uploading'){task.browserTransfer=false;task.resumeRequired=false}
    window.UploadTaskCenterRuntime?.upsert?.(task);
  }
  async function reconcile(reason='manual'){
    if(busy||destroyed)return current;const project=pid();if(!project)return null;busy=true;
    try{
      let server=await listZipJobs(project,{fetchImpl});jobs=mergeJobs(server);for(const job of jobs)publishTaskCenterJob(project,job);await maybeStart(project);await refreshKnown(project);if(!isZipBootstrapReconcile(reason))server=await listZipJobs(project,{fetchImpl});jobs=mergeJobs(server);current=pickZipJob(jobs);
      if(current){patchState(current);if(TERMINAL_ZIP_STATUSES.has(status(current))){writeIntent(project,current.id,'');eligibleSince.delete(String(current.id||''))}}
      render();await applyCompletion(current,reason);return current;
    }finally{busy=false;arm()}
  }
  async function upload(input){
    const file=input?.files?.[0];if(!file)return null;if(!/\.zip$/i.test(file.name||'')){notify?.('请选择 ZIP 压缩包');input.value='';return null}const project=pid();if(!project){notify?.('当前项目未加载，请刷新后重试');return null}
    let multipartTaskId='';uploading={progress:0,message:'准备上传',uploadId:''};window.closeModal?.();open();render();
    try{
      const response=await uploadZipMultipartJob(project,file,{fetchImpl,onSession:session=>{multipartTaskId=String(session.upload_id||'');uploading={...uploading,uploadId:multipartTaskId};window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${session.upload_id}`,kind:'zip',title:file.name,status:'UPLOADING',progress:overallZipProgress({status:'uploading',upload_progress:Number(session.upload_progress||0)}),stage:'正在上传 ZIP',detail:`已完成 ${(session.completed_parts||[]).length}/${session.total_parts||0} 个分片`,serverUrl:`/api/v19/projects/${encodeURIComponent(project)}/import/jobs/${encodeURIComponent(String(session.upload_id))}`,browserTransfer:true,resumeRequired:false})},onTransfer:e=>{const networkPercent=Math.round(e.ratio*1000)/10;uploading={...uploading,progress:Math.round(e.ratio*350)/10,message:`网络上传 ${networkPercent}% · ${bytes(e.loaded)} / ${bytes(e.total)}`};window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${multipartTaskId}`,kind:'zip',title:file.name,status:'UPLOADING',progress:uploading.progress,stage:'正在上传 ZIP',detail:uploading.message,browserTransfer:true,resumeRequired:false});render()},onPhase:phase=>{uploading={...uploading,progress:36,message:phase.message};window.UploadTaskCenterRuntime?.upsert?.({id:`zip:${multipartTaskId}`,kind:'zip',title:file.name,status:'MERGING',progress:36,stage:phase.stage,detail:phase.message,browserTransfer:false,resumeRequired:false});render()}});uploading=null;
      const provisional={...response,id:String(response.id),status:response.status||'selecting',stage:response.stage||'上传与校验完成',message:response.message||'上传与ZIP校验完成，等待开始后台导入',progress:Number(response.progress||0),file_name:response.file_name||file.name,uploaded_bytes:Number(response.uploaded_bytes||file.size||0),created_at:response.created_at||new Date().toISOString()};knownJobs.set(String(provisional.id),provisional);writeIntent(project,provisional.id,'deferred');
      await reconcile('upload');open();return response;
    }catch(e){uploading=null;window.modal?.('ZIP 数据导入',`<div class="alert err">${esc(e.message||e)}</div>`,true);notify?.(e.message||e);throw e}finally{input.value=''}
  }

  function forgetTerminal(){
    const project=pid(),removed=new Set();
    for(const job of jobs){
      if(TERMINAL_ZIP_STATUSES.has(status(job)))removed.add(String(job.id||''));
    }
    for(const [id,job] of [...knownJobs.entries()]){
      if(TERMINAL_ZIP_STATUSES.has(status(job))){removed.add(String(id));knownJobs.delete(id)}
    }
    for(const id of removed){
      eligibleSince.delete(id);started.delete(id);completionEffects.delete(id);writeIntent(project,id,'');
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
    current=job;patchState(job);open();return job;
  }

  const runtime={upload,reconcile,open,openTask,confirmLabels,forgetTerminal,snapshot:()=>({jobs:[...jobs],current}),destroy(){destroyed=true;clearPoll();document.getElementById('zipImportDurableDock')?.remove()}};
  window.ZipImportRuntime=runtime;
  window.doUploadZip426=input=>upload(input).catch(()=>{});
  window.doImportData=()=>{const input=document.getElementById('importFile');if(!input?.files?.length){notify?.('请选择 ZIP 压缩包');return null}return upload(input).catch(()=>null)};
  const initialProject=pid();
  reconcile('bootstrap').catch(()=>{});
  if(!initialProject&&window.__v53InitPromise){
    Promise.resolve(window.__v53InitPromise).then(()=>reconcile('bootstrap-ready')).catch(()=>{});
  }
  return runtime;
}
