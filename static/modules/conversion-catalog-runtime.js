/** One embedded catalog owner. Server owns identities, references and capabilities. */
export function installConversionCatalogRuntime({api,getState,window:win=globalThis.window,document:doc=globalThis.document,modal,closeModal}) {
  const base='/api/v39/deploy/catalog';
  const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const rejected=code=>new Set(['CATALOG_INVALID_REQUEST','CATALOG_VALIDATION_FAILED','CATALOG_REVISION_CONFLICT','CATALOG_OPERATION_CONFLICT','CATALOG_NOT_FOUND','CATALOG_ID_IMMUTABLE','CATALOG_DUPLICATE_NAME','CATALOG_DUPLICATE_CODE','CATALOG_REFERENCED','CATALOG_DELETE_CONFIRMATION_REQUIRED','CATALOG_REFERENCE_CHECK_FAILED','CATALOG_BUSY']).has(code);
  let root,life,epoch=0,project,selected='',revision=0,templates=[],form,dialogAbort,opening=null;
  const queries={vendors:{page:1},chips:{page:1}},tickets={vendors:0,chips:0},inflight=new Map();
  const rows={vendors:[],chips:[]};
  const live=stamp=>stamp===epoch&&root?.isConnected&&getState().page==='部署资源'&&project===getState().project?.id;
  const slot=name=>root?.querySelector(`[data-slot="${name}"]`);
  const status=(message,error=false)=>{const el=slot('notice');if(el){el.textContent=message;el.setAttribute('role',error?'alert':'status')}};
  function read(url){
    if(inflight.has(url))return inflight.get(url);
    const promise=api(url,{signal:life.signal}).finally(()=>{if(inflight.get(url)===promise)inflight.delete(url)});
    inflight.set(url,promise);return promise;
  }
  function operations(entity,row){return `<div class="catalog-actions">${['view','edit','delete',row.enabled?'disable':'enable',...(entity==='chips'?['detect']:[])].map(action=>`<button class="btn mini ${action==='delete'?'danger':''}" data-catalog-action="${action}" data-entity="${entity}" data-id="${esc(row.id)}">${({view:'查看',edit:'编辑',delete:'删除',disable:'停用',enable:'启用',detect:'检测转换能力'})[action]}</button>`).join('')}</div>`}
  function paint(entity,result){
    const body=slot(entity);if(!body)return;
    body.innerHTML=result.items.map(r=>`<tr data-catalog-${entity==='vendors'?'vendor':'chip'}="${esc(r.id)}" class="${entity==='vendors'&&selected===r.id?'selected':''}"><td>${entity==='vendors'?`<button class="catalog-name" data-catalog-action="select" data-id="${esc(r.id)}">${esc(r.name)}</button>`:`<strong>${esc(r.name)}</strong>`}</td>${entity==='vendors'?`<td>${esc(r.template_name)}</td><td>${r.chip_count} / ${r.enabled_chip_count}</td><td>${r.implemented?'已适配':'暂未适配'}</td>`:`<td>${esc(r.sdk_code||'待适配')}</td><td>${esc((r.capability?.allowed_precisions||[]).map(p=>p.toUpperCase()).join(' / ')||'待检测')}</td><td>${esc((r.capability?.resources||[]).map(f=>`${f.resource_name} · ${f.sdk_version||'版本未知'} · ${f.ready?'可用':'不可用'}`).join('；')||'无匹配资源')}</td>`}<td>${r.enabled?'已启用':'已停用'}</td><td>${operations(entity,r)}</td></tr>`).join('')||'<tr><td colspan="6"><div class="empty">暂无匹配记录</div></td></tr>';
    const paging=slot(`${entity}-pager`);
    paging.innerHTML=`<span>共 ${result.total} 条 · 第 ${result.page} 页</span><button class="btn mini" data-catalog-action="page" data-entity="${entity}" data-page="${result.page-1}" ${result.page<=1?'disabled':''}>上一页</button><button class="btn mini" data-catalog-action="page" data-entity="${entity}" data-page="${result.page+1}" ${result.page*result.page_size>=result.total?'disabled':''}>下一页</button>`;
    if(entity==='vendors')slot('vendor-title').textContent=rows.vendors.find(v=>v.id===selected)?.name||'请选择厂商';
  }
  async function load(entity,{selectFirst=false}={}){
    if(!live(epoch))return;
    const stamp=epoch,ticket=++tickets[entity];
    if(entity==='chips'&&!selected){slot('chips').innerHTML='<tr><td colspan="6"><div class="empty">选择厂商后管理芯片</div></td></tr>';slot('chips-pager').innerHTML='';return}
    const params=new URLSearchParams({entity,page_size:'10',...queries[entity],...(entity==='chips'?{vendor_id:selected}:{})});
    try{
      const result=await read(`${base}/records?${params}`);
      if(!live(stamp)||ticket!==tickets[entity])return;
      revision=result.revision;templates=result.templates;rows[entity]=result.items;queries[entity].page=result.page;
      if(entity==='vendors'){
        const filter=root.querySelector('[name="vendors-template_id"]');
        if(filter.options.length===1)filter.insertAdjacentHTML('beforeend',templates.map(t=>`<option value="${esc(t.id)}">${esc(t.name)}</option>`).join(''));
        if(selectFirst&&!selected)selected=result.items[0]?.id||'';
      }
      paint(entity,result);
      const addChip=root.querySelector('[data-catalog-action="new"][data-entity="chips"]');if(addChip)addChip.disabled=!selected;
      if(selectFirst)await load('chips');
    }catch(error){if(live(stamp)&&ticket===tickets[entity]&&error.name!=='AbortError')status(`读取失败：${error.message}，可点击刷新重试。`,true)}
  }
  function releaseDialog(){dialogAbort?.abort();dialogAbort=null;form=null}
  function close(){releaseDialog();closeModal()}
  function show(title,html){
    releaseDialog();modal(title,`<div data-catalog-dialog>${html}<p class="catalog-form-error" role="alert"></p></div>`,false);
    const area=doc.querySelector('[data-catalog-dialog]');
    dialogAbort=new AbortController();
    const signal=dialogAbort.signal,dialog=area.closest('[role="dialog"]')||area.parentElement;
    dialog.addEventListener('click',event=>{
      if(event.target.closest('[data-v424-close],.modal-head [aria-label="关闭"],.modal-close,[data-catalog-action="cancel"]')){releaseDialog();if(event.target.closest('[data-catalog-action="cancel"]'))closeModal();return}
      const button=event.target.closest('[data-dialog-action]');if(button)void dialogAction(button.dataset.dialogAction);
    },{signal});
    doc.addEventListener('keydown',event=>{if(event.key==='Escape')releaseDialog()},{signal,capture:true});
    area.addEventListener('submit',event=>{event.preventDefault();void save()},{signal});
    return area;
  }
  const field=(key,label,value='',extra='')=>`<label class="field">${label}<input class="input" name="${key}" value="${esc(value)}" ${extra}></label>`;
  const footer=label=>`<div class="row end"><button type="button" class="btn" data-catalog-action="cancel">取消</button><button class="btn primary" type="submit" data-save>${label}</button></div>`;
  async function open(entity,id,action){
    if(opening||doc.querySelector('[data-catalog-dialog]'))return;
    const request={vendor:selected};opening=request;
    const stamp=epoch;status('正在读取…');
    try{
      const detail=id?await read(`${base}/records/${entity}/${encodeURIComponent(id)}`):null;
      if(!live(stamp)||opening!==request||selected!==request.vendor)return;status('');
      const item=detail?.item||{enabled:true,vendor_id:selected},refs=detail?.references;
      const name=entity==='vendors'?'厂商':'芯片',mutableIdentity=!id||refs?.can_delete===true;
      if(action==='view'||action==='detect'){
        show(`${name}详情`,detailHtml(item,refs)+`<div class="row end"><button class="btn" data-catalog-action="cancel">关闭</button></div>`);return;
      }
      if(action==='delete'){
        show(`删除${name}`,`<p>确认删除「${esc(item.name)}」？</p>${refs?.can_delete===true?'<p>后端将再次核验引用。删除后不可恢复。</p><button class="btn danger" data-dialog-action="confirm-delete">确认删除</button>':`${referenceNotice(refs)}${refs?.reference_count?`<div class="alert soft">存在 ${refs.reference_count} 项引用，不能物理删除。可停用以保留历史身份。</div>`:''}<button class="btn" data-dialog-action="disable">改为停用</button>`}<button class="btn" data-catalog-action="cancel">取消</button>`);
      }else{
        const content=entity==='vendors'?`<label class="field">SDK 模板<select class="select" name="template_id" ${id&&!mutableIdentity?'disabled':''}>${templates.map(t=>`<option value="${esc(t.id)}" ${t.id===item.template_id?'selected':''}>${esc(t.name)}</option>`).join('')}</select></label>`:`<label class="field">所属厂商<input class="input" value="${esc(rows.vendors.find(v=>v.id===item.vendor_id)?.name||item.vendor_id)}" readonly></label>`;
        show(`${id?'编辑':'新增'}${name}`,`${referenceNotice(refs)}<form>${field('name',`${name}名称`,item.name,'required maxlength="120"')}${content}<label class="catalog-check"><input type="checkbox" name="enabled" ${item.enabled?'checked':''}> 启用</label><details><summary>高级配置</summary>${id?field('id','稳定 ID',id,'readonly'): '<p class="subline">稳定 ID 由系统生成。</p>'}${entity==='chips'?field('code','本地编码',item.code,!mutableIdentity?'readonly':'')+field('sdk_code','SDK 目标编码',item.sdk_code,!mutableIdentity?'readonly':''):' '}${entity==='chips'?'<p class="subline">留空时由后端建议；未知型号登记为待适配。兼容性与精度由实际资源检测决议。</p>':''}</details>${footer(`保存${name}`)}</form>`);
      }
      form={entity,id,item,revision:detail?.revision??revision,action,mutableIdentity,busy:false,operation:null};
      return form;
    }catch(error){if(live(stamp)&&opening===request)status(error.message,true)}finally{if(opening===request)opening=null}
  }
  function referenceNotice(refs){
    if(refs?.check_status!=='UNVERIFIED'&&refs?.check_status!=='RECOVERED')return '';
    const unknown=refs.check_status==='UNVERIFIED',diagnostic=refs.diagnostic;
    const details=diagnostic?[diagnostic.code,diagnostic.detail,diagnostic.solution].filter(Boolean).join(' · '):(refs.diagnostics||[]).map(d=>`${d.code} · ${d.task_id} · ${d.resolved_path||d.original_path||''}`).join('；');
    return `<aside class="alert soft" data-catalog-reference-notice><strong>${unknown?'历史引用未核验':'已按可信任务证据核验引用'}</strong><p>${unknown?'普通编辑可用；删除和改挂暂不可用。':'历史任务路径或文件有缺失，原任务合同和引用保护保留。'}</p><details><summary>诊断详情</summary><p class="subline">${esc(details)}</p></details></aside>`;
  }
  function detailHtml(item,refs){
    const facts=item.capability?.resources||[];
    return `${referenceNotice(refs)}<h3>${esc(item.name)}</h3><dl class="catalog-detail"><dt>稳定 ID</dt><dd>${esc(item.id)}</dd><dt>状态</dt><dd>${item.enabled?'已启用':'已停用'}</dd><dt>SDK 目标</dt><dd>${esc(item.sdk_code||item.template_name||'待适配')}</dd><dt>业务引用</dt><dd>${refs?.reference_count??'未读取'}</dd></dl>${facts.map(f=>`<section class="catalog-resource-fact"><strong>${esc(f.resource_name)}</strong><span>${esc(({local:'本机',remote:'远程',agent:'Agent'})[f.mode]||f.mode)} · ${esc(f.sdk_version||'版本未知')}</span><p>${f.ready?'可用':'不可用'} · ${esc(f.allowed_precisions.join(' / ')||'无已确认精度')} · 支持芯片 ${esc((f.supported_chips||[]).join(' / ')||'未声明')}</p><p>${esc(f.message||'')}</p><p>${esc((f.errors||[]).map(e=>typeof e==='string'?e:e.message||e.code).join('；'))}</p><small>检测时间 ${esc(f.last_checked_at||'未记录')} · ${esc(f.solution)}</small></section>`).join('')||'<p class="subline">无匹配的转换资源。</p>'}`;
  }
  async function save(){
    if(!form||form.busy)return;
    const area=doc.querySelector('[data-catalog-dialog]'),node=area?.querySelector('form');if(!node||!node.reportValidity())return;
    const data=new FormData(node),record={name:String(data.get('name')).trim(),enabled:data.has('enabled')};
    if(form.entity==='vendors')record.template_id=form.mutableIdentity?data.get('template_id'):form.item.template_id;
    else{record.vendor_id=form.item.vendor_id;for(const key of ['code','sdk_code'])if(form.mutableIdentity)record[key]=String(data.get(key)||'').trim()}
    await mutate(form.id?'update':'create',record);
  }
  async function mutate(action,record){
    const current=form;if(!current||current.busy)return;
    current.busy=true;const stamp=epoch,area=doc.querySelector('[data-catalog-dialog]');
    area?.querySelectorAll('button,input,select').forEach(el=>el.disabled=true);
    const errorBox=area?.querySelector('[role="alert"]');
    const operation=current.operation||={entity:current.entity,action,operation_id:catalogOperationId(win.crypto),expected_revision:current.revision,...(current.id?{id:current.id}:{}),...(record?{record}:{}),...(action==='delete'?{confirm_delete:true}:{})};
    try{
      const result=await api(`${base}/operations`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(operation)});
      if(!live(stamp))return;
      if(form!==current){win.invalidateVersionConversionResources428?.();status('后台保存已完成，请刷新字典。');return}
      revision=result.revision;win.invalidateVersionConversionResources428?.();
      if(action==='create'&&current.entity==='vendors')selected=result.item?.id||result.id||selected;
      close();status(action==='delete'?'已物理删除':'已保存');await load('vendors');await load('chips');
    }catch(error){
      if(live(stamp)&&form===current&&errorBox){
        errorBox.textContent=`${error.code||'请求结果待确认'}：${error.message}${rejected(error.code)?'':'。请重试原操作以核验结果；当前表单保留原请求。'}`;
        // Definite validation rejection may be edited; unknown transport result retains exact request for safe replay.
        if(rejected(error.code))current.operation=null;
      }
    }finally{current.busy=false;if(form===current)area?.querySelectorAll('button,input,select').forEach(el=>el.disabled=(Boolean(current.operation)&&['INPUT','SELECT'].includes(el.tagName))||el.name==='id'||(Boolean(current.id)&&!current.mutableIdentity&&['template_id','code','sdk_code'].includes(el.name)))}
  }
  async function dialogAction(action){if(action==='confirm-delete')await mutate('delete');else if(action==='disable')await mutate('disable')}
  async function toggle(entity,id,action){
    const current=await open(entity,id,'edit');if(!current||form!==current||current.entity!==entity||current.id!==id)return;await mutate(action);
  }
  async function detect(id,button){
    const stamp=epoch;button.disabled=true;button.textContent='检测中…';
    try{
      const result=await api(`${base}/chips/${encodeURIComponent(id)}/detect`,{method:'POST',headers:{'Content-Type':'application/json'},body:'{}'});
      if(!live(stamp))return;win.invalidateVersionConversionResources428?.();await load('chips');
      if(!live(stamp))return;
      const row=rows.chips.find(r=>r.id===id);if(row&&!doc.querySelector('[data-catalog-dialog]'))show('芯片转换能力',detailHtml({...row,capability:result.capability})+'<button class="btn" data-catalog-action="cancel">关闭</button>');
    }catch(error){if(live(stamp))status(error.message,true)}finally{if(button.isConnected){button.disabled=false;button.textContent='检测转换能力'}}
  }
  async function onClick(event){
    const button=event.target.closest('[data-catalog-action]');if(!button||button.disabled)return;
    const {catalogAction:action,entity,id}=button.dataset;
    if(action==='select'){opening=null;selected=id;slot('vendor-title').textContent=rows.vendors.find(v=>v.id===id)?.name||'';root.querySelectorAll('[data-catalog-vendor]').forEach(row=>row.classList.toggle('selected',row.dataset.catalogVendor===id));queries.chips={page:1};return load('chips')}
    if(action==='refresh'){status('');return load('vendors',{selectFirst:true})}
    if(action==='page'){queries[entity].page=Number(button.dataset.page);return load(entity)}
    if(action==='new')return open(entity,'','edit');
    if(action==='detect')return detect(id,button);
    if(action==='enable'||action==='disable'){button.disabled=true;try{await toggle(entity,id,action)}finally{if(button.isConnected)button.disabled=false}return}
    if(['view','edit','delete'].includes(action)){button.disabled=true;try{await open(entity,id,action)}finally{if(button.isConnected)button.disabled=false}}
  }
  function leave(){epoch++;opening=null;life?.abort();if(doc.querySelector('[data-catalog-dialog]'))close();else releaseDialog();root=null;inflight.clear()}
  function mount(host){
    leave();root=host;project=getState().project?.id;life=new AbortController();selected='';queries.vendors={page:1};queries.chips={page:1};
    host.innerHTML=`<div class="panel-head"><div><div class="panel-title">厂商与芯片管理</div><div class="subline">本地转换字典</div></div><button class="btn" data-catalog-action="refresh">刷新字典</button></div><div class="panel-body"><p data-slot="notice" role="status"></p>${['vendors','chips'].map(entity=>`<section class="catalog-section"><div class="catalog-section-head"><h3>${entity==='vendors'?'厂商列表':'<span data-slot="vendor-title">请选择厂商</span> · 芯片型号'}</h3><button class="btn primary" data-catalog-action="new" data-entity="${entity}" ${entity==='chips'&&!selected?'disabled':''}>+ 新增${entity==='vendors'?'厂商':'芯片'}</button></div><form data-filter="${entity}" class="catalog-filters"><input class="input" type="search" name="${entity}-query" placeholder="搜索${entity==='vendors'?'厂商名称':'芯片型号'}" aria-label="搜索${entity==='vendors'?'厂商':'芯片'}">${entity==='vendors'?'<select class="select" name="vendors-template_id" aria-label="SDK 模板筛选"><option value="">全部 SDK 模板</option></select>':''}<select class="select" name="${entity}-enabled" aria-label="${entity}启停筛选"><option value="">全部状态</option><option value="true">已启用</option><option value="false">已停用</option></select><select class="select" name="${entity}-sort" aria-label="${entity}排序"><option value="name">名称升序</option><option value="name_desc">名称降序</option><option value="id">稳定 ID</option></select><button class="btn" type="submit">查询</button></form><div class="catalog-table-wrap"><table class="catalog-table"><thead><tr>${(entity==='vendors'?['厂商名称','SDK 模板','芯片 / 已启用','转换适配','状态','操作']:['芯片型号','SDK 目标','支持精度','资源 / SDK 版本','状态','操作']).map(title=>`<th>${title}</th>`).join('')}</tr></thead><tbody data-slot="${entity}"><tr><td colspan="6">加载中…</td></tr></tbody></table></div><div class="catalog-pager" data-slot="${entity}-pager"></div></section>`).join('')}</div>`;
    host.addEventListener('click',onClick,{signal:life.signal});
    host.addEventListener('submit',event=>{const filter=event.target.closest('[data-filter]');if(!filter)return;event.preventDefault();const entity=filter.dataset.filter;queries[entity]={page:1};for(const [key,value]of new FormData(filter))queries[entity][key.slice(entity.length+1)]=value;void load(entity)},{signal:life.signal});
    return load('vendors',{selectFirst:true});
  }
  const runtime={mount,leave};
  win.conversionCatalogRuntime=runtime;
  win.openConversionCatalog428=()=>{const host=doc.querySelector('#conversion-catalog-host');host?.scrollIntoView({behavior:'smooth',block:'start'});host?.focus()};
  return runtime;
}
export function catalogOperationId(crypto){
  if(crypto?.randomUUID)return `catalog-${crypto.randomUUID()}`;
  const bytes=new Uint8Array(16);crypto.getRandomValues(bytes);return 'catalog-'+Array.from(bytes,n=>n.toString(16).padStart(2,'0')).join('');
}
