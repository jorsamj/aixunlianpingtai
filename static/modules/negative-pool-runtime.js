export function negativePoolQuery(filters = {}, page = 1) {
  const q = new URLSearchParams({page: String(page), page_size: '48'});
  for (const key of ['query','joined_days','joined_from','joined_to','review_status']) if (filters[key]) q.set(key, filters[key]);
  for (const key of ['category_id','label']) for (const value of filters[key] || []) q.append(key,value);
  return q;
}
export function installNegativePoolRuntime({getState,api,pid,esc,toast,modal,closeModal,addToDraft} = {}) {
  if (window.NegativePoolRuntime) return window.NegativePoolRuntime;
  let project='', active='materials', labelTab='positive', page=1, total=0, rows=[], categories=[], filters={}, selected=new Set(), epoch=0;
  const view=()=>document.getElementById('view');
  const base=()=>`/api/v61/projects/${encodeURIComponent(pid())}/negative-pool`;
  const reviewName=value=>({annotated:'已标注',unannotated:'待标注',confirmed_empty:'已确认空图',stale:'审核已过期',unknown:'未知 / 未核验'}[value]||'未知 / 未核验');
  const usageName=value=>{if(!value||value==='unknown')return '未知';if(typeof value==='string')return value;return [value.current_algorithm_trained?'当前算法已使用':'',value.other_algorithm_trained?'其他算法已使用':'',value.state||''].filter(Boolean).join(' · ')||'未知'};
  const button=(action,text,extra='')=>`<button type="button" class="btn" data-np="${action}" ${extra}>${text}</button>`;
  const err=e=>toast(e.message||String(e));
  function resetProject(){if(project!==String(pid())){project=String(pid());active='materials';labelTab='positive';filters={};selected.clear();page=1;epoch++}}
  function tabs(kind){const pool=kind==='materials';return `<nav class="negative-pool-tabs" aria-label="${pool?'素材管理':'标签管理'}">${button(pool?'materials':'positive',pool?'训练素材':'正样本标签',`aria-pressed="${pool?active==='materials':labelTab==='positive'}"`)}${button(pool?'pool':'categories',pool?'负样本池':'负样本分类',`aria-pressed="${pool?active==='pool':labelTab==='categories'}"`)}</nav>`}
  function current(token,host,projectId,kind){return token===epoch&&host===view()&&host.isConnected&&String(pid())===projectId&&getState().page===(kind==='pool'?'数据集':'标签管理')&&(kind==='pool'?active==='pool':labelTab==='categories')}
  function selectionText(){const el=document.getElementById('negativePoolSelection');if(el)el.textContent=`已选 ${selected.size} 张（跨页保留）`}
  async function load(kind){
    const token=++epoch, host=view(), projectId=String(pid());
    host.innerHTML=tabs(kind==='pool'?'materials':'labels')+'<section class="panel negative-pool"><div role="status">正在读取…</div></section>';
    try{
      const [cats,data]=await Promise.all([api(base()+'/categories'+(kind==='categories'&&filters.categoryQuery?'?query='+encodeURIComponent(filters.categoryQuery):'')),kind==='pool'?api(base()+'?'+negativePoolQuery(filters,page)):Promise.resolve(null)]);
      if(!current(token,host,projectId,kind))return;
      categories=cats.items||[];
      if(data){rows=data.items||[];total=Number(data.total||0)}
      host.innerHTML=tabs(kind==='pool'?'materials':'labels')+(kind==='pool'?poolHTML():categoryHTML());
    }catch(e){if(current(token,host,projectId,kind))host.innerHTML=tabs(kind==='pool'?'materials':'labels')+`<section class="panel negative-pool"><div class="alert err" role="alert">${esc(e.message||e)}</div>${button('retry','重试')}</section>`}
  }
  const options=(values,chosen=[])=>values.map(x=>`<option value="${esc(x.id)}" ${chosen.includes(String(x.id))?'selected':''}>${esc(x.name)}</option>`).join('');
  function poolHTML(){
    const labels=(getState().labels||[]).map(x=>typeof x==='string'?{id:x,name:x}:{id:x.code||x.name,name:x.display_name||x.code||x.name});
    return `<section class="panel negative-pool"><header class="row between"><div><h2>负样本池</h2><p>池成员不等于已审核负样本；训练角色按本次目标与审核证据判断。</p></div>${button('join','加入已有素材')}</header><form data-np-form="filters" class="negative-pool-filters"><label>名称 / 文件名 / ID<input class="input" name="query" value="${esc(filters.query||'')}" placeholder="搜索素材"></label><label>负样本分类（多选）<select class="select" name="category_id" multiple>${options(categories,filters.category_id)}</select></label><label>原有目标标签（多选）<select class="select" name="label" multiple>${options(labels,filters.label)}</select></label><label>加入时间<select class="select" name="joined_days"><option value="">全部时间</option><option value="7" ${filters.joined_days==='7'?'selected':''}>最近 7 天</option><option value="30" ${filters.joined_days==='30'?'selected':''}>最近 30 天</option></select></label><label>起始日期<input class="input" name="joined_from" type="date" value="${esc(filters.joined_from||'')}"></label><label>截止日期<input class="input" name="joined_to" type="date" value="${esc(filters.joined_to||'')}"></label><label>审核状态<select class="select" name="review_status"><option value="">全部状态</option>${['unannotated','annotated','confirmed_empty','stale','unknown'].map(status=>`<option value="${status}" ${filters.review_status===status?'selected':''}>${reviewName(status)}</option>`).join('')}</select></label><button class="btn primary" type="submit">筛选</button>${button('reset','重置')}</form><div class="row negative-pool-tools">${button('page-select','选中本页')}${button('all-select','全选当前筛选结果')}${button('clear','取消全选')}<span id="negativePoolSelection">已选 ${selected.size} 张（跨页保留）</span>${button('assign','批量设置分类')}${button('unassign','批量移除分类')}${button('remove','移出负样本池')}${button('draft','加入训练草稿')}</div><div class="negative-pool-grid">${rows.map(row=>{const id=String(row.id),pool=row.negative_pool||{};return `<article class="negative-pool-card"><label class="row"><input type="checkbox" data-np-select="${esc(id)}" ${selected.has(id)?'checked':''}><b>${esc(row.filename||row.name||id)}</b></label><button class="negative-pool-preview" data-np="preview" data-id="${esc(id)}" aria-label="查看 ${esc(row.filename||id)}">${window.materialMedia412?.(row,true)||`<img src="${esc(row.thumbnail_url||row.url||'')}" loading="lazy" alt="${esc(row.filename||id)}">`}</button><div class="negative-pool-meta"><span>${esc((pool.categories||[]).map(c=>c.name+(c.enabled===false?'（已停用）':'')).join('、')||'未分类')}</span><span>原标签：${esc((row.labels||[]).join('、')||'无')}</span><span>加入：${esc(pool.joined_at||'未知')}</span><span>审核：${esc(reviewName(pool.review_status))}（不代表本次目标已确认无目标）</span><span>训练使用：${esc(usageName(pool.training_usage))}</span><small>${esc(id)}</small></div></article>`}).join('')||'<div class="empty">当前筛选没有素材</div>'}</div><footer class="row end">共 ${total} 张 · 第 ${page} / ${Math.max(1,Math.ceil(total/48))} 页 ${button('prev','上一页',page<=1?'disabled':'')}${button('next','下一页',page*48>=total?'disabled':'')}</footer></section>`;
  }
  function categoryHTML(){return `<section class="panel negative-pool"><header class="row between"><div><h2>负样本分类</h2><p>一级管理分类，不参与目标检测类别映射。删除分类只移除关联。</p></div>${button('create-category','新建分类')}</header><form class="row" data-np-form="category-search"><input class="input" name="query" placeholder="搜索分类" value="${esc(filters.categoryQuery||'')}"><button class="btn" type="submit">搜索</button></form><div class="negative-pool-category-list">${categories.map(c=>`<article class="row between"><div><b>${esc(c.name)}</b> · ${Number(c.material_count||0)} 张 · ${c.enabled?'启用':'停用'}</div><div class="row">${button('edit-category','编辑',`data-id="${esc(c.id)}"`)}${button('toggle-category',c.enabled?'停用':'启用',`data-id="${esc(c.id)}"`)}${button('delete-category','删除',`data-id="${esc(c.id)}"`)}</div></article>`).join('')||'<div class="empty">暂无分类</div>'}</div></section>`}
  function dialog(title,body,submit){const projectId=String(pid()),originPage=getState().page;const layer=modal(title,`<form id="negativePoolDialog" class="negative-pool-dialog">${body}<div class="row end"><button type="button" class="btn" data-np-cancel>取消</button><button class="btn primary" type="submit">确认</button></div><div role="alert" data-np-error></div></form>`,true);const form=document.getElementById('negativePoolDialog');form.querySelector('[data-np-cancel]').onclick=()=>window.closeModalLayer424(layer);form.onsubmit=async e=>{e.preventDefault();const btn=form.querySelector('[type=submit]');btn.disabled=true;try{if(String(pid())!==projectId)throw Error('项目已变化，请重新操作');await submit(new FormData(form));if(!form.isConnected||String(pid())!==projectId)return;window.closeModalLayer424(layer);if(getState().page===originPage){if(originPage==='标签管理')await window.renderLabelManagement414();else if(originPage==='数据集')await window.renderDatasets424()}}catch(error){if(form.isConnected)form.querySelector('[data-np-error]').textContent=error.message||String(error)}finally{if(form.isConnected)btn.disabled=false}}}
  const write=(path,body,method='POST')=>api(base()+path,{method,headers:{'Content-Type':'application/json'},...(body?{body:JSON.stringify(body)}:{})});
  function requireSelection(){if(!selected.size)throw Error('请先选择素材');return [...selected]}
  async function action(name,id){resetProject();
    if(['materials','pool'].includes(name)){active=name;return window.renderDatasets424()}
    if(['positive','categories'].includes(name)){labelTab=name;return window.renderLabelManagement414()}
    if(name==='retry')return load(getState().page==='标签管理'?'categories':'pool');
    if(name==='reset'){filters={};page=1;return load('pool')}
    if(name==='prev'||name==='next'){page+=name==='prev'?-1:1;return load('pool')}
    if(name==='preview')return window.previewData429(id,rows.find(x=>String(x.id)===id));
    if(name==='clear'){selected.clear();return load('pool')}
    if(name==='page-select'){rows.forEach(x=>selected.add(String(x.id)));return load('pool')}
    if(name==='all-select'){const token=epoch,projectId=String(pid()),result=await api(base()+'/ids?'+negativePoolQuery(filters));if(token!==epoch||String(pid())!==projectId||active!=='pool'||getState().page!=='数据集')return;selected=new Set((result.items||[]).map(String));return load('pool')}
    if(name==='draft'){const ids=requireSelection();if(!addToDraft)throw Error('请先打开原创建训练窗口建立训练草稿');await addToDraft(ids);toast(`已将 ${ids.length} 张素材加入训练草稿`);return}
    if(name==='join'){dialog('加入负样本池','<label>已有素材 ID（逗号或换行分隔）<textarea class="input" name="ids" required></textarea></label><p>复用已有原图与标注；加入池不自动确认无目标。</p>',data=>write('/members',{image_ids:String(data.get('ids')).split(/[\s,，]+/).filter(Boolean),action:'add'}));return}
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
  document.addEventListener('submit',e=>{const kind=e.target.dataset?.npForm;if(!kind)return;e.preventDefault();const data=new FormData(e.target);if(kind==='category-search'){filters.categoryQuery=String(data.get('query')||'');void load('categories');return}filters=Object.fromEntries(['query','joined_days','joined_from','joined_to','review_status'].map(key=>[key,String(data.get(key)||'')]));filters.category_id=data.getAll('category_id');filters.label=data.getAll('label');page=1;void load('pool')});
  function decorateOriginal(kind){
    resetProject();epoch++;
    const host=view();if(!host)return;
    if(!host.querySelector('.negative-pool-tabs'))host.insertAdjacentHTML('afterbegin',tabs(kind));
    if(kind==='materials')host.querySelectorAll('[data-material-id]').forEach(card=>{const actions=card.querySelector('.data426-actions');if(actions&&!actions.querySelector('[data-np]'))actions.insertAdjacentHTML('beforeend',button('join-one','加入负样本池',`data-id="${esc(card.dataset.materialId)}"`))});
  }
  window.NegativePoolRuntime={
    renderTabs:tabs,
    active(kind){resetProject();return kind==='materials'?active==='pool':labelTab==='categories'},
    renderPool:kind=>load(kind==='materials'?'pool':'categories'),
    decorateOriginal,
    refresh:()=>load(getState().page==='标签管理'?'categories':'pool'),
    open:()=>action('pool'),getSelected:()=>[...selected]
  };
  return window.NegativePoolRuntime;
}
