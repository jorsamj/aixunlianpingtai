import {withRequestDeadline} from './api.js?v=20261021s';
import {materialBatchTaskText, isMaterialBatchActive} from './material-batches.js?v=422411';
import {loadingSkeleton} from './modal.js?v=20261021';

const escape = value => String(value ?? '').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const types = {visual_similarity:'视觉相似',same_sha_reference:'同内容引用',cross_split_leakage:'冻结划分泄漏',suspected_annotation:'疑似错标',unverified:'未检查'};
const checks = {visual_similarity:'视觉相似性',leakage:'冻结划分泄漏',mistakenness:'疑似错标',hardness:'困难度'};
export function auditSelection({scope='FILTERED',filters={},imageIds=[],pageIds=[]}={}) {
  if(scope==='ALL') return {scope:'FILTERED',filters:{}};
  if(scope==='SELECTED'||scope==='CURRENT_PAGE') {
    const ids=[...new Set((scope==='CURRENT_PAGE'?pageIds:imageIds).map(String).filter(Boolean))];
    if(!ids.length) throw new Error('请先选择素材');
    return {scope,image_ids:ids};
  }
  return {scope:'FILTERED',filters};
}
export function auditCheckText(check={}) {
  if(check.status==='completed') return `已检查${check.checked==null?'':` · ${Number(check.checked)} 张`}`;
  if(check.status==='partial') return `部分检查${check.checked==null?'':` · ${Number(check.checked)} 张`}${check.not_checked==null?'':` · ${Number(check.not_checked)} 张未检查`}`;
  return ({not_checked:'未检查',unknown:'未知',risk:'有风险',partial:'部分检查',failed:'失败'})[check.status]||'未检查';
}
export function annotationSummaryText(summary={}) {
  const value=key=>summary[key]==null?'未检查':String(summary[key]);
  return `疑似标注异常 ${value('suspected_images')} 张 · 疑似漏标 ${value('possible_missing_boxes')} 框 · 疑似多标 ${value('possible_spurious_boxes')} 框 · 类别差异 ${value('class_difference_images')} 张 · 定位偏差 ${value('location_difference_images')} 张 · 标注证据未覆盖 ${value('annotation_not_checked_images')} 张 · 待复核 ${value('pending_candidates')} 条 · 已确认问题或修正 ${value('confirmed_candidates')} 条 · 标签冲突：由原 Full Audit 核验`;
}

