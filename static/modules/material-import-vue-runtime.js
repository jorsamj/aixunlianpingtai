// Presentation only. Upload/ZIP/confirmation/governance runtimes remain owners.
export function materialImportSafeText(value,maximum=600){
  return String(value??'').replace(/https?:\/\/\S+/g,'[地址已隐藏]')
    .replace(/(token|password|secret|api[_-]?key|authorization)["']?\s*[:=]\s*(?:"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;}]+)/gi,'$1=[已隐藏]')
    .replace(/\\+[^\s,;"']+|[A-Za-z]:[\\/][^\s,;"']*|(?:\/[\w.-]+){2,}/g,'[路径已隐藏]').slice(0,maximum);
}
export function materialImportTaskView(row={}){
  return {id:String(row.id||''),kind:String(row.kind||''),title:materialImportSafeText(row.title),
    status:materialImportSafeText(row.status),stage:materialImportSafeText(row.stage),detail:materialImportSafeText(row.detail),
    progress:row.progressKnown===false||row.progress===null||typeof row.progress!=='number'||!Number.isFinite(row.progress)?null:Math.max(0,Math.min(100,row.progress)),
    createdAt:materialImportSafeText(row.createdAt),updatedAt:materialImportSafeText(row.updatedAt),
    localOnly:row.localOnly===true,browserTransfer:row.browserTransfer===true,resumeRequired:row.resumeRequired===true,
    verificationReason:materialImportSafeText(row.verificationReason),queuePosition:Number.isInteger(row.queuePosition)?row.queuePosition:null};
}
export function installMaterialImportVueRuntime({enabled=false,getState,projectId,load,document=globalThis.document,window=globalThis.window}={}){
  let view=null,generation=0;
  const pid=()=>String(projectId?.()||getState?.()?.project?.id||'');
  const active=owner=>view===owner&&!owner.controller.signal.aborted&&pid()===owner.project&&owner.host.isConnected!==false&&String(getState?.()?.page||'')===owner.page;
  function snapshot(owner=view){
    if(!owner)return null;
    const current=active(owner),rows=current?(window.UploadTaskCenterRuntime?.list?.()||[]):[],session=current?window.UploadConfirmationRuntime?.getSession?.():null;
    return {projectId:owner.project,tasks:rows.slice(0,100).map(materialImportTaskView),total:rows.length,truncated:rows.length>100,
      confirmationAvailable:String(session?.projectId||'')===owner.project&&(session?.batchIds?.length>0||session?.requestIds?.length>0),
      busy:owner.busy,error:current?owner.error:'页面或项目上下文已变化，请从当前项目重新打开。',updatedAt:owner.updatedAt,
      capabilities:{images:current&&typeof window.ImageUppyView?.open==='function',zip:current&&typeof window.openUppyZipUpload==='function',confirmation:current&&typeof window.UploadConfirmationRuntime?.restoreForProject==='function',governance:current&&typeof window.openMaterialIntegrityAudit47==='function'}};
  }
  function notify(){const owner=view;if(!owner||!active(owner))return false;owner.updatedAt=new Date().toISOString();const value=snapshot(owner);for(const listener of owner.listeners)listener(value);return true;}
  function leave(){generation++;const owner=view;view=null;if(!owner)return;owner.controller.abort();owner.stopTransfers?.();owner.stopCenter?.();owner.observer?.disconnect();owner.listeners.clear();owner.dispose?.();}
  async function render(host){
    if(!enabled||!host||!pid()||typeof load!=='function')return false;
    leave();const ticket=generation,owner={host,project:pid(),page:String(getState?.()?.page||''),controller:new AbortController(),listeners:new Set(),dispose:null,busy:false,error:'',updatedAt:''};view=owner;
    const guarded=fn=>async(...args)=>{if(!active(owner))return false;try{owner.error='';return await fn(...args)}catch(error){if(active(owner)){owner.error=materialImportSafeText(error?.message||error);notify()}return false}finally{if(active(owner))notify()}};
    async function go(page,after){if(!active(owner))return;await Promise.resolve(window.setPage?.(page));if(pid()!==owner.project||String(getState?.()?.page||'')!==page)return;return after?.();}
    const context={projectId:owner.project,signal:owner.controller.signal,snapshot:()=>snapshot(owner),subscribe(fn){if(!active(owner))return()=>{};owner.listeners.add(fn);fn(snapshot(owner));return()=>owner.listeners.delete(fn)},actions:{
      images:guarded(()=>window.ImageUppyView?.open?.({projectId:owner.project})),zip:guarded(()=>window.openUppyZipUpload?.()),
      refresh:guarded(async()=>{if(owner.busy)return;owner.busy=true;notify();try{await window.UploadTaskCenterRuntime?.refresh?.()}finally{owner.busy=false}}),
      confirmation:guarded(()=>window.UploadConfirmationRuntime?.restoreForProject?.(owner.project,{autoOpen:true})),
      task:guarded((id,action)=>{
        const row=(window.UploadTaskCenterRuntime?.list?.()||[]).find(item=>String(item.id)===String(id));if(!row)return;
        if(row.kind!=='zip')return go('数据集');
        const zip=window.ZipImportRuntime,key=String(row.id).replace(/^zip:/,'');
        const callbacks={open:()=>row.localOnly?zip?.open?.():zip?.openTask?.(key),pause:()=>zip?.pauseUpload?.(key),resume:async()=>{await zip?.openTask?.(key);if(active(owner))return zip?.promptResume?.(key)},cancel:()=>row.localOnly?zip?.cancelQueuedUpload?.(key):zip?.cancelUpload?.(key),verify:()=>zip?.reconcile?.('manual-reverify')};
        if(!Object.hasOwn(callbacks,action))return;return callbacks[action]();
      }),
      navigate:guarded(key=>{
        if(key==='library')return go(window.PlatformCore?.runtime?.navigationStabilityRuntime?.hasPageOwner?.('素材库正式浏览')?'素材库正式浏览':'数据集');
        if(key==='ai')return go('自动标注及清洗',()=>window.createAiLabel429?.());
        if(key==='clean')return go('自动标注及清洗',()=>window.createClean427?.());
        if(key==='integrity')return go('数据集',()=>window.openMaterialIntegrityAudit47?.());
        if(key==='negative')return go('数据集',()=>window.NegativePoolRuntime?.open?.());
        if(key==='labels')return go('标签管理');
        if(key==='tasks'||key==='clean-history')return go('自动标注及清洗');
        return go('数据集');
      }),
    }};
    // Prefer a future original-owner subscription. Existing fallback observes
    // only the original task center, never the document or the Vue subtree.
    const center=window.UploadTaskCenterRuntime;center?.switchProject?.();
    if(typeof center?.subscribe==='function')owner.stopCenter=center.subscribe(()=>notify());
    else {const root=document.getElementById('uploadTaskCenter');const Observer=window.MutationObserver;if(root&&Observer){let queued=false;owner.observer=new Observer(()=>{if(queued)return;queued=true;queueMicrotask(()=>{queued=false;if(active(owner))notify()})});owner.observer.observe(root,{childList:true,subtree:true,characterData:true,attributes:true,attributeFilter:['style','class','aria-busy']});}}
    owner.stopTransfers=window.ZipImportRuntime?.subscribeTransfers?.(()=>notify());
    try{const dispose=await load(host,context);if(!active(owner)||generation!==ticket){dispose?.();return false}owner.dispose=dispose;notify();return true}
    catch(error){if(active(owner)){owner.error=materialImportSafeText(error?.message||error);notify();host.textContent='素材接入界面加载失败，请通过原数据集与上传任务中心继续。'}return false;}
  }
  return {render,leave,notify,destroy:leave};
}
