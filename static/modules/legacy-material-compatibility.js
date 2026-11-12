import {withRequestDeadline} from './api.js?v=20261021s';

const esc = value => String(value ?? '').replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
const statusText = value => ({normal:'兼容，无需迁移',candidate:'缺失元数据，可预览',unsupported:'仅报告，需人工核验',conflict:'证据冲突，不自动修改'}[value] || '待核验');
const issueText = value => ({'missing content_sha256':'缺少内容 SHA256','missing size_bytes':'缺少文件大小',
  'existing metadata differs from actual source':'已有元数据与实际原图不一致',
  'original is missing':'原始图片缺失','shared object reference requires explicit identity review':'共享原图引用需人工核验',
  'indexed/material payload mismatch':'索引与素材元数据不一致',
  'JSON-only repair unsupported; original owner migration required':'旧 JSON 仅只读检查，不自动导入',
  'source marked unavailable':'来源标记不可用'}[value] || `需人工核验：${value}`);

// Browser-only read receipts, never a Material/GT/task owner. A batch and its
// cursor commit in one transaction, so reload/retry cannot increment twice.
function openCheckCache() {
  return new Promise((resolve,reject)=>{
    const request=indexedDB.open('cl-legacy-compatibility-checks',1);
    request.onupgradeneeded=()=>{
      request.result.createObjectStore('sessions',{keyPath:'pid'});
      const rows=request.result.createObjectStore('rows',{keyPath:['pid','image_id']});
      rows.createIndex('project','pid');rows.createIndex('category','categoryKeys',{multiEntry:true});
    };
    request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
  });
}
function cached(db,stores,mode,operation) {
  return new Promise((resolve,reject)=>{
    const tx=db.transaction(stores,mode);let result;
    tx.oncomplete=()=>resolve(result);tx.onerror=tx.onabort=()=>reject(tx.error||new Error('检查缓存未保存，请重新打开后继续'));
    try{operation(tx,value=>{result=value});}catch(error){tx.abort();reject(error);}
  });
}
const categories={normal:'正常兼容',candidate:'可迁移',gt_issue:'GT 异常',thumbnail_issue:'缩略图异常',conflict:'数据冲突',unknown:'无法确认'};
const rowCategories=row=>{const values=(Array.isArray(row.categories)?row.categories:[({normal:'normal',candidate:'candidate',conflict:'conflict'})[row.status]||'unknown']).filter(key=>Object.hasOwn(categories,key));return [...new Set(values.length?values:['unknown'])];};

