export const ACTIVE_ZIP_STATUSES = new Set(['selecting','queued','waiting','running']);
export const TERMINAL_ZIP_STATUSES = new Set(['done','failed','cancelled','canceled']);
export const LEGACY_START_GRACE_MS = 8000;

const status = job => String(job?.status || '').toLowerCase();
const time = value => Number.isFinite(Date.parse(value || '')) ? Date.parse(value) : 0;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

export function orderZipJobs(jobs) {
  return [...(jobs || [])].sort((a,b) => time(a?.created_at)-time(b?.created_at) || String(a?.id||'').localeCompare(String(b?.id||'')));
}
export function activeZipJobs(jobs) { return orderZipJobs(jobs).filter(job => ACTIVE_ZIP_STATUSES.has(status(job))); }
export function zipQueueInfo(job,jobs) {
  const active=activeZipJobs(jobs), index=active.findIndex(x=>String(x?.id||'')===String(job?.id||''));
  return {index, position:index>=0?index+1:null, ahead:index>0?index:0, canStart:status(job)==='selecting'&&index===0, waits:status(job)==='selecting'&&index>0};
}
export function pickZipJob(jobs) {
  const active=activeZipJobs(jobs), running=active.find(x=>status(x)==='running');
  if(running) return running;
  if(active.length) return active[0];
  return orderZipJobs(jobs).filter(x=>TERMINAL_ZIP_STATUSES.has(status(x))).sort((a,b)=>time(b?.updated_at||b?.created_at)-time(a?.updated_at||a?.created_at))[0]||null;
}
export function backendZipProgress(job) {
  const n=Number(job?.progress); return Number.isFinite(n)?Math.max(0,Math.min(100,n)):0;
}
export function zipView(job,jobs) {
  if(!job) return null;
  const s=status(job), q=zipQueueInfo(job,jobs), progress=backendZipProgress(job);
  if(s==='selecting'&&q.waits) return {status:s,progress,stage:'等待前序 ZIP 导入任务',message:`前面还有 ${q.ahead} 个导入任务；同一项目 ZIP 导入按后台顺序串行执行。`,queue:q};
  if(s==='selecting') return {status:s,progress,stage:'等待启动后台导入',message:job?.message||'ZIP 已上传并完成校验，正在确认后台启动状态。',queue:q};
  if(s==='running') return {status:s,progress,stage:job?.stage||'后台导入中',message:job?.message||'后台正在处理 ZIP 数据。',queue:q};
  if(s==='done') return {status:s,progress:100,stage:'导入完成',message:job?.message||'ZIP 数据已完成导入。',queue:q};
  if(s==='failed') return {status:s,progress,stage:'导入失败',message:job?.error||job?.message||'ZIP 导入失败。',queue:q};
  return {status:s,progress,stage:job?.stage||'ZIP 导入',message:job?.message||'',queue:q};
}
export function zipStartDisposition(job,jobs,{intent='',eligibleForMs=0,graceMs=LEGACY_START_GRACE_MS}={}) {
  if(status(job)!=='selecting') return 'none';
  if(!zipQueueInfo(job,jobs).canStart) return 'wait';
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
export async function startZipJob(projectId,jobId,{fetchImpl=globalThis.fetch}={}) {
  return json(await fetchImpl(`/api/v19/projects/${encodeURIComponent(String(projectId))}/import/jobs/${encodeURIComponent(String(jobId))}/start`,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json'},body:JSON.stringify({selected_paths:[]})}));
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

export function installZipImportRuntime({getState=()=>({}),projectId=()=>getState()?.project?.id,notify=m=>window.toast?.(m),fetchImpl=globalThis.fetch,pollMs=1000}={}) {
  if(typeof window==='undefined'||typeof document==='undefined') return null;
  let jobs=[],current=null,timer=null,busy=false,destroyed=false,uploading=null;
  const eligibleSince=new Map(),started=new Set();
  const pid=()=>String(projectId?.()||'');
  const intentKey=(p,id)=>`mc_zip_import_start_v1:${p}:${id}`;
  const readIntent=(p,id)=>{try{return localStorage.getItem(intentKey(p,id))||''}catch(_){return''}};
  const writeIntent=(p,id,v)=>{try{v?localStorage.setItem(intentKey(p,id),v):localStorage.removeItem(intentKey(p,id))}catch(_){}};
  const seconds=v=>Number.isFinite(Number(v))?`${Number(v).toFixed(1)} 秒`:'-';
  const bytes=v=>{const n=Math.max(0,Number(v)||0);return n>=1048576?`${(n/1048576).toFixed(1)} MB`:`${(n/1024).toFixed(1)} KB`};

  function dock(){let n=document.getElementById('zipImportDurableDock');if(!n){n=document.createElement('button');n.id='zipImportDurableDock';n.type='button';n.className='import411-dock hidden';n.onclick=()=>open();document.body.appendChild(n)}return n}
  function patchState(job){if(!job)return;const v=zipView(job,jobs),s=getState()||{};s.import411={...(s.import411||{}),active:ACTIVE_ZIP_STATUSES.has(v.status),jobId:String(job.id||''),fileName:job.file_name||'ZIP 数据导入',fileSize:Number(job.uploaded_bytes||0),stage:v.stage,message:v.message,progress:v.progress,eta:job.eta_seconds??null,uploadSeconds:job.upload_seconds??null,processSeconds:job.processing_seconds??job.scan_seconds??null,serverStatus:v.status,queuePosition:v.queue.position}}
  function result(job){const s=status(job),r=job?.report||{};if(s==='done')return `<div class="alert ok"><b>导入完成</b>：${Number(r.imported_images||0)} 张图片，其中 ${Number(r.annotated_images||0)} 张带标注，${Number(r.boxes||0)} 个框。</div>`;if(s==='failed')return `<div class="alert err"><b>导入失败</b>：${esc(job?.error||job?.message||'未知错误')}</div>`;return''}
  function body(job){const v=zipView(job,jobs),active=activeZipJobs(jobs),queue=v.queue.waits?`队列第 ${v.queue.position} 位 · 前面 ${v.queue.ahead} 个任务`:(active.length>1?`当前 ${active.length} 个活动 ZIP 导入任务`:'后台任务状态以服务器为准');return `<div class="zip411"><section class="zip411-head"><div><b>${esc(job?.file_name||'ZIP 数据导入')}</b><span>${bytes(job?.uploaded_bytes||0)}</span></div><button class="btn" onclick="closeModal()">关闭窗口</button></section><div class="zip411-main"><div class="zip411-progress"><div><span id="zipDurableStage">${esc(v.stage)}</span><b id="zipDurablePct">${Math.round(v.progress)}%</b></div><i><em id="zipDurableBar" style="width:${v.progress}%"></em></i><p id="zipDurableMsg">${esc(v.message)}</p></div><div id="zipDurableQueue" class="alert ${v.queue.waits?'warn':'ok'}">${esc(queue)}</div><div class="zip411-times"><div><span>上传时间</span><b>${seconds(job?.upload_seconds)}</b></div><div><span>ZIP扫描</span><b>${seconds(job?.scan_seconds)}</b></div><div><span>后台处理</span><b>${seconds(job?.processing_seconds)}</b></div></div>${result(job)}</div></div>`}
  function uploadBody(){return `<div class="zip411"><div class="zip411-main"><div class="zip411-progress"><div><span>正在上传 ZIP</span><b id="zipDurableUploadPct">${Math.round(uploading?.progress||0)}%</b></div><i><em id="zipDurableUploadBar" style="width:${uploading?.progress||0}%"></em></i><p id="zipDurableUploadMsg">${esc(uploading?.message||'准备上传')}</p></div><div class="alert warn">服务器返回任务 ID 后，任务进入可刷新恢复的后台阶段。</div></div></div>`}
  function open(){if(uploading)return window.modal?.('ZIP 数据导入',uploadBody(),true);if(current)window.modal?.('ZIP 数据导入',body(current),true)}
  function render(){
    const d=dock(),active=activeZipJobs(jobs);
    if(uploading){
      d.classList.remove('hidden');d.innerHTML=`<span><b>正在上传 ZIP</b><small>${Math.round(uploading.progress)}% · ${esc(uploading.message)}</small></span><strong>展开</strong>`;
      const pct=document.getElementById('zipDurableUploadPct'),bar=document.getElementById('zipDurableUploadBar'),msg=document.getElementById('zipDurableUploadMsg');
      if(pct)pct.textContent=`${Math.round(uploading.progress)}%`;if(bar)bar.style.width=`${uploading.progress}%`;if(msg)msg.textContent=uploading.message;return;
    }
    if(!active.length){d.classList.add('hidden');return}
    current=pickZipJob(jobs);const v=zipView(current,jobs);d.classList.remove('hidden');d.innerHTML=`<span><b>${esc(v.stage)}</b><small>${Math.round(v.progress)}% · ${active.length} 个活动任务</small></span><strong>展开</strong>`;
    const stage=document.getElementById('zipDurableStage'),pct=document.getElementById('zipDurablePct'),bar=document.getElementById('zipDurableBar'),msg=document.getElementById('zipDurableMsg'),q=document.getElementById('zipDurableQueue');
    if(stage)stage.textContent=v.stage;if(pct)pct.textContent=`${Math.round(v.progress)}%`;if(bar)bar.style.width=`${v.progress}%`;if(msg)msg.textContent=v.message;
    if(q)q.textContent=v.queue.waits?`队列第 ${v.queue.position} 位 · 前面 ${v.queue.ahead} 个任务`:(active.length>1?`当前 ${active.length} 个活动 ZIP 导入任务`:'后台任务状态以服务器为准');
  }
  function clearPoll(){if(window.PollRegistryRuntime?.clear)window.PollRegistryRuntime.clear('zip-import-runtime');else if(timer)clearTimeout(timer);timer=null}
  function arm(){clearPoll();if(destroyed||!activeZipJobs(jobs).length)return;const callback=()=>reconcile('poll').catch(()=>{});if(window.PollRegistryRuntime?.startTimeout){timer=window.PollRegistryRuntime.startTimeout('zip-import-runtime',[String((getState()||{}).page||'数据集')],callback,pollMs)}else timer=setTimeout(callback,pollMs)}

  async function maybeStart(project){const active=activeZipJobs(jobs),next=active[0];if(!next||status(next)!=='selecting')return;const id=String(next.id||'');if(started.has(id))return;const now=Date.now();if(!eligibleSince.has(id))eligibleSince.set(id,now);const action=zipStartDisposition(next,jobs,{intent:readIntent(project,id),eligibleForMs:now-eligibleSince.get(id)});if(!['start','start-legacy-recovery'].includes(action))return;started.add(id);writeIntent(project,id,'submitting');try{await startZipJob(project,id,{fetchImpl});writeIntent(project,id,'submitted')}catch(e){started.delete(id);writeIntent(project,id,'ambiguous');throw e}}
  async function reconcile(reason='manual'){if(busy||destroyed)return current;const project=pid();if(!project)return null;busy=true;try{jobs=await listZipJobs(project,{fetchImpl});await maybeStart(project);if(reason!=='bootstrap')jobs=await listZipJobs(project,{fetchImpl});current=pickZipJob(jobs);if(current){patchState(current);if(TERMINAL_ZIP_STATUSES.has(status(current))){writeIntent(project,current.id,'');eligibleSince.delete(String(current.id||''))}}render();if(status(current)==='done'&&reason!=='bootstrap'){window.completeZipImportReview412?.(current.id);if((getState()||{}).page==='数据集')await window.reloadMaterialPage61?.()}return current}finally{busy=false;arm()}}
  async function upload(input){const file=input?.files?.[0];if(!file)return null;if(!/\.zip$/i.test(file.name||'')){notify?.('请选择 ZIP 压缩包');input.value='';return null}const project=pid();if(!project){notify?.('当前项目未加载，请刷新后重试');return null}uploading={progress:0,message:'准备上传'};window.closeModal?.();open();render();try{const job=await uploadZipJob(project,file,{onTransfer:e=>{uploading={progress:Math.round(e.ratio*100),message:`${bytes(e.loaded)} / ${bytes(e.total)}`};render()}});uploading=null;writeIntent(project,job.id,'deferred');await reconcile('upload');open();return job}catch(e){uploading=null;window.modal?.('ZIP 数据导入',`<div class="alert err">${esc(e.message||e)}</div>`,true);notify?.(e.message||e);throw e}finally{input.value=''}}

  const originalReload=window.reloadMaterialPage61;
  if(typeof originalReload==='function'&&!originalReload.__zipImportDurableWrapped){const wrapped=async function(...args){const out=await originalReload.apply(this,args);reconcile('material-page').catch(()=>{});return out};wrapped.__zipImportDurableWrapped=true;window.reloadMaterialPage61=wrapped}
  const runtime={upload,reconcile,open,snapshot:()=>({jobs:[...jobs],current}),destroy(){destroyed=true;clearPoll();document.getElementById('zipImportDurableDock')?.remove()}};
  window.ZipImportRuntime=runtime;window.doUploadZip426=input=>upload(input).catch(()=>{});reconcile('bootstrap').then(value=>{if(!value&&!pid())setTimeout(()=>reconcile('bootstrap-retry').catch(()=>{}),500)}).catch(()=>{});return runtime;
}
