import {withRequestDeadline} from './api.js?v=20261021s';
const escapeHtml = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const uploadSessionKey = projectId => `material-upload-session:${projectId}`;

export function confirmationRows(batches) {
  const seen = new Set();
  return batches.flatMap(batch => (batch.items || []).filter(item => {
    const id = String(item.image_id || '');
    if (!id || seen.has(id) || item.missing || !item.image || String(item.image.id) !== id || item.image.retired_at || item.image.lifecycle_status === 'retired') return false;
    seen.add(id);
    return true;
  }).map(item => ({...item, batchId: String(batch.id), cleanTaskId: batch.clean_task_id || ''})));
}

export function decisionGroups(rows, selected, decision) {
  const groups = new Map();
  for (const row of rows) {
    if (!selected.has(String(row.image_id)) || row.decision !== 'pending') continue;
    if (decision === 'clean' && row.cleanTaskId) throw new Error('该批次已有清洗任务；剩余图片可直接标注或稍后处理');
    if (decision === 'clean' && (row.image.annotated || (row.image.annotation_state && row.image.annotation_state !== 'unannotated'))) throw new Error('已产生标注的图片请使用现有标注质量审计');
    if (!groups.has(row.batchId)) groups.set(row.batchId, []);
    groups.get(row.batchId).push(String(row.image_id));
  }
  return groups;
}