// Temporary operator UI; the original scan/preview/apply remain sole controllers.
export function renderLegacyMaterialCompatibility({projectId,notify,fetchImpl=window.nativeFetch||window.fetch.bind(window)}={}) {
  const view=document.getElementById('view'),pid=String(projectId?.()||'');if(!view)return;
  view.innerHTML=`<section class="panel"><header class="panel-head"><div><h2>旧素材兼容迁移</h2><p>全面只读检查，后台每批最多50条。迁移仍需单独预览、明确确认；原图与正式GT保持原样。汇总为逐条检查时点记录，库外原图改写不等同于元数据版本变更，需另行重新核验。</p></div></header><div class="panel-body"><div class="row"><button class="btn primary" data-compat-scan>开始全面检查</button><button class="btn" data-compat-pause disabled>暂停检查</button><button class="btn" data-compat-resume disabled>继续检查 / 重试</button></div><p role="status" aria-live="polite" data-compat-status>正在读取本机检查进度…</p><progress data-compat-progress hidden style="width:100%" aria-label="素材检查进度"></progress><div class="row" data-compat-summary></div><p class="muted">各异常类别可重叠；未检查记录不计为正常。缩略图尚未按需生成不视为损坏，无法验证的来源单列“无法确认”。</p><div class="row"><label>检查明细 <select class="select" data-compat-filter><option value="">全部记录</option>${Object.entries(categories).map(([key,label])=>`<option value="${key}">${label}</option>`).join('')}</select></label><button class="btn" data-compat-prev disabled>上一页</button><span data-compat-page></span><button class="btn" data-compat-next disabled>下一页</button><button class="btn" data-compat-preview disabled>预览当前页必要修复</button><button class="btn" data-compat-apply disabled>确认迁移本页元数据</button></div><div data-compat-results></div><div data-compat-plan></div></div></section>`;
  const root=view.firstElementChild,status=root.querySelector('[data-compat-status]');
  const controls=Object.fromEntries(['scan','pause','resume','prev','next','preview','apply'].map(key=>[key,root.querySelector(`[data-compat-${key}]`)]));
  const current=()=>view.contains(root)&&String(projectId?.()||'')===pid;
  let db,session=null,ready=false,running=false,pause=false,busy=false,page=0,filter='',candidates=[],plan=null,taskId=null,displayEpoch=0,controller=null,notice='';
  const observer=new MutationObserver(()=>{if(!current()){pause=true;controller?.abort();observer.disconnect();db?.close();}});observer.observe(view,{childList:true});
  function buttons(){
    const blocked=busy||running||!ready;
    controls.scan.disabled=blocked;controls.pause.disabled=!running||pause;controls.resume.disabled=blocked||!session||session.complete||session.stale;
    controls.preview.disabled=blocked||session?.stale||!candidates.length;controls.apply.disabled=blocked||session?.stale||!plan?.fingerprint||!candidates.length;
    controls.prev.disabled=page===0||busy;controls.next.disabled=(page+1)*25>=Number(filter?session?.counts?.[filter]:session?.checked)||busy;
    for(const key of ['scan','resume','preview','apply'])controls[key].setAttribute('aria-busy',String((running&&['scan','resume'].includes(key))||busy));
  }
  function progress(){
    if(!current())return;buttons();const checked=session?.checked||0,total=session?.total;
    const quantity=`${checked} / ${Number.isInteger(total)?total:'总量未知'}`;
    status.textContent=notice||(!session?'尚未检查。点击一次即可顺序检查全部素材。':session.stale?`素材或GT证据已变化，需要重新核验；上次已检查 ${quantity}，不能给出全库结论。`:session.complete?`全量检查完成：${quantity}；${session.counts.candidate||0} 条需要预览缺失元数据修复。${session.requires_recheck?'旧GT无统一版本，仍需人工重新核验。':(session.counts.normal||0)===checked?'检查时点的全部记录兼容，无需元数据迁移。':'请按异常分类核验，未自动迁移任何数据。'}${session.source_recheck?'含恢复的历史原图检查记录，原图状态需重新核验。':''}`:running?`${pause?'正在暂停，等待本批只读检查安全结束':'正在只读检查全部素材'}：${quantity}`:`已暂停：${quantity}。可继续检查；尚不能给出全库结论。`);
    root.querySelector('[data-compat-summary]').innerHTML=Object.entries(categories).map(([key,label])=>`<span class="badge">${label} ${session?.counts?.[key]||0}</span>`).join('');
    const bar=root.querySelector('[data-compat-progress]');bar.hidden=!session;
    if(Number.isInteger(total)&&total>0&&!session?.stale){bar.max=total;bar.value=checked;}else bar.removeAttribute('value');
  }
  async function request(action,body){
    controller=new AbortController();
    try{return await withRequestDeadline(async signal=>{
      const response=await fetchImpl(`/api/v62/projects/${encodeURIComponent(pid)}/legacy-material-compatibility/${action}`,{method:body?'POST':'GET',signal,...(body?{headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{})});
      const data=await response.json();if(!response.ok)throw Object.assign(new Error(typeof data.detail==='string'?data.detail:data.detail?.message||'兼容检查失败，请安全重试'),{status:response.status});return data;
    },{timeoutMs:30000,label:body?'兼容元数据操作':'只读兼容检查',signal:controller.signal});}
    catch(error){if(!body&&error.code==='REQUEST_TIMEOUT')error.message='只读检查超时，本批未计入，可继续重试';throw error;}
  }
  async function details(){
    const epoch=++displayEpoch;if(!db||!current())return;
    const rows=await cached(db,['rows'],'readonly',(tx,done)=>{
      const store=tx.objectStore('rows'),index=store.index(filter?'category':'project');
      const query=index.openCursor(IDBKeyRange.only(filter?`${pid}:${filter}`:pid)),items=[];let positioned=page===0;
      query.onsuccess=()=>{const cursor=query.result;if(!cursor||items.length===25){done(items);return;}if(!positioned){positioned=true;cursor.advance(page*25);return;}items.push(cursor.value);cursor.continue();};
    });
    if(!current()||epoch!==displayEpoch)return;
    candidates=rows.filter(row=>row.candidate).map(row=>row.image_id);
    root.querySelector('[data-compat-results]').innerHTML=`<table class="table"><thead><tr><th>图片身份</th><th>状态</th><th>检查结果</th></tr></thead><tbody>${rows.map(row=>`<tr><td>${esc(row.image_id)}</td><td>${esc(statusText(row.status))}</td><td>${esc((row.issues||[]).map(issueText).join('；')||rowCategories(row).map(key=>categories[key]).join('；'))}</td></tr>`).join('')}</tbody></table>`;
    root.querySelector('[data-compat-page]').textContent=`第 ${page+1} 页 · 每页25条`;buttons();
  }
  const saveSession=()=>cached(db,['sessions'],'readwrite',(tx,done)=>{
    const headers=tx.objectStore('sessions'),read=headers.get(pid);
    read.onsuccess=()=>{const saved=read.result;if(saved?.id===session.id&&saved.checked===session.checked&&saved.cursor===session.cursor){headers.put(session);done(true);}else done(false);};
  });
  async function reset(){
    const next={pid,id:crypto.randomUUID(),checked:0,total:null,cursor:'',catalog:'',complete:false,counts:{},updated_at:new Date().toISOString()};
    await cached(db,['sessions','rows'],'readwrite',tx=>{
      tx.objectStore('sessions').put(next);const query=tx.objectStore('rows').index('project').openCursor(IDBKeyRange.only(pid));
      query.onsuccess=()=>{const row=query.result;if(row){row.delete();row.continue();}};
    });session=next;page=0;plan=null;taskId=null;root.querySelector('[data-compat-plan]').textContent='';
  }
  async function accept(data){
    const rows=data.items;if(!Array.isArray(rows)||rows.length>50)throw new Error('检查返回不完整，本批未计入，请重试');
    let last=session.cursor;for(const row of rows){if(typeof row.image_id!=='string'||row.image_id<=last)throw new Error('图片身份重复或游标无效，需要重新核验');last=row.image_id;}
    if(session.catalog&&data.catalog_fingerprint!==session.catalog)throw Object.assign(new Error('检查版本已变化，需要重新核验'),{status:409});
    const next={...session,counts:{...session.counts},catalog:data.catalog_fingerprint||session.catalog,total:Number.isInteger(data.total)?data.total:session.total,cursor:last,checked:session.checked+rows.length,complete:!data.next_cursor,requires_recheck:session.requires_recheck||data.requires_recheck||!data.catalog_fingerprint,updated_at:new Date().toISOString()};
    if(data.next_cursor&&(data.next_cursor!==last||!rows.length))throw new Error('检查游标没有推进，请重新核验');
    if(next.complete&&Number.isInteger(next.total)&&next.checked!==next.total)throw Object.assign(new Error('检查数量与总量不一致，需要重新核验'),{status:409});
    for(const row of rows)for(const category of rowCategories(row))next.counts[category]=(next.counts[category]||0)+1;
    await cached(db,['sessions','rows'],'readwrite',tx=>{
      const headers=tx.objectStore('sessions'),read=headers.get(pid);
      read.onsuccess=()=>{
        const saved=read.result;if(saved?.id!==session.id||saved.checked!==session.checked||saved.cursor!==session.cursor){tx.abort();return;}
        for(const row of rows)tx.objectStore('rows').put({pid,image_id:row.image_id,status:row.status,candidate:row.candidate,issues:row.issues||[],categories:rowCategories(row),categoryKeys:rowCategories(row).map(key=>`${pid}:${key}`)});
        headers.put(next);
      };
    });session=next;
  }
  async function scan(fresh){
    if(running||busy||!ready||!current()||!fresh&&(!session||session.complete||session.stale))return;
    running=true;pause=false;notice='';plan=null;taskId=null;progress();
    try{
      if(fresh)await reset();
      if(!current())return;
      do{
        progress();const query=new URLSearchParams({limit:'50',cursor:session.cursor});if(session.catalog)query.set('expected_catalog',session.catalog);
        const data=await request(`scan?${query}`);if(!current())return;
        await accept(data);progress();await details();
      }while(!session.complete&&!pause&&current());
    }catch(error){
      if(current()){
        if(error.status===409&&session){session={...session,complete:false,stale:true};await saveSession().catch(()=>{});}
        notice=`${error.message||'检查失败，可继续重试'}；已检查 ${session?.checked||0} / ${Number.isInteger(session?.total)?session.total:'总量未知'}，未检查记录不计为正常。`;
      }
    }finally{running=false;if(current())progress();}
  }
  async function perform(label,action){
    if(busy||running||!current())return;busy=true;notice=label;progress();
    try{await action();}catch(error){if(current())notice=error.message||'操作未完成，可安全重试';}
    finally{busy=false;if(current())progress();}
  }
  controls.scan.onclick=()=>scan(true);controls.resume.onclick=()=>scan(false);
  controls.pause.onclick=()=>{pause=true;progress();};
  controls.prev.onclick=()=>{page=Math.max(0,page-1);plan=null;details().catch(error=>{notice=error.message;progress();});};
  controls.next.onclick=()=>{page++;plan=null;details().catch(error=>{notice=error.message;progress();});};
  root.querySelector('[data-compat-filter]').onchange=event=>{filter=event.target.value;page=0;plan=null;details().catch(error=>{notice=error.message;progress();});};
  controls.preview.onclick=()=>perform('正在核对迁移影响与当前版本…',async()=>{
    const data=await request('preview',{image_ids:candidates});if(!current())return;
    plan=data.preview||data;taskId=`legacy-metadata-${crypto.randomUUID()}`;
    root.querySelector('[data-compat-plan]').innerHTML=`<p>仅修复当前页 ${candidates.length} 条明确缺失的元数据。执行前备份并重新核验；原图及GT不修改。</p><table class="table"><thead><tr><th>图片身份</th><th>大小</th><th>SHA256</th></tr></thead><tbody>${(plan.items||[]).map(item=>`<tr><td>${esc(item.image_id)}</td><td>${esc(item.proposed?.size_bytes??'不修改')}</td><td>${esc(item.proposed?.content_sha256||'不修改')}</td></tr>`).join('')}</tbody></table>`;
    notice=plan.fingerprint?'影响预览已就绪，请核对后明确确认。':'当前没有可执行计划，请重新检查。';
  });
  controls.apply.onclick=()=>{
    if(busy||running||!plan||!window.confirm('确认只补齐本页缺失元数据？原始图片及正式GT不会修改。'))return;
    return perform('正在备份并迁移本批元数据，请勿重复提交…',async()=>{
      await request('apply',{image_ids:candidates,expected_fingerprint:plan.fingerprint,task_id:taskId,confirm:'migrate_legacy_material_metadata'});if(!current())return;
      plan=null;candidates=[];session={...session,stale:true,complete:false};await saveSession();notice='本批元数据处理完成。检查证据已失效，请重新全面检查。';notify?.('本批兼容元数据处理完成');
    });
  };
  buttons();
  (async()=>{
    db=await openCheckCache();if(!current()){db.close();return;}
    session=await cached(db,['sessions'],'readonly',(tx,done)=>{const query=tx.objectStore('sessions').get(pid);query.onsuccess=()=>done(query.result||null);});
    if(session&&!session.complete)session={...session,source_recheck:true};
    ready=true;if(session?.complete&&!session.stale){ready=false;notice='正在重新核验上次全量检查的数据版本…';}progress();await details();
    if(session?.complete&&!session.stale){
      ready=false;notice='正在重新核验上次全量检查的数据版本…';progress();
      try{const checked=await request(`scan?${new URLSearchParams({limit:'1',cursor:session.cursor,expected_catalog:session.catalog})}`);if(checked.catalog_fingerprint!==session.catalog)throw new Error('检查证据版本变化');if(current()){notice=`上次全量检查记录：${session.checked} / ${Number.isInteger(session.total)?session.total:'总量未知'}。元数据版本未变；原图仅在逐条检查时核验，确认当前原图状态请重新全面检查。`;progress();}}
      catch(error){if(current()){session={...session,complete:false,stale:true};await saveSession();notice='上次检查版本无法确认，请重新全面检查。';}}
      finally{ready=true;if(current())progress();}
    }
  })().catch(error=>{if(current()){notice=`本机检查缓存不可用：${error.message}。未启动检查，请检查浏览器存储设置后重试。`;progress();}});
}