// Presentation only: submission, durable identity and polling remain MaterialBatchRuntime62's.
export function installSmartMaterialAudit({getState,api,modal,notify}={}) {
  let view=null, sequence=0, reviewIntent=null;
  const state=()=>getState()||{};
  const pid=()=>String(state().project?.id||'');
  const tell=message=>(notify||window.toast)?.(message);
  const base=project=>`/api/v62/projects/${encodeURIComponent(project)}/smart-material-audit`;
  const post=body=>({method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
  const active=v=>view===v&&v.root.isConnected&&v.project===pid()&&!v.controller.signal.aborted;
  const request=(v,url,options={})=>withRequestDeadline(signal=>api(url,{...options,signal}),{signal:v.controller.signal,timeoutMs:30000,label:'智能质量分析'});
  function dispose(v) {v.controller.abort();for(const editor of v.editors||[])editor.destroy();if(view===v)view=null;}
  function message(v,value,error=false) {if(active(v)){const box=v.root.querySelector('[data-status]');box.textContent=value;box.setAttribute('role',error?'alert':'status');}}
  function buttons(v,busy) {v.busy=busy;v.root.querySelectorAll('[data-write]').forEach(b=>{b.disabled=busy||!v.enabled;b.setAttribute('aria-busy',String(busy));});}
  async function action(v,work) {if(!active(v)||v.busy)return;buttons(v,true);try{await work();}catch(e){if(active(v))message(v,e.message||e,true);}finally{if(active(v))buttons(v,false);}}
  function taskChanged(v,task) {
    if(!active(v)||task.project_id!==v.project||task.operation!=='SMART_AUDIT')return;
    if(v.desiredTaskId&&task.task_id!==v.desiredTaskId)return;
    if(v.task&&v.task.task_id!==task.task_id)return;
    if(v.task?.updated_at&&task.updated_at<v.task.updated_at)return;
    const wasActive=!v.task||isMaterialBatchActive(v.task),oldAttempt=v.task?.attempt;
    const resultsCleared=Boolean(v.task?.result_ready&&!task.result_ready);
    v.task=task;
    const progress=task.smart_audit_progress||{};
    const phase=({smart_inputs:'只读核验输入',smart_features:'提取图像特征',smart_similarity:'计算视觉相似性',smart_mistakenness:'核验错标证据',smart_engine:'隔离引擎处理中'})[progress.stage||task.phase]||task.phase||'';
    const elapsed=task.smart_audit_summary?.elapsed_seconds;
    message(v,`${materialBatchTaskText(task)} · 已处理 ${Number(task.processed||0)}/${Number(task.total||0)} · 成功 ${Number(task.succeeded||0)} · 失败 ${Number(task.failed||0)} · 未处理 ${Math.max(0,Number(task.total||0)-Number(task.processed||0))}${elapsed==null?'':` · 处理耗时 ${elapsed} 秒`} · ${phase}${progress.scanned==null?'':` · 特征已读取 ${progress.scanned}/${progress.total}（不是整项任务完成度）`}`);
    v.root.querySelector('[data-cancel]').hidden=!isMaterialBatchActive(task);
    v.root.querySelector('[data-retry]').hidden=!['FAILED','CANCELLED','PARTIAL_SUCCESS','BLOCKED_BY_ENVIRONMENT','BLOCKED_BY_HARDWARE'].includes(task.status);
    v.root.querySelector('[data-checks]').innerHTML=Object.entries(task.smart_audit_summary?.checks||{}).map(([key,check])=>`<span title="${escape(check.reason||'')}">${escape(checks[key]||key)}：<b>${escape(auditCheckText(check))}</b></span>`).join('');
    if(oldAttempt!==task.attempt||resultsCleared) {resetResults(v);}
    if(!isMaterialBatchActive(task)&&(wasActive||oldAttempt!==task.attempt)&&task.result_ready) void findings(v);
  }
  function resetResults(v) {v.offset=0;v.detailSequence++;v.listSequence++;v.item=null;for(const editor of v.editors||[])editor.destroy();v.editors=[];for(const name of ['issues','detail','review'])v.root.querySelector(`[data-${name}]`).replaceChildren();v.root.querySelector('[data-annotation-summary]')?.remove();if(v.source==='labels'){const box=document.querySelector('[data-smart-audit-label-summary]');if(box)box.textContent='当前分析结果尚未读取，不使用旧任务计数。';}}
  async function chooseTask(v,id) {
    resetResults(v);v.task=null;v.desiredTaskId=id;
    const task=await request(v,`/api/v62/projects/${encodeURIComponent(v.project)}/material-batches/${encodeURIComponent(id)}`);
    if(!active(v)||v.desiredTaskId!==id)return;taskChanged(v,task);
    if(isMaterialBatchActive(task))window.MaterialBatchRuntime62.poll(task.task_id);
  }
  async function history(v,cursor='') {
    const page=await request(v,`/api/v62/projects/${encodeURIComponent(v.project)}/material-batches?limit=50${cursor?`&cursor=${encodeURIComponent(cursor)}`:''}`);
    if(!active(v))return;
    const items=(page.items||[]).filter(t=>t.operation==='SMART_AUDIT');
    const box=v.root.querySelector('[data-history]');
    box.innerHTML=items.map(task=>`<button class="btn" data-task="${escape(task.task_id)}">${escape(materialBatchTaskText(task))} · ${escape(task.created_at||task.task_id)}</button>`).join('')||'<span>本页没有智能分析任务</span>';
    if(page.next_cursor){const button=document.createElement('button');button.className='btn';button.textContent='更早记录';button.onclick=()=>void action(v,()=>history(v,page.next_cursor));box.append(button);}
    box.querySelectorAll('[data-task]').forEach(b=>b.onclick=()=>void action(v,()=>chooseTask(v,b.dataset.task)));
    if(!v.task&&items.length)await chooseTask(v,items[0].task_id);
  }
  async function findings(v) {
    if(!v.task)return;
    const id=v.task.task_id,attempt=v.task.attempt,token=++v.listSequence;
    try {
      const page=await request(v,`${base(v.project)}/${encodeURIComponent(id)}/findings?limit=25&offset=${v.offset}&issue_type=${encodeURIComponent(v.filter)}`);
      if(!active(v)||v.task.task_id!==id||v.task.attempt!==attempt||page.generation!==attempt||token!==v.listSequence)return;
      v.total=page.total;
      let summary=v.root.querySelector('[data-annotation-summary]');
      if(!summary){summary=document.createElement('p');summary.dataset.annotationSummary='';v.root.querySelector('[data-checks]').after(summary);}
      summary.textContent=annotationSummaryText(page.annotation_summary);
      const labelSummary=document.querySelector('[data-smart-audit-label-summary]');
      if(labelSummary&&v.source==='labels')labelSummary.textContent=`Task ${id} · ${annotationSummaryText(page.annotation_summary)}`;
      v.root.querySelector('[data-count]').textContent=`候选 ${page.total} 条 · 第 ${Math.floor(v.offset/25)+1} 页 · 人工复核 ${Object.entries(page.review_counts||{}).map(([k,n])=>`${({confirmed_issue:'确认问题',no_issue:'无需修改',corrected:'已修正',unknown:'待确认',stale:'已失效'})[k]||k} ${n}`).join(' / ')}`;
      v.root.querySelector('[data-issues]').innerHTML=page.items.map(item=>`<button class="sma-issue" data-issue="${escape(item.issue_id)}"><b>${escape(types[item.issue_type]||item.issue_type)}</b><span>${escape(item.image_id)}${item.related_image_id?` ↔ ${escape(item.related_image_id)}`:''}</span><small>${item.stale?'证据已变化，需复核':item.review_valid?'已人工复核':'待人工复核'}</small></button>`).join('')||'<p>当前筛选没有候选。未检查项仍保持未检查，不代表全库无问题。</p>';
      v.root.querySelectorAll('[data-issue]').forEach(b=>b.onclick=()=>void action(v,()=>detail(v,b.dataset.issue)));
      v.root.querySelectorAll('[data-issue]').forEach(button=>{const item=page.items.find(row=>row.issue_id===button.dataset.issue),img=document.createElement('img');img.src=`/api/v61/projects/${encodeURIComponent(v.project)}/materials/${encodeURIComponent(item.image_id)}/content/thumbnail?edge=128`;img.alt=item.inputs?.[item.image_id]?.filename||item.image_id;img.loading='lazy';img.width=80;img.height=54;img.style.objectFit='contain';img.onerror=()=>{img.remove();const hint=document.createElement('small');hint.textContent='缩略图暂不可用，可查看原图';button.append(hint);};button.prepend(img);});
      v.root.querySelector('[data-prev]').disabled=v.offset===0;v.root.querySelector('[data-next]').disabled=v.offset+25>=page.total;
      if(page.items.length)await detail(v,page.items[0].issue_id);
    }catch(e){if(active(v)&&token===v.listSequence)message(v,e.message||e,true);}
  }
  async function detail(v,id) {
    const token=++v.detailSequence,taskId=v.task.task_id,attempt=v.task.attempt;
    const item=await request(v,`${base(v.project)}/${encodeURIComponent(taskId)}/findings/${encodeURIComponent(id)}`);
    if(!active(v)||token!==v.detailSequence||v.task.task_id!==taskId||v.task.attempt!==attempt||item.generation!==attempt)return;
    v.item=item;for(const editor of v.editors||[])editor.destroy();v.editors=[];
    const imageUrl=image=>`/api/v61/projects/${encodeURIComponent(v.project)}/materials/${encodeURIComponent(image)}/content`;
    v.root.querySelector('[data-detail]').innerHTML=`<h3>${escape(types[item.issue_type]||item.issue_type)}</h3><p>${item.stale?'原图或 GT 证据已改变，请重新检查。':'建议仅供人工复核，不影响正式清洗或评测指标。'}</p><div class="sma-images">${[item.image_id,item.related_image_id].filter(Boolean).map(image=>`<figure><img src="${imageUrl(image)}" alt="${escape(image)}"><figcaption>${escape(image)}</figcaption></figure>`).join('')}</div><div class="row"><button class="btn" data-open-annotation>打开原标注工作台</button><button class="btn" data-open-evaluation>高级评测与困难样本</button></div>`;
    v.root.querySelectorAll('[data-detail] img').forEach((img,index)=>{const imageId=[item.image_id,item.related_image_id][index];img.onerror=()=>{img.alt='原图暂不可用；点击重试';img.onclick=()=>{img.src=imageUrl(imageId)};};});
    const figures=[...v.root.querySelectorAll('[data-detail] figure')];
    for(const [index,figure] of figures.entries()) {
      const imageId=[item.image_id,item.related_image_id][index],facts=item.inputs?.[imageId];
      if(!facts||item.stale)continue; // Never overlay stale frozen boxes onto changed current pixels.
      const img=figure.querySelector('img'),viewport=document.createElement('div'),world=document.createElement('div'),tools=document.createElement('div');
      viewport.className='sma-viewport';world.className='sma-world';img.replaceWith(viewport);viewport.append(world);world.append(img);
      tools.className='row';tools.innerHTML='<label><input type="checkbox" data-gt checked> GT</label><label><input type="checkbox" data-pred checked> 预测</label><button class="btn" data-zoom="1" aria-label="放大">＋</button><button class="btn" data-zoom="-1" aria-label="缩小">−</button><button class="btn" data-fit>适应窗口</button>';figure.append(tools);
      const start=async()=>{
        try {
          if(!active(v)||token!==v.detailSequence)return;
          const {createAnnotoriousEditor}=await import('./annotorious-editor.js?v=20261022a');
          if(!active(v)||token!==v.detailSequence)return;
          const boxes=()=>[['gt_boxes','gt'],['pred_boxes','pred']].flatMap(([key,prefix])=>tools.querySelector(`[data-${prefix}]`).checked?(facts[key]||[]).map((box,i)=>({...box,id:`${prefix}-${i}`})):[]);
          const editor=await createAnnotoriousEditor({image:img,viewport,world,getBoxes:boxes,getLabels:()=>state().labels||[],isActive:()=>active(v)&&token===v.detailSequence,signal:v.controller.signal,onError:e=>message(v,e.message||e,true)});
          if(!active(v)||token!==v.detailSequence){editor.destroy();return;}
          editor.setMode('pan');editor.sync({locked:true});v.editors.push(editor);
          tools.querySelectorAll('input').forEach(input=>input.onchange=()=>editor.sync({locked:true}));
          tools.querySelectorAll('[data-zoom]').forEach(b=>b.onclick=()=>editor.zoom(Number(b.dataset.zoom)*.15));tools.querySelector('[data-fit]').onclick=()=>editor.fit();
        }catch(e){if(active(v)&&token===v.detailSequence)message(v,`图片可查看；框预览暂不可用：${e.message||e}`,true);}
      };
      if(img.complete&&img.naturalWidth)void start();else img.onload=()=>void start();
    }
    v.root.querySelector('[data-review]').innerHTML=`<h3>证据与人工复核</h3><pre>${escape(JSON.stringify(item.evidence,null,2))}</pre><p>原 GT、预测及复核身份均绑定当前图片内容。此处不自动改标注、删除素材或训练。</p><textarea class="input" data-note maxlength="1000" placeholder="复核备注"></textarea><div class="sma-verdicts"><button class="btn" data-verdict="confirmed_issue">确认存在问题</button><button class="btn" data-verdict="no_issue">无需修改</button><button class="btn" data-verdict="unknown">暂无法确认</button></div>`;
    const raw=v.root.querySelector('[data-review] pre'),evidence=item.evidence||{},reason=document.createElement('p');
    reason.textContent=[evidence.possible_missing>0?`疑似漏标 ${evidence.possible_missing} 框`:'',evidence.possible_spurious>0?`疑似多标 ${evidence.possible_spurious} 框`:'',evidence.mistakenness>.5?'疑似类别差异':'',evidence.mistakenness_loc>.5?'疑似框位置偏差':'',Number.isFinite(evidence.distance)?`单位特征距离 ${evidence.distance.toFixed(4)}（越小越近，不是百分比）`:'',evidence.reason||''].filter(Boolean).join('；')||'需人工核验，不能据此自动判定正式错误。';raw.before(reason);
    const source=document.createElement('p');source.textContent=`来源批次：${item.inputs?.[item.image_id]?.source_batch_id||'未记录'}`;raw.before(source);
    const disclosure=document.createElement('details'),title=document.createElement('summary');title.textContent='查看分析证据';raw.replaceWith(disclosure);disclosure.append(title,raw);
    if(item.review){const receipt=document.createElement('p'),names={confirmed_issue:'确认存在问题',no_issue:'无需修改',corrected:'已修正',unknown:'暂无法确认'};receipt.textContent=`最近复核：${names[item.review.verdict]||'未知'} · ${item.review.actor_id||'未记录人员'} · ${item.review.reviewed_at||''}${item.review_valid?'':'（已失效，需重新核验）'}${item.review.note?` · ${item.review.note}`:''}`;disclosure.after(receipt);}
    v.root.querySelectorAll('[data-verdict]').forEach(b=>b.onclick=()=>void action(v,async()=>{
      if(v.task.task_id!==taskId||v.task.attempt!==attempt||v.item!==item)throw new Error('分析结果已切换，请重新核验');
      await request(v,`${base(v.project)}/${encodeURIComponent(taskId)}/findings/${encodeURIComponent(id)}/review`,post({verdict:b.dataset.verdict,expected_generation:attempt,expected_review_token:item.review_token,note:v.root.querySelector('[data-note]').value}));
      if(active(v))await findings(v);
    }));
    v.root.querySelector('[data-open-evaluation]').onclick=async()=>{window.closeModalLayer424?.(v.layer);await window.setPage('质量中心');window.setQualityCenterTab411?.('advanced');};
    v.root.querySelector('[data-open-annotation]').onclick=()=>void action(v,async()=>{
      const originalQueue=state().annotationQueue414,queue=[item.image_id];
      state().annotationQueue414=queue;
      const intent={project:v.project,taskId,attempt,issueId:id,imageId:item.image_id,originalQueue,queue,workbench:null};reviewIntent=intent;
      try {const opened=await window.openAnnotation(item.image_id);if(opened===false||pid()!==v.project||String(state().activeImage?.id)!==item.image_id)throw new Error('原标注工作台未就绪，请稍后重试');if(reviewIntent===intent)intent.workbench=state().annotationWorkbench;}
      catch(error){if(state().annotationQueue414===queue)state().annotationQueue414=originalQueue;reviewIntent=null;throw error;}
    });
  }
  async function open({imageIds=[],projectId=pid(),source='materials'}={}) {
    if(!projectId||String(projectId)!==pid())throw new Error('项目已切换，请重新打开');
    if(view){window.closeModalLayer424?.(view.layer);dispose(view);}
    const root=document.createElement('section');root.className='smart-material-audit';root.dataset.smartAudit=String(++sequence);
    root.innerHTML=`<div data-status role="status">${loadingSkeleton({kind:'cards',rows:2})}</div><div class="sma-toolbar"><label>分析范围 <select class="select" data-scope><option value="FILTERED">全部筛选结果</option><option value="ALL">整个项目</option><option value="SELECTED">已选素材</option><option value="CURRENT_PAGE">当前页（明确限定）</option></select></label><button class="btn" data-write data-estimate disabled>预览范围</button><button class="btn primary" data-write data-create disabled>创建只读分析</button><button class="btn" data-cancel hidden>取消分析</button><button class="btn" data-write data-retry hidden>重试原任务</button><button class="btn" data-refresh>刷新结果</button></div><details><summary>可选模型与历史记录</summary><p>不选择可信评测版本时，错标和冻结划分泄漏保持未检查。HOG/颜色特征补充视觉相似性，不代替原 SHA/dHash/OpenCV 清洗。</p><select class="select" data-model><option value="">不使用模型证据</option></select><button class="btn" data-model-more hidden>更多模型</button><div data-history></div></details><div class="sma-checks" data-checks></div><div class="sma-summary"><select class="select" data-filter><option value="">全部候选</option>${Object.entries(types).map(([key,name])=>`<option value="${key}">${name}</option>`).join('')}</select><span data-count>尚未读取分析结果</span><button class="btn" data-prev disabled>上一页</button><button class="btn" data-next disabled>下一页</button></div><div class="sma-columns"><aside data-issues></aside><main data-detail><p>请选择分析任务。未检查记录不会默认为正常。</p></main><aside data-review></aside></div>`;
    const layer=modal('智能素材质量分析',root.outerHTML,true);
    const mounted=layer?.querySelector('[data-smart-audit]')||document.querySelector(`[data-smart-audit="${sequence}"]`);
    const v={root:mounted,layer,project:String(projectId),source,controller:new AbortController(),enabled:false,busy:false,task:null,offset:0,total:0,filter:'',detailSequence:0,listSequence:0,imageIds:imageIds.length?imageIds:(window.materialSelectedIds61?.()||[])};view=v;
    if(imageIds.length)v.root.querySelector('[data-scope]').value='SELECTED';
    const selection=()=>auditSelection({scope:v.root.querySelector('[data-scope]').value,imageIds:v.imageIds,filters:window.materialBatchFilters61?.()||{},pageIds:window.materialCurrentPageIds61?.()||[]});
    const estimate=()=>request(v,`${base(v.project)}/estimate`,post({selection_spec:selection()}));
    v.root.querySelector('[data-estimate]').onclick=()=>void action(v,async()=>{const result=await estimate();message(v,`本次只读检查 ${result.count} 张；不改原图、GT 或清洗结果`);});
    v.root.querySelector('[data-create]').onclick=()=>void action(v,async()=>{
      let payload=window.MaterialBatchRuntime62.pendingSmart()?.payload;
      if(!payload){const result=await estimate();if(!active(v))return;if(!window.confirm(`只读分析 ${result.count} 张素材。智能建议不自动修改 GT 或删除素材，确认创建？`))return;
        const model=v.root.querySelector('[data-model]'),option=model.selectedOptions[0];
        payload={selection_spec:result.selection_spec,options:{request_id:crypto.randomUUID(),...(option.dataset.algorithm?{algorithm_id:option.dataset.algorithm,version_id:option.value}:{})}};
      }
      const task=await window.MaterialBatchRuntime62.submitSmart(payload);if(active(v)){v.task=null;v.desiredTaskId=task.task_id;taskChanged(v,task);}
    });
    v.root.querySelector('[data-cancel]').onclick=()=>void action(v,()=>window.cancelMaterialBatch62(v.task.task_id));
    v.root.querySelector('[data-retry]').onclick=()=>void action(v,async()=>{const task=await request(v,`${base(v.project)}/${encodeURIComponent(v.task.task_id)}/retry`,post({}));if(active(v)){taskChanged(v,task);window.MaterialBatchRuntime62.poll(task.task_id);}});
    v.root.querySelector('[data-refresh]').onclick=()=>void action(v,()=>v.task?chooseTask(v,v.task.task_id):history(v));
    v.root.querySelector('[data-filter]').onchange=event=>{v.filter=event.target.value;v.offset=0;void findings(v);};
    for(const [name,delta]of[['prev',-25],['next',25]])v.root.querySelector(`[data-${name}]`).onclick=()=>{v.offset=Math.max(0,v.offset+delta);void findings(v);};
    async function models(cursor='') {const page=await request(v,`${base(v.project)}/models?limit=25&cursor=${encodeURIComponent(cursor)}`);if(!active(v))return;const select=v.root.querySelector('[data-model]');for(const item of page.items||[]){const option=document.createElement('option');option.value=item.version_id;option.dataset.algorithm=item.algorithm_id;option.textContent=item.label;select.append(option);}const more=v.root.querySelector('[data-model-more]');more.hidden=!page.next_cursor;more.onclick=()=>void action(v,()=>models(page.next_cursor));}
    try {const status=await request(v,`${base(v.project)}/status`);if(!active(v))return;v.enabled=status.enabled;buttons(v,false);message(v,status.message||`只读分析已启用 · 单次上限 ${status.max_images} 张`);if(v.enabled)await models();await history(v);}
    catch(e){if(active(v))message(v,e.message||e,true);}
    return v;
  }
  const runtime={open,onTask(task){if(view)taskChanged(view,task);},beforeModalClose(layer){if(view&&(layer===view.layer||layer.contains(view.root)))dispose(view);if(reviewIntent&&layer.querySelector('.ann420-stable'))reviewIntent=null;},async onAnnotationSaved(project,imageId,workbench){
    const intent=reviewIntent;if(!intent||intent.project!==project||intent.imageId!==imageId||intent.workbench!==workbench||pid()!==project)return;
    try {const recorded=await withRequestDeadline(async signal=>{const item=await api(`${base(project)}/${encodeURIComponent(intent.taskId)}/findings/${encodeURIComponent(intent.issueId)}`,{signal});if(reviewIntent!==intent||pid()!==project)return false;if(item.generation!==intent.attempt)throw new Error('分析代际已变化');await api(`${base(project)}/${encodeURIComponent(intent.taskId)}/findings/${encodeURIComponent(intent.issueId)}/review`,{...post({verdict:'corrected',expected_generation:intent.attempt,expected_review_token:item.review_token}),signal});return true;},{timeoutMs:30000,label:'人工复核回执'});if(recorded&&pid()===project){tell('标注已保存，分析复核回执已更新');if(view?.task?.task_id===intent.taskId&&view.task.attempt===intent.attempt)void findings(view);}}
    catch(_){if(pid()===project)tell('标注已保存；分析复核回执未更新，可在智能分析中重新核验');}
  }};
  window.SmartMaterialAuditRuntime=runtime;
  window.openSmartMaterialAudit=options=>open(options).catch(error=>tell(error.message||error));
  return runtime;
}
