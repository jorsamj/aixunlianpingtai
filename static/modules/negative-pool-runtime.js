export function negativePoolReviewItems(records) {
  return records.map(record=>{
    const annotation=record.annotation||{}, image=record.image||{};
    const hash=String(image.content_sha256||'');
    if(!image.id||!Number.isInteger(annotation.version)||!/^[a-f0-9]{64}$/.test(hash))throw Error('图片摘要或标注版本缺失，请刷新后重试');
    return {image_id:String(image.id),expected_version:annotation.version,source_content_sha256:hash};
  });
}
export function negativePoolQuery(filters = {}, page = 1) {
  const q = new URLSearchParams({page: String(page), page_size: '48'});
  for (const key of ['algorithm_id','query','joined_days','joined_from','joined_to','review_status']) if (filters[key]) q.set(key, filters[key]);
  for (const key of ['category_id','label','target_label']) for (const value of filters[key] || []) q.append(key,value);
  return q;
}
export function installNegativePoolRuntime({getState,api,pid,esc,toast,modal,closeModal,addToDraft} = {}) {
  if (window.NegativePoolRuntime) return window.NegativePoolRuntime;
  let project='', active='materials', labelTab='positive', page=1, total=0, rows=[], categories=[], filters={}, selected=new Set(), epoch=0;
  let activeRead=null, categoryRevision=0, materialActionsObserver=null, materialActionsHost=null, materialActionsQueued=false;
  const categoryCache=new Map(), categoryFlights=new Map();
  const CATEGORY_TTL_MS=60*1000;
  function invalidateCategories(){categoryRevision++;categoryCache.clear();categoryFlights.clear()}
  function categoriesFor(kind,projectId){
    const q=kind==='categories'?String(filters.categoryQuery||''):'';
    const key=JSON.stringify([projectId,q]);
    const cached=categoryCache.get(key);
    if(cached&&Date.now()-cached.at<CATEGORY_TTL_MS)return Promise.resolve(cached.data);
    const flight=categoryFlights.get(key);
    if(flight)return flight;
    const revision=categoryRevision;
    const url=base()+'/categories'+(q?'?query='+encodeURIComponent(q):'');
    let promise;
    promise=Promise.resolve().then(()=>api(url)).then(data=>{
      if(projectId===String(pid())&&revision===categoryRevision)categoryCache.set(key,{data,at:Date.now()});
      return data;
    }).finally(()=>{if(categoryFlights.get(key)===promise)categoryFlights.delete(key)});
    categoryFlights.set(key,promise);
    return promise;
  }
  const view=()=>document.getElementById('view');
  const base=()=>`/api/v61/projects/${encodeURIComponent(pid())}/negative-pool`;
  const reviewName=value=>({annotated:'已标注',unannotated:'待标注',confirmed_empty:'已确认空图',stale:'审核已过期',unknown:'未知 / 未核验'}[value]||'未知 / 未核验');
  const usageName=value=>{if(!value||value==='unknown')return '未知';if(typeof value==='string')return value;return [value.current_algorithm_trained?'当前算法已使用':'',value.other_algorithm_trained?'其他算法已使用':'',({used:'已参与训练',possible:'可能已参与训练',selected:'仅被选入任务',eval_only:'仅用于评估',unused:'有据未使用',unknown:'历史未知'})[value.state]||'历史未知'].filter(Boolean).join(' · ')||'未知'};
  const button=(action,text,extra='')=>`<button type="button" class="btn" data-np="${action}" ${extra}>${text}</button>`;
  const err=e=>toast(e.message||String(e));
  function resetProject(){if(project!==String(pid())){
    activeRead?.controller.abort();activeRead=null;invalidateCategories();
    project=String(pid());active='materials';labelTab='positive';filters={};selected.clear();page=1;epoch++;
  }}
  function tabs(kind){const pool=kind==='materials';return `<nav class="negative-pool-tabs" aria-label="${pool?'素材管理':'标签管理'}">${button(pool?'materials':'positive',pool?'训练素材':'正样本标签',`aria-pressed="${pool?active==='materials':labelTab==='positive'}"`)}${button(pool?'pool':'categories',pool?'负样本池':'负样本分类',`aria-pressed="${pool?active==='pool':labelTab==='categories'}"`)}</nav>`}
  function current(token,host,projectId,kind){return token===epoch&&host===view()&&host.isConnected&&String(pid())===projectId&&getState().page===(kind==='pool'?'数据集':'标签管理')&&(kind==='pool'?active==='pool':labelTab==='categories')}
  function selectionText(){const el=document.getElementById('negativePoolSelection');if(el)el.textContent=`已选 ${selected.size} 张（跨页保留）`}
  function syncSelection(){
    view()?.querySelectorAll?.('[data-np-select]').forEach(box=>{
      box.checked=selected.has(String(box.dataset.npSelect));
    });
    selectionText();
  }
  function load(kind){
    resetProject();
    const host=view();if(!host)return Promise.resolve(null);
    const projectId=String(pid());
    const listUrl=kind==='pool'?base()+'?'+negativePoolQuery(filters,page):'';
    const queryKey=JSON.stringify([projectId,kind,listUrl,kind==='categories'?filters.categoryQuery||'':'']);
    if(activeRead?.key===queryKey&&activeRead.host===host)return activeRead.promise;
    activeRead?.controller.abort();
    const controller=new AbortController(),token=++epoch;
    host.innerHTML=tabs(kind==='pool'?'materials':'labels')+'<section class="panel negative-pool"><div role="status">正在读取…</div></section>';
    let promise;
    promise=(async()=>{
      try{
        const [cats,data]=await Promise.all([
          categoriesFor(kind,projectId),
          kind==='pool'?api(listUrl,{signal:controller.signal}):Promise.resolve(null)
        ]);
        if(controller.signal.aborted||!current(token,host,projectId,kind))return;
        categories=cats.items||[];
        if(data){rows=data.items||[];total=Number(data.total||0);if(data.scope_kind==='algorithm_contract')filters.target_label=data.effective_label_codes||[];}
        host.innerHTML=tabs(kind==='pool'?'materials':'labels')+(kind==='pool'?poolHTML():categoryHTML());
        if(kind==='pool')host.querySelector('[data-np="join"]')?.insertAdjacentHTML('afterend',button('upload','上传到负样本池'));
      }catch(e){
        if(!controller.signal.aborted&&current(token,host,projectId,kind)){
          host.innerHTML=tabs(kind==='pool'?'materials':'labels')
            +`<section class="panel negative-pool"><div class="alert err" role="alert">${esc(e.message||e)}</div>${button('retry','重试')}</section>`;
        }
      }finally{if(activeRead?.promise===promise)activeRead=null}
    })();
    activeRead={key:queryKey,host,controller,promise};
    return promise;
  }
  const options=(values,chosen=[])=>values.map(x=>`<option value="${esc(x.id)}" ${chosen.includes(String(x.id))?'selected':''}>${esc(x.name)}</option>`).join('');
  function poolHTML(){
    const labels=(getState().labels||[]).map(x=>typeof x==='string'?{id:x,name:x}:{id:x.code||x.name,name:x.display_name||x.code||x.name});
    return `<section class="panel negative-pool"><header class="row between"><div><h2>负样本池</h2><p>按算法管理，审核后用于训练。</p></div>${button('join','加入已有素材')}</header><form data-np-form="filters" class="negative-pool-filters"><label>目标算法<select class="select" name="algorithm_id"><option value="">项目历史池（未指定算法）</option>${options(getState().algorithms||[],filters.algorithm_id?[filters.algorithm_id]:[])}</select></label><label>目标范围<select class="select" name="target_label" multiple ${rows.some(row=>row.negative_pool?.scope_kind==='algorithm_contract')?'disabled':''}>${options(labels,filters.target_label)}</select></label><label>名称 / 文件名 / ID<input class="input" name="query" value="${esc(filters.query||'')}" placeholder="搜索素材"></label><details class="negative-pool-advanced"><summary>高级筛选</summary><div class="negative-pool-advanced-fields"><label>负样本分类（多选）<select class="select" name="category_id" multiple>${options(categories,filters.category_id)}</select></label><label>原有目标标签（多选）<select class="select" name="label" multiple>${options(labels,filters.label)}</select></label><label>加入时间<select class="select" name="joined_days"><option value="">全部时间</option><option value="7" ${filters.joined_days==='7'?'selected':''}>最近 7 天</option><option value="30" ${filters.joined_days==='30'?'selected':''}>最近 30 天</option></select></label><label>起始日期<input class="input" name="joined_from" type="date" value="${esc(filters.joined_from||'')}"></label><label>截止日期<input class="input" name="joined_to" type="date" value="${esc(filters.joined_to||'')}"></label><label>审核状态<select class="select" name="review_status"><option value="">全部状态</option>${['unannotated','annotated','confirmed_empty','stale','unknown'].map(status=>`<option value="${status}" ${filters.review_status===status?'selected':''}>${reviewName(status)}</option>`).join('')}</select></label></div></details><button class="btn primary" type="submit">筛选</button>${button('reset','重置')}</form><div class="row negative-pool-tools"><span id="negativePoolSelection">已选 ${selected.size} 张（跨页保留）</span>${button('page-select','选中本页')}${button('all-select','全选当前筛选结果')}<details class="negative-pool-more"><summary>更多操作</summary><div>${button('clear','取消全选')}${button('assign','批量设置分类')}${button('unassign','批量移除分类')}${button('remove','移出负样本池')}</div></details><div class="negative-pool-primary-actions">${button('review','确认无本算法目标')}${button('draft','加入训练草稿')}</div></div><div class="negative-pool-grid">${rows.map(row=>{const id=String(row.id),pool=row.negative_pool||{};return `<article class="negative-pool-card"><label class="row"><input type="checkbox" data-np-select="${esc(id)}" ${selected.has(id)?'checked':''}><b>${esc(row.filename||row.name||id)}</b></label><div class="negative-pool-preview" data-np="preview" data-id="${esc(id)}">${window.materialMedia412?.(row,true)||`<img src="${esc(row.thumbnail_url||row.url||'')}" loading="lazy" alt="${esc(row.filename||id)}">`}<button type="button" class="btn mini" data-np="preview" data-id="${esc(id)}" aria-label="查看 ${esc(row.filename||id)}">查看详情</button></div><div class="negative-pool-meta"><strong class="negative-pool-qualification">${esc(({confirmed_for_requested_scope:'已确认所选范围',pending_confirmation:'待确认',target_present:'含目标',needs_review:'需复核'})[pool.qualification]||'待确认')}</strong><details><summary>来源与审核详情</summary><div class="negative-pool-detail"><span>${esc((pool.categories||[]).map(c=>c.name+(c.enabled===false?'（已停用）':'')).join('、')||'未分类')}</span><span>原标签：${esc((row.labels||[]).join('、')||'无')}</span><span>加入：${esc(pool.joined_at||'未知')}</span><span>资格：${esc(({confirmed_for_requested_scope:'已确认所选范围',pending_confirmation:'待确认',target_present:'含目标',needs_review:'需复核'})[pool.qualification]||'待确认')}</span><span>审核：${esc(reviewName(pool.review_status))}（不代表本次目标已确认无目标）</span><span>训练使用：${esc(usageName(pool.training_usage))}</span><small>${esc(id)}</small></div></details></div></article>`}).join('')||'<div class="empty">当前筛选没有素材</div>'}</div><footer class="row end">共 ${total} 张 · 第 ${page} / ${Math.max(1,Math.ceil(total/48))} 页 ${button('prev','上一页',page<=1?'disabled':'')}${button('next','下一页',page*48>=total?'disabled':'')}</footer></section>`;
  }
  function categoryHTML(){return `<section class="panel negative-pool"><header class="row between"><div><h2>负样本分类</h2><p>一级管理分类，不参与目标检测类别映射。删除分类只移除关联。</p></div>${button('create-category','新建分类')}</header><form class="row" data-np-form="category-search"><input class="input" name="query" placeholder="搜索分类" value="${esc(filters.categoryQuery||'')}"><button class="btn" type="submit">搜索</button></form><div class="negative-pool-category-list">${categories.map(c=>`<article class="row between"><div><b>${esc(c.name)}</b> · ${Number(c.material_count||0)} 张 · ${c.enabled?'启用':'停用'}</div><div class="row">${button('edit-category','编辑',`data-id="${esc(c.id)}"`)}${button('toggle-category',c.enabled?'停用':'启用',`data-id="${esc(c.id)}"`)}${button('delete-category','删除',`data-id="${esc(c.id)}"`)}</div></article>`).join('')||'<div class="empty">暂无分类</div>'}</div></section>`}
  function dialog(title,body,submit){const projectId=String(pid()),originPage=getState().page;const layer=modal(title,`<form id="negativePoolDialog" class="negative-pool-dialog">${body}<div class="row end"><button type="button" class="btn" data-np-cancel>取消</button><button class="btn primary" type="submit">确认</button></div><div role="alert" data-np-error></div></form>`,true);const form=document.getElementById('negativePoolDialog');form.querySelector('[data-np-cancel]').onclick=()=>window.closeModalLayer424(layer);form.onsubmit=async e=>{e.preventDefault();const btn=form.querySelector('[type=submit]');btn.disabled=true;try{if(String(pid())!==projectId)throw Error('项目已变化，请重新操作');await submit(new FormData(form));if(!form.isConnected||String(pid())!==projectId)return;window.closeModalLayer424(layer);if(getState().page===originPage){if(originPage==='标签管理')await window.renderLabelManagement414();else if(originPage==='数据集')await window.renderDatasets424()}}catch(error){if(form.isConnected)form.querySelector('[data-np-error]').textContent=error.message||String(error)}finally{if(form.isConnected)btn.disabled=false}}}
  const write=async(path,body,method='POST')=>{
    if(path==='/members'&&body&&filters.algorithm_id&&!Object.hasOwn(body,'algorithm_id'))body={...body,algorithm_id:filters.algorithm_id};
    const result=await api(base()+path,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
    if(path.startsWith('/categories')||path.startsWith('/members'))invalidateCategories();
    return result;
  };
  function browseMaterials(){
    const projectId=String(pid()),algorithmId=String(filters.algorithm_id||'');let pageNo=1,requestId=0;const chosen=new Set();
    const layer=modal('从素材库加入负样本池',`<form id="negativePoolBrowse" class="negative-pool-dialog"><div class="row"><input class="input" name="query" placeholder="搜索文件名 / 素材 ID"><button type="button" class="btn" data-np-search>搜索</button></div><div data-np-browse-list role="status">正在读取素材…</div><div class="row between"><span data-np-browse-count>已选 0 张</span><div class="row"><button type="button" class="btn" data-np-prev>上一页</button><span data-np-page></span><button type="button" class="btn" data-np-next>下一页</button></div></div><div class="row end"><button type="button" class="btn" data-np-cancel>取消</button><button type="submit" class="btn primary">加入所选素材</button></div><div role="alert" data-np-error></div></form>`,true);
    const form=layer?.querySelector?.('#negativePoolBrowse')||document.getElementById('negativePoolBrowse');
    if(!form)return;
    const list=form.querySelector('[data-np-browse-list]'),count=form.querySelector('[data-np-browse-count]');
    let pages=1;
    const sync=()=>{count.textContent=`已选 ${chosen.size} 张（跨页保留）`;list.querySelectorAll('[data-np-image]').forEach(box=>{box.checked=chosen.has(box.dataset.npImage)})};
    async function loadPage(){
      const own=++requestId,query=String(new FormData(form).get('query')||'').trim();
      list.textContent='正在读取素材…';
      try{
        const queryString=new URLSearchParams({page:String(pageNo),page_size:'24',query});
        const data=await api(`/api/v61/projects/${encodeURIComponent(projectId)}/materials?${queryString}`);
        if(own!==requestId||!form.isConnected||String(pid())!==projectId)return;
        pages=Math.max(1,Number(data.total_pages)||1);
        list.innerHTML=`<div class="negative-pool-browse-grid">${(data.items||[]).map(row=>`<label class="negative-pool-browse-card"><input type="checkbox" data-np-image="${esc(row.id)}" ${chosen.has(String(row.id))?'checked':''}><img src="${esc(row.thumbnail_url||row.url||'')}" loading="lazy" alt=""><b title="${esc(row.filename||'')}">${esc(row.filename||row.id)}</b><small>原标签：${esc((row.labels||[]).join('、')||'无')}</small></label>`).join('')||'<p>没有符合条件的素材</p>'}</div>`;
        form.querySelector('[data-np-page]').textContent=`${pageNo} / ${pages}`;
        form.querySelector('[data-np-prev]').disabled=pageNo<=1;
        form.querySelector('[data-np-next]').disabled=pageNo>=pages;
        sync();
      }catch(error){if(own===requestId&&form.isConnected)list.textContent=error.message||String(error)}
    }
    form.querySelector('[data-np-cancel]').onclick=()=>window.closeModalLayer424(layer);
    form.querySelector('[data-np-search]').onclick=()=>{pageNo=1;void loadPage()};
    form.querySelector('[data-np-prev]').onclick=()=>{pageNo=Math.max(1,pageNo-1);void loadPage()};
    form.querySelector('[data-np-next]').onclick=()=>{pageNo=Math.min(pages,pageNo+1);void loadPage()};
    form.querySelector('[name="query"]').onkeydown=e=>{if(e.key==='Enter'){e.preventDefault();pageNo=1;void loadPage()}};
    form.addEventListener('change',e=>{if(e.target.matches?.('[data-np-image]')){e.target.checked?chosen.add(e.target.dataset.npImage):chosen.delete(e.target.dataset.npImage);sync()}});
    form.onsubmit=async e=>{e.preventDefault();const submit=form.querySelector('[type=submit]');submit.disabled=true;
      try{if(!chosen.size)throw Error('请先选择素材');if(String(pid())!==projectId)throw Error('项目已变化，请重新操作');
        await write('/members',{image_ids:[...chosen],action:'add',algorithm_id:algorithmId});
        if(!form.isConnected)return;window.closeModalLayer424(layer);toast(`已将 ${chosen.size} 张素材加入负样本池`);if(getState().page==='数据集')await window.renderDatasets424();
      }catch(error){if(form.isConnected)form.querySelector('[data-np-error]').textContent=error.message||String(error)}finally{if(form.isConnected)submit.disabled=false}};
    void loadPage();
  }
  function requireSelection(){if(!selected.size)throw Error('请先选择素材');return [...selected]}
  async function action(name,id){resetProject();
    if(['materials','pool'].includes(name)){active=name;return window.renderDatasets424()}
    if(['positive','categories'].includes(name)){labelTab=name;return window.renderLabelManagement414()}
    if(name==='retry')return load(getState().page==='标签管理'?'categories':'pool');
    if(name==='reset'){filters={};page=1;return load('pool')}
    if(name==='prev'||name==='next'){page+=name==='prev'?-1:1;return load('pool')}
    if(name==='preview')return window.previewData429(id,rows.find(x=>String(x.id)===id));
    if(name==='clear'){selected.clear();syncSelection();return}
    if(name==='page-select'){rows.forEach(x=>selected.add(String(x.id)));syncSelection();return}
    if(name==='all-select'){const token=epoch,projectId=String(pid()),result=await api(base()+'/ids?'+negativePoolQuery(filters));if(token!==epoch||String(pid())!==projectId||active!=='pool'||getState().page!=='数据集')return;selected=new Set((result.items||[]).map(String));syncSelection();return}
    if(name==='review'){
      const ids=requireSelection(),algorithmId=String(filters.algorithm_id||''),projectId=String(pid());
      if(!algorithmId)throw Error('请先选择目标算法并筛选');
      if(ids.length>50)throw Error('每批最多审核 50 张，请缩小所选范围');
      const labels=(getState().labels||[]).map(x=>typeof x==='string'?{id:x,name:x}:{id:x.code||x.name,name:x.display_name||x.code||x.name});
      dialog('确认无本算法目标',`<label>本算法目标范围<select class="select" name="target_labels" multiple required ${rows.some(row=>row.negative_pool?.scope_kind==='algorithm_contract')?'disabled':''}>${options(labels,filters.target_label)}</select></label><p>请先逐图查看所选 ${ids.length} 张图片。确认后保存原正式审核证据，保留其他类别标注。</p><label><input type="checkbox" name="reviewed" required>我已逐图核实，不含上述目标</label>`,async data=>{
        const codes=rows.some(row=>row.negative_pool?.scope_kind==='algorithm_contract')?[...(filters.target_label||[])]:data.getAll('target_labels');if(!codes.length||!data.get('reviewed'))throw Error('请选择目标并明确确认');
        const records=[];for(const id of ids)records.push(await api(`/api/projects/${encodeURIComponent(projectId)}/annotations/${encodeURIComponent(id)}`));
        if(String(pid())!==projectId||filters.algorithm_id!==algorithmId)throw Error('算法或项目已变化，请重新审核');
        const result=await api(`/api/v62/projects/${encodeURIComponent(projectId)}/training-materials/review-negative`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({algorithm_asset_id:algorithmId,train_labels:codes,confirmed:true,items:negativePoolReviewItems(records)})});
        if(result.failures?.length)throw Error(`已确认 ${result.succeeded?.length||0} 张，失败 ${result.failures.length} 张：${result.failures[0].message}`);
        toast(`已确认 ${result.succeeded?.length||0} 张；训练时按冻结目标再次核验`);
      });return;
    }
    if(name==='draft'){const ids=requireSelection();if(!addToDraft)throw Error('请先打开原创建训练窗口建立训练草稿');await addToDraft(ids);toast(`已将 ${ids.length} 张素材加入训练草稿`);return}
    if(name==='join'){browseMaterials();return}
    if(name==='upload'){
      const uploadProject=String(pid()),uploadAlgorithm=String(filters.algorithm_id||'');
      let stagedIds=[];
      dialog('上传到负样本池','<label>选择图片（支持批量）<input class="input" name="files" type="file" accept="image/*,.zip" multiple required></label><p>原图先进入统一素材库，再加入负样本池；不修改任何已有标签。上传失败的图片不会加入池。</p><div data-np-upload-progress role="status"></div>',async data=>{
        if(!stagedIds.length){
          const files=data.getAll('files').filter(file=>file?.size>0);
          if(!files.length)throw Error('请先选择图片');
          const archives=files.filter(file=>/\.zip$/i.test(file.name));
          if(archives.length){
            if(!uploadAlgorithm)throw Error('上传 ZIP 到池前请先选择目标算法');
            if(archives.length!==files.length)throw Error('ZIP 与图片请分批上传');
            if(!window.ZipImportRuntime?.uploadBatch)throw Error('ZIP 导入尚未就绪，请稍后重试');
            closeModal?.();
            await window.ZipImportRuntime.uploadBatch({files:archives,value:'',externalView:true,negativePoolAlgorithmId:uploadAlgorithm});
            toast('ZIP 已交由原导入任务处理，请确认负样本分类后入池');return;
          }
          const body=new FormData();files.forEach(file=>body.append('files',file));body.append('dataset_id','default');
          const status=document.querySelector('#negativePoolDialog [data-np-upload-progress]');
          const upload=await api(`/api/projects/${encodeURIComponent(uploadProject)}/images`,{method:'POST',body,
            onUploadProgress:progress=>{if(status&&status.isConnected&&progress.total)status.textContent=`已上传 ${Math.round(progress.loaded/progress.total*100)}%`}});
          stagedIds=(upload.uploaded_image_ids||upload.uploaded||[]).map(item=>String(item?.id||item)).filter(Boolean);
          if(!stagedIds.length)throw Error('没有成功导入的新图片，请检查重复图片或上传失败记录');
          if(status?.isConnected)status.textContent=`已上传 ${stagedIds.length} 张，正在加入负样本池…`;
        }
        if(String(pid())!==uploadProject)throw Error('项目在上传期间已切换；图片已保存在原项目素材库，请返回原项目加入负样本池');
        await write('/members',{image_ids:stagedIds,action:'add',algorithm_id:uploadAlgorithm});
        toast(`已上传并加入负样本池 ${stagedIds.length} 张`);
      });return;
    }
    if(name==='join-one'){await write('/members',{image_ids:[id],action:'add'});toast('已加入负样本池');return}
    if(name==='remove'){const ids=requireSelection();dialog('移出负样本池',`<p>移出所选 ${ids.length} 张素材，原图与标注保留。</p>`,async()=>{await write('/members',{image_ids:ids,action:'remove'});ids.forEach(x=>selected.delete(x))});return}
    if(name==='assign'||name==='unassign'){const ids=requireSelection();dialog(name==='assign'?'设置分类':'移除分类',`<label>分类（多选）<select class="select" multiple name="category_ids" required>${options(categories.filter(c=>name==='unassign'||c.enabled))}</select></label><p>仅更新分类关联，保留正式标注。</p>`,data=>write('/categories/assign',{image_ids:ids,category_ids:data.getAll('category_ids'),action:name==='assign'?'set':'remove'}));return}
    const category=categories.find(x=>String(x.id)===id);
    if(name==='create-category'||name==='edit-category'){dialog(name==='create-category'?'新建负样本分类':'编辑负样本分类',`<label>分类名称<input class="input" name="name" required maxlength="100" value="${esc(category?.name||'')}"></label>`,data=>write(category?'/categories/'+encodeURIComponent(id):'/categories',{name:String(data.get('name')).trim()},category?'PATCH':'POST'));return}
    if(name==='toggle-category'){await write('/categories/'+encodeURIComponent(id),{enabled:!category.enabled},'PATCH');return load('categories')}
    if(name==='delete-category'){dialog('删除分类',`<p>删除“${esc(category.name)}”及其分类关联，素材本身保留。</p>`,()=>write('/categories/'+encodeURIComponent(id),null,'DELETE'));return}
  }
  document.addEventListener('click',e=>{const target=e.target.closest?.('[data-np]');if(!target)return;e.preventDefault();e.stopPropagation();if(target.disabled)return;target.disabled=true;Promise.resolve(action(target.dataset.np,target.dataset.id)).catch(err).finally(()=>{if(target.isConnected)target.disabled=false})});
  document.addEventListener('change',e=>{if(e.target.matches?.('[data-np-select]')){const id=e.target.dataset.npSelect;e.target.checked?selected.add(id):selected.delete(id);selectionText()}});
  document.addEventListener('submit',e=>{const kind=e.target.dataset?.npForm;if(!kind)return;e.preventDefault();const data=new FormData(e.target);if(kind==='category-search'){filters.categoryQuery=String(data.get('query')||'');void load('categories');return}filters=Object.fromEntries(['algorithm_id','query','joined_days','joined_from','joined_to','review_status'].map(key=>[key,String(data.get(key)||'')]));filters.category_id=data.getAll('category_id');filters.label=data.getAll('label');filters.target_label=data.getAll('target_label');selected.clear();page=1;void load('pool')});
  // Card owners can replace .data426-actions after async annotation refresh.
  // Keep one observer on the current view, rather than competing HTML owners.
  function repairMaterialActions(host){
    if(!host||host!==view()||getState().page!=='数据集'||active!=='materials')return;
    host.querySelectorAll?.('[data-material-id]').forEach(card=>{
      const actions=card.querySelector('.data426-actions');
      if(actions&&!actions.querySelector('[data-np="join-one"]'))
        actions.insertAdjacentHTML('beforeend',button('join-one','加入负样本池',`data-id="${esc(card.dataset.materialId)}"`));
    });
  }
  function disconnectMaterialActions(){
    materialActionsObserver?.disconnect();materialActionsObserver=null;materialActionsHost=null;materialActionsQueued=false;
  }
  function watchMaterialActions(host){
    if(typeof MutationObserver!=='function'||!host?.isConnected)return;
    if(materialActionsHost===host)return;
    disconnectMaterialActions();
    materialActionsHost=host;
    materialActionsObserver=new MutationObserver(()=>{
      if(materialActionsQueued)return;
      materialActionsQueued=true;
      queueMicrotask(()=>{
        materialActionsQueued=false;
        if(host!==view()||getState().page!=='数据集'||active!=='materials'){
          disconnectMaterialActions();return;
        }
        repairMaterialActions(host);
      });
    });
    materialActionsObserver.observe(host,{subtree:true,childList:true});
  }
  function decorateOriginal(kind){
    resetProject();
    if((kind==='materials'&&active==='pool')||(kind==='labels'&&labelTab==='categories'))return;
    epoch++;
    const host=view();if(!host)return;
    if(!host.querySelector('.negative-pool-tabs'))host.insertAdjacentHTML('afterbegin',tabs(kind));
    if(kind==='materials'){
      repairMaterialActions(host);
      watchMaterialActions(host);
    }else disconnectMaterialActions();
  }
  window.NegativePoolRuntime={
    renderTabs:tabs,
    active(kind){resetProject();return kind==='materials'?active==='pool':labelTab==='categories'},
    renderPool:kind=>load(kind==='materials'?'pool':'categories'),
    decorateOriginal,
    refresh:()=>load(getState().page==='标签管理'?'categories':'pool'),
    beforeNavigate(nextPage){
      if(nextPage!=='数据集')disconnectMaterialActions();
      const owner=active==='pool'?'数据集':labelTab==='categories'?'标签管理':null;
      if(owner&&nextPage!==owner){
        activeRead?.controller.abort();activeRead=null;epoch++;
      }
    },
    open:()=>action('pool'),getSelected:()=>[...selected]
  };
  return window.NegativePoolRuntime;
}