export function installUploadConfirmationRuntime({getState, api, getContainer, previewImage, notify, storage = globalThis.localStorage, document: doc = globalThis.document, window: win = globalThis.window} = {}) {
  let session = null, batches = [], selected = new Set(), visible = false, busy = false, loading = false, error = '', page = 1, failurePage = 1, generation = 0;
  const PAGE_SIZE = 48;
  const state = () => getState?.() || {};
  const activeProject = () => String(state().project?.id || state().projectId || '');
  const say = message => (notify || win?.toast)?.(message);
  const endpoint = (project, batch) => `/api/v55/projects/${encodeURIComponent(project)}/upload-batches/${encodeURIComponent(batch)}`;
  const current = (project, token) => token === generation && (!activeProject() || activeProject() === String(project));
  const request = (url, options={}) => withRequestDeadline(signal => api(url, {...options,signal}), {timeoutMs:30000,label:'上传回执'});
  const read = project => {try { return JSON.parse(storage?.getItem(uploadSessionKey(project)) || 'null'); } catch { return null; }};
  function recordSession(value) {
    const projectId = String(value.projectId || '');
    if (!projectId) return null;
    const prior = read(projectId) || {};
    const next = {...prior, ...value, failed:Array.isArray(value.failed)?value.failed.length:(value.failed??prior.failed??0), projectId, batchIds: [...new Set((value.batchIds || prior.batchIds || []).map(String))]};
    // Only session pointers/counters live here. Image identities and decisions come from receipts.
    try {storage?.setItem(uploadSessionKey(projectId), JSON.stringify(next));} catch {}
    return next;
  }
  async function fetchReceipts(projectId, ids, token = generation, recovering = false) {
    const results = [];
    for (const id of ids) {
      if(!current(projectId,token)) throw new Error('项目已切换');
      let receipt;
      try {receipt = await request(endpoint(projectId, id));} catch(e) {if(recovering && e.httpStatus===404)continue;throw e;}
      if(!current(projectId,token)) throw new Error('项目已切换');
      if(recovering && receipt.upload_request_status && receipt.upload_request_status !== 'SUCCEEDED') continue;
      if (String(receipt.id) !== String(id)) throw new Error('上传批次回执不匹配');
      results.push(receipt);
    }
    return results;
  }
  const sessionIds = value => [...new Set([...(value?.batchIds || []),...(value?.requestIds || [])].map(String))];
  const unconfirmedCount = () => Math.max(0, Number(session?.totalFiles || 0) - batches.reduce((count,batch) => count + (batch.items?.length || 0) + (batch.upload_failed?.length || 0), 0));
  function mount(container = getContainer?.()) {
    if (!container || !session || activeProject() && activeProject() !== session.projectId) return;
    let root = container.querySelector('[data-upload-confirmation]');
    if (!root) {root = doc.createElement('section'); root.dataset.uploadConfirmation = ''; container.prepend(root);}
    if(visible && container.firstElementChild !== root || visible && container.children?.length > 1) container.replaceChildren(root);
    root.className = 'upload-confirmation';
    const rows = confirmationRows(batches), pending = rows.filter(r => r.decision === 'pending');
    if (!visible) {
      root.innerHTML = pending.length || unconfirmedCount() || error ? `<button class="btn" data-upload-action="open">本次上传图片 · ${pending.length} 张待处理${unconfirmedCount()?` · 待核验入库 ${unconfirmedCount()} 张`:''}</button>${error ? `<span role="status">${escapeHtml(error)}</span>` : ''}` : '';
    } else {
      const failures = batches.flatMap(b => b.upload_failed || []);
      const successfulNames = new Set(batches.flatMap(batch => batch.items || []).map(row => String(row.image?.filename || '')));
      const retryNames = [...new Set(failures.map(row => String(row.name || '')).filter(name => name && !successfulNames.has(name)))];
      const total = session.totalFiles || batches.reduce((n,b) => n + (b.upload_request_manifest?.length || b.items?.length || 0), 0);
      const start = (page - 1) * PAGE_SIZE, pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
      root.innerHTML = `<style>.upload-confirmation{margin:16px 0}.upload-confirmation .uc-workspace{padding:24px;background:var(--panel,#fff);border:1px solid var(--line,#dce3ec);border-radius:16px}.upload-confirmation .uc-head,.upload-confirmation .uc-actions{display:flex;gap:12px;align-items:center;flex-wrap:wrap;justify-content:space-between}.upload-confirmation .uc-summary{display:flex;gap:24px;flex-wrap:wrap;margin:20px 0;color:var(--muted,#64748b)}.upload-confirmation .uc-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:16px;margin:20px 0}.upload-confirmation .uc-card{border:1px solid var(--line,#dce3ec);border-radius:12px;overflow:hidden}.upload-confirmation .uc-card:has(input:checked){outline:2px solid #3665ef}.upload-confirmation .uc-card img{width:100%;height:150px;object-fit:contain;background:#f1f5f9}.upload-confirmation .uc-card button{border:0;padding:0;width:100%;cursor:zoom-in}.upload-confirmation .uc-caption{padding:10px;display:grid;gap:8px}.upload-confirmation .uc-name{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}.upload-confirmation .uc-error{color:#b42318}</style><div class="uc-workspace" aria-busy="${loading || busy}"><div class="uc-head"><h2>本次上传图片</h2><button class="btn" data-upload-action="later" ${busy?'disabled':''}>稍后处理</button></div><div class="uc-summary"><span>本次选择 <b>${total}</b> 张</span><span>成功入库 <b>${rows.length}</b> 张</span><span>上传失败 <b>${failures.length || (Array.isArray(session.failed)?session.failed.length:Number(session.failed)||0)}</b> 张</span><span>等待处理 <b>${pending.length}</b> 张</span><span>待核验入库 <b>${unconfirmedCount()}</b> 张</span></div>${unconfirmedCount()?`<p role="status">仍有图片等待服务端回执核验。<button class="btn" data-upload-action="refresh" ${loading?'disabled':''}>重新核验上传回执</button></p>`:''}${loading?'<p role="status">正在核对服务端上传回执…</p>':''}${error?`<p class="uc-error" role="alert">${escapeHtml(error)} <button class="btn" data-upload-action="refresh">重新读取</button></p>`:''}<div class="uc-actions"><label><input type="checkbox" data-upload-action="all" ${pending.length && pending.every(r=>selected.has(String(r.image_id)))?'checked':''} ${busy?'disabled':''}> 全选待处理图片</label><span>已选择 ${selected.size} 张</span></div><div class="uc-grid">${rows.slice(start,start+PAGE_SIZE).map(r=>`<article class="uc-card"><button data-preview="${escapeHtml(r.image_id)}" aria-label="查看 ${escapeHtml(r.image.filename)} 大图"><img src="${escapeHtml(r.image.thumbnail_url || `/api/v61/projects/${encodeURIComponent(session.projectId)}/materials/${encodeURIComponent(r.image_id)}/content/thumbnail?edge=384`)}" loading="lazy" decoding="async" alt="${escapeHtml(r.image.filename)}"></button><div data-thumbnail-error="${escapeHtml(r.image_id)}" hidden role="status">缩略图加载失败 <button class="btn mini" data-retry-thumbnail="${escapeHtml(r.image_id)}">重试</button></div><div class="uc-caption"><label class="uc-name" title="${escapeHtml(r.image.filename)}"><input type="checkbox" data-id="${escapeHtml(r.image_id)}" ${selected.has(String(r.image_id))?'checked':''} ${busy || r.decision!=='pending'?'disabled':''}> ${escapeHtml(r.image.filename)}</label><span>${r.decision==='clean'?'已提交清洗':r.decision==='ready'?'无需清洗 · 待标注':'待处理'}</span>${r.cleanTaskId?`<button class="btn mini" data-task="${escapeHtml(r.cleanTaskId)}">查看清洗进度</button>`:''}</div></article>`).join('')}</div><div class="uc-actions"><span>第 ${page} / ${pages} 页</span><div><button class="btn" data-upload-action="prev" ${page<=1?'disabled':''}>上一页</button> <button class="btn" data-upload-action="next" ${page>=pages?'disabled':''}>下一页</button></div></div>${failures.length?`<details><summary>上传失败 ${failures.length} 张</summary>${failures.slice((failurePage-1)*48,failurePage*48).map(f=>`<p>${escapeHtml(f.name)}：${escapeHtml(f.reason)}</p>`).join('')}<div class="uc-actions"><button class="btn" data-upload-action="failure-prev" ${failurePage<=1?'disabled':''}>上一页</button><span>第 ${failurePage} / ${Math.ceil(failures.length/48)} 页</span><button class="btn" data-upload-action="failure-next" ${failurePage*48>=failures.length?'disabled':''}>下一页</button><button class="btn" data-upload-action="retry" ${retryNames.length?'':'disabled'}>${retryNames.length?'重新选择失败图片':'失败文件与成功文件同名，请核对后重新上传'}</button></div></details>`:''}<div class="uc-actions" style="margin-top:24px"><button class="btn" data-upload-action="clean" ${busy||!selected.size?'disabled':''}>开始清洗</button><button class="btn primary" data-upload-action="ready" ${busy||!selected.size?'disabled':''}>无需清洗，进入标注</button></div></div>`;
    }
    root.querySelectorAll?.('.uc-card img').forEach(img => {img.onerror = () => {const card=img.closest('.uc-card');const feedback=card?.querySelector('[data-thumbnail-error]');if(feedback)feedback.hidden=false;img.hidden=true;};});
    root.onchange = event => {
      if (busy) return;
      const input = event.target;
      if (input.dataset.uploadAction === 'all') selected = input.checked ? new Set(pending.map(r=>String(r.image_id))) : new Set();
      else if (input.dataset.id) {if(input.checked)selected.add(input.dataset.id);else selected.delete(input.dataset.id);}
      mount(container);
    };
    root.onclick = event => {
      const button = event.target.closest('button'); if (!button || button.disabled) return;
      if(button.dataset.retryThumbnail){const card=button.closest('.uc-card'),img=card?.querySelector('img'),feedback=card?.querySelector('[data-thumbnail-error]');if(img){if(feedback)feedback.hidden=true;img.hidden=false;const source=img.getAttribute('src');img.removeAttribute('src');img.setAttribute('src',source);}return;}
      if (button.dataset.preview) {const row = rows.find(r=>String(r.image_id)===button.dataset.preview); if(row) previewImage?.(row.image); return;}
      if (button.dataset.task) {win?.showTaskProgress427?.('clean',button.dataset.task);return;}
      const action = button.dataset.uploadAction;
      if (action==='later') {visible=false; session=recordSession({...session,deferred:true}); win?.renderDatasets424?.();mount(container);}
      if (action==='open'||action==='refresh') void open(session);
      if (action==='prev'||action==='next') {page += action==='prev'?-1:1;mount(container);}
      if(action==='failure-prev'||action==='failure-next'){failurePage+=action==='failure-prev'?-1:1;mount(container);container.querySelector('details')?.setAttribute('open','');}
      if(action==='retry') {
        const successfulNames = new Set(batches.flatMap(batch => batch.items || []).map(row => String(row.image?.filename || '')));
        const retryNames = [...new Set(batches.flatMap(batch => batch.upload_failed || []).map(row => String(row.name || '')).filter(name => name && !successfulNames.has(name)))];
        if(retryNames.length) win?.ImageUppyView?.open?.({retryNames});
      }
      if (action==='clean'||action==='ready') void submit(action);
    };
  }
  async function open(value) {
    if (busy) return false;
    session = recordSession({...value,deferred:false}); if (!session) return false;
    const token = ++generation; visible=true;loading=true;error='';selected.clear();batches=[];page=1;failurePage=1;
    await win?.setPage?.('数据集'); if(!current(session.projectId,token))return false;mount();
    try {const next=await fetchReceipts(session.projectId,sessionIds(session),token,true);if(!current(session.projectId,token))return false;batches=next;session=recordSession({...session,batchIds:[...new Set([...(session.batchIds||[]),...next.map(batch=>String(batch.id))])]});}
    catch(e){error=String(e.message||e);}
    finally {if(token===generation){loading=false;if(current(session.projectId,token))mount();}}
    return !error;
  }
  async function restoreForProject(projectId, {autoOpen = true} = {}) {
    // Navigation may restore while open() is awaiting setPage; keep that request owner.
    if (busy || loading) return false;
    const value=read(String(projectId));if(!value || !(value.batchIds?.length || value.requestIds?.length))return false;
    const token=++generation;session=value;visible=false;error='';
    try {const next=await fetchReceipts(String(projectId),sessionIds(value),token,true);if(!current(session.projectId,token))return false;batches=next;session=recordSession({...value,batchIds:[...new Set([...(value.batchIds||[]),...next.map(b=>String(b.id))])]});visible=autoOpen && (confirmationRows(batches).some(r=>r.decision==='pending') || unconfirmedCount()>0) && !value.deferred;mount();return true;}catch(e){if(!current(String(projectId),token))return false;error=String(e.message||e);mount();return false;}
  }
  async function submit(decision) {
    if(busy||loading||!session)return false;
    busy=true;error='';mount();const projectId=session.projectId, token=generation, chosen=new Set(selected), ready=[];
    try {
      batches=await fetchReceipts(projectId,session.batchIds,token);if(!current(projectId,token))return false;
      const groups=decisionGroups(confirmationRows(batches),chosen,decision);
      for(const [batchId,ids] of groups){
        if(!current(projectId,token))return false;
        const updated=await request(`${endpoint(projectId,batchId)}/decisions`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({clean_image_ids:decision==='clean'?ids:[],ready_image_ids:decision==='ready'?ids:[]})});
        if(!current(projectId,token))return false;
        batches=batches.map(b=>String(b.id)===batchId?updated:b);
        if(decision==='ready')ready.push(...ids);
      }
      selected.clear();
      if(ready.length && (!activeProject() || activeProject()===projectId)){state().annotationQueue414=ready;await win?.openAnnotation?.(ready[0]);}
      return true;
    }catch(e){if(current(projectId,token)){error=String(e.message||e);say(error);}return false;}finally{busy=false;if(current(projectId,token))mount();}
  }
  const runtime={open,recordSession,restoreForProject,mount,submit,renderIfActive(){if(!visible||!session||(activeProject() && activeProject()!==session.projectId))return false;mount();return true;},getSession:()=>session,destroy(){generation++;doc?.querySelectorAll('[data-upload-confirmation]').forEach(el=>el.remove());session=null;batches=[];selected.clear();}};
  if(win)win.UploadConfirmationRuntime=runtime;
  return runtime;
}



